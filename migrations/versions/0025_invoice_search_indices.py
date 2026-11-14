"""Two indices for bills that get slow once a centre's history grows:

- A trigram GIN index on the lower-cased patient name, so the "search by name" box in Bills/Dues/exports
  (a leading-wildcard LIKE) can use an index instead of scanning every bill in the tenant.
- A composite index on (tenant_id, status, due), for the Dues page and the "due/paid/part/unpaid" filter.

Revision ID: 0025_invoice_search_indices
Revises: 0024_invoice_centre_snapshot
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_invoice_search_indices"
down_revision = "0024_invoice_centre_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index("ix_invoices_patient_name_trgm", "invoices", [sa.text("lower(patient_name) gin_trgm_ops")],
                    postgresql_using="gin")
    op.create_index("ix_invoices_status_due", "invoices", ["tenant_id", "status", "due"])


def downgrade() -> None:
    op.drop_index("ix_invoices_status_due", table_name="invoices")
    op.drop_index("ix_invoices_patient_name_trgm", table_name="invoices")
