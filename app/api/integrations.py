"""Settings → API & integrations: API keys for other systems (signed-in owner or centre admin), and the
integration API itself at /api/v1 (app/api/v1.py). `install(app)` adds both."""

import uuid

from fastapi import APIRouter, Depends, FastAPI, Query, status
from sqlalchemy.orm import Session

from app.api.deps import Paging, paging, require_any
from app.core.db import DB
from app.core.security import CurrentUser
from app.schemas import Page
from app.schemas_integrations import ApiKeyCreatedOut, ApiKeyCreateIn, ApiKeyOut, ApiKeyRollIn, ApiRequestOut
from app.services.integrations import ApiKeyService, key_out

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
manage = require_any("integrations.manage", None)


@router.get("/keys", response_model=list[ApiKeyOut])
def list_keys(db: Session = DB, current: CurrentUser = Depends(manage)):
    return [key_out(k) for k in ApiKeyService(db, current).all()]


@router.post("/keys", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_key(data: ApiKeyCreateIn, db: Session = DB, current: CurrentUser = Depends(manage)):
    key, secret = ApiKeyService(db, current).create(data.name, list(data.scopes), data.allowed_ips, data.expires_on)
    return {"api_key": key_out(key), "key": secret}


@router.post("/keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(key_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(manage)):
    return key_out(ApiKeyService(db, current).revoke(key_id))


@router.post("/keys/{key_id}/roll", response_model=ApiKeyCreatedOut)
def roll_key(key_id: uuid.UUID, data: ApiKeyRollIn | None = None, db: Session = DB, current: CurrentUser = Depends(manage)):
    key, secret = ApiKeyService(db, current).roll(key_id, data.grace_hours if data else 0)
    return {"api_key": key_out(key), "key": secret}


@router.get("/usage", response_model=Page[ApiRequestOut])
def usage(key_id: uuid.UUID | None = Query(None), p: Paging = Depends(paging), db: Session = DB,
          current: CurrentUser = Depends(manage)):
    rows, total = ApiKeyService(db, current).usage(key_id, p.page, p.size)
    items = [ApiRequestOut(id=r.id, key_id=r.key_id, key_name=name, key_prefix=prefix, method=r.method, path=r.path,
                           status=r.status, duration_ms=r.duration_ms, ip_address=str(r.ip_address) if r.ip_address else None,
                           created_at=r.created_at) for r, name, prefix in rows]
    return Page(items=items, total=total, page=p.page, size=p.size)


def install(app: FastAPI) -> None:
    """The key management routes, and the integration API mounted at /api/v1 with its own docs."""
    from app.api.v1 import create_v1_app
    app.include_router(router)
    app.mount("/api/v1", create_v1_app())
