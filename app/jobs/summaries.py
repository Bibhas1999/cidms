"""Scheduled digests for each centre: the daily summary (21:00 IST) and the weekly dues digest (Mondays)."""

from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.jobs import JobContext, job
from app.core.money import local_today, q2
from app.models import Invoice
from app.services import events
from app.services.billing import BillingService


@job("daily_summary", max_attempts=3)
def daily_summary(ctx: JobContext) -> dict:
    day = date.fromisoformat(ctx.payload["day"]) if ctx.payload.get("day") else local_today()
    s = BillingService(ctx.db, ctx.system_actor()).day_summary(day)  # read-only
    if not s["bills"] and not s["collected_total"]:
        return {"day": str(day), "sent": 0, "skipped": "nothing happened"}
    sent = events.daily_summary(ctx.db, ctx.tenant_id, s)
    return {"day": str(day), "bills": s["bills"], "collected": str(s["collected_total"]), "sent": len(sent)}


@job("dues_digest", max_attempts=3)
def dues_digest(ctx: JobContext) -> dict:
    t = ctx.tenant_id
    live = (Invoice.tenant_id == t, Invoice.due > 0, Invoice.status != "cancelled")
    count, total, oldest = ctx.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.due), 0), func.min(Invoice.bill_date))
                                          .where(*live)).one()
    if not count:
        return {"bills": 0, "sent": 0}
    old = ctx.db.scalar(select(func.count()).where(*live, Invoice.bill_date < local_today() - timedelta(days=30))) or 0
    sent = events.dues_digest(ctx.db, t, count, q2(total), oldest, old)
    return {"bills": count, "due": str(q2(total)), "sent": len(sent)}
