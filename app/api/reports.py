"""Business reports (JSON, Excel or PDF) and the bills list as a file.

/api/reports/... needs analytics.view for turnover reports (business_reports.view until that permission exists)
and business_reports.view for dues and payments. /api/exports/bills.* only needs to be signed in to the centre,
like the bills list itself, and takes exactly the bills list's query string so the file matches the screen.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.billing import bill_filters
from app.api.deps import client_user
from app.core.db import DB
from app.core.errors import Forbidden
from app.core.money import local_today
from app.core.security import CurrentUser
from app.models import TenantSettings
from app.services.audit import AuditService
from app.services.billing import BillFilters
from app.services.exports import to_pdf, to_xlsx, to_xlsx_book
from app.services.reports import (
    CATALOGUE,
    Report,
    ReportParams,
    ReportService,
    bills_by_doctor,
    bills_report,
    dues_workbook,
    file_name,
    filters_for_log,
    visible_reports,
)

router = APIRouter(tags=["reports"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def can_view_reports(current: CurrentUser = Depends(client_user)) -> CurrentUser:
    """Anyone who can see at least one report; each report then checks its own permission."""
    if not any(current.can(p) for p in {r["permission"] for r in CATALOGUE}):
        raise Forbidden("You don't have permission to see reports.")
    return current


def _file(db: Session, current: CurrentUser, report: Report, fmt: str, name: str) -> Response:
    if fmt == "xlsx":
        body, media = to_xlsx(report.title, report.subtitle, report.columns, report.rows, report.totals), XLSX
    else:
        centre = db.get(TenantSettings, current.user.tenant_id)
        body = to_pdf(centre, report.title, report.subtitle, report.columns, report.rows, report.totals,
                      landscape=report.landscape, generated_by=current.user.full_name)
        media = "application/pdf"
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------- the bills list as a file ----------

def _bills_file(fmt: str, f: BillFilters, db: Session, current: CurrentUser) -> Response:
    report = bills_report(db, current, f)
    AuditService(db).record(current.user.tenant_id, current.id, "export.bills", "invoice", "", {
        "format": fmt, "filters": filters_for_log(f), "rows": len(report.rows)})
    return _file(db, current, report, fmt, file_name("bills", f.date_from, f.date_to, fmt))


@router.get("/api/exports/bills.xlsx")
def bills_xlsx(f: BillFilters = Depends(bill_filters), db: Session = DB, current: CurrentUser = Depends(client_user)):
    return _bills_file("xlsx", f, db, current)


@router.get("/api/exports/bills.pdf")
def bills_pdf(f: BillFilters = Depends(bill_filters), db: Session = DB, current: CurrentUser = Depends(client_user)):
    return _bills_file("pdf", f, db, current)


@router.get("/api/exports/bills-by-doctor.xlsx")
def bills_by_doctor_xlsx(f: BillFilters = Depends(bill_filters), db: Session = DB, current: CurrentUser = Depends(client_user)):
    """The bills list as a workbook: a summary sheet, then one sheet per referring doctor (same filters as the screen)."""
    report = bills_report(db, current, f)
    summary, sheets = bills_by_doctor(report)
    AuditService(db).record(current.user.tenant_id, current.id, "export.bills", "invoice", "", {
        "format": "xlsx-by-doctor", "filters": filters_for_log(f), "rows": len(report.rows), "sheets": len(sheets)})
    fname = file_name("bills-by-doctor", f.date_from, f.date_to, "xlsx")
    return Response(to_xlsx_book(sheets, summary=summary), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- the Dues page as a workbook ----------

def dues_viewer(current: CurrentUser = Depends(client_user)) -> CurrentUser:
    if not current.can("payments.collect"):
        raise Forbidden("You don't have permission to see dues.")
    return current


@router.get("/api/dues/workbook")
def dues_book(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
              db: Session = DB, current: CurrentUser = Depends(dues_viewer)):
    """Bills still owing: a summary by referring doctor and a sheet for each doctor (oldest first)."""
    summary, sheets = dues_workbook(db, current, date_from, date_to)
    return {**summary.as_json(), "sheets": [s.as_json() for s in sheets]}


@router.get("/api/dues/workbook.xlsx")
def dues_book_xlsx(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
                   db: Session = DB, current: CurrentUser = Depends(dues_viewer)):
    summary, sheets = dues_workbook(db, current, date_from, date_to)
    AuditService(db).record(current.user.tenant_id, current.id, "export.dues", "invoice", "", {
        "format": "xlsx", "from": str(date_from or ""), "to": str(date_to or ""), "sheets": len(sheets)})
    book = to_xlsx_book([(s.title, s.subtitle, s.columns, s.rows, s.totals) for s in sheets],
                        summary=("Summary", f"Dues by referring doctor · {summary.subtitle}", summary.columns, summary.rows, summary.totals))
    fname = f"dues-by-doctor-{local_today().isoformat()}.xlsx" if not (date_from or date_to) else file_name("dues-by-doctor", date_from, date_to, "xlsx")
    return Response(book, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- reports ----------

@router.get("/api/reports")
def catalogue(current: CurrentUser = Depends(can_view_reports)):
    return visible_reports(current)


@router.get("/api/reports/workbook.xlsx")
def workbook(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
             all_time: bool = Query(False, alias="all"), group: str = Query("day", pattern="^(day|week|month|year)$"),
             db: Session = DB, current: CurrentUser = Depends(can_view_reports)):
    """Every report the person may see, for the same dates, in one Excel workbook — one sheet each
    (Collection, Payments, Dues, Discounts, Tests, Departments, Referring doctors, Staff). Dues lists every
    bill still owing, whatever the dates."""
    service = ReportService(db, current)
    sheets, first = [], None
    for meta in visible_reports(current):
        name = meta["name"]
        dated = name != "dues"
        params = ReportParams(date_from=date_from if dated else None, date_to=date_to if dated else None,
                              all_time=all_time and dated, group=group)
        r = service.run(name, params)
        first = first or params
        sheets.append((r.title, r.subtitle, r.columns, r.rows, r.totals))
    AuditService(db).record(current.user.tenant_id, current.id, "export.report", "report", "workbook", {
        "format": "xlsx", "sheets": [s[0] for s in sheets], "from": str(first.date_from or "") if first else "",
        "to": str(first.date_to or "") if first else "", "group": group})
    fname = file_name("billing-reports", first.date_from if first else None, first.date_to if first else None, "xlsx")
    return Response(to_xlsx_book(sheets), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/api/reports/{name}")
def report(name: str, date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
           all_time: bool = Query(False, alias="all"), group: str = Query("day", pattern="^(day|week|month|year)$"),
           department_id: uuid.UUID | None = None, mode: str = Query("", pattern="^(|cash|upi|card|bank|other)$"),
           format: str = Query("json", pattern="^(json|xlsx|pdf)$"), db: Session = DB,
           current: CurrentUser = Depends(can_view_reports)):
    """One report as JSON, or as the same table in Excel or PDF (`format`), with exactly the filters on screen."""
    params = ReportParams(date_from=date_from, date_to=date_to, all_time=all_time, group=group, department_id=department_id, mode=mode)
    result = ReportService(db, current).run(name, params)
    if format == "json":
        return result.as_json()
    AuditService(db).record(current.user.tenant_id, current.id, "export.report", "report", name, {
        "format": format, "from": str(params.date_from or ""), "to": str(params.date_to or ""), "group": group,
        "department_id": str(department_id or ""), "mode": mode, "rows": len(result.rows)})
    if name == "collection":
        fname = file_name(f"collection-by-{group}", params.date_from, params.date_to, format)
    elif name == "dues" and not (params.date_from or params.date_to):
        fname = f"dues-{local_today().isoformat()}.{format}"
    else:
        fname = file_name(name, params.date_from, params.date_to, format)
    return _file(db, current, result, format, fname)
