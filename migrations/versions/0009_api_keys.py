"""API keys for other systems, and the log of their calls to /api/v1 (integrations).

Both tables are per client with row-level security. Keys are never deleted (they're revoked); the call log
is append-only apart from removing old rows (kept API_REQUEST_RETENTION_DAYS).

Revision ID: 0009_api_keys
Revises: 0008
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET, UUID

revision = "0009_api_keys"
down_revision = "0008"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
TABLES = ("api_keys", "api_requests")


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _user(name: str):
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"))


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(32), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("scopes", ARRAY(sa.String(30)), nullable=False, server_default="{}"),
        sa.Column("allowed_ips", ARRAY(CIDR), nullable=False, server_default="{}"),
        sa.Column("expires_at", TS),
        _user("created_by"),
        sa.Column("created_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", TS),
        sa.Column("last_used_ip", INET),
        sa.Column("revoked_at", TS),
        _user("revoked_by"),
        sa.Column("revoked_by_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("replaced_by", UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="SET NULL")),
        sa.UniqueConstraint("secret_hash", name="uq_api_keys_secret_hash"),
        sa.CheckConstraint("scopes <@ ARRAY['patients:read','tests:read','orders:read','reports:read','images:read',"
                           "'doctors:read']::varchar[]", name="ck_api_keys_scopes"),
    )
    op.create_index("ix_api_keys_tenant", "api_keys", ["tenant_id", sa.text("created_at DESC")])

    op.create_table(
        "api_requests",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        _tenant(),
        sa.Column("key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="CASCADE")),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("status", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ip_address", INET),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_api_requests_tenant_time", "api_requests", ["tenant_id", sa.text("created_at DESC")])
    op.create_index("ix_api_requests_key_time", "api_requests", ["key_id", sa.text("created_at DESC")])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY client_rows ON {table}
                       USING (app_is_platform() OR tenant_id = app_tenant())
                       WITH CHECK (app_is_platform() OR tenant_id = app_tenant())""")
    # Keys are revoked, never deleted, so who made and used them stays on record. The call log is never rewritten.
    op.execute("REVOKE DELETE ON api_keys FROM supreme_app")
    op.execute("REVOKE UPDATE ON api_requests FROM supreme_app")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
