"""Adding many departments, test types or tests at once: typed into a grid, pasted from a spreadsheet, or read from
an uploaded Excel sheet (or CSV). Every row is checked first and nothing is added unless every row is right, so a
half-imported list never happens; the browser shows each row's problem next to it."""

import csv
import io
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Literal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Invalid
from app.core.money import q2
from app.core.security import CurrentUser
from app.models import Department, LabTest, TestType
from app.services.audit import AuditService

Kind = Literal["departments", "test-types", "tests"]
MAX_ROWS = 1000

# The columns of each list: (field, heading in the sheet, other headings taken for it).
COLUMNS: dict[str, list[tuple[str, str, set[str]]]] = {
    "departments": [("name", "Department", {"name", "department name"})],
    "test-types": [("name", "Test type", {"name", "type"}),
                   ("imaging", "Has images", {"imaging", "images", "is imaging", "scan"})],
    "tests": [("name", "Test name", {"name", "test"}),
              ("code", "Short code", {"code"}),
              ("department", "Department", {"dept", "department name"}),
              ("test_type", "Test type", {"type"}),
              ("price", "Price", {"price (₹)", "price (rs)", "rate", "amount", "mrp"})],
}
WHAT = {"departments": ("department", "departments"), "test-types": ("test type", "test types"), "tests": ("test", "tests")}
NAME_MAX = {"departments": 100, "test-types": 100, "tests": 200}
YES = {"yes", "y", "true", "1"}
NO = {"no", "n", "false", "0", ""}


def _squash(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def _key(heading: str) -> str:
    return " ".join(heading.lower().replace("*", "").split())


class CatalogueImport:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    # ---------- reading a sheet ----------
    def parse(self, kind: Kind, filename: str, content: bytes) -> list[dict]:
        """The rows of the first sheet, by heading. The heading row may sit under a title (within the first 10 rows)."""
        if filename.lower().endswith(".csv"):
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("cp1252", errors="replace")
            table = list(csv.reader(io.StringIO(text)))
        else:
            try:
                book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            except (zipfile.BadZipFile, InvalidFileException, KeyError, ValueError) as exc:
                raise Invalid("We couldn't read that file. Save it as an Excel workbook (.xlsx) and try again.", "file") from exc
            sheet = book.worksheets[0]
            table = [list(r) for r in sheet.iter_rows(values_only=True, max_row=MAX_ROWS + 20)]
            book.close()

        lookup = {}
        for field, heading, others in COLUMNS[kind]:
            for h in {heading, *others}:
                lookup[_key(h)] = field
        headings = [(at, {i: lookup[_key(_squash(c))] for i, c in enumerate(row) if _key(_squash(c)) in lookup})
                    for at, row in enumerate(table[:10])]
        found = next(((at, fields) for at, fields in headings if "name" in fields.values()), None)
        if found is None:
            heading = COLUMNS[kind][0][1]
            raise Invalid(f'The first sheet needs a heading row with a "{heading}" column. Download the template to see the layout.', "file")
        heading_row, fields = found

        rows = []
        for raw in table[heading_row + 1:]:
            values = {field: _squash(raw[i]) if i < len(raw) else "" for i, field in fields.items()}
            if any(values.values()):
                rows.append({f: values.get(f, "") for f, _, _ in COLUMNS[kind]})
        if not rows:
            raise Invalid("That sheet has headings but no rows under them.", "file")
        if len(rows) > MAX_ROWS:
            raise Invalid(f"That sheet has {len(rows)} rows; add at most {MAX_ROWS} at a time.", "file")
        return rows

    def template(self, kind: Kind) -> bytes:
        """An empty sheet with the right headings; for tests, drop-downs of the centre's departments and test types."""
        book = Workbook()
        ws = book.active
        ws.title = WHAT[kind][1].capitalize()
        for col, (_, heading, _) in enumerate(COLUMNS[kind], start=1):
            cell = ws.cell(row=1, column=col, value=heading)
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="E6F0F0")
            ws.column_dimensions[cell.column_letter].width = 36 if col == 1 else 20
        ws.freeze_panes = "A2"
        if kind == "test-types":
            yes_no = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
            ws.add_data_validation(yes_no)
            yes_no.add(f"B2:B{MAX_ROWS + 1}")
        if kind == "tests":
            lists = book.create_sheet("Lists")
            depts = [d.name for d in self._all(Department) if d.is_active]
            types = [t.name for t in self._all(TestType) if t.is_active]
            lists["A1"], lists["B1"] = "Departments", "Test types"
            for i, name in enumerate(depts, start=2):
                lists.cell(row=i, column=1, value=name)
            for i, name in enumerate(types, start=2):
                lists.cell(row=i, column=2, value=name)
            for col, count, target in (("A", len(depts), "C"), ("B", len(types), "D")):
                if count:
                    dv = DataValidation(type="list", formula1=f"=Lists!${col}$2:${col}${count + 1}", allow_blank=True)
                    ws.add_data_validation(dv)
                    dv.add(f"{target}2:{target}{MAX_ROWS + 1}")
        out = io.BytesIO()
        book.save(out)
        return out.getvalue()

    # ---------- checking ----------
    def _all(self, model) -> list:
        return list(self.db.scalars(select(model).where(model.tenant_id == self.tenant_id)))

    def check(self, kind: Kind, rows: list[dict]) -> list[dict]:
        """Each row's cleaned values and its problems ({field: message}); an empty errors dict means it's right."""
        if len(rows) > MAX_ROWS:
            raise Invalid(f"Add at most {MAX_ROWS} at a time.", "rows")
        model = {"departments": Department, "test-types": TestType, "tests": LabTest}[kind]
        existing = {r.name.lower() for r in self._all(model)}
        depts = {d.name.lower(): d for d in self._all(Department)} if kind == "tests" else {}
        types = {t.name.lower(): t for t in self._all(TestType)} if kind == "tests" else {}
        seen: dict[str, int] = {}
        out = []
        for n, raw in enumerate(rows, start=1):
            v = {f: _squash(raw.get(f, "")) for f, _, _ in COLUMNS[kind]}
            errors: dict[str, str] = {}
            name, low = v["name"], v["name"].lower()
            if len(name) < 2:
                errors["name"] = "Enter a name." if not name else "Use at least 2 letters."
            elif len(name) > NAME_MAX[kind]:
                errors["name"] = f"Use at most {NAME_MAX[kind]} characters."
            elif low in existing:
                errors["name"] = f"There's already a {WHAT[kind][0]} called {name}."
            elif low in seen:
                errors["name"] = f"Listed twice (also row {seen[low]})."
            if name:
                seen.setdefault(low, n)
            if kind == "test-types":
                flag = v["imaging"].lower()
                if flag not in YES | NO:
                    errors["imaging"] = "Write Yes or No."
                v["imaging"] = "Yes" if flag in YES else "No"
            if kind == "tests":
                v["code"] = v["code"].upper()
                if len(v["code"]) > 20:
                    errors["code"] = "Use at most 20 characters."
                dept = depts.get(v["department"].lower())
                if not v["department"]:
                    errors["department"] = "Enter the department."
                elif dept is None:
                    errors["department"] = f"There's no department called {v['department']}. Add it first, or check the spelling."
                elif not dept.is_active:
                    errors["department"] = f"{dept.name} is switched off."
                else:
                    v["department"] = dept.name
                if v["test_type"]:
                    tt = types.get(v["test_type"].lower())
                    if tt is None:
                        errors["test_type"] = f"There's no test type called {v['test_type']}. Add it first, or leave it blank."
                    elif not tt.is_active:
                        errors["test_type"] = f"{tt.name} is switched off."
                    else:
                        v["test_type"] = tt.name
                price = v["price"].replace("₹", "").replace(",", "").removeprefix("Rs.").removeprefix("Rs").strip()
                try:
                    amount = Decimal(price)
                    if not amount.is_finite() or amount < 0 or amount > 10_000_000:
                        errors["price"] = "Enter a price from 0 to 1,00,00,000."
                    elif amount != amount.quantize(Decimal("0.01")):
                        errors["price"] = "Use at most 2 decimal places."
                    else:
                        v["price"] = f"{amount:.2f}"
                except InvalidOperation:
                    errors["price"] = "Enter the price." if not price else "Enter the price as a number, e.g. 450."
            out.append({"values": v, "errors": errors})
        return out

    # ---------- saving ----------
    def save(self, kind: Kind, rows: list[dict]) -> int:
        """Add every row, or none: if any row is wrong, 422 lists each problem as rows.<index>.<field>."""
        if not rows:
            raise Invalid("Add at least one row.", "rows")
        checked = self.check(kind, rows)
        detail = [{"field": f"rows.{i}.{field}", "message": msg}
                  for i, r in enumerate(checked) for field, msg in r["errors"].items()]
        if detail:
            bad = len({d["field"].split(".")[1] for d in detail})
            raise Invalid(f"{bad} row{'s' if bad != 1 else ''} need{'s' if bad == 1 else ''} fixing before anything is added.",
                          detail[0]["field"], detail)
        depts = {d.name: d.id for d in self._all(Department)}
        types = {t.name: t.id for t in self._all(TestType)}
        added = []
        for r in checked:
            v = r["values"]
            if kind == "departments":
                row = Department(tenant_id=self.tenant_id, name=v["name"], is_active=True)
                details, action = {"name": v["name"]}, "catalogue.department_saved"
            elif kind == "test-types":
                row = TestType(tenant_id=self.tenant_id, name=v["name"], is_imaging=v["imaging"] == "Yes", is_active=True)
                details, action = {"name": v["name"], "is_imaging": row.is_imaging}, "catalogue.test_type_saved"
            else:
                row = LabTest(tenant_id=self.tenant_id, name=v["name"], code=v["code"], department_id=depts[v["department"]],
                              test_type_id=types.get(v["test_type"]) if v["test_type"] else None,
                              price=q2(Decimal(v["price"])), is_active=True)
                details, action = {k: v[k] for k in ("name", "code", "department", "test_type", "price")}, "catalogue.test_saved"
            self.db.add(row)
            added.append((row, action, details))
        try:
            with self.db.begin_nested():
                self.db.flush()
        except IntegrityError as exc:
            raise Conflict("Someone added one of these at the same moment. Check the list and try again.", "rows") from exc
        entity = {"departments": "department", "test-types": "test_type", "tests": "test"}[kind]
        for row, action, details in added:
            self.audit.record(self.tenant_id, self.current.id, action, entity, row.id, {**details, "from": "bulk add"})
        return len(added)
