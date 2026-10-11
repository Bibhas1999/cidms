"""Shapes for managing API keys (Settings → API & integrations). The integration API's own shapes are in
app/schemas_api_v1.py."""

import ipaddress
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.integrations import SCOPES

Scope = Literal["patients:read", "tests:read", "orders:read", "reports:read", "images:read", "doctors:read"]
assert set(Scope.__args__) == set(SCOPES)  # the two lists must not drift apart

MAX_IPS = 20


class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[Scope] = Field(min_length=1, max_length=len(SCOPES))
    expires_on: date | None = None
    allowed_ips: list[str] = Field(default_factory=list, max_length=MAX_IPS)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Give the key a name, such as the system that will use it.")
        return v

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, v: list[str]) -> list[str]:
        return sorted(set(v))

    @field_validator("allowed_ips")
    @classmethod
    def _ips(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            raw = raw.strip()
            if not raw:
                continue
            try:
                net = ipaddress.ip_network(raw, strict=False)
            except ValueError:
                raise ValueError(f"“{raw[:50]}” isn't an IP address or range (like 203.0.113.7 or 203.0.113.0/24).") from None
            if str(net) not in out:
                out.append(str(net))
        return out


class ApiKeyRollIn(BaseModel):
    grace_hours: int = Field(0, ge=0, le=168)


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    allowed_ips: list[str]
    expires_at: datetime | None
    created_by_name: str
    created_at: datetime
    last_used_at: datetime | None
    last_used_ip: str | None
    revoked_at: datetime | None
    revoked_by_name: str
    replaced_by: uuid.UUID | None
    status: Literal["active", "rolling", "revoked", "expired"]


class ApiKeyCreatedOut(BaseModel):
    """The only answer that ever carries the key itself."""
    api_key: ApiKeyOut
    key: str


class ApiRequestOut(BaseModel):
    id: int
    key_id: uuid.UUID | None
    key_name: str
    key_prefix: str
    method: str
    path: str
    status: int
    duration_ms: int
    ip_address: str | None
    created_at: datetime
