"""The platform admin panel: clients and plans."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import Paging, paging, platform_permission
from app.core.db import DB
from app.core.security import CurrentUser
from app.schemas import BackupSettingsIn, ClientCreateIn, ClientOut, ClientUpdateIn, Page, PlanOut
from app.services import backups
from app.services.clients import ClientService, platform_overview

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/clients", response_model=Page[ClientOut])
def list_clients(search: str = Query("", max_length=100), status_: str | None = Query(None, alias="status", pattern="^(active|suspended)$"),
                 p: Paging = Depends(paging), db: Session = DB,
                 current: CurrentUser = Depends(platform_permission("platform.clients.view"))):
    items, total = ClientService(db, current).page(search, status_, p.page, p.size)
    return Page(items=items, total=total, page=p.page, size=p.size)


@router.post("/clients", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(data: ClientCreateIn, db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.clients.manage"))):
    return ClientService(db, current).create(data)


@router.patch("/clients/{tenant_id}", response_model=ClientOut)
def update_client(tenant_id: uuid.UUID, data: ClientUpdateIn, db: Session = DB,
                  current: CurrentUser = Depends(platform_permission("platform.clients.manage"))):
    return ClientService(db, current).update(tenant_id, data)


@router.get("/overview")
def overview(db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.clients.view"))):
    """The platform's home page: centres, people, use this month and renewals due (counts, not centres' money)."""
    return platform_overview(db)


@router.get("/backups")
def backup_overview(db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.backups.manage"))):
    """The backup schedule, when the next one runs, and the last 30 backups."""
    return backups.overview(db)


@router.put("/backups")
def backup_schedule(data: BackupSettingsIn, db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.backups.manage"))):
    return backups.update(db, current.id, data.enabled, data.every_days, data.at_time, data.keep_days)


@router.post("/backups/run")
def backup_now(db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.backups.manage"))):
    """Ask for a backup now: the server starts it within 5 minutes."""
    return backups.request_now(db, current.id)


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.clients.view"))):
    return ClientService(db, current).plans()
