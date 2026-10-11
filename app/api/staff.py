"""Staff and roles. The same routes serve a centre's staff and, in the platform workspace, platform staff."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import Paging, paging, require_any
from app.core.db import DB
from app.core.security import CurrentUser
from app.schemas import Page, PasswordResetIn, StaffCreateIn, StaffOut, StaffUpdateIn
from app.schemas_roles import StaffRolesIn
from app.services.staff import StaffService

router = APIRouter(prefix="/api", tags=["staff"])
manage_staff = require_any("staff.manage", "platform.staff.manage")


@router.get("/staff", response_model=Page[StaffOut])
def list_staff(search: str = Query("", max_length=100), active: bool | None = None, p: Paging = Depends(paging),
               db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    from app.services.auth import avatar_url
    items, total = StaffService(db, current).page(search, active, p.page, p.size)
    out = [StaffOut.model_validate(u).model_copy(update={"avatar_url": avatar_url(u)}) for u in items]
    return Page(items=out, total=total, page=p.page, size=p.size)


@router.post("/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff(data: StaffCreateIn, db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    return StaffService(db, current).create(data)


@router.patch("/staff/{user_id}", response_model=StaffOut)
def update_staff(user_id: uuid.UUID, data: StaffUpdateIn, db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    return StaffService(db, current).update(user_id, data)


@router.post("/staff/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(user_id: uuid.UUID, data: PasswordResetIn, db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    StaffService(db, current).reset_password(user_id, data.temporary_password)


@router.put("/staff/{user_id}/roles", response_model=StaffOut)
def set_staff_roles(user_id: uuid.UUID, data: StaffRolesIn, db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    """Give someone exactly these roles (built-in or the centre's own), with the same rules as editing them.
    The roles list itself (GET /api/roles) lives in app/api/roles.py."""
    return StaffService(db, current).set_roles(user_id, data.role_ids)
