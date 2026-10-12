"""Notifications (the bell, the Notifications page, preferences, the live stream) and background job results.

The live stream (GET /api/notifications/stream) is Server-Sent Events over the session cookie. One listener per app
process LISTENs on Postgres (NOTIFY sdms_notifications, sent when a notification is committed) and wakes the right
streams at once; each stream also looks for itself every POLL_S seconds in case that listener is down. A comment
line every HEARTBEAT_S seconds keeps proxies from closing it, and it ends after MAX_STREAM_S (the browser reconnects
by itself), when the session ends, or when the browser goes away. Checking the stream and the unread count doesn't
count as using the app, so an open tab never stops the idle sign-out.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import Paging, paging
from app.core.config import get_settings
from app.core.db import DB, scoped_session
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.jobs import cancel as cancel_job
from app.core.security import CurrentUser, get_current_user, resolve_current
from app.models import Job, JobFile, Notification, UserSession, utcnow
from app.schemas import Page
from app.services import events  # noqa: F401  (registers the notification kinds)
from app.services import notifications as svc

router = APIRouter(prefix="/api", tags=["notifications"])
log = logging.getLogger("app.notifications")

HEARTBEAT_S = 25
POLL_S = 5            # how often a stream looks for itself when the listener is down
POLL_LISTENING_S = 30  # … and as a safety net when it's up
MAX_STREAM_S = 15 * 60


# ---------- shapes ----------

class NotificationOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str
    severity: str
    read_at: datetime | None
    created_at: datetime


class CountOut(BaseModel):
    count: int


class KindOut(BaseModel):
    code: str
    label: str
    description: str
    audience: str
    can_mute: bool
    enabled: bool


class PreferencesOut(BaseModel):
    kinds: list[KindOut]
    browser_popups: bool


class PreferencesIn(BaseModel):
    muted_kinds: list[str] = Field(default_factory=list, max_length=100)
    browser_popups: bool = False


class JobOut(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    kind: str
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    attempts: int
    max_attempts: int
    last_error: str
    result: dict | None
    created_at: datetime
    finished_at: datetime | None
    file_url: str = ""


# ---------- who is asking, without counting it as activity ----------

@dataclass(frozen=True)
class Viewer:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    is_platform: bool
    session_hash: str


def quiet_viewer(request: Request) -> Viewer:
    """Signed in (same checks as get_current_user, no CSRF since it's only reads), but the session's "last seen"
    isn't moved: background checks by an open tab mustn't keep someone signed in forever."""
    tenant = getattr(request.state, "tenant", None)
    with scoped_session(tenant.id if tenant else None, platform=bool(getattr(request.state, "is_platform", False))) as db:
        current = resolve_current(request, db)
        viewer = None
        if current is not None:
            if current.tenant and not current.tenant.is_active:
                raise Forbidden("This workspace is suspended. Please contact CIDMS support.")
            if current.user.must_change_password:
                raise Forbidden("Set a new password to continue.", "must_change_password")
            viewer = Viewer(current.user.id, current.user.tenant_id, current.is_platform, current.session.id_hash)
        db.rollback()
    if viewer is None:
        raise Unauthorized("Sign in to continue.")
    return viewer


def _session_alive(db: Session, v: Viewer) -> bool:
    s = db.get(UserSession, v.session_hash)
    now = utcnow()
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    return bool(s and s.revoked_at is None and s.expires_at > now and s.last_seen_at + idle > now)


# ---------- the list, counts and reading ----------

@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(unread: bool | None = None, kind: str = Query("", max_length=60),
                       severity: Literal["", "info", "success", "warning", "danger"] = "",
                       p: Paging = Depends(paging), db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    items, total = svc.page(db, current.id, unread=unread, kind=kind, severity=severity, page_no=p.page, size=p.size)
    return Page(items=[NotificationOut.model_validate(n) for n in items], total=total, page=p.page, size=p.size)


@router.get("/notifications/unread-count", response_model=CountOut)
def unread_count(v: Viewer = Depends(quiet_viewer)):
    with scoped_session(v.tenant_id, platform=v.is_platform) as db:
        n = svc.unread_count(db, v.user_id)
        db.rollback()
    return CountOut(count=n)


@router.post("/notifications/read-all", response_model=CountOut)
def read_all(db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    svc.mark_all_read(db, current.id)
    return CountOut(count=0)


@router.post("/notifications/{notification_id}/read", response_model=CountOut)
def read_one(notification_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    if not svc.mark_read(db, current.id, notification_id):
        raise NotFound("We couldn't find that notification.")
    return CountOut(count=svc.unread_count(db, current.id))


@router.get("/notifications/preferences", response_model=PreferencesOut)
def get_preferences(db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    return _prefs_out(svc.preferences(db, current.id))


@router.put("/notifications/preferences", response_model=PreferencesOut)
def put_preferences(data: PreferencesIn, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    return _prefs_out(svc.save_preferences(db, current.user, data.muted_kinds, data.browser_popups))


@router.post("/notifications/test", response_model=CountOut)
def send_test(db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    """A notification to yourself, to check the bell and browser pop-ups work."""
    svc.notify(db, current.user.tenant_id, kind="test", user_ids=[current.id], severity="info", title="Test notification",
               body="Notifications are working on this computer.", link="/notifications")
    return CountOut(count=svc.unread_count(db, current.id))


def _prefs_out(p) -> PreferencesOut:
    muted = set(p.muted_kinds or [])
    kinds = [KindOut(code=c, label=k.label, description=k.description, audience=k.audience, can_mute=k.can_mute,
                     enabled=not (k.can_mute and c in muted)) for c, k in svc.KINDS.items()]
    return PreferencesOut(kinds=kinds, browser_popups=bool(p.browser_popups))


# ---------- the live stream ----------

class _Hub:
    """One LISTEN connection per process, waking the streams of the people a NOTIFY names."""

    def __init__(self) -> None:
        self._subs: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.listening = False

    def subscribe(self, user_id: uuid.UUID) -> tuple[asyncio.AbstractEventLoop, asyncio.Event]:
        self._ensure_started()
        entry = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._subs.setdefault(str(user_id), set()).add(entry)
        return entry

    def unsubscribe(self, user_id: uuid.UUID, entry) -> None:
        with self._lock:
            subs = self._subs.get(str(user_id))
            if subs:
                subs.discard(entry)
                if not subs:
                    self._subs.pop(str(user_id), None)

    def wake(self, payload: str) -> None:
        with self._lock:
            targets = [e for uid in payload.split(",") for e in self._subs.get(uid.strip(), ())]
        for loop, ev in targets:
            with contextlib.suppress(RuntimeError):  # that stream's loop has closed
                loop.call_soon_threadsafe(ev.set)

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="notifications-listener", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        import psycopg
        url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        while True:
            try:
                with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
                    conn.execute(f"LISTEN {svc.CHANNEL}")
                    self.listening = True
                    while True:
                        for n in conn.notifies(timeout=30):
                            self.wake(n.payload)
                        conn.execute("SELECT 1")  # notice a dropped connection even when it's quiet
            except Exception:
                log.warning("notification listener lost its connection; streams fall back to polling", exc_info=True)
            self.listening = False
            time.sleep(5)


hub = _Hub()


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


def _check(v: Viewer, sent: set[uuid.UUID], since: datetime) -> tuple[bool, int, list[NotificationOut]]:
    with scoped_session(v.tenant_id, platform=v.is_platform) as db:
        alive = _session_alive(db, v)
        count = svc.unread_count(db, v.user_id) if alive else 0
        # A notification's time is when it was written, which can be a moment before it was committed: look back a
        # little and skip the ones already sent.
        fresh = [NotificationOut.model_validate(n) for n in svc.newer_than(db, v.user_id, since - timedelta(minutes=2), limit=50)
                 if n.id not in sent] if alive else []
        db.rollback()
    return alive, count, list(reversed(fresh))


def _start(v: Viewer) -> tuple[datetime, list[uuid.UUID], int]:
    with scoped_session(v.tenant_id, platform=v.is_platform) as db:
        since = db.scalar(select(Notification.created_at).where(Notification.user_id == v.user_id)
                          .order_by(Notification.created_at.desc()).limit(1)) or utcnow()
        recent = list(db.scalars(select(Notification.id).where(Notification.user_id == v.user_id,
                                                               Notification.created_at > since - timedelta(minutes=2))).all())
        count = svc.unread_count(db, v.user_id)
        db.rollback()
    return since, recent, count


async def _events(request: Request, v: Viewer):
    loop_entry = hub.subscribe(v.user_id)
    _, wake = loop_entry
    sent: set[uuid.UUID] = set()
    started = time.monotonic()
    try:
        since, recent, count = await run_in_threadpool(_start, v)
        sent.update(recent)
        yield f"retry: 5000\n{_sse('unread', {'count': count})}"
        last_beat = last_check = time.monotonic()
        while time.monotonic() - started < MAX_STREAM_S:
            poll = POLL_LISTENING_S if hub.listening else POLL_S
            timeout = max(0.05, min(HEARTBEAT_S - (time.monotonic() - last_beat), poll - (time.monotonic() - last_check),
                                    MAX_STREAM_S - (time.monotonic() - started)))
            try:
                await asyncio.wait_for(wake.wait(), timeout)
                woke = True
            except TimeoutError:
                woke = False
            wake.clear()
            if await request.is_disconnected():
                break
            if woke or time.monotonic() - last_check >= poll:
                last_check = time.monotonic()
                alive, new_count, fresh = await run_in_threadpool(_check, v, sent, since)
                if not alive:
                    yield _sse("end", {"reason": "signed_out"})
                    return
                for n in fresh:
                    sent.add(n.id)
                    since = max(since, n.created_at)
                    yield _sse("notification", n.model_dump(mode="json"))
                if new_count != count or fresh:
                    count = new_count
                    yield _sse("unread", {"count": count})
                if len(sent) > 500:
                    sent = set(list(sent)[-200:])
            if time.monotonic() - last_beat >= HEARTBEAT_S:
                last_beat = time.monotonic()
                yield ": ping\n\n"
        yield _sse("reconnect", {})
    finally:
        hub.unsubscribe(v.user_id, loop_entry)


@router.get("/notifications/stream")
async def stream(request: Request, v: Viewer = Depends(quiet_viewer)):
    return StreamingResponse(_events(request, v), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ---------- background job results ----------

def _own_job(db: Session, current: CurrentUser, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)  # row-level security: only this client's jobs
    if job is None or (job.created_by != current.id and not current.is_platform):
        raise NotFound("We couldn't find that task.")
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def job_status(job_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    job = _own_job(db, current, job_id)
    has_file = db.scalar(select(JobFile.id).where(JobFile.job_id == job.id, JobFile.expires_at > utcnow()).limit(1))
    out = JobOut.model_validate(job)
    out.file_url = f"/api/jobs/{job.id}/file" if has_file else ""
    return out


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def job_cancel(job_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    job = _own_job(db, current, job_id)
    if not cancel_job(db, job.id):
        raise NotFound("That task has already started or finished, so it can't be cancelled.")
    db.refresh(job)
    return JobOut.model_validate(job)


@router.get("/jobs/{job_id}/file")
def job_file(job_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    job = _own_job(db, current, job_id)
    f = db.scalar(select(JobFile).where(JobFile.job_id == job.id).order_by(JobFile.created_at.desc()).limit(1))
    if f is None or f.expires_at <= utcnow():
        raise NotFound("This file has expired or isn't ready yet. Make the export again.")
    ascii_name = f.filename.encode("ascii", "ignore").decode().replace('"', "") or "export"
    return Response(bytes(f.data), media_type=f.mime, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.filename)}"})
