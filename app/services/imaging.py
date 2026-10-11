"""Medical images: DICOM files uploaded for a test go to the Orthanc image server, and each study is recorded
against the test (and the client) here.

- The image server is shared by every client, so each study is labelled with its client, and a study whose
  StudyInstanceUID already belongs to another client is refused (the new files are removed again).
- Browsers only ever reach images through the DICOMweb proxy, which serves a client's own studies alone.
"""

import io
import logging
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import BinaryIO

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, Invalid, NotFound
from app.core.orthanc import Orthanc, tenant_label
from app.core.security import CurrentUser
from app.models import ImagingStudy, Invoice, InvoiceItem, utcnow
from app.services.audit import AuditService

log = logging.getLogger("app.imaging")

MAX_FILES = 5000
MAX_UNCOMPRESSED = 4 * 1024**3  # what a zip may unpack to, in all
SKIP = ("__macosx/", "dicomdir", "thumbs.db", ".ds_store")


@dataclass
class UploadResult:
    studies: list[ImagingStudy] = field(default_factory=list)
    stored: int = 0
    already_stored: int = 0
    rejected: int = 0
    messages: list[str] = field(default_factory=list)


def upload_limit_bytes() -> int:
    return get_settings().imaging_max_upload_mb * 1024 * 1024


def dicom_payloads(files: Iterable[tuple[str, BinaryIO]]) -> Iterator[tuple[str, bytes]]:
    """Each DICOM file to store: plain files as they are, and every file inside a .zip."""
    count, unpacked = 0, 0
    for name, fh in files:
        fh.seek(0)
        head = fh.read(4)
        fh.seek(0)
        if head == b"PK\x03\x04" or name.lower().endswith(".zip"):
            try:
                archive = zipfile.ZipFile(fh)
            except zipfile.BadZipFile as exc:
                raise Invalid(f"{name} isn't a readable .zip file.", "files") from exc
            with archive:
                for info in archive.infolist():
                    lower = info.filename.lower()
                    if info.is_dir() or any(s in lower for s in SKIP) or lower.endswith((".txt", ".xml", ".html", ".exe", ".pdf")):
                        continue
                    unpacked += info.file_size
                    count += 1
                    if unpacked > MAX_UNCOMPRESSED or count > MAX_FILES:
                        raise Invalid("That archive is too large. Upload it in parts.", "files")
                    with archive.open(info) as member:
                        data = member.read(info.file_size + 1)
                    if len(data) > info.file_size:  # the archive lied about the size
                        raise Invalid(f"{name} looks damaged.", "files")
                    yield info.filename, data
        else:
            count += 1
            if count > MAX_FILES:
                raise Invalid(f"Upload at most {MAX_FILES} files at a time, or put them in a .zip.", "files")
            yield name, fh.read()


class ImagingService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    # ---------- reading ----------
    def _item(self, item_id: uuid.UUID) -> tuple[InvoiceItem, Invoice]:
        row = self.db.execute(select(InvoiceItem, Invoice).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                              .where(InvoiceItem.tenant_id == self.tenant_id, InvoiceItem.id == item_id)).first()
        if row is None:
            raise NotFound("We couldn't find that test.")
        return row[0], row[1]

    def studies(self, item_id: uuid.UUID) -> list[ImagingStudy]:
        self._item(item_id)
        return list(self.db.scalars(select(ImagingStudy).where(ImagingStudy.tenant_id == self.tenant_id,
                                                               ImagingStudy.invoice_item_id == item_id)
                                    .order_by(ImagingStudy.created_at)))

    def owns(self, study_uid: str) -> bool:
        return self.db.scalar(select(ImagingStudy.id).where(ImagingStudy.tenant_id == self.tenant_id,
                                                            ImagingStudy.study_instance_uid == study_uid)) is not None

    def own_uids(self) -> set[str]:
        return set(self.db.scalars(select(ImagingStudy.study_instance_uid).where(ImagingStudy.tenant_id == self.tenant_id)))

    def _taken_elsewhere(self, study_uid: str) -> bool:
        return bool(self.db.scalar(text("SELECT imaging_uid_taken_elsewhere(:uid)"), {"uid": study_uid}))

    # ---------- upload ----------
    def upload(self, item_id: uuid.UUID, files: list[tuple[str, BinaryIO]]) -> UploadResult:
        item, invoice = self._item(item_id)
        if item.status == "cancelled" or invoice.status == "cancelled":
            raise Conflict(f"{item.test_name} was cancelled, so images can't be added.")
        if not item.is_imaging:
            raise Invalid(f"{item.test_name} isn't a scan, so it has no images.", "files")
        if not files:
            raise Invalid("Choose the DICOM files (.dcm) or a .zip of them.", "files")
        out = UploadResult()
        new_instances: dict[str, list[str]] = {}  # Orthanc study id -> instances this upload added
        with Orthanc() as orthanc:
            for _name, data in dicom_payloads(files):
                stored = orthanc.store(data)
                if stored is None or "ParentStudy" not in stored:
                    out.rejected += 1
                    continue
                study_id = stored["ParentStudy"]
                new_instances.setdefault(study_id, [])
                if stored.get("Status") == "AlreadyStored":
                    out.already_stored += 1
                else:
                    out.stored += 1
                    new_instances[study_id].append(stored["ID"])
            for study_id, added in new_instances.items():
                study = self._claim(orthanc, study_id, added, item, out)
                if study is not None and study not in out.studies:
                    out.studies.append(study)
        if out.rejected:
            out.messages.append(f"{out.rejected} file{'s' if out.rejected != 1 else ''} weren't DICOM images and were skipped.")
        if not out.studies:
            if not out.messages:
                out.messages.append("No DICOM images were found in what you uploaded.")
            return out
        if item.status == "billed":
            item.status, item.status_changed_at = "scanned", utcnow()
            self.audit.record(self.tenant_id, self.current.id, "test.scanned", "invoice_item", item.id, {
                "invoice_no": invoice.invoice_no, "test": item.test_name, "from": "billed", "due": str(invoice.due)})
        self.audit.record(self.tenant_id, self.current.id, "imaging.uploaded", "invoice_item", item.id, {
            "invoice_no": invoice.invoice_no, "test": item.test_name, "studies": [s.study_instance_uid for s in out.studies],
            "stored": out.stored, "already_stored": out.already_stored, "rejected": out.rejected})
        return out

    def _claim(self, orthanc: Orthanc, study_id: str, added: list[str], item: InvoiceItem, out: UploadResult) -> ImagingStudy | None:
        info = orthanc.study(study_id)
        tags = info.get("MainDicomTags", {})
        uid = tags.get("StudyInstanceUID", "")
        mine = tenant_label(self.tenant_id)
        other_label = any(lbl.startswith("tenant_") and lbl != mine for lbl in info.get("Labels", []))
        if not uid or self._taken_elsewhere(uid) or other_label:
            for instance_id in added:  # take back only what this upload put there
                orthanc.delete_instance(instance_id)
            self.audit.record(self.tenant_id, self.current.id, "imaging.refused", "invoice_item", item.id, {"study_uid": uid})
            out.messages.append("A study in this upload is already held by another centre, so it wasn't added.")
            return None
        row = self.db.scalar(select(ImagingStudy).where(ImagingStudy.tenant_id == self.tenant_id, ImagingStudy.study_instance_uid == uid))
        if row is not None and row.invoice_item_id != item.id:
            out.messages.append(f"Study {uid} is already attached to another test; its images were updated there.")
        orthanc.add_label(study_id, mine)
        stats = orthanc.statistics(study_id)
        modalities = sorted({s.get("MainDicomTags", {}).get("Modality", "") for s in orthanc.series(study_id)} - {""})
        if row is None:
            row = ImagingStudy(id=uuid.uuid4(), tenant_id=self.tenant_id, invoice_item_id=item.id, study_instance_uid=uid,
                               uploaded_by=self.current.id, uploaded_by_name=self.current.user.full_name)
            self.db.add(row)
        row.orthanc_study_id = study_id
        row.modality = "/".join(modalities)[:40]
        row.description = (tags.get("StudyDescription") or "")[:300]
        row.series_count = int(stats.get("CountSeries") or len(info.get("Series", [])))
        row.instance_count = int(stats.get("CountInstances") or 0)
        row.size_bytes = int(stats.get("DiskSize") or stats.get("UncompressedSize") or 0)
        row.updated_at = utcnow()
        self.db.flush()
        return row


def as_files(blobs: list[tuple[str, bytes]]) -> list[tuple[str, BinaryIO]]:
    """For callers holding bytes rather than uploaded files (tests, scripts)."""
    return [(name, io.BytesIO(data)) for name, data in blobs]
