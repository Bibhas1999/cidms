"""Admin commands run on the server.

    python -m app.manage create-user --workspace supreme --email you@example.com --name "Your Name" --role owner
    python -m app.manage create-user --workspace platform --email you@example.com --name "Your Name" --role platform_owner

A temporary password is printed once; the person must choose their own at first sign-in.
"""

import argparse
import secrets

from sqlalchemy import select

from app.catalog import ROLES
from app.core.db import scoped_session
from app.core.passwords import hash_password
from app.models import Role, Tenant, User, UserRole


def temporary_password() -> str:
    return f"Temp-{secrets.token_urlsafe(9)}"


def create_user(workspace: str, email: str, name: str, role_code: str) -> str:
    email = email.strip().lower()
    if role_code not in ROLES:
        raise SystemExit(f"Unknown role {role_code!r}. Choose from: {', '.join(ROLES)}")
    scope = ROLES[role_code][1]
    with scoped_session(platform=True) as db, db.begin():
        tenant_id = None
        if workspace != "platform":
            tenant = db.scalar(select(Tenant).where(Tenant.slug == workspace))
            if tenant is None:
                raise SystemExit(f"No client with the address {workspace!r}.")
            tenant_id = tenant.id
        if (scope == "platform") != (tenant_id is None):
            raise SystemExit(f"{role_code} is a {scope} role; use it with --workspace {'platform' if scope == 'platform' else '<client>'}.")
        tenant_filter = User.tenant_id.is_(None) if tenant_id is None else User.tenant_id == tenant_id
        if db.scalar(select(User).where(tenant_filter, User.email == email)):
            raise SystemExit(f"{email} already has an account in {workspace}.")
        password = temporary_password()
        user = User(tenant_id=tenant_id, email=email, full_name=name.strip(), password_hash=hash_password(password),
                    must_change_password=True)
        db.add(user)
        db.flush()
        role = db.scalar(select(Role).where(Role.tenant_id.is_(None), Role.code == role_code))
        db.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=tenant_id))
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cu = sub.add_parser("create-user", help="add a person with a temporary password")
    cu.add_argument("--workspace", required=True, help='a client address such as "supreme", or "platform"')
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", required=True, help=", ".join(ROLES))
    args = parser.parse_args()
    if args.command == "create-user":
        password = create_user(args.workspace, args.email, args.name, args.role)
        print(f"Created {args.email.lower()} in {args.workspace} as {args.role}. Temporary password: {password}")


if __name__ == "__main__":
    main()
