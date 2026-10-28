"""Sign-in, sign-out and password changes."""

import secrets
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, Invalid, Locked, NotFound, Unauthorized
from app.core.limits import login_limiter, reset_limiter
from app.core.logging import client_ip
from app.core.passwords import check_strength, hash_password, verify_password
from app.core.security import (
    CurrentUser,
    clear_session_cookie,
    create_session,
    is_locked,
    load_permissions,
    load_session,
    revoke_user_sessions,
    token_hash,
)
from app.core.tenancy import TenantRef
from app.models import PasswordReset, User, UserSession, utcnow
from app.repositories.users import UserRepository
from app.schemas import MeOut, WorkspaceOut
from app.services import events
from app.services.audit import AuditService

WRONG = "That email and password don't match. Check them and try again."
OWN_ACCOUNT = "account.manage_own"


def manages_own_account(user: User, permissions: set[str]) -> bool:
    """Only the owner and the centre admin (and platform staff) change their own sign-in email and password.
    Other staff get a temporary password from them, and choose their own only at that first sign-in."""
    return user.tenant_id is None or OWN_ACCOUNT in permissions


def workspace_of(request: Request) -> WorkspaceOut:
    if request.state.is_platform:
        return WorkspaceOut(kind="platform", name="CIDMS platform")
    tenant: TenantRef | None = request.state.tenant
    if tenant:
        brand = branding(tenant)
        return WorkspaceOut(kind="client", name=tenant.name, slug=tenant.slug, active=tenant.is_active, **brand)
    return WorkspaceOut(kind="none")


def branding(tenant: TenantRef) -> dict:
    """Colour, tagline and logo address for a centre's sign-in page (public: it's what the centre shows anyway)."""
    from app.core.db import scoped_session
    from app.models import TenantSettings
    with scoped_session(tenant.id) as db:
        row = db.get(TenantSettings, tenant.id)
        if row is None:
            return {}
        logo = f"/api/workspace/logo?v={row.logo_file}" if row.logo_file and row.logo_data else ""
        wordmark = f"/api/workspace/wordmark?v={row.wordmark_file}" if row.wordmark_file and row.wordmark_data else ""
        return {"brand_color": row.brand_color, "tagline": row.tagline, "logo_url": logo, "wordmark_url": wordmark}


def me_out(request: Request, user: User, sess: UserSession, permissions: set[str], roles: list[str]) -> MeOut:
    return MeOut(id=user.id, email=user.email, full_name=user.full_name, mobile=user.mobile, avatar_url=avatar_url(user),
                 roles=roles, permissions=sorted(permissions), manage_own_account=manages_own_account(user, permissions),
                 must_change_password=user.must_change_password, csrf_token=sess.csrf_token, workspace=workspace_of(request))


def avatar_url(user: User) -> str:
    return f"/api/users/{user.id}/avatar?v={user.avatar_file}" if user.avatar_file and user.avatar_data else ""


def me_from_current(request: Request, current: CurrentUser) -> MeOut:
    return me_out(request, current.user, current.session, current.permissions, current.roles)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.audit = AuditService(db)

    def login(self, request: Request, response: Response, email: str, password: str, remember: bool = False) -> MeOut:
        tenant: TenantRef | None = request.state.tenant
        if not request.state.is_platform and tenant is None:
            raise NotFound("There's no workspace at this address. Check the link you were given.")
        if tenant and not tenant.is_active:
            raise Forbidden("This workspace is suspended. Please contact CIDMS support.")
        login_limiter.hit(f"ip:{client_ip(request)}")
        tenant_id = tenant.id if tenant else None
        s = get_settings()
        now = utcnow()

        user = self.users.by_email(tenant_id, email)
        if user and is_locked(user, now):
            raise Locked("This account is locked for a few minutes after too many wrong passwords. Try again later.")
        ok, needs_rehash = verify_password(password, user.password_hash if user else None)
        if not ok or user is None or not user.is_active:
            if user is not None:
                user.failed_logins += 1
                locked = user.failed_logins >= s.max_failed_logins
                if locked:
                    user.locked_until = now + timedelta(minutes=s.lockout_minutes)
                    user.failed_logins = 0
                self.audit.record(tenant_id, user.id, "user.sign_in_failed", "user", user.id, {"locked": locked})
                self.db.commit()  # keep the count even though the request fails
            raise Unauthorized(WRONG)

        user.failed_logins = 0
        user.locked_until = None
        user.last_login_at = now
        if needs_rehash:
            user.password_hash = hash_password(password)
        sess = create_session(self.db, user, request, response, remember)
        self.audit.record(tenant_id, user.id, "user.sign_in", "user", user.id, {"remember": remember})
        self.db.flush()
        permissions, roles = load_permissions(self.db, user.id)
        request.state.user_id = str(user.id)
        return me_out(request, user, sess, permissions, roles)

    def logout(self, request: Request, response: Response) -> None:
        sess = load_session(self.db, request)
        if sess:
            sess.revoked_at = utcnow()
            self.audit.record(sess.tenant_id, sess.user_id, "user.sign_out", "user", sess.user_id)
        clear_session_cookie(response)

    def change_password(self, current: CurrentUser, current_password: str, new_password: str) -> None:
        user = current.user
        if not user.must_change_password and not manages_own_account(user, current.permissions):
            raise Forbidden("Only the owner or the centre admin can change passwords here.")
        ok, _ = verify_password(current_password, user.password_hash)
        if not ok:
            raise Invalid("Your current password isn't right.", "current_password")
        check_strength(new_password)
        if verify_password(new_password, user.password_hash)[0]:
            raise Invalid("Choose a password different from your current one.", "new_password")
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        revoke_user_sessions(self.db, user.id, keep=current.session.id_hash)  # sign out other browsers
        self.audit.record(user.tenant_id, user.id, "user.password_changed", "user", user.id)

    # ---------- forgot password ----------
    def forgot_password(self, request: Request, email: str) -> tuple[str, str, str] | None:
        """Makes a single-use reset link if the email belongs to an active account here, and returns
        (to, subject, body) for the caller to send after responding. The answer to the browser is the same
        either way, so this can't be used to find out who has an account."""
        tenant: TenantRef | None = request.state.tenant
        if not request.state.is_platform and tenant is None:
            raise NotFound("There's no workspace at this address. Check the link you were given.")
        ip = client_ip(request)
        login_limiter.hit(f"ip:{ip}")
        reset_limiter.hit(f"forgot:{email.strip().lower()}", "A reset link was sent recently. Check your email, or try again later.")
        user = self.users.by_email(tenant.id if tenant else None, email)
        if user is None or not user.is_active or (tenant and not tenant.is_active):
            return None
        if not manages_own_account(user, load_permissions(self.db, user.id)[0]):
            return None  # staff don't reset their own password; their owner or admin gives them a temporary one
        s = get_settings()
        token = secrets.token_urlsafe(32)
        now = utcnow()
        self.db.add(PasswordReset(token_hash=token_hash(token), tenant_id=user.tenant_id, user_id=user.id, created_at=now,
                                  expires_at=now + timedelta(minutes=s.password_reset_minutes), ip_address=ip or None))
        self.audit.record(user.tenant_id, user.id, "user.password_reset_requested", "user", user.id)
        events.password_reset_requested(self.db, user, ip or "")
        link = f"{request.base_url.scheme}://{request.headers.get('host', '')}/reset-password?token={token}"
        where = tenant.name if tenant else "the CIDMS platform"
        body = "\n\n".join([
            f"Hello {user.full_name},",
            f"Someone asked to reset your password for {where}. If it was you, open this link within "
            f"{s.password_reset_minutes} minutes and choose a new password:",
            link,
            "If it wasn't you, ignore this email: your password stays the same.",
            "CIDMS",
        ])
        return user.email, f"Reset your password for {where}", body

    def reset_password(self, request: Request, token: str, new_password: str) -> None:
        row = self.db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash(token)).with_for_update())
        tenant: TenantRef | None = request.state.tenant
        now = utcnow()
        if (row is None or row.used_at is not None or row.expires_at <= now
                or row.tenant_id != (tenant.id if tenant else None) or not row.user.is_active
                or not manages_own_account(row.user, load_permissions(self.db, row.user_id)[0])):
            raise Invalid("This reset link has expired or was already used. Ask for a new one.", "token")
        check_strength(new_password)
        user = row.user
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.failed_logins = 0
        user.locked_until = None
        row.used_at = now
        # Any other links for this person stop working, and every browser is signed out.
        for other in self.db.scalars(select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))):
            other.used_at = now
        revoke_user_sessions(self.db, user.id)
        self.audit.record(user.tenant_id, user.id, "user.password_reset", "user", user.id)

    # ---------- your own profile ----------
    def update_profile(self, current: CurrentUser, full_name: str, mobile: str) -> None:
        user = current.user
        changes = {}
        for field, value in (("full_name", " ".join(full_name.split())), ("mobile", mobile.strip())):
            if getattr(user, field) != value:
                changes[field] = [getattr(user, field), value]
                setattr(user, field, value)
        if changes:
            self.audit.record(user.tenant_id, user.id, "user.profile_updated", "user", user.id, changes)

    def change_email(self, current: CurrentUser, new_email: str, current_password: str) -> None:
        """The owner or admin changes the email they sign in with. Needs their password; unique in the centre.
        The session stays valid (it isn't tied to the email)."""
        user = current.user
        if not manages_own_account(user, current.permissions):
            raise Forbidden("Only the owner or the centre admin can change their sign-in email.")
        if not verify_password(current_password, user.password_hash)[0]:
            raise Invalid("Your current password isn't right.", "current_password")
        email = new_email.strip().lower()
        if email == user.email:
            raise Invalid("That's already your email.", "email")
        if self.users.by_email(user.tenant_id, email) is not None:
            raise Conflict("Someone here already uses that email.", "email")
        old, user.email = user.email, email
        self.db.flush()
        self.audit.record(user.tenant_id, user.id, "user.email_changed", "user", user.id, {"email": [old, email]})

    def set_avatar(self, current: CurrentUser, data: bytes | None) -> None:
        from app.core.storage import avatar_image
        user = current.user
        if data is None:
            user.avatar_data = user.avatar_mime = user.avatar_file = ""
            self.audit.record(user.tenant_id, user.id, "user.picture_removed", "user", user.id)
            return
        image = avatar_image(data)
        user.avatar_data, user.avatar_mime, user.avatar_file = image.data, image.mime, image.version
        self.audit.record(user.tenant_id, user.id, "user.picture_changed", "user", user.id)
