"""Things that happened, turned into notifications for the right people. One call per event, made where the
event happens, inside the same transaction (so the notification exists only if the change was saved):

    from app.services import events
    events.bill_cancelled(self.db, invoice, self.current, reason)

Every helper is safe to call: a problem notifying is logged and never undoes or fails the change itself (the
notification is written in a savepoint). The person who did it isn't notified about their own action.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.money import rupees
from app.services.notifications import notify, register_kind

log = logging.getLogger("app.events")

OWNERS = ("owner", "admin")
FRONT_DESK = ("receptionist",)

register_kind("bill.cancelled", "Bill cancelled", "A bill is cancelled, with the reason given.", "Owners and centre admins")
register_kind("bill.held_for_review", "Bill on hold for review", "A fully paid bill is put on hold for owners/admin review.",
              "Owners and centre admins")
register_kind("refund.recorded", "Refund recorded", "Money is given back on a bill.", "Owners and centre admins")
register_kind("discount.over_limit", "Discount over the limit", "A bill gets a discount above the centre's discount limit.",
              "Owners and centre admins")
register_kind("staff.added", "New staff member", "Someone is added to the centre's staff.", "Owners and centre admins")
register_kind("security.password_reset", "Password reset requested", "Someone asks for a password reset link for your account.",
              "You", can_mute=False)
register_kind("export.ready", "Export ready", "A file you asked for has been made and is ready to download.", "You")
register_kind("job.failed", "Background task failed", "Something you started in the background couldn't be finished.", "You",
              can_mute=False)
register_kind("report.signed", "Report signed", "A doctor signs a test report, so it can be printed or sent.", "Front desk")
register_kind("report.sent", "Report sent to patient", "A signed report is sent to the patient (WhatsApp).", "Front desk")
register_kind("summary.daily", "Daily summary", "Each evening at 9 pm: the day's bills, collection and dues.", "Owners and centre admins")
register_kind("summary.dues", "Weekly dues digest", "Every Monday morning: how much is still due, and on how many bills.",
              "Owners, admins and accounts")


def _safe(fn: Callable[..., Any]) -> Callable[..., list[uuid.UUID]]:
    def wrapper(db: Session, *args, **kwargs) -> list[uuid.UUID]:
        try:
            with db.begin_nested():
                return fn(db, *args, **kwargs) or []
        except Exception:
            log.exception("couldn't record the notification for %s", fn.__name__)
            return []
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _who(actor: Any) -> tuple[uuid.UUID | None, str]:
    if actor is None:
        return None, "Someone"
    user = getattr(actor, "user", actor)
    return getattr(actor, "id", None) or getattr(user, "id", None), getattr(user, "full_name", "") or "Someone"


# ---------- billing (call from app/services/billing.py) ----------

@_safe
def bill_cancelled(db: Session, invoice: Any, actor: Any, reason: str = "") -> list[uuid.UUID]:
    actor_id, name = _who(actor)
    return notify(db, invoice.tenant_id, kind="bill.cancelled", severity="warning", roles=OWNERS, exclude=[actor_id],
                  title=f"Bill {invoice.invoice_no} cancelled",
                  body=f"{name} cancelled {invoice.patient_name}'s bill of {rupees(invoice.total)}." + (f" Reason: {reason}" if reason else ""),
                  link=f"/bills/{invoice.id}")


@_safe
def bill_held_for_review(db: Session, invoice: Any, actor: Any, reason: str = "") -> list[uuid.UUID]:
    actor_id, name = _who(actor)
    return notify(db, invoice.tenant_id, kind="bill.held_for_review", severity="warning", roles=OWNERS, exclude=[actor_id],
                  title=f"Bill {invoice.invoice_no} is on hold for review",
                  body=f"{name} put {invoice.patient_name}'s fully paid bill on hold. Review it to decide whether to keep or cancel it."
                       + (f" Reason: {reason}" if reason else ""),
                  link=f"/bills/{invoice.id}")


@_safe
def refund_recorded(db: Session, invoice: Any, actor: Any, amount: Decimal, mode: str = "", reason: str = "") -> list[uuid.UUID]:
    actor_id, name = _who(actor)
    return notify(db, invoice.tenant_id, kind="refund.recorded", severity="warning", roles=OWNERS, exclude=[actor_id],
                  title=f"Refund of {rupees(amount)} on {invoice.invoice_no}",
                  body=f"{name} refunded {rupees(amount)}{f' ({mode})' if mode else ''} to {invoice.patient_name}."
                       + (f" Reason: {reason}" if reason else ""),
                  link=f"/bills/{invoice.id}")


@_safe
def discount_over_limit(db: Session, invoice: Any, actor: Any, limit_percent: Decimal) -> list[uuid.UUID]:
    actor_id, name = _who(actor)
    pct = (invoice.discount_amount * 100 / invoice.subtotal).quantize(Decimal("0.1")) if invoice.subtotal else Decimal(0)
    return notify(db, invoice.tenant_id, kind="discount.over_limit", severity="warning", roles=OWNERS, exclude=[actor_id],
                  title=f"{pct.normalize()}% discount on {invoice.invoice_no}",
                  body=f"{name} gave {invoice.patient_name} a discount of {rupees(invoice.discount_amount)}, above the "
                       f"centre's limit of {Decimal(limit_percent).normalize()}%.",
                  link=f"/bills/{invoice.id}")


# ---------- people (staff service, sign-in) ----------

@_safe
def staff_added(db: Session, user: Any, actor: Any) -> list[uuid.UUID]:
    actor_id, name = _who(actor)
    roles = ", ".join(r.name for r in getattr(user, "roles", []) or []) or "no role yet"
    return notify(db, user.tenant_id, kind="staff.added", roles=OWNERS, exclude=[actor_id, user.id],
                  title=f"{user.full_name} joined the staff", body=f"Added by {name} ({roles}).", link="/settings/staff")


@_safe
def password_reset_requested(db: Session, user: Any, ip: str = "") -> list[uuid.UUID]:
    return notify(db, user.tenant_id, kind="security.password_reset", severity="warning", user_ids=[user.id],
                  title="Password reset requested",
                  body="A link to reset your password was emailed to you" + (f" (asked from {ip})" if ip else "")
                       + ". If it wasn't you, tell your owner or admin.",
                  link="/settings/password")


# ---------- reports (test_reports.py, whatsapp.py) ----------

@_safe
def report_signed(db: Session, report: Any, item: Any, invoice: Any, actor: Any) -> list[uuid.UUID]:
    actor_id, _ = _who(actor)
    signer = getattr(report, "signer_name", "") or "The doctor"
    return notify(db, invoice.tenant_id, kind="report.signed", severity="success", roles=FRONT_DESK, exclude=[actor_id],
                  title=f"Report ready: {invoice.patient_name}", body=f"{signer} signed the {item.test_name} report ({invoice.invoice_no}).",
                  link=f"/bills/{invoice.id}")


@_safe
def report_sent(db: Session, delivery: Any, patient_name: str, test_name: str = "", invoice_id: Any = None) -> list[uuid.UUID]:
    failed = getattr(delivery, "status", "sent") == "failed"
    return notify(db, delivery.tenant_id, kind="report.sent", severity="danger" if failed else "success", roles=FRONT_DESK,
                  user_ids=[delivery.sent_by] if failed and delivery.sent_by else None,
                  exclude=[] if failed else [delivery.sent_by],
                  title=(f"Couldn't send {patient_name}'s report" if failed else f"Report sent to {patient_name}"),
                  body=(f"{test_name + ': ' if test_name else ''}" + (delivery.error or "WhatsApp didn't accept it.") if failed
                        else f"{test_name + ' report ' if test_name else 'Report '}sent on WhatsApp to {delivery.to}."),
                  link=f"/bills/{invoice_id}" if invoice_id else "")


# ---------- background jobs (app/jobs) ----------

@_safe
def export_ready(db: Session, tenant_id: uuid.UUID | None, user_id: uuid.UUID, job_id: uuid.UUID, filename: str) -> list[uuid.UUID]:
    return notify(db, tenant_id, kind="export.ready", severity="success", user_ids=[user_id],
                  title="Your export is ready", body=f"{filename}: download it within 24 hours.", link=f"/api/jobs/{job_id}/file")


@_safe
def job_failed(db: Session, tenant_id: uuid.UUID | None, user_id: uuid.UUID, job_id: uuid.UUID, kind: str, error: str) -> list[uuid.UUID]:
    what = {"export": "Your export"}.get(kind, "A background task")
    return notify(db, tenant_id, kind="job.failed", severity="danger", user_ids=[user_id],
                  title=f"{what} couldn't be finished", body=f"Please try again. If it keeps failing, quote reference {job_id}.")


@_safe
def daily_summary(db: Session, tenant_id: uuid.UUID, s: dict) -> list[uuid.UUID]:
    day = s["day"]
    parts = [f"{s['bills']} bill{'s' if s['bills'] != 1 else ''} worth {rupees(s['billed'])}",
             f"collected {rupees(s['collected_total'])}"]
    if s.get("dues_collected"):
        parts.append(f"incl. {rupees(s['dues_collected'])} of old dues")
    if s.get("refunds"):
        parts.append(f"refunds {rupees(s['refunds'])}")
    if s.get("discounts"):
        parts.append(f"discounts {rupees(s['discounts'])}")
    body = "; ".join(parts) + f". Outstanding dues: {rupees(s['outstanding_dues'])}."
    return notify(db, tenant_id, kind="summary.daily", roles=OWNERS, title=f"Summary for {day:%a %d %b}", body=body,
                  link=f"/bills?date_from={day}&date_to={day}")


@_safe
def dues_digest(db: Session, tenant_id: uuid.UUID, count: int, total: Decimal, oldest=None, over_30_days: int = 0) -> list[uuid.UUID]:
    body = f"{count} bill{'s' if count != 1 else ''} with {rupees(total)} still due"
    if oldest:
        body += f"; the oldest from {oldest:%d %b %Y}"
    if over_30_days:
        body += f"; {over_30_days} older than 30 days"
    return notify(db, tenant_id, kind="summary.dues", severity="warning" if over_30_days else "info",
                  roles=(*OWNERS, "accounts"), title="This week's dues", body=body + ".", link="/dues")
