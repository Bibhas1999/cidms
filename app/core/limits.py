"""Limits: request body size, and attempts per caller (sign-in, reset emails, error reports, report-link checks,
API keys). Attempts are kept in the database (rate_limit_hits), so every app process and worker counts them
together; each attempt is saved in its own short transaction, so it counts even when the request then fails."""

import math
import random

from sqlalchemy import text

from app.core.errors import TooManyRequests

MAX_JSON_BYTES = 1_000_000


class RateLimiter:
    """At most `limit` attempts per key in any `per_seconds` window (sliding), shared by all processes."""

    def __init__(self, name: str, limit: int, per_seconds: int):
        self.name, self.limit, self.per = name, limit, per_seconds

    def wait_seconds(self, key: str, record: bool = True) -> int:
        """Record an attempt and return 0, or, when over the limit, how long to wait (and record nothing).
        record=False only asks whether the key is over the limit."""
        from app.core.db import engine
        key = key[:200]
        with engine.begin() as conn:
            # One caller's attempts are counted one at a time, so two at once can't both slip under the limit.
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"{self.name}:{key}"})
            count, oldest, now = conn.execute(text(
                "SELECT count(*), min(at), now() FROM rate_limit_hits"
                " WHERE bucket = :b AND key = :k AND at > now() - make_interval(secs => :p)"),
                {"b": self.name, "k": key, "p": self.per}).one()
            if count >= self.limit:
                return max(1, math.ceil(self.per - (now - oldest).total_seconds()))
            if not record:
                return 0
            conn.execute(text("INSERT INTO rate_limit_hits (bucket, key) VALUES (:b, :k)"), {"b": self.name, "k": key})
            if random.random() < 0.01:  # noqa: S311 - housekeeping, not security
                conn.execute(text("DELETE FROM rate_limit_hits WHERE at < now() - interval '2 days'"))
        return 0

    def hit(self, key: str, message: str = "Too many attempts. Please wait a few minutes and try again.") -> None:
        if self.wait_seconds(key):
            raise TooManyRequests(message)

    def reset(self) -> None:
        """Forget every attempt in this bucket (tests)."""
        from app.core.db import engine
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM rate_limit_hits WHERE bucket = :b"), {"b": self.name})


login_limiter = RateLimiter("login", limit=20, per_seconds=300)
client_error_limiter = RateLimiter("client-error", limit=30, per_seconds=60)
reset_limiter = RateLimiter("reset-email", limit=3, per_seconds=900)  # reset emails per address


def body_limit(path: str) -> int:
    """The largest request body each path takes."""
    if path in ("/api/settings/logo", "/api/auth/avatar", "/api/test-reports/my-signature/image"):
        return 2_100_000
    if path.startswith("/api/imaging/items/") and path.endswith("/upload"):
        from app.core.config import get_settings
        return get_settings().imaging_max_upload_mb * 1024 * 1024 + 1_000_000  # DICOM uploads (checked again by the route)
    if path.startswith("/api/uploads/"):
        from app.services.uploads import MAX_CHUNK
        return MAX_CHUNK  # one piece of a resumable upload (checked again by the service)
    return MAX_JSON_BYTES


async def _too_large(send) -> None:
    body = b'{"message": "That request is too large."}'
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class BodySizeMiddleware:
    """Refuses bodies over the path's limit: at once when Content-Length says so, and otherwise by reading the body
    (up to the limit) before the app sees it, so one sent without Content-Length, or with a false one, is refused
    too. DICOM uploads stream on (their route counts the bytes itself)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith("/api/"):
            return await self.app(scope, receive, send)
        limit = body_limit(path)
        headers = {k.lower(): v for k, v in scope["headers"]}
        if headers.get(b"content-type", b"").startswith(b"application/vnd.cidms.enc+json"):
            limit = limit * 4 // 3 + 1024  # encrypted bodies are base64: a third larger
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > limit:
            return await _too_large(send)
        if scope["method"] in ("GET", "HEAD", "OPTIONS") or (path.startswith("/api/imaging/items/") and path.endswith("/upload")):
            return await self.app(scope, receive, send)

        chunks, received, more = [], 0, True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return  # the caller went away
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > limit:
                return await _too_large(send)
            chunks.append(chunk)
            more = message.get("more_body", False)
        body = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
