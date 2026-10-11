"""The background worker: runs queued jobs (app/core/jobs.py) and the recurring schedule.

    python -m app.worker                    # run until Ctrl+C / SIGTERM (finishes the job in hand first)
    python -m app.worker --concurrency 4    # four jobs at a time in this process
    python -m app.worker --once             # run what's due now, then exit (cron, tests, scripts)
    docker compose up -d worker             # the same, as a service

Any number of workers can run at once (on one machine or several): jobs are claimed with FOR UPDATE SKIP LOCKED
and each scheduled run is taken by exactly one worker (a row lock on job_schedules).

Every 30 s a worker writes a heartbeat (job_workers.last_seen_at, a log line) and refreshes the locks of the jobs it's
running; every minute it puts back jobs whose worker vanished (lock older than STALE_LOCK_MINUTES). Logs are JSON
lines with the job id, kind, client and attempt.

Recurring jobs: add a Schedule to SCHEDULES (times are in the display time zone, IST).
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import signal
import socket
import sys
import threading
import time as clock
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import jobs
from app.core.config import get_settings
from app.core.db import engine, scoped_session
from app.core.logging import JsonFormatter, request_id
from app.models import JobSchedule, JobWorker, Tenant, utcnow

log = logging.getLogger("app.worker")

HEARTBEAT_S = 30
RECOVER_EVERY_S = 60
SCHEDULE_EVERY_S = 20


# ---------- the schedule ----------------------------------------------------------------------------------------

def local_zone() -> ZoneInfo:
    return ZoneInfo(get_settings().display_timezone)


@dataclass(frozen=True)
class Schedule:
    name: str
    kind: str
    at: time                       # local time of day
    weekday: int | None = None     # 0 = Monday … 6 = Sunday; None = every day
    per_tenant: bool = True        # one job per active client, or one platform job

    def next_after(self, after: datetime) -> datetime:
        """The first run strictly after `after` (aware), as an aware UTC datetime."""
        tz = local_zone()
        local = after.astimezone(tz)
        candidate = datetime.combine(local.date(), self.at, tzinfo=tz)
        while candidate <= local or (self.weekday is not None and candidate.weekday() != self.weekday):
            candidate = datetime.combine(candidate.date() + timedelta(days=1), self.at, tzinfo=tz)
        return candidate.astimezone(ZoneInfo("UTC"))


SCHEDULES: list[Schedule] = [
    Schedule("daily_summary", "daily_summary", time(21, 0)),            # each centre's day, at 9 pm
    Schedule("dues_digest", "dues_digest", time(9, 0), weekday=0),      # Mondays, 9 am
    Schedule("cleanup", "cleanup", time(3, 30), per_tenant=False),      # nightly housekeeping
]


def _fire(db, s: Schedule, slot: datetime) -> int:
    day: date = slot.astimezone(local_zone()).date()
    payload = {"day": day.isoformat(), "scheduled_for": slot.isoformat()}
    key = f"{s.name}:{day.isoformat()}"
    if not s.per_tenant:
        jobs.enqueue(db, s.kind, payload, tenant_id=None, dedupe_key=key)
        return 1
    tenants = db.scalars(select(Tenant.id).where(Tenant.status == "active")).all()
    for t in tenants:
        jobs.enqueue(db, s.kind, payload, tenant_id=t, dedupe_key=key)
    return len(tenants)


def tick(now: datetime | None = None, schedules: list[Schedule] | None = None) -> dict[str, int]:
    """Enqueue every schedule that's due. Safe with many workers: each due run is taken by one of them.
    Returns {schedule name: jobs enqueued} for the runs fired."""
    now = now or utcnow()
    fired: dict[str, int] = {}
    for s in schedules or SCHEDULES:
        with scoped_session(platform=True) as db:
            db.execute(pg_insert(JobSchedule).values(name=s.name, next_run_at=s.next_after(now)).on_conflict_do_nothing())
            row = db.scalar(select(JobSchedule).where(JobSchedule.name == s.name, JobSchedule.next_run_at <= now)
                            .with_for_update(skip_locked=True))
            if row is not None:
                fired[s.name] = _fire(db, s, row.next_run_at)
                # A worker that was down for days runs a missed schedule once, not once per missed day.
                row.next_run_at = s.next_after(max(now, row.next_run_at))
                row.last_run_at = now
                log.info("schedule fired", extra={"schedule": s.name, "jobs": fired[s.name], "next_run_at": row.next_run_at.isoformat()})
            db.commit()
    return fired


# ---------- the worker ------------------------------------------------------------------------------------------

class WorkerFormatter(JsonFormatter):
    FIELDS = (*JsonFormatter.FIELDS, "worker", "job_id", "kind", "tenant_id", "attempt", "status", "error", "trace",
              "duration_ms", "schedule", "jobs", "next_run_at", "running", "removed", "recovered")


class Worker:
    def __init__(self, concurrency: int = 1, poll_s: float = 1.0, kinds: list[str] | None = None, scheduler: bool = True):
        self.id = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(2)}"
        self.concurrency = max(1, concurrency)
        self.poll_s = poll_s
        self.kinds = kinds
        self.scheduler = scheduler
        self.stop = threading.Event()
        self.running: set[uuid.UUID] = set()
        self.done = 0
        self.failed = 0
        self._lock = threading.Lock()

    # ----- life cycle
    def _register(self) -> None:
        with scoped_session(platform=True) as db:
            db.execute(pg_insert(JobWorker).values(worker_id=self.id, hostname=socket.gethostname()[:200], pid=os.getpid(),
                                                   started_at=utcnow(), last_seen_at=utcnow(), status="running")
                       .on_conflict_do_nothing())
            db.commit()

    def _heartbeat(self, status: str = "running") -> None:
        with self._lock:
            ids, done, failed = list(self.running), self.done, self.failed
        jobs.touch(ids, self.id)
        with scoped_session(platform=True) as db:
            db.execute(update(JobWorker).where(JobWorker.worker_id == self.id)
                       .values(last_seen_at=utcnow(), jobs_done=done, jobs_failed=failed, status=status))
            db.commit()
        log.info("heartbeat", extra={"worker": self.id, "running": len(ids), "status": status})

    def install_signals(self) -> None:
        def handler(signum, _frame):
            if self.stop.is_set():
                log.warning("second stop signal: exiting now", extra={"worker": self.id})
                os._exit(1)
            log.info("stopping: finishing the jobs in hand", extra={"worker": self.id})
            self.stop.set()
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), handler)

    # ----- running jobs
    def run_job(self, c: jobs.Claimed) -> str:
        token = request_id.set(f"job-{c.id.hex[:16]}")
        started = clock.perf_counter()
        ctx = {"worker": self.id, "job_id": str(c.id), "kind": c.kind, "tenant_id": str(c.tenant_id or ""), "attempt": c.attempts}
        with self._lock:
            self.running.add(c.id)
        try:
            log.info("job started", extra=ctx)
            status = jobs.execute(c, self.id)
        except Exception:  # execute() handles handler errors; this is the database itself failing
            log.exception("job crashed", extra=ctx)
            status = "error"
        finally:
            with self._lock:
                self.running.discard(c.id)
                if status == "done":
                    self.done += 1
                elif status == "failed":
                    self.failed += 1
            log.info("job finished", extra={**ctx, "status": status, "duration_ms": round((clock.perf_counter() - started) * 1000, 1)})
            request_id.reset(token)
        return status

    def _loop(self, once: bool) -> None:
        while not self.stop.is_set():
            try:
                c = jobs.claim(self.id, self.kinds)
            except Exception:
                log.exception("couldn't claim a job; retrying shortly", extra={"worker": self.id})
                self.stop.wait(5)
                continue
            if c is None:
                if once:
                    return
                self.stop.wait(self.poll_s)
                continue
            self.run_job(c)

    def _housekeeping(self, last: dict[str, float]) -> None:
        now = clock.monotonic()
        try:
            if now - last.get("beat", 0) >= HEARTBEAT_S:
                last["beat"] = now
                self._heartbeat()
            if now - last.get("recover", 0) >= RECOVER_EVERY_S:
                last["recover"] = now
                back = jobs.recover_stale()
                if back:
                    log.warning("put back jobs from a vanished worker", extra={"worker": self.id, "recovered": [str(i) for i in back]})
            if self.scheduler and now - last.get("schedule", 0) >= SCHEDULE_EVERY_S:
                last["schedule"] = now
                tick()
        except Exception:
            log.exception("housekeeping failed; will retry", extra={"worker": self.id})

    def run(self, once: bool = False) -> int:
        jobs.load_job_modules()
        self._register()
        log.info("worker started", extra={"worker": self.id, "running": self.concurrency})
        last: dict[str, float] = {}
        self._housekeeping(last)
        threads = [threading.Thread(target=self._loop, args=(once,), name=f"job-{i}", daemon=True) for i in range(self.concurrency)]
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            if self.stop.wait(1.0) and not once:
                break
            self._housekeeping(last)
        for t in threads:
            t.join()
        try:
            self._heartbeat(status="stopped")
        except Exception:
            log.exception("couldn't record the worker stopping", extra={"worker": self.id})
        log.info("worker stopped", extra={"worker": self.id, "status": f"{self.done} done, {self.failed} failed"})
        return 0


def configure(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(WorkerFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.worker", description="Supreme DMS background worker")
    p.add_argument("--concurrency", type=int, default=int(os.environ.get("WORKER_CONCURRENCY", "2")))
    p.add_argument("--poll", type=float, default=1.0, help="seconds between looks at an empty queue")
    p.add_argument("--kinds", default="", help="only these job kinds (comma separated)")
    p.add_argument("--once", action="store_true", help="run the jobs due now, then exit")
    p.add_argument("--no-scheduler", action="store_true", help="don't enqueue the recurring jobs from this worker")
    args = p.parse_args(argv)
    configure(get_settings().log_level)
    with engine.connect() as conn:  # fail fast, with a clear message, if the database isn't there
        conn.execute(text("SELECT 1"))
    w = Worker(args.concurrency, args.poll, [k for k in args.kinds.split(",") if k] or None, not args.no_scheduler)
    w.install_signals()
    return w.run(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
