"""What the integration API (/api/v1) sends. Written out field by field, never reused from the app's own shapes,
so nothing financial can ride along: these classes physically have no prices, amounts, discounts, totals,
payments or dues (tests/test_api_keys.py walks every one of them to make sure)."""

import uuid
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ListOut(BaseModel, Generic[T]):
    data: list[T]
    next_cursor: str | None = Field(None, description="Pass as ?cursor= for the next page; null on the last page.")


class ItemOut(BaseModel, Generic[T]):
    data: T


# ---------- references used inside other records ----------

class PatientRef(BaseModel):
    id: uuid.UUID
    patient_no: str
    name: str
    age: str = Field(description="Age as recorded on the order, e.g. \"61\" or \"6 months\".")
    gender: str


class NamedRef(BaseModel):
    id: uuid.UUID | None
    name: str


class Signer(BaseModel):
    name: str
    degree: str
    registration_no: str


# ---------- records ----------

class PatientV1(BaseModel):
    id: uuid.UUID
    patient_no: str
    name: str
    guardian_name: str
    age_years: int | None
    date_of_birth: date | None
    gender: str
    mobile: str
    email: str
    address: str
    created_at: datetime
    updated_at: datetime


class CatalogueTestV1(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    department: NamedRef
    modality: str = Field(description="The kind of test, e.g. X-ray, CT scan, ECG, Blood.")
    is_imaging: bool
    is_active: bool
    updated_at: datetime


class OrderV1(BaseModel):
    """One test ordered for a patient, and how far it has got."""
    id: uuid.UUID
    bill_id: uuid.UUID
    bill_no: str
    ordered_on: date
    patient: PatientRef
    test: NamedRef
    department: NamedRef | None
    is_imaging: bool
    accession_no: str
    status: Literal["billed", "scanned", "reported", "delivered", "cancelled"]
    status_changed_at: datetime | None
    referring_doctor: NamedRef | None
    report_id: uuid.UUID | None = Field(description="The signed report for this test, if there is one.")
    created_at: datetime
    updated_at: datetime


class ReportV1(BaseModel):
    """A signed (or amended after signing) test report. Findings and impression are HTML."""
    id: uuid.UUID
    order_id: uuid.UUID
    patient: PatientRef
    test_name: str
    department_name: str
    accession_no: str
    status: Literal["signed", "amended"]
    title: str
    technique: str
    modality: str
    findings_html: str
    impression_html: str
    signer: Signer
    signed_at: datetime | None
    version: int
    amended: bool
    amend_reason: str
    pdf_url: str
    created_at: datetime
    updated_at: datetime


class StudyV1(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    study_instance_uid: str
    modality: str
    description: str
    series_count: int
    instance_count: int
    created_at: datetime
    updated_at: datetime


class DoctorV1(BaseModel):
    id: uuid.UUID
    name: str
    qualification: str
    is_active: bool
    created_at: datetime


class WhoAmIV1(BaseModel):
    centre: str
    key_name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
