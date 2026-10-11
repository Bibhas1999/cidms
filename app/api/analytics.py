"""Analytics: turnover and business figures, for the owner and the centre admin only (analytics.view).

One request per section, so the page loads them side by side:
    GET /api/analytics/{summary|trend|heatmap|departments|tests|doctors|patients|dues|staff|pipeline}
        ?from=&to=&department_id=&doctor=<id|self>&created_by=
    GET /api/analytics/live      today, the whole centre (polled by the page)
    GET /api/analytics/options   what the filters can be set to
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import client_user
from app.core.db import DB
from app.core.errors import Forbidden
from app.core.security import CurrentUser
from app.services.analytics import AnalyticsFilters, AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

UUID_OR_SELF = r"^(|self|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"


def analyst(current: CurrentUser = Depends(client_user)) -> CurrentUser:
    if not current.can("analytics.view"):
        raise Forbidden("Only the owner and the centre admin can see analytics.")
    return current


def filters(date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
            department_id: uuid.UUID | None = None, doctor: str = Query("", pattern=UUID_OR_SELF),
            created_by: uuid.UUID | None = None) -> AnalyticsFilters:
    return AnalyticsFilters(date_from=date_from, date_to=date_to, department_id=department_id, doctor=doctor, created_by=created_by)


def service(f: AnalyticsFilters = Depends(filters), db: Session = DB, current: CurrentUser = Depends(analyst)) -> AnalyticsService:
    return AnalyticsService(db, current, f)


SECTIONS = ("summary", "trend", "heatmap", "departments", "tests", "doctors", "patients", "dues", "staff", "pipeline")


def _route(name: str):
    def endpoint(svc: AnalyticsService = Depends(service)) -> dict:
        return getattr(svc, name)()
    endpoint.__name__ = f"analytics_{name}"
    endpoint.__doc__ = getattr(AnalyticsService, name).__doc__
    router.add_api_route(f"/{name}", endpoint, methods=["GET"], name=f"analytics_{name}")


for _name in SECTIONS:
    _route(_name)


@router.get("/live")
def live(db: Session = DB, current: CurrentUser = Depends(analyst)) -> dict:
    return AnalyticsService(db, current, AnalyticsFilters()).live()


@router.get("/options")
def options(db: Session = DB, current: CurrentUser = Depends(analyst)) -> dict:
    return AnalyticsService(db, current, AnalyticsFilters()).options()
