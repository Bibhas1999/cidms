"""Request and response shapes for billing: catalogue, patients, bills, payments, worklist and the day's summary."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas import Out, Page, _mobile

PaymentMode = Literal["cash", "upi", "card", "bank", "other"]
Gender = Literal["male", "female", "other"]
Money = Decimal


def _strip(v: str) -> str:
    return " ".join(v.split())


# ---------- catalogue ----------

class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    is_active: bool = True
    _n = field_validator("name")(_strip)


class DepartmentOut(Out):
    id: uuid.UUID
    name: str
    is_active: bool


class TestTypeIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    is_imaging: bool = False
    is_active: bool = True
    _n = field_validator("name")(_strip)


class TestTypeOut(Out):
    id: uuid.UUID
    name: str
    is_imaging: bool
    is_active: bool


class LabTestIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(default="", max_length=20)
    department_id: uuid.UUID
    test_type_id: uuid.UUID | None = None
    price: Money = Field(ge=0, le=10_000_000, decimal_places=2)
    is_active: bool = True
    _n = field_validator("name")(_strip)


class LabTestOut(Out):
    id: uuid.UUID
    code: str
    name: str
    price: Money
    is_active: bool
    department: DepartmentOut
    test_type: TestTypeOut | None


class DoctorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    qualification: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=20)
    is_active: bool = True
    _n = field_validator("name")(_strip)
    _m = field_validator("phone")(_mobile)


class DoctorOut(Out):
    id: uuid.UUID
    name: str
    qualification: str
    phone: str
    is_active: bool


# ---------- patients ----------

class PatientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    guardian_name: str = Field(default="", max_length=200)
    age_years: int | None = Field(default=None, ge=0, le=130)
    date_of_birth: date | None = None
    gender: Gender
    mobile: str = Field(default="", max_length=20)
    email: EmailStr | Literal[""] = ""
    address: str = Field(default="", max_length=1000)
    _n = field_validator("name", "guardian_name")(_strip)
    _m = field_validator("mobile")(_mobile)

    @model_validator(mode="after")
    def _age_or_dob(self) -> "PatientIn":
        if self.age_years is None and self.date_of_birth is None:
            raise ValueError("Enter the patient's age or date of birth.")
        if self.date_of_birth and self.date_of_birth > date.today():
            raise ValueError("The date of birth can't be in the future.")
        return self


class PatientOut(Out):
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


# ---------- bills ----------

class BillLineIn(BaseModel):
    id: uuid.UUID | None = None          # an existing line on the bill (when editing)
    test_id: uuid.UUID | None = None     # a new line
    quantity: int = Field(default=1, ge=1, le=20)

    @model_validator(mode="after")
    def _one(self) -> "BillLineIn":
        if (self.id is None) == (self.test_id is None):
            raise ValueError("Each line is either an existing line or a test.")
        return self


class PaymentIn(BaseModel):
    mode: PaymentMode
    amount: Money = Field(gt=0, le=10_000_000, decimal_places=2)
    reference: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=300)


class RefundIn(BaseModel):
    mode: PaymentMode
    amount: Money = Field(gt=0, le=10_000_000, decimal_places=2)
    note: str = Field(min_length=3, max_length=300, description="Why the money is being given back")


class Discount(BaseModel):
    discount_type: Literal["none", "percent", "amount"] = "none"
    discount_value: Money = Field(default=Decimal("0"), ge=0, le=10_000_000, decimal_places=2)

    @model_validator(mode="after")
    def _discount(self):
        if self.discount_type == "percent" and self.discount_value > 100:
            raise ValueError("A percentage discount can't be more than 100%.")
        if self.discount_type == "none":
            self.discount_value = Decimal("0")
        return self


class OfflineIn(BaseModel):
    """A bill made offline on the desk computer, arriving now that the connection is back."""
    made_at: datetime                                    # when it was really made (and paid)
    offline_no: str = Field(min_length=3, max_length=40, pattern=r"^OFF-[A-Z0-9-]+$")
    printed_total: Money = Field(ge=0, le=100_000_000)   # what the printed bill said
    accept_new_total: bool = False                       # prices changed since: save at today's prices anyway


class BillIn(Discount):
    patient_id: uuid.UUID | None = None
    patient: PatientIn | None = None
    referring_doctor_id: uuid.UUID | None = None
    referring_doctor_name: str = Field(default="", max_length=200)  # a doctor not in the list yet
    lines: list[BillLineIn] = Field(min_length=1, max_length=50)
    payments: list[PaymentIn] = Field(default_factory=list, max_length=5)
    notes: str = Field(default="", max_length=1000)
    hold: bool = False
    offline: OfflineIn | None = None

    @model_validator(mode="after")
    def _patient(self) -> "BillIn":
        if (self.patient_id is None) == (self.patient is None):
            raise ValueError("Choose a patient or add a new one.")
        if any(line.id for line in self.lines):
            raise ValueError("A new bill can only have tests.")
        return self


class BillUpdateIn(Discount):
    referring_doctor_id: uuid.UUID | None = None
    referring_doctor_name: str = Field(default="", max_length=200)
    lines: list[BillLineIn] = Field(min_length=1, max_length=50)
    notes: str = Field(default="", max_length=1000)
    reason: str = Field(min_length=3, max_length=300, description="Why the bill is being changed")


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class ItemStatusIn(BaseModel):
    status: Literal["billed", "scanned", "reported", "delivered"]


class BillItemsStatusIn(BaseModel):
    """Several tests on one bill at once; no item_ids means every test on the bill (not taken off)."""
    status: Literal["billed", "reported", "delivered"]
    item_ids: list[uuid.UUID] | None = Field(None, max_length=200)


class BillLineOut(Out):
    id: uuid.UUID
    position: int
    test_id: uuid.UUID | None
    test_name: str
    department_name: str
    is_imaging: bool
    unit_price: Money
    quantity: int
    amount: Money
    status: str
    accession_no: str
    status_changed_at: datetime | None


class PaymentOut(Out):
    id: uuid.UUID
    kind: str
    amount: Money
    mode: str
    reference: str
    note: str
    received_at: datetime
    received_by_name: str


class BillSummaryOut(Out):
    id: uuid.UUID
    invoice_no: str
    legacy_no: int | None
    bill_date: date
    patient_id: uuid.UUID
    patient_name: str
    patient_mobile: str
    referring_doctor_name: str
    status: str
    total: Money
    paid: Money
    due: Money
    created_by_name: str
    created_at: datetime
    offline_no: str = ""
    made_offline_at: datetime | None = None


class BillPage(Page[BillSummaryOut]):
    # billed, paid and due across every matching bill (cancelled ones left out), not just this page.
    # billed is null for people who may not see turnover (no analytics.view).
    sums: dict[str, Money | None]


class BillOut(BillSummaryOut):
    patient_age: str
    patient_gender: str
    patient_address: str
    guardian_name: str
    referring_doctor_id: uuid.UUID | None
    subtotal: Money
    discount_type: str
    discount_value: Money
    discount_amount: Money
    notes: str
    cancel_reason: str
    updated_at: datetime
    items: list[BillLineOut]
    payments: list[PaymentOut]


class WorklistRowOut(BaseModel):
    item_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_no: str
    bill_date: date
    patient_name: str
    patient_age: str
    patient_gender: str
    test_name: str
    department_name: str
    is_imaging: bool
    accession_no: str
    status: str
    bill_status: str
    due: Money
    status_changed_at: datetime | None


class DaySummaryOut(BaseModel):
    day: date
    bills: int
    billed: Money | None              # null without analytics.view
    discounts: Money | None           # null without analytics.view
    collected: dict[str, Money]       # by payment mode, refunds taken off
    collected_total: Money
    dues_collected: Money             # paid today against bills from earlier days
    refunds: Money
    outstanding_dues: Money           # everything still owed, all days
    items_by_status: dict[str, int]   # today's tests by progress


class DeskSummaryOut(BaseModel):
    """The dashboard for staff without analytics.view: the period's totals, without the analytics."""
    date_from: date
    date_to: date
    all_time: bool
    bills: int                        # the period's bills
    billed: Money                     # what they came to, after discounts (cancelled left out)
    collected: dict[str, Money]       # received in the period, by payment mode, refunds taken off
    collected_total: Money
    dues_collected: Money             # paid in the period against bills from before it
    refunds: Money
    due_on_bills: Money               # still owed on the period's bills
    due_bills: int                    # how many of the period's bills still have money due
    outstanding_dues: Money           # everything still owed, any date
    dues_count: int
    pending_tests: dict[str, int]     # billed / scanned, from the period's bills


class TrendPointOut(BaseModel):
    day: date
    billed: Money
    collected: Money


class BreakdownOut(BaseModel):
    name: str
    bills: int
    amount: Money


class PeriodOut(BaseModel):
    bills: int
    billed: Money
    discounts: Money
    due_on_bills: Money               # still owed on the period's bills
    patients: int
    collected: dict[str, Money]       # by payment mode, refunds taken off
    collected_total: Money
    dues_collected: Money             # paid in the period against bills from before it
    refunds: Money


class PreviousPeriodOut(BaseModel):
    date_from: date
    date_to: date
    bills: int
    billed: Money
    collected_total: Money


class OverviewOut(BaseModel):
    """Everything the owner's dashboard shows for the chosen period, in one request."""
    date_from: date
    date_to: date
    days: int
    all_time: bool                        # no start date given: everything since the first bill
    period: PeriodOut
    previous: PreviousPeriodOut           # the same number of days just before
    dues_count: int                       # everything still owed, any date
    outstanding_dues: Money
    trend: list[TrendPointOut]            # oldest first, every day (or month) present
    trend_unit: str                       # day | month
    departments: list[BreakdownOut]       # the period, by amount
    doctors: list[BreakdownOut]           # the period, top referrers by bills
    pending_tests: dict[str, int]         # billed / scanned, from the period's bills
    oldest_dues: list[BillSummaryOut]
