"""Billing: departments, test types, tests, referring doctors, patients, bills, bill lines, payments,
running numbers and idempotent operations. Every table is per client, with row-level security.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
MONEY = sa.Numeric(12, 2)
TABLES = ("counters", "operations", "departments", "test_types", "tests", "referring_doctors", "patients",
          "invoices", "invoice_items", "payments")


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant(primary_key: bool = False):
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
                     primary_key=primary_key)


def _user(name: str):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"))


def upgrade() -> None:
    # Fast "contains" searches on names (patients, bills). pg_trgm is a trusted extension: the database owner may add it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column("tenant_settings", sa.Column("max_discount_percent", sa.Numeric(5, 2), nullable=False, server_default="20"))
    op.add_column("tenant_settings", sa.Column("bill_paper", sa.String(4), nullable=False, server_default="A5"))
    op.create_check_constraint("ck_settings_discount", "tenant_settings", "max_discount_percent BETWEEN 0 AND 100")
    op.create_check_constraint("ck_settings_paper", "tenant_settings", "bill_paper IN ('A4', 'A5')")

    op.create_table(
        "counters",
        _tenant(primary_key=True),
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("value", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.create_table(
        "operations",
        _tenant(primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("response", JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_operations_created_at", "operations", ["created_at"])

    op.create_table(
        "departments",
        _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("legacy_id", sa.Integer),
    )
    op.execute("CREATE UNIQUE INDEX uq_departments_name ON departments (tenant_id, lower(name))")
    op.create_table(
        "test_types",
        _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_imaging", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("legacy_id", sa.Integer),
    )
    op.execute("CREATE UNIQUE INDEX uq_test_types_name ON test_types (tenant_id, lower(name))")
    op.create_table(
        "tests",
        _id(), _tenant(),
        sa.Column("code", sa.String(20), nullable=False, server_default=""),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("test_type_id", UUID(as_uuid=True), sa.ForeignKey("test_types.id")),
        sa.Column("price", MONEY, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("legacy_id", sa.Integer),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("price >= 0", name="ck_tests_price"),
    )
    op.execute("CREATE UNIQUE INDEX uq_tests_name ON tests (tenant_id, lower(name))")
    op.execute("CREATE INDEX ix_tests_name_trgm ON tests USING gin (lower(name) gin_trgm_ops)")

    op.create_table(
        "referring_doctors",
        _id(), _tenant(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("qualification", sa.String(200), nullable=False, server_default=""),
        sa.Column("phone", sa.String(20), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.execute("CREATE UNIQUE INDEX uq_referring_doctors_name ON referring_doctors (tenant_id, lower(name))")

    op.create_table(
        "patients",
        _id(), _tenant(),
        sa.Column("patient_no", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("guardian_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("age_years", sa.Integer),
        sa.Column("date_of_birth", sa.Date),
        sa.Column("gender", sa.String(10), nullable=False),
        sa.Column("mobile", sa.String(20), nullable=False, server_default=""),
        sa.Column("email", sa.String(200), nullable=False, server_default=""),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("legacy_customer_ids", JSONB, nullable=False, server_default="[]"),
        _user("created_by"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "patient_no", name="uq_patients_no"),
        sa.CheckConstraint("gender IN ('male', 'female', 'other')", name="ck_patients_gender"),
        sa.CheckConstraint("age_years IS NULL OR age_years BETWEEN 0 AND 130", name="ck_patients_age"),
    )
    op.create_index("ix_patients_mobile", "patients", ["tenant_id", "mobile"])
    op.execute("CREATE INDEX ix_patients_name_trgm ON patients USING gin (lower(name) gin_trgm_ops)")

    op.create_table(
        "invoices",
        _id(), _tenant(),
        sa.Column("invoice_no", sa.String(40), nullable=False),
        sa.Column("legacy_no", sa.Integer),
        sa.Column("bill_date", sa.Date, nullable=False),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("patient_name", sa.String(200), nullable=False),
        sa.Column("patient_age", sa.String(20), nullable=False, server_default=""),
        sa.Column("patient_gender", sa.String(10), nullable=False, server_default=""),
        sa.Column("patient_mobile", sa.String(20), nullable=False, server_default=""),
        sa.Column("patient_address", sa.Text, nullable=False, server_default=""),
        sa.Column("guardian_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("referring_doctor_id", UUID(as_uuid=True), sa.ForeignKey("referring_doctors.id")),
        sa.Column("referring_doctor_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="confirmed"),
        sa.Column("subtotal", MONEY, nullable=False),
        sa.Column("discount_type", sa.String(8), nullable=False, server_default="none"),
        sa.Column("discount_value", MONEY, nullable=False, server_default="0"),
        sa.Column("discount_amount", MONEY, nullable=False, server_default="0"),
        sa.Column("total", MONEY, nullable=False),
        sa.Column("paid", MONEY, nullable=False, server_default="0"),
        sa.Column("due", MONEY, nullable=False),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("cancel_reason", sa.Text, nullable=False, server_default=""),
        _user("created_by"),
        sa.Column("created_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "invoice_no", name="uq_invoices_no"),
        sa.CheckConstraint("status IN ('confirmed', 'on_hold', 'cancelled')", name="ck_invoices_status"),
        sa.CheckConstraint("discount_type IN ('none', 'percent', 'amount')", name="ck_invoices_discount_type"),
        # The money always adds up, whatever writes the row.
        sa.CheckConstraint("subtotal >= 0 AND discount_amount >= 0 AND discount_amount <= subtotal", name="ck_invoices_discount"),
        sa.CheckConstraint("total = subtotal - discount_amount", name="ck_invoices_total"),
        sa.CheckConstraint("paid >= 0 AND due = total - paid AND (due >= 0 OR status = 'cancelled')", name="ck_invoices_due"),
    )
    op.create_index("ix_invoices_date", "invoices", ["tenant_id", sa.text("bill_date DESC"), sa.text("created_at DESC")])
    op.create_index("ix_invoices_patient", "invoices", ["tenant_id", "patient_id"])
    op.create_index("ix_invoices_doctor", "invoices", ["tenant_id", "referring_doctor_id", "bill_date"])
    op.execute("CREATE INDEX ix_invoices_due ON invoices (tenant_id, bill_date) WHERE due > 0 AND status <> 'cancelled'")
    op.execute("CREATE INDEX ix_invoices_name_trgm ON invoices USING gin (lower(patient_name) gin_trgm_ops)")
    op.create_index("ix_invoices_mobile", "invoices", ["tenant_id", "patient_mobile"])

    op.create_table(
        "invoice_items",
        _id(), _tenant(),
        sa.Column("invoice_id", UUID(as_uuid=True), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("test_id", UUID(as_uuid=True), sa.ForeignKey("tests.id")),
        sa.Column("test_name", sa.String(200), nullable=False),
        sa.Column("department_id", UUID(as_uuid=True), sa.ForeignKey("departments.id")),
        sa.Column("department_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("is_imaging", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("unit_price", MONEY, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="billed"),
        sa.Column("accession_no", sa.String(32), nullable=False, server_default=""),
        sa.Column("status_changed_at", TS),
        sa.Column("legacy_id", sa.Integer),
        sa.CheckConstraint("quantity > 0 AND unit_price >= 0 AND amount = unit_price * quantity", name="ck_items_amount"),
        sa.CheckConstraint("status IN ('billed', 'scanned', 'reported', 'delivered', 'cancelled')", name="ck_items_status"),
    )
    op.create_index("ix_items_invoice", "invoice_items", ["invoice_id", "position"])
    op.create_index("ix_items_worklist", "invoice_items", ["tenant_id", "department_id", "status"])
    op.execute("CREATE UNIQUE INDEX uq_items_accession ON invoice_items (tenant_id, accession_no) WHERE accession_no <> ''")

    op.create_table(
        "payments",
        _id(), _tenant(),
        sa.Column("invoice_id", UUID(as_uuid=True), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False, server_default="payment"),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("reference", sa.String(100), nullable=False, server_default=""),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("received_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("received_on", sa.Date, nullable=False),
        _user("received_by"),
        sa.Column("received_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("legacy_id", sa.Integer),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount"),
        sa.CheckConstraint("kind IN ('payment', 'refund')", name="ck_payments_kind"),
        sa.CheckConstraint("mode IN ('cash', 'upi', 'card', 'bank', 'other')", name="ck_payments_mode"),
    )
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"])
    op.create_index("ix_payments_day", "payments", ["tenant_id", "received_on"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY client_rows ON {table}
                       USING (app_is_platform() OR tenant_id = app_tenant())
                       WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    # Money already received is never rewritten or removed by the app: corrections are refunds.
    op.execute("REVOKE UPDATE, DELETE ON payments FROM supreme_app")
    op.execute("REVOKE DELETE ON invoices, invoice_items, patients FROM supreme_app")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_constraint("ck_settings_paper", "tenant_settings")
    op.drop_constraint("ck_settings_discount", "tenant_settings")
    op.drop_column("tenant_settings", "bill_paper")
    op.drop_column("tenant_settings", "max_discount_percent")
