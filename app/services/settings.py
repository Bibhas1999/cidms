"""A centre's own details: what its bills and reports show."""

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.security import CurrentUser
from app.models import TenantSettings
from app.schemas import SettingsIn
from app.services.audit import AuditService


class SettingsService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current

    def get(self) -> TenantSettings:
        row = self.db.get(TenantSettings, self.current.user.tenant_id)
        if row is None:
            raise NotFound("This centre has no settings yet.")
        return row

    def update(self, data: SettingsIn) -> TenantSettings:
        row = self.get()
        changes = {}
        for field, value in data.model_dump().items():
            if getattr(row, field) != value:
                changes[field] = [getattr(row, field), value]
                setattr(row, field, value)
        if changes:
            AuditService(self.db).record(row.tenant_id, self.current.id, "settings.updated", "tenant", row.tenant_id, changes)
            self.db.flush()
            self.db.refresh(row)
        return row

    def set_logo(self, data: bytes) -> TenantSettings:
        from app.core.storage import save_logo
        row = self.get()
        old = row.logo_file
        row.logo_file = save_logo(row.tenant_id, data)
        AuditService(self.db).record(row.tenant_id, self.current.id, "settings.logo_changed", "tenant", row.tenant_id,
                                     {"logo_file": [old, row.logo_file]})
        self.db.flush()
        self.db.refresh(row)
        return row
