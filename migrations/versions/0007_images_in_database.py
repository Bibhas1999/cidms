"""Logos and profile pictures are kept in the database (base64 text) instead of files on disk.

logo_file / avatar_file stay, now holding a short version code that changes with the picture (for caching).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_settings", sa.Column("logo_data", sa.Text, nullable=False, server_default=""))
    op.add_column("tenant_settings", sa.Column("logo_mime", sa.String(40), nullable=False, server_default=""))
    op.add_column("users", sa.Column("avatar_data", sa.Text, nullable=False, server_default=""))
    op.add_column("users", sa.Column("avatar_mime", sa.String(40), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "avatar_mime")
    op.drop_column("users", "avatar_data")
    op.drop_column("tenant_settings", "logo_mime")
    op.drop_column("tenant_settings", "logo_data")
