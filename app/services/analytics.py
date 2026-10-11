"""Analytics for the owner and the centre admin: turnover, collection, patients, doctors, staff and the test
pipeline, for any period, narrowed by department, referring doctor and who billed.

Every figure is one aggregate query in the database (nothing is summed row by row in Python), always limited to
the signed-in centre (row-level security, plus an explicit tenant filter). Each section is its own request, so
the page loads them side by side. Money goes out as strings, like the rest of the API.

Definitions used throughout:
- Billed: totals of the period's bills (by bill date), after discounts. Cancelled bills are left out.
- Collected: money received in the period (by date received), refunds taken off, whatever the bill's date,
  so it includes dues paid against older bills.
- Collection efficiency: of what the period's bills came to, how much has been paid on them so far.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Date, Integer, and_, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Invalid
from app.core.money import ZERO, local_now, local_today, q2
from app.core.security import CurrentUser
from app.models import Department, Invoice, InvoiceItem, Payment

CANCELLED = "cancelled"
WAITING = ("billed", "scanned")
PIPELINE = ("billed", "scanned", "reported", "delivered")
AGE_BANDS = ("0–12", "13–17", "18–29", "30–44", "45–59", "60+", "Not given")
DUE_BUCKETS = (("0–7 days", 0, 7), ("8–30 days", 8, 30), ("31–90 days", 31, 90), ("Over 90 days", 91, None))


def money(v) -> str:
    return str(q2(v or 0))


def pct(part, whole) -> float | None:
    whole = Decimal(whole or 0)
    return round(float(Decimal(part or 0) / whole * 100), 1) if whole else None


@dataclass
class AnalyticsFilters:
    date_from: date | None = None
    date_to: date | None = None
    department_id: uuid.UUID | None = None
    doctor: str = ""                    # a referring doctor's id, "self" for self-referred, or "" for any
    created_by: uuid.UUID | None = None


class AnalyticsService:
    def __init__(self, db: Session, current: CurrentUser, f: AnalyticsFilters, today: date | None = None):
        self.db = db
        self.t = current.user.tenant_id
        self.f = f
        self.today = today or local_today()
        self.tz = get_settings().display_timezone
        to = min(f.date_to or self.today, self.today)
        self.all_time = f.date_from is None
        frm = f.date_from or self.db.scalar(select(func.min(Invoice.bill_date)).where(Invoice.tenant_id == self.t)) or to
        if frm > to:
            raise Invalid("The start date is after the end date.", field="from")
        self.frm, self.to = frm, to
        self.days = (to - frm).days + 1
        self.unit = "day" if self.days <= 62 else "week" if self.days <= 371 else "month"

    # ---------- building blocks ----------
    def _bill_filters(self, *, dated: bool = True, live: bool = True, items: bool = True) -> list:
        """Conditions on Invoice for the chosen filters. `items=False` leaves the department to the caller
        (queries over invoice lines filter the line itself)."""
        f = self.f
        c = [Invoice.tenant_id == self.t]
        if live:
            c.append(Invoice.status != CANCELLED)
        if dated:
            c += [Invoice.bill_date >= self.frm, Invoice.bill_date <= self.to]
        if f.doctor == "self":
            c.append(Invoice.referring_doctor_id.is_(None))
        elif f.doctor:
            c.append(Invoice.referring_doctor_id == uuid.UUID(f.doctor))
        if f.created_by:
            c.append(Invoice.created_by == f.created_by)
        if items and f.department_id:
            c.append(select(InvoiceItem.id).where(InvoiceItem.invoice_id == Invoice.id, InvoiceItem.status != CANCELLED,
                                                  InvoiceItem.department_id == f.department_id).exists())
        return c

    def _item_filters(self) -> list:
        c = [InvoiceItem.tenant_id == self.t, InvoiceItem.status != CANCELLED, *self._bill_filters(items=False)]
        if self.f.department_id:
            c.append(InvoiceItem.department_id == self.f.department_id)
        return c

    def _payments(self, a: date, b: date):
        """Payments received between a and b on bills matching every filter but the bill date."""
        return (select().select_from(Payment).join(Invoice, Invoice.id == Payment.invoice_id)
                .where(Payment.tenant_id == self.t, Payment.received_on >= a, Payment.received_on <= b,
                       *self._bill_filters(dated=False, live=False)))

    @staticmethod
    def _signed():
        return case((Payment.kind == "payment", Payment.amount), else_=-Payment.amount)

    def _bucket(self, col):
        return col if self.unit == "day" else cast(func.date_trunc(self.unit, col), Date)

    def _start(self, d: date) -> date:
        if self.unit == "week":
            return d - timedelta(days=d.weekday())
        if self.unit == "month":
            return d.replace(day=1)
        return d

    def _keys(self) -> list[date]:
        keys, d = [], self._start(self.frm)
        while d <= self.to:
            keys.append(d)
            d = d + timedelta(days=1) if self.unit == "day" else d + timedelta(days=7) if self.unit == "week" \
                else (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        return keys

    def _local(self, col):
        return func.timezone(self.tz, col)

    def period(self) -> dict:
        return {"date_from": self.frm, "date_to": self.to, "days": self.days, "all_time": self.all_time, "unit": self.unit}

    # ---------- sections ----------
    def summary(self) -> dict:
        def bills(a: date, b: date):
            return self.db.execute(
                select(func.count(), func.coalesce(func.sum(Invoice.total), 0), func.coalesce(func.sum(Invoice.discount_amount), 0),
                       func.coalesce(func.sum(Invoice.subtotal), 0), func.coalesce(func.sum(Invoice.paid), 0),
                       func.coalesce(func.sum(Invoice.due), 0), func.count(func.distinct(Invoice.patient_id)))
                .where(*self._bill_filters(dated=False), Invoice.bill_date >= a, Invoice.bill_date <= b)).one()

        def collected(a: date, b: date) -> Decimal:
            return self.db.scalar(self._payments(a, b).add_columns(func.coalesce(func.sum(self._signed()), 0))) or ZERO

        now = bills(self.frm, self.to)
        prev_to = self.frm - timedelta(days=1)
        prev_from = prev_to - timedelta(days=self.days - 1)
        before = bills(prev_from, prev_to)
        by_mode = {m: money(v) for m, v in self.db.execute(
            self._payments(self.frm, self.to).add_columns(Payment.mode, func.sum(self._signed())).group_by(Payment.mode)).all()}
        refunds = self.db.scalar(self._payments(self.frm, self.to).add_columns(func.coalesce(func.sum(Payment.amount), 0))
                                 .where(Payment.kind == "refund")) or 0
        dues_collected = self.db.scalar(self._payments(self.frm, self.to).add_columns(func.coalesce(func.sum(Payment.amount), 0))
                                        .where(Payment.kind == "payment", Invoice.bill_date < self.frm)) or 0
        cancelled = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.subtotal), 0))
                                    .where(*self._bill_filters(live=False), Invoice.status == CANCELLED)).one()
        outstanding = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.due), 0))
                                      .where(*self._bill_filters(dated=False), Invoice.due > 0)).one()
        tests = self.db.scalar(select(func.count()).select_from(InvoiceItem).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                               .where(*self._item_filters())) or 0
        coll_now = collected(self.frm, self.to)
        return {
            **self.period(),
            "bills": now[0], "billed": money(now[1]), "discounts": money(now[2]), "discount_pct": pct(now[2], now[3]),
            "paid_on_bills": money(now[4]), "due_on_bills": money(now[5]), "patients": now[6], "tests": tests,
            "average_bill": money(Decimal(now[1]) / now[0]) if now[0] else money(0),
            "collected": money(coll_now), "collected_by_mode": by_mode, "refunds": money(refunds), "dues_collected": money(dues_collected),
            "efficiency_pct": pct(now[4], now[1]),
            "cancelled": cancelled[0], "cancelled_amount": money(cancelled[1]),
            "outstanding_dues": money(outstanding[1]), "dues_count": outstanding[0],
            "previous": {"date_from": prev_from, "date_to": prev_to, "bills": before[0], "billed": money(before[1]),
                         "collected": money(collected(prev_from, prev_to)), "patients": before[6]},
        }

    def trend(self) -> dict:
        """Bucketed by day, week or month (by the span): billed, collected (by mode), bills, discounts,
        efficiency, cancellations and refunds."""
        bi, bp = self._bucket(Invoice.bill_date), self._bucket(Payment.received_on)
        billed = {k: r for k, *r in self.db.execute(
            select(bi, func.count(), func.sum(Invoice.total), func.sum(Invoice.discount_amount), func.sum(Invoice.subtotal), func.sum(Invoice.paid))
            .where(*self._bill_filters()).group_by(bi)).all()}
        start = self._start(self.frm)
        modes: dict[date, dict[str, Decimal]] = {}
        refunds: dict[date, Decimal] = {}
        for k, mode, kind, amount in self.db.execute(
                self._payments(start, self.to).add_columns(bp, Payment.mode, Payment.kind, func.sum(Payment.amount))
                .group_by(bp, Payment.mode, Payment.kind)).all():
            if k < start:
                continue
            sign = 1 if kind == "payment" else -1
            modes.setdefault(k, {})[mode] = modes.get(k, {}).get(mode, ZERO) + sign * amount
            if kind == "refund":
                refunds[k] = refunds.get(k, ZERO) + amount
        cancelled = {k: (n, a) for k, n, a in self.db.execute(
            select(bi, func.count(), func.sum(Invoice.subtotal)).where(*self._bill_filters(live=False), Invoice.status == CANCELLED)
            .group_by(bi)).all()}
        points = []
        for k in self._keys():
            n, total, disc, sub, paid = billed.get(k, (0, 0, 0, 0, 0))
            by_mode = modes.get(k, {})
            points.append({
                "key": k, "bills": n, "billed": money(total), "collected": money(sum(by_mode.values(), ZERO)),
                "by_mode": {m: money(v) for m, v in by_mode.items()},
                "average_bill": money(Decimal(total or 0) / n) if n else money(0),
                "discounts": money(disc), "discount_pct": pct(disc, sub), "efficiency_pct": pct(paid, total),
                "refunds": money(refunds.get(k)), "cancelled": cancelled.get(k, (0, 0))[0], "cancelled_amount": money(cancelled.get(k, (0, 0))[1]),
            })
        return {**self.period(), "points": points}

    def heatmap(self) -> dict:
        """Bills by weekday (Monday = 1) and hour of the day, on the centre's clock."""
        local = self._local(Invoice.created_at)
        dow, hour = cast(func.extract("isodow", local), Integer), cast(func.extract("hour", local), Integer)
        cells = [{"weekday": d, "hour": h, "bills": n, "billed": money(a)} for d, h, n, a in self.db.execute(
            select(dow, hour, func.count(), func.sum(Invoice.total)).where(*self._bill_filters()).group_by(dow, hour)).all()]
        return {**self.period(), "cells": cells}

    def departments(self) -> dict:
        rows = self.db.execute(
            select(InvoiceItem.department_name, func.sum(InvoiceItem.amount), func.sum(InvoiceItem.quantity),
                   func.count(func.distinct(InvoiceItem.invoice_id)))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(*self._item_filters())
            .group_by(InvoiceItem.department_name).order_by(func.sum(InvoiceItem.amount).desc())).all()
        return {**self.period(), "rows": [{"name": n or "Other", "amount": money(a), "tests": int(t or 0), "bills": b} for n, a, t, b in rows]}

    def tests(self, limit: int = 10) -> dict:
        base = (select(InvoiceItem.test_name, InvoiceItem.department_name, func.sum(InvoiceItem.amount), func.sum(InvoiceItem.quantity))
                .join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(*self._item_filters())
                .group_by(InvoiceItem.test_name, InvoiceItem.department_name))
        out = lambda rows: [{"name": n, "department": d or "Other", "amount": money(a), "count": int(c or 0)} for n, d, a, c in rows]  # noqa: E731
        return {**self.period(),
                "by_revenue": out(self.db.execute(base.order_by(func.sum(InvoiceItem.amount).desc()).limit(limit)).all()),
                "by_count": out(self.db.execute(base.order_by(func.sum(InvoiceItem.quantity).desc(), func.sum(InvoiceItem.amount).desc()).limit(limit)).all())}

    def doctors(self, limit: int = 10) -> dict:
        conds = self._bill_filters()
        top = self.db.execute(
            select(Invoice.referring_doctor_id, func.max(Invoice.referring_doctor_name), func.count(), func.sum(Invoice.total))
            .where(*conds, Invoice.referring_doctor_id.is_not(None))
            .group_by(Invoice.referring_doctor_id).order_by(func.count().desc(), func.sum(Invoice.total).desc()).limit(limit)).all()
        ids = [r[0] for r in top]
        bi = self._bucket(Invoice.bill_date)
        series: dict[uuid.UUID, dict[date, int]] = {}
        if ids:
            for doc, k, n in self.db.execute(select(Invoice.referring_doctor_id, bi, func.count())
                                              .where(*conds, Invoice.referring_doctor_id.in_(ids)).group_by(Invoice.referring_doctor_id, bi)).all():
                series.setdefault(doc, {})[k] = n
        keys = self._keys()
        self_referred = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0))
                                        .where(*conds, Invoice.referring_doctor_id.is_(None))).one()
        referred = self.db.execute(select(func.count(), func.count(func.distinct(Invoice.referring_doctor_id)))
                                   .where(*conds, Invoice.referring_doctor_id.is_not(None))).one()
        return {**self.period(), "keys": keys,
                "rows": [{"id": d, "name": name, "bills": n, "amount": money(a), "trend": [series.get(d, {}).get(k, 0) for k in keys]}
                         for d, name, n, a in top],
                "self_referred": {"bills": self_referred[0], "amount": money(self_referred[1])},
                "referred": {"bills": referred[0], "doctors": referred[1]}}

    def patients(self) -> dict:
        """New (first bill ever falls in the bucket) against returning patients, and the period's visits by
        age band and gender (age as written on the bill)."""
        first = (select(Invoice.patient_id.label("pid"), func.min(Invoice.bill_date).label("first"))
                 .where(Invoice.tenant_id == self.t, Invoice.status != CANCELLED).group_by(Invoice.patient_id).subquery())
        bi = self._bucket(Invoice.bill_date)
        is_new = self._bucket(first.c.first) == bi
        rows = self.db.execute(select(bi, is_new, func.count(func.distinct(Invoice.patient_id)))
                               .join(first, first.c.pid == Invoice.patient_id).where(*self._bill_filters()).group_by(bi, is_new)).all()
        by: dict[date, dict[str, int]] = {}
        for k, new, n in rows:
            by.setdefault(k, {"new": 0, "returning": 0})["new" if new else "returning"] += n
        points = [{"key": k, **by.get(k, {"new": 0, "returning": 0})} for k in self._keys()]
        totals = self.db.execute(select(func.count(func.distinct(case((first.c.first >= self.frm, Invoice.patient_id)))),
                                        func.count(func.distinct(case((first.c.first < self.frm, Invoice.patient_id)))))
                                 .join(first, first.c.pid == Invoice.patient_id).where(*self._bill_filters())).one()

        years = cast(func.substring(Invoice.patient_age, r"^\s*(\d+)"), Integer)
        unit = func.upper(func.substring(Invoice.patient_age, r"^\s*\d+\s*([A-Za-z])"))
        age = case((unit.in_(("M", "D", "W")), literal(0)), else_=years)
        band = case((age.is_(None), literal(AGE_BANDS[6])), (age <= 12, literal(AGE_BANDS[0])), (age <= 17, literal(AGE_BANDS[1])),
                    (age <= 29, literal(AGE_BANDS[2])), (age <= 44, literal(AGE_BANDS[3])), (age <= 59, literal(AGE_BANDS[4])),
                    else_=literal(AGE_BANDS[5]))
        gender = case((Invoice.patient_gender.in_(("male", "female")), Invoice.patient_gender), else_=literal("other"))
        ages = {(b, g): n for b, g, n in self.db.execute(select(band, gender, func.count()).where(*self._bill_filters()).group_by(band, gender)).all()}
        return {**self.period(), "points": points, "new": totals[0], "returning": totals[1],
                "ages": [{"band": b, "female": ages.get((b, "female"), 0), "male": ages.get((b, "male"), 0), "other": ages.get((b, "other"), 0)}
                         for b in AGE_BANDS]}

    def dues(self) -> dict:
        """Everything still owed today, however old, by how long it has been owed (filters other than dates apply)."""
        days = cast(literal(self.today, Date) - Invoice.bill_date, Integer)  # date - date is a number of days in Postgres
        label = case(*[(and_(days >= lo, days <= hi) if hi is not None else days >= lo, literal(name)) for name, lo, hi in DUE_BUCKETS])
        got = {name: (n, a) for name, n, a in self.db.execute(
            select(label, func.count(), func.sum(Invoice.due)).where(*self._bill_filters(dated=False), Invoice.due > 0).group_by(label)).all()}
        rows = [{"bucket": name, "bills": got.get(name, (0, 0))[0], "amount": money(got.get(name, (0, 0))[1])} for name, _, _ in DUE_BUCKETS]
        return {**self.period(), "rows": rows, "total": money(sum((Decimal(r["amount"]) for r in rows), ZERO)),
                "bills": sum(r["bills"] for r in rows)}

    def staff(self) -> dict:
        billed = self.db.execute(
            select(Invoice.created_by, func.max(Invoice.created_by_name), func.count(), func.sum(Invoice.total), func.sum(Invoice.discount_amount))
            .where(*self._bill_filters()).group_by(Invoice.created_by).order_by(func.sum(Invoice.total).desc())).all()
        taken = dict(self.db.execute(
            self._payments(self.frm, self.to).add_columns(Payment.received_by, func.sum(self._signed())).group_by(Payment.received_by)).all())
        return {**self.period(), "rows": [
            {"id": uid, "name": name or "Unknown", "bills": n, "billed": money(a), "discounts": money(d),
             "average_bill": money(Decimal(a or 0) / n) if n else money(0), "collected": money(taken.get(uid))}
            for uid, name, n, a, d in billed]}

    def pipeline(self) -> dict:
        """The period's tests by where they are now, how many reached each stage, and the average hours from
        billing to the stage they're at (from when the bill was made to the last progress change)."""
        hours = func.extract("epoch", InvoiceItem.status_changed_at - Invoice.created_at) / 3600
        rows = {s: (n, h) for s, n, h in self.db.execute(
            select(InvoiceItem.status, func.count(),
                   func.avg(case((and_(InvoiceItem.status_changed_at.is_not(None), InvoiceItem.status_changed_at >= Invoice.created_at), hours))))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(*self._item_filters()).group_by(InvoiceItem.status)).all()}
        stages = []
        for i, s in enumerate(PIPELINE):
            n, h = rows.get(s, (0, None))
            stages.append({"stage": s, "now": n, "reached": sum(rows.get(x, (0, None))[0] for x in PIPELINE[i:]),
                           "avg_hours": round(float(h), 1) if h is not None and s != "billed" else None})
        return {**self.period(), "stages": stages, "total": sum(s["now"] for s in stages)}

    # ---------- live: today, the whole centre ----------
    def live(self) -> dict:
        t, today = self.t, self.today
        live = and_(Invoice.tenant_id == t, Invoice.status != CANCELLED)
        bills = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0), func.coalesce(func.sum(Invoice.due), 0),
                                       func.count(func.distinct(Invoice.patient_id))).where(live, Invoice.bill_date == today)).one()
        signed = self._signed()
        by_mode = {m: money(v) for m, v in self.db.execute(select(Payment.mode, func.sum(signed))
                                                           .where(Payment.tenant_id == t, Payment.received_on == today).group_by(Payment.mode)).all()}
        dues_collected = self.db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).join(Invoice, Invoice.id == Payment.invoice_id)
                                        .where(Payment.tenant_id == t, Payment.received_on == today, Payment.kind == "payment",
                                               Invoice.bill_date < today)) or 0
        waiting = dict(self.db.execute(select(InvoiceItem.status, func.count()).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                                       .where(live, Invoice.bill_date == today, InvoiceItem.status.in_(WAITING)).group_by(InvoiceItem.status)).all())
        hour = cast(func.extract("hour", self._local(Invoice.created_at)), Integer)
        today_hours = dict(self.db.execute(select(hour, func.count()).where(live, Invoice.bill_date == today).group_by(hour)).all())
        # The same weekday over the previous eight weeks, averaged over the days the centre billed anything.
        same = [today - timedelta(weeks=w) for w in range(1, 9)]
        past = self.db.execute(select(hour, func.count(), func.count(func.distinct(Invoice.bill_date)))
                               .where(live, Invoice.bill_date.in_(same)).group_by(hour)).all()
        open_days = self.db.scalar(select(func.count(func.distinct(Invoice.bill_date))).where(live, Invoice.bill_date.in_(same))) or 0
        avg = {h: round(n / open_days, 1) for h, n, _ in past} if open_days else {}
        hours = [{"hour": h, "today": today_hours.get(h, 0), "average": avg.get(h, 0)} for h in range(24)]
        recent = self.db.execute(select(Invoice.id, Invoice.invoice_no, Invoice.created_at, Invoice.patient_name, Invoice.referring_doctor_name,
                                        Invoice.total, Invoice.paid, Invoice.due, Invoice.created_by_name, Invoice.status)
                                 .where(Invoice.tenant_id == t).order_by(Invoice.created_at.desc()).limit(12)).all()
        collected = sum((Decimal(v) for v in by_mode.values()), ZERO)
        return {
            "as_of": local_now().isoformat(timespec="seconds"), "day": today, "weekday": today.strftime("%A"), "compared_days": open_days,
            "bills": bills[0], "billed": money(bills[1]), "due_on_bills": money(bills[2]), "patients": bills[3],
            "collected": money(collected), "collected_by_mode": by_mode, "dues_collected": money(dues_collected),
            "waiting": {"billed": waiting.get("billed", 0), "scanned": waiting.get("scanned", 0)},
            "hours": hours,
            "recent": [{"id": r[0], "invoice_no": r[1], "created_at": r[2], "patient_name": r[3], "doctor": r[4] or "Self",
                        "total": money(r[5]), "paid": money(r[6]), "due": money(r[7]), "created_by_name": r[8], "status": r[9]} for r in recent],
        }

    # ---------- what the filters can be set to ----------
    def options(self) -> dict:
        t = self.t
        departments = [{"id": i, "name": n} for i, n in self.db.execute(
            select(Department.id, Department.name).where(Department.tenant_id == t).order_by(Department.name)).all()]
        doctors = [{"id": i, "name": n} for i, n, _ in self.db.execute(
            select(Invoice.referring_doctor_id, func.max(Invoice.referring_doctor_name), func.count())
            .where(Invoice.tenant_id == t, Invoice.referring_doctor_id.is_not(None))
            .group_by(Invoice.referring_doctor_id).order_by(func.count().desc()).limit(300)).all()]
        billers = [{"id": i, "name": n or "Unknown"} for i, n in self.db.execute(
            select(Invoice.created_by, func.max(Invoice.created_by_name)).where(Invoice.tenant_id == t, Invoice.created_by.is_not(None))
            .group_by(Invoice.created_by).order_by(func.max(Invoice.created_by_name))).all()]
        return {"departments": departments, "doctors": sorted(doctors, key=lambda d: d["name"].lower()), "billers": billers}
