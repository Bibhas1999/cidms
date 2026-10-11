"""Background jobs: a queue kept in Postgres (table `jobs`), run by the worker (`python -m app.worker`).

Why Postgres: no extra service to run; a job is enqueued in the same transaction as the change that caused it,
so it exists exactly when that change was saved; workers claim jobs with SELECT … FOR UPDATE SKIP LOCKED, so
any number of them can run side by side without taking the same job.

Enqueue (in a request, a service or another job):

    from app.core.jobs import enqueue
    job_id = enqueue(db, "export", {"function": "bills_xlsx", "params": {...}}, created_by=current.id)

    - tenant_id defaults to the session's client (db.info["tenant_id"]); pass tenant_id=None from a platform
      session for platform work. Row-level security means a client session can only enqueue for its own client.
    - run_at=datetime  runs it later; dedupe_key="..."  makes a second enqueue a no-op while one with the same
      (client, kind, key) is still queued or running (the existing job's id is returned).
    - Nothing runs until the transaction commits (the worker can't see uncommitted rows).

Add a job kind: create a module in app/jobs/ (every module there is imported by the worker and by enqueue) and
decorate a function that takes a JobContext:

    # app/jobs/my_thing.py
    from app.core.jobs import JobContext, PermanentError, job

    @job("my_thing", max_attempts=3, timeout_s=120)
    def my_thing(ctx: JobContext) -> dict | None:
        ...                          # ctx.db is a session scoped to the job's client (row-level security applies)
        ctx.actor()                  # the person who enqueued it, with their current permissions (CurrentUser)
        ctx.save_file(name, mime, data)   # keep a produced file 24 h; downloadable at GET /api/jobs/{id}/file
        return {"rows": 10}          # saved as the job's result (JSON)

    - The handler's database work and marking the job done commit together, in one transaction.
    - Raise PermanentError("…") (or a DomainError) for a failure retrying can't fix; any other exception is retried with
      exponential backoff (BACKOFF_BASE_S · 2^(attempt-1), at most BACKOFF_MAX_S) until max_attempts.
    - Handlers must be safe to run twice (a worker can die after the work but before the commit).

Recurring jobs: add a Schedule to SCHEDULES in app/worker.py.
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.db import scoped_session
from app.models import Job, JobFile, utcnow

log = logging.getLogger("app.jobs")

BACKOFF_BASE_S = 15
BACKOFF_MAX_S = 60 * 60
STALE_LOCK_MINUTES = 10
FILE_TTL = timedelta(hours=24)
MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_TIMEOUT_S = 300
_SESSION = object()  # "use the session's client"


class PermanentError(Exception):
    """A failure retrying won't fix (bad payload, missing record): the job fails at once."""


@dataclass(frozen=True)
class JobKind:
    kind: str
    fn: Callable[[JobContext], dict | None]
    max_attempts: int = 5
    priority: int = 0
    timeout_s: int = DEFAULT_TIMEOUT_S
    notify_failure: bool = False  # tell the person who enqueued it when it finally fails


JOBS: dict[str, JobKind] = {}


def job(kind: str, *, max_attempts: int = 5, priority: int = 0, timeout_s: int = DEFAULT_TIMEOUT_S, notify_failure: bool = False):
    """Register a handler for a job kind (see the module docstring)."""
    def wrap(fn):
        if kind in JOBS and JOBS[kind].fn is not fn:
            raise RuntimeError(f"Job kind {kind!r} is registered twice")
        JOBS[kind] = JobKind(kind, fn, max_attempts, priority, timeout_s, notify_failure)
        return fn
    return wrap


_loaded = False
_load_lock = threading.Lock()


def load_job_modules() -> None:
    """Import every module in app/jobs so their @job handlers are registered."""
    global _loaded
    if _loaded:
        return
    with _load_lock:
        if _loaded:
            return
        import app.jobs as pkg
        for mod in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module(f"{pkg.__name__}.{mod.name}")
        _loaded = True


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


# ---------- enqueueing ----------------------------------------------------------------------------------------

def enqueue(db: Session, kind: str, payload: dict | None = None, tenant_id: Any = _SESSION, run_at: datetime | None = None,
            dedupe_key: str | None = None, *, priority: int | None = None, max_attempts: int | None = None,
            created_by: uuid.UUID | None = None) -> uuid.UUID:
    """Add a job; returns its id (or, with dedupe_key, the id of the live job already waiting)."""
    load_job_modules()
    spec = JOBS.get(kind)
    if spec is None:
        raise ValueError(f"Unknown job kind {kind!r}: register it with @job in a module under app/jobs/")
    if tenant_id is _SESSION:
        tenant_id = db.info.get("tenant_id")
    stmt = pg_insert(Job).values(
        id=uuid.uuid4(), tenant_id=tenant_id, kind=kind, payload=_jsonable(payload or {}), status="queued",
        priority=spec.priority if priority is None else priority, run_at=run_at or utcnow(), attempts=0,
        max_attempts=max_attempts or spec.max_attempts, last_error="", dedupe_key=dedupe_key, created_by=created_by,
        created_at=utcnow(),
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "kind", "dedupe_key"],
            index_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"))
    new_id = db.scalar(stmt.returning(Job.id))
    db.info["wrote"] = True
    if new_id is not None:
        return new_id
    existing = db.scalar(select(Job.id).where(
        Job.tenant_id.is_(None) if tenant_id is None else Job.tenant_id == tenant_id,
        Job.kind == kind, Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running"))))
    if existing is None:  # it finished between the insert and this read: enqueue afresh
        return enqueue(db, kind, payload, tenant_id, run_at, dedupe_key, priority=priority, max_attempts=max_attempts, created_by=created_by)
    return existing


def cancel(db: Session, job_id: uuid.UUID) -> bool:
    """Cancel a job that hasn't started. Returns False if it's already running or finished."""
    n = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                   .values(status="cancelled", finished_at=utcnow())).rowcount
    return bool(n)


# ---------- what a handler gets ----------------------------------------------------------------------------------

@dataclass
class JobContext:
    id: uuid.UUID
    kind: str
    tenant_id: uuid.UUID | None
    payload: dict
    attempt: int
    max_attempts: int
    created_by: uuid.UUID | None
    db: Session
    worker_id: str = ""
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("app.jobs"))

    def actor(self):
        """The person who enqueued the job, as a CurrentUser with their permissions now (None if no one did)."""
        if self.created_by is None:
            return None
        from app.core.security import CurrentUser, load_permissions
        from app.core.tenancy import TenantRef
        from app.models import Tenant, User
        user = self.db.get(User, self.created_by)
        if user is None or not user.is_active:
            raise PermanentError("The person who asked for this is no longer active.")
        tenant = self.db.get(Tenant, self.tenant_id) if self.tenant_id else None
        ref = TenantRef(tenant.id, tenant.slug, tenant.name, tenant.kind, tenant.status) if tenant else None
        perms, roles = load_permissions(self.db, user.id)
        return CurrentUser(user=user, session=None, tenant=ref, permissions=perms, roles=roles)  # type: ignore[arg-type]

    def system_actor(self) -> SystemActor:
        """Stands in for a person when a scheduled job calls a service that reads current.user.tenant_id."""
        return SystemActor(self.tenant_id)

    def save_file(self, filename: str, mime: str, data: bytes, ttl: timedelta = FILE_TTL) -> JobFile:
        if len(data) > MAX_FILE_BYTES:
            raise PermanentError(f"The file is too big ({len(data) // 1_048_576} MB).")
        f = JobFile(tenant_id=self.tenant_id, job_id=self.id, filename=filename[:200], mime=mime[:100], size_bytes=len(data),
                    data=data, expires_at=utcnow() + ttl)
        self.db.add(f)
        self.db.flush()
        return f


@dataclass
class _SystemUser:
    tenant_id: uuid.UUID | None
    id: None = None
    full_name: str = "Supreme DMS"
    is_active: bool = True


class SystemActor:
    """A minimal CurrentUser look-alike for scheduled work (no person; can do nothing permission-gated)."""
    def __init__(self, tenant_id: uuid.UUID | None):
        self.user = _SystemUser(tenant_id)
        self.id = None
        self.tenant = None
        self.permissions: set[str] = set()
        self.roles: list[str] = []
        self.is_platform = tenant_id is None

    def can(self, permission: str) -> bool:
        return False


# ---------- claiming and running (used by app/worker.py; also handy in tests) ------------------------------------

@dataclass(frozen=True)
class Claimed:
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    kind: str
    payload: dict
    attempts: int
    max_attempts: int
    created_by: uuid.UUID | None


CLAIM_SQL = text("""
    UPDATE jobs SET status = 'running', locked_by = :worker, locked_at = now(), attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued' AND run_at <= now() AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))
        ORDER BY priority DESC, run_at, created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1)
    RETURNING id, tenant_id, kind, payload, attempts, max_attempts, created_by
""")


def claim(worker_id: str, kinds: list[str] | None = None) -> Claimed | None:
    """Take the next due job (platform scope), mark it running and commit. None if there's nothing to do."""
    with scoped_session(platform=True) as db:
        row = db.execute(CLAIM_SQL, {"worker": worker_id, "kinds": kinds}).first()
        db.commit()
    return Claimed(*row) if row else None


def backoff(attempts: int) -> timedelta:
    """Wait before retry number `attempts` (1-based): 15 s, 30 s, 1 min, 2 min … at most an hour."""
    return timedelta(seconds=min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** max(0, attempts - 1)))


def execute(c: Claimed, worker_id: str) -> str:
    """Run a claimed job in a session scoped to its client. Returns the job's new status."""
    load_job_modules()
    spec = JOBS.get(c.kind)
    error = ""
    permanent = False
    with scoped_session(tenant_id=c.tenant_id, platform=c.tenant_id is None) as db:
        try:
            if spec is None:
                raise PermanentError(f"No handler for job kind {c.kind!r}")
            db.execute(text("SELECT set_config('statement_timeout', :t, true)"), {"t": f"{spec.timeout_s * 1000}"})
            ctx = JobContext(c.id, c.kind, c.tenant_id, c.payload or {}, c.attempts, c.max_attempts, c.created_by, db, worker_id)
            result = spec.fn(ctx)
            done = db.execute(update(Job).where(Job.id == c.id, Job.locked_by == worker_id).values(
                status="done", result=_jsonable(result) if result is not None else None, finished_at=utcnow(),
                locked_by=None, locked_at=None, last_error="")).rowcount
            db.commit()
            if not done:
                log.warning("job finished after its lock was taken over", extra={"job_id": str(c.id), "kind": c.kind})
            return "done"
        except Exception as exc:
            db.rollback()
            from app.core.errors import DomainError
            permanent = isinstance(exc, PermanentError | DomainError)  # a business rule said no: retrying won't help
            error = f"{type(exc).__name__}: {exc}"[:2000]
            log.warning("job failed", extra={"job_id": str(c.id), "kind": c.kind, "attempt": c.attempts,
                                             "error": error, "trace": traceback.format_exc(limit=8)})
    return fail(c, worker_id, error, permanent=permanent)


def fail(c: Claimed, worker_id: str, error: str, permanent: bool = False) -> str:
    final = permanent or c.attempts >= c.max_attempts
    values: dict = {"locked_by": None, "locked_at": None, "last_error": error}
    if final:
        values.update(status="failed", finished_at=utcnow())
    else:
        values.update(status="queued", run_at=utcnow() + backoff(c.attempts))
    with scoped_session(platform=True) as db:
        db.execute(update(Job).where(Job.id == c.id, Job.locked_by == worker_id).values(**values))
        db.commit()
    spec = JOBS.get(c.kind)
    if final and spec and spec.notify_failure and c.created_by:
        try:
            from app.services import events
            with scoped_session(tenant_id=c.tenant_id, platform=c.tenant_id is None) as db:
                events.job_failed(db, c.tenant_id, c.created_by, c.id, c.kind, error)
                db.commit()
        except Exception:
            log.exception("couldn't tell the requester a job failed", extra={"job_id": str(c.id)})
    return "failed" if final else "queued"


def recover_stale(minutes: int = STALE_LOCK_MINUTES) -> list[uuid.UUID]:
    """Jobs whose worker vanished (lock not refreshed for `minutes`): back in the queue, or failed if out of tries."""
    with scoped_session(platform=True) as db:
        rows = db.execute(text("""
            UPDATE jobs SET
                status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
                finished_at = CASE WHEN attempts >= max_attempts THEN now() END,
                run_at = now(), locked_by = NULL, locked_at = NULL,
                last_error = 'The worker running this job stopped responding.'
            WHERE status = 'running' AND locked_at < now() - make_interval(mins => :m)
            RETURNING id"""), {"m": minutes}).scalars().all()
        db.commit()
    return list(rows)


def touch(job_ids: list[uuid.UUID], worker_id: str) -> None:
    """Refresh the locks of jobs this worker is running, so a long job isn't taken for a stale one."""
    if not job_ids:
        return
    with scoped_session(platform=True) as db:
        db.execute(update(Job).where(Job.id.in_(job_ids), Job.locked_by == worker_id).values(locked_at=utcnow()))
        db.commit()


def run_one(worker_id: str = "inline", kinds: list[str] | None = None) -> tuple[uuid.UUID, str] | None:
    """Claim and run a single job: (id, new status), or None if nothing was due. For tests and scripts."""
    c = claim(worker_id, kinds)
    if c is None:
        return None
    return c.id, execute(c, worker_id)
