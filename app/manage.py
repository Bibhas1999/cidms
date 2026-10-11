"""Admin commands run on the server.

    python -m app.manage create-user --workspace supreme --email you@example.com --name "Your Name" --role owner
    python -m app.manage create-user --workspace platform --email you@example.com --name "Your Name" --role platform_owner

A temporary password is printed once; the person must choose their own at first sign-in.
"""

import argparse

from sqlalchemy import select

from app.catalog import ROLES
from app.core.db import scoped_session
from app.core.passwords import hash_password
from app.models import Role, Tenant, User, UserRole


def temporary_password() -> str:
    """The centre's one-time temporary password (DEFAULT_TEMPORARY_PASSWORD); they choose their own at first sign-in."""
    from app.core.config import get_settings
    return get_settings().default_temporary_password


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


def move_images_to_database() -> None:
    """Logos and profile pictures saved as files (before they moved into the database) are copied in."""
    from pathlib import Path

    from app.core.config import get_settings
    from app.core.storage import avatar_image, logo_image
    from app.models import TenantSettings
    base = Path(get_settings().storage_dir)
    moved = 0
    with scoped_session(platform=True) as db, db.begin():
        for row in db.scalars(select(TenantSettings).where(TenantSettings.logo_file != "", TenantSettings.logo_data == "")):
            path = base / "tenants" / str(row.tenant_id) / row.logo_file
            if path.is_file():
                image = logo_image(path.read_bytes())
                row.logo_data, row.logo_mime, row.logo_file = image.data, image.mime, image.version
                moved += 1
        for user in db.scalars(select(User).where(User.avatar_file != "", User.avatar_data == "")):
            folder = base / ("platform" if user.tenant_id is None else f"tenants/{user.tenant_id}") / "avatars"
            path = folder / user.avatar_file
            if path.is_file():
                image = avatar_image(path.read_bytes())
                user.avatar_data, user.avatar_mime, user.avatar_file = image.data, image.mime, image.version
                moved += 1
            else:
                user.avatar_file = ""
    print(f"Moved {moved} pictures into the database.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cu = sub.add_parser("create-user", help="add a person with a temporary password")
    cu.add_argument("--workspace", required=True, help='a client address such as "supreme", or "platform"')
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", required=True, help=", ".join(ROLES))
    sub.add_parser("move-images-to-db", help="copy logos and profile pictures saved as files into the database")
    args = parser.parse_args()
    if args.command == "move-images-to-db":
        move_images_to_database()
        return
    if args.command == "create-user":
        password = create_user(args.workspace, args.email, args.name, args.role)
        print(f"Created {args.email.lower()} in {args.workspace} as {args.role}. Temporary password: {password}")


if __name__ == "__main__":
    main()
