"""Removes the work areas and the OPD (0020_work_areas): the feature was taken out again before any centre
depended on it. Drops staff_areas, opd_doctors and opd_visits, and puts the client restore function back as 0020
found it.

Revision ID: 0021_revert_work_areas
Revises: 0020_work_areas
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0021_revert_work_areas"
down_revision = "0020_work_areas"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
ID = UUID(as_uuid=True)
BEFORE = ["tenant_settings", "counters", "departments", "test_types", "tests", "report_templates", "referring_doctors",
          "patients", "invoices", "invoice_items", "payments", "test_reports", "test_report_versions", "report_shares",
          "message_deliveries", "imaging_studies", "doctor_signatures"]
AFTER = [*BEFORE, "staff_areas", "opd_doctors", "opd_visits"]


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
    _restore_clear(BEFORE)
    op.drop_table("opd_visits")
    op.drop_table("opd_doctors")
    op.drop_table("staff_areas")


def downgrade() -> None:
    op.create_table(
        "staff_areas",
        sa.Column("id", ID, primary_key=True),
        sa.Column("tenant_id", ID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", ID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("area", sa.String(12), nullable=False),
        sa.Column("department_id", ID, sa.ForeignKey("departments.id", ondelete="CASCADE")),
        sa.CheckConstraint("area IN ('reception', 'opd', 'department')", name="ck_staff_areas_area"),
        sa.CheckConstraint("(area = 'department') = (department_id IS NOT NULL)", name="ck_staff_areas_department"),
    )
    op.create_index("ix_staff_areas_user", "staff_areas", ["user_id"])
    op.execute("CREATE UNIQUE INDEX uq_staff_areas ON staff_areas "
               "(user_id, area, coalesce(department_id, '00000000-0000-0000-0000-000000000000'::uuid))")

    op.create_table(
        "opd_doctors",
        sa.Column("id", ID, primary_key=True),
        sa.Column("tenant_id", ID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("qualification", sa.String(200), nullable=False, server_default=""),
        sa.Column("fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("fee >= 0", name="ck_opd_doctors_fee"),
    )
    op.execute("CREATE UNIQUE INDEX uq_opd_doctors_name ON opd_doctors (tenant_id, lower(name))")

    op.create_table(
        "opd_visits",
        sa.Column("id", ID, primary_key=True),
        sa.Column("tenant_id", ID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visit_date", sa.Date, nullable=False),
        sa.Column("token_no", sa.Integer, nullable=False),
        sa.Column("doctor_id", ID, sa.ForeignKey("opd_doctors.id"), nullable=False),
        sa.Column("patient_id", ID, sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("invoice_id", ID, sa.ForeignKey("invoices.id")),
        sa.Column("fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(12), nullable=False, server_default="waiting"),
        sa.Column("cancel_reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_by", ID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("called_at", TS),
        sa.Column("done_at", TS),
        sa.CheckConstraint("status IN ('waiting', 'with_doctor', 'done', 'cancelled')", name="ck_opd_visits_status"),
        sa.CheckConstraint("fee >= 0", name="ck_opd_visits_fee"),
        sa.UniqueConstraint("tenant_id", "doctor_id", "visit_date", "token_no", name="uq_opd_visits_token"),
    )
    op.create_index("ix_opd_visits_day", "opd_visits", ["tenant_id", "visit_date"])

    for table in ("staff_areas", "opd_doctors", "opd_visits"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY client_rows ON {table}
                       USING (app_is_platform() OR tenant_id = app_tenant())
                       WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    op.execute("REVOKE DELETE ON opd_doctors, opd_visits FROM supreme_app")
    _restore_clear(AFTER)
