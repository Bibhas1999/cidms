"""Reference data and first sign-in details. Safe to run again: it only adds what's missing and keeps the
built-in roles' permissions in step with app/catalog.py.

    python -m app.seed               permissions, roles, plans, the platform owner
    python -m app.seed --supreme     ...and Supreme Health Care as the first client (development)
"""

import argparse
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.catalog import CLIENT_PERMISSIONS, PLATFORM_PERMISSIONS, ROLES
from app.core.config import get_settings
from app.core.db import scoped_session
from app.core.passwords import hash_password
from app.models import Permission, Plan, Role, RolePermission, Tenant, TenantSettings, User, UserRole

PLANS = [
    # code, name, users, bills a month, image storage (GB), ₹ a month
    ("starter", "Starter", 5, 1500, 50, Decimal("1499.00")),
    ("standard", "Standard", 15, 5000, 250, Decimal("2999.00")),
    ("pro", "Pro", 50, 20000, 1000, Decimal("5999.00")),
]


def seed_reference(db: Session) -> None:
    for scope, perms in (("platform", PLATFORM_PERMISSIONS), ("client", CLIENT_PERMISSIONS)):
        for code, description in perms.items():
            row = db.get(Permission, code)
            if row is None:
                db.add(Permission(code=code, scope=scope, description=description))
            else:
                row.scope, row.description = scope, description
    db.flush()
    for code, (name, scope, description, perms) in ROLES.items():
        role = db.scalar(select(Role).where(Role.tenant_id.is_(None), Role.code == code))
        if role is None:
            role = Role(tenant_id=None, code=code, name=name, scope=scope, description=description)
            db.add(role)
            db.flush()
        else:
            role.name, role.scope, role.description = name, scope, description
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.add_all(RolePermission(role_id=role.id, permission_code=p) for p in sorted(perms))
    for code, name, users, bills, storage, price in PLANS:
        if db.scalar(select(Plan).where(Plan.code == code)) is None:
            db.add(Plan(code=code, name=name, max_users=users, max_bills_per_month=bills, storage_gb=storage, price_monthly=price))
    db.flush()


def _role(db: Session, code: str) -> Role:
    return db.scalar(select(Role).where(Role.tenant_id.is_(None), Role.code == code))


def seed_platform_owner(db: Session, email: str, password: str) -> None:
    email = email.strip().lower()
    if db.scalar(select(User).where(User.tenant_id.is_(None), User.email == email)):
        return
    user = User(tenant_id=None, email=email, full_name="Platform owner", password_hash=hash_password(password), must_change_password=True)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=_role(db, "platform_owner").id, tenant_id=None))
    print(f"Platform owner: {email} (asked to change the password at first sign-in)")


def seed_supreme(db: Session, email: str, password: str) -> None:
    """Supreme Health Care, the first client. Its real staff, bills and patients come across in phase 3."""
    if db.scalar(select(Tenant).where(Tenant.slug == "supreme")):
        return
    plan = db.scalar(select(Plan).where(Plan.code == "standard"))
    tenant = Tenant(slug="supreme", name="Supreme Health Care", kind="diagnostic", plan_id=plan.id if plan else None)
    db.add(tenant)
    db.flush()
    db.add(TenantSettings(
        tenant_id=tenant.id, legal_name="Supreme Health Care & Medical Solution",
        address="Janai (Near Subedar More), Chanditala, Hooghly-712304", phones="+91 76880 17623",
        email="supremehealthcaresolution@gmail.com", invoice_prefix="SHC",
        bill_footer="No refund once a test is done. Reports are delivered 4 pm to 8 pm, Monday to Saturday. "
                    "Reports not collected within 30 days are not kept.",
    ))
    owner = User(tenant_id=tenant.id, email=email.strip().lower(), full_name="Supreme owner",
                 password_hash=hash_password(password), must_change_password=True)
    db.add(owner)
    db.flush()
    db.add(UserRole(user_id=owner.id, role_id=_role(db, "owner").id, tenant_id=tenant.id))
    print(f"Supreme Health Care: sign in at supreme.<BASE_DOMAIN> as {owner.email}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--supreme", action="store_true", help="also add Supreme Health Care as a client")
    args = parser.parse_args()
    s = get_settings()
    if s.is_production and "Change-me-now-1" in (s.seed_platform_owner_password, s.seed_supreme_owner_password):
        raise SystemExit("Set SEED_PLATFORM_OWNER_PASSWORD (and SEED_SUPREME_OWNER_PASSWORD) before seeding production.")
    with scoped_session(platform=True) as db, db.begin():
        seed_reference(db)
        seed_platform_owner(db, s.seed_platform_owner_email, s.seed_platform_owner_password)
        if args.supreme:
            seed_supreme(db, s.seed_supreme_owner_email, s.seed_supreme_owner_password)
    print("Reference data is up to date.")


if __name__ == "__main__":
    main()
