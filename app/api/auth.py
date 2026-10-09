"""Sign-in, sign-out, who am I, and changing your own password."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.db import DB
from app.core.security import CurrentUser, get_user_allowing_password_change
from app.schemas import LoginIn, MeOut, PasswordChangeIn, WorkspaceOut
from app.services.auth import AuthService, me_from_current, workspace_of

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/workspace", response_model=WorkspaceOut)
def workspace(request: Request):
    """Which centre this address belongs to, for the sign-in page. Needs no sign-in."""
    return workspace_of(request)


@router.post("/auth/login", response_model=MeOut)
def login(data: LoginIn, request: Request, response: Response, db: Session = DB):
    return AuthService(db).login(request, response, data.email, data.password)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = DB):
    # Works even with an expired session, so the cookie is always cleared.
    AuthService(db).logout(request, response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=MeOut)
def me(request: Request, current: CurrentUser = Depends(get_user_allowing_password_change)):
    return me_from_current(request, current)


@router.post("/auth/password", response_model=MeOut)
def change_password(data: PasswordChangeIn, request: Request, db: Session = DB,
                    current: CurrentUser = Depends(get_user_allowing_password_change)):
    AuthService(db).change_password(current, data.current_password, data.new_password)
    return me_from_current(request, current)
