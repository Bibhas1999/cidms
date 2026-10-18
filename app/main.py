"""Application factory: one FastAPI app serving the JSON API and the built Svelte app from the same address,
so the HttpOnly session cookie works everywhere without CORS."""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import (
    analytics,
    auth,
    billing,
    catalogue_import,
    centre,
    payload,
    platform,
    reports,
    staff,
    system,
    test_reports,  # test reports, imaging, DICOMweb proxy, viewer, WhatsApp
    uploads,  # files sent in pieces, with pause and resume
)
from app.core.config import get_settings
from app.core.db import is_transient
from app.core.errors import DomainError
from app.core.limits import BodySizeMiddleware
from app.core.logging import RequestLogMiddleware, configure_logging, request_id
from app.core.payload import PayloadCryptoMiddleware
from app.core.tenancy import TenancyMiddleware

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
log = logging.getLogger("app")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    CSP = "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",  # style attributes set by components (widths, positions)
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ])

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", self.CSP)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if get_settings().is_production:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/") or "text/html" in h.get("content-type", ""):
            h.setdefault("Cache-Control", "no-store")  # patient data never sits in a browser or proxy cache
        return response


def _error(status: int, message: str, field: str | None = None, detail: list | None = None, headers: dict | None = None) -> JSONResponse:
    """Every error has the same shape: a sentence people can read, and the request ID to quote to support."""
    body: dict = {"message": message, "request_id": request_id.get()}
    if field:
        body["field"] = field
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, headers=headers)


def _field_name(loc) -> str:
    names = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(names) or "__all__"


def _clean(msg: str) -> str:
    if msg.startswith("value is not a valid email address"):
        return "Enter a valid email address."
    if msg == "Field required":
        return "This is required."
    return msg.removeprefix("Value error, ").removeprefix("Assertion failed, ")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return _error(exc.status, exc.message, exc.field, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        detail = [{"field": _field_name(e["loc"]), "message": _clean(e["msg"])} for e in exc.errors()]
        first = detail[0] if detail else {"field": None, "message": "That request wasn't valid."}
        return _error(422, first["message"], first["field"], detail)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        messages = {404: "We couldn't find that.", 405: "That isn't allowed here."}
        return _error(exc.status_code, messages.get(exc.status_code, str(exc.detail)))

    @app.exception_handler(DBAPIError)
    async def database_error(request: Request, exc: DBAPIError):
        if not is_transient(exc):
            return await unexpected(request, exc)
        log.warning("Temporary database problem: %s", type(exc.orig).__name__ if exc.orig else exc)
        return _error(503, "CIDMS is busy for a moment. Please try again.", headers={"Retry-After": "2"})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error(500, "Something went wrong on our side. It's been logged; please try again.")


def mount_web(app: FastAPI) -> None:
    """Serve the built Svelte app: its hashed assets, and index.html for every other non-API address."""
    index = WEB_DIST / "index.html"
    if not index.exists():
        log.warning("The web app isn't built yet (web/dist). In development run it with: cd web && npm run dev")
        return
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return _error(404, "We couldn't find that.")
        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and WEB_DIST in candidate.parents:
            if path == "sw.js":  # the service worker: always check for a new one
                return FileResponse(candidate, media_type="text/javascript", headers={"Cache-Control": "no-cache"})
            if path == "manifest.webmanifest":
                return FileResponse(candidate, media_type="application/manifest+json")
            return FileResponse(candidate)  # icons and other files at the top level
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    # The last added runs first: the request log wraps everything, so every line carries the request ID.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(PayloadCryptoMiddleware)  # encrypted bodies: decrypted before, and encrypted after, everything else
    app.add_middleware(BodySizeMiddleware)
    app.add_middleware(TenancyMiddleware)
    if settings.environment == "development":  # the Dev monitor (/dev/monitor): never in tests or production
        from app.api import dev
        from app.core.db import engine
        from app.core.devmonitor import install as install_dev_monitor
        install_dev_monitor(app, engine)  # inside the request log, so its entries carry the request ID
        app.include_router(dev.router)
    app.add_middleware(RequestLogMiddleware)
    install_error_handlers(app)

    for module in (system, auth, payload, staff, centre, billing, catalogue_import, platform, reports, analytics, uploads):
        app.include_router(module.router)
    app.include_router(test_reports.router)
    from app.api.client_backups import router as client_backups_router  # Settings > Backups, per centre
    app.include_router(client_backups_router)
    from app.api.roles import router as roles_router  # Settings > Roles & permissions
    app.include_router(roles_router)
    from app.api.integrations import install as install_integrations  # API keys, and the integration API at /api/v1
    install_integrations(app)
    from app.api.notifications import router as notifications_router  # the bell, live stream, background job results
    app.include_router(notifications_router)
    mount_web(app)
    return app


app = create_app()
