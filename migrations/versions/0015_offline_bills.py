"""Bills made while the centre's internet was down: kept on the desk computer with a provisional number
(OFF-K7Q-0003), printed, and sent here when the connection is back. The bill keeps that number and the time it
was really made, and its date is the day it was made, not the day it arrived.

Revision ID: 0015_offline_bills
Revises: 0014_backup_schedule
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_offline_bills"
down_revision = "0014_backup_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("offline_no", sa.String(40), nullable=False, server_default=""))
    op.add_column("invoices", sa.Column("made_offline_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("invoices", "made_offline_at")
    op.drop_column("invoices", "offline_no")
