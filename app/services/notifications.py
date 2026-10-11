"""In-app notifications: the bell in the top bar, the Notifications page, and browser pop-ups.

    from app.services.notifications import notify
    notify(db, tenant_id, kind="bill.cancelled", title="…", body="…", link="/bills/…", severity="warning",
           roles=("owner", "admin"), exclude=[current.id])

Recipients: user_ids=[…], and/or everyone holding a permission (permission="billing.create"), and/or everyone
with one of the role codes (roles=(…)). Only active people of that client (tenant_id None: platform staff).
People who turned the kind off in their preferences are skipped, unless the kind can't be turned off.

The rows are added in the caller's transaction, so a notification exists exactly when the change it's about was
saved. On commit Postgres tells the listening app servers (NOTIFY on CHANNEL) so open browsers get it at once
over /api/notifications/stream. For a big fan-out, or from code that shouldn't wait, use notify_later() which
enqueues the "notify" background job with the same arguments.

Event helpers (one call per thing that happened) are in app/services/events.py; add a kind to KINDS there.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session

from app.models import Notification, NotificationPreference, Role, RolePermission, User, UserRole, utcnow

log = logging.getLogger("app.notifications")

CHANNEL = "sdms_notifications"   # NOTIFY payload: comma-separated user ids (never any content)
SEVERITIES = ("info", "success", "warning", "danger")
MAX_PAYLOAD = 7000               # Postgres limits a NOTIFY payload to 8000 bytes


@dataclass(frozen=True)
class Kind:
    label: str
    description: str          # shown in the preferences as what triggers it
    audience: str             # who gets it, in words
    can_mute: bool = True


KINDS: dict[str, Kind] = {}


def register_kind(code: str, label: str, description: str, audience: str, can_mute: bool = True) -> None:
    KINDS[code] = Kind(label, description, audience, can_mute)


def safe_link(link: str) -> str:
    """Only addresses inside the app ("/bills/…"): a notification can never send someone to another site."""
    link = (link or "").strip()
    if not link.startswith("/") or link.startswith("//") or "\\" in link:
        return ""
    return link[:500]


def _recipients(db: Session, tenant_id: uuid.UUID | None, user_ids: Iterable[uuid.UUID] | None, permission: str | None,
                roles: Iterable[str] | None) -> set[uuid.UUID]:
    conds = []
    ids = [uuid.UUID(str(u)) for u in (user_ids or [])]
    if ids:
        conds.append(User.id.in_(ids))
    if permission:
        conds.append(User.id.in_(select(UserRole.user_id).join(RolePermission, RolePermission.role_id == UserRole.role_id)
                                 .where(RolePermission.permission_code == permission)))
    role_codes = list(roles or [])
    if role_codes:
        conds.append(User.id.in_(select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.code.in_(role_codes))))
    if not conds:
        return set()
    same_place = User.tenant_id.is_(None) if tenant_id is None else User.tenant_id == tenant_id
    return set(db.scalars(select(User.id).where(same_place, User.is_active.is_(True), or_(*conds))))


def _muted(db: Session, user_ids: set[uuid.UUID], kind: str) -> set[uuid.UUID]:
    if not user_ids or not KINDS.get(kind, Kind("", "", "")).can_mute:
        return set()
    rows = db.execute(select(NotificationPreference.user_id, NotificationPreference.muted_kinds)
                      .where(NotificationPreference.user_id.in_(user_ids))).all()
    return {uid for uid, muted in rows if kind in (muted or [])}


def notify(db: Session, tenant_id: uuid.UUID | None, *, kind: str, title: str, body: str = "", link: str = "",
           severity: str = "info", user_ids: Iterable[uuid.UUID] | None = None, permission: str | None = None,
           roles: Iterable[str] | None = None, exclude: Iterable[uuid.UUID | None] = ()) -> list[uuid.UUID]:
    """Add a notification for each recipient; returns who got one."""
    if severity not in SEVERITIES:
        severity = "info"
    who = _recipients(db, tenant_id, user_ids, permission, roles) - {e for e in exclude if e}
    who -= _muted(db, who, kind)
    if not who:
        return []
    now = utcnow()
    db.add_all([Notification(id=uuid.uuid4(), tenant_id=tenant_id, user_id=uid, kind=kind[:60], title=title.strip()[:200],
                             body=body.strip()[:4000], link=safe_link(link), severity=severity, created_at=now) for uid in who])
    db.flush()
    signal(db, who)
    return sorted(who, key=str)


def signal(db: Session, user_ids: Iterable[uuid.UUID]) -> None:
    """Wake open streams for these people when the transaction commits (NOTIFY is transactional)."""
    chunk: list[str] = []
    for uid in user_ids:
        chunk.append(str(uid))
        if len(chunk) * 37 > MAX_PAYLOAD:
            db.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": ",".join(chunk)})
            chunk = []
    if chunk:
        db.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": ",".join(chunk)})


def notify_later(db: Session, tenant_id: uuid.UUID | None, **kwargs) -> uuid.UUID:
    """notify() in the background ("notify" job): same arguments; ids are sent as text."""
    from app.core.jobs import enqueue
    payload = {k: ([str(x) for x in v if x] if k in ("user_ids", "exclude", "roles") else v) for k, v in kwargs.items() if v is not None}
    return enqueue(db, "notify", payload, tenant_id=tenant_id, priority=10)


# ---------- reading (always for one person) ----------------------------------------------------------------------

def page(db: Session, user_id: uuid.UUID, *, unread: bool | None = None, kind: str = "", severity: str = "",
         page_no: int = 1, size: int = 20) -> tuple[list[Notification], int]:
    q = select(Notification).where(Notification.user_id == user_id)
    if unread is True:
        q = q.where(Notification.read_at.is_(None))
    elif unread is False:
        q = q.where(Notification.read_at.is_not(None))
    if kind:
        q = q.where(or_(Notification.kind == kind, Notification.kind.like(f"{kind.rstrip('.')}.%")))
    if severity in SEVERITIES:
        q = q.where(Notification.severity == severity)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Notification.created_at.desc(), Notification.id).offset((page_no - 1) * size).limit(size)).all()
    return list(rows), total


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(Notification.user_id == user_id, Notification.read_at.is_(None))) or 0


def newer_than(db: Session, user_id: uuid.UUID, since, limit: int = 20) -> list[Notification]:
    return list(db.scalars(select(Notification).where(Notification.user_id == user_id, Notification.created_at > since)
                           .order_by(Notification.created_at.desc()).limit(limit)).all())


def mark_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
    """False if there's no such notification for this person."""
    n = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id))
    if n is None:
        return False
    if n.read_at is None:
        n.read_at = utcnow()
        db.flush()
        signal(db, [user_id])
    return True


def mark_all_read(db: Session, user_id: uuid.UUID) -> int:
    count = db.execute(update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
                       .values(read_at=utcnow())).rowcount
    if count:
        db.info["wrote"] = True
        signal(db, [user_id])
    return count


# ---------- preferences -----------------------------------------------------------------------------------------

def preferences(db: Session, user_id: uuid.UUID) -> NotificationPreference:
    p = db.get(NotificationPreference, user_id)
    return p or NotificationPreference(user_id=user_id, muted_kinds=[], browser_popups=False)


def save_preferences(db: Session, user: User, muted_kinds: list[str], browser_popups: bool) -> NotificationPreference:
    muted = sorted({k for k in muted_kinds if k in KINDS and KINDS[k].can_mute})
    p = db.get(NotificationPreference, user.id)
    if p is None:
        p = NotificationPreference(user_id=user.id, tenant_id=user.tenant_id)
        db.add(p)
    p.muted_kinds = muted
    p.browser_popups = browser_popups
    p.updated_at = utcnow()
    db.flush()
    return p


def purge_old(db: Session, read_days: int = 90, any_days: int = 180) -> int:
    now = utcnow()
    return db.execute(Notification.__table__.delete().where(or_(
        Notification.read_at < now - timedelta(days=read_days), Notification.created_at < now - timedelta(days=any_days)))).rowcount
