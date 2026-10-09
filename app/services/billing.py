"""Bills, payments and dues: every money rule lives here.

- Totals are worked out on the server from the catalogue's prices; the browser only says which tests.
- Subtotal = the lines still on the bill. Discount is a percentage or an amount, stored as both the choice
  and the amount it came to. Total = subtotal - discount. Paid = payments - refunds. Due = total - paid.
- Money received is never edited or deleted: a mistake is corrected with a refund, which needs a reason.
- A bill is never deleted: it's put on hold or cancelled with a reason (only once nothing is left paid).
- Bill numbers run per centre and financial year (SHC/2026-27/000123), taken under a lock.
- Every change locks the bill row first, so two people changing one bill can't overwrite each other.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.money import ZERO, financial_year, local_today, q2, rupees
from app.core.security import CurrentUser
from app.models import Invoice, InvoiceItem, LabTest, Patient, Payment, ReferringDoctor, Tenant, TenantSettings, utcnow
from app.repositories.common import contains
from app.repositories.counters import next_number
from app.schemas_billing import BillIn, BillLineIn, BillUpdateIn, PaymentIn, RefundIn
from app.services.audit import AuditService
from app.services.catalogue import CatalogueService
from app.services.patients import PatientService, age_text

CANCELLED = "cancelled"  # a line taken off the bill; every other status counts towards it
ITEM_FLOW = {  # which progress changes the worklist may make in phase 2 (reports add "reported" in phase 4)
    "billed": {"scanned", "delivered"},
    "scanned": {"billed", "delivered"},
    "reported": {"delivered"},
    "delivered": {"scanned", "billed"},
}


def compute_discount(subtotal: Decimal, discount_type: str, value: Decimal) -> Decimal:
    if discount_type == "percent":
        amount = q2(subtotal * value / 100)
    elif discount_type == "amount":
        amount = q2(value)
    else:
        amount = ZERO
    if amount > subtotal:
        raise Invalid(f"The discount can't be more than the bill ({rupees(subtotal)}).", "discount_value")
    return amount


class BillingService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    # ---------- reading ----------
    def get(self, invoice_id: uuid.UUID, lock: bool = False) -> Invoice:
        q = select(Invoice).where(Invoice.tenant_id == self.tenant_id, Invoice.id == invoice_id)
        if lock:
            q = q.with_for_update().execution_options(populate_existing=True)
        row = self.db.scalar(q)
        if row is None:
            raise NotFound("We couldn't find that bill.")
        return row

    def page(self, search: str, date_from: date | None, date_to: date | None, status: str | None, due_only: bool,
             doctor_id: uuid.UUID | None, patient_id: uuid.UUID | None, page: int, size: int, oldest_first: bool = False):
        q = select(Invoice).where(Invoice.tenant_id == self.tenant_id)
        s = search.strip()
        if s:
            digits = "".join(ch for ch in s if ch.isdigit())
            conditions = [func.lower(Invoice.patient_name).like(contains(s), escape="\\"),
                          func.lower(Invoice.invoice_no) == s.lower()]
            if s.isdigit() and len(s) <= 9:
                conditions.append(Invoice.invoice_no.like(f"%/{int(s):06d}"))  # "123" finds .../000123 in any year
            if digits and len(digits) >= 4:
                conditions.append(Invoice.patient_mobile.like(f"%{digits}%"))
            if digits.isdigit() and len(digits) <= 7 and digits == s:
                conditions.append(Invoice.legacy_no == int(digits))
            q = q.where(or_(*conditions))
        if date_from:
            q = q.where(Invoice.bill_date >= date_from)
        if date_to:
            q = q.where(Invoice.bill_date <= date_to)
        if status:
            q = q.where(Invoice.status == status)
        if due_only:
            q = q.where(Invoice.due > 0, Invoice.status != "cancelled")
        if doctor_id:
            q = q.where(Invoice.referring_doctor_id == doctor_id)
        if patient_id:
            q = q.where(Invoice.patient_id == patient_id)
        counted = q.where(Invoice.status != "cancelled").subquery()
        totals = self.db.execute(select(func.count(), func.coalesce(func.sum(counted.c.total), 0),
                                        func.coalesce(func.sum(counted.c.due), 0))).one()
        total_rows = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        order = (Invoice.bill_date, Invoice.created_at) if oldest_first else (Invoice.bill_date.desc(), Invoice.created_at.desc())
        rows = self.db.scalars(q.order_by(*order).offset((page - 1) * size).limit(size)).all()
        return list(rows), total_rows, {"billed": q2(totals[1]), "due": q2(totals[2])}

    # ---------- helpers ----------
    def _settings(self) -> TenantSettings:
        return self.db.get(TenantSettings, self.tenant_id)

    def _tests(self, lines: list[BillLineIn]) -> dict[uuid.UUID, LabTest]:
        ids = {line.test_id for line in lines if line.test_id}
        if not ids:
            return {}
        found = {t.id: t for t in self.db.scalars(select(LabTest).where(LabTest.tenant_id == self.tenant_id, LabTest.id.in_(ids)))}
        missing = ids - set(found)
        if missing:
            raise Invalid("One of the tests isn't in your catalogue. Refresh the page and try again.", "lines")
        inactive = [t.name for t in found.values() if not t.is_active]
        if inactive:
            raise Invalid(f"{', '.join(inactive)} is switched off in the catalogue.", "lines")
        return found

    def _doctor(self, doctor_id: uuid.UUID | None, name: str) -> ReferringDoctor | None:
        if doctor_id:
            doc = self.db.scalar(select(ReferringDoctor).where(ReferringDoctor.tenant_id == self.tenant_id, ReferringDoctor.id == doctor_id))
            if doc is None:
                raise Invalid("Choose a doctor from the list.", "referring_doctor_id")
            return doc
        return CatalogueService(self.db, self.current).doctor_by_name_or_new(name)

    def _new_line(self, invoice: Invoice, position: int, test: LabTest, quantity: int) -> InvoiceItem:
        is_imaging = bool(test.test_type and test.test_type.is_imaging)
        item = InvoiceItem(
            tenant_id=self.tenant_id, position=position, test_id=test.id, test_name=test.name,
            department_id=test.department_id, department_name=test.department.name, is_imaging=is_imaging,
            unit_price=q2(test.price), quantity=quantity, amount=q2(test.price * quantity), status="billed",
            accession_no=self._accession(invoice.bill_date) if is_imaging else "",
        )
        invoice.items.append(item)
        return item

    def _accession(self, day: date) -> str:
        """The number a scanner puts on the images, so they find their way to this line (phase 4)."""
        stamp = day.strftime("%y%m%d")
        return f"A{stamp}{next_number(self.db, self.tenant_id, f'accession:{stamp}'):04d}"

    def _price(self, invoice: Invoice, discount_type: str, discount_value: Decimal) -> None:
        subtotal = q2(sum((i.amount for i in invoice.items if i.status != CANCELLED), ZERO))
        amount = compute_discount(subtotal, discount_type, discount_value)
        limit = self._settings().max_discount_percent
        if amount > 0 and subtotal > 0 and amount * 100 > subtotal * limit and not self.current.can("billing.discount_over_limit"):
            raise Forbidden(f"Discounts above {limit.normalize()}% need an admin. Ask them, or lower the discount.", "discount_value")
        invoice.subtotal = subtotal
        invoice.discount_type = discount_type
        invoice.discount_value = q2(discount_value)
        invoice.discount_amount = amount
        invoice.total = subtotal - amount
        self._settle(invoice)

    def _settle(self, invoice: Invoice) -> None:
        paid = sum((p.amount if p.kind == "payment" else -p.amount for p in invoice.payments), ZERO)
        invoice.paid = q2(paid)
        invoice.due = invoice.total - invoice.paid

    def _take(self, invoice: Invoice, kind: str, mode: str, amount: Decimal, reference: str = "", note: str = "") -> Payment:
        p = Payment(tenant_id=self.tenant_id, kind=kind, amount=q2(amount), mode=mode, reference=reference.strip(), note=note.strip(),
                    received_at=utcnow(), received_on=local_today(), received_by=self.current.id,
                    received_by_name=self.current.user.full_name)
        invoice.payments.append(p)
        self._settle(invoice)
        return p

    def _check_bill_limit(self) -> None:
        tenant = self.db.get(Tenant, self.tenant_id)
        if not tenant or not tenant.plan:
            return
        first = local_today().replace(day=1)
        count = self.db.scalar(select(func.count()).where(Invoice.tenant_id == self.tenant_id, Invoice.bill_date >= first)) or 0
        if count >= tenant.plan.max_bills_per_month:
            raise Conflict(f"Your plan allows {tenant.plan.max_bills_per_month} bills a month and this month's are used up. "
                           "Please contact Supreme DMS to change your plan.")

    def _not_cancelled(self, invoice: Invoice) -> None:
        if invoice.status == "cancelled":
            raise Conflict("This bill is cancelled and can't be changed.")

    # ---------- creating and changing bills ----------
    def create(self, data: BillIn) -> Invoice:
        self._check_bill_limit()
        patients = PatientService(self.db, self.current)
        patient: Patient = patients.get(data.patient_id) if data.patient_id else patients.create(data.patient)
        tests = self._tests(data.lines)
        doctor = self._doctor(data.referring_doctor_id, data.referring_doctor_name)
        settings = self._settings()
        today = local_today()
        fy = financial_year(today)
        number = next_number(self.db, self.tenant_id, f"invoice:{fy}")
        invoice = Invoice(
            tenant_id=self.tenant_id, invoice_no=f"{settings.invoice_prefix}/{fy}/{number:06d}", bill_date=today,
            patient_id=patient.id, patient_name=patient.name, patient_age=age_text(patient, today), patient_gender=patient.gender,
            patient_mobile=patient.mobile, patient_address=patient.address, guardian_name=patient.guardian_name,
            referring_doctor_id=doctor.id if doctor else None, referring_doctor_name=doctor.name if doctor else "",
            status="on_hold" if data.hold else "confirmed", notes=data.notes.strip(),
            created_by=self.current.id, created_by_name=self.current.user.full_name,
            subtotal=ZERO, total=ZERO, due=ZERO, items=[], payments=[],
        )
        for position, line in enumerate(data.lines, start=1):
            self._new_line(invoice, position, tests[line.test_id], line.quantity)
        self._price(invoice, data.discount_type, data.discount_value)
        taking = q2(sum((p.amount for p in data.payments), ZERO))
        if taking > invoice.total:
            raise Invalid(f"The payment ({rupees(taking)}) is more than the bill ({rupees(invoice.total)}).", "payments")
        for p in data.payments:
            self._take(invoice, "payment", p.mode, p.amount, p.reference, p.note)
        self.db.add(invoice)
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "bill.created", "invoice", invoice.id, {
            "invoice_no": invoice.invoice_no, "patient": patient.patient_no, "total": str(invoice.total), "paid": str(invoice.paid),
            "discount": str(invoice.discount_amount), "status": invoice.status})
        return invoice

    def update(self, invoice_id: uuid.UUID, data: BillUpdateIn) -> Invoice:
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        before = {"total": str(invoice.total), "tests": [i.test_name for i in invoice.items if i.status != CANCELLED]}
        existing = {i.id: i for i in invoice.items}
        kept: set[uuid.UUID] = set()
        tests = self._tests(data.lines)
        position = max((i.position for i in invoice.items), default=0)
        for line in data.lines:
            if line.id:
                item = existing.get(line.id)
                if item is None or item.status == CANCELLED:
                    raise Invalid("A line on this bill has changed. Refresh the page and try again.", "lines")
                if item.quantity != line.quantity:
                    if item.status != "billed":
                        raise Invalid(f"{item.test_name} is already {item.status}; its quantity can't change.", "lines")
                    item.quantity = line.quantity
                    item.amount = q2(item.unit_price * line.quantity)
                kept.add(item.id)
            else:
                position += 1
                self._new_line(invoice, position, tests[line.test_id], line.quantity)
        for item in invoice.items:
            if item.id in existing and item.id not in kept and item.status != CANCELLED:
                if item.status != "billed":
                    raise Invalid(f"{item.test_name} is already {item.status}, so it can't be taken off the bill.", "lines")
                item.status = CANCELLED
                item.status_changed_at = utcnow()
        doctor = self._doctor(data.referring_doctor_id, data.referring_doctor_name)
        invoice.referring_doctor_id = doctor.id if doctor else None
        invoice.referring_doctor_name = doctor.name if doctor else ""
        invoice.notes = data.notes.strip()
        self._price(invoice, data.discount_type, data.discount_value)
        if invoice.due < 0:
            raise Invalid(f"{rupees(invoice.paid)} has been paid, more than the new total of {rupees(invoice.total)}. "
                          f"Refund {rupees(-invoice.due)} first, then change the bill.", "lines")
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "bill.updated", "invoice", invoice.id, {
            "reason": data.reason, "total": [before["total"], str(invoice.total)],
            "tests": [before["tests"], [i.test_name for i in invoice.items if i.status != CANCELLED]]})
        return invoice

    def hold(self, invoice_id: uuid.UUID, reason: str) -> Invoice:
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        if invoice.status != "on_hold":
            invoice.status = "on_hold"
            self.audit.record(self.tenant_id, self.current.id, "bill.held", "invoice", invoice.id, {"reason": reason})
        return invoice

    def confirm(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        if invoice.status != "confirmed":
            invoice.status = "confirmed"
            self.audit.record(self.tenant_id, self.current.id, "bill.confirmed", "invoice", invoice.id)
        return invoice

    def cancel(self, invoice_id: uuid.UUID, reason: str) -> Invoice:
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        if invoice.paid > 0:
            raise Conflict(f"{rupees(invoice.paid)} has been paid on this bill. Refund it first, then cancel.")
        done = [i.test_name for i in invoice.items if i.status in ("reported", "delivered")]
        if done:
            raise Conflict(f"{', '.join(done)} has already been reported or delivered, so the bill can't be cancelled.")
        invoice.status = "cancelled"
        invoice.cancel_reason = reason.strip()
        for item in invoice.items:
            if item.status != CANCELLED:
                item.status = CANCELLED
                item.status_changed_at = utcnow()
        self.audit.record(self.tenant_id, self.current.id, "bill.cancelled", "invoice", invoice.id, {"reason": reason, "total": str(invoice.total)})
        return invoice

    # ---------- money ----------
    def pay(self, invoice_id: uuid.UUID, data: PaymentIn) -> Invoice:
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        if invoice.due <= 0:
            raise Conflict("Nothing is due on this bill.")
        if data.amount > invoice.due:
            raise Invalid(f"Only {rupees(invoice.due)} is due on this bill.", "amount")
        p = self._take(invoice, "payment", data.mode, data.amount, data.reference, data.note)
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "payment.received", "invoice", invoice.id, {
            "amount": str(p.amount), "mode": p.mode, "due_after": str(invoice.due)})
        return invoice

    def refund(self, invoice_id: uuid.UUID, data: RefundIn) -> Invoice:
        invoice = self.get(invoice_id, lock=True)
        if data.amount > invoice.paid:
            raise Invalid(f"Only {rupees(invoice.paid)} has been paid on this bill.", "amount")
        p = self._take(invoice, "refund", data.mode, data.amount, note=data.note)
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "payment.refunded", "invoice", invoice.id, {
            "amount": str(p.amount), "mode": p.mode, "reason": data.note})
        return invoice

    # ---------- worklist ----------
    def set_item_status(self, item_id: uuid.UUID, status: str) -> InvoiceItem:
        item = self.db.scalar(select(InvoiceItem).where(InvoiceItem.tenant_id == self.tenant_id, InvoiceItem.id == item_id))
        if item is None:
            raise NotFound("We couldn't find that test.")
        invoice = self.get(item.invoice_id, lock=True)
        self._not_cancelled(invoice)
        if item.status == status:
            return item
        if status not in ITEM_FLOW.get(item.status, set()):
            raise Conflict(f"{item.test_name} is {item.status}; it can't be marked {status}.")
        if status == "scanned" and not item.is_imaging:
            raise Invalid(f"{item.test_name} isn't a scan.", "status")
        old = item.status
        item.status = status
        item.status_changed_at = utcnow()
        self.audit.record(self.tenant_id, self.current.id, f"test.{status}", "invoice_item", item.id, {
            "invoice_no": invoice.invoice_no, "test": item.test_name, "from": old, "due": str(invoice.due)})
        return item

    def worklist(self, department_id: uuid.UUID | None, statuses: list[str], date_from: date | None, date_to: date | None,
                 search: str, page: int, size: int):
        q = (select(InvoiceItem, Invoice).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
             .where(InvoiceItem.tenant_id == self.tenant_id, InvoiceItem.status != CANCELLED, Invoice.status != "cancelled"))
        if department_id:
            q = q.where(InvoiceItem.department_id == department_id)
        if statuses:
            q = q.where(InvoiceItem.status.in_(statuses))
        if date_from:
            q = q.where(Invoice.bill_date >= date_from)
        if date_to:
            q = q.where(Invoice.bill_date <= date_to)
        s = search.strip()
        if s:
            q = q.where(or_(func.lower(Invoice.patient_name).like(contains(s), escape="\\"), func.lower(Invoice.invoice_no) == s.lower(),
                            InvoiceItem.accession_no == s.upper()))
        total = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = self.db.execute(q.order_by(Invoice.bill_date.desc(), Invoice.created_at.desc(), InvoiceItem.position)
                               .offset((page - 1) * size).limit(size)).all()
        return rows, total

    # ---------- the day at a glance ----------
    def day_summary(self, day: date) -> dict:
        t = self.tenant_id
        bills = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0), func.coalesce(func.sum(Invoice.discount_amount), 0))
                                .where(Invoice.tenant_id == t, Invoice.bill_date == day, Invoice.status != "cancelled")).one()
        signed = case((Payment.kind == "payment", Payment.amount), else_=-Payment.amount)
        by_mode = dict(self.db.execute(select(Payment.mode, func.sum(signed)).where(Payment.tenant_id == t, Payment.received_on == day)
                                       .group_by(Payment.mode)).all())
        refunds = self.db.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                                 .where(Payment.tenant_id == t, Payment.received_on == day, Payment.kind == "refund")) or 0
        dues_collected = self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).join(Invoice, Invoice.id == Payment.invoice_id)
            .where(Payment.tenant_id == t, Payment.received_on == day, Payment.kind == "payment", Invoice.bill_date < day)) or 0
        outstanding = self.db.scalar(select(func.coalesce(func.sum(Invoice.due), 0))
                                     .where(Invoice.tenant_id == t, Invoice.due > 0, Invoice.status != "cancelled")) or 0
        statuses = dict(self.db.execute(
            select(InvoiceItem.status, func.count()).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(InvoiceItem.tenant_id == t, Invoice.bill_date == day, and_(Invoice.status != "cancelled", InvoiceItem.status != CANCELLED))
            .group_by(InvoiceItem.status)).all())
        collected = {mode: q2(v) for mode, v in by_mode.items()}
        return {
            "day": day, "bills": bills[0], "billed": q2(bills[1]), "discounts": q2(bills[2]), "collected": collected,
            "collected_total": q2(sum(collected.values(), ZERO)), "dues_collected": q2(dues_collected), "refunds": q2(refunds),
            "outstanding_dues": q2(outstanding), "items_by_status": statuses,
        }


def default_worklist_window() -> tuple[date, date]:
    today = local_today()
    return today - timedelta(days=6), today



class OverviewService(BillingService):
    """The owner's dashboard: today against yesterday, the month, a 30-day trend and what needs chasing."""

    def overview(self, today: date) -> dict:
        t = self.tenant_id
        live = and_(Invoice.tenant_id == t, Invoice.status != "cancelled")
        yesterday = today - timedelta(days=1)
        first = today.replace(day=1)
        start = today - timedelta(days=29)

        y = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0)).where(live, Invoice.bill_date == yesterday)).one()
        m = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0), func.coalesce(func.sum(Invoice.discount_amount), 0))
                            .where(live, Invoice.bill_date >= first, Invoice.bill_date <= today)).one()
        signed = case((Payment.kind == "payment", Payment.amount), else_=-Payment.amount)
        month_collected = self.db.scalar(select(func.coalesce(func.sum(signed), 0))
                                         .where(Payment.tenant_id == t, Payment.received_on >= first, Payment.received_on <= today)) or 0
        dues_count = self.db.scalar(select(func.count()).where(live, Invoice.due > 0)) or 0

        billed_by_day = dict(self.db.execute(select(Invoice.bill_date, func.sum(Invoice.total))
                                             .where(live, Invoice.bill_date >= start, Invoice.bill_date <= today).group_by(Invoice.bill_date)).all())
        paid_by_day = dict(self.db.execute(select(Payment.received_on, func.sum(signed))
                                           .where(Payment.tenant_id == t, Payment.received_on >= start, Payment.received_on <= today)
                                           .group_by(Payment.received_on)).all())
        trend = [{"day": start + timedelta(days=i), "billed": q2(billed_by_day.get(start + timedelta(days=i), 0)),
                  "collected": q2(paid_by_day.get(start + timedelta(days=i), 0))} for i in range(30)]

        departments = [{"name": name or "Other", "bills": bills, "amount": q2(amount)} for name, bills, amount in self.db.execute(
            select(InvoiceItem.department_name, func.count(func.distinct(InvoiceItem.invoice_id)), func.sum(InvoiceItem.amount))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(live, InvoiceItem.status != CANCELLED, Invoice.bill_date >= first, Invoice.bill_date <= today)
            .group_by(InvoiceItem.department_name).order_by(func.sum(InvoiceItem.amount).desc())).all()]
        doctors = [{"name": name, "bills": bills, "amount": q2(amount)} for name, bills, amount in self.db.execute(
            select(Invoice.referring_doctor_name, func.count(), func.sum(Invoice.total))
            .where(live, Invoice.referring_doctor_id.is_not(None), Invoice.bill_date >= first, Invoice.bill_date <= today)
            .group_by(Invoice.referring_doctor_name).order_by(func.count().desc(), func.sum(Invoice.total).desc()).limit(8)).all()]
        pending = dict(self.db.execute(
            select(InvoiceItem.status, func.count()).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(live, InvoiceItem.status.in_(("billed", "scanned")), Invoice.bill_date >= today - timedelta(days=6))
            .group_by(InvoiceItem.status)).all())
        oldest_dues = list(self.db.scalars(select(Invoice).where(live, Invoice.due > 0).order_by(Invoice.bill_date, Invoice.created_at).limit(6)))
        recent = list(self.db.scalars(select(Invoice).where(Invoice.tenant_id == t).order_by(Invoice.created_at.desc()).limit(8)))
        return {
            "today": self.day_summary(today), "yesterday_bills": y[0], "yesterday_billed": q2(y[1]),
            "month_bills": m[0], "month_billed": q2(m[1]), "month_discounts": q2(m[2]), "month_collected": q2(month_collected),
            "dues_count": dues_count, "trend": trend, "departments": departments, "doctors": doctors,
            "pending_tests": {"billed": pending.get("billed", 0), "scanned": pending.get("scanned", 0)},
            "oldest_dues": oldest_dues, "recent_bills": recent,
        }
