"""A client's backups and restores (app/services/client_backups.py), run by the worker."""

import uuid
from datetime import datetime

from app.core.jobs import JobContext, PermanentError, job
from app.models import ClientBackup, utcnow
from app.services import client_backups
from app.services.audit import AuditService


@job("client_backup", max_attempts=2, timeout_s=900)
def client_backup(ctx: JobContext) -> dict:
    """Back up now (payload: backup_id) or the client's schedule (payload: scheduled_for)."""
    backup_id = uuid.UUID(ctx.payload["backup_id"]) if ctx.payload.get("backup_id") else None
    slot = datetime.fromisoformat(ctx.payload["scheduled_for"]) if ctx.payload.get("scheduled_for") else None
    made = client_backups.run_backup(ctx.tenant_id, backup_id, "manual" if backup_id else "scheduled", slot)
    return {"backup_id": str(made)}


@job("client_restore", max_attempts=1, timeout_s=1800)
def client_restore(ctx: JobContext) -> dict:
    """Put a copy back: a fresh copy first, then the copy's rows in place of the client's, in this job's transaction."""
    restore_id = uuid.UUID(ctx.payload["restore_id"])
    r = ctx.db.get(ClientBackup, restore_id)
    if r is None or r.status != "running":
        return {"skipped": "not waiting"}
    try:
        source = ctx.db.get(ClientBackup, r.source_id)
        if source is None:
            raise PermanentError("The copy to restore isn't there any more.")
        data = client_backups.read_copy(source)
        when = f"{source.started_at.astimezone(client_backups._tz()):%d %b %Y, %I:%M %p}"
        before = client_backups.run_backup(ctx.tenant_id, None, "manual",
                                           message=f"The data just before restoring the copy of {when}")
        put = client_backups.restore_copy(ctx.db, ctx.tenant_id, data)
    except Exception as e:
        ctx.db.rollback()
        text = str(e) if isinstance(e, PermanentError) or type(e).__name__ in ("Invalid", "NotFound") else f"{type(e).__name__}: {str(e)[:300]}"
        client_backups.fail(ctx.tenant_id, restore_id, f"The restore didn't go through, so nothing changed ({text}).")
        raise PermanentError(text) from e
    r = ctx.db.get(ClientBackup, restore_id)
    r.status, r.finished_at, r.counts = "ok", utcnow(), put
    r.message = f"{r.message}. The data before it was copied first."[:500]
    AuditService(ctx.db).record(ctx.tenant_id, r.requested_by, "backups.restored", "client_backups", source.id,
                                {"copy_before": str(before), "rows": put})
    return {"restored": put, "copy_before": str(before)}
