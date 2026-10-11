"""Custom roles per centre: who made a role and when, and database rules that keep built-in roles fixed.

Built-in roles (tenant_id NULL) are shared and kept in step with app/catalog.py by app.seed; a centre can read
them but the existing row-level security already stops it changing them (write_roles only matches its own rows).
A centre's own roles are always client roles, and their codes never reuse a built-in code.

Revision ID: 0011_custom_roles
Revises: 0010_jobs_and_notifications
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0011_custom_roles"
down_revision = "0010_jobs_and_notifications"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("roles", sa.Column("created_by_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL",
                                                                                         name="fk_roles_created_by")))
    op.add_column("roles", sa.Column("created_at", TS, server_default=sa.func.now()))
    op.add_column("roles", sa.Column("updated_at", TS, server_default=sa.func.now()))
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])
    op.create_check_constraint("ck_roles_custom_are_client", "roles", "tenant_id IS NULL OR scope = 'client'")


def downgrade() -> None:
    op.drop_constraint("ck_roles_custom_are_client", "roles", type_="check")
    op.drop_index("ix_user_roles_role_id", "user_roles")
    op.drop_index("ix_roles_tenant_id", "roles")
    op.drop_column("roles", "updated_at")
    op.drop_column("roles", "created_at")
    op.drop_column("roles", "created_by_id")
