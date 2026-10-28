"""Each client's own backups: a copy of one centre's data, made by the worker on the owner's schedule or when asked,
downloadable as an Excel workbook, as SQL, or as the copy itself, and restorable by the owner (or the platform).

What a copy holds: the centre's settings and running numbers, its catalogue, doctors and hospitals, patients,
bills, payments, test reports (with their versions, share links and deliveries), image records, doctors'
signatures, where each person works (staff areas) and the OPD's doctors and visits. Not in it: staff accounts, roles and API keys (who may sign in is access control, not records, and a
restore must never lock the owner out), the activity log (kept as it is; a restore adds to it), sessions and jobs.
The images themselves live in Orthanc, not here.

A copy is a gzip'd JSON file in the app's storage (one folder per client), each table's rows exactly as Postgres
gives them (json_agg), with the database's schema version: it can be restored only into the same version.

Restoring, in one transaction: the client's rows in those tables are deleted and the copy's put back (Postgres
turns the JSON back into rows itself: json_populate_recordset), then the client's staff are signed out. A fresh
copy of the data as it was is made first, so a restore can be undone.
"""

from __future__ import annotations

import gzip
import io
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Base, scoped_session
from app.core.errors import Conflict, Invalid, NotFound
from app.models import ClientBackup, ClientBackupSettings, Tenant, User, UserSession, utcnow
from app.services.audit import AuditService
from app.services.backups import CYCLES, KEEP, plan_next

FORMAT = "cidms-client-backup"
# Put back parents first; deleted in the reverse order.
TABLES = ["tenant_settings", "counters", "departments", "test_types", "tests", "report_templates", "referring_doctors",
          "patients", "invoices", "invoice_items", "payments", "test_reports", "test_report_versions", "report_shares",
          "message_deliveries", "imaging_studies", "doctor_signatures", "staff_areas", "opd_doctors", "opd_visits"]
STALE = timedelta(hours=2)   # a copy still "running" this long was cut off
CHUNK = 1000                 # rows per INSERT when restoring


# ---------- where the copies are ----------

def _dir(tenant_id: uuid.UUID) -> Path:
    return Path(get_settings().storage_dir) / "client-backups" / str(tenant_id)


def path_of(b: ClientBackup) -> Path | None:
    if b.trigger == "restore" or b.status != "ok" or not b.file:
        return None
    p = _dir(b.tenant_id) / b.file
    return p if p.is_file() else None


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().display_timezone)


def schema_version(db: Session) -> str:
    return db.scalar(text("SELECT version_num FROM alembic_version")) or ""


# ---------- schedule and list ----------

def settings_row(db: Session, tenant_id: uuid.UUID, lock: bool = False) -> ClientBackupSettings:
    q = select(ClientBackupSettings).where(ClientBackupSettings.tenant_id == tenant_id)
    row = db.scalar(q.with_for_update() if lock else q)
    if row is None:
        row = ClientBackupSettings(tenant_id=tenant_id, enabled=True, every_days=1, at_time="23:30", keep_days=30)
        row.next_run_at = plan_next(row, utcnow(), None)
        db.add(row)
        db.flush()
    return row


def _running(db: Session, tenant_id: uuid.UUID) -> ClientBackup | None:
    return db.scalar(select(ClientBackup).where(ClientBackup.tenant_id == tenant_id, ClientBackup.status == "running",
                                                ClientBackup.started_at > utcnow() - STALE))


def overview(db: Session, tenant_id: uuid.UUID) -> dict:
    s = settings_row(db, tenant_id)
    rows = list(db.scalars(select(ClientBackup).where(ClientBackup.tenant_id == tenant_id)
                           .order_by(func.coalesce(ClientBackup.finished_at, ClientBackup.started_at).desc()).limit(30)))
    current = schema_version(db)
    return {
        "settings": {"enabled": s.enabled, "every_days": s.every_days, "at_time": s.at_time, "keep_days": s.keep_days,
                     "next_run_at": s.next_run_at},
        "cycles": [{"days": d, "label": label} for d, label in CYCLES.items()],
        "keep_options": [{"days": d, "label": label} for d, label in KEEP.items()],
        "runs": [{
            "id": b.id, "trigger": b.trigger, "status": b.status, "started_at": b.started_at, "finished_at": b.finished_at,
            "requested_by_name": b.requested_by_name, "file": b.file, "size_bytes": b.size_bytes, "counts": b.counts,
            "message": b.message, "available": path_of(b) is not None,
            "restorable": path_of(b) is not None and b.schema_version == current,
        } for b in rows],
        "busy": _running(db, tenant_id) is not None,
    }


def update(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, enabled: bool, every_days: int, at_time: str,
           keep_days: int) -> dict:
    if every_days not in CYCLES:
        raise Invalid("Choose how often from the list.", "every_days")
    if keep_days not in KEEP:
        raise Invalid("Choose how long to keep copies from the list.", "keep_days")
    try:
        hh, mm = (int(x) for x in at_time.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except (ValueError, AssertionError):
        raise Invalid("Enter a time like 23:30.", "at_time") from None
    s = settings_row(db, tenant_id, lock=True)
    s.enabled, s.every_days, s.at_time, s.keep_days = enabled, every_days, f"{hh:02d}:{mm:02d}", keep_days
    s.next_run_at = plan_next(s, utcnow(), None)
    AuditService(db).record(tenant_id, user_id, "backups.schedule_changed", "client_backup_settings", tenant_id,
                            {"enabled": enabled, "every_days": every_days, "at_time": s.at_time, "keep_days": keep_days})
    db.flush()
    return overview(db, tenant_id)


def _who(db: Session, user_id: uuid.UUID | None) -> str:
    u = db.get(User, user_id) if user_id else None
    return (u.full_name if u else "")[:200]


def request_backup(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """Back up now: the worker makes the copy within a few seconds."""
    from app.core.jobs import enqueue
    if _running(db, tenant_id):
        raise Conflict("A backup or restore is running. It shows below when it's done.")
    b = ClientBackup(tenant_id=tenant_id, trigger="manual", status="running", requested_by=user_id,
                     requested_by_name=_who(db, user_id), started_at=utcnow())
    db.add(b)
    db.flush()
    enqueue(db, "client_backup", {"backup_id": str(b.id)}, tenant_id=tenant_id, created_by=user_id)
    AuditService(db).record(tenant_id, user_id, "backups.requested", "client_backups", b.id, {})
    return overview(db, tenant_id)


def request_restore(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, backup_id: uuid.UUID) -> dict:
    from app.core.jobs import enqueue
    source = db.get(ClientBackup, backup_id)
    if source is None or source.tenant_id != tenant_id or source.trigger == "restore":
        raise NotFound("There's no such backup.")
    if path_of(source) is None:
        raise Invalid("This copy isn't kept any more, so it can't be restored.")
    if source.schema_version != schema_version(db):
        raise Invalid("This copy is from an earlier version of CIDMS and can't be restored. You can still download it.")
    if _running(db, tenant_id):
        raise Conflict("A backup or restore is running. Try again once it's done.")
    when = f"{source.started_at.astimezone(_tz()):%d %b %Y, %I:%M %p}"
    r = ClientBackup(tenant_id=tenant_id, trigger="restore", status="running", requested_by=user_id,
                     requested_by_name=_who(db, user_id), source_id=source.id, started_at=utcnow(),
                     message=f"Back to the copy of {when}")
    db.add(r)
    db.flush()
    enqueue(db, "client_restore", {"restore_id": str(r.id)}, tenant_id=tenant_id, created_by=user_id)
    AuditService(db).record(tenant_id, user_id, "backups.restore_requested", "client_backups", source.id, {"copy": when})
    return overview(db, tenant_id)


def get_backup(db: Session, tenant_id: uuid.UUID, backup_id: uuid.UUID) -> ClientBackup:
    b = db.get(ClientBackup, backup_id)
    if b is None or b.tenant_id != tenant_id or path_of(b) is None:
        raise NotFound("That copy isn't kept any more.")
    return b


# ---------- making a copy ----------

def make_copy(db: Session, tenant_id: uuid.UUID, b: ClientBackup) -> None:
    """Write the client's data to a file and fill in `b`. Reads only; the caller commits."""
    tenant = db.get(Tenant, tenant_id)
    now = utcnow()
    counts: dict[str, int] = {}
    parts = []
    for t in TABLES:
        rows = db.scalar(text(f"SELECT coalesce(json_agg(x), '[]'::json)::text FROM {t} x WHERE x.tenant_id = :t"),  # noqa: S608
                         {"t": tenant_id})
        counts[t] = db.scalar(text(f"SELECT count(*) FROM {t} WHERE tenant_id = :t"), {"t": tenant_id}) or 0  # noqa: S608
        parts.append(f"{json.dumps(t)}: {rows}")
    staff = [{"name": u.full_name, "email": u.email, "mobile": u.mobile, "active": u.is_active, "roles": roles}
             for u, roles in _staff(db, tenant_id)]
    meta = {"format": FORMAT, "version": 1, "schema": schema_version(db), "client": tenant.slug, "client_name": tenant.name,
            "made_at": now.isoformat(), "counts": counts}
    body = ('{"meta": ' + json.dumps(meta) + ', "staff": ' + json.dumps(staff) + ', "tables": {' + ", ".join(parts) + "}}")
    folder = _dir(tenant_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{tenant.slug}-{now.astimezone(_tz()):%Y-%m-%d-%H%M%S}.cidms.json.gz"
    tmp = folder / (name + ".part")
    with gzip.open(tmp, "wb", compresslevel=6) as f:
        f.write(body.encode("utf-8"))
    tmp.replace(folder / name)
    b.file, b.size_bytes, b.counts = name, (folder / name).stat().st_size, counts
    b.schema_version, b.status, b.finished_at = meta["schema"], "ok", utcnow()


def _staff(db: Session, tenant_id: uuid.UUID):
    rows = db.execute(text(
        "SELECT u.id, coalesce(string_agg(r.name, ', ' ORDER BY r.name), '') FROM users u "
        "LEFT JOIN user_roles ur ON ur.user_id = u.id LEFT JOIN roles r ON r.id = ur.role_id "
        "WHERE u.tenant_id = :t GROUP BY u.id"), {"t": tenant_id}).all()
    users = {u.id: u for u in db.scalars(select(User).where(User.tenant_id == tenant_id))}
    return sorted(((users[i], roles) for i, roles in rows if i in users), key=lambda p: p[0].full_name.lower())


def prune(db: Session, tenant_id: uuid.UUID) -> int:
    """Copies older than the client's keep setting are deleted (their record stays, marked as no longer kept)."""
    s = settings_row(db, tenant_id)
    if s.keep_days == 0:
        return 0
    cutoff = utcnow() - timedelta(days=s.keep_days)
    gone = 0
    for b in db.scalars(select(ClientBackup).where(ClientBackup.tenant_id == tenant_id, ClientBackup.status == "ok",
                                                   ClientBackup.trigger != "restore", ClientBackup.started_at < cutoff)):
        p = path_of(b)
        if p:
            p.unlink(missing_ok=True)
            gone += 1
    return gone


def read_copy(b: ClientBackup) -> dict:
    p = path_of(b)
    if p is None:
        raise NotFound("That copy isn't kept any more.")
    with gzip.open(p, "rb") as f:
        data = json.loads(f.read())
    if data.get("meta", {}).get("format") != FORMAT:
        raise Invalid("That file isn't a CIDMS backup.")
    return data


# ---------- restoring ----------

def _user_refs() -> dict[str, list[tuple[str, bool]]]:
    """Per table: the columns that point at a person (users.id), and whether they may be empty."""
    out: dict[str, list[tuple[str, bool]]] = {}
    for t in TABLES:
        table = Base.metadata.tables.get(t)
        if table is None:
            continue
        out[t] = [(c.name, bool(c.nullable)) for c in table.columns
                  if any(fk.column.table.name == "users" for fk in c.foreign_keys)]
    return out


def restore_copy(db: Session, tenant_id: uuid.UUID, data: dict) -> dict[str, int]:
    """Replace the client's rows in TABLES with the copy's, in the caller's transaction. Staff who no longer exist
    are left out of the copy's records ("made by" goes empty; a signature of someone removed is dropped)."""
    meta = data["meta"]
    if meta.get("schema") != schema_version(db):
        raise Invalid("This copy is from an earlier version of CIDMS and can't be restored.")
    users = {str(u) for u in db.scalars(select(User.id))}
    refs = _user_refs()
    tables = data["tables"]
    # The app can't delete these rows itself; this database function can, only while this client's restore runs.
    db.execute(text("SELECT client_restore_clear(:t)"), {"t": tenant_id})
    put: dict[str, int] = {}
    for t in TABLES:
        rows = []
        for r in tables.get(t, []):
            if str(r.get("tenant_id")) != str(tenant_id):
                raise Invalid("This copy belongs to another centre.")
            keep = True
            for col, nullable in refs.get(t, []):
                if r.get(col) is not None and str(r[col]) not in users:
                    if nullable:
                        r[col] = None
                    else:
                        keep = False
            if keep:
                rows.append(r)
        for i in range(0, len(rows), CHUNK):
            db.execute(text(f"INSERT INTO {t} SELECT * FROM json_populate_recordset(NULL::{t}, CAST(:rows AS json))"),  # noqa: S608
                       {"rows": json.dumps(rows[i:i + CHUNK])})
        put[t] = len(rows)
    db.execute(delete(UserSession).where(UserSession.tenant_id == tenant_id))   # everyone signs in again
    return put


def run_backup(tenant_id: uuid.UUID, backup_id: uuid.UUID | None, trigger: str = "scheduled",
               scheduled_for: datetime | None = None, message: str = "") -> uuid.UUID:
    """Make a copy in its own transaction (the worker's job, and the copy taken before a restore). A copy that
    fails is recorded as failed and the error raised again."""
    with scoped_session(tenant_id) as db, db.begin():
        b = db.get(ClientBackup, backup_id) if backup_id else None
        if b is None:
            b = ClientBackup(tenant_id=tenant_id, trigger=trigger, status="running", scheduled_for=scheduled_for,
                             started_at=utcnow(), message=message[:500])
            db.add(b)
            db.flush()
        if b.status == "ok":
            return b.id                  # already made (a job run twice)
        backup_id = b.id
    try:
        with scoped_session(tenant_id) as db, db.begin():
            b = db.get(ClientBackup, backup_id)
            make_copy(db, tenant_id, b)
            prune(db, tenant_id)
    except Exception as e:
        with scoped_session(tenant_id) as db, db.begin():
            b = db.get(ClientBackup, backup_id)
            b.status, b.finished_at = "failed", utcnow()
            b.message = f"The copy couldn't be made ({type(e).__name__})."
        raise
    return backup_id


def fail(tenant_id: uuid.UUID, backup_id: uuid.UUID, message: str) -> None:
    with scoped_session(tenant_id) as db, db.begin():
        b = db.get(ClientBackup, backup_id)
        if b is not None and b.status == "running":
            b.status, b.finished_at, b.message = "failed", utcnow(), message[:500]


# ---------- downloads ----------

def to_sql(data: dict) -> bytes:
    """The copy as SQL: one INSERT per row, in an order that loads into a CIDMS database of the same version."""
    def lit(v) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int | float):
            return repr(v)
        if isinstance(v, dict | list):
            v = json.dumps(v, ensure_ascii=False)
        return "'" + str(v).replace("'", "''") + "'"

    meta = data["meta"]
    out = io.StringIO()
    out.write(f"-- CIDMS backup of {meta['client_name']} ({meta['client']}), made {meta['made_at']}\n"
              f"-- Database version {meta['schema']}. Staff accounts, roles and API keys are not included.\n"
              "BEGIN;\n")
    for t in TABLES:
        rows = data["tables"].get(t, [])
        out.write(f"\n-- {t}: {len(rows)} row(s)\n")
        for r in rows:
            cols = ", ".join(f'"{c}"' for c in r)
            values = ", ".join(lit(v) for v in r.values())
            out.write(f"INSERT INTO {t} ({cols}) VALUES ({values});\n")  # noqa: S608 (written to the file, never run)
    out.write("\nCOMMIT;\n")
    return out.getvalue().encode("utf-8")


# sheet: (table, [(column, heading)])
SHEETS = [
    ("Patients", "patients", [("patient_no", "Patient no."), ("name", "Name"), ("guardian_name", "C/O"), ("age_years", "Age"),
                              ("gender", "Gender"), ("mobile", "Mobile"), ("email", "Email"), ("address", "Address"),
                              ("created_at", "Registered")]),
    ("Bills", "invoices", [("invoice_no", "Bill no."), ("bill_date", "Date"), ("patient_name", "Patient"),
                           ("patient_mobile", "Mobile"), ("referring_doctor_name", "Referred by"), ("status", "Status"),
                           ("subtotal", "Subtotal"), ("discount_amount", "Discount"), ("total", "Total"), ("paid", "Paid"),
                           ("due", "Due"), ("created_by_name", "Made by"), ("created_at", "Made at")]),
    ("Bill lines", "invoice_items", [("@invoice", "Bill no."), ("position", "#"), ("test_name", "Test"),
                                     ("department_name", "Department"), ("unit_price", "Price"), ("quantity", "Qty"),
                                     ("amount", "Amount"), ("status", "Status")]),
    ("Payments", "payments", [("@invoice", "Bill no."), ("kind", "Kind"), ("amount", "Amount"), ("mode", "Mode"),
                              ("reference", "Reference"), ("received_on", "Date"), ("received_by_name", "Received by"),
                              ("note", "Note")]),
    ("Reports", "test_reports", [("@item_invoice", "Bill no."), ("title", "Title"), ("status", "Status"),
                                 ("reported_by_name", "Reported by"), ("signer_name", "Signed by"), ("signed_at", "Signed at"),
                                 ("impression", "Impression")]),
    ("Tests", "tests", [("name", "Test"), ("@department", "Department"), ("price", "Price"), ("is_active", "Active")]),
    ("Departments", "departments", [("name", "Department"), ("is_active", "Active")]),
    ("Doctors & hospitals", "referring_doctors", [("name", "Name"), ("qualification", "Qualification"), ("phone", "Phone"),
                                                  ("is_active", "Active")]),
]


def to_xlsx(data: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    tables = data["tables"]
    bill_no = {r["id"]: r["invoice_no"] for r in tables.get("invoices", [])}
    item_bill = {r["id"]: bill_no.get(r["invoice_id"], "") for r in tables.get("invoice_items", [])}
    dept = {r["id"]: r["name"] for r in tables.get("departments", [])}
    money = {"subtotal", "discount_amount", "total", "paid", "due", "unit_price", "amount", "price"}

    def value(r: dict, col: str):
        if col == "@invoice":
            return bill_no.get(r.get("invoice_id"), "")
        if col == "@item_invoice":
            return item_bill.get(r.get("invoice_item_id"), "")
        if col == "@department":
            return dept.get(r.get("department_id"), "")
        v = r.get(col)
        if col in money and v is not None:
            return float(v)
        if isinstance(v, str) and len(v) >= 19 and v[4] == "-" and v[10] == "T":
            return datetime.fromisoformat(v).astimezone(_tz()).replace(tzinfo=None)
        return v

    wb = Workbook()
    about = wb.active
    about.title = "About"
    meta = data["meta"]
    for row in (("CIDMS backup", meta["client_name"]), ("Made at", datetime.fromisoformat(meta["made_at"]).astimezone(_tz()).replace(tzinfo=None)),
                ("Database version", meta["schema"]), ("", ""), *((t, n) for t, n in meta["counts"].items())):
        about.append(row)
    about["A1"].font = Font(bold=True)
    for title, table, cols in [*SHEETS, ("Staff", None, [("name", "Name"), ("email", "Email"), ("mobile", "Mobile"),
                                                         ("roles", "Roles"), ("active", "Active")])]:
        ws = wb.create_sheet(title)
        ws.append([h for _, h in cols])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        rows = data.get("staff", []) if table is None else tables.get(table, [])
        for r in rows:
            ws.append([value(r, c) for c, _ in cols])
        ws.freeze_panes = "A2"
        for i, (_, h) in enumerate(cols, start=1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(10, min(40, len(h) + 6))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- the schedule (called by the worker every minute) ----------

def enqueue_due(now: datetime | None = None) -> int:
    """Queue a backup for each active client whose time has come. Safe with many workers (row locks)."""
    from app.core.jobs import enqueue
    now = now or utcnow()
    queued = 0
    with scoped_session(platform=True) as db, db.begin():
        for tenant_id in db.scalars(select(Tenant.id).where(Tenant.status == "active")):
            s = db.scalar(select(ClientBackupSettings).where(ClientBackupSettings.tenant_id == tenant_id)
                          .with_for_update(skip_locked=True))
            if s is None:
                settings_row(db, tenant_id)
                continue
            if not s.enabled or s.next_run_at is None or s.next_run_at > now:
                continue
            slot = s.next_run_at
            enqueue(db, "client_backup", {"scheduled_for": slot.isoformat()}, tenant_id=tenant_id,
                    dedupe_key=f"client_backup:{slot.isoformat()}")
            s.next_run_at = plan_next(s, now, slot)
            queued += 1
    return queued
