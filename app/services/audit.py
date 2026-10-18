"""The activity log: one row per sign-in, sign-out and change, with who, when, from where and the request ID; and
who opened a patient's records (a patient, a bill, a report), at most once per person and record every 10 minutes."""

import threading
import time
import uuid

from sqlalchemy.orm import Session

from app.core.logging import redact, request_client, request_id
from app.models import ActivityLog

VIEW_EVERY_S = 600
_viewed: dict[tuple, float] = {}
_viewed_lock = threading.Lock()


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

    def viewed(self, tenant_id: uuid.UUID | None, user_id: uuid.UUID | None, entity: str, entity_id: object,
               details: dict | None = None) -> None:
        """Someone opened a patient's record: "<entity>.viewed". Repeats within 10 minutes aren't logged again."""
        key = (user_id, entity, str(entity_id), (details or {}).get("as"))
        now = time.monotonic()
        with _viewed_lock:
            if now - _viewed.get(key, -VIEW_EVERY_S) < VIEW_EVERY_S:
                return
            _viewed[key] = now
            if len(_viewed) > 20_000:
                for k in [k for k, t in _viewed.items() if now - t >= VIEW_EVERY_S]:
                    del _viewed[k]
        self.record(tenant_id, user_id, f"{entity}.viewed", entity, entity_id, details)
