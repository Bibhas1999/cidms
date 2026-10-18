"""Rate limits shared by every app process (sign-in attempts, reset emails, report-link checks, API keys…): one row
per attempt, counted in a sliding window. Not client data, so no row-level security; rows older than two days go.

Revision ID: 0019_rate_limits
Revises: 0018_payload_keys
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_rate_limits"
down_revision = "0018_payload_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hits",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("bucket", sa.String(40), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rate_limit_hits_bucket_key_at", "rate_limit_hits", ["bucket", "key", "at"])


def downgrade() -> None:
    op.drop_table("rate_limit_hits")
