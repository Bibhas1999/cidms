"""Small job kinds: "ping" (checks the worker end to end) and "notify" (notification fan-out)."""

import uuid

from app.core.jobs import JobContext, PermanentError, job
from app.models import utcnow
from app.services import events  # noqa: F401  (registers the notification kinds)
from app.services.notifications import notify


@job("ping", max_attempts=1, timeout_s=10)
def ping(ctx: JobContext) -> dict:
    if ctx.payload.get("fail"):
        raise PermanentError("asked to fail")
    return {"pong": True, "at": utcnow().isoformat(), "worker": ctx.worker_id}


@job("notify", max_attempts=5, priority=10)
def fan_out(ctx: JobContext) -> dict:
    """notify_later(): the same arguments as notify(), sent as JSON."""
    p = dict(ctx.payload)
    for key in ("user_ids", "exclude"):
        if key in p:
            p[key] = [uuid.UUID(x) for x in p[key]]
    if not p.get("kind") or not p.get("title"):
        raise PermanentError("A notification needs a kind and a title.")
    sent = notify(ctx.db, ctx.tenant_id, **p)
    return {"recipients": len(sent)}
