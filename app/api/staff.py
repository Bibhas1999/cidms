"""Staff and roles. The same routes serve a centre's staff and, in the platform workspace, platform staff."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import Paging, paging, require_any
from app.core.db import DB
from app.core.security import CurrentUser
from app.repositories.users import RoleRepository
from app.schemas import Page, PasswordResetIn, RoleOut, StaffCreateIn, StaffOut, StaffUpdateIn
from app.services.staff import StaffService

router = APIRouter(prefix="/api", tags=["staff"])
manage_staff = require_any("staff.manage", "platform.staff.manage")


@router.get("/staff", response_model=Page[StaffOut])
def list_staff(search: str = Query("", max_length=100), active: bool | None = None, p: Paging = Depends(paging),
               db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    items, total = StaffService(db, current).page(search, active, p.page, p.size)
    return Page(items=items, total=total, page=p.page, size=p.size)


@router.post("/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_staff(data: StaffCreateIn, db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    return StaffService(db, current).create(data)


@router.patch("/staff/{user_id}", response_model=StaffOut)
def update_staff(user_id: uuid.UUID, data: StaffUpdateIn, db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    return StaffService(db, current).update(user_id, data)


@router.post("/staff/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(user_id: uuid.UUID, data: PasswordResetIn, db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    StaffService(db, current).reset_password(user_id, data.temporary_password)


@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: Session = DB, current: CurrentUser = Depends(manage_staff)):
    return RoleRepository(db).for_scope("platform" if current.is_platform else "client")
