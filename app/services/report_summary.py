"""The reporting dashboard: counts and times only (no money), for doctors and reporting staff.

- The work in hand (waiting, drafts, ready to sign, overdue, oldest waiting, my work) is "now", whatever the period.
- Signed, amended, turnaround, sent to patients and the charts are for the chosen period (by the centre's dates).
- Turnaround = when the bill was made to when the report was first signed. Overdue = still waiting for a signed
  report after REPORT_TARGET_HOURS_IMAGING (scans) or REPORT_TARGET_HOURS_OTHER (other tests).
"""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import CurrentUser
from app.models import ImagingStudy, Invoice, InvoiceItem, MessageDelivery, ReportShare, TestReport, TestReportVersion, utcnow

SIGNED = ("signed", "amended")


def _local_day(col):
    return func.date(func.timezone(get_settings().display_timezone, col))


class ReportSummaryService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.t = current.user.tenant_id

    def _in_period(self, col, date_from: date | None, date_to: date | None):
        conds = []
        if date_from:
            conds.append(_local_day(col) >= date_from)
        if date_to:
            conds.append(_local_day(col) <= date_to)
        return and_(*conds) if conds else literal(True)

    def _waiting(self):
        """Tests on live bills that still have no signed report."""
        return (select(InvoiceItem, Invoice, TestReport).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                .outerjoin(TestReport, TestReport.invoice_item_id == InvoiceItem.id)
                .where(InvoiceItem.tenant_id == self.t, InvoiceItem.status.in_(("billed", "scanned")), Invoice.status != "cancelled",
                       InvoiceItem.test_id.is_not(None), or_(TestReport.id.is_(None), TestReport.status.not_in(SIGNED))))

    @staticmethod
    def _target_hours(is_imaging: bool) -> int:
        s = get_settings()
        return s.report_target_hours_imaging if is_imaging else s.report_target_hours_other

    def _age(self, invoice: Invoice, item: InvoiceItem, now: datetime) -> dict:
        hours = (now - invoice.created_at).total_seconds() / 3600
        target = self._target_hours(item.is_imaging)
        state = "overdue" if hours > target else "due_soon" if hours > target * 0.75 else "on_time"
        return {"age_hours": round(hours, 1), "target_hours": target, "state": state}

    @staticmethod
    def _row(item: InvoiceItem, invoice: Invoice, report: TestReport | None, extra: dict | None = None) -> dict:
        return {"item_id": item.id, "invoice_no": invoice.invoice_no, "bill_date": invoice.bill_date, "patient_name": invoice.patient_name,
                "test_name": item.test_name, "department_name": item.department_name, "is_imaging": item.is_imaging,
                "report_status": report.status if report else None, "reported_by_name": report.reported_by_name if report else "",
                "signer_name": report.signer_name if report else "", "signed_at": report.signed_at if report else None,
                "updated_at": report.updated_at if report else None, **(extra or {})}

    def summary(self, date_from: date | None, date_to: date | None) -> dict:
        db, t, now = self.db, self.t, utcnow()
        s = get_settings()

        # ---------- the work in hand (now) ----------
        waiting_q = self._waiting().subquery()
        waiting = db.scalar(select(func.count()).select_from(waiting_q)) or 0
        imaging_limit = now - timedelta(hours=s.report_target_hours_imaging)
        other_limit = now - timedelta(hours=s.report_target_hours_other)
        overdue = db.scalar(select(func.count()).select_from(self._waiting().where(
            case((InvoiceItem.is_imaging, Invoice.created_at < imaging_limit), else_=Invoice.created_at < other_limit)).subquery())) or 0
        by_status = dict(db.execute(select(TestReport.status, func.count()).join(InvoiceItem, InvoiceItem.id == TestReport.invoice_item_id)
                                    .where(TestReport.tenant_id == t, InvoiceItem.status != "cancelled").group_by(TestReport.status)).all())

        # ---------- the period ----------
        first_signed = (select(TestReportVersion.report_id, func.min(TestReportVersion.created_at).label("at"))
                        .where(TestReportVersion.tenant_id == t, TestReportVersion.action == "signed")
                        .group_by(TestReportVersion.report_id).subquery())
        signed_rows = (select(first_signed.c.at, Invoice.created_at.label("billed_at"), InvoiceItem.department_name, InvoiceItem.is_imaging,
                              TestReport.signer_name, TestReport.modality)
                       .join(TestReport, TestReport.id == first_signed.c.report_id)
                       .join(InvoiceItem, InvoiceItem.id == TestReport.invoice_item_id).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                       .where(self._in_period(first_signed.c.at, date_from, date_to)).subquery())
        hours = func.extract("epoch", signed_rows.c.at - signed_rows.c.billed_at) / 3600
        totals = db.execute(select(func.count(), func.avg(hours), func.percentile_cont(0.9).within_group(hours))
                            .select_from(signed_rows)).one()
        amended = db.scalar(select(func.count()).where(TestReportVersion.tenant_id == t, TestReportVersion.action == "amended",
                                                       self._in_period(TestReportVersion.created_at, date_from, date_to))) or 0
        sent = db.scalar(select(func.count()).where(MessageDelivery.tenant_id == t, MessageDelivery.status != "failed",
                                                    self._in_period(MessageDelivery.created_at, date_from, date_to))) or 0
        link_views = db.scalar(select(func.coalesce(func.sum(ReportShare.views), 0)).where(
            ReportShare.tenant_id == t, ReportShare.last_viewed_at.is_not(None),
            self._in_period(ReportShare.last_viewed_at, date_from, date_to))) or 0

        # Charts: per day, or per month when the period is long (or all time).
        span = (date_to or now.date()) - (date_from or date(2000, 1, 1))
        unit = "month" if span.days > 92 else "day"

        def bucket(col):
            d = _local_day(col)
            return func.to_char(d, "YYYY-MM-01") if unit == "month" else func.to_char(d, "YYYY-MM-DD")

        b = bucket(signed_rows.c.at)
        trend = [{"day": k, "signed": n, "avg_hours": round(float(a), 1) if a is not None else None}
                 for k, n, a in db.execute(select(b, func.count(), func.avg(hours)).select_from(signed_rows).group_by(b).order_by(b)).all()]
        dept = func.coalesce(func.nullif(signed_rows.c.department_name, ""), "Other")
        by_department = [{"name": k, "count": n, "avg_hours": round(float(a), 1) if a is not None else None} for k, n, a in db.execute(
            select(dept, func.count(), func.avg(hours)).select_from(signed_rows).group_by(dept).order_by(func.count().desc()).limit(12)).all()]
        mod = func.coalesce(func.nullif(signed_rows.c.modality, ""), "—")
        by_modality = [{"name": k, "count": n} for k, n in db.execute(
            select(mod, func.count()).select_from(signed_rows).group_by(mod).order_by(func.count().desc()).limit(12)).all()]
        doc = func.coalesce(func.nullif(signed_rows.c.signer_name, ""), "—")
        by_doctor = [{"name": k, "count": n, "avg_hours": round(float(a), 1) if a is not None else None} for k, n, a in db.execute(
            select(doc, func.count(), func.avg(hours)).select_from(signed_rows).group_by(doc).order_by(func.count().desc()).limit(12)).all()]
        ib = bucket(ImagingStudy.created_at)
        images = [{"day": k, "studies": n, "images": int(i or 0)} for k, n, i in db.execute(
            select(ib, func.count(), func.sum(ImagingStudy.instance_count)).where(
                ImagingStudy.tenant_id == t, self._in_period(ImagingStudy.created_at, date_from, date_to)).group_by(ib).order_by(ib)).all()]

        # ---------- lists ----------
        oldest = [self._row(i, b_, r, self._age(b_, i, now))
                  for i, b_, r in db.execute(self._waiting().order_by(Invoice.created_at).limit(10)).all()]
        recent = [self._row(i, b_, r) for i, b_, r in db.execute(
            select(InvoiceItem, Invoice, TestReport).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .join(TestReport, TestReport.invoice_item_id == InvoiceItem.id)
            .where(TestReport.tenant_id == t, TestReport.status.in_(SIGNED), TestReport.signed_at.is_not(None))
            .order_by(TestReport.signed_at.desc()).limit(10)).all()]
        mine = self._my_work()

        return {
            "now": now, "trend_unit": unit,
            "target_hours": {"imaging": s.report_target_hours_imaging, "other": s.report_target_hours_other},
            "kpis": {
                "waiting": waiting, "drafts": by_status.get("draft", 0), "ready_to_sign": by_status.get("final", 0),
                "signed": totals[0] or 0, "amended": amended, "overdue": overdue,
                "avg_turnaround_hours": round(float(totals[1]), 1) if totals[1] is not None else None,
                "p90_turnaround_hours": round(float(totals[2]), 1) if totals[2] is not None else None,
                "sent_whatsapp": sent, "link_views": int(link_views),
            },
            "trend": trend, "by_department": by_department, "by_modality": by_modality, "by_doctor": by_doctor, "images": images,
            "oldest_waiting": oldest, "recently_signed": recent, **mine,
        }

    def _my_work(self) -> dict:
        me: uuid.UUID = self.current.id
        base = (select(InvoiceItem, Invoice, TestReport).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                .join(TestReport, TestReport.invoice_item_id == InvoiceItem.id)
                .where(TestReport.tenant_id == self.t, InvoiceItem.status != "cancelled", Invoice.status != "cancelled"))
        drafts = [self._row(i, b, r) for i, b, r in self.db.execute(
            base.where(TestReport.status == "draft", TestReport.reported_by == me).order_by(TestReport.updated_at.desc()).limit(10)).all()]
        to_sign = []
        if self.current.can("reports.sign"):
            to_sign = [self._row(i, b, r) for i, b, r in self.db.execute(
                base.where(TestReport.status == "final").order_by(TestReport.updated_at).limit(10)).all()]
        return {"my_drafts": drafts, "awaiting_my_signature": to_sign}
