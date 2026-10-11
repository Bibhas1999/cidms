"""A centre's wide logo with its name and slogan ("wordmark"), kept in the database as base64 like the square logo.

Used on the sign-in page, the sidebar, printed bills and PDF letterheads; the square logo stays for small places.

Revision ID: 0012_wordmark
Revises: 0011_custom_roles
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_wordmark"
down_revision = "0011_custom_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_settings", sa.Column("wordmark_file", sa.String(100), nullable=False, server_default=""))
    op.add_column("tenant_settings", sa.Column("wordmark_data", sa.Text, nullable=False, server_default=""))
    op.add_column("tenant_settings", sa.Column("wordmark_mime", sa.String(40), nullable=False, server_default=""))


def downgrade() -> None:
    for col in ("wordmark_mime", "wordmark_data", "wordmark_file"):
        op.drop_column("tenant_settings", col)
