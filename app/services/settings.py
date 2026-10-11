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

    def set_wordmark(self, data: bytes | None) -> TenantSettings:
        """Upload (or with None, remove) the wide logo with the centre's name and slogan."""
        from app.core.storage import wordmark_image
        row = self.get()
        old = row.wordmark_file
        if data is None:
            row.wordmark_data, row.wordmark_mime, row.wordmark_file = "", "", ""
        else:
            image = wordmark_image(data)
            row.wordmark_data, row.wordmark_mime, row.wordmark_file = image.data, image.mime, image.version
        AuditService(self.db).record(row.tenant_id, self.current.id, "settings.wordmark_changed", "tenant", row.tenant_id,
                                     {"wordmark_file": [old, row.wordmark_file]})
        self.db.flush()
        return row

    def set_logo(self, data: bytes) -> TenantSettings:
        from app.core.storage import logo_image
        row = self.get()
        old = row.logo_file
        image = logo_image(data)
        row.logo_data, row.logo_mime, row.logo_file = image.data, image.mime, image.version
        AuditService(self.db).record(row.tenant_id, self.current.id, "settings.logo_changed", "tenant", row.tenant_id,
                                     {"logo_file": [old, row.logo_file]})
        self.db.flush()
        self.db.refresh(row)
        return row
