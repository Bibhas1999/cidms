"""Billing API: catalogue, patients, bills, payments, worklist and the day's summary."""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import Paging, client_user, paging
from app.core.db import DB
from app.core.errors import Forbidden, Invalid, NotFound
from app.core.idempotency import run_once
from app.core.logging import client_ip
from app.core.money import local_today
from app.core.security import CurrentUser, require
from app.models import Patient, ReferringDoctor, TenantSettings
from app.schemas import Page
from app.schemas_billing import (
    BillIn,
    BillItemsStatusIn,
    BillOut,
    BillPartiesIn,
    BillPage,
    BillShareOut,
    BillUpdateIn,
    DaySummaryOut,
    DepartmentIn,
    DepartmentOut,
    DeskSummaryOut,
    DoctorIn,
    DoctorOut,
    ItemStatusIn,
    LabTestIn,
    LabTestOut,
    OverviewOut,
    PatientIn,
    PatientOut,
    PaymentIn,
    PublicBillCentreOut,
    PublicBillCheckIn,
    PublicBillInfoOut,
    PublicBillOut,
    ReasonIn,
    RefundIn,
    TestTypeIn,
    TestTypeOut,
    WorklistRowOut,
)
from app.services import bill_links
from app.services.audit import AuditService
from app.services.billing import BillFilters, BillingService, OverviewService, default_worklist_window
from app.services.catalogue import CatalogueService
from app.services.patients import PatientService

router = APIRouter(prefix="/api", tags=["billing"])
manage_catalogue = require("catalogue.manage")


def base_url(request: Request) -> str:
    """This centre's address as the browser used it (for the patient's link)."""
    return f"{request.url.scheme}://{request.headers.get('host', '')}"


# ---------- catalogue (everyone in the centre reads it; catalogue.manage changes it) ----------

@router.get("/departments", response_model=list[DepartmentOut])
def departments(db: Session = DB, current: CurrentUser = Depends(client_user)):
    return CatalogueService(db, current).departments()


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def add_department(data: DepartmentIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_department(data)


@router.put("/departments/{dept_id}", response_model=DepartmentOut)
def edit_department(dept_id: uuid.UUID, data: DepartmentIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_department(data, dept_id)


@router.get("/test-types", response_model=list[TestTypeOut])
def test_types(db: Session = DB, current: CurrentUser = Depends(client_user)):
    return CatalogueService(db, current).test_types()


@router.post("/test-types", response_model=TestTypeOut, status_code=status.HTTP_201_CREATED)
def add_test_type(data: TestTypeIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_test_type(data)


@router.put("/test-types/{type_id}", response_model=TestTypeOut)
def edit_test_type(type_id: uuid.UUID, data: TestTypeIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_test_type(data, type_id)


@router.get("/tests", response_model=Page[LabTestOut])
def tests(search: str = Query("", max_length=100), department_id: uuid.UUID | None = None, active: bool | None = None,
          p: Paging = Depends(paging), db: Session = DB, current: CurrentUser = Depends(client_user)):
    items, total = CatalogueService(db, current).tests(search, department_id, active, p.page, p.size)
    return Page(items=items, total=total, page=p.page, size=p.size)


@router.post("/tests", response_model=LabTestOut, status_code=status.HTTP_201_CREATED)
def add_test(data: LabTestIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_test(data)


@router.put("/tests/{test_id}", response_model=LabTestOut)
def edit_test(test_id: uuid.UUID, data: LabTestIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_test(data, test_id)


@router.get("/doctors", response_model=Page[DoctorOut])
def doctors(search: str = Query("", max_length=100), active: bool | None = None, p: Paging = Depends(paging),
            db: Session = DB, current: CurrentUser = Depends(client_user)):
    items, total = CatalogueService(db, current).doctors(search, active, p.page, p.size)
    return Page(items=items, total=total, page=p.page, size=p.size)


@router.post("/doctors", response_model=DoctorOut, status_code=status.HTTP_201_CREATED)
def add_doctor(data: DoctorIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    """Adding a referring doctor is front-desk work too: anyone who bills (or manages the catalogue) may."""
    if not (current.can("catalogue.manage") or current.can("billing.create")):
        raise Forbidden("You don't have permission to add doctors.")
    return CatalogueService(db, current).save_doctor(data)


@router.put("/doctors/{doctor_id}", response_model=DoctorOut)
def edit_doctor(doctor_id: uuid.UUID, data: DoctorIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_doctor(data, doctor_id)


@router.get("/doctors/{doctor_id}", response_model=DoctorOut)
def doctor(doctor_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    found = db.scalar(select(ReferringDoctor).where(ReferringDoctor.tenant_id == current.user.tenant_id,
                                                   ReferringDoctor.id == doctor_id))
    if found is None:
        raise NotFound("That doctor or hospital isn't in this centre's list.")
    return found


# ---------- patients ----------

@router.get("/patients", response_model=Page[PatientOut])
def patients(search: str = Query("", max_length=100), p: Paging = Depends(paging), db: Session = DB,
             current: CurrentUser = Depends(client_user)):
    items, total = PatientService(db, current).page(search, p.page, p.size)
    return Page(items=items, total=total, page=p.page, size=p.size)


@router.get("/patients/same-mobile", response_model=list[PatientOut])
def same_mobile(mobile: str = Query(max_length=20), exclude: uuid.UUID | None = None, db: Session = DB,
                current: CurrentUser = Depends(client_user)):
    return PatientService(db, current).same_mobile(mobile, exclude)


@router.post("/patients", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def add_patient(data: PatientIn, db: Session = DB, current: CurrentUser = Depends(require("patients.manage"))):
    return PatientService(db, current).create(data)


@router.get("/patients/{patient_id}", response_model=PatientOut)
def patient(patient_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    found = PatientService(db, current).get(patient_id)
    AuditService(db).viewed(current.user.tenant_id, current.id, "patient", found.id, {"patient_no": found.patient_no})
    return found


@router.put("/patients/{patient_id}", response_model=PatientOut)
def edit_patient(patient_id: uuid.UUID, data: PatientIn, db: Session = DB, current: CurrentUser = Depends(require("patients.manage"))):
    return PatientService(db, current).update(patient_id, data)


# ---------- bills ----------

def bill_filters(search: str = Query("", max_length=100), date_from: date | None = Query(None, alias="from"),
                 date_to: date | None = Query(None, alias="to"),
                 status_: str | None = Query(None, alias="status", pattern="^(confirmed|on_hold|cancelled)$"),
                 payment: str = Query("", pattern="^(|due|paid|part|unpaid)$"),
                 due: bool = False, paid: bool = False,
                 mode: str = Query("", pattern="^(|cash|upi|card|bank|other)$"),
                 doctor_id: uuid.UUID | None = None, self_referred: bool = False, patient_id: uuid.UUID | None = None,
                 department_id: uuid.UUID | None = None, test_id: uuid.UUID | None = None, created_by: uuid.UUID | None = None,
                 min_total: Decimal | None = Query(None, ge=0), max_total: Decimal | None = Query(None, ge=0),
                 discount: str = Query("", pattern="^(|yes|no)$"),
                 report: str = Query("", pattern="^(|pending|ready|delivered)$"),
                 sort: str = Query("newest", pattern="^(newest|oldest)$")) -> BillFilters:
    """The bills list's filters from the query string (also used by exports, so they match what's on screen)."""
    return BillFilters(search=search, date_from=date_from, date_to=date_to, status=status_,
                       payment=payment or ("due" if due else "paid" if paid else ""), mode=mode, doctor_id=doctor_id,
                       self_referred=self_referred, patient_id=patient_id, department_id=department_id, test_id=test_id,
                       created_by=created_by, min_total=min_total, max_total=max_total, discount=discount, report=report,
                       oldest_first=sort == "oldest")


@router.get("/bills", response_model=BillPage)
def bills(f: BillFilters = Depends(bill_filters), p: Paging = Depends(paging), db: Session = DB,
          current: CurrentUser = Depends(client_user)):
    items, total, sums = BillingService(db, current).page(f, p.page, p.size)
    return BillPage(items=items, total=total, page=p.page, size=p.size, sums=sums)


@router.post("/bills", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def create_bill(data: BillIn, request: Request, db: Session = DB, current: CurrentUser = Depends(require("billing.create"))):
    svc = BillingService(db, current)
    return run_once(request, db, current, "bill.create", lambda: BillOut.model_validate(svc.create(data)), status.HTTP_201_CREATED)


@router.get("/bills/next-number")
def next_number(db: Session = DB, current: CurrentUser = Depends(client_user)):
    return {"invoice_no": BillingService(db, current).next_invoice_no(), "date": local_today()}


@router.get("/bills/{invoice_id}", response_model=BillOut)
def bill(invoice_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    invoice = BillingService(db, current).get(invoice_id)
    AuditService(db).viewed(current.user.tenant_id, current.id, "invoice", invoice.id, {"invoice_no": invoice.invoice_no})
    return invoice


@router.put("/bills/{invoice_id}/parties", response_model=BillOut)
def update_bill_parties(invoice_id: uuid.UUID, data: BillPartiesIn, db: Session = DB,
                        current: CurrentUser = Depends(require("billing.edit"))):
    return BillingService(db, current).update_parties(invoice_id, data)


@router.put("/bills/{invoice_id}", response_model=BillOut)
def edit_bill(invoice_id: uuid.UUID, data: BillUpdateIn, db: Session = DB, current: CurrentUser = Depends(require("billing.edit"))):
    return BillingService(db, current).update(invoice_id, data)


def _share_out(share, request: Request) -> BillShareOut:
    if share is None:
        return BillShareOut(exists=False, active=False, url="", created_at=None, expires_at=None, revoked_at=None, views=0, last_viewed_at=None)
    active = bill_links.is_active(share)
    return BillShareOut(exists=True, active=active, url=bill_links.public_url(base_url(request), share) if active else "",
                        created_at=share.created_at, expires_at=share.expires_at, revoked_at=share.revoked_at, views=share.views,
                        last_viewed_at=share.last_viewed_at)


@router.get("/bills/{invoice_id}/share", response_model=BillShareOut)
def bill_share_status(invoice_id: uuid.UUID, request: Request, db: Session = DB, current: CurrentUser = Depends(client_user)):
    BillingService(db, current).get(invoice_id)
    return _share_out(bill_links.current_share(db, current.user.tenant_id, invoice_id), request)


@router.post("/bills/{invoice_id}/share", response_model=BillShareOut)
def bill_share_issue(invoice_id: uuid.UUID, request: Request, replace: bool = Query(False), db: Session = DB,
                     current: CurrentUser = Depends(client_user)):
    """The bill's QR link: whatever is already active, or a new one. `replace=true` makes a fresh one (the old
    one, and any printed QR with it, stops working)."""
    BillingService(db, current).get(invoice_id)
    share = bill_links.issue(db, current.user.tenant_id, invoice_id, current.id, replace=replace)
    return _share_out(share, request)


@router.delete("/bills/{invoice_id}/share", response_model=BillShareOut)
def bill_share_revoke(invoice_id: uuid.UUID, request: Request, db: Session = DB, current: CurrentUser = Depends(require("billing.edit"))):
    BillingService(db, current).get(invoice_id)
    bill_links.revoke(db, current.user.tenant_id, invoice_id, current.id)
    return _share_out(None, request)


@router.post("/bills/{invoice_id}/hold", response_model=BillOut)
def hold_bill(invoice_id: uuid.UUID, data: ReasonIn, db: Session = DB, current: CurrentUser = Depends(require("billing.edit"))):
    return BillingService(db, current).hold(invoice_id, data.reason)


@router.post("/bills/{invoice_id}/confirm", response_model=BillOut)
def confirm_bill(invoice_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(require("billing.edit"))):
    return BillingService(db, current).confirm(invoice_id)


@router.post("/bills/{invoice_id}/cancel", response_model=BillOut)
def cancel_bill(invoice_id: uuid.UUID, data: ReasonIn, db: Session = DB, current: CurrentUser = Depends(require("billing.edit"))):
    return BillingService(db, current).cancel(invoice_id, data.reason)


@router.post("/bills/{invoice_id}/payments", response_model=BillOut)
def take_payment(invoice_id: uuid.UUID, data: PaymentIn, request: Request, db: Session = DB,
                 current: CurrentUser = Depends(require("payments.collect"))):
    svc = BillingService(db, current)
    return run_once(request, db, current, "payment.take", lambda: BillOut.model_validate(svc.pay(invoice_id, data)))


@router.post("/bills/{invoice_id}/refunds", response_model=BillOut)
def refund(invoice_id: uuid.UUID, data: RefundIn, request: Request, db: Session = DB,
           current: CurrentUser = Depends(require("payments.collect"))):
    svc = BillingService(db, current)
    return run_once(request, db, current, "payment.refund", lambda: BillOut.model_validate(svc.refund(invoice_id, data)))


# ---------- worklist and the day ----------

@router.get("/worklist", response_model=Page[WorklistRowOut])
def worklist(department_id: uuid.UUID | None = None, status_: list[str] = Query(default=["billed", "scanned"], alias="status"),
             date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
             search: str = Query("", max_length=100), p: Paging = Depends(paging), db: Session = DB,
             current: CurrentUser = Depends(client_user)):
    if date_from is None and date_to is None:
        date_from, date_to = default_worklist_window()
    rows, total = BillingService(db, current).worklist(department_id, status_, date_from, date_to, search, p.page, p.size)
    items = [WorklistRowOut(item_id=i.id, invoice_id=b.id, invoice_no=b.invoice_no, bill_date=b.bill_date, patient_name=b.patient_name,
                            patient_age=b.patient_age, patient_gender=b.patient_gender, test_name=i.test_name, department_name=i.department_name,
                            is_imaging=i.is_imaging, accession_no=i.accession_no, status=i.status, bill_status=b.status, due=b.due,
                            status_changed_at=i.status_changed_at) for i, b in rows]
    return Page(items=items, total=total, page=p.page, size=p.size)


def can_update_progress(current: CurrentUser = Depends(client_user)) -> CurrentUser:
    """Marking tests pending / ready / delivered: the front desk (reports.deliver) or the lab (worklist.update)."""
    if not (current.can("reports.deliver") or current.can("worklist.update")):
        raise Forbidden("You don't have permission to change a test's progress.")
    return current


@router.post("/worklist/{item_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def set_status(item_id: uuid.UUID, data: ItemStatusIn, db: Session = DB, current: CurrentUser = Depends(can_update_progress)):
    BillingService(db, current).set_item_status(item_id, data.status)


@router.post("/bills/{bill_id}/tests/status", status_code=status.HTTP_204_NO_CONTENT)
def set_bill_tests_status(bill_id: uuid.UUID, data: BillItemsStatusIn, db: Session = DB,
                          current: CurrentUser = Depends(can_update_progress)):
    """Mark tests on one bill pending, ready or delivered — all of them, or the ones listed."""
    BillingService(db, current).set_bill_items_status(bill_id, data.status, data.item_ids)


@router.get("/summary/day", response_model=DaySummaryOut)
def day_summary(day: date | None = None, db: Session = DB, current: CurrentUser = Depends(client_user)):
    """The day at a glance, for everyone who works at the centre."""
    return BillingService(db, current).day_summary(day or local_today())


@router.get("/summary/desk", response_model=DeskSummaryOut)
def desk_summary(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                 db: Session = DB, current: CurrentUser = Depends(client_user)):
    """The dashboard for everyone in the centre: money collected and dues for a period, never the turnover."""
    if date_from and date_to and date_from > date_to:
        raise Invalid("The start date is after the end date.", field="from")
    return BillingService(db, current).desk_summary(local_today(), date_from, date_to)


@router.get("/summary/overview", response_model=OverviewOut)
def overview(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
             db: Session = DB, current: CurrentUser = Depends(require("analytics.view"))):
    """The owner's dashboard for a period; without a start date, everything since the first bill.
    Turnover and business figures, so only for the owner and the centre admin (analytics.view)."""
    if date_from and date_to and date_from > date_to:
        raise Invalid("The start date is after the end date.", field="from")
    return OverviewService(db, current).overview(local_today(), date_from, date_to)


# ---------- the patient's page (no sign-in; the link's token and a check instead) ----------

public_bills = APIRouter(prefix="/public/bills", tags=["public"])  # router already has prefix="/api"
PUBLIC_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}


def _public_tenant(request: Request) -> uuid.UUID:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None or not tenant.is_active:
        raise NotFound(bill_links.NOT_FOUND)
    return tenant.id


@public_bills.get("/{token}", response_model=PublicBillInfoOut)
def public_bill_info(token: str, request: Request, response: Response, db: Session = DB):
    """The centre's name and what the patient is asked for. Nothing about the bill or the patient."""
    response.headers.update(PUBLIC_HEADERS)
    tenant_id = _public_tenant(request)
    _share, invoice = bill_links.find(db, tenant_id, token)
    settings = db.get(TenantSettings, tenant_id)
    kind, _answer = bill_links.check_kind(db, invoice)
    return PublicBillInfoOut(centre_name=(settings.legal_name if settings else "") or request.state.tenant.name,
                            has_logo=bool(settings and settings.logo_data), check=kind)


@public_bills.post("/{token}/open", response_model=PublicBillOut)
def public_bill_open(token: str, data: PublicBillCheckIn, request: Request, response: Response, db: Session = DB):
    response.headers.update(PUBLIC_HEADERS)
    tenant_id = _public_tenant(request)
    _share, invoice = bill_links.check(db, tenant_id, token, data.check, client_ip(request) or "")
    patient = db.get(Patient, invoice.patient_id)
    settings = db.get(TenantSettings, tenant_id)
    centre = PublicBillCentreOut(legal_name=(settings.legal_name if settings else "") or request.state.tenant.name,
                                 address=settings.address if settings else "", phones=settings.phones if settings else "",
                                 bill_footer=settings.bill_footer if settings else "")
    return PublicBillOut(bill=BillOut.model_validate(invoice), patient_no=patient.patient_no if patient else "", centre=centre)


router.include_router(public_bills)
