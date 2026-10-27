"""The patient's link to a signed report: the QR code on the printout and the PDF, opening /r/<token>.

- A link is issued when a report is signed (and kept when it is amended: it always shows the latest signed
  version). It works for REPORT_LINK_DAYS, can be revoked, and a new one can be issued (revoking the old).
- The token is 128 random-looking bits derived from the share's id with the server's secret (HMAC), so the
  printout can show it again later while the database only ever holds its SHA-256 hash: a copy of the database
  alone opens nothing.
- Opening it needs the last 4 digits of the patient's mobile (or the year of birth, or the bill number's last
  4 digits when there's no mobile). 5 wrong tries lock the link for 15 minutes; wrong tries are also limited per IP.
  Every view and every failed check goes in the activity log. The link only works at its own centre's address.
- After a correct check, a 15-minute grant lets that browser download the PDF.
"""

import base64
import hashlib
import hmac
import re
import time
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound, TooManyRequests
from app.core.limits import RateLimiter
from app.models import Invoice, InvoiceItem, Patient, ReportShare, TestReport, utcnow
from app.services.audit import AuditService

MAX_FAILED = 5
LOCK = timedelta(minutes=15)
GRANT_SECONDS = 15 * 60
TOKEN = re.compile(r"^[A-Za-z0-9_-]{22}$")
NOT_FOUND = "This link isn't valid or has expired. Ask the centre for a new one."
public_check_limiter = RateLimiter("report-check-ip", limit=20, per_seconds=900)  # wrong checks per IP
# Wrong checks per link in a day: with the 15-minute lock alone, a 4-digit check could be guessed in a few weeks.
link_daily_limiter = RateLimiter("report-check-link", limit=15, per_seconds=24 * 3600)


def _secret() -> bytes:
    """REPORT_LINK_SECRET signs the links printed on reports (the QR codes). Kept apart from SESSION_SECRET so that
    changing the session secret doesn't break every printed report; unset, it falls back to SESSION_SECRET (as
    before), so set REPORT_LINK_SECRET to the current SESSION_SECRET before ever changing that."""
    settings = get_settings()
    return (settings.report_link_secret or settings.session_secret).encode()


def token_for(share_id: uuid.UUID) -> str:
    mac = hmac.new(_secret(), b"report-share:" + share_id.bytes, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public_url(base_url: str, share: ReportShare) -> str:
    return f"{base_url.rstrip('/')}/r/{token_for(share.id)}"


def is_active(share: ReportShare | None) -> bool:
    return share is not None and share.revoked_at is None and share.expires_at > utcnow()


# ---------- staff side ----------

def current_share(db: Session, tenant_id: uuid.UUID, report_id: uuid.UUID) -> ReportShare | None:
    return db.scalar(select(ReportShare).where(ReportShare.tenant_id == tenant_id, ReportShare.report_id == report_id)
                     .order_by(ReportShare.created_at.desc()).limit(1))


def issue(db: Session, tenant_id: uuid.UUID, report_id: uuid.UUID, user_id: uuid.UUID | None, replace: bool = False) -> ReportShare:
    """The report's working link; a new one when there is none (or replace=True, which revokes the old)."""
    share = current_share(db, tenant_id, report_id)
    if is_active(share) and not replace:
        return share  # type: ignore[return-value]
    now = utcnow()
    if share is not None and share.revoked_at is None:
        share.revoked_at = now
    new = ReportShare(id=uuid.uuid4(), tenant_id=tenant_id, report_id=report_id, created_by=user_id, created_at=now,
                      expires_at=now + timedelta(days=get_settings().report_link_days))
    new.token_hash = token_hash(token_for(new.id))
    db.add(new)
    db.flush()
    AuditService(db).record(tenant_id, user_id, "report.link_issued", "test_report", report_id, {"share": str(new.id)})
    return new


def revoke(db: Session, tenant_id: uuid.UUID, report_id: uuid.UUID, user_id: uuid.UUID) -> ReportShare | None:
    share = current_share(db, tenant_id, report_id)
    if share is not None and share.revoked_at is None:
        share.revoked_at = utcnow()
        AuditService(db).record(tenant_id, user_id, "report.link_revoked", "test_report", report_id, {"share": str(share.id)})
    return share


# ---------- patient side (no sign-in) ----------

def find(db: Session, tenant_id: uuid.UUID, token: str, lock: bool = False) -> tuple[ReportShare, TestReport, InvoiceItem, Invoice]:
    """The link's share, report, test and bill, or NotFound (the same answer for unknown, revoked and expired)."""
    if not TOKEN.match(token or ""):
        raise NotFound(NOT_FOUND)
    q = (select(ReportShare, TestReport, InvoiceItem, Invoice).join(TestReport, TestReport.id == ReportShare.report_id)
         .join(InvoiceItem, InvoiceItem.id == TestReport.invoice_item_id).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
         .where(ReportShare.tenant_id == tenant_id, ReportShare.token_hash == token_hash(token)))
    if lock:
        q = q.with_for_update(of=ReportShare)
    row = db.execute(q).first()
    if row is None or not is_active(row[0]) or row[1].status not in ("signed", "amended"):
        raise NotFound(NOT_FOUND)
    return row[0], row[1], row[2], row[3]


def check_kind(db: Session, invoice: Invoice) -> tuple[str, str]:
    """What the patient is asked for, and the right answer."""
    digits = re.sub(r"\D", "", invoice.patient_mobile or "")
    if len(digits) >= 4:
        return "mobile", digits[-4:]
    patient = db.get(Patient, invoice.patient_id)
    if patient is not None and patient.date_of_birth:
        return "birth_year", str(patient.date_of_birth.year)
    return "bill", re.sub(r"\D", "", invoice.invoice_no)[-4:]


def check(db: Session, tenant_id: uuid.UUID, token: str, answer: str, ip: str) -> tuple[ReportShare, TestReport, InvoiceItem, Invoice]:
    share, report, item, invoice = find(db, tenant_id, token, lock=True)
    audit = AuditService(db)
    now = utcnow()
    if share.locked_until and share.locked_until > now:
        raise TooManyRequests("Too many wrong tries. Please try again in 15 minutes.")
    if link_daily_limiter.wait_seconds(str(share.id), record=False):
        raise TooManyRequests("Too many wrong tries for this link today. Please try again tomorrow, or ask the centre.")
    _kind, expected = check_kind(db, invoice)
    if not expected or not hmac.compare_digest(re.sub(r"\s", "", answer or ""), expected):
        share.failed_checks += 1
        if share.failed_checks >= MAX_FAILED:
            share.locked_until, share.failed_checks = now + LOCK, 0
        audit.record(tenant_id, None, "report.public_check_failed", "test_report", report.id, {"share": str(share.id), "public": True})
        db.commit()  # the failed try counts even though the request fails
        link_daily_limiter.wait_seconds(str(share.id))
        public_check_limiter.hit(f"ip:{ip}", "Too many wrong tries. Please try again in 15 minutes.")
        raise Forbidden("That doesn't match our records. Please check and try again.", "check")
    share.failed_checks, share.locked_until = 0, None
    share.views += 1
    share.last_viewed_at = now
    audit.record(tenant_id, None, "report.public_viewed", "test_report", report.id, {"share": str(share.id), "public": True})
    return share, report, item, invoice


def grant_for(share_id: uuid.UUID, now: float | None = None) -> str:
    exp = int((now or time.time()) + GRANT_SECONDS)
    mac = hmac.new(_secret(), f"report-grant:{share_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{mac}"


def grant_ok(share_id: uuid.UUID, grant: str) -> bool:
    exp, _, mac = (grant or "").partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    expected = hmac.new(_secret(), f"report-grant:{share_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(mac, expected)
