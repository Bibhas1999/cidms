"""Bring a centre's records across from the old Laravel app (MariaDB) into its tables in CIDMS.

    python -m app.legacy_import --dry-run     # do everything in one transaction, then roll it back
    python -m app.legacy_import               # the real move

Safe to run again: rows are matched on the old app's ids, so only rows not brought across before are added.
The whole run is one transaction. A report is written to storage/import/<date-time>/ (report.md, issues.csv,
doctors.csv, reconciliation.csv), and the old and new figures are compared at the end: the exit code is 1
if anything doesn't match.

Runs as the tables' owner (MIGRATION_DATABASE_URL), which isn't held back by row-level security.
"""

import argparse
import csv
import html
import re
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, column, create_engine, insert, table, text
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.money import ZERO, financial_year, q2
from app.models import ActivityLog, Department, Invoice, InvoiceItem, LabTest, Patient, Payment, ReferringDoctor, TestType, User, UserRole
from app.repositories.counters import set_at_least
from app.services.patients import age_text

DEFAULT_LEGACY_URL = "mysql+pymysql://root:local-legacy-only@localhost:3307/pos"

DEPARTMENT_NAMES = {"RADIOLOGY": "Radiology", "PATHOLOGY": "Pathology", "ECHO&USG": "Echo & USG", "CARDIOLOGY": "Cardiology",
                    "NEUROLOGY": "Neurology", "OTHERS": "Others", "OPD": "OPD"}
# old type name: (new name, is imaging)
TEST_TYPE_NAMES = {"X-RAY": ("X-ray", True), "CT-SCAN": ("CT scan", True), "USG": ("USG", True), "ECG": ("ECG", False),
                   "BLOOD TEST": ("Blood test", False)}
USER_ROLES = {"admin": "owner", "manager": "admin", "receptionist": "receptionist", "user": "technician"}
# old invoice_details column: key in invoice_items.legacy_report
REPORT_FIELDS = {"report_study": "study", "report_imp": "impression", "report_mod": "modality", "report_name": "name",
                 "report_tech": "tech", "report_tech_deg": "tech_degree", "report_tech_spec": "tech_specialisation",
                 "report_tech_signature": "signature", "report_reg_no": "reg_no", "report_file": "file"}
NO_DOCTOR = {"", "SELF", "-", "NA", "NONE"}
UNKNOWN_DEPARTMENT = "Others"
ADJUSTMENT = "Adjustment from the old system"

RULES = [
    "Departments and test types renamed to the new spelling (e.g. ECHO&USG -> Echo & USG, CT-SCAN -> CT scan); X-ray, CT scan and USG are imaging.",
    "Test names trimmed with spaces collapsed. Same name (any case) in the same department at the same price: merged into one test. "
    "Otherwise the later one is renamed '<name> (<Department>)', or '<name> (old #<id>)' if that is taken too.",
    "Bill lines pointing at a test that no longer exists keep their price as 'Unknown test (old #<id>)' with no test or department.",
    "Referring doctors grouped on a key (upper case, 'DR' prefix, dots and commas removed, spaces collapsed, single initials joined); "
    "SELF, NA, NONE, '-' and blank mean no doctor. Shown under the most used spelling in nice case, with 'Dr.' when any spelling had it.",
    "Customers merged into one patient only when the name (upper case, spaces collapsed) and the last 10 digits of a 10+ digit mobile match. "
    "Patient numbers follow each patient's earliest old customer id.",
    "A merged patient's details (name, age, gender, mobile, address, C/O, email) come from the latest customer row; created_at from the earliest.",
    "Ages: whole numbers kept; decimals ('1.5') rounded down to whole years; months/days converted to whole years; anything else left empty.",
    "Bill numbers: <prefix>/<financial year>/<old number, 6 digits>; a repeated old number keeps the plain form on the lowest old id and the "
    "later ones get -B, -C.",
    "Bill total = old payments.total_amount; the difference from the lines' total is the discount (type 'amount').",
    "Payments: only old payment rows with an amount above zero; online -> UPI with the note 'Online (old system)'.",
    "Staff: emails lower-cased; an existing account with the same email is kept as it is and only linked. New accounts keep the old bcrypt "
    "password (replaced at first sign-in) and must change it. Admin -> owner, Manager -> admin, Receptionist -> receptionist, User -> technician.",
    "Running numbers continue after the highest imported patient number and, per financial year, the highest old bill number.",
]

# invoices.legacy_id comes with migration 0005; written through a plain table description of its columns.
INVOICES = table("invoices", *(column(c.name) for c in Invoice.__table__.columns), column("legacy_id"))


class ImportFailed(Exception):
    pass


# ---------- plain helpers (no database) -----------------------------------------------------------------

_SPACES = re.compile(r"\s+")
_DR_PREFIX = re.compile(r"^(?:DR\b[.,]*\s*)+", re.IGNORECASE)
_VOWELS = set("AEIOU")
# Short words that stay as written in upper case even though they have a vowel.
_ACRONYMS = {"AH", "ESI", "IVF", "ENT", "ICU", "USG", "ECG", "OPD", "AIIMS", "IPGME", "IPGMER"}
_SMALL_WORDS = {"OF", "AND", "FOR", "THE", "IN", "AT", "ON"}
_SPECIAL_WORDS = {"MR": "Mr", "MRS": "Mrs", "MS": "Ms", "KR": "Kr", "PROF": "Prof", "DR": "Dr"}


def collapse(value: object) -> str:
    """Trimmed, with runs of spaces (and line breaks) made one space."""
    return _SPACES.sub(" ", "" if value is None else str(value)).strip()


def money(value: object) -> Decimal:
    """The old app keeps money as doubles; read them through their shortest text form, then round to paise."""
    return ZERO if value is None else q2(Decimal(str(value)))


def has_dr_prefix(raw: str | None) -> bool:
    return bool(_DR_PREFIX.match(collapse(raw)))


def doctor_key(raw: str | None) -> str:
    """The key doctor spellings are grouped on; "" means no doctor.
    "DR. S. K . HALDER", "Dr S.K.Halder" and "S K HALDER" all give "SK HALDER"."""
    s = collapse(raw).upper()
    if s in NO_DOCTOR:
        return ""
    s = re.sub(r"[.,]", " ", _DR_PREFIX.sub("", s))
    words, initials = [], ""
    for token in s.split():
        if len(token) == 1 and token.isalpha():
            initials += token
            continue
        if initials:
            words.append(initials)
            initials = ""
        words.append(token)
    if initials:
        words.append(initials)
    key = " ".join(words)
    return "" if key in NO_DOCTOR else key


def _nice_word(token: str, first: bool) -> str:
    letters = re.sub(r"[^A-Z]", "", token)
    if not letters or any(ch.isdigit() for ch in token):
        return token
    if letters in _SPECIAL_WORDS:
        return token.replace(letters, _SPECIAL_WORDS[letters])
    if not first and token in _SMALL_WORDS:
        return token.lower()
    if letters in _ACRONYMS or (len(letters) >= 2 and not set(letters) & _VOWELS):
        return token  # PHC, SSKM, MD, PVT: abbreviations stay upper case
    return re.sub(r"[A-Z]+", lambda m: m.group().capitalize(), token)


def doctor_display(spellings: dict[str, int]) -> str:
    """The name shown for a group of spellings: the most used one, in nice case, with "Dr." when any spelling had it.
    Initials are written together with dots: "S. K HALDER" -> "S.K. Halder"."""
    best = max(sorted(spellings), key=lambda s: spellings[s])
    body = re.sub(r"\s*\.\s*", ". ", _DR_PREFIX.sub("", collapse(best).upper())).replace(" ,", ",")
    words: list[str] = []
    initials = ""
    for token in body.split():
        if re.fullmatch(r"[A-Z]\.?", token):
            initials += token[0] + "."
            continue
        if initials:
            words.append(initials)
            initials = ""
        words.append(_nice_word(token, first=not words))
    if initials:
        words.append(initials)
    name = " ".join(words).replace(". )", ".)")
    return f"Dr. {name}" if any(has_dr_prefix(s) for s in spellings) else name


def parse_age(raw: object) -> tuple[int | None, str]:
    """(whole years, how it was read). How: "" for a plain number, "decimal", "months", "days", "unreadable",
    "out_of_range" or "empty"."""
    s = collapse(raw).upper()
    if not s:
        return None, "empty"
    how = ""
    if m := re.fullmatch(r"(\d{1,3})\s*(?:Y|YR|YRS|YEAR|YEARS)?\.?", s):
        years = int(m.group(1))
    elif m := re.fullmatch(r"(\d{1,3}\.\d+)\s*(?:Y|YR|YRS|YEAR|YEARS)?\.?", s):
        years, how = int(Decimal(m.group(1))), "decimal"
    elif m := re.fullmatch(r"(\d{1,3})\s*(?:Y|YR|YRS|YEARS?)\.?\s*(\d{1,2})\s*(?:M|MO|MON|MONTHS?)\.?", s):
        years, how = int(m.group(1)), "months"
    elif m := re.fullmatch(r"(\d{1,4})\s*(?:M|MO|MON|MONTHS?)\.?", s):
        years, how = int(m.group(1)) // 12, "months"
    elif m := re.fullmatch(r"(\d{1,4})\s*(?:D|DAYS?|W|WK|WKS|WEEKS?)\.?", s):
        n = int(m.group(1))
        years, how = (n // 52 if s[len(m.group(1)):].strip().startswith("W") else n // 365), "days"
    else:
        return None, "unreadable"
    if not 0 <= years <= 130:
        return None, "out_of_range"
    return years, how


def patient_key(name: str | None, mobile: str | None) -> str | None:
    """Customers with the same key are one person. None when the mobile is too short to be sure."""
    digits = re.sub(r"\D", "", mobile or "")
    if len(digits) < 10:
        return None
    return f"{collapse(name).upper()}|{digits[-10:]}"


def invoice_number(prefix: str, bill_date: date, legacy_no: int, used: set[str]) -> str:
    """"SHC/2026-27/004127"; when that's already used, "-B", "-C" and so on. Adds the result to `used`."""
    base = f"{prefix}/{financial_year(bill_date)}/{legacy_no:06d}"
    for suffix in ["", *(f"-{chr(c)}" for c in range(ord("B"), ord("Z") + 1))]:
        if base + suffix not in used:
            used.add(base + suffix)
            return base + suffix
    raise ImportFailed(f"Too many bills numbered {base}.")


def strip_html(value: str | None) -> str:
    """Plain text from the old app's rich-text notes: tags removed, entities decoded, blank lines dropped."""
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value or "")
    s = html.unescape(re.sub(r"<[^>]*>", " ", s))
    return "\n".join(line for line in (collapse(part) for part in s.splitlines()) if line)


def department_name(raw: str) -> str:
    s = collapse(raw)
    return DEPARTMENT_NAMES.get(s.upper(), s.title())


def gender(raw: str | None) -> str:
    s = collapse(raw).lower()
    return s if s in ("male", "female") else "other"


def guardian(raw: str | None) -> str:
    s = collapse(raw)
    return "" if s.upper() == "SELF" else s


def utc(value: datetime | None) -> datetime | None:
    """The old app's timestamps are UTC, read without a zone."""
    return value.replace(tzinfo=UTC) if value else None


# ---------- the import ----------------------------------------------------------------------------------

@dataclass
class Issue:
    kind: str
    legacy_id: object
    detail: str


@dataclass
class Tally:
    source: int = 0    # rows in the old table
    created: int = 0   # new rows written
    matched: int = 0   # brought across in an earlier run, or linked to a row that was already there
    merged: int = 0    # folded into another new row
    skipped: int = 0   # left out, see issues


@dataclass
class TestInfo:
    id: uuid.UUID
    name: str
    department_id: uuid.UUID
    department_name: str
    price: Decimal
    is_imaging: bool
    legacy_id: int | None


@dataclass
class Outcome:
    tenant_id: uuid.UUID
    dry_run: bool
    report_dir: Path
    counts: dict[str, Tally]
    issues: list[Issue]
    notes: list[str]
    doctors: list[tuple[str, list[str], int]]
    checks: list[tuple[str, str, str, str, bool]]
    doctor_spellings: int = 0
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(ok for *_, ok in self.checks)


class LegacyImport:
    def __init__(self, new: Connection, old: Connection, tenant_slug: str):
        self.new, self.old = new, old
        row = self._new_rows("SELECT t.id, s.invoice_prefix FROM tenants t JOIN tenant_settings s ON s.tenant_id = t.id "
                             "WHERE t.slug = :slug", slug=tenant_slug)
        if not row:
            raise ImportFailed(f"There is no client with the address name '{tenant_slug}'.")
        self.tenant_id: uuid.UUID = row[0].id
        self.prefix: str = row[0].invoice_prefix
        self.tz = ZoneInfo(get_settings().display_timezone)
        self.now = datetime.now(UTC)
        self.issues: list[Issue] = []
        self.notes: list[str] = []
        self.counts: dict[str, Tally] = defaultdict(Tally)
        self.doctors: list[tuple[str, list[str], int]] = []
        self.doctor_spellings = 0
        self.stats: Counter[str] = Counter()

    # -- small database helpers
    def _new_rows(self, sql: str, **params):
        return self.new.execute(text(sql), params).all()

    def _old_rows(self, sql: str, **params):
        return self.old.execute(text(sql), params).mappings().all()

    def _insert(self, target, rows: list[dict]) -> None:
        if rows:
            self.new.execute(insert(target), rows)

    def issue(self, kind: str, legacy_id: object, detail: str) -> None:
        self.issues.append(Issue(kind, legacy_id, detail))

    def run(self) -> None:
        self.import_users()
        self.import_departments()
        self.import_test_types()
        self.import_tests()
        self.load_invoices()
        self.import_doctors()
        self.import_patients()
        self.import_invoices()
        self.set_counters()
        self.new.execute(insert(ActivityLog.__table__), [{
            "tenant_id": self.tenant_id, "user_id": None, "action": "import.completed", "entity": "import", "entity_id": "",
            "details": {name: vars(t) for name, t in self.counts.items()} | {"issues": len(self.issues)},
            "ip_address": None, "user_agent": "app.legacy_import", "request_id": "", "created_at": self.now,
        }])

    # -- staff
    def import_users(self) -> None:
        roles = {r.code: r.id for r in self._new_rows("SELECT id, code FROM roles WHERE tenant_id IS NULL")}
        existing = self._new_rows("SELECT id, lower(email) AS email, legacy_id FROM users WHERE tenant_id = :t", t=self.tenant_id)
        by_legacy = {r.legacy_id for r in existing if r.legacy_id is not None}
        by_email = {r.email: r for r in existing}
        users, links = [], []
        tally = self.counts["users"]
        for u in self._old_rows("SELECT * FROM users ORDER BY id"):
            tally.source += 1
            if u["id"] in by_legacy:
                tally.matched += 1
                continue
            email = collapse(u["email"]).lower()
            if email in by_email:
                self.new.execute(text("UPDATE users SET legacy_id = :l WHERE id = :i"), {"l": u["id"], "i": by_email[email].id})
                self.notes.append(f"Staff: {email} already had an account here; it was kept as it is and linked to old user #{u['id']}.")
                tally.matched += 1
                continue
            code = USER_ROLES.get(collapse(u["usertype"]).lower())
            if code is None:
                code = "technician"
                self.issue("user_role_unknown", u["id"], f"usertype {u['usertype']!r} for {email}; given the Technician role")
            user_id = uuid.uuid4()
            created = utc(u["created_at"]) or self.now
            users.append({"id": user_id, "tenant_id": self.tenant_id, "email": email, "full_name": collapse(u["name"]) or email,
                          "mobile": collapse(u["mobile"])[:20], "password_hash": u["password"], "is_active": u["status"] == 1,
                          "must_change_password": True, "failed_logins": 0, "locked_until": None, "last_login_at": None,
                          "legacy_id": u["id"], "created_at": created, "updated_at": utc(u["updated_at"]) or created})
            links.append({"user_id": user_id, "role_id": roles[code], "tenant_id": self.tenant_id})
            tally.created += 1
        self._insert(User.__table__, users)
        self._insert(UserRole.__table__, links)
        rows = self._new_rows("SELECT id, full_name, legacy_id FROM users WHERE tenant_id = :t", t=self.tenant_id)
        self.user_by_legacy = {r.legacy_id: (r.id, r.full_name) for r in rows if r.legacy_id is not None}
        self.user_by_name = {collapse(r.full_name).lower(): r.id for r in rows}

    # -- catalogue
    def _named_rows(self, table_name: str) -> tuple[dict, dict]:
        rows = self._new_rows(f"SELECT id, name, legacy_id FROM {table_name} WHERE tenant_id = :t", t=self.tenant_id)  # noqa: S608 (fixed names)
        return {r.legacy_id: r for r in rows if r.legacy_id is not None}, {r.name.lower(): r for r in rows}

    def import_departments(self) -> None:
        by_legacy, by_name = self._named_rows("departments")
        self.dept_by_legacy: dict[int, tuple[uuid.UUID, str]] = {k: (r.id, r.name) for k, r in by_legacy.items()}
        self.dept_by_name: dict[str, tuple[uuid.UUID, str]] = {k: (r.id, r.name) for k, r in by_name.items()}
        tally = self.counts["departments"]
        for d in self._old_rows("SELECT * FROM depts ORDER BY id"):
            tally.source += 1
            if d["id"] in self.dept_by_legacy:
                tally.matched += 1
                continue
            name = department_name(d["name"])
            if name.lower() in self.dept_by_name:
                found = self.dept_by_name[name.lower()]
                self.new.execute(text("UPDATE departments SET legacy_id = :l WHERE id = :i AND legacy_id IS NULL"), {"l": d["id"], "i": found[0]})
                self.dept_by_legacy[d["id"]] = found
                tally.matched += 1
                continue
            self.dept_by_legacy[d["id"]] = self._add_department(name, d["status"] == 1, d["id"])
            tally.created += 1

    def _add_department(self, name: str, active: bool = True, legacy_id: int | None = None) -> tuple[uuid.UUID, str]:
        row = {"id": uuid.uuid4(), "tenant_id": self.tenant_id, "name": name, "is_active": active, "legacy_id": legacy_id}
        self.new.execute(insert(Department.__table__), [row])
        self.dept_by_name[name.lower()] = (row["id"], name)
        return row["id"], name

    def _unknown_department(self) -> tuple[uuid.UUID, str]:
        return self.dept_by_name.get(UNKNOWN_DEPARTMENT.lower()) or self._add_department(UNKNOWN_DEPARTMENT)

    def import_test_types(self) -> None:
        rows = self._new_rows("SELECT id, name, is_imaging, legacy_id FROM test_types WHERE tenant_id = :t", t=self.tenant_id)
        self.type_by_legacy: dict[int, tuple[uuid.UUID, bool]] = {r.legacy_id: (r.id, r.is_imaging) for r in rows if r.legacy_id is not None}
        by_name = {r.name.lower(): (r.id, r.is_imaging) for r in rows}
        tally = self.counts["test_types"]
        new_rows = []
        for tt in self._old_rows("SELECT * FROM testtypes ORDER BY id"):
            tally.source += 1
            if tt["id"] in self.type_by_legacy:
                tally.matched += 1
                continue
            raw = collapse(tt["typename"])
            name, imaging = TEST_TYPE_NAMES.get(raw.upper(), (raw.title(), False))
            if name.lower() in by_name:
                found = by_name[name.lower()]
                self.new.execute(text("UPDATE test_types SET legacy_id = :l WHERE id = :i AND legacy_id IS NULL"), {"l": tt["id"], "i": found[0]})
                self.type_by_legacy[tt["id"]] = found
                tally.matched += 1
                continue
            row = {"id": uuid.uuid4(), "tenant_id": self.tenant_id, "name": name, "is_imaging": imaging, "is_active": tt["status"] == 1,
                   "legacy_id": tt["id"]}
            new_rows.append(row)
            by_name[name.lower()] = self.type_by_legacy[tt["id"]] = (row["id"], imaging)
            tally.created += 1
        self._insert(TestType.__table__, new_rows)

    def import_tests(self) -> None:
        dept_names = dict(self.dept_by_name.values())
        imaging_types = dict(self.type_by_legacy.values())
        rows = self._new_rows("SELECT id, name, department_id, test_type_id, price, legacy_id FROM tests WHERE tenant_id = :t", t=self.tenant_id)
        infos = [TestInfo(r.id, r.name, r.department_id, dept_names.get(r.department_id, ""), r.price,
                          imaging_types.get(r.test_type_id, False), r.legacy_id) for r in rows]
        self.test_by_legacy: dict[int, TestInfo] = {i.legacy_id: i for i in infos if i.legacy_id is not None}
        by_name = {i.name.lower(): i for i in infos}
        tally = self.counts["tests"]
        new_rows = []
        for t in self._old_rows("SELECT * FROM tests ORDER BY id"):
            tally.source += 1
            if t["id"] in self.test_by_legacy:
                tally.matched += 1
                continue
            dept = self.dept_by_legacy.get(t["dept_id"])
            if dept is None:
                dept = self._unknown_department()
                dept_names[dept[0]] = dept[1]
                self.issue("test_department_unknown", t["id"], f"department #{t['dept_id']} doesn't exist; put under {dept[1]}")
            type_id, imaging = None, False
            if str(t["type_id"]).strip().isdigit() and int(t["type_id"]) in self.type_by_legacy:
                type_id, imaging = self.type_by_legacy[int(t["type_id"])]
            else:
                self.issue("test_type_unknown", t["id"], f"test type {t['type_id']!r} doesn't exist; left without a type")
            name, price = collapse(t["name"]), money(t["price"])
            same = by_name.get(name.lower())
            if same and same.department_id == dept[0] and same.price == price:
                self.test_by_legacy[t["id"]] = same
                tally.merged += 1
                self.issue("test_merged", t["id"], f"'{name}' merged into '{same.name}' (old #{same.legacy_id}): same name, department and price")
                continue
            if same:
                candidate = f"{name} ({dept[1]})"
                if candidate.lower() in by_name:
                    candidate = f"{name} (old #{t['id']})"
                self.issue("test_renamed", t["id"], f"'{name}' clashes with old #{same.legacy_id} ({same.department_name}, {same.price}); "
                                                    f"named '{candidate}'")
                name = candidate
            info = TestInfo(uuid.uuid4(), name[:200], dept[0], dept[1], price, imaging, t["id"])
            created = utc(t["created_at"]) or self.now
            new_rows.append({"id": info.id, "tenant_id": self.tenant_id, "code": "", "name": info.name, "department_id": dept[0],
                             "test_type_id": type_id, "price": price, "is_active": t["status"] == 1, "legacy_id": t["id"],
                             "created_at": created, "updated_at": utc(t["updated_at"]) or created})
            by_name[info.name.lower()] = info
            self.test_by_legacy[t["id"]] = info
            tally.created += 1
        self._insert(LabTest.__table__, new_rows)

    # -- bills as the old app has them
    def load_invoices(self) -> None:
        self.old_invoices = self._old_rows(
            "SELECT i.*, p.id AS pay_id, p.customer_id, p.paid_amount, p.due_amount, p.total_amount, p.payment_mode "
            "FROM invoices i LEFT JOIN payments p ON p.invoice_id = i.id ORDER BY i.id, p.id")
        self.old_items: dict[int, list] = defaultdict(list)
        for d in self._old_rows("SELECT * FROM invoice_details ORDER BY id"):
            self.old_items[d["invoice_id"]].append(d)
        self.old_payments: dict[int, list] = defaultdict(list)
        for p in self._old_rows("SELECT * FROM payment_details ORDER BY id"):
            self.old_payments[p["invoice_id"]].append(p)

    # -- referring doctors
    def import_doctors(self) -> None:
        groups: dict[str, Counter[str]] = defaultdict(Counter)
        seen = set()
        for inv in self.old_invoices:
            if inv["id"] in seen:
                continue
            seen.add(inv["id"])
            key = doctor_key(inv["doctor"])
            if key:
                groups[key][collapse(inv["doctor"])] += 1
        self.doctor_spellings = len({s for c in groups.values() for s in c})
        existing = {r.name.lower(): (r.id, r.name) for r in self._new_rows("SELECT id, name FROM referring_doctors WHERE tenant_id = :t",
                                                                             t=self.tenant_id)}
        tally = self.counts["referring_doctors"]
        self.doctor_by_key: dict[str, tuple[uuid.UUID, str]] = {}
        rows = []
        for key in sorted(groups):
            spellings = groups[key]
            name = doctor_display(spellings)[:200]
            tally.source += len(spellings)
            tally.merged += len(spellings) - 1
            self.doctors.append((name, sorted(spellings), sum(spellings.values())))
            if name.lower() in existing:
                self.doctor_by_key[key] = existing[name.lower()]
                tally.matched += 1
                continue
            row = {"id": uuid.uuid4(), "tenant_id": self.tenant_id, "name": name, "qualification": "", "phone": "", "is_active": True,
                   "created_at": self.now}
            rows.append(row)
            existing[name.lower()] = self.doctor_by_key[key] = (row["id"], name)
            tally.created += 1
        self._insert(ReferringDoctor.__table__, rows)
        self.doctors.sort(key=lambda d: (-d[2], d[0]))

    # -- patients
    def import_patients(self) -> None:
        customers = self._old_rows("SELECT * FROM customers ORDER BY id")
        self.customers = {c["id"]: c for c in customers}
        existing = self._new_rows("SELECT id, patient_no, name, mobile, legacy_customer_ids FROM patients WHERE tenant_id = :t", t=self.tenant_id)
        self.patient_by_customer: dict[int, uuid.UUID] = {}
        by_key: dict[str, uuid.UUID] = {}
        highest = 0
        for p in existing:
            for cid in p.legacy_customer_ids or []:
                self.patient_by_customer[int(cid)] = p.id
            if p.legacy_customer_ids and (key := patient_key(p.name, p.mobile)):
                by_key[key] = p.id
            if re.fullmatch(r"P\d+", p.patient_no):
                highest = max(highest, int(p.patient_no[1:]))
        counter = self.new.execute(text("SELECT value FROM counters WHERE tenant_id = :t AND name = 'patient'"), {"t": self.tenant_id}).scalar()
        highest = max(highest, counter or 0)

        tally = self.counts["patients"]
        groups: dict[str, list] = {}
        for c in customers:
            tally.source += 1
            if c["id"] in self.patient_by_customer:
                tally.matched += 1
                continue
            age, how = parse_age(c["age"])
            if how in ("unreadable", "out_of_range"):
                self.issue("age_unreadable", c["id"], f"age {c['age']!r} ({how}); left empty")
            elif how:
                self.stats[f"age_{how}"] += 1
            groups.setdefault(patient_key(c["name"], c["mobile_no"]) or f"#{c['id']}", []).append(c)

        rows = []
        for key, members in groups.items():
            ids = [c["id"] for c in members]
            if key in by_key:  # a later visit by someone brought across in an earlier run
                self.new.execute(text("UPDATE patients SET legacy_customer_ids = legacy_customer_ids || CAST(:ids AS jsonb) WHERE id = :i"),
                                 {"ids": str(ids), "i": by_key[key]})
                self.patient_by_customer.update(dict.fromkeys(ids, by_key[key]))
                tally.merged += len(ids)
                continue
            latest, earliest = members[-1], members[0]
            age = next((a for a, _ in (parse_age(c["age"]) for c in reversed(members)) if a is not None), None)
            email = collapse(latest["email"]).lower()
            highest += 1
            created = utc(earliest["created_at"]) or self.now
            row = {"id": uuid.uuid4(), "tenant_id": self.tenant_id, "patient_no": f"P{highest:06d}", "name": collapse(latest["name"])[:200],
                   "guardian_name": guardian(latest["co"])[:200], "age_years": age, "date_of_birth": None, "gender": gender(latest["gender"]),
                   "mobile": collapse(latest["mobile_no"])[:20], "email": email[:200] if "@" in email else "",
                   "address": collapse(latest["address"]), "legacy_customer_ids": ids,
                   "created_by": self.user_by_legacy.get(earliest["created_by"], (None,))[0],
                   "created_at": created, "updated_at": max(utc(c["updated_at"]) or created for c in members)}
            rows.append(row)
            self.patient_by_customer.update(dict.fromkeys(ids, row["id"]))
            tally.created += 1
            tally.merged += len(ids) - 1
        self._insert(Patient.__table__, rows)

    # -- bills, bill lines and payments
    def import_invoices(self) -> None:
        existing = {r.legacy_id: r for r in self._new_rows(
            "SELECT id, legacy_id, total, paid, due FROM invoices WHERE tenant_id = :t AND legacy_id IS NOT NULL", t=self.tenant_id)}
        used = {r.invoice_no for r in self._new_rows("SELECT invoice_no FROM invoices WHERE tenant_id = :t", t=self.tenant_id)}
        self.paid_ids = {r.legacy_id for r in self._new_rows(
            "SELECT legacy_id FROM payments WHERE tenant_id = :t AND legacy_id IS NOT NULL", t=self.tenant_id)}
        invoices, items_plain, items_report, payments = [], [], [], []
        ti, tl, tp = self.counts["invoices"], self.counts["invoice_items"], self.counts["payments"]
        seen: set[int] = set()
        for inv in self.old_invoices:
            if inv["id"] in seen:
                self.issue("invoice_payment_rows", inv["id"], f"more than one old payments row; used payments #{inv['pay_id']} only")
                continue
            seen.add(inv["id"])
            ti.source += 1
            details, pds = self.old_items.get(inv["id"], []), self.old_payments.get(inv["id"], [])
            tl.source += len(details)
            takings = sorted((p for p in pds if (p["current_paid_amount"] or 0) > 0), key=lambda p: (p["date"] or inv["date"], p["id"]))
            tp.source += len(takings)
            for p in pds:
                if (p["current_paid_amount"] or 0) < 0:
                    self.issue("payment_negative", p["id"], f"old payment of {p['current_paid_amount']} on bill #{inv['id']} left out")
            if inv["id"] in existing:
                ti.matched += 1
                tl.matched += len(details)
                self._later_payments(inv, existing[inv["id"]], takings, payments)
                continue
            built = self._build_invoice(inv, details, takings, used)
            if built is None:
                ti.skipped += 1
                tl.skipped += len(details)
                tp.skipped += len(takings)
                continue
            invoice, lines, money_in = built
            invoices.append(invoice)
            for line in lines:
                (items_report if line.get("legacy_report") else items_plain).append(line)
            payments.extend(money_in)
            ti.created += 1
            tl.created += len(lines)
            tp.created += len(money_in)
        self._insert(INVOICES, invoices)
        for group in (items_plain, items_report):
            for line in group:
                if not line.get("legacy_report"):
                    line.pop("legacy_report", None)
            self._insert(InvoiceItem.__table__, group)
        self._insert(Payment.__table__, payments)

    def _build_invoice(self, inv, details: list, takings: list, used: set[str]):
        if inv["pay_id"] is None:
            self.issue("invoice_without_payment_row", inv["id"], "no old payments row, so no total; bill left out")
            return None
        customer = self.customers.get(inv["customer_id"])
        patient_id = self.patient_by_customer.get(inv["customer_id"])
        if customer is None or patient_id is None:
            self.issue("invoice_customer_missing", inv["id"], f"customer #{inv['customer_id']} doesn't exist; bill left out")
            return None
        total, paid, due = money(inv["total_amount"]), money(inv["paid_amount"]), money(inv["due_amount"])
        taken = sum((money(p["current_paid_amount"]) for p in takings), ZERO)
        if taken != paid:
            self.issue("paid_mismatch", inv["id"], f"payments add up to {taken} but the bill says {paid} paid; bill left out")
            return None
        if total - paid != due or due < 0:
            self.issue("due_mismatch", inv["id"], f"total {total} - paid {paid} != due {due} (or due below zero); bill left out")
            return None

        invoice_id = uuid.uuid4()
        bill_date: date = inv["date"]
        created = utc(inv["created_at"]) or datetime.combine(bill_date, time(12), self.tz)
        updated = utc(inv["updated_at"]) or created
        delivered = inv["report_status"] == 1
        lines = []
        for position, d in enumerate(details, start=1):
            test = self.test_by_legacy.get(d["test_id"])
            if test is None:
                self.issue("test_missing", d["id"], f"bill #{inv['id']} (old no. {inv['invoice_no']}): test #{d['test_id']} no longer exists; "
                                                    f"kept as 'Unknown test (old #{d['test_id']})'")
            unit, amount = money(d["unit_price"]), money(d["selling_price"])
            quantity = int(d["selling_qty"]) if d["selling_qty"] and d["selling_qty"] == int(d["selling_qty"]) else 0
            if quantity < 1 or unit * quantity != amount:
                self.issue("item_amount_mismatch", d["id"], f"{d['selling_qty']} x {unit} != {amount}; kept as 1 x {amount}")
                unit, quantity = amount, 1
            report = {key: str(d[col]).strip() for col, key in REPORT_FIELDS.items() if d.get(col) is not None and str(d[col]).strip()}
            lines.append({
                "id": uuid.uuid4(), "tenant_id": self.tenant_id, "invoice_id": invoice_id, "position": position,
                "test_id": test.id if test else None, "test_name": test.name if test else f"Unknown test (old #{d['test_id']})",
                "department_id": test.department_id if test else None, "department_name": test.department_name if test else "",
                "is_imaging": test.is_imaging if test else False, "unit_price": unit, "quantity": quantity, "amount": amount,
                "status": "delivered" if delivered else "billed", "accession_no": "", "status_changed_at": updated if delivered else None,
                "legacy_id": d["id"], "legacy_report": report or None,
            })
        subtotal = sum((line["amount"] for line in lines), ZERO)
        if subtotal < total:
            extra = total - subtotal
            self.issue("total_above_lines", inv["id"], f"bill total {total} is above its lines ({subtotal}); added '{ADJUSTMENT}' for {extra}")
            lines.append({"id": uuid.uuid4(), "tenant_id": self.tenant_id, "invoice_id": invoice_id,
                          "position": len(lines) + 1, "test_id": None, "test_name": ADJUSTMENT, "department_id": None, "department_name": "",
                          "is_imaging": False, "unit_price": extra, "quantity": 1, "amount": extra, "status": "billed", "accession_no": "",
                          "status_changed_at": None, "legacy_id": None, "legacy_report": None})
            subtotal = total
        discount = subtotal - total

        number = invoice_number(self.prefix, bill_date, inv["invoice_no"], used)
        if "-" in number.rsplit("/", 1)[-1]:
            self.issue("invoice_no_duplicate", inv["id"], f"old bill no. {inv['invoice_no']} is used more than once; this one is {number}")
        doctor_id, doctor_name = self.doctor_by_key.get(doctor_key(inv["doctor"]), (None, ""))
        if inv["status"] not in (0, 1):
            self.issue("invoice_status_unknown", inv["id"], f"status {inv['status']}; put on hold")
        created_by_name = collapse(inv["created_by"])
        created_by = self.user_by_name.get(created_by_name.lower())
        if created_by_name and created_by is None:
            self.stats["created_by_unmatched"] += 1
        age, _ = parse_age(customer["age"])
        invoice = {
            "id": invoice_id, "tenant_id": self.tenant_id, "invoice_no": number, "legacy_no": inv["invoice_no"], "legacy_id": inv["id"],
            "bill_date": bill_date, "patient_id": patient_id, "patient_name": collapse(customer["name"])[:200],
            "patient_age": age_text(Patient(age_years=age, date_of_birth=None)), "patient_gender": gender(customer["gender"]),
            "patient_mobile": collapse(customer["mobile_no"])[:20], "patient_address": collapse(customer["address"]),
            "guardian_name": guardian(customer["co"])[:200], "referring_doctor_id": doctor_id, "referring_doctor_name": doctor_name,
            "status": "confirmed" if inv["status"] == 1 else "on_hold", "subtotal": subtotal,
            "discount_type": "amount" if discount > 0 else "none", "discount_value": discount, "discount_amount": discount,
            "total": total, "paid": paid, "due": due, "notes": strip_html(inv["description"]), "cancel_reason": "",
            "created_by": created_by, "created_by_name": created_by_name[:200], "created_at": created, "updated_at": updated,
        }
        money_in = [self._payment(p, inv["payment_mode"], invoice_id, bill_date, created_by, created_by_name) for p in takings]
        return invoice, lines, money_in

    def _payment(self, p, old_mode: str | None, invoice_id: uuid.UUID, bill_date: date, fallback_user: uuid.UUID | None,
                 fallback_name: str) -> dict:
        """One old payment_details row. The mode is kept on the old payments row, one per bill."""
        mode, note = "cash", ""
        old_mode = collapse(old_mode).lower()
        if old_mode == "online":
            mode, note = "upi", "Online (old system)"
        elif old_mode != "cash":
            mode, note = "other", f"{old_mode or 'unknown'} (old system)"
            self.issue("payment_mode_unknown", p["id"], f"payment mode {old_mode!r}; recorded as other")
        user_id, user_name = fallback_user, fallback_name
        if p["updated_by"] is not None:
            if p["updated_by"] in self.user_by_legacy:
                user_id, user_name = self.user_by_legacy[p["updated_by"]]
            else:
                self.issue("payment_user_unknown", p["id"], f"taken by old user #{p['updated_by']}, who doesn't exist; credited to the bill's maker")
        return {"id": uuid.uuid4(), "tenant_id": self.tenant_id, "invoice_id": invoice_id, "kind": "payment",
                "amount": money(p["current_paid_amount"]), "mode": mode, "reference": "", "note": note,
                "received_at": utc(p["created_at"]) or datetime.combine(bill_date, time(12), self.tz),
                "received_on": p["date"] or bill_date, "received_by": user_id, "received_by_name": (user_name or "")[:200],
                "legacy_id": p["id"]}

    def _later_payments(self, inv, current, takings: list, out: list) -> None:
        """Money the old app took on a bill after it was brought across: add those payments and its new paid and due."""
        later = [p for p in takings if p["id"] not in self.paid_ids]
        tally = self.counts["payments"]
        tally.matched += len(takings) - len(later)
        if not later:
            return
        total, paid, due = money(inv["total_amount"]), money(inv["paid_amount"]), money(inv["due_amount"])
        added = sum((money(p["current_paid_amount"]) for p in later), ZERO)
        if total != current.total or current.paid + added != paid or total - paid != due or due < 0:
            self.issue("later_payment_mismatch", inv["id"], f"{len(later)} new old-app payment(s) of {added} don't add up "
                                                            f"(bill total {total}, paid {paid}, due {due}); left out")
            tally.skipped += len(later)
            return
        user = self.user_by_name.get(collapse(inv["created_by"]).lower())
        out.extend(self._payment(p, inv["payment_mode"], current.id, inv["date"], user, collapse(inv["created_by"])) for p in later)
        self.new.execute(text("UPDATE invoices SET paid = :p, due = :d, updated_at = now() WHERE id = :i"), {"p": paid, "d": due, "i": current.id})
        tally.created += len(later)

    # -- running numbers
    def set_counters(self) -> None:
        numbers = [int(r.patient_no[1:]) for r in self._new_rows("SELECT patient_no FROM patients WHERE tenant_id = :t", t=self.tenant_id)
                   if re.fullmatch(r"P\d+", r.patient_no)]
        if numbers:
            set_at_least(self.new, self.tenant_id, "patient", max(numbers))  # type: ignore[arg-type]
        per_year: dict[str, int] = {}
        for r in self._new_rows("SELECT bill_date, legacy_no FROM invoices WHERE tenant_id = :t AND legacy_id IS NOT NULL", t=self.tenant_id):
            fy = financial_year(r.bill_date)
            per_year[fy] = max(per_year.get(fy, 0), r.legacy_no or 0)
        for fy, value in sorted(per_year.items()):
            set_at_least(self.new, self.tenant_id, f"invoice:{fy}", value)  # type: ignore[arg-type]
            self.notes.append(f"Counter invoice:{fy} set to at least {value}.")
        if numbers:
            self.notes.append(f"Counter patient set to at least {max(numbers)}.")


# ---------- old against new -----------------------------------------------------------------------------

def reconcile(new: Connection, old: Connection, tenant_id: uuid.UUID) -> list[tuple[str, str, str, str, bool]]:
    """(check, key, old, new, matches) for the counts, each calendar month's billed, paid and due, and every bill's due."""
    checks: list[tuple[str, str, str, str, bool]] = []

    def add(check: str, key: str, old_value: object, new_value: object) -> None:
        checks.append((check, key, str(old_value), str(new_value), old_value == new_value))

    def one(sql: str, conn: Connection, **params) -> int:
        return int(conn.execute(text(sql), params).scalar() or 0)

    t = {"t": tenant_id}
    add("count", "invoices", one("SELECT COUNT(*) FROM invoices", old), one(
        "SELECT COUNT(*) FROM invoices WHERE tenant_id = :t AND legacy_id IS NOT NULL", new, **t))
    add("count", "invoice_items", one("SELECT COUNT(*) FROM invoice_details", old), one(
        "SELECT COUNT(*) FROM invoice_items WHERE tenant_id = :t AND legacy_id IS NOT NULL", new, **t))
    add("count", "payments", one("SELECT COUNT(*) FROM payment_details WHERE current_paid_amount > 0", old), one(
        "SELECT COUNT(*) FROM payments WHERE tenant_id = :t AND legacy_id IS NOT NULL", new, **t))
    old_customers = {r[0] for r in old.execute(text("SELECT id FROM customers"))}
    covered = {int(c) for (ids,) in new.execute(text("SELECT legacy_customer_ids FROM patients WHERE tenant_id = :t"), t) for c in ids or []}
    add("count", "customers brought across", len(old_customers), len(old_customers & covered))

    old_bills = {r.id: r for r in old.execute(text(
        "SELECT i.id, i.date, p.total_amount, p.paid_amount, p.due_amount FROM invoices i JOIN payments p ON p.invoice_id = i.id"))}
    new_bills = {r.legacy_id: r for r in new.execute(text(
        "SELECT legacy_id, bill_date, total, paid, due FROM invoices WHERE tenant_id = :t AND legacy_id IS NOT NULL"), t)}
    months_old: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO])
    months_new: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO])
    for r in old_bills.values():
        m = months_old[r.date.strftime("%Y-%m")]
        for i, v in enumerate((r.total_amount, r.paid_amount, r.due_amount)):
            m[i] += money(v)
    for r in new_bills.values():
        m = months_new[r.bill_date.strftime("%Y-%m")]
        for i, v in enumerate((r.total, r.paid, r.due)):
            m[i] += v
    for month in sorted(set(months_old) | set(months_new)):
        for i, what in enumerate(("billed", "paid", "due")):
            add(f"month {what}", month, months_old[month][i], months_new[month][i])
    for legacy_id in sorted(set(old_bills) | set(new_bills)):
        o, n = old_bills.get(legacy_id), new_bills.get(legacy_id)
        add("invoice due", str(legacy_id), money(o.due_amount) if o else "missing", n.due if n else "missing")
    return checks


# ---------- running it ----------------------------------------------------------------------------------

def run(tenant: str = "supreme", legacy_url: str = DEFAULT_LEGACY_URL, target_url: str | None = None, dry_run: bool = False,
        report_root: Path | None = None) -> Outcome:
    target = create_engine(target_url or get_settings().migration_database_url, poolclass=NullPool)
    source = create_engine(legacy_url, poolclass=NullPool, connect_args={"init_command": "SET time_zone = '+00:00'"})
    try:
        with source.connect() as old, target.connect() as new:
            tx = new.begin()
            try:
                new.execute(text("SELECT set_config('app.platform', 'on', true)"))
                job = LegacyImport(new, old, tenant)
                job.run()
                checks = reconcile(new, old, job.tenant_id)
                if dry_run:
                    tx.rollback()
                else:
                    tx.commit()
            except BaseException:
                tx.rollback()
                raise
    finally:
        target.dispose()
        source.dispose()
    stamp = datetime.now(ZoneInfo(get_settings().display_timezone)).strftime("%Y%m%d-%H%M%S")
    folder = (report_root or Path(get_settings().storage_dir) / "import") / stamp
    outcome = Outcome(job.tenant_id, dry_run, folder, dict(job.counts), job.issues, job.notes, job.doctors, checks,
                      job.doctor_spellings, dict(job.stats))
    write_report(outcome, tenant)
    return outcome


def write_report(o: Outcome, tenant: str) -> None:
    o.report_dir.mkdir(parents=True, exist_ok=True)
    with (o.report_dir / "issues.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["kind", "legacy_id", "detail"])
        w.writerows((i.kind, i.legacy_id, i.detail) for i in o.issues)
    with (o.report_dir / "doctors.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["canonical_name", "legacy_spellings", "bill_count"])
        w.writerows((name, " | ".join(spellings), count) for name, spellings, count in o.doctors)
    with (o.report_dir / "reconciliation.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["check", "key", "old", "new", "ok"])
        w.writerows((c, k, a, b, "yes" if ok else "NO") for c, k, a, b, ok in o.checks)

    by_kind = Counter(i.kind for i in o.issues)
    failed = [c for c in o.checks if not c[4]]
    lines = [
        f"# Data move from the old app: {tenant}",
        "",
        f"- When: {o.report_dir.name}",
        f"- Mode: {'DRY RUN (rolled back, nothing saved)' if o.dry_run else 'saved'}",
        f"- Reconciliation: {'OK' if not failed else f'{len(failed)} mismatch(es)'}",
        "",
        "## Rows in and out",
        "",
        "| table | old rows | created | already there | merged | left out |",
        "|---|---:|---:|---:|---:|---:|",
        *(f"| {name} | {t.source} | {t.created} | {t.matched} | {t.merged} | {t.skipped} |" for name, t in o.counts.items()),
        "",
        f"Referring doctors: {o.doctor_spellings} spellings grouped into {len(o.doctors)} doctors (see doctors.csv). "
        "For doctors, 'old rows' counts spellings.",
        "",
        "## Decisions applied",
        "",
        *(f"- {rule}" for rule in RULES),
        *(f"- {note}" for note in o.notes),
        *(f"- {key.replace('_', ' ')}: {n} row(s)" for key, n in sorted(o.stats.items())),
        "",
        f"## Issues ({len(o.issues)})",
        "",
        *(f"- {kind}: {n}" for kind, n in sorted(by_kind.items())),
        "",
        "| kind | old id | detail |",
        "|---|---:|---|",
        *(f"| {i.kind} | {i.legacy_id} | {i.detail.replace('|', '/')} |" for i in o.issues),
        "",
        "## Reconciliation",
        "",
        *(f"- {c}: {k}: old {a}, new {b}" for c, k, a, b, _ in failed[:200]),
        *(["- Everything matches."] if not failed else []),
        "",
    ]
    (o.report_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def summary(o: Outcome) -> str:
    c = o.counts
    by_kind = Counter(i.kind for i in o.issues)
    failed = [x for x in o.checks if not x[4]]
    out = [
        f"{'DRY RUN, rolled back' if o.dry_run else 'Saved'}.",
        f"Patients: {c['patients'].created} created from {c['patients'].source} customer rows ({c['patients'].merged} merged, "
        f"{c['patients'].matched} already there)",
        f"Doctors: {o.doctor_spellings} spellings -> {len(o.doctors)} doctors ({c['referring_doctors'].created} new)",
        *(f"{name}: {t.created} created, {t.matched} already there, {t.merged} merged, {t.skipped} left out (of {t.source})"
          for name, t in c.items() if name not in ("patients", "referring_doctors")),
        f"Issues: {len(o.issues)} " + ", ".join(f"{k}={n}" for k, n in sorted(by_kind.items())),
        f"Report: {o.report_dir}",
        "Reconciliation: OK" if not failed else f"Reconciliation: {len(failed)} MISMATCH(ES)",
        *(f"  {a}: {b}: old {x}, new {y}" for a, b, x, y, _ in failed[:20]),
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.legacy_import", description="Bring the old app's data into a client's tables.")
    parser.add_argument("--dry-run", action="store_true", help="do everything in one transaction, then roll it back")
    parser.add_argument("--tenant", default="supreme", help="the client's address name (default: supreme)")
    parser.add_argument("--legacy-url", default=DEFAULT_LEGACY_URL, help="the old MariaDB database")
    args = parser.parse_args(argv)
    try:
        outcome = run(args.tenant, args.legacy_url, dry_run=args.dry_run)
    except ImportFailed as exc:
        print(f"Import stopped: {exc}", file=sys.stderr)
        return 2
    print(summary(outcome))
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    sys.exit(main())
