"""Branding per centre (colour, tagline, logo) and room for reports brought across from the old app.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_settings", sa.Column("brand_color", sa.String(7), nullable=False, server_default="#0f6e6e"))
    op.add_column("tenant_settings", sa.Column("tagline", sa.String(120), nullable=False, server_default=""))
    op.add_column("tenant_settings", sa.Column("logo_file", sa.String(100), nullable=False, server_default=""))
    op.create_check_constraint("ck_settings_brand_color", "tenant_settings", "brand_color ~ '^#[0-9a-fA-F]{6}$'")
    # The old app's typed reports (findings, impression, doctor) are kept as they were until phase 4 turns
    # them into proper reports, so nothing is lost in the move.
    op.add_column("invoice_items", sa.Column("legacy_report", JSONB))


def downgrade() -> None:
    op.drop_column("invoice_items", "legacy_report")
    op.drop_constraint("ck_settings_brand_color", "tenant_settings")
    for col in ("logo_file", "tagline", "brand_color"):
        op.drop_column("tenant_settings", col)
