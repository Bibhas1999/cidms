"""Business reports: collection, dues, doctors, tests, departments, staff, discounts and payments, and the bills
list as a file. Every report is a table (columns, rows, totals) so the screen, Excel and PDF show the same thing.

Billing figures are dated by the bill's date; money received by the day it was received (the centre's local
date). Cancelled bills never count in totals. Collected = payments minus refunds.
"""

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session, noload

from app.catalog import CLIENT_PERMISSIONS
from app.core.errors import Forbidden, Invalid, NotFound
from app.core.money import ZERO, local_today, q2
from app.core.security import CurrentUser
from app.models import Department, Invoice, InvoiceItem, LabTest, Payment, ReferringDoctor, User
from app.services.billing import CANCELLED, BillFilters, BillingService
from app.services.exports import Column, day_text, indian

MODES = ("cash", "upi", "card", "bank", "other")
ROW_CAP = 20_000
MAX_DAYS = 400
LIMITS = {"day": MAX_DAYS, "week": 270, "month": None, "year": None}  # most rows per collection grouping


@dataclass
class Report:
    name: str
    title: str
    subtitle: str
    columns: list[Column]
    rows: list[dict]
    totals: dict | None = None
    summary: list[dict] = field(default_factory=list)  # [{label, value, kind}] shown above the table
    landscape: bool = False
    # A report that is a workbook (Bills): this table is its first sheet, these are the others.
    sheets: list["Report"] = field(default_factory=list)

    def as_json(self) -> dict:
        kinds = {key: kind for key, _, kind in self.columns}
        return {
            "name": self.name, "title": self.title, "subtitle": self.subtitle,
            "columns": [{"key": k, "label": label, "kind": kind} for k, label, kind in self.columns],
            "rows": [{k: _json(v, kinds.get(k, "text")) for k, v in row.items()} for row in self.rows],
            "totals": {k: _json(v, kinds.get(k, "text")) for k, v in self.totals.items()} if self.totals is not None else None,
            "summary": [{**s, "value": _json(s["value"], s.get("kind", "text"))} for s in self.summary],
            **({"sheets": [s.as_json() for s in self.sheets]} if self.sheets else {}),
        }


def _json(value, kind: str):
    if isinstance(value, Decimal):
        return str(q2(value)) if kind in ("money", "percent") else str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


GROUPS = ("day", "week", "month", "year")


@dataclass
class ReportParams:
    date_from: date | None = None
    date_to: date | None = None
    all_time: bool = False            # no dates: everything since the first bill
    group: str = "day"                # collection: one row per day | week | month | year
    department_id: uuid.UUID | None = None
    mode: str = ""                    # payments: only this payment mode


# Turnover-type figures are for the owner and centre admin (analytics.view, once the catalogue has it);
# dues and payments are for anyone who sees business reports.
ANALYTICS = "analytics.view" if "analytics.view" in CLIENT_PERMISSIONS else "business_reports.view"
MONEY_IN = "business_reports.view"
PERMISSION = {"dues": MONEY_IN, "payments": MONEY_IN, "bills": MONEY_IN}

CATALOGUE = [
    {"name": "bills", "group": "money", "title": "Bills",
     "question": "Which bills, and which doctor sent them?",
     "description": "Every bill in the dates as a workbook: a summary by referring doctor, then a sheet for each doctor.",
     "filters": ["range"]},
    {"name": "collection", "group": "money", "title": "Collection",
     "question": "How much did we bill and collect?",
     "description": "Bills, discounts and money received, by payment mode — one row per day, week, month or year.",
     "filters": ["range", "group"]},
    {"name": "payments", "group": "money", "title": "Payments",
     "question": "Who paid what, and how?",
     "description": "Every payment and refund, with mode, reference and who received it.", "filters": ["range", "mode"]},
    {"name": "dues", "group": "money", "title": "Dues",
     "question": "Who still owes us?",
     "description": "Bills with money still owed, oldest first, with how long they've been owed.", "filters": ["range_optional"]},
    {"name": "discounts", "group": "money", "title": "Discounts",
     "question": "Where did we give discounts?",
     "description": "Every bill given a discount, how much, and who billed it.", "filters": ["range"]},
    {"name": "tests", "group": "work", "title": "Tests",
     "question": "Which tests were done most?",
     "description": "How many of each test were billed, and for how much.", "filters": ["range", "department"]},
    {"name": "departments", "group": "work", "title": "Departments",
     "question": "Which departments bring in the most?",
     "description": "Tests, bills and amount by department.", "filters": ["range"]},
    {"name": "referring-doctors", "group": "work", "title": "Referring doctors",
     "question": "Which doctors refer the most?",
     "description": "Bills and amount by referring doctor.", "filters": ["range"]},
    {"name": "staff", "group": "work", "title": "Staff",
     "question": "Who billed and collected what?",
     "description": "Bills made and money received by each person.", "filters": ["range"]},
]
for _r in CATALOGUE:
    _r["permission"] = PERMISSION.get(_r["name"], ANALYTICS)
BY_NAME = {r["name"]: r for r in CATALOGUE}


def visible_reports(current: CurrentUser) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "permission"} for r in CATALOGUE if current.can(r["permission"])]


def range_text(a: date | None, b: date | None) -> str:
    if a and b:
        return day_text(a) if a == b else f"{day_text(a)} to {day_text(b)}"
    if a:
        return f"From {day_text(a)}"
    if b:
        return f"Up to {day_text(b)}"
    return "All dates"


def rs(v: Decimal) -> str:
    return f"₹{indian(v)}"


class ReportService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.t = current.user.tenant_id

    # ---------- dispatch ----------
    def run(self, name: str, p: ReportParams) -> Report:
        meta = BY_NAME.get(name)
        if meta is None:
            raise NotFound("There's no such report.")
        if not self.current.can(meta["permission"]):
            raise Forbidden("You don't have permission to see this report.")
        if p.group not in GROUPS:
            raise Invalid("Group by day, week, month or year.", "group")
        if p.all_time:
            p.date_from = self.db.scalar(select(func.min(Invoice.bill_date)).where(Invoice.tenant_id == self.t)) or local_today()
            p.date_to = local_today()
        if "range" in meta["filters"]:
            p.date_from, p.date_to = self._range(p.date_from, p.date_to)
        elif p.date_from and p.date_to and p.date_from > p.date_to:
            raise Invalid("The start date is after the end date.", "from")
        return getattr(self, name.replace("-", "_"))(p)

    def _range(self, a: date | None, b: date | None) -> tuple[date, date]:
        today = local_today()
        a = a or (b or today).replace(day=1)
        b = b or max(a, today)
        if a > b:
            raise Invalid("The start date is after the end date.", "from")
        return a, b

    def _live(self):
        return (Invoice.tenant_id == self.t, Invoice.status != "cancelled")

    # ---------- collection ----------
    def _collection(self, inv_key, pay_key, start: date, end: date) -> dict:
        """Billing and money received in [start, end], grouped by inv_key(bill_date) / pay_key(received_on)."""
        out: dict = {}
        ik, pk = inv_key(Invoice.bill_date), pay_key(Payment.received_on)

        def slot(k):
            return out.setdefault(k, {"bills": 0, "billed": ZERO, "discounts": ZERO, **dict.fromkeys(MODES, ZERO),
                                      "refunds": ZERO, "net": ZERO, "dues_collected": ZERO})

        for k, n, billed, disc in self.db.execute(
                select(ik, func.count(), func.coalesce(func.sum(Invoice.total), 0),
                       func.coalesce(func.sum(Invoice.discount_amount), 0))
                .where(*self._live(), Invoice.bill_date >= start, Invoice.bill_date <= end).group_by(ik)):
            s = slot(k)
            s["bills"], s["billed"], s["discounts"] = n, q2(billed), q2(disc)
        signed = case((Payment.kind == "payment", Payment.amount), else_=-Payment.amount)
        in_range = (Payment.tenant_id == self.t, Payment.received_on >= start, Payment.received_on <= end)
        for k, mode, amount in self.db.execute(select(pk, Payment.mode, func.sum(signed))
                                               .where(*in_range).group_by(pk, Payment.mode)):
            s = slot(k)
            s[mode if mode in MODES else "other"] += q2(amount)
            s["net"] += q2(amount)
        for k, amount in self.db.execute(select(pk, func.sum(Payment.amount))
                                         .where(*in_range, Payment.kind == "refund").group_by(pk)):
            slot(k)["refunds"] = q2(amount)
        for k, amount in self.db.execute(
                select(pk, func.sum(Payment.amount)).join(Invoice, Invoice.id == Payment.invoice_id)
                .where(*in_range, Payment.kind == "payment", Invoice.bill_date < Payment.received_on).group_by(pk)):
            slot(k)["dues_collected"] = q2(amount)
        return out

    def _collection_columns(self, first: Column) -> list[Column]:
        return [first, ("bills", "Bills", "int"), ("billed", "Billed", "money"), ("discounts", "Discounts", "money"),
                ("cash", "Cash", "money"), ("upi", "UPI", "money"), ("card", "Card", "money"), ("bank", "Bank", "money"),
                ("other", "Other", "money"), ("refunds", "Refunds", "money"), ("net", "Net collected", "money"),
                ("dues_collected", "Dues collected", "money")]

    @staticmethod
    def _sum(rows: list[dict], columns: list[Column], label: str = "Total") -> dict:
        totals: dict = {columns[0][0]: label}
        for key, _, kind in columns[1:]:
            if kind == "money":
                totals[key] = q2(sum((r[key] for r in rows if r.get(key) is not None), ZERO))
            elif kind == "int":
                totals[key] = sum(r[key] or 0 for r in rows)
        return totals

    def _collection_summary(self, totals: dict) -> list[dict]:
        return [{"label": "Bills", "value": totals["bills"], "kind": "int"},
                {"label": "Billed", "value": totals["billed"], "kind": "money"},
                {"label": "Net collected", "value": totals["net"], "kind": "money"},
                {"label": "Dues collected", "value": totals["dues_collected"], "kind": "money"}]

    def _empty_collection(self) -> dict:
        return {"bills": 0, "billed": ZERO, "discounts": ZERO, **dict.fromkeys(MODES, ZERO), "refunds": ZERO, "net": ZERO,
                "dues_collected": ZERO}



    def collection(self, p: ReportParams) -> Report:
        """Billing and money received for the range, one row per day, week (from Monday), month or year."""
        a, b, g = p.date_from, p.date_to, p.group

        def start(d: date) -> date:
            if g == "week":
                return d - timedelta(days=d.weekday())
            if g == "month":
                return d.replace(day=1)
            if g == "year":
                return d.replace(month=1, day=1)
            return d

        def step(d: date) -> date:
            if g == "week":
                return d + timedelta(days=7)
            if g == "month":
                return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
            if g == "year":
                return d.replace(year=d.year + 1)
            return d + timedelta(days=1)

        keys, k = [], start(a)
        while k <= b:
            keys.append(k)
            k = step(k)
        limit = LIMITS[g]
        if limit and len(keys) > limit:
            raise Invalid(f"That's {len(keys):,} {g}s — choose a shorter range, or group by a longer period.", "group")

        def bucket(col):
            return col if g == "day" else cast(func.date_trunc(g, col), Date)

        data = self._collection(bucket, bucket, a, b)
        label = {"day": ("Date", "date"), "week": ("Week from", "date"), "month": ("Month", "text"), "year": ("Year", "text")}[g]
        cols = self._collection_columns(("period", label[0], label[1]))

        def name(d: date):
            if g == "month":
                return f"{calendar.month_abbr[d.month]} {d.year}"
            if g == "year":
                return str(d.year)
            return d

        rows = [{"period": name(k), **(data.get(k) or self._empty_collection())} for k in keys]
        totals = self._sum(rows, cols)
        # Payment modes and refunds nobody used in the period are left out, so the table stays readable.
        unused = {k for k in (*MODES, "refunds") if not any(r[k] for r in rows)}
        cols = [c for c in cols if c[0] not in unused]
        sub = f"{range_text(a, b)} · by {g}"
        return Report("collection", "Collection", sub, cols, rows, totals, self._collection_summary(totals), landscape=True)

    # ---------- dues ----------
    def bills(self, p: ReportParams) -> Report:
        """The bills in the dates as a workbook: the summary by referring doctor first, then one sheet per doctor
        (the same as the Bills page's "Workbook by referring doctor")."""
        listed = bills_report(self.db, self.current, BillFilters(date_from=p.date_from, date_to=p.date_to))
        (_title, _subtitle, columns, rows, totals), sheets = bills_by_doctor(listed)
        due_bills = sum(1 for r in listed.rows if r["status"] != "Cancelled" and r["due"] > 0)
        return Report("bills", "Bills", listed.subtitle, list(columns), list(rows), totals, summary=[
            {"label": "Bills", "value": totals["bills"], "kind": "int"},
            {"label": "Billed", "value": totals["total"], "kind": "money"},
            {"label": "Paid", "value": totals["paid"], "kind": "money"},
            {"label": "Total due", "value": totals["due"], "kind": "money"},
            {"label": "Bills with dues", "value": due_bills, "kind": "int"},
        ], sheets=[Report("bills", t, sub, list(c), list(r), tot, landscape=True) for t, sub, c, r, tot in sheets])

    def dues(self, p: ReportParams) -> Report:
        today = local_today()
        q = select(Invoice).options(noload(Invoice.items), noload(Invoice.payments)).where(*self._live(), Invoice.due > 0)
        if p.date_from:
            q = q.where(Invoice.bill_date >= p.date_from)
        if p.date_to:
            q = q.where(Invoice.bill_date <= p.date_to)
        bills = list(self.db.scalars(q.order_by(Invoice.bill_date, Invoice.created_at).limit(ROW_CAP + 1)))
        capped = len(bills) > ROW_CAP
        bills = bills[:ROW_CAP]
        buckets = {"0-30": ZERO, "31-60": ZERO, "61-90": ZERO, "90+": ZERO}
        rows = []
        for b in bills:
            age = (today - b.bill_date).days
            bucket = "0-30" if age <= 30 else "31-60" if age <= 60 else "61-90" if age <= 90 else "90+"
            buckets[bucket] += b.due
            rows.append({"id": str(b.id), "invoice_no": b.invoice_no, "bill_date": b.bill_date, "patient": b.patient_name,
                         "mobile": b.patient_mobile, "doctor": b.referring_doctor_name or "Self", "total": b.total,
                         "paid": b.paid, "due": b.due, "age": age})
        cols: list[Column] = [("invoice_no", "Bill no", "text"), ("bill_date", "Date", "date"), ("patient", "Patient", "text"),
                              ("mobile", "Mobile", "text"), ("doctor", "Referred by", "text"), ("total", "Total", "money"),
                              ("paid", "Paid", "money"), ("due", "Due", "money"), ("age", "Age (days)", "int")]
        totals = self._sum(rows, cols)
        totals.pop("age", None)
        ageing = " · ".join(f"{k} days {rs(v)}" for k, v in buckets.items())
        sub = f"As of {day_text(today)} · bills dated {range_text(p.date_from, p.date_to).lower()} · {ageing}"
        if capped:
            sub += f" · showing the oldest {ROW_CAP:,} only"
        summary = [{"label": "Bills with dues", "value": len(rows), "kind": "int"},
                   {"label": "Total due", "value": totals["due"], "kind": "money"},
                   *({"label": f"{k} days", "value": v, "kind": "money"} for k, v in buckets.items())]
        return Report("dues", "Dues", sub, cols, rows, totals, summary, landscape=True)

    # ---------- doctors, tests, departments ----------
    def referring_doctors(self, p: ReportParams) -> Report:
        name = func.coalesce(ReferringDoctor.name, "Self")
        rows = [{"doctor": doc, "bills": n, "billed": q2(billed), "discount": q2(disc), "average": q2(Decimal(billed) / n) if n else ZERO}
                for doc, n, billed, disc in self.db.execute(
                    select(name, func.count(), func.coalesce(func.sum(Invoice.total), 0), func.coalesce(func.sum(Invoice.discount_amount), 0))
                    .select_from(Invoice).outerjoin(ReferringDoctor, ReferringDoctor.id == Invoice.referring_doctor_id)
                    .where(*self._live(), Invoice.bill_date >= p.date_from, Invoice.bill_date <= p.date_to)
                    .group_by(Invoice.referring_doctor_id, ReferringDoctor.name)
                    .order_by(func.sum(Invoice.total).desc(), name))]
        cols: list[Column] = [("doctor", "Referring doctor", "text"), ("bills", "Bills", "int"), ("billed", "Billed", "money"),
                              ("discount", "Discount", "money"), ("average", "Average bill", "money")]
        totals = self._sum(rows, cols)
        totals["average"] = q2(totals["billed"] / totals["bills"]) if totals["bills"] else ZERO
        summary = [{"label": "Doctors", "value": sum(1 for r in rows if r["doctor"] != "Self"), "kind": "int"},
                   {"label": "Bills", "value": totals["bills"], "kind": "int"},
                   {"label": "Billed", "value": totals["billed"], "kind": "money"}]
        return Report("referring-doctors", "Referring doctors", range_text(p.date_from, p.date_to), cols, rows, totals, summary)

    def _items(self, p: ReportParams):
        return (InvoiceItem.status != CANCELLED, InvoiceItem.tenant_id == self.t, *self._live(),
                Invoice.bill_date >= p.date_from, Invoice.bill_date <= p.date_to)

    def tests(self, p: ReportParams) -> Report:
        q = (select(InvoiceItem.test_name, InvoiceItem.department_name, func.sum(InvoiceItem.quantity), func.sum(InvoiceItem.amount))
             .join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(*self._items(p)))
        sub = range_text(p.date_from, p.date_to)
        if p.department_id:
            q = q.where(InvoiceItem.department_id == p.department_id)
            dept = self.db.scalar(select(Department.name).where(Department.tenant_id == self.t, Department.id == p.department_id))
            if dept is None:
                raise Invalid("Choose a department from the list.", "department_id")
            sub += f" · {dept}"
        rows = [{"test": name, "department": dept or "", "count": n, "amount": q2(amount)} for name, dept, n, amount in self.db.execute(
            q.group_by(InvoiceItem.test_name, InvoiceItem.department_name).order_by(func.sum(InvoiceItem.amount).desc(), InvoiceItem.test_name))]
        cols: list[Column] = [("test", "Test", "text"), ("department", "Department", "text"), ("count", "Count", "int"),
                              ("amount", "Amount", "money")]
        totals = self._sum(rows, cols)
        summary = [{"label": "Different tests", "value": len(rows), "kind": "int"},
                   {"label": "Tests done", "value": totals["count"], "kind": "int"},
                   {"label": "Amount", "value": totals["amount"], "kind": "money"}]
        return Report("tests", "Tests", sub, cols, rows, totals, summary)

    def departments(self, p: ReportParams) -> Report:
        rows = [{"department": name or "Other", "tests": n, "bills": bills, "amount": q2(amount)} for name, n, bills, amount in self.db.execute(
            select(InvoiceItem.department_name, func.sum(InvoiceItem.quantity), func.count(func.distinct(InvoiceItem.invoice_id)),
                   func.sum(InvoiceItem.amount))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(*self._items(p))
            .group_by(InvoiceItem.department_name).order_by(func.sum(InvoiceItem.amount).desc()))]
        cols: list[Column] = [("department", "Department", "text"), ("tests", "Tests", "int"), ("bills", "Bills", "int"),
                              ("amount", "Amount", "money")]
        totals = self._sum(rows, cols)
        # A bill with tests from two departments counts once in each row, but once in the total.
        totals["bills"] = self.db.scalar(select(func.count(func.distinct(InvoiceItem.invoice_id)))
                                         .join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(*self._items(p))) or 0
        summary = [{"label": "Tests", "value": totals["tests"], "kind": "int"},
                   {"label": "Bills", "value": totals["bills"], "kind": "int"},
                   {"label": "Amount", "value": totals["amount"], "kind": "money"}]
        return Report("departments", "Departments", range_text(p.date_from, p.date_to), cols, rows, totals, summary)

    # ---------- staff ----------
    def staff(self, p: ReportParams) -> Report:
        people: dict = {}

        def person(uid, name):
            return people.setdefault(uid or name, {"staff": name or "Unknown", "bills": 0, "billed": ZERO, "payments": 0,
                                                   "received": ZERO, "refunds_count": 0, "refunds": ZERO, "net": ZERO})

        for uid, name, n, billed in self.db.execute(
                select(Invoice.created_by, func.max(Invoice.created_by_name), func.count(), func.coalesce(func.sum(Invoice.total), 0))
                .where(*self._live(), Invoice.bill_date >= p.date_from, Invoice.bill_date <= p.date_to).group_by(Invoice.created_by)):
            s = person(uid, name)
            s["bills"], s["billed"] = n, q2(billed)
        for uid, name, kind, n, amount in self.db.execute(
                select(Payment.received_by, func.max(Payment.received_by_name), Payment.kind, func.count(), func.sum(Payment.amount))
                .where(Payment.tenant_id == self.t, Payment.received_on >= p.date_from, Payment.received_on <= p.date_to)
                .group_by(Payment.received_by, Payment.kind)):
            s = person(uid, name)
            if kind == "refund":
                s["refunds_count"], s["refunds"] = n, q2(amount)
            else:
                s["payments"], s["received"] = n, q2(amount)
        ids = [k for k in people if isinstance(k, uuid.UUID)]
        if ids:
            for uid, full_name in self.db.execute(select(User.id, User.full_name).where(User.tenant_id == self.t, User.id.in_(ids))):
                people[uid]["staff"] = full_name
        rows = []
        for s in people.values():
            s["net"] = s["received"] - s["refunds"]
            rows.append(s)
        rows.sort(key=lambda r: (-r["billed"], -r["net"], r["staff"].lower()))
        cols: list[Column] = [("staff", "Staff", "text"), ("bills", "Bills made", "int"), ("billed", "Billed", "money"),
                              ("payments", "Payments", "int"), ("received", "Received", "money"), ("refunds_count", "Refunds", "int"),
                              ("refunds", "Refunded", "money"), ("net", "Net received", "money")]
        totals = self._sum(rows, cols)
        summary = [{"label": "Staff", "value": len(rows), "kind": "int"},
                   {"label": "Billed", "value": totals["billed"], "kind": "money"},
                   {"label": "Net received", "value": totals["net"], "kind": "money"}]
        return Report("staff", "Staff", range_text(p.date_from, p.date_to), cols, rows, totals, summary)

    # ---------- discounts ----------
    def discounts(self, p: ReportParams) -> Report:
        q = (select(Invoice).options(noload(Invoice.items), noload(Invoice.payments))
             .where(*self._live(), Invoice.discount_amount > 0, Invoice.bill_date >= p.date_from, Invoice.bill_date <= p.date_to)
             .order_by(Invoice.bill_date, Invoice.created_at).limit(ROW_CAP + 1))
        bills = list(self.db.scalars(q))
        capped = len(bills) > ROW_CAP
        rows = [{"id": str(b.id), "invoice_no": b.invoice_no, "bill_date": b.bill_date, "patient": b.patient_name, "subtotal": b.subtotal,
                 "discount": b.discount_amount, "percent": q2(b.discount_amount * 100 / b.subtotal) if b.subtotal else ZERO,
                 "total": b.total, "billed_by": b.created_by_name} for b in bills[:ROW_CAP]]
        cols: list[Column] = [("invoice_no", "Bill no", "text"), ("bill_date", "Date", "date"), ("patient", "Patient", "text"),
                              ("subtotal", "Subtotal", "money"), ("discount", "Discount", "money"), ("percent", "%", "percent"),
                              ("total", "Total", "money"), ("billed_by", "Billed by", "text")]
        totals = self._sum(rows, cols)
        totals["percent"] = q2(totals["discount"] * 100 / totals["subtotal"]) if totals["subtotal"] else ZERO
        sub = range_text(p.date_from, p.date_to) + (f" · showing the first {ROW_CAP:,} only" if capped else "")
        summary = [{"label": "Bills discounted", "value": len(rows), "kind": "int"},
                   {"label": "Discount given", "value": totals["discount"], "kind": "money"},
                   {"label": "Average", "value": totals["percent"], "kind": "percent"}]
        return Report("discounts", "Discounts", sub, cols, rows, totals, summary)

    # ---------- payments ----------
    def payments(self, p: ReportParams) -> Report:
        q = (select(Payment, Invoice.invoice_no, Invoice.patient_name, Invoice.id).join(Invoice, Invoice.id == Payment.invoice_id)
             .where(Payment.tenant_id == self.t, Payment.received_on >= p.date_from, Payment.received_on <= p.date_to,
                    *((Payment.mode == p.mode,) if p.mode else ()))
             .order_by(Payment.received_at).limit(ROW_CAP + 1))
        found = self.db.execute(q).all()
        capped = len(found) > ROW_CAP
        rows, by_mode = [], dict.fromkeys(MODES, ZERO)
        for pay, invoice_no, patient, invoice_id in found[:ROW_CAP]:
            amount = pay.amount if pay.kind == "payment" else -pay.amount
            by_mode[pay.mode if pay.mode in MODES else "other"] += amount
            rows.append({"id": str(invoice_id), "received_at": pay.received_at, "invoice_no": invoice_no, "patient": patient,
                         "kind": "Refund" if pay.kind == "refund" else "Payment", "mode": pay.mode.upper() if pay.mode in ("upi",) else pay.mode.title(),
                         "reference": pay.reference or pay.note, "amount": q2(amount), "received_by": pay.received_by_name})
        cols: list[Column] = [("received_at", "When", "datetime"), ("invoice_no", "Bill no", "text"), ("patient", "Patient", "text"),
                              ("kind", "Kind", "text"), ("mode", "Mode", "text"), ("reference", "Reference / note", "text"),
                              ("amount", "Amount", "money"), ("received_by", "Received by", "text")]
        totals = self._sum(rows, cols)
        modes = [(m, v) for m, v in by_mode.items() if v]
        sub = range_text(p.date_from, p.date_to) + (f" · {'UPI' if p.mode == 'upi' else p.mode.title()} only" if p.mode else "")
        if modes:
            sub += " · " + " · ".join(f"{'UPI' if m == 'upi' else m.title()} {rs(v)}" for m, v in modes)
        if capped:
            sub += f" · showing the first {ROW_CAP:,} only"
        summary = [{"label": "Net received", "value": totals["amount"], "kind": "money"},
                   *({"label": "UPI" if m == "upi" else m.title(), "value": v, "kind": "money"} for m, v in modes)]
        return Report("payments", "Payments", sub, cols, rows, totals, summary, landscape=True)


# ---------- the bills list as a file ----------

BILL_COLUMNS: list[Column] = [
    ("invoice_no", "Bill no", "text"), ("bill_date", "Date", "date"), ("patient", "Patient", "text"), ("mobile", "Mobile", "text"),
    ("doctor", "Referred by", "text"), ("tests", "Tests", "text"), ("total", "Total", "money"), ("discount", "Discount", "money"),
    ("paid", "Paid", "money"), ("due", "Due", "money"), ("status", "Status", "text"), ("billed_by", "Billed by", "text"),
]
STATUS_TEXT = {"confirmed": "Confirmed", "on_hold": "On hold", "cancelled": "Cancelled"}


def bills_report(db: Session, current: CurrentUser, f: BillFilters) -> Report:
    """Every bill matching the bills list's filters (up to ROW_CAP), with its tests, in one query."""
    tests = (select(func.string_agg(InvoiceItem.test_name, aggregate_order_by(literal(", "), InvoiceItem.position)))
             .where(InvoiceItem.invoice_id == Invoice.id, InvoiceItem.status != CANCELLED).scalar_subquery())
    q = BillingService(db, current).query(f).options(noload(Invoice.items), noload(Invoice.payments)).add_columns(tests)
    found = db.execute(q.limit(ROW_CAP + 1)).all()
    capped = len(found) > ROW_CAP
    rows = [{"id": str(b.id), "invoice_no": b.invoice_no, "bill_date": b.bill_date, "patient": b.patient_name, "mobile": b.patient_mobile,
             "doctor": b.referring_doctor_name or "Self", "tests": names or "", "total": b.total, "discount": b.discount_amount,
             "paid": b.paid, "due": b.due, "status": STATUS_TEXT.get(b.status, b.status), "billed_by": b.created_by_name,
             "_cancelled": b.status == "cancelled"} for b, names in found[:ROW_CAP]]
    totals: dict = {"invoice_no": "Total"}
    live = [r for r in rows if not r["_cancelled"]]
    for key in ("total", "discount", "paid", "due"):
        totals[key] = q2(sum((r[key] for r in live), ZERO))
    for r in rows:
        r.pop("_cancelled")
    sub = describe_filters(db, current, f)
    sub += f" · {len(rows):,} bill{'s' if len(rows) != 1 else ''}"
    if any(r["status"] == "Cancelled" for r in rows):
        sub += " (cancelled bills are not in the totals)"
    if capped:
        sub += f" · only the first {ROW_CAP:,} are included; narrow the filters to see the rest"
    return Report("bills", "Bills", sub, BILL_COLUMNS, rows, totals, landscape=True)


DOCTOR_SUMMARY_COLUMNS: list[Column] = [
    ("doctor", "Referred by", "text"), ("bills", "Bills", "int"), ("total", "Total", "money"), ("discount", "Discount", "money"),
    ("paid", "Paid", "money"), ("due", "Due", "money"),
]


def bills_by_doctor(report: Report) -> tuple[tuple, list[tuple]]:
    """The bills report split by referring doctor: a summary (one row per doctor, biggest first, its name linking to
    the doctor's sheet) and one sheet per doctor with that doctor's bills and totals. Cancelled bills are listed but
    not added up, as in the bills report."""
    groups: dict[str, list[dict]] = {}
    for row in report.rows:
        groups.setdefault(row["doctor"] or "Self", []).append(row)
    columns = [c for c in report.columns if c[0] != "doctor"]
    keys = ("total", "discount", "paid", "due")
    summed = []
    for doctor, rows in groups.items():
        live = [r for r in rows if r["status"] != "Cancelled"]
        sums = {k: q2(sum((r[k] for r in live), ZERO)) for k in keys}
        summed.append((doctor, rows, live, sums))
    summed.sort(key=lambda g: (g[0] == "Self", -g[3]["total"], g[0].lower()))  # "Self" last
    sheets, summary_rows = [], []
    for doctor, rows, live, sums in summed:
        n = len(rows)
        sheets.append((doctor, f"{report.subtitle.split(' · ')[0]} · referred by {doctor} · {n:,} bill{'s' if n != 1 else ''}",
                       columns, rows, {"invoice_no": "Total", **sums}))
        summary_rows.append({"doctor": doctor, "bills": len(live), **sums})
    grand = {k: q2(sum((r[k] for r in summary_rows), ZERO)) for k in keys}
    summary = ("Summary", f"Bills by referring doctor · {report.subtitle}", DOCTOR_SUMMARY_COLUMNS, summary_rows,
               {"doctor": "All doctors", "bills": sum(r["bills"] for r in summary_rows), **grand})
    return summary, sheets


def describe_filters(db: Session, current: CurrentUser, f: BillFilters) -> str:
    t = current.user.tenant_id
    parts = [range_text(f.date_from, f.date_to)]
    if f.search.strip():
        parts.append(f'matching "{f.search.strip()}"')
    if f.status:
        parts.append(STATUS_TEXT.get(f.status, f.status))
    if f.payment:
        parts.append({"due": "With dues", "paid": "Fully paid", "part": "Part paid", "unpaid": "Unpaid"}.get(f.payment, f.payment))
    if f.mode:
        parts.append(f"Paid by {'UPI' if f.mode == 'upi' else f.mode}")
    if f.doctor_id:
        name = db.scalar(select(ReferringDoctor.name).where(ReferringDoctor.tenant_id == t, ReferringDoctor.id == f.doctor_id))
        parts.append(f"Referred by {name or 'a doctor'}")
    if f.self_referred:
        parts.append("Self referred")
    if f.patient_id:
        name = db.scalar(select(Invoice.patient_name).where(Invoice.tenant_id == t, Invoice.patient_id == f.patient_id).limit(1))
        parts.append(f"Patient {name or ''}".strip())
    if f.department_id:
        name = db.scalar(select(Department.name).where(Department.tenant_id == t, Department.id == f.department_id))
        parts.append(f"Department {name or ''}".strip())
    if f.test_id:
        name = db.scalar(select(LabTest.name).where(LabTest.tenant_id == t, LabTest.id == f.test_id))
        parts.append(f"Test {name or ''}".strip())
    if f.created_by:
        name = db.scalar(select(User.full_name).where(User.tenant_id == t, User.id == f.created_by))
        parts.append(f"Billed by {name or ''}".strip())
    if f.min_total is not None:
        parts.append(f"Total from {rs(f.min_total)}")
    if f.max_total is not None:
        parts.append(f"Total up to {rs(f.max_total)}")
    if f.discount:
        parts.append("With a discount" if f.discount == "yes" else "Without a discount")
    if f.report:
        parts.append({"pending": "Reports pending", "ready": "Reports ready to collect", "delivered": "All reports delivered"}[f.report])
    return " · ".join(parts)


def filters_for_log(f: BillFilters) -> dict:
    out = {}
    for k, v in f.__dict__.items():
        if v in (None, "", False):
            continue
        out[k] = v if isinstance(v, bool | int | str) else str(v)
    return out


def file_name(stem: str, a: date | None, b: date | None, ext: str) -> str:
    if a and b:
        span = a.isoformat() if a == b else f"{a.isoformat()}-to-{b.isoformat()}"
    elif a:
        span = f"from-{a.isoformat()}"
    elif b:
        span = f"to-{b.isoformat()}"
    else:
        span = local_today().isoformat()
    return f"{stem}-{span}.{ext}"
