"""Nightly housekeeping (platform scope): expired sessions and reset links, finished jobs, expired job files,
old notifications, workers that stopped long ago, unfinished uploads, old payload keys and rate-limit attempts."""

from datetime import timedelta

from sqlalchemy import delete, or_, text

from app.core.jobs import JobContext, job
from app.models import Job, JobFile, JobWorker, PasswordReset, PayloadKey, Upload, UserSession, utcnow
from app.services.notifications import purge_old

SESSION_GRACE = timedelta(days=7)        # ended sessions are kept a week (for "signed in from" questions)
RESET_GRACE = timedelta(days=1)
DONE_JOBS = timedelta(days=14)
FAILED_JOBS = timedelta(days=30)


@job("cleanup", max_attempts=3, timeout_s=900)
def cleanup(ctx: JobContext) -> dict:
    db, now = ctx.db, utcnow()
    out = {
        "sessions": db.execute(delete(UserSession).where(or_(UserSession.expires_at < now - SESSION_GRACE,
                                                             UserSession.revoked_at < now - SESSION_GRACE))).rowcount,
        "password_resets": db.execute(delete(PasswordReset).where(PasswordReset.expires_at < now - RESET_GRACE)).rowcount,
        "job_files": db.execute(delete(JobFile).where(JobFile.expires_at < now)).rowcount,
        "jobs": db.execute(delete(Job).where(or_(
            Job.status.in_(("done", "cancelled")) & (Job.finished_at < now - DONE_JOBS),
            (Job.status == "failed") & (Job.finished_at < now - FAILED_JOBS)))).rowcount,
        "notifications": purge_old(db),
        "workers": db.execute(delete(JobWorker).where(JobWorker.last_seen_at < now - timedelta(days=1))).rowcount,
        # Uploads nobody finished, encryption keys from tabs closed long ago, and old rate-limit attempts.
        "uploads": db.execute(delete(Upload).where(Upload.updated_at < now - timedelta(days=1))).rowcount,
        "payload_keys": db.execute(delete(PayloadKey).where(PayloadKey.created_at < now - timedelta(days=1))).rowcount,
        "rate_limit_hits": db.execute(text("DELETE FROM rate_limit_hits WHERE at < now() - interval '2 days'")).rowcount,
    }
    ctx.log.info("cleanup done", extra={"job_id": str(ctx.id), "removed": out})
    return out
