"""Health checks and error reports from the browser."""

import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import engine
from app.core.limits import client_error_limiter
from app.core.logging import client_ip
from app.schemas import ClientErrorIn

router = APIRouter(tags=["system"])
log = logging.getLogger("app.browser")


@router.get("/healthz", include_in_schema=False)
def healthz():
    """Liveness: the app is running. Doesn't touch the database."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz():
    """Readiness: the app can reach its database."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logging.getLogger("app").warning("Readiness check failed: %s", type(exc).__name__)
        return JSONResponse({"status": "unavailable", "database": "unreachable"}, status_code=503, headers={"Retry-After": "5"})
    return {"status": "ok", "database": "ok"}


@router.post("/api/client-errors", status_code=status.HTTP_204_NO_CONTENT)
def client_error(data: ClientErrorIn, request: Request):
    """A screen crashed or a script failed in someone's browser. Logged with the request ID so it can be
    matched to server logs; needs no sign-in (it may be the sign-in page that failed)."""
    client_error_limiter.hit(f"ip:{client_ip(request)}", "Too many error reports.")
    log.warning("Browser error: %s", data.message[:500], extra={
        "client_error": {"kind": data.kind, "url": data.url, "stack": data.stack[:4000]},
        "user_id": getattr(request.state, "user_id", None),
    })
