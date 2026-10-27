"""API keys: making, rolling and revoking them, checking one on a call to /api/v1, the per-key rate limit and
the log of calls.

A key looks like  sdms_live_Ab3dE6gH_<43 random letters and digits>  (about 256 random bits). The first part
(the prefix) is kept so people can tell keys apart in lists and logs; the whole key is shown once, when it is
made, and only its SHA-256 is stored, so a leaked database can't be used to call the API.

Keys only ever reach medical data: patients, the test catalogue without prices, ordered tests and their
progress without amounts, signed reports, imaging studies and referring doctors. Nothing financial.
"""

import hashlib
import hmac
import ipaddress
import random
import re
import secrets
import string
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.db import scoped_session
from app.core.errors import Conflict, Forbidden, Invalid, NotFound, TooManyRequests, Unauthorized
from app.core.limits import RateLimiter
from app.core.security import CurrentUser
from app.core.tenancy import TenantRef
from app.models import ApiKey, ApiRequest, utcnow
from app.services.audit import AuditService

# What a key may be allowed to read. Medical data only: there is deliberately no scope for bills or money.
SCOPES: dict[str, str] = {
    "patients:read": "Patients: name, patient number, age, gender, mobile, email and address.",
    "tests:read": "The test catalogue: test names, codes, departments and modality (X-ray, CT…). No prices.",
    "orders:read": "Tests ordered for patients and their progress (billed, scanned, reported, delivered), accession numbers, "
                   "referring doctor and times. No amounts, discounts or payments.",
    "reports:read": "Signed and amended test reports: findings, impression, the signing doctor and when, and the PDF.",
    "images:read": "Imaging studies: StudyInstanceUID, modality, number of series and images.",
    "doctors:read": "Referring doctors: name and qualification.",
}

KEY_PREFIX = "sdms_live_"
_ALPHABET = string.ascii_letters + string.digits
KEY_PATTERN = re.compile(r"^sdms_live_[A-Za-z0-9]{8}_[A-Za-z0-9]{43}$")
MAX_ACTIVE_KEYS = 25
TZ = ZoneInfo("Asia/Kolkata")

RATE_LIMIT_PER_MINUTE = 600
TOUCH_EVERY_SECONDS = 60          # "last used" is written at most once a minute per key
RETENTION_DAYS = 30               # the call log keeps this many days
_PRUNE_CHANCE = 0.01              # roughly one call in a hundred clears out the centre's old log rows


def _random(n: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> tuple[str, str, str]:
    """(the key to show once, its prefix for lists, its SHA-256 to store)."""
    prefix = KEY_PREFIX + _random(8)
    key = f"{prefix}_{_random(43)}"
    return key, prefix, key_hash(key)


def key_status(key: ApiKey, now: datetime | None = None) -> str:
    now = now or utcnow()
    if key.revoked_at is not None:
        return "revoked" if key.revoked_at <= now else "rolling"
    if key.expires_at is not None and key.expires_at <= now:
        return "expired"
    return "active"


def _ips(key: ApiKey) -> list[str]:
    return [str(n) for n in (key.allowed_ips or [])]


def key_out(key: ApiKey) -> dict:
    return {
        "id": key.id, "name": key.name, "prefix": key.prefix, "scopes": list(key.scopes or []), "allowed_ips": _ips(key),
        "expires_at": key.expires_at, "created_by_name": key.created_by_name, "created_at": key.created_at,
        "last_used_at": key.last_used_at, "last_used_ip": str(key.last_used_ip) if key.last_used_ip else None,
        "revoked_at": key.revoked_at, "revoked_by_name": key.revoked_by_name, "replaced_by": key.replaced_by,
        "status": key_status(key),
    }


def end_of_day(d: date) -> datetime:
    """A date someone picked ("expires on 31 Dec") means the end of that day in India."""
    return datetime.combine(d + timedelta(days=1), datetime.min.time(), TZ) - timedelta(seconds=1)


# ---------- managing keys (Settings → API & integrations) ---------------------------------------------

class ApiKeyService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id

    def _audit(self, action: str, key: ApiKey, extra: dict | None = None) -> None:
        AuditService(self.db).record(self.tenant_id, self.current.id, action, "api_key", key.id,
                                     {"name": key.name, "prefix": key.prefix, **(extra or {})})

    def all(self) -> list[ApiKey]:
        return list(self.db.scalars(select(ApiKey).where(ApiKey.tenant_id == self.tenant_id)
                                    .order_by(ApiKey.created_at.desc(), ApiKey.id)))

    def get(self, key_id: uuid.UUID, lock: bool = False) -> ApiKey:
        q = select(ApiKey).where(ApiKey.tenant_id == self.tenant_id, ApiKey.id == key_id)
        key = self.db.scalar(q.with_for_update() if lock else q)
        if key is None:
            raise NotFound("We couldn't find that API key.")
        return key

    def _active_count(self) -> int:
        now = utcnow()
        return self.db.scalar(select(func.count()).select_from(ApiKey).where(
            ApiKey.tenant_id == self.tenant_id,
            or_(ApiKey.revoked_at.is_(None), ApiKey.revoked_at > now),
            or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now))) or 0

    def _make(self, name: str, scopes: list[str], allowed_ips: list[str], expires_at: datetime | None) -> tuple[ApiKey, str]:
        secret, prefix, digest = new_key()
        key = ApiKey(tenant_id=self.tenant_id, name=name, prefix=prefix, secret_hash=digest, scopes=scopes,
                     allowed_ips=[ipaddress.ip_network(n, strict=False) for n in allowed_ips], expires_at=expires_at,
                     created_by=self.current.id, created_by_name=self.current.user.full_name, created_at=utcnow())
        self.db.add(key)
        self.db.flush()
        return key, secret

    def create(self, name: str, scopes: list[str], allowed_ips: list[str], expires_on: date | None) -> tuple[ApiKey, str]:
        unknown = set(scopes) - set(SCOPES)
        if unknown or not scopes:
            raise Invalid("Choose what the key may read.", "scopes")
        expires_at = None
        if expires_on is not None:
            expires_at = end_of_day(expires_on)
            if expires_at <= utcnow():
                raise Invalid("Pick a date from today on, or leave it empty for a key that doesn't expire.", "expires_on")
        if self._active_count() >= MAX_ACTIVE_KEYS:
            raise Conflict(f"A centre can have up to {MAX_ACTIVE_KEYS} working keys. Revoke one you no longer use first.")
        key, secret = self._make(name, scopes, allowed_ips, expires_at)
        self._audit("api_key.created", key, {"scopes": scopes, "allowed_ips": allowed_ips,
                                             "expires_at": expires_at.isoformat() if expires_at else None})
        return key, secret

    def revoke(self, key_id: uuid.UUID) -> ApiKey:
        key = self.get(key_id, lock=True)
        now = utcnow()
        if key.revoked_at is not None and key.revoked_at <= now:
            raise Conflict("That key is already revoked.")
        key.revoked_at = now
        key.revoked_by = self.current.id
        key.revoked_by_name = self.current.user.full_name
        self._audit("api_key.revoked", key)
        return key

    def roll(self, key_id: uuid.UUID, grace_hours: int) -> tuple[ApiKey, str]:
        """A new key with the same name, scopes, addresses and expiry. The old one stops working now, or after
        the grace period so the other system can switch over without a gap."""
        old = self.get(key_id, lock=True)
        status = key_status(old)
        if status != "active":
            raise Conflict({"rolling": "That key has already been replaced.", "revoked": "That key is revoked.",
                            "expired": "That key has expired. Create a new one instead."}[status])
        new, secret = self._make(old.name, list(old.scopes), _ips(old), old.expires_at)
        old.revoked_at = utcnow() + timedelta(hours=grace_hours)
        old.revoked_by = self.current.id
        old.revoked_by_name = self.current.user.full_name
        old.replaced_by = new.id
        self._audit("api_key.rolled", old, {"new_prefix": new.prefix, "grace_hours": grace_hours,
                                            "old_stops_at": old.revoked_at.isoformat()})
        return new, secret

    def usage(self, key_id: uuid.UUID | None, page: int, size: int) -> tuple[list[tuple[ApiRequest, str, str]], int]:
        where = [ApiRequest.tenant_id == self.tenant_id]
        if key_id is not None:
            self.get(key_id)
            where.append(ApiRequest.key_id == key_id)
        total = self.db.scalar(select(func.count()).select_from(ApiRequest).where(*where)) or 0
        rows = self.db.execute(
            select(ApiRequest, func.coalesce(ApiKey.name, ""), func.coalesce(ApiKey.prefix, ""))
            .outerjoin(ApiKey, ApiKey.id == ApiRequest.key_id).where(*where)
            .order_by(ApiRequest.created_at.desc(), ApiRequest.id.desc()).offset((page - 1) * size).limit(size)
        ).all()
        return [tuple(r) for r in rows], total


# ---------- checking a key on a call --------------------------------------------------------------------

@dataclass
class ApiCaller:
    key_id: uuid.UUID
    tenant: TenantRef
    name: str
    prefix: str
    scopes: set[str] = field(default_factory=set)
    expires_at: datetime | None = None


def authenticate(db: Session, tenant: TenantRef | None, raw: str, ip: str) -> ApiCaller:
    if tenant is None:
        raise Unauthorized("API keys work only at your centre's own address, e.g. https://<centre>.supremedms.in/api/v1.")
    raw = (raw or "").strip()
    if not raw:
        raise Unauthorized("Send your API key in the Authorization header: Authorization: Bearer sdms_live_…")
    if not KEY_PATTERN.match(raw):
        raise Unauthorized("That API key isn't valid.")
    digest = key_hash(raw)
    # Row-level security limits this to the centre at this address, so another centre's key is never found.
    key = db.scalar(select(ApiKey).where(ApiKey.secret_hash == digest))
    if key is None or key.tenant_id != tenant.id or not hmac.compare_digest(key.secret_hash, digest):
        raise Unauthorized("That API key isn't valid.")
    now = utcnow()
    if key.revoked_at is not None and key.revoked_at <= now:
        raise Unauthorized("That API key has been revoked.")
    if key.expires_at is not None and key.expires_at <= now:
        raise Unauthorized("That API key has expired.")
    if not tenant.is_active:
        raise Forbidden("This workspace is suspended. Please contact CIDMS support.")
    if key.allowed_ips:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            addr = None
        if addr is None or not any(addr in ipaddress.ip_network(str(n), strict=False) for n in key.allowed_ips):
            raise Forbidden(f"This API key can't be used from {ip or 'this address'}. Add it to the key's allowed IP addresses.")
    return ApiCaller(key_id=key.id, tenant=tenant, name=key.name, prefix=key.prefix, scopes=set(key.scopes or []),
                     expires_at=key.expires_at)


class RateLimited(TooManyRequests):
    def __init__(self, retry_after: int):
        super().__init__(f"Too many requests for this API key. Try again in {retry_after} seconds.")
        self.retry_after = retry_after


class KeyRateLimiter(RateLimiter):
    """Calls per API key in a sliding minute, shared by every app process."""

    def __init__(self, limit: int, per_seconds: int = 60):
        super().__init__("api-key", limit, per_seconds)

    def hit(self, key_id: uuid.UUID) -> None:  # type: ignore[override]
        wait = self.wait_seconds(str(key_id))
        if wait:
            raise RateLimited(wait)


rate_limiter = KeyRateLimiter(RATE_LIMIT_PER_MINUTE)

_touched: dict[uuid.UUID, float] = {}
_touch_lock = threading.Lock()


def _should_touch(key_id: uuid.UUID) -> bool:
    now = time.monotonic()
    with _touch_lock:
        if now - _touched.get(key_id, -1e9) < TOUCH_EVERY_SECONDS:
            return False
        _touched[key_id] = now
        if len(_touched) > 10_000:
            _touched.clear()
        return True


def forget_touches() -> None:
    with _touch_lock:
        _touched.clear()


def record_call(tenant_id: uuid.UUID, key_id: uuid.UUID | None, method: str, path: str, status: int, duration_ms: int,
                ip: str, request_id: str) -> None:
    """Log one call (never its body), note when the key was last used, and now and then clear out old log rows."""
    with scoped_session(tenant_id) as db, db.begin():
        db.add(ApiRequest(tenant_id=tenant_id, key_id=key_id, method=method[:8], path=path[:300], status=status,
                          duration_ms=duration_ms, ip_address=ip or None, request_id=request_id[:64], created_at=utcnow()))
        if key_id is not None and status < 400 and _should_touch(key_id):
            cutoff = utcnow() - timedelta(seconds=TOUCH_EVERY_SECONDS)
            db.execute(update(ApiKey).where(ApiKey.id == key_id, or_(ApiKey.last_used_at.is_(None), ApiKey.last_used_at < cutoff))
                       .values(last_used_at=utcnow(), last_used_ip=ip or None))
        if random.random() < _PRUNE_CHANCE:  # noqa: S311 - not security related
            db.execute(delete(ApiRequest).where(ApiRequest.tenant_id == tenant_id,
                                                ApiRequest.created_at < utcnow() - timedelta(days=RETENTION_DAYS)))
