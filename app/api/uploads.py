"""Resumable uploads: start one, send it piece by piece (PUT with Content-Range), ask how far it has got, or cancel it.
The finished file is taken by the feature it's for (e.g. POST /api/catalogue/{kind}/import). Kept in the database."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import client_user
from app.core.db import DB
from app.core.errors import Invalid
from app.core.security import CurrentUser
from app.services.uploads import MAX_CHUNK, UploadService, UploadState

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class UploadStartIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    purpose: Literal["catalogue", "report_pdf"]


class UploadOut(BaseModel):
    id: uuid.UUID
    filename: str
    size: int
    received: int
    chunk_size: int
    complete: bool


def _out(s: UploadState) -> UploadOut:
    return UploadOut(id=s.id, filename=s.filename, size=s.size, received=s.received, chunk_size=s.chunk_size, complete=s.complete)


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def start(data: UploadStartIn, db: Session = DB, current: CurrentUser = Depends(client_user)):
    return _out(UploadService(db, current).start(data.filename, data.size, data.purpose))


@router.get("/{upload_id}", response_model=UploadOut)
def progress(upload_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    return _out(UploadService(db, current).status(upload_id))


@router.put("/{upload_id}", response_model=UploadOut)
async def piece(upload_id: uuid.UUID, request: Request, db: Session = DB, current: CurrentUser = Depends(client_user)):
    # Read the whole piece first (bounded), so a connection that drops half-way changes nothing.
    body = bytearray()
    async for block in request.stream():
        body += block
        if len(body) > MAX_CHUNK:
            raise Invalid("That piece is too large.", "content_range")
    service = UploadService(db, current)
    return _out(await run_in_threadpool(service.receive, upload_id, request.headers.get("content-range", ""), bytes(body)))


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel(upload_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(client_user)):
    UploadService(db, current).cancel(upload_id)
