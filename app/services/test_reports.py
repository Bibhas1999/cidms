"""Test reports: writing, finalising, signing and amending, with every saved state kept.

- One report per test on a bill. It starts as a draft, may be marked final (ready to sign), and is signed by a
  doctor with a signature profile. A signed report is never edited: it is amended, with a reason, which keeps
  every earlier version and marks the printout "Amended".
- Every save carries the version it was edited from. If someone else saved in between, the save is refused
  (409) instead of silently overwriting their work.
- Findings and impression are HTML from the editor, cleaned to a small safe set of tags before saving.
- Signing moves the test to "reported" on the worklist.
- People who don't write or sign reports only see signed reports (and print them for the patient).
"""

import base64
import io
import uuid
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.html_clean import clean_html
from app.core.security import CurrentUser
from app.models import (
    DoctorSignature,
    ImagingStudy,
    Invoice,
    InvoiceItem,
    LabTest,
    Patient,
    ReportTemplate,
    TenantSettings,
    TestReport,
    TestReportVersion,
    utcnow,
)
from app.repositories.common import contains
from app.schemas_reports import ReportAmendIn, ReportContentIn, ReportSaveIn, SignatureIn, TemplateIn
from app.services import report_links
from app.services.audit import AuditService
from app.services.uploads import UploadService

WRITE, SIGN = "reports.write", "reports.sign"
EDITABLE = {"draft", "final"}
SIGNED = {"signed", "amended"}
CONTENT = ("title", "technique", "modality", "findings", "impression")


def data_url(data: str, mime: str) -> str:
    return f"data:{mime or 'image/png'};base64,{data}" if data else ""


class TestReportService:
    __test__ = False  # not a pytest test class

    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    # ---------- who may do what ----------
    @property
    def sees_drafts(self) -> bool:
        return self.current.can(WRITE) or self.current.can(SIGN)

    def _need(self, permission: str) -> None:
        if not self.current.can(permission):
            raise Forbidden("You don't have permission to do that.")

    # ---------- reading ----------
    def item(self, item_id: uuid.UUID) -> tuple[InvoiceItem, Invoice]:
        row = self.db.execute(select(InvoiceItem, Invoice).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                              .where(InvoiceItem.tenant_id == self.tenant_id, InvoiceItem.id == item_id)).first()
        if row is None:
            raise NotFound("We couldn't find that test.")
        return row[0], row[1]

    def report(self, item_id: uuid.UUID, lock: bool = False) -> TestReport | None:
        q = select(TestReport).where(TestReport.tenant_id == self.tenant_id, TestReport.invoice_item_id == item_id)
        if lock:
            q = q.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(q)

    def _existing(self, item_id: uuid.UUID) -> tuple[TestReport, InvoiceItem, Invoice]:
        """The report, locked for the change, with its test and bill. A cancelled test can't be changed."""
        item, invoice = self.item(item_id)
        report = self.report(item_id, lock=True)
        if report is None:
            raise NotFound("This test has no report yet.")
        self._reportable(item, invoice)
        return report, item, invoice

    def visible(self, report: TestReport | None) -> TestReport | None:
        """The report as this person may see it: everything for doctors, only signed reports for others."""
        if report is None or self.sees_drafts or report.status in SIGNED:
            return report
        return None

    def versions(self, report: TestReport) -> list[TestReportVersion]:
        return list(self.db.scalars(select(TestReportVersion).where(TestReportVersion.report_id == report.id)
                                    .order_by(TestReportVersion.version.desc())))

    def version(self, item_id: uuid.UUID, number: int) -> TestReportVersion:
        if not self.sees_drafts:
            raise Forbidden("You don't have permission to see earlier versions.")
        self.item(item_id)
        report = self.report(item_id)
        row = report and self.db.scalar(select(TestReportVersion).where(TestReportVersion.report_id == report.id,
                                                                         TestReportVersion.version == number))
        if not row:
            raise NotFound("We couldn't find that version.")
        return row

    def studies(self, item_id: uuid.UUID) -> list[ImagingStudy]:
        return list(self.db.scalars(select(ImagingStudy).where(ImagingStudy.tenant_id == self.tenant_id,
                                                               ImagingStudy.invoice_item_id == item_id)
                                    .order_by(ImagingStudy.created_at)))

    def previous(self, item: InvoiceItem, invoice: Invoice) -> list[tuple]:
        """The same patient's other reports for the same test (or test name), newest first."""
        same_test = InvoiceItem.test_id == item.test_id if item.test_id else InvoiceItem.test_name == item.test_name
        q = (select(InvoiceItem, Invoice, TestReport).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
             .join(TestReport, TestReport.invoice_item_id == InvoiceItem.id)
             .where(InvoiceItem.tenant_id == self.tenant_id, Invoice.patient_id == invoice.patient_id, InvoiceItem.id != item.id,
                    same_test)
             .order_by(Invoice.bill_date.desc(), Invoice.created_at.desc()).limit(10))
        if not self.sees_drafts:
            q = q.where(TestReport.status.in_(SIGNED))
        return list(self.db.execute(q).all())

    # ---------- writing ----------
    def _record(self, report: TestReport, action: str, reason: str = "") -> None:
        self.db.add(TestReportVersion(
            tenant_id=self.tenant_id, report_id=report.id, version=report.version, action=action, status=report.status,
            title=report.title, technique=report.technique, modality=report.modality, findings=report.findings,
            impression=report.impression, reason=reason, saved_by=self.current.id, saved_by_name=self.current.user.full_name,
            attachment_name=report.attachment_name))
        self.db.flush()

    def _check_version(self, report: TestReport, version: int) -> None:
        if version != report.version:
            last = self.db.scalar(select(TestReportVersion.saved_by_name).where(TestReportVersion.report_id == report.id)
                                  .order_by(TestReportVersion.version.desc()).limit(1))
            raise Conflict(f"{last or 'Someone'} saved this report after you opened it (it's now version {report.version}). "
                           "Reload to see their changes before saving yours.", "version")

    def _reportable(self, item: InvoiceItem, invoice: Invoice) -> None:
        if item.status == "cancelled" or invoice.status == "cancelled":
            raise Conflict(f"{item.test_name} was cancelled, so it can't be reported.")

    @staticmethod
    def _apply(report: TestReport, data: ReportContentIn) -> bool:
        """Copy the content across (cleaned). True when anything changed."""
        new = {"title": data.title, "technique": data.technique, "modality": data.modality,
               "findings": clean_html(data.findings), "impression": clean_html(data.impression)}
        changed = any(getattr(report, k) != v for k, v in new.items())
        for k, v in new.items():
            setattr(report, k, v)
        return changed

    def _audit(self, action: str, report: TestReport, item: InvoiceItem, invoice: Invoice, extra: dict | None = None) -> None:
        self.audit.record(self.tenant_id, self.current.id, action, "test_report", report.id, {
            "invoice_no": invoice.invoice_no, "test": item.test_name, "version": report.version, **(extra or {})})

    def create(self, item_id: uuid.UUID, template_id: uuid.UUID | None = None) -> TestReport:
        self._need(WRITE)
        item, invoice = self.item(item_id)
        self._reportable(item, invoice)
        self.db.execute(select(InvoiceItem.id).where(InvoiceItem.id == item.id).with_for_update())  # one creator at a time
        existing = self.report(item_id)
        if existing is not None:
            return existing
        report = TestReport(id=uuid.uuid4(), tenant_id=self.tenant_id, invoice_item_id=item.id, status="draft", title=item.test_name,
                            reported_by=self.current.id, reported_by_name=self.current.user.full_name, version=1)
        if template_id:
            t = TemplateService(self.db, self.current).get(template_id)
            self._apply(report, ReportContentIn(title=t.title or item.test_name, technique=t.technique, findings=t.findings,
                                                impression=t.impression))
        self.db.add(report)
        self.db.flush()
        self._record(report, "created")
        self._audit("report.created", report, item, invoice, {"template": str(template_id) if template_id else ""})
        return report

    def save(self, item_id: uuid.UUID, data: ReportSaveIn) -> TestReport:
        self._need(WRITE)
        report, item, invoice = self._existing(item_id)
        self._check_version(report, data.version)
        if report.status in SIGNED:
            raise Conflict("This report is signed. Amend it to change it.")
        if not self._apply(report, data):
            return report  # nothing changed (an autosave with no edits): no new version
        report.status = "draft"  # editing a finalised report opens it again
        report.version += 1
        report.reported_by, report.reported_by_name = self.current.id, self.current.user.full_name
        report.updated_at = utcnow()
        self._record(report, "saved")
        self._audit("report.saved", report, item, invoice)
        return report

    def finalise(self, item_id: uuid.UUID, version: int) -> TestReport:
        self._need(WRITE)
        report, item, invoice = self._existing(item_id)
        self._check_version(report, version)
        if report.status != "draft":
            raise Conflict(f"This report is already {report.status}.")
        self._has_words(report)
        report.status = "final"
        report.version += 1
        report.updated_at = utcnow()
        self._record(report, "finalised")
        self._audit("report.finalised", report, item, invoice)
        return report

    @staticmethod
    def _has_words(report: TestReport) -> None:
        if not report.findings and not report.impression and not report.attachment_name:
            raise Invalid("Write the findings or the impression, or attach the report as a PDF, first.", "findings")

    # ---------- an uploaded PDF report ----------
    def attach(self, item_id: uuid.UUID, upload_id: uuid.UUID, version: int | None, reason: str = "") -> TestReport:
        """Attach (or replace) the report as a PDF sent with a resumable upload. A draft or final report goes back to
        draft; replacing the PDF of a signed report is an amendment, signed again, and needs a reason."""
        self._need(WRITE)
        item, invoice = self.item(item_id)
        self._reportable(item, invoice)
        report = self.report(item_id, lock=True)
        if report is None:
            self.create(item_id)
            report = self.report(item_id, lock=True)
        elif version is not None:
            self._check_version(report, version)
        signed = report.status in SIGNED
        if signed:
            self._need(SIGN)
            if len(reason.strip()) < 3:
                raise Invalid("This report is signed: say why the PDF is being replaced.", "reason")
            sig = self._signature()
        filename, content = UploadService(self.db, self.current).take(upload_id, "report_pdf")
        pages = pdf_pages(content)
        report.attachment_name, report.attachment_pages, report.attachment_size = filename, pages, len(content)
        report.attachment_data = base64.b64encode(content).decode()
        report.version += 1
        report.updated_at = utcnow()
        if signed:
            self._sign_as(report, sig)
            report.status, report.amend_reason = "amended", reason.strip()
            report.amendments += 1
            self._record(report, "amended", reason.strip())
            report_links.issue(self.db, self.tenant_id, report.id, self.current.id)
        else:
            report.status = "draft"
            report.reported_by, report.reported_by_name = self.current.id, self.current.user.full_name
            self._record(report, "attached")
        self._audit("report.attached", report, item, invoice, {"file": filename, "pages": pages, "bytes": len(content),
                                                               **({"reason": reason.strip()} if signed else {})})
        return report

    def detach(self, item_id: uuid.UUID, version: int) -> TestReport:
        self._need(WRITE)
        report, item, invoice = self._existing(item_id)
        self._check_version(report, version)
        if report.status in SIGNED:
            raise Conflict("This report is signed. Replace the PDF instead (that's an amendment).")
        if not report.attachment_name:
            return report
        name = report.attachment_name
        report.attachment_name, report.attachment_pages, report.attachment_size, report.attachment_data = "", 0, 0, ""
        report.status = "draft"
        report.version += 1
        report.updated_at = utcnow()
        self._record(report, "detached")
        self._audit("report.detached", report, item, invoice, {"file": name})
        return report

    def attachment(self, item_id: uuid.UUID) -> tuple[bytes, str]:
        """The uploaded PDF as it was sent (to look at while reporting); drafts only for those who may see them."""
        report = self.visible(self.report(item_id))
        if report is None or not report.attachment_name:
            raise NotFound("This report has no PDF attached.")
        return base64.b64decode(report.attachment_data), report.attachment_name

    def _signature(self) -> DoctorSignature:
        sig = self.db.get(DoctorSignature, self.current.id)
        if sig is None or sig.tenant_id != self.tenant_id:
            raise Invalid("Set up your signature (name, degree and registration number) in Settings before signing.", "signature")
        return sig

    def _sign_as(self, report: TestReport, sig: DoctorSignature) -> None:
        report.signed_by, report.signed_at = self.current.id, utcnow()
        report.signer_name, report.signer_degree, report.signer_registration_no = sig.display_name, sig.degree, sig.registration_no
        report.signature_data, report.signature_mime = sig.signature_data, sig.signature_mime

    def _mark_reported(self, item: InvoiceItem, invoice: Invoice) -> None:
        """Billed or scanned tests move to "reported" (a test already delivered stays delivered)."""
        if item.status in ("billed", "scanned"):
            old = item.status
            item.status = "reported"
            item.status_changed_at = utcnow()
            self.audit.record(self.tenant_id, self.current.id, "test.reported", "invoice_item", item.id, {
                "invoice_no": invoice.invoice_no, "test": item.test_name, "from": old, "due": str(invoice.due)})

    def sign(self, item_id: uuid.UUID, version: int) -> TestReport:
        self._need(SIGN)
        report, item, invoice = self._existing(item_id)
        self._check_version(report, version)
        if report.status not in EDITABLE:
            raise Conflict("This report is already signed.")
        self._has_words(report)
        self._sign_as(report, self._signature())
        report.status = "signed"
        report.version += 1
        report.updated_at = utcnow()
        self._record(report, "signed")
        self._mark_reported(item, invoice)
        report_links.issue(self.db, self.tenant_id, report.id, self.current.id)
        self._audit("report.signed", report, item, invoice, {"signer": report.signer_name})
        return report

    def amend(self, item_id: uuid.UUID, data: ReportAmendIn) -> TestReport:
        self._need(SIGN)
        report, item, invoice = self._existing(item_id)
        self._check_version(report, data.version)
        if report.status not in SIGNED:
            raise Conflict("Only a signed report can be amended. Save your changes instead.")
        sig = self._signature()
        self._apply(report, data)
        self._has_words(report)
        self._sign_as(report, sig)
        report.status = "amended"
        report.amend_reason = data.reason
        report.amendments += 1
        report.version += 1
        report.updated_at = utcnow()
        self._record(report, "amended", data.reason)
        self._mark_reported(item, invoice)
        report_links.issue(self.db, self.tenant_id, report.id, self.current.id)  # the same link, now showing the amendment
        self._audit("report.amended", report, item, invoice, {"reason": data.reason, "signer": report.signer_name})
        return report

    # ---------- the reporting worklist ----------
    def query(self, tab: str, date_from: date | None, date_to: date | None, search: str, department_id: uuid.UUID | None):
        studies = (select(func.count()).select_from(ImagingStudy).where(ImagingStudy.invoice_item_id == InvoiceItem.id)
                   .correlate(InvoiceItem).scalar_subquery())
        first_uid = (select(ImagingStudy.study_instance_uid).where(ImagingStudy.invoice_item_id == InvoiceItem.id)
                     .order_by(ImagingStudy.created_at).limit(1).correlate(InvoiceItem).scalar_subquery())
        q = (select(InvoiceItem, Invoice, TestReport, studies.label("study_count"), first_uid.label("study_uid"))
             .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
             .outerjoin(TestReport, TestReport.invoice_item_id == InvoiceItem.id)
             .where(InvoiceItem.tenant_id == self.tenant_id, InvoiceItem.status != "cancelled", Invoice.status != "cancelled",
                    InvoiceItem.test_id.is_not(None)))
        if not self.sees_drafts:
            tab = "signed"
        if tab == "pending":
            q = q.where(TestReport.id.is_(None), InvoiceItem.status.in_(("billed", "scanned")))
        elif tab == "draft":
            q = q.where(TestReport.status.in_(EDITABLE))
        elif tab == "signed":
            q = q.where(TestReport.status.in_(SIGNED))
        if date_from:
            q = q.where(Invoice.bill_date >= date_from)
        if date_to:
            q = q.where(Invoice.bill_date <= date_to)
        if department_id:
            q = q.where(InvoiceItem.department_id == department_id)
        s = search.strip()
        if s:
            q = q.where(or_(func.lower(Invoice.patient_name).like(contains(s), escape="\\"), func.lower(Invoice.invoice_no) == s.lower(),
                            InvoiceItem.accession_no == s.upper(), func.lower(InvoiceItem.test_name).like(contains(s), escape="\\")))
        if tab == "pending":
            order = (Invoice.bill_date, Invoice.created_at, InvoiceItem.position)
        elif tab == "signed":
            order = (TestReport.signed_at.desc().nulls_last(), TestReport.updated_at.desc())
        else:
            order = (TestReport.updated_at.desc().nulls_last(), Invoice.bill_date.desc(), InvoiceItem.position)
        return q.order_by(*order)

    def page(self, tab: str, date_from: date | None, date_to: date | None, search: str, department_id: uuid.UUID | None,
             page: int, size: int):
        q = self.query(tab, date_from, date_to, search, department_id)
        total = self.db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        return self.db.execute(q.offset((page - 1) * size).limit(size)).all(), total

    # ---------- print ----------
    def print_data(self, item_id: uuid.UUID, base_url: str = "") -> dict:
        item, invoice = self.item(item_id)
        report = self.visible(self.report(item_id))
        if report is None:
            raise NotFound("This test has no signed report to print yet.")
        return build_print_data(self.db, self.tenant_id, report, item, invoice, base_url)

    def item_id_of(self, report_id: uuid.UUID) -> uuid.UUID:
        item_id = self.db.scalar(select(TestReport.invoice_item_id).where(TestReport.tenant_id == self.tenant_id, TestReport.id == report_id))
        if item_id is None:
            raise NotFound("We couldn't find that report.")
        return item_id

    def pdf(self, report_id: uuid.UUID, base_url: str = "") -> tuple[bytes, str]:
        """The signed report as a PDF, and a file name for it."""
        item_id = self.item_id_of(report_id)
        item, invoice = self.item(item_id)
        report = self.report(item_id)
        if report is None or report.status not in SIGNED:
            raise Conflict("Only a signed report can be downloaded as a PDF.")
        return build_pdf(self.db, self.tenant_id, report, item, invoice, base_url)


def pdf_pages(content: bytes) -> int:
    """Pages in an uploaded PDF; refuses anything that isn't a readable, unlocked PDF."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    if not content.startswith(b"%PDF-"):
        raise Invalid("That file isn't a PDF.", "file")
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise Invalid("That PDF is password-protected. Save it without a password and upload it again.", "file")
        pages = len(reader.pages)
    except (PdfReadError, ValueError, KeyError) as exc:
        raise Invalid("That PDF couldn't be read. It may be damaged; export it again and upload it.", "file") from exc
    if not pages:
        raise Invalid("That PDF has no pages.", "file")
    return pages


def join_pdfs(*parts: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for part in parts:
        reader = PdfReader(io.BytesIO(part))
        if reader.is_encrypted:
            reader.decrypt("")
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def build_print_data(db: Session, tenant_id: uuid.UUID, report: TestReport, item: InvoiceItem, invoice: Invoice, base_url: str = "") -> dict:
    """Everything the printed report (and the PDF, and the patient's page) shows."""
    settings = db.get(TenantSettings, tenant_id)
    patient = db.get(Patient, invoice.patient_id)
    signer = None
    if report.status in SIGNED and report.signer_name:
        signer = {"name": report.signer_name, "degree": report.signer_degree, "registration_no": report.signer_registration_no,
                  "signature": data_url(report.signature_data, report.signature_mime)}
    share = report_links.current_share(db, tenant_id, report.id)
    link = report_links.public_url(base_url, share) if base_url and report_links.is_active(share) and report.status in SIGNED else ""
    return {
        "centre": {"legal_name": settings.legal_name if settings else "", "tagline": settings.tagline if settings else "",
                   "address": settings.address if settings else "", "phones": settings.phones if settings else "",
                   "email": settings.email if settings else "", "brand_color": settings.brand_color if settings else "#0f6e6e",
                   "has_logo": bool(settings and settings.logo_data), "report_footer": settings.report_footer if settings else ""},
        "item": item_out(item, invoice), "patient_no": patient.patient_no if patient else "",
        "report_id": report.id, "status": report.status, "title": report.title, "technique": report.technique,
        "modality": report.modality, "findings": report.findings, "impression": report.impression, "version": report.version,
        "amended": report.status == "amended" or report.amendments > 0, "amend_reason": report.amend_reason,
        "signed_at": report.signed_at, "signer": signer, "is_final": report.status in SIGNED,
        "verification": f"{report.id.hex[:8].upper()}-{report.version}", "public_url": link,
    }


def build_pdf(db: Session, tenant_id: uuid.UUID, report: TestReport, item: InvoiceItem, invoice: Invoice, base_url: str = "") -> tuple[bytes, str]:
    from app.core.storage import decode
    from app.services.report_pdf import report_pdf
    data = build_print_data(db, tenant_id, report, item, invoice, base_url)
    settings = db.get(TenantSettings, tenant_id)
    # An uploaded PDF report: the centre's signed page first (any typed findings, the signer, the verification code
    # and link), then every page of the uploaded report.
    if report.attachment_name and not data["findings"] and not data["impression"]:
        n = report.attachment_pages
        data["findings"] = f"<p>The report follows on the next {n} page{'s' if n != 1 else ''}.</p>"
    content = report_pdf(data, decode(settings.logo_data) if settings else None, decode(report.signature_data))
    if report.attachment_name:
        content = join_pdfs(content, base64.b64decode(report.attachment_data))
    safe = "".join(ch if ch.isalnum() else "-" for ch in f"{item.test_name} {invoice.patient_name}").strip("-")
    return content, f"Report-{safe[:60] or 'patient'}.pdf"


def item_out(item: InvoiceItem, invoice: Invoice) -> dict:
    return {
        "item_id": item.id, "invoice_id": invoice.id, "invoice_no": invoice.invoice_no, "bill_date": invoice.bill_date,
        "test_id": item.test_id, "test_name": item.test_name, "department_name": item.department_name, "is_imaging": item.is_imaging,
        "accession_no": item.accession_no, "status": item.status, "patient_id": invoice.patient_id, "patient_name": invoice.patient_name,
        "patient_age": invoice.patient_age, "patient_gender": invoice.patient_gender, "patient_mobile": invoice.patient_mobile,
        "referring_doctor_name": invoice.referring_doctor_name,
    }


class TemplateService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    def list(self, test_id: uuid.UUID | None = None, active_only: bool = False) -> list[tuple[ReportTemplate, str]]:
        q = (select(ReportTemplate, LabTest.name).outerjoin(LabTest, LabTest.id == ReportTemplate.test_id)
             .where(ReportTemplate.tenant_id == self.tenant_id))
        if test_id:
            q = q.where(or_(ReportTemplate.test_id == test_id, ReportTemplate.test_id.is_(None)))
        if active_only:
            q = q.where(ReportTemplate.is_active.is_(True))
        # For a test: its own templates first, then the general ones.
        return list(self.db.execute(q.order_by(ReportTemplate.test_id.is_(None), func.lower(ReportTemplate.name))).all())

    def get(self, template_id: uuid.UUID) -> ReportTemplate:
        t = self.db.scalar(select(ReportTemplate).where(ReportTemplate.tenant_id == self.tenant_id, ReportTemplate.id == template_id))
        if t is None:
            raise NotFound("We couldn't find that template.")
        return t

    def save(self, data: TemplateIn, template_id: uuid.UUID | None = None) -> ReportTemplate:
        if data.test_id and self.db.scalar(select(LabTest.id).where(LabTest.tenant_id == self.tenant_id, LabTest.id == data.test_id)) is None:
            raise Invalid("Choose a test from your catalogue.", "test_id")
        clash = select(ReportTemplate.id).where(ReportTemplate.tenant_id == self.tenant_id,
                                                func.lower(ReportTemplate.name) == data.name.lower())
        if template_id:
            clash = clash.where(ReportTemplate.id != template_id)
        if self.db.scalar(clash) is not None:
            raise Invalid("There's already a template with this name.", "name")
        t = self.get(template_id) if template_id else ReportTemplate(id=uuid.uuid4(), tenant_id=self.tenant_id)
        t.name, t.test_id, t.title, t.technique, t.is_active = data.name, data.test_id, data.title, data.technique, data.is_active
        t.findings, t.impression = clean_html(data.findings), clean_html(data.impression)
        t.updated_at = utcnow()
        if not template_id:
            self.db.add(t)
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "report_template.updated" if template_id else "report_template.created",
                          "report_template", t.id, {"name": t.name})
        return t

    def delete(self, template_id: uuid.UUID) -> None:
        t = self.get(template_id)
        self.audit.record(self.tenant_id, self.current.id, "report_template.deleted", "report_template", t.id, {"name": t.name})
        self.db.delete(t)


class SignatureService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    def get(self) -> DoctorSignature | None:
        sig = self.db.get(DoctorSignature, self.current.id)
        return sig if sig is not None and sig.tenant_id == self.tenant_id else None

    def save(self, data: SignatureIn) -> DoctorSignature:
        sig = self.get()
        if sig is None:
            sig = DoctorSignature(user_id=self.current.id, tenant_id=self.tenant_id, display_name=data.display_name)
            self.db.add(sig)
        sig.display_name, sig.degree, sig.registration_no = data.display_name, data.degree, data.registration_no
        sig.updated_at = utcnow()
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "signature.updated", "user", self.current.id,
                          {"name": sig.display_name, "degree": sig.degree, "registration_no": sig.registration_no})
        return sig

    def set_image(self, data: bytes | None) -> DoctorSignature:
        from app.core.storage import _clean_png
        sig = self.get()
        if sig is None:
            raise Invalid("Save your name and registration number first.", "signature")
        if data is None:
            sig.signature_data = sig.signature_mime = sig.signature_version = ""
        else:
            img = _clean_png(data, "signature", "signature", max_side=600)
            sig.signature_data, sig.signature_mime, sig.signature_version = img.data, img.mime, img.version
        sig.updated_at = utcnow()
        self.audit.record(self.tenant_id, self.current.id, "signature.image_removed" if data is None else "signature.image_updated",
                          "user", self.current.id)
        return sig
