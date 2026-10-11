"""Background jobs (a queue in Postgres, run by `python -m app.worker`), files produced by jobs, the worker
scheduler's state, and in-app notifications with each person's preferences.

Row-level security: jobs, job files, notifications and preferences belong to one client (or, with a NULL
tenant_id, to the platform: only platform work sees those). The worker claims jobs with platform scope and runs
each one in a session scoped to the job's client. The scheduler's state and worker heartbeats are platform-only.

Revision ID: 0010_jobs_and_notifications
Revises: 0009_api_keys
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0010_jobs_and_notifications"
down_revision = "0009_api_keys"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
CLIENT_TABLES = ("jobs", "job_files", "notifications", "notification_preferences")
PLATFORM_TABLES = ("job_schedules", "job_workers")


def _tenant(nullable: bool = True):
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("last_error", sa.Text, nullable=False, server_default=""),
        sa.Column("locked_by", sa.String(120)),
        sa.Column("locked_at", TS),
        sa.Column("result", JSONB),
        sa.Column("dedupe_key", sa.String(200)),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed', 'cancelled')", name="ck_jobs_status"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts"),
    )
    op.create_index("ix_jobs_status_run_at", "jobs", ["status", "run_at"])
    op.create_index("ix_jobs_tenant_created", "jobs", ["tenant_id", sa.text("created_at DESC")])
    # One live job per (client, kind, key): enqueueing the same thing twice while it waits or runs is a no-op.
    op.execute("""CREATE UNIQUE INDEX uq_jobs_dedupe ON jobs (tenant_id, kind, dedupe_key) NULLS NOT DISTINCT
                  WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running')""")

    op.create_table(
        "job_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
    )
    op.create_index("ix_job_files_job", "job_files", ["job_id"])
    op.create_index("ix_job_files_expires", "job_files", ["expires_at"])

    op.create_table(
        "job_schedules",
        sa.Column("name", sa.String(60), primary_key=True),
        sa.Column("next_run_at", TS, nullable=False),
        sa.Column("last_run_at", TS),
    )
    op.create_table(
        "job_workers",
        sa.Column("worker_id", sa.String(120), primary_key=True),
        sa.Column("hostname", sa.String(200), nullable=False, server_default=""),
        sa.Column("pid", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("jobs_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("jobs_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(10), nullable=False, server_default="running"),  # running | stopped
    )

    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("link", sa.String(500), nullable=False, server_default=""),
        sa.Column("severity", sa.String(10), nullable=False, server_default="info"),
        sa.Column("read_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('info', 'success', 'warning', 'danger')", name="ck_notifications_severity"),
    )
    op.create_index("ix_notifications_user_time", "notifications", ["user_id", sa.text("created_at DESC")])
    op.execute("CREATE INDEX ix_notifications_unread ON notifications (user_id) WHERE read_at IS NULL")

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        _tenant(),
        sa.Column("muted_kinds", JSONB, nullable=False, server_default="[]"),
        sa.Column("browser_popups", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )

    for table in CLIENT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY client_rows ON {table}
                       USING (app_is_platform() OR tenant_id = app_tenant())
                       WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    for table in PLATFORM_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY platform_only ON {table} USING (app_is_platform()) WITH CHECK (app_is_platform())")


def downgrade() -> None:
    for table in ("notification_preferences", "notifications", "job_workers", "job_schedules", "job_files", "jobs"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
