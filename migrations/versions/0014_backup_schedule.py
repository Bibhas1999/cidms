"""Backups the platform owner sets up in the app: on or off, the time of day, how often, and how long copies are
kept, plus a "Back up now" request. The server's cron (deploy/backup.sh --if-due, every 5 minutes) asks the app
whether a backup is due and records how each one went. Both tables are platform-only.

Revision ID: 0014_backup_schedule
Revises: 0013_clear_logo_backgrounds
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0014_backup_schedule"
down_revision = "0013_clear_logo_backgrounds"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "backup_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("every_days", sa.Integer, nullable=False, server_default="1"),
        sa.Column("at_time", sa.String(5), nullable=False, server_default="23:00"),
        sa.Column("keep_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("next_run_at", TS),
        sa.Column("requested_at", TS),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "backup_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("trigger", sa.String(10), nullable=False),
        sa.Column("scheduled_for", TS),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
        sa.Column("status", sa.String(10), nullable=False, server_default="running"),
        sa.Column("file", sa.String(200), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("message", sa.String(500), nullable=False, server_default=""),
    )
    op.create_index("ix_backup_runs_started_at", "backup_runs", ["started_at"])
    for table in ("backup_settings", "backup_runs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY platform_only ON {table} USING (app_is_platform()) WITH CHECK (app_is_platform())")


def downgrade() -> None:
    op.drop_table("backup_runs")
    op.drop_table("backup_settings")
