"""Uploads sent in pieces, so a file survives a dropped connection and can be paused and picked up again.

The browser starts an upload (file name, size and what it's for), then sends the file in order, one piece per
request, each with a Content-Range header. Pieces are kept in the database (the uploads table, base64, appended as
they arrive; nothing is written to the server's disk) and every answer says how much has arrived, so the browser can
always carry on from there: after a pause, a dropped connection or a reload. When every byte is in, the feature the
file is for takes it (take()) and the row is removed. Uploads nobody finished are removed after a day.

Every piece but the last is a whole number of 3-byte groups, so its base64 can simply be added to the end."""

import base64
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePosixPath

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, undefer

from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.security import CurrentUser
from app.models import Upload, utcnow

CHUNK_SIZE = 255 * 1024        # what the browser sends at a time (a multiple of 3)
MAX_CHUNK = 4 * 1024 * 1024    # the most one request may carry
STALE = timedelta(days=1)

# What each kind of upload is for: who may send it, the largest file, and the file types taken.
PURPOSES: dict[str, dict] = {
    "catalogue": {"permission": "catalogue.manage", "max_bytes": 10 * 1024 * 1024, "extensions": (".xlsx", ".csv")},
    "report_pdf": {"permission": "reports.write", "max_bytes": 20 * 1024 * 1024, "extensions": (".pdf",)},
}

_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_GONE = "That upload has expired or was cancelled. Choose the file again."


@dataclass
class UploadState:
    id: uuid.UUID
    filename: str
    size: int
    received: int
    purpose: str
    chunk_size: int = CHUNK_SIZE

    @property
    def complete(self) -> bool:
        return self.received >= self.size


def _state(u: Upload) -> UploadState:
    return UploadState(u.id, u.filename, u.size, u.received, u.purpose)


class UploadService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id

    def _get(self, upload_id: uuid.UUID, lock: bool = False, with_data: bool = False) -> Upload:
        q = select(Upload).where(Upload.tenant_id == self.tenant_id, Upload.id == upload_id, Upload.user_id == self.current.id)
        if with_data:
            q = q.options(undefer(Upload.data))
        row = self.db.scalar(q.with_for_update() if lock else q)
        if row is None:  # only the person who started it, and never across clients (row-level security too)
            raise NotFound(_GONE)
        return row

    def start(self, filename: str, size: int, purpose: str) -> UploadState:
        rules = PURPOSES.get(purpose)
        if rules is None:
            raise Invalid("Uploads of that kind aren't taken.", "purpose")
        if not self.current.can(rules["permission"]):
            raise Forbidden("You don't have permission to do that.")
        name = PurePosixPath(filename.replace("\\", "/")).name.strip()[:200]
        if not name.lower().endswith(rules["extensions"]):
            raise Invalid(f"Choose a {' or '.join(rules['extensions'])} file.", "file")
        if size <= 0:
            raise Invalid("That file is empty.", "file")
        if size > rules["max_bytes"]:
            raise Invalid(f"That file is too large: the most is {rules['max_bytes'] // (1024 * 1024)} MB.", "file")
        self.db.execute(delete(Upload).where(Upload.tenant_id == self.tenant_id, Upload.updated_at < utcnow() - STALE))
        row = Upload(id=uuid.uuid4(), tenant_id=self.tenant_id, user_id=self.current.id, purpose=purpose, filename=name,
                     size=size, received=0, data="")
        self.db.add(row)
        self.db.flush()
        return _state(row)

    def status(self, upload_id: uuid.UUID) -> UploadState:
        return _state(self._get(upload_id))

    def receive(self, upload_id: uuid.UUID, content_range: str, piece: bytes) -> UploadState:
        """Add one piece. It must start exactly where the upload has got to; otherwise 409 says to ask how far it is."""
        row = self._get(upload_id, lock=True)  # one piece at a time per upload
        m = _RANGE.match(content_range.strip())
        if not m:
            raise Invalid("Send each piece with a Content-Range header (bytes start-end/total).", "content_range")
        start, end, total = (int(g) for g in m.groups())
        expected = end - start + 1
        if total != row.size or end < start or end >= total or expected > MAX_CHUNK:
            raise Invalid("That piece doesn't fit this upload.", "content_range")
        if len(piece) != expected:
            raise Invalid("That piece arrived incomplete. Send it again.", "content_range")
        if start != row.received:
            raise Conflict(f"{row.received} bytes of this file have arrived; carry on from there.", "offset")
        if end + 1 < total and expected % 3:
            raise Invalid("Every piece but the last must be a multiple of 3 bytes.", "content_range")
        self.db.execute(update(Upload).where(Upload.id == row.id)
                        .values(data=Upload.data + base64.b64encode(piece).decode(), received=end + 1, updated_at=utcnow()))
        row.received = end + 1
        return _state(row)

    def take(self, upload_id: uuid.UUID, purpose: str) -> tuple[str, bytes]:
        """The finished file, for the feature it was sent for. It's removed once taken."""
        row = self._get(upload_id, lock=True, with_data=True)
        if row.purpose != purpose:
            raise Invalid("That upload was for something else.", "upload_id")
        if row.received < row.size:
            raise Conflict(f"The file hasn't finished uploading ({row.received} of {row.size} bytes).", "upload_id")
        content = base64.b64decode(row.data)
        self.db.delete(row)
        self.db.flush()
        return row.filename, content

    def cancel(self, upload_id: uuid.UUID) -> None:
        self.db.delete(self._get(upload_id))
        self.db.flush()
