"""Structured JSON logs with a per-request ID, the client and the person, so one line tells the whole story."""

import ipaddress
import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

request_id: ContextVar[str] = ContextVar("request_id", default="-")
# Who is calling (IP address, browser), for the activity log.
request_client: ContextVar[tuple[str, str]] = ContextVar("request_client", default=("", ""))

SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
# Never written to logs, whatever a caller sends.
SECRET_KEYS = re.compile(r"password|token|secret|cookie|authorization", re.IGNORECASE)


def client_ip(request: Request) -> str:
    """The caller's IP, or "" if it isn't one. Only the last X-Forwarded-For entry is trusted: the one our own
    proxy appended."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    candidate = (forwarded or (request.client.host if request.client else ""))[:45]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ""


def redact(data: dict) -> dict:
    return {k: ("[redacted]" if SECRET_KEYS.search(k) else v) for k, v in data.items()}


class JsonFormatter(logging.Formatter):
    FIELDS = ("method", "path", "status", "duration_ms", "tenant", "user_id", "client_error")

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
        }
        for key in self.FIELDS:
            if hasattr(record, key):
                data[key] = getattr(record, key)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our request log below


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Keep a caller's request ID only if it's plainly an ID (it ends up in logs and the activity log).
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id.set(rid)
        client_token = request_client.set((client_ip(request), request.headers.get("user-agent", "")[:300]))
        start = time.perf_counter()
        status = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Last resort for anything no handler caught. Handled here, inside the request, so the log line
                # and the reply both carry the request ID people can quote to support.
                logging.getLogger("app").exception("Unhandled error on %s %s", request.method, request.url.path)
                response = JSONResponse({"message": "Something went wrong on our side. It's been logged; please try again.",
                                         "request_id": rid}, status_code=500)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            if request.url.path.startswith("/api/") or status >= 500:
                tenant = getattr(request.state, "tenant", None)
                logging.getLogger("app.request").info(
                    "request", extra={
                        "method": request.method, "path": request.url.path, "status": status,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                        "tenant": tenant.slug if tenant else None,
                        "user_id": getattr(request.state, "user_id", None),
                    })
            request_id.reset(token)
            request_client.reset(client_token)
