"""Database backups on a schedule the platform owner chooses: the time of day (India time), how often, and how
long copies are kept, plus "Back up now". The copy itself is made on the server by deploy/backup.sh, which cron
runs every 5 minutes with --if-due: it asks `python -m app.manage backup-start` whether one is due, makes it,
and reports back with `backup-finish`. The app never touches the backup files; it only keeps the schedule and
the record of each run.
"""

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, Invalid
from app.models import BackupRun, BackupSettings, utcnow
from app.services.audit import AuditService

CYCLES = {1: "Every day", 2: "Every 2 days", 3: "Every 3 days", 7: "Every week", 14: "Every 2 weeks", 30: "Every month"}
KEEP = {7: "1 week", 14: "2 weeks", 30: "1 month", 60: "2 months", 90: "3 months", 180: "6 months", 365: "1 year", 0: "Forever"}  # 0: never deleted
STALE = timedelta(hours=3)   # a run still "running" this long was cut off (the server restarted mid-backup)


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().display_timezone)


def plan_next(s: BackupSettings, now: datetime, last_slot: datetime | None) -> datetime | None:
    """The next scheduled backup: every_days after the last scheduled one, at the chosen time. If that's already
    past (the server was off, or the time was just changed), the next time the clock reaches at_time."""
    if not s.enabled:
        return None
    hh, mm = (int(x) for x in s.at_time.split(":"))
    tz = _tz()
    if last_slot is not None:
        slot = datetime.combine(last_slot.astimezone(tz).date() + timedelta(days=s.every_days), time(hh, mm), tz)
        if slot > now:
            return slot
    slot = datetime.combine(now.astimezone(tz).date(), time(hh, mm), tz)
    return slot if slot > now else slot + timedelta(days=1)


def _row(db: Session, lock: bool = False) -> BackupSettings:
    q = select(BackupSettings).where(BackupSettings.id == 1)
    row = db.scalar(q.with_for_update() if lock else q)
    if row is None:
        row = BackupSettings(id=1, enabled=True, every_days=1, at_time="23:00", keep_days=30)
        row.next_run_at = plan_next(row, utcnow(), None)
        db.add(row)
        db.flush()
    return row


def _last_slot(db: Session) -> datetime | None:
    return db.scalar(select(BackupRun.scheduled_for).where(BackupRun.trigger == "scheduled", BackupRun.scheduled_for.is_not(None))
                     .order_by(BackupRun.scheduled_for.desc()).limit(1))


def _settings_out(s: BackupSettings) -> dict:
    return {"enabled": s.enabled, "every_days": s.every_days, "at_time": s.at_time, "keep_days": s.keep_days,
            "next_run_at": s.next_run_at, "requested_at": s.requested_at}


def overview(db: Session) -> dict:
    s = _row(db)
    now = utcnow()
    runs = list(db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(30)))
    return {
        "settings": _settings_out(s),
        "cycles": [{"days": d, "label": label} for d, label in CYCLES.items()],
        "keep_options": [{"days": d, "label": label} for d, label in KEEP.items()],
        "timezone": get_settings().display_timezone,
        "runs": [{"id": r.id, "trigger": r.trigger, "scheduled_for": r.scheduled_for, "started_at": r.started_at,
                  "finished_at": r.finished_at, "status": r.status, "file": r.file.rsplit("/", 1)[-1], "size_bytes": r.size_bytes,
                  "message": r.message, "kept": r.status == "ok" and (s.keep_days == 0 or r.started_at >= now - timedelta(days=s.keep_days))}
                 for r in runs],
    }


def update(db: Session, user_id: uuid.UUID, enabled: bool, every_days: int, at_time: str, keep_days: int) -> dict:
    if every_days not in CYCLES:
        raise Invalid("Choose how often from the list.", "every_days")
    if keep_days not in KEEP:
        raise Invalid("Choose how long to keep backups from the list.", "keep_days")
    try:
        hh, mm = (int(x) for x in at_time.split(":"))
    except ValueError:
        hh = mm = -1
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise Invalid("Give the time as hours and minutes, e.g. 23:00.", "at_time")
    s = _row(db, lock=True)
    before = _settings_out(s)
    s.enabled, s.every_days, s.at_time, s.keep_days = enabled, every_days, f"{hh:02d}:{mm:02d}", keep_days
    s.next_run_at = plan_next(s, utcnow(), _last_slot(db))
    after = _settings_out(s)
    changes = {k: [before[k], after[k]] for k in ("enabled", "every_days", "at_time", "keep_days") if before[k] != after[k]}
    if changes:
        AuditService(db).record(None, user_id, "backups.schedule_changed", "backup_settings", 1, changes)
    db.flush()
    return overview(db)


def request_now(db: Session, user_id: uuid.UUID) -> dict:
    s = _row(db, lock=True)
    if db.scalar(select(BackupRun.id).where(BackupRun.status == "running", BackupRun.started_at > utcnow() - STALE)):
        raise Conflict("A backup is being made right now. It shows below when it's done.")
    if s.requested_at is None:
        s.requested_at, s.requested_by = utcnow(), user_id
        AuditService(db).record(None, user_id, "backups.requested", "backup_settings", 1, {})
    db.flush()
    return overview(db)


# ---- used by the server's backup script (python -m app.manage backup-start / backup-finish) ----

def start(db: Session, now: datetime | None = None, force: bool = False) -> tuple[BackupRun, int] | None:
    """A backup to make now, if one is due (or force: someone ran the script by hand). None when nothing is due."""
    now = now or utcnow()
    s = _row(db, lock=True)
    for stuck in db.scalars(select(BackupRun).where(BackupRun.status == "running", BackupRun.started_at <= now - STALE)):
        stuck.status, stuck.finished_at, stuck.message = "failed", now, "Stopped without finishing (the server may have restarted)."
    db.flush()
    if db.scalar(select(BackupRun.id).where(BackupRun.status == "running")):
        return None
    if force or s.requested_at is not None:
        run = BackupRun(trigger="manual", requested_by=s.requested_by, started_at=now)
        s.requested_at, s.requested_by = None, None
    elif s.enabled and s.next_run_at is not None and s.next_run_at <= now:
        run = BackupRun(trigger="scheduled", scheduled_for=s.next_run_at, started_at=now)
        s.next_run_at = plan_next(s, now, s.next_run_at)
    else:
        return None
    db.add(run)
    db.flush()
    return run, s.keep_days


def finish(db: Session, run_id: uuid.UUID, ok: bool, file: str = "", size_bytes: int = 0, message: str = "") -> None:
    run = db.get(BackupRun, run_id)
    if run is None:
        raise SystemExit(f"No backup run {run_id}.")
    run.status, run.finished_at = ("ok" if ok else "failed"), utcnow()
    run.file, run.size_bytes, run.message = file[:200], size_bytes, message[:500]
    db.flush()
