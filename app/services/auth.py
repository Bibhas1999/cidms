"""Sign-in, sign-out and password changes."""

from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Forbidden, Invalid, Locked, NotFound, Unauthorized
from app.core.limits import login_limiter
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
)
from app.core.tenancy import TenantRef
from app.models import User, UserSession, utcnow
from app.repositories.users import UserRepository
from app.schemas import MeOut, WorkspaceOut
from app.services.audit import AuditService

WRONG = "That email and password don't match. Check them and try again."


def workspace_of(request: Request) -> WorkspaceOut:
    if request.state.is_platform:
        return WorkspaceOut(kind="platform", name="Supreme DMS platform")
    tenant: TenantRef | None = request.state.tenant
    if tenant:
        return WorkspaceOut(kind="client", name=tenant.name, slug=tenant.slug, active=tenant.is_active)
    return WorkspaceOut(kind="none")


def me_out(request: Request, user: User, sess: UserSession, permissions: set[str], roles: list[str]) -> MeOut:
    return MeOut(id=user.id, email=user.email, full_name=user.full_name, roles=roles, permissions=sorted(permissions),
                 must_change_password=user.must_change_password, csrf_token=sess.csrf_token, workspace=workspace_of(request))


def me_from_current(request: Request, current: CurrentUser) -> MeOut:
    return me_out(request, current.user, current.session, current.permissions, current.roles)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.audit = AuditService(db)

    def login(self, request: Request, response: Response, email: str, password: str) -> MeOut:
        tenant: TenantRef | None = request.state.tenant
        if not request.state.is_platform and tenant is None:
            raise NotFound("There's no workspace at this address. Check the link you were given.")
        if tenant and not tenant.is_active:
            raise Forbidden("This workspace is suspended. Please contact Supreme DMS support.")
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
        sess = create_session(self.db, user, request, response)
        self.audit.record(tenant_id, user.id, "user.sign_in", "user", user.id)
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
