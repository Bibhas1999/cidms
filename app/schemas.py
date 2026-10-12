"""Request and response shapes for the JSON API."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


# ---------- workspace and sign-in ----------

class WorkspaceLink(BaseModel):
    name: str
    url: str


class WorkspaceOut(BaseModel):
    kind: Literal["client", "platform", "none"]
    name: str = ""
    slug: str = ""
    active: bool = True
    # A centre's own look on its sign-in page and menu.
    brand_color: str = ""
    tagline: str = ""
    logo_url: str = ""
    wordmark_url: str = ""   # the wide logo with name and slogan, when the centre has one
    # Only when no centre is at this address: the product's own address, for its landing page.
    base_domain: str = ""
    platform_subdomain: str = ""
    # Development only, at an address with no workspace: where the workspaces are.
    links: list[WorkspaceLink] = []


class LoginIn(BaseModel):
    # Looked up, not validated: any string that matches an account is fine.
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    remember: bool = False


class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    new_password: str = Field(min_length=1, max_length=200)


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    mobile: str = Field(default="", max_length=20)

    @field_validator("mobile")
    @classmethod
    def _mobile_ok(cls, v: str) -> str:
        return _mobile(v)


class EmailChangeIn(BaseModel):
    email: EmailStr
    current_password: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class RoleOut(Out):
    id: uuid.UUID
    code: str
    name: str
    description: str


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    mobile: str = ""
    avatar_url: str = ""
    roles: list[str]
    permissions: list[str]
    must_change_password: bool
    manage_own_account: bool = False  # may change their own email and password (owner, centre admin, platform staff)
    csrf_token: str
    workspace: WorkspaceOut


# ---------- staff ----------

class StaffOut(Out):
    id: uuid.UUID
    email: str
    full_name: str
    avatar_url: str = ""
    mobile: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    roles: list[RoleOut]


def _mobile(v: str) -> str:
    """A valid mobile for its country, saved as +<code><number>; "" when left empty (see app/core/phone.py)."""
    from app.core.phone import normalise_mobile
    return normalise_mobile(v)


class StaffCreateIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    mobile: str = Field(default="", max_length=20)
    role_ids: list[uuid.UUID] = Field(min_length=1)
    temporary_password: str = Field(default="", max_length=200)  # empty: the centre's default temporary password

    _m = field_validator("mobile")(_mobile)


class StaffUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    mobile: str | None = Field(default=None, max_length=20)
    role_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    _m = field_validator("mobile")(lambda v: _mobile(v) if v is not None else v)


class PasswordResetIn(BaseModel):
    temporary_password: str = Field(default="", max_length=200)  # empty: the default temporary password


# ---------- centre settings ----------

class SettingsIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    tagline: str = Field(default="", max_length=120)
    brand_color: str = Field(default="#0f6e6e", pattern=r"^#[0-9a-fA-F]{6}$")
    address: str = Field(default="", max_length=1000)
    phones: str = Field(default="", max_length=200)
    email: EmailStr | Literal[""] = ""
    gst_number: str = Field(default="", max_length=20, pattern=r"^([0-9A-Z]{15})?$")
    invoice_prefix: str = Field(min_length=1, max_length=10, pattern=r"^[A-Z0-9]+$")
    bill_paper: Literal["A4", "A5"] = "A5"
    max_discount_percent: Decimal = Field(default=Decimal("20"), ge=0, le=100, decimal_places=2)
    bill_footer: str = Field(default="", max_length=2000)
    report_footer: str = Field(default="", max_length=2000)


class SettingsOut(Out, SettingsIn):
    email: str = ""
    logo_file: str = ""
    wordmark_file: str = ""
    updated_at: datetime


# ---------- activity ----------

class ActivityOut(BaseModel):
    id: int
    created_at: datetime
    user_name: str | None
    action: str
    entity: str
    entity_id: str
    details: dict
    ip_address: str | None


# ---------- platform ----------

class PlanOut(Out):
    id: uuid.UUID
    code: str
    name: str
    max_users: int
    max_bills_per_month: int
    storage_gb: int
    price_monthly: Decimal


class ClientOut(Out):
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    status: str
    plan: PlanOut | None
    paid_until: datetime | None
    created_at: datetime


class ClientCreateIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$", description="Lower-case letters, numbers and dashes")
    name: str = Field(min_length=2, max_length=200)
    kind: Literal["diagnostic", "opd", "clinic"] = "diagnostic"
    plan_id: uuid.UUID | None = None
    owner_name: str = Field(min_length=2, max_length=200)
    owner_email: EmailStr
    owner_temporary_password: str = Field(min_length=1, max_length=200)


class ClientUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    kind: Literal["diagnostic", "opd", "clinic"] | None = None
    status: Literal["active", "suspended"] | None = None
    plan_id: uuid.UUID | None = None


# ---------- browser error reports ----------

class ClientErrorIn(BaseModel):
    message: str = Field(max_length=2000)
    stack: str = Field(default="", max_length=8000)
    url: str = Field(default="", max_length=500)
    kind: Literal["boundary", "error", "unhandledrejection", "api"] = "error"


class BackupSettingsIn(BaseModel):
    enabled: bool = True
    every_days: int = Field(1, ge=1, le=365)
    at_time: str = Field("23:00", max_length=5)
    keep_days: int = Field(30, ge=1, le=3650)
