"""Putting a bill on hold now also marks when: payments received at or before that no longer count toward
its paid/due (they stay in the payments table, just ignored for this bill's balance until it's paid again).

Revision ID: 0023_invoice_held_at
Revises: 0022_invoice_shares
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_invoice_held_at"
down_revision = "0022_invoice_shares"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("invoices", sa.Column("held_at", TS))


def downgrade() -> None:
    op.drop_column("invoices", "held_at")
