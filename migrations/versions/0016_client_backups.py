"""Each client's own backups: a schedule set by the centre's owner (on or off, time of day, how often, how long
copies are kept) and the record of each copy, which the worker makes and restores (app/services/client_backups.py).
The copies themselves are files in the app's storage, one folder per client. Client tables (row-level security).

Revision ID: 0016_client_backups
Revises: 0015_offline_bills
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0016_client_backups"
down_revision = "0015_offline_bills"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
# A client's records that a restore puts back, parents first (as app/services/client_backups.TABLES).
RESTORED = ["tenant_settings", "counters", "departments", "test_types", "tests", "report_templates", "referring_doctors",
            "patients", "invoices", "invoice_items", "payments", "test_reports", "test_report_versions", "report_shares",
            "message_deliveries", "imaging_studies", "doctor_signatures"]


def upgrade() -> None:
    op.create_table(
        "client_backup_settings",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("every_days", sa.Integer, nullable=False, server_default="1"),
        sa.Column("at_time", sa.String(5), nullable=False, server_default="23:30"),
        sa.Column("keep_days", sa.Integer, nullable=False, server_default="30"),
        sa.Column("next_run_at", TS),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "client_backups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger", sa.String(10), nullable=False),          # scheduled | manual | restore
        sa.Column("status", sa.String(10), nullable=False, server_default="running"),  # running | ok | failed
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("requested_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("source_id", UUID(as_uuid=True)),                    # a restore: the copy it put back
        sa.Column("scheduled_for", TS),
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
        sa.Column("file", sa.String(200), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("schema_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("counts", JSONB, nullable=False, server_default="{}"),
        sa.Column("message", sa.String(500), nullable=False, server_default=""),
    )
    op.create_index("ix_client_backups_tenant_started", "client_backups", ["tenant_id", "started_at"])
    for table in ("client_backup_settings", "client_backups"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY client_rows ON {table}
                       USING (app_is_platform() OR tenant_id = app_tenant())
                       WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")

    # The app may never delete bills, payments, patients or reports (0002, 0008). A restore has to: this function,
    # run as the tables' owner, clears one client's records, and only while a restore of that client is running.
    deletes = "\n".join(f"  DELETE FROM {t} WHERE tenant_id = p_tenant;" for t in reversed(RESTORED))
    op.execute(f"""CREATE FUNCTION client_restore_clear(p_tenant uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT (app_is_platform() OR app_tenant() = p_tenant) THEN
    RAISE EXCEPTION 'client_restore_clear: not this client';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM client_backups WHERE tenant_id = p_tenant AND trigger = 'restore' AND status = 'running') THEN
    RAISE EXCEPTION 'client_restore_clear: no restore is running for this client';
  END IF;
{deletes}
END $$""")
    op.execute("REVOKE ALL ON FUNCTION client_restore_clear(uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION client_restore_clear(uuid) TO supreme_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS client_restore_clear(uuid)")
    op.drop_table("client_backups")
    op.drop_table("client_backup_settings")
