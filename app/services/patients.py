"""Patients: one record per person per centre, found by name, mobile or patient number."""

import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Invalid, NotFound
from app.core.money import local_today
from app.core.security import CurrentUser
from app.models import Invoice, Patient
from app.repositories.common import contains
from app.repositories.counters import next_number
from app.schemas_billing import PatientIn
from app.services.audit import AuditService


def age_text(p: Patient, on: date | None = None) -> str:
    """"45 Y", or "8 M" for babies, from the date of birth when there is one."""
    on = on or local_today()
    if p.date_of_birth:
        months = (on.year - p.date_of_birth.year) * 12 + on.month - p.date_of_birth.month - (on.day < p.date_of_birth.day)
        return f"{months // 12} Y" if months >= 24 else f"{max(months, 0)} M"
    return f"{p.age_years} Y" if p.age_years is not None else ""


class PatientService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id

    def get(self, patient_id: uuid.UUID) -> Patient:
        row = self.db.scalar(select(Patient).where(Patient.tenant_id == self.tenant_id, Patient.id == patient_id))
        if row is None:
            raise NotFound("We couldn't find that patient.")
        return row

    def page(self, search: str, page: int, size: int) -> tuple[list[Patient], int]:
        q = select(Patient).where(Patient.tenant_id == self.tenant_id)
        s = search.strip()
        if s:
            digits = "".join(ch for ch in s if ch.isdigit())
            conditions = [func.lower(Patient.name).like(contains(s), escape="\\"), func.lower(Patient.patient_no) == s.lower()]
            if len(digits) >= 4:
                conditions.append(Patient.mobile.like(f"%{digits}%"))
            q = q.where(or_(*conditions))
        total = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = self.db.scalars(q.order_by(Patient.updated_at.desc()).offset((page - 1) * size).limit(size)).all()
        return list(rows), total

    def same_mobile(self, mobile: str, exclude: uuid.UUID | None = None) -> list[Patient]:
        """Others registered with this mobile (often family members), shown before adding a new patient."""
        digits = "".join(ch for ch in mobile if ch.isdigit())
        if len(digits) < 10:
            return []
        q = select(Patient).where(Patient.tenant_id == self.tenant_id, Patient.mobile.like(f"%{digits[-10:]}"))
        if exclude:
            q = q.where(Patient.id != exclude)
        return list(self.db.scalars(q.order_by(Patient.name).limit(20)))

    def create(self, data: PatientIn) -> Patient:
        number = next_number(self.db, self.tenant_id, "patient")
        row = Patient(tenant_id=self.tenant_id, patient_no=f"P{number:06d}", created_by=self.current.id, **data.model_dump())
        self.db.add(row)
        self.db.flush()
        AuditService(self.db).record(self.tenant_id, self.current.id, "patient.created", "patient", row.id, {"patient_no": row.patient_no})
        return row

    def update(self, patient_id: uuid.UUID, data: PatientIn) -> Patient:
        row = self.get(patient_id)
        changes = {}
        for field, value in data.model_dump().items():
            if getattr(row, field) != value:
                changes[field] = [str(getattr(row, field)), str(value)]
                setattr(row, field, value)
        if changes:
            AuditService(self.db).record(self.tenant_id, self.current.id, "patient.updated", "patient", row.id, changes)
            self.db.flush()
        return row

    def delete(self, patient_id: uuid.UUID) -> None:
        row = self.get(patient_id)
        has_bills = self.db.scalar(
            select(func.count()).select_from(Invoice).where(Invoice.tenant_id == self.tenant_id, Invoice.patient_id == patient_id)
        ) or 0
        if has_bills:
            raise Invalid("This patient has bills in the system, so their record can't be deleted.")
        AuditService(self.db).record(self.tenant_id, self.current.id, "patient.deleted", "patient", row.id,
                                    {"patient_no": row.patient_no, "name": row.name})
        self.db.delete(row)
        self.db.flush()

    def bills(self, patient_id: uuid.UUID, limit: int = 100) -> list[Invoice]:
        self.get(patient_id)
        return list(self.db.scalars(select(Invoice).where(Invoice.tenant_id == self.tenant_id, Invoice.patient_id == patient_id)
                                    .order_by(Invoice.bill_date.desc(), Invoice.created_at.desc()).limit(limit)))
