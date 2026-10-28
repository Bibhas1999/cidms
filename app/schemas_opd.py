"""Request and response shapes for the OPD: its doctors and the day's queue of visits."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas import Out
from app.schemas_billing import PatientIn, PaymentIn, _referrer, _strip

VisitStatus = Literal["waiting", "with_doctor", "done", "cancelled"]


class OpdDoctorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    qualification: str = Field(default="", max_length=200)
    fee: Decimal = Field(default=Decimal("0"), ge=0, le=100_000, decimal_places=2)
    is_active: bool = True
    _n = field_validator("name")(_referrer)
    _q = field_validator("qualification")(_strip)


class OpdDoctorOut(Out):
    id: uuid.UUID
    name: str
    qualification: str
    fee: Decimal
    is_active: bool


class OpdVisitIn(BaseModel):
    patient_id: uuid.UUID | None = None
    patient: PatientIn | None = None       # a new patient, registered with the visit
    doctor_id: uuid.UUID
    fee: Decimal = Field(ge=0, le=100_000, decimal_places=2)
    payment: PaymentIn | None = None       # what's paid now; the rest stays due on the fee's bill

    @model_validator(mode="after")
    def _patient(self) -> "OpdVisitIn":
        if (self.patient_id is None) == (self.patient is None):
            raise ValueError("Choose a patient or add a new one.")
        return self


class OpdStatusIn(BaseModel):
    status: VisitStatus
    reason: str = Field(default="", max_length=300)  # needed to cancel


class OpdDoctorRef(Out):
    id: uuid.UUID
    name: str


class OpdPatientRef(Out):
    id: uuid.UUID
    patient_no: str
    name: str
    age_years: int | None
    gender: str
    mobile: str


class OpdVisitOut(BaseModel):
    id: uuid.UUID
    token_no: int
    visit_date: date
    status: VisitStatus
    fee: Decimal
    paid: Decimal
    due: Decimal
    cancel_reason: str
    created_at: datetime
    called_at: datetime | None
    done_at: datetime | None
    created_by_name: str
    doctor: OpdDoctorRef
    patient: OpdPatientRef
    invoice_id: uuid.UUID | None
    invoice_no: str
