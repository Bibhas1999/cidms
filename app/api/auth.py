"""Sign-in, sign-out, who am I, and changing your own password."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core import mailer
from app.core.config import get_settings
from app.core.db import DB
from app.core.security import CurrentUser, get_current_user, get_user_allowing_password_change
from app.core.storage import MAX_LOGO_BYTES
from app.schemas import EmailChangeIn, ForgotPasswordIn, LoginIn, MeOut, PasswordChangeIn, ProfileIn, ResetPasswordIn, WorkspaceOut
from app.schemas import WorkspaceLink as WorkspaceLinkOut
from app.services.auth import AuthService, me_from_current, workspace_of

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/workspace", response_model=WorkspaceOut)
def workspace(request: Request):
    """Which centre this address belongs to, for the sign-in page. Needs no sign-in."""
    out = workspace_of(request)
    s = get_settings()
    if out.kind == "none":
        out.base_domain = s.base_domain
        out.platform_subdomain = s.platform_subdomain
    if out.kind == "none" and not s.is_production:
        # On a developer's machine, plain localhost lists the workspaces to open. Never in production:
        # the list of clients isn't public.
        from sqlalchemy import select

        from app.core.db import scoped_session
        from app.models import Tenant
        port = request.url.port
        suffix = f"{s.base_domain}:{port}" if port and port not in (80, 443) else s.base_domain
        scheme = request.url.scheme
        with scoped_session(platform=True) as db:
            tenants = db.execute(select(Tenant.name, Tenant.slug).where(Tenant.status == "active").order_by(Tenant.name).limit(20)).all()
        out.links = [WorkspaceLinkOut(name=n, url=f"{scheme}://{slug}.{suffix}") for n, slug in tenants]
        out.links.append(WorkspaceLinkOut(name="Platform admin", url=f"{scheme}://{s.platform_subdomain}.{suffix}"))
    return out


def _centre_image(request: Request, kind: str) -> Response:
    from app.core.db import scoped_session
    from app.core.errors import NotFound
    from app.core.storage import decode
    from app.models import TenantSettings
    tenant = request.state.tenant
    if tenant is None:
        raise NotFound("No logo here.")
    with scoped_session(tenant.id) as db:
        row = db.get(TenantSettings, tenant.id)
        content, mime = (decode(getattr(row, f"{kind}_data")), getattr(row, f"{kind}_mime")) if row else (None, "")
    if not content:
        raise NotFound("No logo here.")
    return Response(content, media_type=mime or "image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/workspace/logo", include_in_schema=False)
def workspace_logo(request: Request):
    """The centre's square logo, for its sign-in page and bills. Needs no sign-in."""
    return _centre_image(request, "logo")


@router.get("/workspace/wordmark", include_in_schema=False)
def workspace_wordmark(request: Request):
    """The centre's wide logo with its name and slogan. Needs no sign-in (it's on the sign-in page)."""
    return _centre_image(request, "wordmark")


@router.post("/auth/login", response_model=MeOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = DB):
    return AuthService(db).login(request, response, data.email, data.password, data.remember)


@router.post("/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(data: ForgotPasswordIn, request: Request, background: BackgroundTasks, db: Session = DB):
    """Always the same answer, whether or not the email has an account here."""
    email = AuthService(db).forgot_password(request, data.email)
    if email:
        background.add_task(mailer.send, *email)  # after the reply, so timing gives nothing away
    return {"message": "If that email has an account here, a link to reset the password is on its way. It works for 30 minutes."}


@router.post("/auth/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(data: ResetPasswordIn, request: Request, db: Session = DB):
    AuthService(db).reset_password(request, data.token, data.new_password)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = DB):
    # Works even with an expired session, so the cookie is always cleared.
    AuthService(db).logout(request, response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=MeOut)
def me(request: Request, current: CurrentUser = Depends(get_user_allowing_password_change)):
    return me_from_current(request, current)


@router.put("/auth/profile", response_model=MeOut)
def update_profile(data: ProfileIn, request: Request, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    """Your own name and mobile. The email you sign in with changes at PUT /api/auth/email (owner and admin only)."""
    AuthService(db).update_profile(current, data.full_name, data.mobile)
    return me_from_current(request, current)


@router.post("/auth/avatar", response_model=MeOut)
async def upload_avatar(avatar: UploadFile, request: Request, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    data = await avatar.read(MAX_LOGO_BYTES + 1)
    AuthService(db).set_avatar(current, data)
    return me_from_current(request, current)


@router.delete("/auth/avatar", response_model=MeOut)
def remove_avatar(request: Request, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    AuthService(db).set_avatar(current, None)
    return me_from_current(request, current)


@router.get("/users/{user_id}/avatar", include_in_schema=False)
def user_avatar(user_id: uuid.UUID, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    """A colleague's picture. Only people in the same centre (or platform) can see it."""
    from app.core.errors import NotFound
    from app.core.storage import decode
    from app.models import User
    user = db.get(User, user_id)  # row-level security: other centres' people aren't visible
    if user is None or user.tenant_id != current.user.tenant_id:
        raise NotFound("No picture.")
    content = decode(user.avatar_data)
    if not content:
        raise NotFound("No picture.")
    return Response(content, media_type=user.avatar_mime or "image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.put("/auth/email", response_model=MeOut)
def change_email(data: EmailChangeIn, request: Request, db: Session = DB, current: CurrentUser = Depends(get_current_user)):
    """The owner or centre admin changes the email they sign in with (needs their current password)."""
    AuthService(db).change_email(current, data.email, data.current_password)
    return me_from_current(request, current)


@router.post("/auth/password", response_model=MeOut)
def change_password(data: PasswordChangeIn, request: Request, db: Session = DB,
                    current: CurrentUser = Depends(get_user_allowing_password_change)):
    AuthService(db).change_password(current, data.current_password, data.new_password)
    return me_from_current(request, current)
