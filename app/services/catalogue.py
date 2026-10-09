"""The centre's catalogue: departments, test types, tests with prices, and referring doctors.
Nothing here is ever deleted (bills point at it); things are switched off instead."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Invalid, NotFound
from app.core.money import q2
from app.core.security import CurrentUser
from app.models import Department, LabTest, ReferringDoctor, TestType
from app.repositories.common import contains
from app.schemas_billing import DepartmentIn, DoctorIn, LabTestIn, TestTypeIn
from app.services.audit import AuditService


def _diff(row, data: dict) -> dict:
    changes = {}
    for field, value in data.items():
        old = getattr(row, field)
        if old != value:
            changes[field] = [str(old) if old is not None else None, str(value) if value is not None else None]
            setattr(row, field, value)
    return changes


class CatalogueService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    def _save(self, row, action: str, entity: str, details: dict, duplicate: str):
        try:
            with self.db.begin_nested():
                self.db.flush()
        except IntegrityError as exc:
            raise Conflict(duplicate, "name") from exc
        if details:
            self.audit.record(self.tenant_id, self.current.id, action, entity, row.id, details)
        return row

    def _get(self, model, row_id: uuid.UUID, what: str):
        row = self.db.scalar(select(model).where(model.tenant_id == self.tenant_id, model.id == row_id))
        if row is None:
            raise NotFound(f"We couldn't find that {what}.")
        return row

    # ---------- departments and test types ----------
    def departments(self) -> list[Department]:
        return list(self.db.scalars(select(Department).where(Department.tenant_id == self.tenant_id).order_by(Department.name)))

    def save_department(self, data: DepartmentIn, dept_id: uuid.UUID | None = None) -> Department:
        if dept_id is None:
            row = Department(tenant_id=self.tenant_id, **data.model_dump())
            self.db.add(row)
            changes = data.model_dump()
        else:
            row = self._get(Department, dept_id, "department")
            changes = _diff(row, data.model_dump())
        return self._save(row, "catalogue.department_saved", "department", changes, "There's already a department with that name.")

    def test_types(self) -> list[TestType]:
        return list(self.db.scalars(select(TestType).where(TestType.tenant_id == self.tenant_id).order_by(TestType.name)))

    def save_test_type(self, data: TestTypeIn, type_id: uuid.UUID | None = None) -> TestType:
        if type_id is None:
            row = TestType(tenant_id=self.tenant_id, **data.model_dump())
            self.db.add(row)
            changes = data.model_dump()
        else:
            row = self._get(TestType, type_id, "test type")
            changes = _diff(row, data.model_dump())
        return self._save(row, "catalogue.test_type_saved", "test_type", changes, "There's already a test type with that name.")

    # ---------- tests ----------
    def tests(self, search: str, department_id: uuid.UUID | None, active: bool | None, page: int, size: int):
        q = select(LabTest).where(LabTest.tenant_id == self.tenant_id)
        if search:
            like = contains(search)
            q = q.where(or_(func.lower(LabTest.name).like(like, escape="\\"), func.lower(LabTest.code) == search.strip().lower()))
        if department_id:
            q = q.where(LabTest.department_id == department_id)
        if active is not None:
            q = q.where(LabTest.is_active.is_(active))
        total = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        # Names that start with what was typed come first, so "CT" finds "CT Brain" before "PET-CT".
        starts = func.lower(LabTest.name).like(search.strip().lower() + "%") if search else None
        order = [starts.desc()] if starts is not None else []
        rows = self.db.scalars(q.order_by(*order, LabTest.name).offset((page - 1) * size).limit(size)).unique().all()
        return list(rows), total

    def save_test(self, data: LabTestIn, test_id: uuid.UUID | None = None) -> LabTest:
        self._get(Department, data.department_id, "department")
        if data.test_type_id:
            self._get(TestType, data.test_type_id, "test type")
        values = {**data.model_dump(), "price": q2(data.price), "code": data.code.strip().upper()}
        if test_id is None:
            row = LabTest(tenant_id=self.tenant_id, **values)
            self.db.add(row)
            changes = {k: str(v) for k, v in values.items()}
        else:
            row = self._get(LabTest, test_id, "test")
            changes = _diff(row, values)
        self._save(row, "catalogue.test_saved", "test", changes, "There's already a test with that name.")
        self.db.refresh(row)
        return row

    # ---------- referring doctors ----------
    def doctors(self, search: str, active: bool | None, page: int, size: int):
        q = select(ReferringDoctor).where(ReferringDoctor.tenant_id == self.tenant_id)
        if search:
            q = q.where(func.lower(ReferringDoctor.name).like(contains(search), escape="\\"))
        if active is not None:
            q = q.where(ReferringDoctor.is_active.is_(active))
        total = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = self.db.scalars(q.order_by(ReferringDoctor.name).offset((page - 1) * size).limit(size)).all()
        return list(rows), total

    def save_doctor(self, data: DoctorIn, doctor_id: uuid.UUID | None = None) -> ReferringDoctor:
        if doctor_id is None:
            row = ReferringDoctor(tenant_id=self.tenant_id, **data.model_dump())
            self.db.add(row)
            changes = data.model_dump()
        else:
            row = self._get(ReferringDoctor, doctor_id, "doctor")
            changes = _diff(row, data.model_dump())
        return self._save(row, "catalogue.doctor_saved", "doctor", changes, "There's already a doctor with that name.")

    def doctor_by_name_or_new(self, name: str) -> ReferringDoctor | None:
        """For billing: a doctor typed by name. "Self" or nothing means no referring doctor."""
        name = " ".join(name.split())
        if not name or name.lower() in {"self", "none", "-"}:
            return None
        if len(name) < 2:
            raise Invalid("Enter the doctor's full name.", "referring_doctor_name")
        row = self.db.scalar(select(ReferringDoctor).where(ReferringDoctor.tenant_id == self.tenant_id,
                                                           func.lower(ReferringDoctor.name) == name.lower()))
        if row is None:
            row = ReferringDoctor(tenant_id=self.tenant_id, name=name)
            self.db.add(row)
            self.db.flush()
            self.audit.record(self.tenant_id, self.current.id, "catalogue.doctor_saved", "doctor", row.id, {"name": name, "from": "billing"})
        return row
