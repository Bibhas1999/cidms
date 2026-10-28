"""The OPD: the centre's own doctors seeing patients, and the day's queue for each of them.

- A visit is one patient for one doctor on one day (India time), with a token number that runs per doctor per
  day from 1, taken under a lock (repositories/counters), so two desks never hand out the same token.
- The consultation fee is a normal bill (one line, not from the catalogue), numbered, paid and refunded like any
  other. A visit with no fee has no bill.
- The queue moves waiting -> with the doctor -> done, one step back at a time if pressed by mistake, and a
  waiting (or called-in) visit can be cancelled with a reason. Cancelling leaves the fee's bill as it is: any
  money is given back from the bill, with the usual refund rules.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Invalid, NotFound
from app.core.money import ZERO, local_today, q2, rupees
from app.core.security import CurrentUser
from app.models import OpdDoctor, OpdVisit, utcnow
from app.repositories.counters import next_number
from app.schemas_opd import OpdDoctorIn, OpdVisitIn, OpdVisitOut
from app.services.audit import AuditService
from app.services.billing import BillingService
from app.services.patients import PatientService

LABELS = {"waiting": "waiting", "with_doctor": "with the doctor", "done": "done", "cancelled": "cancelled"}
FLOW = {  # where a visit may go next: forward, one step back, or cancelled before it's done
    "waiting": {"with_doctor", "cancelled"},
    "with_doctor": {"done", "waiting", "cancelled"},
    "done": {"with_doctor"},
    "cancelled": set(),
}


def visit_out(v: OpdVisit) -> OpdVisitOut:
    bill = v.invoice
    return OpdVisitOut(
        id=v.id, token_no=v.token_no, visit_date=v.visit_date, status=v.status, fee=q2(v.fee),
        paid=q2(bill.paid) if bill else ZERO, due=q2(bill.due) if bill and bill.status != "cancelled" else ZERO,
        cancel_reason=v.cancel_reason, created_at=v.created_at, called_at=v.called_at, done_at=v.done_at,
        created_by_name=v.creator.full_name if v.creator else "",
        doctor={"id": v.doctor.id, "name": v.doctor.name},
        patient={"id": v.patient.id, "patient_no": v.patient.patient_no, "name": v.patient.name, "age_years": v.patient.age_years,
                 "gender": v.patient.gender, "mobile": v.patient.mobile},
        invoice_id=v.invoice_id, invoice_no=bill.invoice_no if bill else "",
    )


class OpdService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    # ---------- doctors ----------
    def doctors(self, include_off: bool = False) -> list[OpdDoctor]:
        q = select(OpdDoctor).where(OpdDoctor.tenant_id == self.tenant_id)
        if not include_off:
            q = q.where(OpdDoctor.is_active.is_(True))
        return list(self.db.scalars(q.order_by(func.lower(OpdDoctor.name))))

    def _doctor(self, doctor_id: uuid.UUID, lock: bool = False) -> OpdDoctor:
        q = select(OpdDoctor).where(OpdDoctor.tenant_id == self.tenant_id, OpdDoctor.id == doctor_id)
        row = self.db.scalar(q.with_for_update() if lock else q)
        if row is None:
            raise NotFound("We couldn't find that doctor.")
        return row

    def save_doctor(self, data: OpdDoctorIn, doctor_id: uuid.UUID | None = None) -> OpdDoctor:
        same = select(OpdDoctor.id).where(OpdDoctor.tenant_id == self.tenant_id, func.lower(OpdDoctor.name) == data.name.lower())
        if doctor_id:
            same = same.where(OpdDoctor.id != doctor_id)
        if self.db.scalar(same):
            raise Conflict(f"There's already a doctor called {data.name} in the OPD.", "name")
        values = {"name": data.name, "qualification": data.qualification, "fee": q2(data.fee), "is_active": data.is_active}
        if doctor_id is None:
            row = OpdDoctor(tenant_id=self.tenant_id, **values)
            self.db.add(row)
            self.db.flush()
            self.audit.record(self.tenant_id, self.current.id, "opd.doctor_created", "opd_doctor", row.id,
                              {**values, "fee": str(values["fee"])})
            return row
        row = self._doctor(doctor_id, lock=True)
        changes = {k: [str(getattr(row, k)), str(v)] for k, v in values.items() if getattr(row, k) != v}
        for k, v in values.items():
            setattr(row, k, v)
        if changes:
            self.db.flush()
            self.audit.record(self.tenant_id, self.current.id, "opd.doctor_updated", "opd_doctor", row.id, changes)
        return row

    # ---------- the queue ----------
    def visits(self, day: date, doctor_id: uuid.UUID | None = None, status: str | None = None) -> list[OpdVisit]:
        q = (select(OpdVisit).join(OpdDoctor, OpdDoctor.id == OpdVisit.doctor_id)
             .where(OpdVisit.tenant_id == self.tenant_id, OpdVisit.visit_date == day))
        if doctor_id:
            q = q.where(OpdVisit.doctor_id == doctor_id)
        if status:
            q = q.where(OpdVisit.status == status)
        return list(self.db.scalars(q.order_by(func.lower(OpdDoctor.name), OpdVisit.token_no)).unique())

    def get(self, visit_id: uuid.UUID, lock: bool = False) -> OpdVisit:
        q = select(OpdVisit).where(OpdVisit.tenant_id == self.tenant_id, OpdVisit.id == visit_id)
        if lock:
            q = q.with_for_update(of=OpdVisit).execution_options(populate_existing=True)
        row = self.db.scalar(q)
        if row is None:
            raise NotFound("We couldn't find that visit.")
        return row

    def create_visit(self, data: OpdVisitIn) -> OpdVisit:
        doctor = self._doctor(data.doctor_id)
        if not doctor.is_active:
            raise Invalid(f"{doctor.name} is switched off in the OPD. Choose another doctor.", "doctor_id")
        fee = q2(data.fee)
        if data.payment is not None and data.payment.amount > fee:
            raise Invalid(f"Paid now can't be more than the fee, {rupees(fee)}.", "payment.amount")
        patients = PatientService(self.db, self.current)
        patient = patients.get(data.patient_id) if data.patient_id else patients.create(data.patient)
        day = local_today()
        token = next_number(self.db, self.tenant_id, f"opd:{doctor.id.hex[:12]}:{day:%y%m%d}")
        invoice = None
        if fee > 0:
            invoice = BillingService(self.db, self.current).create_consultation(patient, doctor.name, fee, data.payment)
        visit = OpdVisit(tenant_id=self.tenant_id, visit_date=day, token_no=token, doctor_id=doctor.id, patient_id=patient.id,
                         invoice_id=invoice.id if invoice else None, fee=fee, status="waiting", created_by=self.current.id,
                         created_at=utcnow())
        self.db.add(visit)
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "opd.visit_created", "opd_visit", visit.id, {
            "token": token, "doctor": doctor.name, "patient": patient.patient_no, "fee": str(fee),
            "paid": str(invoice.paid) if invoice else "0.00", "invoice_no": invoice.invoice_no if invoice else ""})
        return self.get(visit.id)

    def set_status(self, visit_id: uuid.UUID, status: str, reason: str = "") -> OpdVisit:
        visit = self.get(visit_id, lock=True)
        if visit.status == status:
            return visit
        if status not in FLOW[visit.status]:
            raise Conflict(f"Token {visit.token_no} is {LABELS[visit.status]}; it can't be marked {LABELS[status]}.")
        reason = " ".join(reason.split())
        if status == "cancelled" and len(reason) < 3:
            raise Invalid("Say why the visit is cancelled (at least 3 characters).", "reason")
        old, now = visit.status, utcnow()
        if status == "with_doctor" and old == "waiting":
            visit.called_at = now
        elif status == "waiting":
            visit.called_at = None
        if status == "done":
            visit.done_at = now
        elif old == "done":
            visit.done_at = None
        if status == "cancelled":
            visit.cancel_reason = reason
        visit.status = status
        if status == "done" or old == "done":
            self._consultation_line(visit, delivered=status == "done")
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, f"opd.visit_{status}", "opd_visit", visit.id, {
            "token": visit.token_no, "doctor": visit.doctor.name, "patient": visit.patient.patient_no, "from": old,
            **({"reason": reason} if status == "cancelled" else {})})
        return visit

    def _consultation_line(self, visit: OpdVisit, delivered: bool) -> None:
        """The fee's line follows the visit: delivered once the doctor has seen them, back to billed on undo."""
        bill = visit.invoice
        if bill is None or bill.status == "cancelled":
            return
        for item in bill.items:
            if delivered and item.status == "billed":
                item.status, item.status_changed_at = "delivered", utcnow()
            elif not delivered and item.status == "delivered":
                item.status, item.status_changed_at = "billed", utcnow()
