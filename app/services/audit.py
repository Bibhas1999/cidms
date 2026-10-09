"""The activity log: one row per sign-in, sign-out and change, with who, when, from where and the request ID."""

import uuid

from sqlalchemy.orm import Session

from app.core.logging import redact, request_client, request_id
from app.models import ActivityLog


class AuditService:
    def __init__(self, db: Session):
        self.db = db

    def record(self, tenant_id: uuid.UUID | None, user_id: uuid.UUID | None, action: str,
               entity: str = "", entity_id: object = "", details: dict | None = None) -> None:
        ip, agent = request_client.get()
        self.db.add(ActivityLog(
            tenant_id=tenant_id, user_id=user_id, action=action, entity=entity, entity_id=str(entity_id or ""),
            details=redact(details or {}), ip_address=ip or None, user_agent=agent, request_id=request_id.get(),
        ))
