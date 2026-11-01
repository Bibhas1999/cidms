"""A centre's settings and its activity log (and the platform's own activity log)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Paging, client_user, paging, require_any
from app.core.db import DB
from app.core.security import CurrentUser, require
from app.core.storage import MAX_LOGO_BYTES
from app.models import ActivityLog
from app.schemas import ActivityOut, DiscountLimitIn, Page, SettingsIn, SettingsOut
from app.services.settings import SettingsService

router = APIRouter(prefix="/api", tags=["centre"])


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = DB, current: CurrentUser = Depends(client_user)):
    return SettingsService(db, current).get()


@router.put("/settings", response_model=SettingsOut)
def update_settings(data: SettingsIn, db: Session = DB, current: CurrentUser = Depends(require("settings.manage"))):
    return SettingsService(db, client_user(current)).update(data)


@router.put("/settings/discount-limit", response_model=SettingsOut)
def update_discount_limit(data: DiscountLimitIn, db: Session = DB,
                          current: CurrentUser = Depends(require("billing.discount_limit.manage"))):
    return SettingsService(db, client_user(current)).update_discount_limit(data.max_discount_percent)


@router.post("/settings/wordmark", response_model=SettingsOut)
async def upload_wordmark(wordmark: UploadFile, db: Session = DB, current: CurrentUser = Depends(require("settings.manage"))):
    """The wide logo with the centre's name and slogan (PNG, JPG or WebP, under 2 MB), stored in the database."""
    data = await wordmark.read(MAX_LOGO_BYTES + 1)
    return SettingsService(db, client_user(current)).set_wordmark(data)


@router.delete("/settings/wordmark", response_model=SettingsOut)
def remove_wordmark(db: Session = DB, current: CurrentUser = Depends(require("settings.manage"))):
    return SettingsService(db, client_user(current)).set_wordmark(None)


@router.post("/settings/logo", response_model=SettingsOut)
async def upload_logo(logo: UploadFile, db: Session = DB, current: CurrentUser = Depends(require("settings.manage"))):
    data = await logo.read(MAX_LOGO_BYTES + 1)
    return SettingsService(db, client_user(current)).set_logo(data)


@router.get("/activity", response_model=Page[ActivityOut])
def activity(action: str = Query("", max_length=60), user_id: uuid.UUID | None = None,
             since: datetime | None = None, until: datetime | None = None, p: Paging = Depends(paging),
             db: Session = DB, current: CurrentUser = Depends(require_any("activity.view", "platform.activity.view"))):
    tenant_id = current.user.tenant_id
    q = select(ActivityLog).where(ActivityLog.tenant_id.is_(None) if tenant_id is None else ActivityLog.tenant_id == tenant_id)
    if action:
        q = q.where(ActivityLog.action.startswith(action))
    if user_id:
        q = q.where(ActivityLog.user_id == user_id)
    if since:
        q = q.where(ActivityLog.created_at >= since)
    if until:
        q = q.where(ActivityLog.created_at < until)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc()).offset((p.page - 1) * p.size).limit(p.size)).all()
    items = [ActivityOut(id=r.id, created_at=r.created_at, user_name=r.user.full_name if r.user else None, action=r.action,
                         entity=r.entity, entity_id=r.entity_id, details=r.details,
                         ip_address=str(r.ip_address) if r.ip_address else None) for r in rows]
    return Page(items=items, total=total, page=p.page, size=p.size)
