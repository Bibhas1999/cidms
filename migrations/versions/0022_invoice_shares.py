"""The patient's public link to a bill (the QR code on it), the same design as a report's (report_shares):
only the token's SHA-256 is kept, opening it needs a check (mobile/birth year/bill number), and it can be
revoked or reissued.

Revision ID: 0022_invoice_shares
Revises: 0021_revert_work_areas
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0022_invoice_shares"
down_revision = "0021_revert_work_areas"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
ID = UUID(as_uuid=True)
BEFORE = ["tenant_settings", "counters", "departments", "test_types", "tests", "report_templates", "referring_doctors",
          "patients", "invoices", "invoice_items", "payments", "test_reports", "test_report_versions", "report_shares",
          "message_deliveries", "imaging_studies", "doctor_signatures"]
AFTER = [*BEFORE, "invoice_shares"]


def _restore_clear(tables: list[str]) -> None:
    """The restore's clearing function as 0016 made it, for this list of tables."""
    deletes = "\n".join(f"  DELETE FROM {t} WHERE tenant_id = p_tenant;" for t in reversed(tables))
    op.execute(f"""CREATE OR REPLACE FUNCTION client_restore_clear(p_tenant uuid) RETURNS void
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


def upgrade() -> None:
    op.create_table(
        "invoice_shares",
        sa.Column("id", ID, primary_key=True),
        sa.Column("tenant_id", ID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invoice_id", ID, sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by", ID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_viewed_at", TS),
        sa.Column("failed_checks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", TS),
        sa.UniqueConstraint("token_hash", name="uq_invoice_shares_token"),
    )
    op.create_index("ix_invoice_shares_invoice", "invoice_shares", ["invoice_id", sa.text("created_at DESC")])
    op.execute("ALTER TABLE invoice_shares ENABLE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY client_rows ON invoice_shares
                   USING (app_is_platform() OR tenant_id = app_tenant())
                   WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    _restore_clear(AFTER)


def downgrade() -> None:
    _restore_clear(BEFORE)
    op.drop_table("invoice_shares")
