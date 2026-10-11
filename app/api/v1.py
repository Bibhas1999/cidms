"""The integration API, version 1, at https://<centre>.<domain>/api/v1 (docs at /api/v1/docs).

Other systems (a hospital's HIS, a referring doctor's EMR, a PACS) read the centre's medical data with an API
key: `Authorization: Bearer sdms_live_…` (or `X-API-Key: sdms_live_…`). No cookies, no CSRF. A key only works
at its own centre's address, only from its allowed IP addresses, only for its scopes, and never reaches
anything financial: the shapes in app/schemas_api_v1.py have no prices, amounts, totals, payments or dues.

Lists return {data, next_cursor}; pass next_cursor back as ?cursor= for the next page. Errors look like the
rest of the app's: {message, field?, request_id}. Every call is logged (key, method, path, status, time, IP).
"""

import base64
import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select, func, or_, select, tuple_
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.db import DB, is_transient
from app.core.errors import DomainError, Forbidden, Invalid, NotFound
from app.core.logging import client_ip, request_id
from app.models import (
    Department,
    ImagingStudy,
    Invoice,
    InvoiceItem,
    LabTest,
    Patient,
    ReferringDoctor,
    TestReport,
    TestType,
)
from app.repositories.common import contains
from app.schemas_api_v1 import (
    CatalogueTestV1,
    DoctorV1,
    ItemOut,
    ListOut,
    NamedRef,
    OrderV1,
    PatientRef,
    PatientV1,
    ReportV1,
    Signer,
    StudyV1,
    WhoAmIV1,
)
from app.services.integrations import SCOPES, ApiCaller, RateLimited, authenticate, rate_limiter, record_call
from app.services.integrations import TZ as LOCAL_TZ

SIGNED = ("signed", "amended")
ORDER_STATUSES = ("billed", "scanned", "reported", "delivered", "cancelled")
DOC_PATHS = {"/docs", "/openapi.json"}

DESCRIPTION = """Read your centre's **medical** data from other systems: patients, the test catalogue, ordered tests
and their progress, signed reports (with PDFs), imaging studies and referring doctors.

**Financial data (bills, prices, payments, dues) is never available through this API.**

### Authentication
Create a key in Supreme DMS under *Settings → API & integrations*, then send it on every call:

    Authorization: Bearer sdms_live_…

(or `X-API-Key: sdms_live_…`). A key works only at your centre's own address, only for the scopes it was given,
and only from its allowed IP addresses if any were set.

### Paging
Lists return `{"data": [...], "next_cursor": "..."}`, oldest change first. Pass `next_cursor` back as
`?cursor=` until it is `null`. To keep another system in step, remember the last `updated_at` you saw and ask
for `?updated_since=` that time next time.

### Limits and errors
Up to 600 calls a minute per key; beyond that the answer is `429` with a `Retry-After` header (seconds).
Errors look like `{"message": "...", "field": "...", "request_id": "..."}`: quote the request ID to support.
"""

TAGS = [{"name": "about", "description": "Check your key."}] + [
    {"name": s.split(":")[0], "description": f"Needs the `{s}` scope. {d}"} for s, d in SCOPES.items()]

bearer = HTTPBearer(auto_error=False, scheme_name="ApiKey", bearerFormat="sdms_live_…",
                    description="Your API key: `Authorization: Bearer sdms_live_…`")
header_key = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="XApiKey",
                          description="Or send the key in an X-API-Key header.")


# ---------- who is calling ----------

def api_caller(request: Request, db: Session = DB, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
               x_api_key: str | None = Depends(header_key)) -> ApiCaller:
    raw = creds.credentials if creds else (x_api_key or "")
    caller = authenticate(db, getattr(request.state, "tenant", None), raw, client_ip(request))
    request.state.api_key_id = caller.key_id
    rate_limiter.hit(caller.key_id)
    return caller


def scope(name: str):
    def dep(caller: ApiCaller = Depends(api_caller)) -> ApiCaller:
        if name not in caller.scopes:
            raise Forbidden(f"This API key doesn't have the {name} scope. An owner or centre admin can make a key that does.")
        return caller
    return dep


# ---------- paging ----------

def encode_cursor(when: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([when.isoformat(), str(row_id)]).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        when, row_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        return datetime.fromisoformat(when), uuid.UUID(row_id)
    except (ValueError, TypeError):
        raise Invalid("That cursor isn't valid. Use next_cursor from the previous page as it was given.", "cursor") from None


def page_of(db: Session, q: Select, sort_col, id_col, cursor: str | None, limit: int) -> tuple[list, str | None]:
    if cursor:
        when, row_id = decode_cursor(cursor)
        q = q.where(tuple_(sort_col, id_col) > tuple_(when, row_id))
    rows = db.execute(q.order_by(sort_col, id_col).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, encode_cursor(rows[-1].sort_at, rows[-1].row_id) if more and rows else None


def local_start(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), LOCAL_TZ)


Limit = Query(50, ge=1, le=200, description="How many to return (1–200).")
Cursor = Query(None, max_length=200, description="next_cursor from the previous page.")
UpdatedSince = Query(None, description="Only records changed at or after this time (ISO 8601, e.g. 2026-10-01T00:00:00Z).")


# ---------- the app ----------

def _error(status: int, message: str, field: str | None = None, headers: dict | None = None) -> JSONResponse:
    body: dict = {"message": message, "request_id": request_id.get()}
    if field:
        body["field"] = field
    return JSONResponse(body, status_code=status, headers=headers)


class ApiCallLog(BaseHTTPMiddleware):
    """No caching anywhere, and one log row per call (never the body or the query string)."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            return response
        finally:
            tenant = getattr(request.state, "tenant", None)
            path = request.url.path
            if tenant is not None and request.scope.get("path", path) not in DOC_PATHS and not path.endswith(tuple(DOC_PATHS)):
                try:
                    await run_in_threadpool(record_call, tenant.id, getattr(request.state, "api_key_id", None), request.method, path,
                                            status, int((time.perf_counter() - start) * 1000), client_ip(request), request_id.get())
                except Exception:  # the log must never turn an answer into an error
                    logging.getLogger("app").exception("Couldn't log an API call")


def create_v1_app() -> FastAPI:
    v1 = FastAPI(title="Supreme DMS Integration API", version="1.0", description=DESCRIPTION, docs_url=None, redoc_url=None,
                 openapi_url="/openapi.json", openapi_tags=TAGS)
    v1.add_middleware(ApiCallLog)

    @v1.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
        if exc.status == 401:
            headers = {"WWW-Authenticate": "Bearer"}
        return _error(exc.status, exc.message, exc.field, headers)

    @v1.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {"loc": (), "msg": "That request wasn't valid."}
        field = ".".join(str(p) for p in first["loc"] if p not in ("query", "path", "body")) or None
        return _error(422, str(first["msg"]).removeprefix("Value error, "), field)

    @v1.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        messages = {404: "We couldn't find that.", 405: "That isn't allowed here."}
        return _error(exc.status_code, messages.get(exc.status_code, str(exc.detail)))

    @v1.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        if is_transient(exc):
            return _error(503, "Supreme DMS is busy for a moment. Please try again.", headers={"Retry-After": "2"})
        logging.getLogger("app").exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "Something went wrong on our side. It's been logged; please try again.")

    @v1.get("/docs", include_in_schema=False)
    def docs(request: Request):
        root = request.scope.get("root_path", "").rstrip("/")
        page = get_swagger_ui_html(openapi_url=f"{root}/openapi.json", title="Supreme DMS Integration API")
        page.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        return page

    for r in (about_routes, patient_routes, test_routes, order_routes, report_routes, study_routes, doctor_routes):
        r(v1)
    return v1


# ---------- endpoints ----------

def about_routes(v1: FastAPI) -> None:
    @v1.get("/me", response_model=ItemOut[WhoAmIV1], tags=["about"], summary="The key you're calling with")
    def whoami(caller: ApiCaller = Depends(api_caller)):
        return {"data": WhoAmIV1(centre=caller.tenant.name, key_name=caller.name, key_prefix=caller.prefix,
                                 scopes=sorted(caller.scopes), expires_at=caller.expires_at)}


def _patient(p: Patient) -> PatientV1:
    return PatientV1(id=p.id, patient_no=p.patient_no, name=p.name, guardian_name=p.guardian_name, age_years=p.age_years,
                     date_of_birth=p.date_of_birth, gender=p.gender, mobile=p.mobile, email=p.email, address=p.address,
                     created_at=p.created_at, updated_at=p.updated_at)


def patient_routes(v1: FastAPI) -> None:
    need = scope("patients:read")

    @v1.get("/patients", response_model=ListOut[PatientV1], tags=["patients"], summary="Patients")
    def patients(search: str = Query("", max_length=100, description="Part of the name, the patient number, or the mobile."),
                 updated_since: datetime | None = UpdatedSince, cursor: str | None = Cursor, limit: int = Limit,
                 db: Session = DB, caller: ApiCaller = Depends(need)):
        q = select(Patient, Patient.updated_at.label("sort_at"), Patient.id.label("row_id")).where(Patient.tenant_id == caller.tenant.id)
        s = search.strip()
        if s:
            conds = [func.lower(Patient.name).like(contains(s), escape="\\"), func.lower(Patient.patient_no) == s.lower()]
            digits = "".join(ch for ch in s if ch.isdigit())
            if len(digits) >= 4:
                conds.append(Patient.mobile.like(f"%{digits}%"))
            q = q.where(or_(*conds))
        if updated_since:
            q = q.where(Patient.updated_at >= updated_since)
        rows, nxt = page_of(db, q, Patient.updated_at, Patient.id, cursor, limit)
        return {"data": [_patient(r[0]) for r in rows], "next_cursor": nxt}

    @v1.get("/patients/{patient_id}", response_model=ItemOut[PatientV1], tags=["patients"], summary="One patient")
    def patient(patient_id: uuid.UUID, db: Session = DB, caller: ApiCaller = Depends(need)):
        p = db.scalar(select(Patient).where(Patient.tenant_id == caller.tenant.id, Patient.id == patient_id))
        if p is None:
            raise NotFound("We couldn't find that patient.")
        return {"data": _patient(p)}


def test_routes(v1: FastAPI) -> None:
    @v1.get("/tests", response_model=ListOut[CatalogueTestV1], tags=["tests"], summary="The test catalogue (no prices)")
    def tests(active: bool | None = Query(None, description="true: only tests offered now; false: only switched-off ones."),
              updated_since: datetime | None = UpdatedSince, cursor: str | None = Cursor, limit: int = Limit,
              db: Session = DB, caller: ApiCaller = Depends(scope("tests:read"))):
        # Columns picked one by one: the price is never read.
        q = (select(LabTest.id, LabTest.code, LabTest.name, LabTest.department_id, Department.name.label("department_name"),
                    func.coalesce(TestType.name, "").label("modality"), func.coalesce(TestType.is_imaging, False).label("is_imaging"),
                    LabTest.is_active, LabTest.updated_at, LabTest.updated_at.label("sort_at"), LabTest.id.label("row_id"))
             .join(Department, Department.id == LabTest.department_id).outerjoin(TestType, TestType.id == LabTest.test_type_id)
             .where(LabTest.tenant_id == caller.tenant.id))
        if active is not None:
            q = q.where(LabTest.is_active.is_(active))
        if updated_since:
            q = q.where(LabTest.updated_at >= updated_since)
        rows, nxt = page_of(db, q, LabTest.updated_at, LabTest.id, cursor, limit)
        return {"data": [CatalogueTestV1(id=r.id, code=r.code, name=r.name, department=NamedRef(id=r.department_id, name=r.department_name),
                                         modality=r.modality, is_imaging=r.is_imaging, is_active=r.is_active, updated_at=r.updated_at)
                         for r in rows], "next_cursor": nxt}


# Orders: one row per test on a bill. Only these columns are ever read, so no amount can reach the answer.
ORDER_UPDATED = func.greatest(Invoice.updated_at, func.coalesce(InvoiceItem.status_changed_at, Invoice.updated_at))
SIGNED_REPORT = (select(TestReport.id).where(TestReport.invoice_item_id == InvoiceItem.id, TestReport.status.in_(SIGNED))
                 .correlate(InvoiceItem).scalar_subquery())


def _order_query(tenant_id: uuid.UUID) -> Select:
    return (select(InvoiceItem.id, InvoiceItem.invoice_id, Invoice.invoice_no, Invoice.bill_date, Invoice.patient_id,
                   func.coalesce(Patient.patient_no, "").label("patient_no"), Invoice.patient_name, Invoice.patient_age,
                   Invoice.patient_gender, InvoiceItem.test_id, InvoiceItem.test_name, InvoiceItem.department_id,
                   InvoiceItem.department_name, InvoiceItem.is_imaging, InvoiceItem.accession_no, InvoiceItem.status,
                   Invoice.status.label("bill_status"), InvoiceItem.status_changed_at, Invoice.referring_doctor_id,
                   Invoice.referring_doctor_name, SIGNED_REPORT.label("report_id"), Invoice.created_at,
                   ORDER_UPDATED.label("sort_at"), InvoiceItem.id.label("row_id"))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id).outerjoin(Patient, Patient.id == Invoice.patient_id)
            .where(InvoiceItem.tenant_id == tenant_id))


def _order(r) -> OrderV1:
    cancelled = r.bill_status == "cancelled" or r.status == "cancelled"
    return OrderV1(
        id=r.id, bill_id=r.invoice_id, bill_no=r.invoice_no, ordered_on=r.bill_date,
        patient=PatientRef(id=r.patient_id, patient_no=r.patient_no, name=r.patient_name, age=r.patient_age, gender=r.patient_gender),
        test=NamedRef(id=r.test_id, name=r.test_name),
        department=NamedRef(id=r.department_id, name=r.department_name) if r.department_name else None,
        is_imaging=r.is_imaging, accession_no=r.accession_no, status="cancelled" if cancelled else r.status,
        status_changed_at=r.status_changed_at,
        referring_doctor=NamedRef(id=r.referring_doctor_id, name=r.referring_doctor_name) if r.referring_doctor_name else None,
        report_id=r.report_id, created_at=r.created_at, updated_at=r.sort_at,
    )


def order_routes(v1: FastAPI) -> None:
    need = scope("orders:read")

    @v1.get("/orders", response_model=ListOut[OrderV1], tags=["orders"], summary="Ordered tests and their progress (no amounts)")
    def orders(date_from: date | None = Query(None, alias="from", description="Ordered on or after this date (YYYY-MM-DD)."),
               date_to: date | None = Query(None, alias="to", description="Ordered on or before this date."),
               status: str | None = Query(None, description="billed, scanned, reported, delivered or cancelled."),
               patient_id: uuid.UUID | None = None, updated_since: datetime | None = UpdatedSince, cursor: str | None = Cursor,
               limit: int = Limit, db: Session = DB, caller: ApiCaller = Depends(need)):
        q = _order_query(caller.tenant.id)
        if date_from:
            q = q.where(Invoice.bill_date >= date_from)
        if date_to:
            q = q.where(Invoice.bill_date <= date_to)
        if status:
            if status not in ORDER_STATUSES:
                raise Invalid(f"Use one of: {', '.join(ORDER_STATUSES)}.", "status")
            if status == "cancelled":
                q = q.where(or_(Invoice.status == "cancelled", InvoiceItem.status == "cancelled"))
            else:
                q = q.where(InvoiceItem.status == status, Invoice.status != "cancelled")
        if patient_id:
            q = q.where(Invoice.patient_id == patient_id)
        if updated_since:
            q = q.where(updated_since <= ORDER_UPDATED)
        rows, nxt = page_of(db, q, ORDER_UPDATED, InvoiceItem.id, cursor, limit)
        return {"data": [_order(r) for r in rows], "next_cursor": nxt}

    @v1.get("/orders/{order_id}", response_model=ItemOut[OrderV1], tags=["orders"], summary="One ordered test")
    def order(order_id: uuid.UUID, db: Session = DB, caller: ApiCaller = Depends(need)):
        r = db.execute(_order_query(caller.tenant.id).where(InvoiceItem.id == order_id)).first()
        if r is None:
            raise NotFound("We couldn't find that order.")
        return {"data": _order(r)}


def _report_query(tenant_id: uuid.UUID) -> Select:
    return (select(TestReport.id, TestReport.invoice_item_id, Invoice.patient_id, func.coalesce(Patient.patient_no, "").label("patient_no"),
                   Invoice.patient_name, Invoice.patient_age, Invoice.patient_gender, InvoiceItem.test_name, InvoiceItem.department_name,
                   InvoiceItem.accession_no, TestReport.status, TestReport.title, TestReport.technique, TestReport.modality,
                   TestReport.findings, TestReport.impression, TestReport.signer_name, TestReport.signer_degree,
                   TestReport.signer_registration_no, TestReport.signed_at, TestReport.version, TestReport.amendments,
                   TestReport.amend_reason, TestReport.created_at, TestReport.updated_at,
                   TestReport.updated_at.label("sort_at"), TestReport.id.label("row_id"))
            .join(InvoiceItem, InvoiceItem.id == TestReport.invoice_item_id).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .outerjoin(Patient, Patient.id == Invoice.patient_id)
            .where(TestReport.tenant_id == tenant_id, TestReport.status.in_(SIGNED)))


def _report(r, root: str) -> ReportV1:
    return ReportV1(
        id=r.id, order_id=r.invoice_item_id,
        patient=PatientRef(id=r.patient_id, patient_no=r.patient_no, name=r.patient_name, age=r.patient_age, gender=r.patient_gender),
        test_name=r.test_name, department_name=r.department_name, accession_no=r.accession_no, status=r.status, title=r.title,
        technique=r.technique, modality=r.modality, findings_html=r.findings, impression_html=r.impression,
        signer=Signer(name=r.signer_name, degree=r.signer_degree, registration_no=r.signer_registration_no), signed_at=r.signed_at,
        version=r.version, amended=r.status == "amended" or r.amendments > 0, amend_reason=r.amend_reason,
        pdf_url=f"{root}/reports/{r.id}/pdf", created_at=r.created_at, updated_at=r.updated_at,
    )


def report_routes(v1: FastAPI) -> None:
    need = scope("reports:read")

    @v1.get("/reports", response_model=ListOut[ReportV1], tags=["reports"], summary="Signed and amended reports")
    def reports(request: Request,
                date_from: date | None = Query(None, alias="from", description="Signed on or after this date (YYYY-MM-DD, India time)."),
                date_to: date | None = Query(None, alias="to", description="Signed on or before this date."),
                status: str | None = Query(None, description="signed or amended."),
                patient_id: uuid.UUID | None = None, updated_since: datetime | None = UpdatedSince, cursor: str | None = Cursor,
                limit: int = Limit, db: Session = DB, caller: ApiCaller = Depends(need)):
        q = _report_query(caller.tenant.id)
        if date_from:
            q = q.where(TestReport.signed_at >= local_start(date_from))
        if date_to:
            q = q.where(TestReport.signed_at < local_start(date_to + timedelta(days=1)))
        if status:
            if status not in SIGNED:
                raise Invalid("Use signed or amended. Only signed reports are available through the API.", "status")
            q = q.where(TestReport.status == status)
        if patient_id:
            q = q.where(Invoice.patient_id == patient_id)
        if updated_since:
            q = q.where(TestReport.updated_at >= updated_since)
        rows, nxt = page_of(db, q, TestReport.updated_at, TestReport.id, cursor, limit)
        root = request.scope.get("root_path", "")
        return {"data": [_report(r, root) for r in rows], "next_cursor": nxt}

    @v1.get("/reports/{report_id}", response_model=ItemOut[ReportV1], tags=["reports"], summary="One signed report")
    def report(report_id: uuid.UUID, request: Request, db: Session = DB, caller: ApiCaller = Depends(need)):
        r = db.execute(_report_query(caller.tenant.id).where(TestReport.id == report_id)).first()
        if r is None:
            raise NotFound("We couldn't find a signed report with that ID.")
        return {"data": _report(r, request.scope.get("root_path", ""))}

    @v1.get("/reports/{report_id}/pdf", tags=["reports"], summary="A signed report as a PDF",
            response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
    def report_pdf(report_id: uuid.UUID, db: Session = DB, caller: ApiCaller = Depends(need)):
        from app.services.test_reports import build_pdf
        rep = db.scalar(select(TestReport).where(TestReport.tenant_id == caller.tenant.id, TestReport.id == report_id,
                                                 TestReport.status.in_(SIGNED)))
        if rep is None:
            raise NotFound("We couldn't find a signed report with that ID.")
        item = db.get(InvoiceItem, rep.invoice_item_id)
        invoice = db.get(Invoice, item.invoice_id)
        content, filename = build_pdf(db, caller.tenant.id, rep, item, invoice)
        return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def study_routes(v1: FastAPI) -> None:
    @v1.get("/studies", response_model=ListOut[StudyV1], tags=["images"], summary="Imaging studies")
    def studies(order_id: uuid.UUID | None = Query(None, description="Only the studies for this ordered test."),
                updated_since: datetime | None = UpdatedSince, cursor: str | None = Cursor, limit: int = Limit,
                db: Session = DB, caller: ApiCaller = Depends(scope("images:read"))):
        s = ImagingStudy
        q = (select(s.id, s.invoice_item_id, s.study_instance_uid, s.modality, s.description, s.series_count, s.instance_count,
                    s.created_at, s.updated_at, s.updated_at.label("sort_at"), s.id.label("row_id")).where(s.tenant_id == caller.tenant.id))
        if order_id:
            q = q.where(s.invoice_item_id == order_id)
        if updated_since:
            q = q.where(s.updated_at >= updated_since)
        rows, nxt = page_of(db, q, s.updated_at, s.id, cursor, limit)
        return {"data": [StudyV1(id=r.id, order_id=r.invoice_item_id, study_instance_uid=r.study_instance_uid, modality=r.modality,
                                 description=r.description, series_count=r.series_count, instance_count=r.instance_count,
                                 created_at=r.created_at, updated_at=r.updated_at) for r in rows], "next_cursor": nxt}


def doctor_routes(v1: FastAPI) -> None:
    @v1.get("/doctors", response_model=ListOut[DoctorV1], tags=["doctors"], summary="Referring doctors")
    def doctors(active: bool | None = Query(None, description="true: only doctors suggested on new orders."),
                cursor: str | None = Cursor, limit: int = Limit, db: Session = DB, caller: ApiCaller = Depends(scope("doctors:read"))):
        d = ReferringDoctor
        q = (select(d.id, d.name, d.qualification, d.is_active, d.created_at, d.created_at.label("sort_at"), d.id.label("row_id"))
             .where(d.tenant_id == caller.tenant.id))
        if active is not None:
            q = q.where(d.is_active.is_(active))
        rows, nxt = page_of(db, q, d.created_at, d.id, cursor, limit)
        return {"data": [DoctorV1(id=r.id, name=r.name, qualification=r.qualification, is_active=r.is_active, created_at=r.created_at)
                         for r in rows], "next_cursor": nxt}

