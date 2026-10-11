"""Request and response shapes for roles and permissions (Settings > Roles & permissions)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _clean_permissions(v: list[str]) -> list[str]:
    return sorted({p.strip() for p in v if p and p.strip()})


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=300)
    permissions: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("name")
    @classmethod
    def _name_long_enough(cls, v: str) -> str:
        if len(v) < 2:
            raise ValueError("Give the role a name of at least 2 characters.")
        return v

    _p = field_validator("permissions")(_clean_permissions)


class RoleCopyIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)


class StaffRolesIn(BaseModel):
    role_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class PermissionOut(BaseModel):
    code: str
    label: str
    description: str
    held: bool = True  # whether the person asking holds it (only those can be given to a role)


class PermissionGroupOut(BaseModel):
    key: str
    label: str
    description: str
    permissions: list[PermissionOut]


class RoleDetailOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    scope: str
    is_builtin: bool
    permissions: list[str]
    member_count: int
    editable: bool          # the person asking may change or delete it
    assignable: bool        # the person asking may give it to someone
    locked_reason: str = ""  # why it can't be changed, in words, when editable is False
    created_by_name: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RoleMemberOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    is_active: bool
    avatar_url: str = ""
