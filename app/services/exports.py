"""Turning a table (columns + rows + totals) into an Excel workbook or a printable PDF.

Columns are (key, label, kind) with kind one of text | money | int | date | datetime | percent. Rows and totals
are dicts keyed by column key. Money is Decimal; it's never turned into float on the way to the PDF.
"""

import io
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.pagesizes import landscape as to_landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings
from app.core.money import local_now, q2
from app.models import TenantSettings

Column = tuple[str, str, str]  # key, label, kind
NUMERIC = {"money", "int", "percent"}
MONEY_FORMAT = "#,##0.00"


# ---------- plain-text formatting (PDF, file names, subtitles) ----------

def indian(value: Decimal) -> str:
    """1,23,456.00: Indian digit grouping, no currency sign (the PDF's standard fonts have no ₹)."""
    v = q2(value)
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([g for g in [head, *groups] if g] + [tail])
    return f"{'-' if v < 0 else ''}{whole}.{frac}"


def day_text(d: date | None) -> str:
    return d.strftime("%d %b %Y") if d else ""


def local_dt(value: datetime) -> datetime:
    return value.astimezone(ZoneInfo(get_settings().display_timezone)) if value.tzinfo else value


def cell_text(value, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return indian(Decimal(value))
    if kind == "percent":
        return f"{Decimal(value):.2f}%"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "date" and isinstance(value, date):
        return day_text(value)
    if kind == "datetime" and isinstance(value, datetime):
        return local_dt(value).strftime("%d %b %Y %I:%M %p")
    return str(value)


def pdf_safe(text: str) -> str:
    """The standard PDF fonts can't draw ₹ (DejaVu isn't bundled), so it's written Rs."""
    return text.replace("₹", "Rs. ")


# ---------- Excel ----------

def _sheet_title(title: str) -> str:
    cleaned = "".join("-" if ch in '[]:*?/\\' else ch for ch in title).strip()
    return (cleaned or "Report")[:31]


def to_xlsx(title: str, subtitle: str, columns: Sequence[Column], rows: Sequence[dict], totals: dict | None = None) -> bytes:
    """One report as a workbook with one sheet."""
    return to_xlsx_book([(title, subtitle, columns, rows, totals)])


def to_xlsx_book(sheets: Sequence[tuple[str, str, Sequence[Column], Sequence[dict], dict | None]]) -> bytes:
    """Several reports in one workbook, one sheet each (in the order given), e.g. Collection, Dues, Payments…"""
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for title, subtitle, columns, rows, totals in sheets:
        name = _sheet_title(title)
        while name in used:  # sheet names must be unique
            name = _sheet_title(f"{name[:28]} {len(used)}")
        used.add(name)
        _write_sheet(wb.create_sheet(name), title, subtitle, columns, rows, totals)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _write_sheet(ws, title: str, subtitle: str, columns: Sequence[Column], rows: Sequence[dict], totals: dict | None) -> None:
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=14)
    ws.cell(row=2, column=1, value=subtitle).font = Font(italic=True, color="555555")
    header_row = 4
    head_fill = PatternFill("solid", fgColor="E6F0F0")
    line = Side(style="thin", color="999999")
    widths = [len(label) + 2 for _, label, _ in columns]

    for c, (_, label, kind) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=c, value=label)
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.border = Border(bottom=line)
        cell.alignment = Alignment(horizontal="right" if kind in NUMERIC else "left", vertical="center")

    def put(r: int, c: int, value, kind: str):
        if kind == "money" and value is not None and value != "":
            value = Decimal(value)
        elif kind == "percent" and value is not None and value != "":
            value = Decimal(value) / 100
        elif kind == "datetime" and isinstance(value, datetime):
            value = local_dt(value).replace(tzinfo=None)
        cell = ws.cell(row=r, column=c, value=value)
        if kind == "money":
            cell.number_format = MONEY_FORMAT
        elif kind == "percent":
            cell.number_format = "0.00%"
        elif kind == "int":
            cell.number_format = "#,##0"
        elif kind == "date":
            cell.number_format = "DD-MMM-YYYY"
        elif kind == "datetime":
            cell.number_format = "DD-MMM-YYYY HH:MM"
        return cell

    r = header_row
    for row in rows:
        r += 1
        for c, (key, _, kind) in enumerate(columns, start=1):
            value = row.get(key)
            put(r, c, value, kind)
            widths[c - 1] = max(widths[c - 1], min(len(cell_text(value, kind)) + 2, 60))

    if totals is not None:
        r += 1
        for c, (key, _, kind) in enumerate(columns, start=1):
            value = totals.get(key)
            if c == 1 and value in (None, ""):
                value = "Total"
            cell = put(r, c, value, kind if c > 1 else "text")
            cell.font = Font(bold=True)
            cell.border = Border(top=line)
            widths[c - 1] = max(widths[c - 1], min(len(cell_text(value, kind)) + 2, 60))

    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = max(w, 8)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.print_title_rows = f"{header_row}:{header_row}"


# ---------- PDF ----------

def _numbered_canvas(footer_left: str):
    """A canvas that waits until every page is laid out, so the footer can say "page x of y"."""
    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):  # noqa: N802 (reportlab's name)
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._footer(total)
                super().showPage()
            super().save()

        def _footer(self, total: int):
            width, _ = self._pagesize
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#666666"))
            self.drawString(12 * mm, 8 * mm, footer_left)
            self.drawRightString(width - 12 * mm, 8 * mm, f"Page {self._pageNumber} of {total}")
    return NumberedCanvas


def _wordmark(centre: TenantSettings, max_width: float):
    """The centre's wide logo as a PDF image, 16 mm tall (narrower if needed), or None."""
    import base64

    from reportlab.platypus import Image as PdfImage
    if not getattr(centre, "wordmark_data", ""):
        return None
    try:
        raw = io.BytesIO(base64.b64decode(centre.wordmark_data))
        from PIL import Image
        with Image.open(raw) as im:
            w, h = im.size
        raw.seek(0)
        height = 16 * mm
        width = min(max_width * 0.6, height * w / h)
        img = PdfImage(raw, width=width, height=width * h / w)
        img.hAlign = "LEFT"
        return img
    except Exception:  # a broken picture must never stop the export
        return None


def to_pdf(centre: TenantSettings, title: str, subtitle: str, columns: Sequence[Column], rows: Sequence[dict],
           totals: dict | None = None, landscape: bool = False, generated_by: str = "") -> bytes:
    page = to_landscape(A4) if landscape else A4
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
                            title=pdf_safe(title), author=pdf_safe(centre.legal_name if centre else ""))
    brand = colors.HexColor(centre.brand_color) if centre and centre.brand_color and len(centre.brand_color) == 7 else colors.HexColor("#0f6e6e")
    name_style = ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=brand)
    small = ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#444444"))
    title_style = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=6)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold")
    head_right = ParagraphStyle("head_r", parent=head, alignment=2)

    def p(text: str, style=small) -> Paragraph:
        return Paragraph(escape(pdf_safe(text)).replace("\n", "<br/>"), style)

    story = []
    if centre:
        mark = _wordmark(centre, doc.width)
        story.append(mark if mark is not None else p(centre.legal_name, name_style))
        contact = [x for x in (centre.address.strip(), centre.phones.strip() and f"Phone: {centre.phones.strip()}") if x]
        if contact:
            story.append(p("\n".join(contact)))
    story.append(p(title, title_style))
    if subtitle:
        story.append(p(subtitle))
    story.append(Spacer(1, 4 * mm))

    data = [[p(label, head_right if kind in NUMERIC else head) for _, label, kind in columns]]
    for row in rows:
        data.append([cell_text(row.get(key), kind) if kind in NUMERIC else p(cell_text(row.get(key), kind), cell)
                     for key, _, kind in columns])
    if totals is not None:
        line = []
        for i, (key, _, kind) in enumerate(columns):
            value = totals.get(key)
            text = cell_text(value, kind) if i else (str(value) if value not in (None, "") else "Total")
            line.append(text if kind in NUMERIC and i else p(text, head))
        data.append(line)

    widths = _widths(columns, data, doc.width)
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6F0F0")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, (_, _, kind) in enumerate(columns):
        if kind in NUMERIC:
            style.append(("ALIGN", (i, 1), (i, -1), "RIGHT"))
    last_body = len(data) - (2 if totals is not None else 1)
    for r in range(2, last_body + 1, 2):
        style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#F5F7F7")))
    if totals is not None:
        style += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8),
                  ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#333333"))]
    table.setStyle(TableStyle(style))
    story.append(table)
    if not rows:
        story.append(Spacer(1, 3 * mm))
        story.append(p("Nothing to show for these filters."))

    stamp = local_now().strftime("%d %b %Y %I:%M %p IST")
    footer = f"Generated {stamp}" + (f" by {generated_by}" if generated_by else "") + " · Supreme DMS"
    doc.build(story, canvasmaker=_numbered_canvas(pdf_safe(footer)))
    return out.getvalue()


def _widths(columns: Sequence[Column], data: list[list], available: float) -> list[float]:
    """Share the page width by how long each column's text tends to be (numbers get what they need)."""
    want = []
    for i, (_, label, kind) in enumerate(columns):
        longest = len(label)
        for row in data[1:200]:
            v = row[i]
            n = len(v) if isinstance(v, str) else len(v.text) if isinstance(v, Paragraph) else 0
            longest = max(longest, n)
        cap = 14 if kind in NUMERIC or kind in ("date", "datetime") else 40
        want.append(max(min(longest, cap), 5))
    total = sum(want)
    return [available * w / total for w in want]
