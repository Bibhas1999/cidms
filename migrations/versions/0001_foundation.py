"""Foundation: plans, clients, people, roles and permissions, sessions, activity log, row-level security.

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ZERO_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"
TS = sa.DateTime(timezone=True)


def _tenant_fk(nullable: bool = True, **kw):
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=nullable, **kw)


def upgrade() -> None:
    # Whose data a transaction may see. Set per transaction by app/core/db.py; empty means "no client".
    op.execute("""
        CREATE FUNCTION app_tenant() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;
        CREATE FUNCTION app_is_platform() RETURNS boolean LANGUAGE sql STABLE AS
        $$ SELECT coalesce(current_setting('app.platform', true), '') = 'on' $$;
    """)

    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("max_users", sa.Integer, nullable=False),
        sa.Column("max_bills_per_month", sa.Integer, nullable=False),
        sa.Column("storage_gb", sa.Integer, nullable=False),
        sa.Column("price_monthly", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="diagnostic"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id")),
        sa.Column("paid_until", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("slug ~ '^[a-z][a-z0-9-]{1,38}[a-z0-9]$'", name="ck_tenants_slug"),
        sa.CheckConstraint("kind IN ('diagnostic', 'opd', 'clinic')", name="ck_tenants_kind"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_tenants_status"),
    )
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("phones", sa.String(200), nullable=False, server_default=""),
        sa.Column("email", sa.String(200), nullable=False, server_default=""),
        sa.Column("gst_number", sa.String(20), nullable=False, server_default=""),
        sa.Column("invoice_prefix", sa.String(10), nullable=False, server_default="INV"),
        sa.Column("bill_footer", sa.Text, nullable=False, server_default=""),
        sa.Column("report_footer", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(60), primary_key=True),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.CheckConstraint("scope IN ('platform', 'client')", name="ck_permissions_scope"),
    )
    op.create_table(
        "roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant_fk(),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.CheckConstraint("scope IN ('platform', 'client')", name="ck_roles_scope"),
    )
    op.execute(f"CREATE UNIQUE INDEX uq_roles_code ON roles (coalesce(tenant_id, {ZERO_UUID}), code)")
    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_code", sa.String(60), sa.ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant_fk(index=True),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("mobile", sa.String(20), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("failed_logins", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", TS),
        sa.Column("last_login_at", TS),
        sa.Column("legacy_id", sa.Integer),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
    )
    # One account per email in each client (and once among platform staff).
    op.execute(f"CREATE UNIQUE INDEX uq_users_email ON users (coalesce(tenant_id, {ZERO_UUID}), email)")
    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        _tenant_fk(index=True),
    )
    op.create_table(
        "sessions",
        sa.Column("id_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        _tenant_fk(index=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.Column("ip_address", INET),
        sa.Column("user_agent", sa.String(300), nullable=False, server_default=""),
    )
    op.create_table(
        "activity_log",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _tenant_fk(),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("entity", sa.String(40), nullable=False, server_default=""),
        sa.Column("entity_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
        sa.Column("ip_address", INET),
        sa.Column("user_agent", sa.String(300), nullable=False, server_default=""),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_activity_tenant_time", "activity_log", ["tenant_id", sa.text("created_at DESC")])
    op.create_index("ix_activity_created_at", "activity_log", ["created_at"])

    # ---------- row-level security ----------
    # Client tables: a transaction sees only its own client's rows, or everything when doing platform work.
    for table in ("tenant_settings", "users", "user_roles", "sessions", "activity_log"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY client_rows ON {table}
                       USING (app_is_platform() OR tenant_id = app_tenant())
                       WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    # Clients see their own record only; only platform work changes clients.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY read_own ON tenants FOR SELECT USING (app_is_platform() OR id = app_tenant())")
    op.execute("CREATE POLICY platform_writes ON tenants FOR ALL USING (app_is_platform()) WITH CHECK (app_is_platform())")
    # Plans and permissions hold no client data: everyone reads them, only platform work changes them.
    for table in ("plans", "permissions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY read_all ON {table} FOR SELECT USING (true)")
        op.execute(f"CREATE POLICY platform_writes ON {table} FOR ALL USING (app_is_platform()) WITH CHECK (app_is_platform())")
    # Roles: built-in client roles are shared by every client; a client's own roles are its alone.
    op.execute("ALTER TABLE roles ENABLE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY read_roles ON roles FOR SELECT
                  USING (app_is_platform() OR tenant_id = app_tenant() OR (tenant_id IS NULL AND scope = 'client'))""")
    op.execute("""CREATE POLICY write_roles ON roles FOR ALL
                  USING (app_is_platform() OR tenant_id = app_tenant())
                  WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    op.execute("ALTER TABLE role_permissions ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY read_visible ON role_permissions FOR SELECT USING (EXISTS (SELECT 1 FROM roles r WHERE r.id = role_id))")
    op.execute("""CREATE POLICY write_own ON role_permissions FOR ALL
                  USING (app_is_platform() OR EXISTS (SELECT 1 FROM roles r WHERE r.id = role_id AND r.tenant_id = app_tenant()))
                  WITH CHECK (app_is_platform() OR EXISTS (SELECT 1 FROM roles r WHERE r.id = role_id AND r.tenant_id = app_tenant()))""")

    # The activity log is append-only for the app.
    op.execute("REVOKE UPDATE, DELETE ON activity_log FROM supreme_app")


def downgrade() -> None:
    for table in ("activity_log", "sessions", "user_roles", "users", "role_permissions", "roles", "permissions",
                  "tenant_settings", "tenants", "plans"):
        op.drop_table(table)
    op.execute("DROP FUNCTION app_is_platform(); DROP FUNCTION app_tenant();")
