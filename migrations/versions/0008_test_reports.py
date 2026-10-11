"""Test reports, their saved versions, report templates, doctors' signatures, imaging studies and report
deliveries to patients (WhatsApp) and public patient links (QR code) (phase 4).

Every table is per client with row-level security. Saved report versions are never rewritten or removed.
Reports the old app typed (invoice_items.legacy_report) are brought across as imported reports.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
TABLES = ("test_reports", "test_report_versions", "report_templates", "doctor_signatures", "imaging_studies", "message_deliveries",
          "report_shares")


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _user(name: str):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"))


def _text(name: str):
    return sa.Column(name, sa.Text, nullable=False, server_default="")


def upgrade() -> None:
    op.create_table(
        "test_reports",
        _id(), _tenant(),
        sa.Column("invoice_item_id", UUID(as_uuid=True), sa.ForeignKey("invoice_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("technique", sa.String(500), nullable=False, server_default=""),
        sa.Column("modality", sa.String(40), nullable=False, server_default=""),
        _text("findings"), _text("impression"),
        _user("reported_by"),
        sa.Column("reported_by_name", sa.String(200), nullable=False, server_default=""),
        _user("signed_by"),
        sa.Column("signed_at", TS),
        # Who signed, as it read when they signed: the print never changes if their profile does later.
        sa.Column("signer_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("signer_degree", sa.String(200), nullable=False, server_default=""),
        sa.Column("signer_registration_no", sa.String(60), nullable=False, server_default=""),
        _text("signature_data"),
        sa.Column("signature_mime", sa.String(40), nullable=False, server_default=""),
        sa.Column("amend_reason", sa.Text, nullable=False, server_default=""),
        sa.Column("amendments", sa.Integer, nullable=False, server_default="0"),
        sa.Column("imported", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("invoice_item_id", name="uq_test_reports_item"),
        sa.CheckConstraint("status IN ('draft', 'final', 'signed', 'amended')", name="ck_test_reports_status"),
        sa.CheckConstraint("version >= 1", name="ck_test_reports_version"),
    )
    op.create_index("ix_test_reports_status", "test_reports", ["tenant_id", "status", sa.text("updated_at DESC")])

    op.create_table(
        "test_report_versions",
        _id(), _tenant(),
        sa.Column("report_id", UUID(as_uuid=True), sa.ForeignKey("test_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("action", sa.String(12), nullable=False),  # created | saved | finalised | signed | amended | imported
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("technique", sa.String(500), nullable=False, server_default=""),
        sa.Column("modality", sa.String(40), nullable=False, server_default=""),
        _text("findings"), _text("impression"),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        _user("saved_by"),
        sa.Column("saved_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("report_id", "version", name="uq_report_versions"),
    )

    op.create_table(
        "report_templates",
        _id(), _tenant(),
        sa.Column("test_id", UUID(as_uuid=True), sa.ForeignKey("tests.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("technique", sa.String(500), nullable=False, server_default=""),
        _text("findings"), _text("impression"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.execute("CREATE UNIQUE INDEX uq_report_templates_name ON report_templates (tenant_id, lower(name))")
    op.create_index("ix_report_templates_test", "report_templates", ["tenant_id", "test_id"])

    op.create_table(
        "doctor_signatures",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        _tenant(),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("degree", sa.String(200), nullable=False, server_default=""),
        sa.Column("registration_no", sa.String(60), nullable=False, server_default=""),
        _text("signature_data"),
        sa.Column("signature_mime", sa.String(40), nullable=False, server_default=""),
        sa.Column("signature_version", sa.String(20), nullable=False, server_default=""),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "imaging_studies",
        _id(), _tenant(),
        sa.Column("invoice_item_id", UUID(as_uuid=True), sa.ForeignKey("invoice_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("study_instance_uid", sa.String(128), nullable=False),
        sa.Column("orthanc_study_id", sa.String(64), nullable=False),
        sa.Column("modality", sa.String(40), nullable=False, server_default=""),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("series_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("instance_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        _user("uploaded_by"),
        sa.Column("uploaded_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "study_instance_uid", name="uq_imaging_studies_uid"),
    )
    op.create_index("ix_imaging_studies_item", "imaging_studies", ["invoice_item_id"])

    op.create_table(
        "message_deliveries",
        _id(), _tenant(),
        sa.Column("report_id", UUID(as_uuid=True), sa.ForeignKey("test_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False, server_default="whatsapp"),
        sa.Column("to", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("provider", sa.String(20), nullable=False, server_default=""),
        sa.Column("provider_message_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("error", sa.String(500), nullable=False, server_default=""),
        sa.Column("report_version", sa.Integer, nullable=False, server_default="1"),
        _user("sent_by"),
        sa.Column("sent_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", TS),
        sa.Column("delivered_at", TS),
        sa.Column("read_at", TS),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('queued', 'sent', 'delivered', 'read', 'failed')", name="ck_message_deliveries_status"),
        sa.CheckConstraint("channel IN ('whatsapp')", name="ck_message_deliveries_channel"),
    )
    op.create_index("ix_message_deliveries_report", "message_deliveries", ["report_id", sa.text("created_at DESC")])
    op.execute("CREATE INDEX ix_message_deliveries_provider_id ON message_deliveries (provider_message_id) WHERE provider_message_id <> ''")

    # A link the patient opens from the report's QR code. Only the SHA-256 of its token is kept.
    op.create_table(
        "report_shares",
        _id(), _tenant(),
        sa.Column("report_id", UUID(as_uuid=True), sa.ForeignKey("test_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        _user("created_by"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_viewed_at", TS),
        sa.Column("failed_checks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", TS),
        sa.UniqueConstraint("token_hash", name="uq_report_shares_token"),
    )
    op.create_index("ix_report_shares_report", "report_shares", ["report_id", sa.text("created_at DESC")])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY client_rows ON {table}
                       USING (app_is_platform() OR tenant_id = app_tenant())
                       WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    # A saved version is a record of what was written: never rewritten or removed. Reports are never deleted.
    op.execute("REVOKE UPDATE, DELETE ON test_report_versions FROM supreme_app")
    op.execute("REVOKE DELETE ON test_reports, message_deliveries FROM supreme_app")

    # The image server is shared, so before a client claims a study we ask whether another client already has it.
    # Row-level security hides other clients' rows, so this one question runs as the table owner and only ever
    # answers yes or no.
    op.execute("""
        CREATE FUNCTION imaging_uid_taken_elsewhere(uid text) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT EXISTS (SELECT 1 FROM imaging_studies WHERE study_instance_uid = uid
                          AND tenant_id IS DISTINCT FROM app_tenant()) $$
    """)
    op.execute("REVOKE ALL ON FUNCTION imaging_uid_taken_elsewhere(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION imaging_uid_taken_elsewhere(text) TO supreme_app")

    from app.services.report_import import import_legacy_reports
    import_legacy_reports(op.get_bind())


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS imaging_uid_taken_elsewhere(text)")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
