"""The platform admin panel: clients and plans."""

import gzip
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import Paging, paging, platform_permission
from app.core.db import DB
from app.core.errors import NotFound
from app.core.security import CurrentUser, confirm_identity
from app.schemas import BackupRestoreIn, BackupSettingsIn, ClientCreateIn, ClientOut, ClientUpdateIn, Page, PlanOut
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


@router.get("/backups/{run_id}/download")
def backup_download(run_id: uuid.UUID, format: Literal["dump", "sql"] = "dump", db: Session = DB,
                    current: CurrentUser = Depends(platform_permission("platform.backups.manage"))):
    """The backup's file: .dump (Postgres's own format, for restoring) or .sql (plain SQL to read)."""
    run = db.get(backups.BackupRun, run_id)
    path = backups.file_for(run, format) if run else None
    if path is None:
        raise NotFound("That backup's file isn't on the server.")
    backups.AuditService(db).record(None, current.id, "backups.downloaded", "backup_runs", run_id, {"format": format})
    if format == "dump":
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    def chunks():
        with gzip.open(path, "rb") as f:
            while block := f.read(1 << 20):
                yield block
    name = path.name.removesuffix(".gz")
    return StreamingResponse(chunks(), media_type="application/sql",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/backups/{run_id}/restore")
def backup_restore(run_id: uuid.UUID, data: BackupRestoreIn, db: Session = DB,
                   current: CurrentUser = Depends(platform_permission("platform.backups.manage"))):
    """Put the whole database back to this backup. The server starts within a minute; it can be called off till then.
    Needs the person's own password again."""
    confirm_identity(current, data.password)
    return backups.request_restore(db, current.id, run_id)


@router.delete("/backups/restore")
def backup_restore_cancel(db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.backups.manage"))):
    return backups.cancel_restore(db, current.id)


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = DB, current: CurrentUser = Depends(platform_permission("platform.clients.view"))):
    return ClientService(db, current).plans()
