"""Telling the people who run CIDMS when something needs them: a background job that has failed for good, the
disk filling up, the worker stopping. By email to ALERT_EMAIL (several, comma-separated); with no ALERT_EMAIL the
alert is only logged (as an ERROR line, which error tracking picks up too). The same alert is sent at most once
every few hours, however many processes notice it.

Error tracking: with SENTRY_DSN set, unexpected errors in the app and the worker go to Sentry (or any
Sentry-compatible service), without request bodies, cookies or other personal data."""

import logging
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.core.limits import RateLimiter

log = logging.getLogger("app.alerts")
_once = RateLimiter("alert", limit=1, per_seconds=6 * 3600)  # the same alert at most every 6 hours

DISK_MIN_FREE = 0.10  # alert below 10% free


def alert(key: str, subject: str, body: str) -> bool:
    """Send an alert (once per key every 6 hours). Returns True if it was sent or logged now."""
    try:
        if _once.wait_seconds(key):
            return False
    except Exception:  # the database may be the problem: alert anyway
        log.warning("couldn't check the alert limit; sending anyway", exc_info=True)
    log.error("ALERT %s: %s", subject, body)
    to = [a.strip() for a in get_settings().alert_email.split(",") if a.strip()]
    if to:
        from app.core import mailer
        for address in to:
            try:
                mailer.send(address, f"[CIDMS] {subject}", body)
            except Exception:
                log.exception("couldn't email the alert to %s", address)
    return True


def check_disk(path: str | None = None) -> float:
    """Free space on the disk holding the app's storage (a fraction); alerts when it's low."""
    target = Path(path or get_settings().storage_dir)
    while not target.exists() and target != target.parent:
        target = target.parent
    usage = shutil.disk_usage(target)
    free = usage.free / usage.total if usage.total else 1.0
    if free < DISK_MIN_FREE:
        alert("disk", "The server's disk is nearly full",
              f"Only {free:.0%} ({usage.free // (1024 ** 3)} GB) is free on the disk holding {target}. "
              "Free some space (old backups, Docker images: docker image prune) before the database stops.")
    return free


def init_error_tracking(component: str) -> None:
    """Sentry, when SENTRY_DSN is set. Personal data is never sent: no bodies, cookies, headers or user details."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk isn't installed")
        return

    def scrub(event, _hint):
        request = event.get("request") or {}
        for key in ("data", "cookies", "headers", "query_string", "env"):
            request.pop(key, None)
        event.pop("user", None)
        return event

    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, send_default_pii=False,
                    max_request_body_size="never", traces_sample_rate=0.0, before_send=scrub,
                    server_name=component)
