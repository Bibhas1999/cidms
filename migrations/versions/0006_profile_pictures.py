"""Profile pictures: each person can add a photo of themselves.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_file", sa.String(100), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("users", "avatar_file")
