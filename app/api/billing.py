"""Billing API: catalogue, patients, bills, payments, worklist and the day's summary."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import Paging, client_user, paging
from app.core.db import DB
from app.core.idempotency import run_once
from app.core.money import local_today
from app.core.security import CurrentUser, require
from app.schemas import Page
from app.schemas_billing import (
    BillIn,
    BillOut,
    BillPage,
    BillUpdateIn,
    DaySummaryOut,
    DepartmentIn,
    DepartmentOut,
    DoctorIn,
    DoctorOut,
    ItemStatusIn,
    LabTestIn,
    LabTestOut,
    OverviewOut,
    PatientIn,
    PatientOut,
    PaymentIn,
    ReasonIn,
    RefundIn,
    TestTypeIn,
    TestTypeOut,
    WorklistRowOut,
)
from app.services.billing import BillingService, OverviewService, default_worklist_window
from app.services.catalogue import CatalogueService
from app.services.patients import PatientService

router = APIRouter(prefix="/api", tags=["billing"])
manage_catalogue = require("catalogue.manage")


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
def add_doctor(data: DoctorIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_doctor(data)


@router.put("/doctors/{doctor_id}", response_model=DoctorOut)
def edit_doctor(doctor_id: uuid.UUID, data: DoctorIn, db: Session = DB, current: CurrentUser = Depends(manage_catalogue)):
    return CatalogueService(db, current).save_doctor(data, doctor_id)


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
    return PatientService(db, current).get(patient_id)


@router.put("/patients/{patient_id}", response_model=PatientOut)
def edit_patient(patient_id: uuid.UUID, data: PatientIn, db: Session = DB, current: CurrentUser = Depends(require("patients.manage"))):
    return PatientService(db, current).update(patient_id, data)


# ---------- bills ----------

@router.get("/bills", response_model=BillPage)
def bills(search: str = Query("", max_length=100), date_from: date | None = Query(None, alias="from"),
          date_to: date | None = Query(None, alias="to"), status_: str | None = Query(None, alias="status", pattern="^(confirmed|on_hold|cancelled)$"),
          due: bool = False, doctor_id: uuid.UUID | None = None, patient_id: uuid.UUID | None = None,
          sort: str = Query("newest", pattern="^(newest|oldest)$"),
          p: Paging = Depends(paging), db: Session = DB, current: CurrentUser = Depends(client_user)):
    items, total, sums = BillingService(db, current).page(search, date_from, date_to, status_, due, doctor_id, patient_id, p.page, p.size,
                                                          oldest_first=sort == "oldest")
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
    return BillingService(db, current).get(invoice_id)


@router.put("/bills/{invoice_id}", response_model=BillOut)
def edit_bill(invoice_id: uuid.UUID, data: BillUpdateIn, db: Session = DB, current: CurrentUser = Depends(require("billing.edit"))):
    return BillingService(db, current).update(invoice_id, data)


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


@router.post("/worklist/{item_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def set_status(item_id: uuid.UUID, data: ItemStatusIn, db: Session = DB, current: CurrentUser = Depends(require("worklist.update"))):
    BillingService(db, current).set_item_status(item_id, data.status)


@router.get("/summary/day", response_model=DaySummaryOut)
def day_summary(day: date | None = None, db: Session = DB, current: CurrentUser = Depends(client_user)):
    return BillingService(db, current).day_summary(day or local_today())


@router.get("/summary/overview", response_model=OverviewOut)
def overview(db: Session = DB, current: CurrentUser = Depends(require("business_reports.view"))):
    """The owner's dashboard. Business figures, so only for people who may see business reports."""
    return OverviewService(db, current).overview(local_today())
