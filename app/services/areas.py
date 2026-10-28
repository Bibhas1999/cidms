"""Who may work where. A centre is used in separate work areas: reception (billing), the OPD (the doctors' queue)
and each department (its worklist). Staff are given one or more of them (staff_areas); owners and centre admins
hold areas.all and work everywhere, plus the admin area (dashboards, reports, the catalogue).

These checks come on top of the permission checks, never instead of them: someone in reception still needs
billing.create to make a bill.
"""

import uuid

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.core.security import CurrentUser, get_current_user
from app.models import Department, User
from app.schemas import AreaOut

EVERYWHERE = "areas.all"
NAMES = {"admin": "Admin", "reception": "Reception", "opd": "OPD"}


def _mine(user) -> list:
    return list(getattr(user, "areas", None) or [])


def _has(current, area: str, department_id: uuid.UUID | None = None) -> bool:
    if current.can(EVERYWHERE):
        return True
    return any(a.area == area and (department_id is None or a.department_id == department_id) for a in _mine(current.user))


def has_reception(current: CurrentUser) -> bool:
    return _has(current, "reception")


def has_opd(current: CurrentUser) -> bool:
    return _has(current, "opd")


def has_department(current: CurrentUser, department_id: uuid.UUID | None) -> bool:
    if department_id is None:
        return current.can(EVERYWHERE)
    return _has(current, "department", department_id)


def may_progress(current: CurrentUser, department_id: uuid.UUID | None) -> bool:
    """Moving a test along (in progress, ready, delivered): its department, or reception from the bill page."""
    return current.can(EVERYWHERE) or has_reception(current) or (department_id is not None and has_department(current, department_id))


def areas_of(db: Session, user: User, permissions: set[str]) -> list[AreaOut]:
    """Every work area of the centre, in menu order: admin, reception, OPD, then its departments by name (active
    only), each saying whether this person may work there. The chooser shows them all: one they may use opens, the
    others say they aren't permitted. Admin is listed only for those who work everywhere."""
    if user.tenant_id is None:
        return []
    everywhere = EVERYWHERE in permissions
    mine = _mine(user)
    kinds = {a.area for a in mine}
    out: list[AreaOut] = [AreaOut(key="admin", kind="admin", name=NAMES["admin"])] if everywhere else []
    for kind in ("reception", "opd"):
        out.append(AreaOut(key=kind, kind=kind, name=NAMES[kind], allowed=everywhere or kind in kinds))
    ids = {a.department_id for a in mine if a.area == "department" and a.department_id}
    q = select(Department).where(Department.tenant_id == user.tenant_id, Department.is_active.is_(True))
    for d in db.scalars(q.order_by(Department.name)):
        out.append(AreaOut(key=f"department:{d.id}", kind="department", department_id=d.id, name=d.name,
                           allowed=everywhere or d.id in ids))
    return out


def areas_for(db: Session, current: CurrentUser) -> list[AreaOut]:
    return areas_of(db, current.user, current.permissions)


# ---------- route dependencies ----------

def _client(current: CurrentUser) -> CurrentUser:
    if current.is_platform:
        raise NotFound("Not available in the platform workspace.")
    return current


def reception_area(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not has_reception(_client(current)):
        raise Forbidden("You don't work in reception.")
    return current


def opd_area(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not has_opd(_client(current)):
        raise Forbidden("You don't work in the OPD.")
    return current


def reception_or_opd_area(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    _client(current)
    if not (has_reception(current) or has_opd(current)):
        raise Forbidden("You don't work in reception or the OPD.")
    return current
