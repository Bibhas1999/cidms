"""Tests run against the supreme_test database in the local Docker Postgres (docker compose up -d), rebuilt
from the migrations at the start of the run, with the same row-level security the app uses."""

import os

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "postgresql+psycopg://supreme_app:local-app-only@localhost:5433/supreme_test"
os.environ["MIGRATION_DATABASE_URL"] = "postgresql+psycopg://supreme_owner:local-owner-only@localhost:5433/supreme_test"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import engine, scoped_session
from app.core.limits import client_error_limiter, login_limiter, reset_limiter
from app.core.passwords import hash_password
from app.core.tenancy import forget_tenant
from app.main import app
from app.models import Role, Tenant, TenantSettings, User, UserRole
from app.seed import seed_reference

PASSWORD = "Test-password-1"
TABLES = "password_resets, payments, invoice_items, invoices, patients, referring_doctors, tests, test_types, departments, operations, counters, activity_log, sessions, user_roles, users, role_permissions, roles, permissions, tenant_settings, tenants, plans"


@pytest.fixture(scope="session", autouse=True)
def database():
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = os.environ["MIGRATION_DATABASE_URL"]
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


def _owner_connection():
    from sqlalchemy import create_engine
    return create_engine(os.environ["MIGRATION_DATABASE_URL"]).connect()


@pytest.fixture(autouse=True)
def clean(database):
    """Every test starts from the reference data alone."""
    with _owner_connection() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        conn.commit()
    with scoped_session(platform=True) as db, db.begin():
        seed_reference(db)
    login_limiter.reset()
    client_error_limiter.reset()
    reset_limiter.reset()
    forget_tenant()
    yield


def make_tenant(slug: str, name: str | None = None, status: str = "active") -> Tenant:
    with scoped_session(platform=True) as db, db.begin():
        t = Tenant(slug=slug, name=name or slug.title(), status=status)
        db.add(t)
        db.flush()
        db.add(TenantSettings(tenant_id=t.id, legal_name=t.name, invoice_prefix="TST"))
        return t


def make_user(tenant: Tenant | None, email: str, roles: list[str], password: str = PASSWORD,
              must_change: bool = False, password_hash: str | None = None) -> User:
    with scoped_session(platform=True) as db, db.begin():
        u = User(tenant_id=tenant.id if tenant else None, email=email, full_name=email.split("@")[0].title(),
                 password_hash=password_hash or hash_password(password), must_change_password=must_change)
        db.add(u)
        db.flush()
        for code in roles:
            role = db.query(Role).filter(Role.tenant_id.is_(None), Role.code == code).one()
            db.add(UserRole(user_id=u.id, role_id=role.id, tenant_id=u.tenant_id))
        return u


class Client(TestClient):
    """A browser at one address. Sends the CSRF token it was given at sign-in on every change."""
    csrf = ""

    def request(self, method, url, *args, **kwargs):
        if method.upper() not in ("GET", "HEAD", "OPTIONS") and self.csrf:
            kwargs["headers"] = {"X-CSRF-Token": self.csrf, **dict(kwargs.get("headers") or {})}
        return super().request(method, url, *args, **kwargs)

    def login(self, email: str, password: str = PASSWORD):
        r = self.post("/api/auth/login", json={"email": email, "password": password})
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r


def browser(host: str) -> Client:
    return Client(app, base_url=f"http://{host}")


@pytest.fixture
def alpha():
    return make_tenant("alpha", "Alpha Diagnostics")


@pytest.fixture
def beta():
    return make_tenant("beta", "Beta Clinic")
