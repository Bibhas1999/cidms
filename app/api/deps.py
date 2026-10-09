"""Shared route dependencies: paging, and which workspace a route belongs to."""

from dataclasses import dataclass

from fastapi import Depends, Query, Request

from app.core.errors import Forbidden, NotFound
from app.core.security import CurrentUser, get_current_user


@dataclass
class Paging:
    page: int
    size: int


def paging(page: int = Query(1, ge=1, le=100_000), size: int = Query(25, ge=1, le=100)) -> Paging:
    return Paging(page, size)


def require_any(client_permission: str | None, platform_permission: str | None):
    """Signed in, and holding the permission that applies to this workspace (client or platform)."""
    def dep(request: Request, current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        needed = platform_permission if current.is_platform else client_permission
        if needed is None:
            raise NotFound("Not available here.")
        if not current.can(needed):
            raise Forbidden("You don't have permission to do that.")
        return current
    return dep


def client_user(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current.is_platform:
        raise NotFound("Not available in the platform workspace.")
    return current


def platform_permission(permission: str):
    def dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current.is_platform:
            raise NotFound("Not found.")
        if not current.can(permission):
            raise Forbidden("You don't have permission to do that.")
        return current
    return dep
