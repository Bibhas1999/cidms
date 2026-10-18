"""Sessions, CSRF protection and permission checks.

- The browser only ever holds a random session token in an HttpOnly, SameSite=Lax cookie (Secure and
  __Host- prefixed in production). The database stores its SHA-256 hash, so a leaked database can't be
  used to sign in. JavaScript never sees the token.
- Sessions expire after inactivity and after an absolute maximum, and sign-out revokes them on the server.
- Every state-changing request needs the session's CSRF token in the X-CSRF-Token header and must come
  from the same site.
- A session belongs to one client (or to the platform) and only works at that client's address.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import DB
from app.core.errors import Forbidden, Unauthorized
from app.core.logging import client_ip
from app.core.tenancy import TenantRef
from app.models import Role, RolePermission, User, UserRole, UserSession, utcnow

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
TOUCH_EVERY = timedelta(minutes=5)  # "last seen" is written at most this often, to keep writes low


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- sessions --------------------------------------------------------

def create_session(db: Session, user: User, request: Request, response: Response, remember: bool = False) -> UserSession:
    """remember=True ("Remember me"): signed in on this computer for up to SESSION_ABSOLUTE_DAYS.
    Otherwise the cookie lasts until the browser closes, and the session at most SESSION_BROWSER_HOURS.
    Either way, SESSION_IDLE_MINUTES without using the app signs the person out."""
    s = get_settings()
    token = secrets.token_urlsafe(32)
    now = utcnow()
    lifetime = timedelta(days=s.session_absolute_days) if remember else timedelta(hours=s.session_browser_hours)
    sess = UserSession(
        id_hash=token_hash(token), user_id=user.id, tenant_id=user.tenant_id, csrf_token=secrets.token_urlsafe(32),
        created_at=now, last_seen_at=now, expires_at=now + lifetime,
        ip_address=client_ip(request) or None, user_agent=request.headers.get("user-agent", "")[:300],
    )
    db.add(sess)
    response.set_cookie(
        s.cookie_name, token, max_age=int(lifetime.total_seconds()) if remember else None,
        httponly=True, secure=s.is_production, samesite="lax", path="/",
    )
    return sess


def clear_session_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(s.cookie_name, path="/", secure=s.is_production, httponly=True, samesite="lax")


def load_session(db: Session, request: Request) -> UserSession | None:
    token = request.cookies.get(get_settings().cookie_name)
    if not token or len(token) > 100:
        return None
    sess = db.get(UserSession, token_hash(token))  # row-level security: only this client's sessions are visible
    if sess is None or sess.revoked_at is not None:
        return None
    tenant: TenantRef | None = request.state.tenant
    if sess.tenant_id != (tenant.id if tenant else None):
        return None  # a platform session used at a client address, or the other way round
    now = utcnow()
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    if sess.expires_at <= now or sess.last_seen_at + idle <= now or not sess.user.is_active:
        sess.revoked_at = now
        return None
    if now - sess.last_seen_at > TOUCH_EVERY:
        sess.last_seen_at = now
    return sess


def revoke_user_sessions(db: Session, user_id: uuid.UUID, keep: str | None = None) -> None:
    """Sign a person out everywhere (deactivated, password reset), optionally keeping the current session."""
    now = utcnow()
    for sess in db.scalars(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))):
        if sess.id_hash != keep:
            sess.revoked_at = now


# ---------- current user and permissions -------------------------------------

@dataclass
class CurrentUser:
    user: User
    session: UserSession
    tenant: TenantRef | None
    permissions: set[str] = field(default_factory=set)
    roles: list[str] = field(default_factory=list)

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def is_platform(self) -> bool:
        return self.user.tenant_id is None

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def load_permissions(db: Session, user_id: uuid.UUID) -> tuple[set[str], list[str]]:
    rows = db.execute(
        select(Role.name, RolePermission.permission_code)
        .join(UserRole, UserRole.role_id == Role.id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).all()
    return {p for _, p in rows if p}, sorted({r for r, _ in rows})


def resolve_current(request: Request, db: Session) -> CurrentUser | None:
    if hasattr(request.state, "current"):
        return request.state.current
    current = None
    sess = load_session(db, request)
    if sess is not None:
        perms, roles = load_permissions(db, sess.user_id)
        current = CurrentUser(user=sess.user, session=sess, tenant=request.state.tenant, permissions=perms, roles=roles)
        request.state.user_id = str(sess.user_id)
    request.state.current = current
    return current


def _site(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme.lower(), parts.netloc.lower()


def check_csrf(request: Request, current: CurrentUser) -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    if origin and _site(origin)[1] != request.headers.get("host", "").lower():
        raise Forbidden("Cross-site request blocked.")
    if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), current.session.csrf_token):
        raise Forbidden("Your session token is missing or out of date. Refresh the page and try again.")


def _signed_in(request: Request, db: Session, allow_password_change: bool) -> CurrentUser:
    current = resolve_current(request, db)
    if current is None:
        raise Unauthorized("Sign in to continue.")
    check_csrf(request, current)
    if current.tenant and not current.tenant.is_active:
        raise Forbidden("This workspace is suspended. Please contact CIDMS support.")
    if current.user.must_change_password and not allow_password_change:
        raise Forbidden("Set a new password to continue.", "must_change_password")
    return current


def get_current_user(request: Request, db: Session = DB) -> CurrentUser:
    """Signed in, CSRF checked, password up to date. 401 / 403 otherwise."""
    return _signed_in(request, db, allow_password_change=False)


def get_user_allowing_password_change(request: Request, db: Session = DB) -> CurrentUser:
    """For the few endpoints someone who must change their password can still use (who am I, change it, sign out)."""
    return _signed_in(request, db, allow_password_change=True)


def confirm_identity(current: CurrentUser, password: str) -> None:
    """Ask for the person's own password again before something that can't be taken back (restoring a backup).
    Wrong answers count against the sign-in limit for that person."""
    from app.core.limits import login_limiter
    from app.core.passwords import verify_password
    ok, _ = verify_password(password or "", current.user.password_hash)
    if not ok:
        login_limiter.hit(f"confirm:{current.user.id}")
        raise Forbidden("That password isn't right. Enter the password you sign in with.", "password")


def require(permission: str):
    """Dependency factory: signed in and holding the permission."""
    def dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current.can(permission):
            raise Forbidden("You don't have permission to do that.")
        return current
    return dep


def is_locked(user: User, now: datetime) -> bool:
    return user.locked_until is not None and user.locked_until > now
