"""A centre's own backups (Settings > Backups, the owner) and the same for any client from the platform."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import client_user, platform_permission
from app.core.db import DB
from app.core.errors import NotFound
from app.core.security import CurrentUser, require
from app.models import Tenant
from app.schemas import BackupRestoreIn, BackupSettingsIn
from app.services import client_backups as cb
from app.services.audit import AuditService

router = APIRouter(tags=["backups"])
Format = Literal["xlsx", "sql", "copy"]


def _owner(current: CurrentUser = Depends(require("backups.manage"))) -> CurrentUser:
    return client_user(current)


def _download(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, backup_id: uuid.UUID, fmt: str):
    b = cb.get_backup(db, tenant_id, backup_id)
    AuditService(db).record(tenant_id, user_id, "backups.downloaded", "client_backups", b.id, {"format": fmt})
    stem = b.file.removesuffix(".cidms.json.gz")
    if fmt == "copy":
        return FileResponse(cb.path_of(b), media_type="application/gzip", filename=b.file)
    data = cb.read_copy(b)
    if fmt == "sql":
        return Response(cb.to_sql(data), media_type="application/sql",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.sql"'})
    return Response(cb.to_xlsx(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"'})


# ---------- the centre's own (owner) ----------

@router.get("/api/backups")
def overview(db: Session = DB, current: CurrentUser = Depends(_owner)):
    """The centre's backup schedule and its last 30 copies and restores."""
    return cb.overview(db, current.tenant.id)


@router.put("/api/backups")
def schedule(data: BackupSettingsIn, db: Session = DB, current: CurrentUser = Depends(_owner)):
    return cb.update(db, current.tenant.id, current.id, data.enabled, data.every_days, data.at_time, data.keep_days)


@router.post("/api/backups/run")
def back_up_now(db: Session = DB, current: CurrentUser = Depends(_owner)):
    return cb.request_backup(db, current.tenant.id, current.id)


@router.get("/api/backups/{backup_id}/download")
def download(backup_id: uuid.UUID, format: Format = "xlsx", db: Session = DB, current: CurrentUser = Depends(_owner)):
    """xlsx: a workbook to read; sql: INSERT statements; copy: the backup file itself (what restores use)."""
    return _download(db, current.tenant.id, current.id, backup_id, format)


@router.post("/api/backups/{backup_id}/restore")
def restore(backup_id: uuid.UUID, data: BackupRestoreIn, db: Session = DB, current: CurrentUser = Depends(_owner)):
    """Put all the centre's records back to this copy. A fresh copy is made first; everyone signs in again."""
    return cb.request_restore(db, current.tenant.id, current.id, backup_id)


# ---------- any client, from the platform ----------

def _client(db: Session, tenant_id: uuid.UUID) -> Tenant:
    t = db.get(Tenant, tenant_id)
    if t is None:
        raise NotFound("There's no such client.")
    return t


PLATFORM = Depends(platform_permission("platform.backups.manage"))


@router.get("/api/platform/clients/{tenant_id}/backups")
def client_overview(tenant_id: uuid.UUID, db: Session = DB, current: CurrentUser = PLATFORM):
    return cb.overview(db, _client(db, tenant_id).id)


@router.post("/api/platform/clients/{tenant_id}/backups/run")
def client_back_up_now(tenant_id: uuid.UUID, db: Session = DB, current: CurrentUser = PLATFORM):
    return cb.request_backup(db, _client(db, tenant_id).id, current.id)


@router.get("/api/platform/clients/{tenant_id}/backups/{backup_id}/download")
def client_download(tenant_id: uuid.UUID, backup_id: uuid.UUID, format: Format = "xlsx", db: Session = DB,
                    current: CurrentUser = PLATFORM):
    return _download(db, _client(db, tenant_id).id, current.id, backup_id, format)


@router.post("/api/platform/clients/{tenant_id}/backups/{backup_id}/restore")
def client_restore(tenant_id: uuid.UUID, backup_id: uuid.UUID, data: BackupRestoreIn, db: Session = DB,
                   current: CurrentUser = PLATFORM):
    return cb.request_restore(db, _client(db, tenant_id).id, current.id, backup_id)
