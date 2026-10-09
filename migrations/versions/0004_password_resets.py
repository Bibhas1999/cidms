"""Password reset links: single use, short lived, only a hash of the token stored.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_resets",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", INET),
    )
    op.execute("ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY client_rows ON password_resets
                  USING (app_is_platform() OR tenant_id = app_tenant())
                  WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    # Platform staff (tenant_id NULL) reset at the platform address, which works in platform scope.


def downgrade() -> None:
    op.drop_table("password_resets")
