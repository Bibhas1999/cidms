"""Agreeing the key for encrypted request and response bodies (see app/core/payload.py)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.limits import RateLimiter
from app.core.logging import client_ip
from app.core.payload import agree

router = APIRouter(prefix="/api/payload", tags=["payload"])
key_limiter = RateLimiter("payload-key", limit=120, per_seconds=300)  # a tab agrees one key per load


class KeyIn(BaseModel):
    public_key: str = Field(min_length=40, max_length=200)


class KeyOut(BaseModel):
    key_id: str
    public_key: str
    mode: str


@router.post("/key", response_model=KeyOut)
async def new_key(data: KeyIn, request: Request):
    mode = get_settings().payload_encryption
    if mode == "off":
        raise NotFound("Encrypted bodies are switched off.")
    key_limiter.hit(client_ip(request) or "unknown", "Too many requests. Please wait a few minutes and reload the page.")
    key_id, public = await run_in_threadpool(agree, data.public_key)
    return KeyOut(key_id=key_id, public_key=public, mode=mode)
