"""Bills remember which bill they were in the old app, so the data move can be run again safely.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("legacy_id", sa.Integer))  # invoices.id in the old Laravel app
    op.execute("CREATE UNIQUE INDEX uq_invoices_legacy_id ON invoices (tenant_id, legacy_id) WHERE legacy_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_invoices_legacy_id")
    op.drop_column("invoices", "legacy_id")
