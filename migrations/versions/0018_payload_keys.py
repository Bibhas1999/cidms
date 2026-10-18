"""Encrypted request and response bodies: the AES keys agreed with each browser tab (ECDH). Not client data (a key
is agreed before anyone signs in), so no row-level security; keys older than a day are removed.

Revision ID: 0018_payload_keys
Revises: 0017_report_pdfs
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_payload_keys"
down_revision = "0017_report_pdfs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payload_keys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),  # base64 of the 32-byte AES key
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_payload_keys_created", "payload_keys", ["created_at"])


def downgrade() -> None:
    op.drop_table("payload_keys")
