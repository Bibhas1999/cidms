"""Test reports, report templates, signatures, imaging uploads, the DICOMweb proxy and the image viewer.

Browsers never talk to the image server (Orthanc) or the viewer (OHIF) directly: both are reached through
this app at /api/dicom-web and /viewer, so they share its sign-in, and each client only sees its own studies.
"""

import base64
import gzip
import hashlib
import hmac
import json
import re
import uuid
from datetime import date

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUpload

from app.api.deps import Paging, client_user, paging
from app.core.config import get_settings
from app.core.db import DB, scoped_session
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.logging import client_ip
from app.core.orthanc import ImageServerUnavailable, async_client, is_up, shared_async_client
from app.core.security import CurrentUser, resolve_current
from app.core.storage import MAX_LOGO_BYTES
from app.models import TenantSettings
from app.schemas import Page
from app.schemas_reports import (
    DeliveriesOut,
    DeliveryOut,
    PublicCheckIn,
    PublicInfoOut,
    PublicReportOut,
    ReportActionIn,
    ReportAmendIn,
    ReportAttachIn,
    ReportCreateIn,
    ReportOut,
    ReportPrintOut,
    ReportRowOut,
    ReportSaveIn,
    ReportTab,
    ReportVersionFullOut,
    ReportVersionOut,
    ReportWorkspaceOut,
    ShareOut,
    SignatureIn,
    SignatureOut,
    StudyOut,
    TemplateIn,
    TemplateOut,
    UploadResultOut,
    WhatsAppIn,
)
from app.services import report_links
from app.services.audit import AuditService
from app.services.imaging import MAX_FILES, ImagingService, upload_limit_bytes
from app.services.report_summary import ReportSummaryService
from app.services.test_reports import (
    SIGN,
    WRITE,
    SignatureService,
    TemplateService,
    TestReportService,
    build_pdf,
    build_print_data,
    data_url,
    item_out,
)
from app.services.whatsapp import WhatsAppService, apply_statuses, signature_ok, wa_me_link
from app.services.whatsapp import is_configured as whatsapp_configured

router = APIRouter()  # everything below, included once by app.main
reports = APIRouter(prefix="/api/test-reports", tags=["test reports"])
imaging = APIRouter(prefix="/api/imaging", tags=["imaging"])
dicomweb = APIRouter(prefix="/api/dicom-web", tags=["imaging"], include_in_schema=False)
viewer = APIRouter(include_in_schema=False)
webhooks = APIRouter(prefix="/api/webhooks", include_in_schema=False)
public = APIRouter(prefix="/api/public/reports", tags=["public"])


def any_of(*permissions: str):
    """A client user holding at least one of the permissions."""
    def dep(current: CurrentUser = Depends(client_user)) -> CurrentUser:
        if not any(current.can(p) for p in permissions):
            raise Forbidden("You don't have permission to do that.")
        return current
    return dep


def base_url(request: Request) -> str:
    """This centre's address as the browser used it (for the patient's link)."""
    return f"{request.url.scheme}://{request.headers.get('host', '')}"


def viewer_url(uid: str) -> str:
    return f"/viewer/viewer?StudyInstanceUIDs={uid}"


def _study(s) -> StudyOut:
    return StudyOut.model_validate(s).model_copy(update={"viewer_url": viewer_url(s.study_instance_uid)})


def _workspace(svc: TestReportService, item_id: uuid.UUID, check_server: bool = False) -> ReportWorkspaceOut:
    item, invoice = svc.item(item_id)
    report = svc.visible(svc.report(item_id))
    previous = [{"item_id": i.id, "bill_date": b.bill_date, "invoice_no": b.invoice_no, "test_name": i.test_name, "status": r.status,
                 "title": r.title, "signed_at": r.signed_at} for i, b, r in svc.previous(item, invoice)]
    return ReportWorkspaceOut(
        item=item_out(item, invoice), report=ReportOut.model_validate(report) if report else None,
        versions=[ReportVersionOut.model_validate(v) for v in svc.versions(report)] if report and svc.sees_drafts else [],
        studies=[_study(s) for s in svc.studies(item_id)], previous=previous,
        image_server=is_up() if check_server and item.is_imaging else True,
    )


# ---------- reports ----------

@reports.get("", response_model=Page[ReportRowOut])
def report_queue(tab: ReportTab = Query("pending", alias="status"), date_from: date | None = Query(None, alias="from"),
                 date_to: date | None = Query(None, alias="to"), search: str = Query("", max_length=100),
                 department_id: uuid.UUID | None = None, p: Paging = Depends(paging), db: Session = DB,
                 current: CurrentUser = Depends(client_user)):
    """The reporting worklist: tests waiting for a report (pending), drafts (draft and final), signed reports."""
    rows, total = TestReportService(db, current).page(tab, date_from, date_to, search, department_id, p.page, p.size)
    items = [ReportRowOut(
        item_id=i.id, invoice_id=b.id, invoice_no=b.invoice_no, bill_date=b.bill_date, patient_name=b.patient_name,
        patient_age=b.patient_age, patient_gender=b.patient_gender, test_name=i.test_name, department_name=i.department_name,
        is_imaging=i.is_imaging, accession_no=i.accession_no, item_status=i.status, report_id=r.id if r else None,
        report_status=r.status if r else None, report_title=r.title if r else "", reported_by_name=r.reported_by_name if r else "",
        signer_name=r.signer_name if r else "", signed_at=r.signed_at if r else None, updated_at=r.updated_at if r else None,
        study_count=n or 0, study_uid=uid) for i, b, r, n, uid in rows]
    return Page(items=items, total=total, page=p.page, size=p.size)


@reports.get("/summary")
def report_summary(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"), db: Session = DB,
                   current: CurrentUser = Depends(any_of(WRITE, SIGN))):
    """The reporting dashboard: work in hand now, and signed / turnaround / sent for the period. Counts and times only."""
    return ReportSummaryService(db, current).summary(date_from, date_to)


@reports.get("/for-item/{item_id}", response_model=ReportWorkspaceOut)
def report_for_item(item_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    out = _workspace(TestReportService(db, current), item_id, check_server=True)
    AuditService(db).viewed(current.user.tenant_id, current.id, "invoice_item", item_id, {"as": "report", "test": out.item.test_name})
    return out


@reports.post("/for-item/{item_id}", response_model=ReportWorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_report(item_id: uuid.UUID, data: ReportCreateIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    svc = TestReportService(db, current)
    svc.create(item_id, data.template_id)
    return _workspace(svc, item_id)


@reports.put("/for-item/{item_id}", response_model=ReportWorkspaceOut)
def save_report(item_id: uuid.UUID, data: ReportSaveIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    svc = TestReportService(db, current)
    svc.save(item_id, data)
    return _workspace(svc, item_id)


@reports.post("/for-item/{item_id}/finalise", response_model=ReportWorkspaceOut)
def finalise_report(item_id: uuid.UUID, data: ReportActionIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    svc = TestReportService(db, current)
    svc.finalise(item_id, data.version)
    return _workspace(svc, item_id)


@reports.post("/for-item/{item_id}/sign", response_model=ReportWorkspaceOut)
def sign_report(item_id: uuid.UUID, data: ReportActionIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    svc = TestReportService(db, current)
    svc.sign(item_id, data.version)
    return _workspace(svc, item_id)


@reports.post("/for-item/{item_id}/amend", response_model=ReportWorkspaceOut)
def amend_report(item_id: uuid.UUID, data: ReportAmendIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    svc = TestReportService(db, current)
    svc.amend(item_id, data)
    return _workspace(svc, item_id)


@reports.post("/for-item/{item_id}/attachment", response_model=ReportWorkspaceOut)
def attach_pdf(item_id: uuid.UUID, data: ReportAttachIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    """The report as an uploaded PDF (instead of, or as well as, typed findings)."""
    svc = TestReportService(db, current)
    svc.attach(item_id, data.upload_id, data.version, data.reason)
    return _workspace(svc, item_id)


@reports.delete("/for-item/{item_id}/attachment", response_model=ReportWorkspaceOut)
def detach_pdf(item_id: uuid.UUID, version: int, db: Session = DB, current: CurrentUser = Depends(client_user)):
    svc = TestReportService(db, current)
    svc.detach(item_id, version)
    return _workspace(svc, item_id)


@reports.get("/for-item/{item_id}/attachment", include_in_schema=False)
def attached_pdf(item_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    content, filename = TestReportService(db, current).attachment(item_id)
    safe = "".join(ch if ch.isalnum() or ch in ".-_" else "-" for ch in filename)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{safe}"'})


@reports.get("/for-item/{item_id}/versions/{number}", response_model=ReportVersionFullOut)
def report_version(item_id: uuid.UUID, number: int, db: Session = DB, current: CurrentUser = Depends(client_user)):
    return TestReportService(db, current).version(item_id, number)


@reports.get("/for-item/{item_id}/print", response_model=ReportPrintOut)
def report_print(item_id: uuid.UUID, request: Request, db: Session = DB, current: CurrentUser = Depends(client_user)):
    data = TestReportService(db, current).print_data(item_id, base_url(request))
    AuditService(db).viewed(current.user.tenant_id, current.id, "invoice_item", item_id, {"as": "print"})
    return data


# ---------- the PDF, and sending it to the patient ----------

@reports.get("/{report_id}/pdf", include_in_schema=False)
def report_pdf(report_id: uuid.UUID, request: Request, download: bool = False, db: Session = DB,
               current: CurrentUser = Depends(client_user)):
    content, filename = TestReportService(db, current).pdf(report_id, base_url(request))
    AuditService(db).viewed(current.user.tenant_id, current.id, "test_report", report_id, {"as": "pdf"})
    disposition = "attachment" if download else "inline"
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})


def _deliveries(svc: WhatsAppService, report_id: uuid.UUID) -> DeliveriesOut:
    _report, _item, invoice = svc.report(report_id)
    to = svc.default_to(invoice)
    return DeliveriesOut(configured=whatsapp_configured(), default_to=to, wa_link=wa_me_link(to, svc.centre_name()),
                         pdf_url=f"/api/test-reports/{report_id}/pdf",
                         deliveries=[DeliveryOut.model_validate(d) for d in svc.history(report_id)])


@reports.get("/{report_id}/whatsapp", response_model=DeliveriesOut)
def whatsapp_history(report_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    """Whether WhatsApp is set up, the patient's number, and every time this report was sent."""
    return _deliveries(WhatsAppService(db, current), report_id)


@reports.post("/{report_id}/whatsapp", response_model=DeliveriesOut)
def whatsapp_send(report_id: uuid.UUID, data: WhatsAppIn, request: Request, db: Session = DB,
                  current: CurrentUser = Depends(any_of(WRITE))):
    """Send the signed report's PDF to the patient. The answer lists the deliveries, newest (this one) first:
    its status is "sent" or "failed" (with the reason)."""
    svc = WhatsAppService(db, current)
    delivery = svc.queue(report_id, data.to or None)
    content, filename = TestReportService(db, current).pdf(report_id, base_url(request))
    report, _item, invoice = svc.report(report_id)
    share = report_links.issue(db, current.user.tenant_id, report.id, current.id)  # a working link to go with it
    svc.deliver(delivery, content, filename, invoice.patient_name, report_links.public_url(base_url(request), share))
    db.flush()
    return _deliveries(svc, report_id)


# ---------- the patient's link (QR code) ----------

def _share(db: Session, current: CurrentUser, report_id: uuid.UUID, request: Request) -> ShareOut:
    share = report_links.current_share(db, current.user.tenant_id, report_id)
    if share is None:
        return ShareOut(exists=False, active=False, url="", created_at=None, expires_at=None, revoked_at=None, views=0, last_viewed_at=None)
    active = report_links.is_active(share)
    return ShareOut(exists=True, active=active, url=report_links.public_url(base_url(request), share) if active else "",
                    created_at=share.created_at, expires_at=share.expires_at, revoked_at=share.revoked_at, views=share.views,
                    last_viewed_at=share.last_viewed_at)


def _signed_report(db: Session, current: CurrentUser, report_id: uuid.UUID):
    report, _item, _invoice = WhatsAppService(db, current).report(report_id)
    if report.status not in ("signed", "amended"):
        raise Conflict("The patient's link is made when the report is signed.")
    return report


@reports.get("/{report_id}/share", response_model=ShareOut)
def share_status(report_id: uuid.UUID, request: Request, db: Session = DB, current: CurrentUser = Depends(any_of(WRITE, SIGN))):
    WhatsAppService(db, current).report(report_id)
    return _share(db, current, report_id, request)


@reports.post("/{report_id}/share", response_model=ShareOut)
def share_issue(report_id: uuid.UUID, request: Request, db: Session = DB, current: CurrentUser = Depends(any_of(WRITE))):
    """A new link for the patient. The old one stops working (printed QR codes with it too)."""
    report = _signed_report(db, current, report_id)
    report_links.issue(db, current.user.tenant_id, report.id, current.id, replace=True)
    return _share(db, current, report_id, request)


@reports.delete("/{report_id}/share", response_model=ShareOut)
def share_revoke(report_id: uuid.UUID, request: Request, db: Session = DB, current: CurrentUser = Depends(any_of(WRITE))):
    WhatsAppService(db, current).report(report_id)
    report_links.revoke(db, current.user.tenant_id, report_id, current.id)
    return _share(db, current, report_id, request)


# ---------- the patient's page (no sign-in; the link's token and a check instead) ----------

PUBLIC_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}


def _public_tenant(request: Request) -> uuid.UUID:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None or not tenant.is_active:
        raise NotFound(report_links.NOT_FOUND)
    return tenant.id


@public.get("/{token}", response_model=PublicInfoOut)
def public_info(token: str, request: Request, response: Response, db: Session = DB):
    """The centre's name and what the patient is asked for. Nothing about the report or the patient."""
    response.headers.update(PUBLIC_HEADERS)
    tenant_id = _public_tenant(request)
    _share_row, _report, _item, invoice = report_links.find(db, tenant_id, token)
    settings = db.get(TenantSettings, tenant_id)
    kind, _answer = report_links.check_kind(db, invoice)
    return PublicInfoOut(centre_name=(settings.legal_name if settings else "") or request.state.tenant.name,
                         has_logo=bool(settings and settings.logo_data), check=kind)


@public.post("/{token}/open", response_model=PublicReportOut)
def public_open(token: str, data: PublicCheckIn, request: Request, response: Response, db: Session = DB):
    response.headers.update(PUBLIC_HEADERS)
    tenant_id = _public_tenant(request)
    share, report, item, invoice = report_links.check(db, tenant_id, token, data.check, client_ip(request) or "")
    out = build_print_data(db, tenant_id, report, item, invoice, base_url(request))
    return PublicReportOut(report=ReportPrintOut.model_validate(out),
                           pdf_url=f"/api/public/reports/{token}/pdf?grant={report_links.grant_for(share.id)}")


@public.get("/{token}/pdf", include_in_schema=False)
def public_pdf(token: str, request: Request, grant: str = Query("", max_length=80), db: Session = DB):
    tenant_id = _public_tenant(request)
    share, report, item, invoice = report_links.find(db, tenant_id, token)
    if not report_links.grant_ok(share.id, grant):
        raise Forbidden("This download has expired. Open the link again.")
    content, filename = build_pdf(db, tenant_id, report, item, invoice, base_url(request))
    AuditService(db).record(tenant_id, None, "report.public_downloaded", "test_report", report.id, {"share": str(share.id), "public": True})
    disposition = 'attachment; filename="' + filename + '"'
    return Response(content, media_type="application/pdf", headers={**PUBLIC_HEADERS, "Content-Disposition": disposition})


# ---------- templates ----------

manage_templates = any_of(SIGN, "catalogue.manage")


def _template(t, test_name: str | None) -> TemplateOut:
    return TemplateOut.model_validate(t).model_copy(update={"test_name": test_name or ""})


@reports.get("/templates", response_model=list[TemplateOut])
def templates(test_id: uuid.UUID | None = None, active: bool = False, db: Session = DB,
              current: CurrentUser = Depends(any_of(WRITE, SIGN, "catalogue.manage"))):
    """All templates, or with test_id those for that test plus the general ones (active=true: switched-on only)."""
    return [_template(t, n) for t, n in TemplateService(db, current).list(test_id, active)]


@reports.post("/templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def add_template(data: TemplateIn, db: Session = DB, current: CurrentUser = Depends(manage_templates)):
    svc = TemplateService(db, current)
    t = svc.save(data)
    return _template(t, next((n for x, n in svc.list() if x.id == t.id), ""))


@reports.put("/templates/{template_id}", response_model=TemplateOut)
def edit_template(template_id: uuid.UUID, data: TemplateIn, db: Session = DB, current: CurrentUser = Depends(manage_templates)):
    svc = TemplateService(db, current)
    t = svc.save(data, template_id)
    return _template(t, next((n for x, n in svc.list() if x.id == t.id), ""))


@reports.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(manage_templates)):
    TemplateService(db, current).delete(template_id)


# ---------- my signature ----------

def _signature(sig) -> SignatureOut:
    if sig is None:
        return SignatureOut(exists=False, display_name="", degree="", registration_no="", signature="", updated_at=None)
    return SignatureOut(exists=True, display_name=sig.display_name, degree=sig.degree, registration_no=sig.registration_no,
                        signature=data_url(sig.signature_data, sig.signature_mime), updated_at=sig.updated_at)


@reports.get("/my-signature", response_model=SignatureOut)
def my_signature(db: Session = DB, current: CurrentUser = Depends(any_of(SIGN))):
    out = _signature(SignatureService(db, current).get())
    if not out.exists:
        out.display_name = current.user.full_name
    return out


@reports.put("/my-signature", response_model=SignatureOut)
def save_my_signature(data: SignatureIn, db: Session = DB, current: CurrentUser = Depends(any_of(SIGN))):
    return _signature(SignatureService(db, current).save(data))


@reports.post("/my-signature/image", response_model=SignatureOut)
async def upload_signature_image(request: Request, db: Session = DB, current: CurrentUser = Depends(any_of(SIGN))):
    form = await request.form(max_files=1, max_fields=2)
    try:
        upload = form.get("signature")
        if not isinstance(upload, StarletteUpload):
            raise Invalid("Choose a picture of your signature.", "signature")
        data = await upload.read(MAX_LOGO_BYTES + 1)
    finally:
        await form.close()
    return _signature(SignatureService(db, current).set_image(data))


@reports.delete("/my-signature/image", response_model=SignatureOut)
def remove_signature_image(db: Session = DB, current: CurrentUser = Depends(any_of(SIGN))):
    return _signature(SignatureService(db, current).set_image(None))


# ---------- imaging ----------

@imaging.get("/status")
def imaging_status(current: CurrentUser = Depends(client_user)):
    return {"available": is_up(), "max_upload_mb": get_settings().imaging_max_upload_mb}


@imaging.get("/items/{item_id}/studies", response_model=list[StudyOut])
def item_studies(item_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    return [_study(s) for s in ImagingService(db, current).studies(item_id)]


@imaging.post("/items/{item_id}/upload", response_model=UploadResultOut)
async def upload_images(item_id: uuid.UUID, request: Request, db: Session = DB,
                        current: CurrentUser = Depends(any_of("worklist.update", WRITE))):
    """DICOM files (.dcm) or .zip archives of them, as multipart field "files". Up to IMAGING_MAX_UPLOAD_MB in all."""
    length = request.headers.get("content-length", "")
    limit = upload_limit_bytes()
    if not length.isdigit():
        raise Invalid("The upload's size is missing. Please try again.", "files")
    if int(length) > limit + 1_000_000:
        raise Invalid(f"Upload at most {get_settings().imaging_max_upload_mb} MB at a time.", "files")
    form = await request.form(max_files=MAX_FILES, max_fields=10)
    try:
        files = [(f.filename or "file", f.file) for f in form.getlist("files") if isinstance(f, StarletteUpload)]
        if sum(f.size or 0 for f in form.getlist("files") if isinstance(f, StarletteUpload)) > limit:
            raise Invalid(f"Upload at most {get_settings().imaging_max_upload_mb} MB at a time.", "files")
        result = await run_in_threadpool(ImagingService(db, current).upload, item_id, files)
    finally:
        await form.close()
    return UploadResultOut(studies=[_study(s) for s in result.studies], stored=result.stored, already_stored=result.already_stored,
                           rejected=result.rejected, messages=result.messages)


# ---------- DICOMweb proxy (for the viewer) ----------

ORTHANC_BASE = re.compile(rb"https?://[^\"\s/]+(?:/[^\"\s]*?)?/dicom-web/")
STUDY_UID_TAG = "0020000D"
UID = re.compile(r"^[0-9.]{1,64}$")


def _study_uid(entry: dict) -> str:
    values = (entry.get(STUDY_UID_TAG) or {}).get("Value") or [""]
    return str(values[0])


async def _close(resp: httpx.Response) -> None:
    await resp.aclose()


@dicomweb.get("/{path:path}")
async def dicom_web(path: str, request: Request, db: Session = DB, current: CurrentUser = Depends(client_user)):
    """QIDO-RS and WADO-RS reads, passed to the image server with its credentials, for this client's studies only:
    searches are filtered to them, and anything under another study's UID is "not found"."""
    parts = [p for p in path.split("/") if p]
    svc = ImagingService(db, current)
    only: set[str] | None = None
    if len(parts) >= 2 and parts[0] == "studies":
        if not UID.match(parts[1]) or not svc.owns(parts[1]):
            raise NotFound("We couldn't find that study.")
    elif parts in (["studies"], ["series"], ["instances"]):
        only = svc.own_uids()
        if not only:
            return JSONResponse([], media_type="application/dicom+json")
    else:
        raise NotFound("We couldn't find that.")
    db.close()  # nothing more from the database; don't hold a connection while images stream

    client = async_client()
    upstream = client.build_request("GET", "/dicom-web/" + "/".join(parts), params=list(request.query_params.multi_items()),
                                    headers={"Accept": request.headers.get("accept", "application/dicom+json"), "Accept-Encoding": "identity"})
    try:
        resp = await client.send(upstream, stream=True)
    except httpx.TransportError as exc:
        raise ImageServerUnavailable() from exc
    if resp.status_code in (401, 403) or resp.status_code >= 500:
        await _close(resp)
        raise ImageServerUnavailable()
    if resp.status_code == 404:
        await _close(resp)
        raise NotFound("We couldn't find that.")
    ctype = resp.headers.get("content-type", "application/octet-stream")
    if "json" in ctype or only is not None:
        body = await resp.aread()
        await _close(resp)
        if only is not None and body.strip():
            entries = json.loads(body)
            body = json.dumps([e for e in entries if _study_uid(e) in only]).encode()
        # Links inside the answer point at the image server; point them at this proxy instead.
        base = f"{request.url.scheme}://{request.headers.get('host', '')}/api/dicom-web/".encode()
        return Response(ORTHANC_BASE.sub(base, body), status_code=resp.status_code, media_type=ctype)
    headers = {k: v for k, v in resp.headers.items() if k.lower() in ("content-length", "content-disposition")}
    return StreamingResponse(resp.aiter_bytes(), status_code=resp.status_code, media_type=ctype, headers=headers,
                             background=BackgroundTask(_close, resp))


# ---------- the viewer (OHIF), on this address so it shares the sign-in ----------

VIEWER_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval' {hashes}",
    "worker-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self' data: blob:",
    "frame-ancestors 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
])
INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)
MAIN_BUNDLE = re.compile(r"^app\.bundle\.[0-9a-f]+\.js$")
_bundles: dict[str, bytes] = {}  # the main bundle, moved under /viewer/ (its name has a content hash, so it never goes stale)


def _viewer_html(html: str) -> tuple[str, str]:
    """OHIF's page is built for the site root: move it under /viewer/, and allow exactly its own inline scripts."""
    html = html.replace('window.PUBLIC_URL="/"', 'window.PUBLIC_URL="/viewer/"')
    html = re.sub(r'(href|src|content)="/(?!/)', r'\1="/viewer/', html)
    hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()}'" for s in INLINE_SCRIPT.findall(html))
    return html, VIEWER_CSP.format(hashes=hashes)


@viewer.get("/viewer")
@viewer.get("/viewer/{path:path}")
async def viewer_proxy(request: Request, path: str = "", db: Session = DB):
    current = resolve_current(request, db)
    db.close()
    if current is None or current.is_platform or current.user.must_change_password or (current.tenant and not current.tenant.is_active):
        if "." in path.rsplit("/", 1)[-1]:
            return JSONResponse({"message": "Sign in to continue."}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    client = shared_async_client(get_settings().ohif_url)
    try:
        resp = await client.send(client.build_request("GET", "/" + path, params=list(request.query_params.multi_items()),
                                                      headers={"Accept-Encoding": "gzip"}), stream=True)
    except httpx.TransportError:
        return Response("<!doctype html><title>Image viewer unavailable</title><p style='font-family:sans-serif;padding:24px'>"
                        "The image viewer isn't available right now. Please try again in a few minutes.</p>",
                        status_code=503, media_type="text/html")
    ctype = resp.headers.get("content-type", "application/octet-stream")
    if ctype.startswith("text/css") and resp.status_code == 200:
        await resp.aread()
        await _close(resp)
        css = resp.content.replace(b"url(/", b"url(/viewer/")  # fonts are linked from the site root
        return Response(css, media_type=ctype, headers={"Cache-Control": "private, max-age=86400"})
    if MAIN_BUNDLE.match(path) and resp.status_code == 200:
        # The build loads its other parts from "/"; under /viewer/ they must come from "/viewer/".
        if path not in _bundles:
            await resp.aread()
            body = resp.content.replace(b'__webpack_require__.p = "/";', b'__webpack_require__.p = "/viewer/";', 1)
            _bundles.clear()
            _bundles[path] = gzip.compress(body, compresslevel=6)
        await _close(resp)
        return Response(_bundles[path], media_type=ctype, headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=86400"})
    if ctype.startswith("text/html"):
        await resp.aread()
        await _close(resp)
        html, csp = _viewer_html(resp.text)
        return Response(html, status_code=resp.status_code, media_type="text/html", headers={"Content-Security-Policy": csp,
                                                                                              "X-Frame-Options": "SAMEORIGIN"})
    headers = {k: v for k, v in resp.headers.items() if k.lower() in ("content-length", "content-encoding", "etag", "last-modified")}
    headers["Cache-Control"] = "private, max-age=3600"
    return StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, media_type=ctype, headers=headers,
                             background=BackgroundTask(_close, resp))


# ---------- WhatsApp status webhook (called by Meta) ----------

@webhooks.get("/whatsapp")
def whatsapp_verify(mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                    challenge: str = Query("", alias="hub.challenge", max_length=200)):
    expected = get_settings().whatsapp_verify_token
    if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
        return PlainTextResponse(challenge)
    raise Forbidden("Not allowed.")


@webhooks.post("/whatsapp")
async def whatsapp_status(request: Request):
    body = await request.body()
    if not signature_ok(body, request.headers.get("x-hub-signature-256", "")):
        raise Forbidden("Not allowed.")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise Invalid("Not JSON.") from exc

    def apply() -> int:
        with scoped_session(platform=True) as db, db.begin():  # the message ids say whose deliveries these are
            return apply_statuses(db, payload)
    updated = await run_in_threadpool(apply)
    return {"updated": updated}


for _r in (reports, imaging, dicomweb, viewer, webhooks, public):
    router.include_router(_r)
