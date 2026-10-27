"""OPD API: the OPD's doctors and the day's queue of visits. Every route is for people who work in the OPD
(or everywhere); changes also need appointments.manage (doctors: or catalogue.manage)."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.db import DB
from app.core.errors import Forbidden
from app.core.idempotency import run_once
from app.core.money import local_today
from app.core.security import CurrentUser, require
from app.schemas_opd import OpdDoctorIn, OpdDoctorOut, OpdStatusIn, OpdVisitIn, OpdVisitOut
from app.services.areas import opd_area
from app.services.opd import OpdService, visit_out

router = APIRouter(prefix="/api/opd", tags=["opd"], dependencies=[Depends(opd_area)])
run_queue = require("appointments.manage")


def manage_doctors(current: CurrentUser = Depends(opd_area)) -> CurrentUser:
    if not (current.can("appointments.manage") or current.can("catalogue.manage")):
        raise Forbidden("You don't have permission to change the OPD's doctors.")
    return current


@router.get("/doctors", response_model=list[OpdDoctorOut])
def doctors(all_: bool = Query(False, alias="all"), db: Session = DB, current: CurrentUser = Depends(opd_area)):
    """The OPD's doctors; switched-off ones too with ?all=true."""
    return OpdService(db, current).doctors(include_off=all_)


@router.post("/doctors", response_model=OpdDoctorOut, status_code=status.HTTP_201_CREATED)
def add_doctor(data: OpdDoctorIn, db: Session = DB, current: CurrentUser = Depends(manage_doctors)):
    return OpdService(db, current).save_doctor(data)


@router.put("/doctors/{doctor_id}", response_model=OpdDoctorOut)
def edit_doctor(doctor_id: uuid.UUID, data: OpdDoctorIn, db: Session = DB, current: CurrentUser = Depends(manage_doctors)):
    return OpdService(db, current).save_doctor(data, doctor_id)


@router.get("/visits", response_model=list[OpdVisitOut])
def visits(day: date | None = Query(None, alias="date"), doctor_id: uuid.UUID | None = None,
           status_: str | None = Query(None, alias="status", pattern="^(waiting|with_doctor|done|cancelled)$"),
           db: Session = DB, current: CurrentUser = Depends(opd_area)):
    """One day's queue (today in India by default), by doctor and then token."""
    return [visit_out(v) for v in OpdService(db, current).visits(day or local_today(), doctor_id, status_)]


@router.post("/visits", response_model=OpdVisitOut, status_code=status.HTTP_201_CREATED)
def add_visit(data: OpdVisitIn, request: Request, db: Session = DB, current: CurrentUser = Depends(run_queue)):
    """A patient joins a doctor's queue and gets a token; the fee (if any) is billed and what's paid now taken."""
    svc = OpdService(db, current)
    return run_once(request, db, current, "opd.visit", lambda: visit_out(svc.create_visit(data)), status.HTTP_201_CREATED)


@router.post("/visits/{visit_id}/status", response_model=OpdVisitOut)
def set_status(visit_id: uuid.UUID, data: OpdStatusIn, db: Session = DB, current: CurrentUser = Depends(run_queue)):
    return visit_out(OpdService(db, current).set_status(visit_id, data.status, data.reason))
