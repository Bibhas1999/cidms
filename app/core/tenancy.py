"""Which client a request is for, from its address: <slug>.<base domain> is a client,
<platform subdomain>.<base domain> is the platform admin panel, anything else is neither."""

import threading
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import get_settings

CACHE_SECONDS = 30


@dataclass(frozen=True)
class TenantRef:
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    status: str

    @property
    def is_active(self) -> bool:
        return self.status == "active"


_cache: dict[str, tuple[float, TenantRef | None]] = {}
_lock = threading.Lock()


def forget_tenant(slug: str | None = None) -> None:
    with _lock:
        if slug:
            _cache.pop(slug, None)
        else:
            _cache.clear()


def lookup_tenant(slug: str) -> TenantRef | None:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(slug)
        if hit and hit[0] > now:
            return hit[1]
    from app.core.db import scoped_session
    from app.models import Tenant
    # Finding a client by its address is the one read that happens before we know the client.
    with scoped_session(platform=True) as db:
        row = db.execute(select(Tenant.id, Tenant.slug, Tenant.name, Tenant.kind, Tenant.status).where(Tenant.slug == slug)).first()
        db.rollback()
    ref = TenantRef(*row) if row else None
    with _lock:
        _cache[slug] = (now + CACHE_SECONDS, ref)
    return ref


def classify_host(host: str) -> tuple[str, str | None]:
    """("platform", None) | ("client", slug) | ("none", None)."""
    s = get_settings()
    host = host.split(":")[0].strip().lower().rstrip(".")
    base = s.base_domain.lower()
    if host == f"{s.platform_subdomain}.{base}":
        return "platform", None
    if host.endswith("." + base):
        label = host[: -len(base) - 1]
        if label and "." not in label:
            return "client", label
    return "none", None


class TenancyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        kind, slug = classify_host(request.headers.get("host", ""))
        request.state.is_platform = kind == "platform"
        request.state.tenant = None
        request.state.unknown_workspace = False
        if kind == "client" and slug:
            from starlette.concurrency import run_in_threadpool
            tenant = await run_in_threadpool(lookup_tenant, slug)
            request.state.tenant = tenant
            request.state.unknown_workspace = tenant is None
        return await call_next(request)
