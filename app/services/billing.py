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
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Date, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.money import ZERO, financial_year, local_date, local_today, q2, rupees
from app.core.security import CurrentUser
from app.models import Counter, Invoice, InvoiceItem, LabTest, Patient, Payment, ReferringDoctor, Tenant, TenantSettings, utcnow
from app.repositories.common import contains
from app.repositories.counters import next_number
from app.schemas_billing import BillIn, BillLineIn, BillPartiesIn, BillUpdateIn, PaymentIn, RefundIn
from app.services import events
from app.services.audit import AuditService
from app.services.catalogue import CatalogueService
from app.services.patients import PatientService, age_text

CANCELLED = "cancelled"  # a line taken off the bill; every other status counts towards it
ITEM_FLOW = {  # which progress changes staff may make by hand (signing a test report also marks it "reported")
    "billed": {"scanned", "reported", "delivered"},
    "scanned": {"billed", "reported", "delivered"},
    "reported": {"billed", "scanned", "delivered"},   # back to pending only while no signed report exists
    "delivered": {"billed", "scanned", "reported"},
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


@dataclass
class BillFilters:
    """Every way the bills list can be narrowed. Empty values mean "any"."""
    search: str = ""
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None
    payment: str = ""                    # due | paid | part | unpaid
    mode: str = ""                       # cash | upi | card | bank | other: paid at least partly this way
    doctor_id: uuid.UUID | None = None
    self_referred: bool = False
    patient_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    test_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    discount: str = ""                   # yes | no
    report: str = ""                     # pending (a test not ready yet) | ready (one to hand over) | delivered (all handed over)
    oldest_first: bool = False


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

    def query(self, f: "BillFilters"):
        """Bills matching the filters (a SELECT, not run): shared by the bills list, the dashboard and exports."""
        q = select(Invoice).where(Invoice.tenant_id == self.tenant_id)
        s = f.search.strip()
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
        if f.date_from:
            q = q.where(Invoice.bill_date >= f.date_from)
        if f.date_to:
            q = q.where(Invoice.bill_date <= f.date_to)
        if f.status:
            q = q.where(Invoice.status == f.status)
        live = Invoice.status != "cancelled"
        if f.payment == "due":          # anything still owed
            q = q.where(Invoice.due > 0, live)
        elif f.payment == "paid":       # nothing owed
            q = q.where(Invoice.due <= 0, live)
        elif f.payment == "part":       # some paid, some owed
            q = q.where(Invoice.due > 0, Invoice.paid > 0, live)
        elif f.payment == "unpaid":     # nothing paid yet
            q = q.where(Invoice.due > 0, Invoice.paid <= 0, live)
        if f.mode:
            q = q.where(select(Payment.id).where(Payment.invoice_id == Invoice.id, Payment.kind == "payment",
                                                 Payment.mode == f.mode).exists())
        if f.doctor_id:
            q = q.where(Invoice.referring_doctor_id == f.doctor_id)
        if f.self_referred:
            q = q.where(Invoice.referring_doctor_id.is_(None))
        if f.patient_id:
            q = q.where(Invoice.patient_id == f.patient_id)
        if f.department_id or f.test_id:
            item = select(InvoiceItem.id).where(InvoiceItem.invoice_id == Invoice.id, InvoiceItem.status != CANCELLED)
            if f.department_id:
                item = item.where(InvoiceItem.department_id == f.department_id)
            if f.test_id:
                item = item.where(InvoiceItem.test_id == f.test_id)
            q = q.where(item.exists())
        if f.created_by:
            q = q.where(Invoice.created_by == f.created_by)
        if f.min_total is not None:
            q = q.where(Invoice.total >= f.min_total)
        if f.max_total is not None:
            q = q.where(Invoice.total <= f.max_total)
        if f.discount == "yes":
            q = q.where(Invoice.discount_amount > 0)
        elif f.discount == "no":
            q = q.where(Invoice.discount_amount == 0)
        if f.report:
            def lines(*where):
                return select(InvoiceItem.id).where(InvoiceItem.invoice_id == Invoice.id, InvoiceItem.status != CANCELLED, *where).exists()
            if f.report == "pending":
                q = q.where(lines(InvoiceItem.status.in_(("billed", "scanned"))))
            elif f.report == "ready":
                q = q.where(lines(InvoiceItem.status == "reported"))
            elif f.report == "delivered":
                q = q.where(lines(), ~lines(InvoiceItem.status != "delivered"))
        order = (Invoice.bill_date, Invoice.created_at) if f.oldest_first else (Invoice.bill_date.desc(), Invoice.created_at.desc())
        return q.order_by(*order)

    def page(self, f: "BillFilters", page: int, size: int):
        q = self.query(f)
        counted = q.order_by(None).where(Invoice.status != "cancelled").subquery()
        totals = self.db.execute(select(func.count(), func.coalesce(func.sum(counted.c.total), 0),
                                        func.coalesce(func.sum(counted.c.paid), 0), func.coalesce(func.sum(counted.c.due), 0))).one()
        total_rows = self.db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        rows = self.db.scalars(q.offset((page - 1) * size).limit(size)).all()
        return list(rows), total_rows, {"billed": q2(totals[1]), "paid": q2(totals[2]), "due": q2(totals[3])}

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
        # Above the limit but allowed (an owner or admin): tell the others once the bill is saved.
        self._over_limit = limit if amount > 0 and subtotal > 0 and amount * 100 > subtotal * limit else None
        invoice.subtotal = subtotal
        invoice.discount_type = discount_type
        invoice.discount_value = q2(discount_value)
        invoice.discount_amount = amount
        invoice.total = subtotal - amount
        self._settle(invoice)

    def _settle(self, invoice: Invoice) -> None:
        """Paid/due, from the payments taken since the bill was last put on hold (earlier ones still happened,
        but stop counting once the bill goes on hold: see hold())."""
        counted = (p for p in invoice.payments if invoice.held_at is None or p.received_at > invoice.held_at)
        paid = sum((p.amount if p.kind == "payment" else -p.amount for p in counted), ZERO)
        invoice.paid = q2(paid)
        invoice.due = invoice.total - invoice.paid

    def _take(self, invoice: Invoice, kind: str, mode: str, amount: Decimal, reference: str = "", note: str = "",
              at: datetime | None = None) -> Payment:
        p = Payment(tenant_id=self.tenant_id, kind=kind, amount=q2(amount), mode=mode, reference=reference.strip(), note=note.strip(),
                    received_at=at or utcnow(), received_on=local_date(at) if at else local_today(), received_by=self.current.id,
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
                           "Please contact CIDMS to change your plan.")

    def _not_cancelled(self, invoice: Invoice) -> None:
        if invoice.status == "cancelled":
            raise Conflict("This bill is cancelled and can't be changed.")

    def next_invoice_no(self) -> str:
        """The number the next bill will most likely get, for the New bill page. Only a preview: the real
        number is taken when the bill is saved, so two desks billing at once each get their own."""
        fy = financial_year(local_today())
        current = self.db.scalar(select(Counter.value).where(Counter.tenant_id == self.tenant_id, Counter.name == f"invoice:{fy}")) or 0
        return f"{self._settings().invoice_prefix}/{fy}/{current + 1:06d}"

    # ---------- creating and changing bills ----------
    def _offline_time(self, data: BillIn) -> datetime | None:
        """When an offline bill was really made: within the last 30 days, and not in the future."""
        if data.offline is None:
            return None
        made = data.offline.made_at
        if made.tzinfo is None:
            raise Invalid("The time the bill was made must include its time zone.", "offline")
        now = utcnow()
        if made > now + timedelta(minutes=10):
            raise Invalid("This offline bill's time is in the future. Check the computer's clock.", "offline")
        if made < now - timedelta(days=30):
            raise Invalid("This offline bill is more than 30 days old, so it can't be added. Make it again as a new bill.", "offline")
        dup = self.db.scalar(select(Invoice.invoice_no).where(Invoice.tenant_id == self.tenant_id, Invoice.offline_no == data.offline.offline_no))
        if dup:
            raise Conflict(f"This offline bill is already saved, as {dup}.", "offline_duplicate")
        return made

    def create(self, data: BillIn) -> Invoice:
        made_offline = self._offline_time(data)
        self._check_bill_limit()
        patients = PatientService(self.db, self.current)
        patient: Patient = patients.get(data.patient_id) if data.patient_id else patients.create(data.patient)
        tests = self._tests(data.lines)
        doctor = self._doctor(data.referring_doctor_id, data.referring_doctor_name)
        settings = self._settings()
        today = local_date(made_offline) if made_offline else local_today()
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
            offline_no=data.offline.offline_no if data.offline else "", made_offline_at=made_offline,
        )
        for position, line in enumerate(data.lines, start=1):
            self._new_line(invoice, position, tests[line.test_id], line.quantity)
        self._price(invoice, data.discount_type, data.discount_value)
        if data.offline and not data.offline.accept_new_total and invoice.total != q2(data.offline.printed_total):
            raise Conflict(f"Prices have changed since this bill was made offline: it was printed for {rupees(data.offline.printed_total)}, "
                           f"and today's prices make it {rupees(invoice.total)}.", "offline_total")
        taking = q2(sum((p.amount for p in data.payments), ZERO))
        if taking > invoice.total:
            raise Invalid(f"The payment ({rupees(taking)}) is more than the bill ({rupees(invoice.total)}).", "payments")
        for p in data.payments:
            self._take(invoice, "payment", p.mode, p.amount, p.reference, p.note, at=made_offline)
        self.db.add(invoice)
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "bill.created", "invoice", invoice.id, {
            "invoice_no": invoice.invoice_no, "patient": patient.patient_no, "total": str(invoice.total), "paid": str(invoice.paid),
            "discount": str(invoice.discount_amount), "status": invoice.status,
            **({"offline_no": invoice.offline_no, "made_offline_at": made_offline.isoformat()} if made_offline else {})})
        if getattr(self, "_over_limit", None):
            events.discount_over_limit(self.db, invoice, self.current, self._over_limit)
        return invoice

    def _fully_paid(self, invoice: Invoice) -> bool:
        return invoice.total > 0 and invoice.due <= 0

    def update(self, invoice_id: uuid.UUID, data: BillUpdateIn) -> Invoice:
        """Change a bill's tests or discount. Only while it's on hold, and never once it's fully paid."""
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        if self._fully_paid(invoice):
            raise Conflict("This bill is fully paid, so it can't be changed.")
        if invoice.status != "on_hold":
            raise Conflict("Put the bill on hold first, then change it.")
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
        if getattr(self, "_over_limit", None):
            events.discount_over_limit(self.db, invoice, self.current, self._over_limit)
        return invoice

    def update_parties(self, invoice_id: uuid.UUID, data: BillPartiesIn) -> Invoice:
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        patient = PatientService(self.db, self.current).get(data.patient_id)
        doctor = None
        if data.referring_doctor_id:
            doctor = self.db.scalar(select(ReferringDoctor).where(ReferringDoctor.tenant_id == self.tenant_id,
                                                                  ReferringDoctor.id == data.referring_doctor_id))
            if doctor is None:
                raise Invalid("Choose a doctor from the list.", "referring_doctor_id")

        before = {"patient_id": str(invoice.patient_id), "referring_doctor_id": str(invoice.referring_doctor_id or "")}
        invoice.patient_id = patient.id
        invoice.patient_name = patient.name
        invoice.patient_age = age_text(patient, invoice.bill_date)
        invoice.patient_gender = patient.gender
        invoice.patient_mobile = patient.mobile
        invoice.patient_address = patient.address
        invoice.guardian_name = patient.guardian_name
        invoice.referring_doctor_id = doctor.id if doctor else None
        invoice.referring_doctor_name = doctor.name if doctor else ""
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "bill.parties_updated", "invoice", invoice.id,
                          {"before": before, "patient_id": str(patient.id),
                           "referring_doctor_id": str(doctor.id if doctor else "")})
        return invoice

    def hold(self, invoice_id: uuid.UUID, reason: str) -> Invoice:
        """Put a bill on hold, including a fully paid one. Treated like a fresh draft from here: what's been
        paid so far stops counting (though it stays on record), so the bill is due again until it's repaid."""
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        if invoice.status != "on_hold":
            invoice.status = "on_hold"
            invoice.held_at = utcnow()
            self._settle(invoice)
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
        events.bill_cancelled(self.db, invoice, self.current, reason)
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
        events.refund_recorded(self.db, invoice, self.current, p.amount, p.mode, data.note)
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
        if status in ("billed", "scanned") and self._has_signed_report(item.id):
            raise Conflict(f"{item.test_name} has a signed report, so it can't go back to pending.")
        old = item.status
        item.status = status
        item.status_changed_at = utcnow()
        self.audit.record(self.tenant_id, self.current.id, f"test.{status}", "invoice_item", item.id, {
            "invoice_no": invoice.invoice_no, "test": item.test_name, "from": old, "due": str(invoice.due)})
        return item

    def _has_signed_report(self, item_id: uuid.UUID) -> bool:
        from app.models import TestReport  # the reports module (on hold in the app) may sign tests off

        return bool(self.db.scalar(select(func.count()).select_from(TestReport)
                                   .where(TestReport.invoice_item_id == item_id, TestReport.status.in_(("signed", "amended")))))

    def set_bill_items_status(self, invoice_id: uuid.UUID, status: str, item_ids: list[uuid.UUID] | None = None) -> list[InvoiceItem]:
        """Mark every (or the given) live test on one bill: e.g. all reports handed over at once. Tests already
        there are left alone; one that can't move (a signed report going back to pending) stops the lot."""
        invoice = self.get(invoice_id, lock=True)
        self._not_cancelled(invoice)
        lines = [i for i in invoice.items if i.status != CANCELLED and (item_ids is None or i.id in item_ids)]
        if item_ids is not None and len(lines) != len(set(item_ids)):
            raise NotFound("Some of those tests aren't on this bill.")
        return [self.set_item_status(i.id, status) for i in lines if i.status != status]

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


    def desk_summary(self, today: date, date_from: date | None = None, date_to: date | None = None) -> dict:
        """Bills, total amount, collected and dues for a period (no start date: since the first bill)."""
        t = self.tenant_id
        live = and_(Invoice.tenant_id == t, Invoice.status != "cancelled")
        to = min(date_to or today, today)
        all_time = date_from is None
        frm = min(date_from or self.db.scalar(select(func.min(Invoice.bill_date)).where(Invoice.tenant_id == t)) or to, to)
        signed = case((Payment.kind == "payment", Payment.amount), else_=-Payment.amount)
        received = (Payment.tenant_id == t, Payment.received_on >= frm, Payment.received_on <= to)
        by_mode = {mode: q2(v) for mode, v in self.db.execute(
            select(Payment.mode, func.sum(signed)).where(*received).group_by(Payment.mode)).all()}
        refunds = self.db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(*received, Payment.kind == "refund")) or 0
        dues_collected = self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).join(Invoice, Invoice.id == Payment.invoice_id)
            .where(*received, Payment.kind == "payment", Invoice.bill_date < frm)) or 0
        in_period = (live, Invoice.bill_date >= frm, Invoice.bill_date <= to)
        bills = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.due), 0), func.count().filter(Invoice.due > 0),
                                       func.coalesce(func.sum(Invoice.total), 0))
                                .where(*in_period)).one()
        outstanding = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.due), 0)).where(live, Invoice.due > 0)).one()
        pending = dict(self.db.execute(
            select(InvoiceItem.status, func.count()).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(*in_period, InvoiceItem.status.in_(("billed", "scanned"))).group_by(InvoiceItem.status)).all())
        return {
            "date_from": frm, "date_to": to, "all_time": all_time, "bills": bills[0], "billed": q2(bills[3]),
            "collected": by_mode, "collected_total": q2(sum(by_mode.values(), ZERO)), "dues_collected": q2(dues_collected),
            "refunds": q2(refunds), "due_on_bills": q2(bills[1]), "due_bills": bills[2],
            "outstanding_dues": q2(outstanding[1]), "dues_count": outstanding[0],
            "pending_tests": {"billed": pending.get("billed", 0), "scanned": pending.get("scanned", 0)},
        }


def default_worklist_window() -> tuple[date, date]:
    today = local_today()
    return today - timedelta(days=6), today



class OverviewService(BillingService):
    """The owner's dashboard for any period: what was billed and collected, against the period before it,
    the trend, departments and doctors, plus what needs doing now (tests waiting, dues to chase)."""

    def overview(self, today: date, date_from: date | None = None, date_to: date | None = None) -> dict:
        t = self.tenant_id
        live = and_(Invoice.tenant_id == t, Invoice.status != "cancelled")
        to = min(date_to or today, today)
        all_time = date_from is None
        if date_from is None:  # the default, "all time": from the first bill
            date_from = self.db.scalar(select(func.min(Invoice.bill_date)).where(Invoice.tenant_id == t)) or to
        frm = min(date_from, to)
        days = (to - frm).days + 1
        prev_to = frm - timedelta(days=1)
        prev_from = prev_to - timedelta(days=days - 1)
        signed = case((Payment.kind == "payment", Payment.amount), else_=-Payment.amount)

        def billed(a: date, b: date):
            return self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.total), 0), func.coalesce(func.sum(Invoice.discount_amount), 0),
                                          func.coalesce(func.sum(Invoice.due), 0), func.count(func.distinct(Invoice.patient_id)))
                                   .where(live, Invoice.bill_date >= a, Invoice.bill_date <= b)).one()

        def collected(a: date, b: date) -> Decimal:
            return self.db.scalar(select(func.coalesce(func.sum(signed), 0))
                                  .where(Payment.tenant_id == t, Payment.received_on >= a, Payment.received_on <= b)) or ZERO

        now, before = billed(frm, to), billed(prev_from, prev_to)
        by_mode = {mode: q2(v) for mode, v in self.db.execute(
            select(Payment.mode, func.sum(signed)).where(Payment.tenant_id == t, Payment.received_on >= frm, Payment.received_on <= to)
            .group_by(Payment.mode)).all()}
        refunds = self.db.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                                 .where(Payment.tenant_id == t, Payment.received_on >= frm, Payment.received_on <= to, Payment.kind == "refund")) or 0
        dues_collected = self.db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).join(Invoice, Invoice.id == Payment.invoice_id)
            .where(Payment.tenant_id == t, Payment.received_on >= frm, Payment.received_on <= to, Payment.kind == "payment",
                   Invoice.bill_date < frm)) or 0
        outstanding = self.db.execute(select(func.count(), func.coalesce(func.sum(Invoice.due), 0)).where(live, Invoice.due > 0)).one()

        # The trend: day by day up to about three months, then month by month. A short period shows the
        # fortnight leading up to its end, so a single day still has something to compare with.
        monthly = days > 92
        t_from = frm if days >= 14 else to - timedelta(days=13)
        if monthly:
            t_from = t_from.replace(day=1)
            bucket_i = func.date_trunc("month", Invoice.bill_date).cast(Date)
            bucket_p = func.date_trunc("month", Payment.received_on).cast(Date)
        else:
            bucket_i, bucket_p = Invoice.bill_date, Payment.received_on
        billed_by = dict(self.db.execute(
            select(bucket_i, func.sum(Invoice.total)).where(live, Invoice.bill_date >= t_from, Invoice.bill_date <= to).group_by(bucket_i)).all())
        paid_by = dict(self.db.execute(
            select(bucket_p, func.sum(signed)).where(Payment.tenant_id == t, Payment.received_on >= t_from, Payment.received_on <= to)
            .group_by(bucket_p)).all())
        if monthly:
            keys, d = [], t_from
            while d <= to:
                keys.append(d)
                d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            keys = [t_from + timedelta(days=i) for i in range((to - t_from).days + 1)]
        trend = [{"day": k, "billed": q2(billed_by.get(k, 0)), "collected": q2(paid_by.get(k, 0))} for k in keys]

        in_period = (Invoice.bill_date >= frm, Invoice.bill_date <= to)
        departments = [{"name": name or "Other", "bills": bills, "amount": q2(amount)} for name, bills, amount in self.db.execute(
            select(InvoiceItem.department_name, func.count(func.distinct(InvoiceItem.invoice_id)), func.sum(InvoiceItem.amount))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(live, InvoiceItem.status != CANCELLED, *in_period)
            .group_by(InvoiceItem.department_name).order_by(func.sum(InvoiceItem.amount).desc())).all()]
        doctors = [{"name": name, "bills": bills, "amount": q2(amount)} for name, bills, amount in self.db.execute(
            select(Invoice.referring_doctor_name, func.count(), func.sum(Invoice.total))
            .where(live, Invoice.referring_doctor_id.is_not(None), *in_period)
            .group_by(Invoice.referring_doctor_name).order_by(func.count().desc(), func.sum(Invoice.total).desc()).limit(8)).all()]
        pending = dict(self.db.execute(
            select(InvoiceItem.status, func.count()).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(live, InvoiceItem.status.in_(("billed", "scanned")), *in_period)
            .group_by(InvoiceItem.status)).all())
        oldest_dues = list(self.db.scalars(select(Invoice).where(live, Invoice.due > 0).order_by(Invoice.bill_date, Invoice.created_at).limit(6)))
        return {
            "date_from": frm, "date_to": to, "days": days, "all_time": all_time,
            "period": {"bills": now[0], "billed": q2(now[1]), "discounts": q2(now[2]), "due_on_bills": q2(now[3]), "patients": now[4],
                       "collected": by_mode, "collected_total": q2(sum(by_mode.values(), ZERO)), "dues_collected": q2(dues_collected),
                       "refunds": q2(refunds)},
            "previous": {"date_from": prev_from, "date_to": prev_to, "bills": before[0], "billed": q2(before[1]),
                         "collected_total": q2(collected(prev_from, prev_to))},
            "dues_count": outstanding[0], "outstanding_dues": q2(outstanding[1]),
            "trend": trend, "trend_unit": "month" if monthly else "day",
            "departments": departments, "doctors": doctors,
            "pending_tests": {"billed": pending.get("billed", 0), "scanned": pending.get("scanned", 0)},
            "oldest_dues": oldest_dues,
        }
