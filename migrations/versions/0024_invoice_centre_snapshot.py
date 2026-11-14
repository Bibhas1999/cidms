"""A bill now keeps a copy of the centre's name, address, phones and bill footer as they were when it was
made, so a reprint still matches what the patient was handed even after the centre's letterhead changes.
Existing bills get today's settings as the closest available guess, since no earlier copy exists.

Revision ID: 0024_invoice_centre_snapshot
Revises: 0023_invoice_held_at
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_invoice_centre_snapshot"
down_revision = "0023_invoice_held_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("centre_name", sa.String(200), nullable=False, server_default=""))
    op.add_column("invoices", sa.Column("centre_address", sa.Text(), nullable=False, server_default=""))
    op.add_column("invoices", sa.Column("centre_phones", sa.String(200), nullable=False, server_default=""))
    op.add_column("invoices", sa.Column("centre_bill_footer", sa.Text(), nullable=False, server_default=""))
    op.execute("""
        UPDATE invoices i SET
            centre_name = COALESCE(NULLIF(s.legal_name, ''), t.name),
            centre_address = s.address,
            centre_phones = s.phones,
            centre_bill_footer = s.bill_footer
        FROM tenants t
        LEFT JOIN tenant_settings s ON s.tenant_id = t.id
        WHERE t.id = i.tenant_id
    """)
    op.alter_column("invoices", "centre_name", server_default=None)
    op.alter_column("invoices", "centre_address", server_default=None)
    op.alter_column("invoices", "centre_phones", server_default=None)
    op.alter_column("invoices", "centre_bill_footer", server_default=None)


def downgrade() -> None:
    op.drop_column("invoices", "centre_bill_footer")
    op.drop_column("invoices", "centre_phones")
    op.drop_column("invoices", "centre_address")
    op.drop_column("invoices", "centre_name")
