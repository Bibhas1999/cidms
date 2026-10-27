"""Resumable uploads kept in the database (base64, built up piece by piece), never as files on the server; and
a report can be a PDF uploaded instead of (or as well as) typed findings, e.g. from an outside lab or a machine.
The file is kept on the report itself (base64, like the logos since 0007), so client backups and restores carry it
with no change; the PDF that's printed, shared and sent puts the centre's signed cover page in front of it.

Revision ID: 0017_report_pdfs
Revises: 0016_client_backups
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0017_report_pdfs"
down_revision = "0016_client_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("received", sa.Integer, nullable=False, server_default="0"),
        sa.Column("data", sa.Text, nullable=False, server_default=""),  # base64 of the bytes received so far
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_uploads_tenant_updated", "uploads", ["tenant_id", "updated_at"])
    op.execute("ALTER TABLE uploads ENABLE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY client_rows ON uploads
                   USING (app_is_platform() OR tenant_id = app_tenant())
                   WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    op.add_column("test_reports", sa.Column("attachment_name", sa.String(200), nullable=False, server_default=""))
    op.add_column("test_reports", sa.Column("attachment_pages", sa.Integer, nullable=False, server_default="0"))
    op.add_column("test_reports", sa.Column("attachment_size", sa.Integer, nullable=False, server_default="0"))
    op.add_column("test_reports", sa.Column("attachment_data", sa.Text, nullable=False, server_default=""))
    op.add_column("test_report_versions", sa.Column("attachment_name", sa.String(200), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_table("uploads")
    op.drop_column("test_report_versions", "attachment_name")
    for column in ("attachment_data", "attachment_size", "attachment_pages", "attachment_name"):
        op.drop_column("test_reports", column)
