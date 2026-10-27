"""Request and response shapes for test reports, report templates, signatures and imaging studies."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas import Out


def _strip(v: str) -> str:
    return " ".join(v.split())


# ---------- reports ----------

class ReportContentIn(BaseModel):
    """What the doctor writes. findings and impression are HTML from the editor, cleaned on the server."""
    title: str = Field("", max_length=200)
    technique: str = Field("", max_length=500)
    modality: str = Field("", max_length=40)
    findings: str = Field("", max_length=200_000)
    impression: str = Field("", max_length=50_000)
    _t = field_validator("title", "technique", "modality")(_strip)


class ReportCreateIn(BaseModel):
    template_id: uuid.UUID | None = None


class ReportSaveIn(ReportContentIn):
    version: int = Field(ge=1, description="The version this edit started from; 409 if someone saved since.")


class ReportActionIn(BaseModel):
    version: int = Field(ge=1)


class ReportAmendIn(ReportSaveIn):
    reason: str = Field(min_length=3, max_length=500)
    _r = field_validator("reason")(lambda v: v.strip())


class ReportAttachIn(BaseModel):
    """Attach the report as a PDF sent with a resumable upload. version: the report's version when there is one;
    reason: needed when replacing the PDF of a signed report (an amendment)."""
    upload_id: uuid.UUID
    version: int | None = None
    reason: str = Field(default="", max_length=500)


class ReportOut(Out):
    id: uuid.UUID
    invoice_item_id: uuid.UUID
    status: str
    title: str
    technique: str
    modality: str
    findings: str
    impression: str
    reported_by_name: str
    signed_by: uuid.UUID | None
    signed_at: datetime | None
    signer_name: str
    signer_degree: str
    signer_registration_no: str
    amend_reason: str
    amendments: int
    imported: bool
    attachment_name: str
    attachment_pages: int
    attachment_size: int
    version: int
    created_at: datetime
    updated_at: datetime


class ReportVersionOut(Out):
    version: int
    action: str
    status: str
    saved_by_name: str
    reason: str
    created_at: datetime


class ReportVersionFullOut(ReportVersionOut):
    title: str
    technique: str
    modality: str
    findings: str
    impression: str
    attachment_name: str = ""


class StudyOut(Out):
    id: uuid.UUID
    study_instance_uid: str
    modality: str
    description: str
    series_count: int
    instance_count: int
    size_bytes: int
    uploaded_by_name: str
    created_at: datetime
    viewer_url: str = ""


class ReportItemOut(BaseModel):
    """The test, its bill and its patient, as the report header shows them."""
    item_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_no: str
    bill_date: date
    test_id: uuid.UUID | None
    test_name: str
    department_name: str
    is_imaging: bool
    accession_no: str
    status: str
    patient_id: uuid.UUID
    patient_name: str
    patient_age: str
    patient_gender: str
    patient_mobile: str
    referring_doctor_name: str


class PreviousReportOut(BaseModel):
    item_id: uuid.UUID
    bill_date: date
    invoice_no: str
    test_name: str
    status: str
    title: str
    signed_at: datetime | None


class ReportWorkspaceOut(BaseModel):
    item: ReportItemOut
    report: ReportOut | None
    versions: list[ReportVersionOut]
    studies: list[StudyOut]
    previous: list[PreviousReportOut]
    image_server: bool = True


class ReportRowOut(BaseModel):
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
    item_status: str
    report_id: uuid.UUID | None
    report_status: str | None
    report_title: str
    reported_by_name: str
    signer_name: str
    signed_at: datetime | None
    updated_at: datetime | None
    study_count: int
    study_uid: str | None


# ---------- print ----------

class LetterheadOut(BaseModel):
    legal_name: str
    tagline: str
    address: str
    phones: str
    email: str
    brand_color: str
    has_logo: bool
    report_footer: str


class PrintSignerOut(BaseModel):
    name: str
    degree: str
    registration_no: str
    signature: str  # data: URL of the signature picture, or ""


class ReportPrintOut(BaseModel):
    centre: LetterheadOut
    item: ReportItemOut
    patient_no: str
    report_id: uuid.UUID
    status: str
    title: str
    technique: str
    modality: str
    findings: str
    impression: str
    version: int
    amended: bool
    amend_reason: str
    signed_at: datetime | None
    signer: PrintSignerOut | None
    is_final: bool  # signed or amended: valid to hand over
    verification: str
    public_url: str = ""  # the patient's link (for the QR code), when one is working


# ---------- templates ----------

class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    test_id: uuid.UUID | None = None
    title: str = Field("", max_length=200)
    technique: str = Field("", max_length=500)
    findings: str = Field("", max_length=200_000)
    impression: str = Field("", max_length=50_000)
    is_active: bool = True
    _n = field_validator("name", "title", "technique")(_strip)


class TemplateOut(Out):
    id: uuid.UUID
    test_id: uuid.UUID | None
    test_name: str = ""
    name: str
    title: str
    technique: str
    findings: str
    impression: str
    is_active: bool
    updated_at: datetime


# ---------- signature ----------

class SignatureIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=200)
    degree: str = Field("", max_length=200)
    registration_no: str = Field(min_length=2, max_length=60)
    _n = field_validator("display_name", "degree", "registration_no")(_strip)


class SignatureOut(BaseModel):
    exists: bool
    display_name: str
    degree: str
    registration_no: str
    signature: str  # data: URL, or ""
    updated_at: datetime | None


class UploadResultOut(BaseModel):
    studies: list[StudyOut]
    stored: int
    already_stored: int
    rejected: int
    messages: list[str]


# ---------- sending to the patient ----------

class WhatsAppIn(BaseModel):
    to: str = Field("", max_length=24, description="The number to send to; empty = the patient's mobile on the bill.")


class DeliveryOut(Out):
    id: uuid.UUID
    channel: str
    to: str
    status: str
    error: str
    report_version: int
    sent_by_name: str
    created_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None


class DeliveriesOut(BaseModel):
    configured: bool          # WhatsApp sending is set up on the server
    default_to: str           # the patient's mobile (E.164) or ""
    wa_link: str              # wa.me link with a short note, for sending by hand when not configured
    pdf_url: str
    deliveries: list[DeliveryOut]


# ---------- the patient's link ----------

class ShareOut(BaseModel):
    exists: bool
    active: bool
    url: str
    created_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    views: int
    last_viewed_at: datetime | None


class PublicCheckIn(BaseModel):
    check: str = Field(min_length=4, max_length=8)


class PublicInfoOut(BaseModel):
    centre_name: str
    has_logo: bool
    check: Literal["mobile", "birth_year", "bill"]


class PublicReportOut(BaseModel):
    report: "ReportPrintOut"
    pdf_url: str  # works for 15 minutes


ReportTab = Literal["pending", "draft", "signed", "all"]
