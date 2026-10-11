"""Small in-process limits: request body size, and attempts per IP for sign-in and error reports.
(One app process locally; a shared store such as Redis replaces this when there are several.)"""

import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.errors import TooManyRequests

MAX_JSON_BYTES = 1_000_000


class RateLimiter:
    def __init__(self, limit: int, per_seconds: int):
        self.limit, self.per = limit, per_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, message: str = "Too many attempts. Please wait a few minutes and try again.") -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - self.per:
                q.popleft()
            if len(q) >= self.limit:
                raise TooManyRequests(message)
            q.append(now)
            if len(self._hits) > 50_000:  # forget idle callers so memory stays bounded
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.per}

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter(limit=20, per_seconds=300)
client_error_limiter = RateLimiter(limit=30, per_seconds=60)
reset_limiter = RateLimiter(limit=3, per_seconds=900)  # reset emails per address


class BodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        limit = 2_100_000 if request.url.path in ("/api/settings/logo", "/api/auth/avatar", "/api/test-reports/my-signature/image") else MAX_JSON_BYTES
        if request.url.path.startswith("/api/imaging/items/") and request.url.path.endswith("/upload"):
            from app.core.config import get_settings
            limit = get_settings().imaging_max_upload_mb * 1024 * 1024 + 1_000_000  # DICOM uploads (checked again by the route)
        if request.url.path.startswith("/api/") and length and length.isdigit() and int(length) > limit:
            return JSONResponse({"message": "That request is too large."}, status_code=413)
        return await call_next(request)
