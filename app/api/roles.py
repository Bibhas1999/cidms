"""Roles and permissions (Settings > Roles & permissions). Reading is open to whoever manages staff or roles,
since the staff screen needs the list to pick roles from; changes need roles.manage, in a centre's workspace."""

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import DB
from app.core.errors import Forbidden
from app.core.security import CurrentUser, get_current_user
from app.schemas_roles import PermissionGroupOut, RoleCopyIn, RoleDetailOut, RoleIn, RoleMemberOut
from app.services.roles import RoleService

router = APIRouter(prefix="/api", tags=["roles"])


def can_read_roles(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    needed = ("platform.staff.manage",) if current.is_platform else ("staff.manage", "roles.manage")
    if not any(current.can(p) for p in needed):
        raise Forbidden("You don't have permission to do that.")
    return current


@router.get("/permissions", response_model=list[PermissionGroupOut])
def permission_catalog(db: Session = DB, current: CurrentUser = Depends(can_read_roles)):
    """Every permission a role in this workspace can have, grouped by area, with whether you hold it."""
    return RoleService(db, current).catalog()


@router.get("/roles", response_model=list[RoleDetailOut])
def list_roles(db: Session = DB, current: CurrentUser = Depends(can_read_roles)):
    return RoleService(db, current).all_roles()


@router.get("/roles/{role_id}", response_model=RoleDetailOut)
def get_role(role_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(can_read_roles)):
    return RoleService(db, current).detail(role_id)


@router.get("/roles/{role_id}/members", response_model=list[RoleMemberOut])
def role_members(role_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(can_read_roles)):
    from app.services.auth import avatar_url
    return [RoleMemberOut(id=u.id, full_name=u.full_name, email=u.email, is_active=u.is_active, avatar_url=avatar_url(u))
            for u in RoleService(db, current).members(role_id)]


@router.post("/roles", response_model=RoleDetailOut, status_code=status.HTTP_201_CREATED)
def create_role(data: RoleIn, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    svc = RoleService(db, current)
    return svc.detail(svc.create(data).id)


@router.put("/roles/{role_id}", response_model=RoleDetailOut)
def update_role(role_id: uuid.UUID, data: RoleIn, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    svc = RoleService(db, current)
    return svc.detail(svc.update(role_id, data).id)


@router.post("/roles/{role_id}/copy", response_model=RoleDetailOut, status_code=status.HTTP_201_CREATED)
def copy_role(role_id: uuid.UUID, data: RoleCopyIn | None = None, db: Session = DB,
              current: CurrentUser = Depends(get_current_user)):
    svc = RoleService(db, current)
    return svc.detail(svc.copy(role_id, data.name if data else None).id)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(role_id: uuid.UUID, reassign_to: uuid.UUID | None = Query(None), db: Session = DB,
                current: CurrentUser = Depends(get_current_user)):
    """A role that people have is refused (409, with how many) unless reassign_to names the role to move them to."""
    RoleService(db, current).delete(role_id, reassign_to)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
