"""Live monitoring for development (ENVIRONMENT=development only; never installed otherwise).

Keeps the last few hundred requests, errors and slow database queries in memory and streams them to the
Dev monitor page (/dev/monitor) with GET /api/dev/stream (Server-Sent Events). SQL is recorded without its
parameters, so no patient data is copied into the monitor."""

import logging
import threading
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import request_id

SLOW_SQL_MS = 50
KEEP = 300

_queries: ContextVar[list | None] = ContextVar("dev_queries", default=None)


@dataclass
class Monitor:
    seq: int = 0
    started: float = field(default_factory=time.time)
    events: deque = field(default_factory=lambda: deque(maxlen=KEEP * 3))
    durations: deque = field(default_factory=lambda: deque(maxlen=1000))  # (time, ms, status) of recent requests
    totals: dict = field(default_factory=lambda: {"requests": 0, "errors": 0, "server_errors": 0, "slow_queries": 0, "queries": 0})
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, kind: str, data: dict) -> None:
        with self.lock:
            self.seq += 1
            self.events.append({"seq": self.seq, "kind": kind, "at": time.time(), **data})

    def since(self, seq: int) -> list[dict]:
        with self.lock:
            return [e for e in self.events if e["seq"] > seq]

    def stats(self) -> dict:
        now = time.time()
        with self.lock:
            recent = [d for d in self.durations if d[0] > now - 60]
            totals = dict(self.totals)
        ms = sorted(d[1] for d in recent)
        p95 = ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else 0
        return {"uptime_s": int(now - self.started), "per_minute": len(recent),
                "avg_ms": round(sum(ms) / len(ms), 1) if ms else 0, "p95_ms": round(p95, 1),
                "errors_per_minute": sum(1 for d in recent if d[2] >= 400), **totals}


monitor = Monitor()


def _skip(path: str) -> bool:
    return path.startswith("/api/dev/") or not path.startswith("/api/")


class DevMonitorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _skip(request.url.path):
            return await call_next(request)
        queries: list = []
        token = _queries.set(queries)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            ms = round((time.perf_counter() - start) * 1000, 1)
            tenant = getattr(request.state, "tenant", None)
            with monitor.lock:
                monitor.totals["requests"] += 1
                if status >= 400:
                    monitor.totals["errors"] += 1
                if status >= 500:
                    monitor.totals["server_errors"] += 1
                monitor.durations.append((time.time(), ms, status))
            monitor.add("request", {"method": request.method, "path": request.url.path, "status": status, "ms": ms,
                                    "queries": len(queries), "sql_ms": round(sum(queries), 1),
                                    "tenant": tenant.slug if tenant else None, "request_id": request_id.get()})
            _queries.reset(token)


class _ErrorHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            detail = ""
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                detail = f"{type(exc).__name__}: {exc}"[:500]
            monitor.add("error", {"level": record.levelname, "logger": record.name, "message": record.getMessage()[:500],
                                  "detail": detail, "request_id": request_id.get()})
        except Exception:  # noqa: S110 - the monitor must never break logging
            pass


def _watch_sql(engine) -> None:
    from sqlalchemy import event

    @event.listens_for(engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("dev_started", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        started = conn.info.get("dev_started")
        if not started:
            return
        ms = (time.perf_counter() - started.pop()) * 1000
        queries = _queries.get()
        if queries is not None:
            queries.append(ms)
        with monitor.lock:
            monitor.totals["queries"] += 1
        if ms >= SLOW_SQL_MS:
            with monitor.lock:
                monitor.totals["slow_queries"] += 1
            monitor.add("slow_sql", {"ms": round(ms, 1), "sql": " ".join(statement.split())[:600], "request_id": request_id.get()})


def install(app, engine) -> None:
    """Called by create_app() in development only."""
    app.add_middleware(DevMonitorMiddleware)
    handler = _ErrorHandler(level=logging.WARNING)
    logging.getLogger().addHandler(handler)
    _watch_sql(engine)
