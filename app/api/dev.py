"""The Dev monitor's live stream (development only): requests, errors and slow queries as they happen, and every
couple of seconds the state of the background jobs, uploads in progress and the database pool."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.db import engine, scoped_session
from app.core.devmonitor import monitor
from app.core.errors import Forbidden, NotFound
from app.core.security import CurrentUser, get_current_user
from app.models import Job, Upload

router = APIRouter(prefix="/api/dev", tags=["dev"])
MAX_STREAM_S = 30 * 60


def developer(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if get_settings().environment != "development":
        raise NotFound("Not found.")
    if not (current.can("dev.monitor") or current.can("platform.dev.monitor")):
        raise Forbidden("Only the owner, admins and developers can open the dev monitor.")
    return current


def _system() -> dict:
    with scoped_session(platform=True) as db:
        jobs = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
        failed = [{"kind": k, "error": (e or "")[:300], "at": a} for k, e, a in db.execute(
            select(Job.kind, Job.last_error, Job.run_at).where(Job.status == "failed").order_by(Job.run_at.desc()).limit(5)).all()]
        uploads = [{"filename": f, "purpose": p, "received": r, "size": s} for f, p, r, s in db.execute(
            select(Upload.filename, Upload.purpose, Upload.received, Upload.size).where(Upload.received < Upload.size)
            .order_by(Upload.updated_at.desc()).limit(10)).all()]
    pool = engine.pool
    return {"jobs": jobs, "failed_jobs": failed, "uploads": uploads,
            "pool": {"size": pool.size(), "checked_out": pool.checkedout(), "overflow": pool.overflow()}}


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


async def _events(request: Request):
    last = max(0, monitor.seq - 200)  # start with the most recent history
    began = time.monotonic()
    tick = 0
    while time.monotonic() - began < MAX_STREAM_S:
        if await request.is_disconnected():
            return
        fresh = monitor.since(last)
        if fresh:
            last = fresh[-1]["seq"]
            yield _sse("events", fresh)
        payload = {"stats": monitor.stats()}
        if tick % 2 == 0:
            try:
                payload["system"] = await run_in_threadpool(_system)
            except Exception as exc:  # the database may be down: say so rather than ending the stream
                payload["system"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        yield _sse("stats", payload)
        tick += 1
        await asyncio.sleep(1)
    yield _sse("reconnect", {})


@router.get("/stream")
async def stream(request: Request, current: CurrentUser = Depends(developer)):
    return StreamingResponse(_events(request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
