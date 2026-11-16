"""Restoring a client's backup no longer deletes anything first: it merges the copy's rows into the current
ones (a matching row is overwritten, a row made since the copy was taken is left alone). The one function
that could bypass the "nothing here is ever deleted" rule - used only by that old delete-then-restore step -
is no longer called, so it's dropped.

Revision ID: 0026_drop_restore_clear
Revises: 0025_invoice_search_indices
Create Date: 2026-11-17
"""

from alembic import op

revision = "0026_drop_restore_clear"
down_revision = "0025_invoice_search_indices"
branch_labels = None
depends_on = None

# The tables client_restore_clear(p_tenant) was deleting from, as of 0022 (parents first; this undoes it in reverse).
RESTORED = ["tenant_settings", "counters", "departments", "test_types", "tests", "report_templates", "referring_doctors",
            "patients", "invoices", "invoice_items", "payments", "invoice_shares", "test_reports", "test_report_versions",
            "report_shares", "message_deliveries", "imaging_studies", "doctor_signatures"]


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS client_restore_clear(uuid)")


def downgrade() -> None:
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
