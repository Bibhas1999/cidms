"""Turning a table (columns + rows + totals) into a CSV file, an Excel workbook, a printable PDF or a Word
document.

Columns are (key, label, kind) with kind one of text | money | int | date | datetime | percent. Rows and totals
are dicts keyed by column key. Money is Decimal; it's never turned into float on the way to a file.
"""

import csv as csv_module
import io
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm as DocxMm
from docx.shared import Pt, RGBColor
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


def _totals_row(columns: Sequence[Column], totals: dict) -> list[str]:
    """The totals row's text, column by column - column 0 is a label ("Total") unless it holds its own value."""
    line = []
    for i, (key, _, kind) in enumerate(columns):
        value = totals.get(key)
        line.append(cell_text(value, kind) if i else (str(value) if value not in (None, "") else "Total"))
    return line


# ---------- CSV ----------

def to_csv(columns: Sequence[Column], rows: Sequence[dict], totals: dict | None = None) -> bytes:
    """One table as CSV, the same cell text as everywhere else (Indian digit grouping, etc.). utf-8-sig so
    Excel opens it with the right encoding instead of guessing."""
    out = io.StringIO()
    writer = csv_module.writer(out)
    writer.writerow([label for _, label, _ in columns])
    for row in rows:
        writer.writerow([cell_text(row.get(key), kind) for key, _, kind in columns])
    if totals is not None:
        writer.writerow(_totals_row(columns, totals))
    return out.getvalue().encode("utf-8-sig")


# ---------- Excel ----------

def _sheet_title(title: str) -> str:
    cleaned = "".join("-" if ch in '[]:*?/\\' else ch for ch in title).strip()
    return (cleaned or "Report")[:31]


def to_xlsx(title: str, subtitle: str, columns: Sequence[Column], rows: Sequence[dict], totals: dict | None = None) -> bytes:
    """One report as a workbook with one sheet."""
    return to_xlsx_book([(title, subtitle, columns, rows, totals)])


# Workbook colours: the centre's brand blue for headings, a light tint for every other row, like an Excel table.
THEME = {"title": "0B2F6B", "head": "004AAD", "head_text": "FFFFFF", "band": "EEF4FC", "total": "DCE8F8",
         "line": "C9D3E3", "muted": "5B6B82", "tabs": ["004AAD", "F58634", "0B2F6B", "2E8B57", "8E44AD", "C0392B", "16A085", "D4A017"]}


def to_xlsx_book(sheets: Sequence[tuple[str, str, Sequence[Column], Sequence[dict], dict | None]],
                 summary: tuple[str, str, Sequence[Column], Sequence[dict], dict | None] | None = None) -> bytes:
    """Several reports in one workbook, one sheet each (in the order given), e.g. Collection, Dues, Payments…
    With `summary`, a first sheet lists one row per sheet; its first column links to that sheet."""
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    names = []
    for title, *_ in sheets:
        name = _sheet_title(title)
        n = 1
        while name.lower() in used:  # sheet names must be unique (Excel ignores case)
            n += 1
            name = _sheet_title(f"{_sheet_title(title)[:27]} ({n})")
        used.add(name.lower())
        names.append(name)
    if summary is not None:
        title, subtitle, columns, rows, totals = summary
        ws = wb.create_sheet(_sheet_title(title) if _sheet_title(title).lower() not in used else "Summary")
        _write_sheet(ws, title, subtitle, columns, rows, totals, tab=THEME["title"])
        for i, name in enumerate(names):
            cell = ws.cell(row=HEADER_ROW + 1 + i, column=1)
            cell.hyperlink = f"#'{name}'!A1"
            cell.font = Font(color=THEME["head"], underline="single")
    for i, (name, (title, subtitle, columns, rows, totals)) in enumerate(zip(names, sheets, strict=True)):
        _write_sheet(wb.create_sheet(name), title, subtitle, columns, rows, totals, tab=THEME["tabs"][i % len(THEME["tabs"])])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


HEADER_ROW = 4


def _write_sheet(ws, title: str, subtitle: str, columns: Sequence[Column], rows: Sequence[dict], totals: dict | None,
                 tab: str = THEME["head"]) -> None:
    ws.sheet_properties.tabColor = tab
    ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=15, color=THEME["title"])
    ws.cell(row=2, column=1, value=subtitle).font = Font(italic=True, color=THEME["muted"])
    header_row = HEADER_ROW
    head_fill = PatternFill("solid", fgColor=THEME["head"])
    band_fill = PatternFill("solid", fgColor=THEME["band"])
    total_fill = PatternFill("solid", fgColor=THEME["total"])
    line = Side(style="thin", color=THEME["line"])
    grid = Border(left=line, right=line, top=line, bottom=line)
    widths = [len(label) + 4 for _, label, _ in columns]

    for c, (_, label, kind) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=c, value=label)
        cell.font = Font(bold=True, color=THEME["head_text"])
        cell.fill = head_fill
        cell.border = grid
        cell.alignment = Alignment(horizontal="right" if kind in NUMERIC else "left", vertical="center")
    ws.row_dimensions[header_row].height = 22

    def put(r: int, c: int, value, kind: str):
        if kind == "money" and value is not None and value != "":
            value = Decimal(value)
        elif kind == "percent" and value is not None and value != "":
            value = Decimal(value) / 100
        elif kind == "datetime" and isinstance(value, datetime):
            value = local_dt(value).replace(tzinfo=None)
        cell = ws.cell(row=r, column=c, value=value)
        cell.border = grid
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
    for i, row in enumerate(rows):
        r += 1
        for c, (key, _, kind) in enumerate(columns, start=1):
            value = row.get(key)
            cell = put(r, c, value, kind)
            if i % 2:
                cell.fill = band_fill
            widths[c - 1] = max(widths[c - 1], min(len(cell_text(value, kind)) + 2, 60))
    last_data = r

    if totals is not None:
        r += 1
        for c, (key, _, kind) in enumerate(columns, start=1):
            value = totals.get(key)
            if c == 1 and value in (None, ""):
                value = "Total"
            cell = put(r, c, value, kind if c > 1 else "text")
            cell.font = Font(bold=True, color=THEME["title"])
            cell.fill = total_fill
            cell.border = Border(left=line, right=line, top=Side(style="medium", color=THEME["head"]), bottom=line)
            widths[c - 1] = max(widths[c - 1], min(len(cell_text(value, kind)) + 2, 60))

    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = max(w, 8)
    if columns:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(columns))}{max(last_data, header_row)}"
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.page_setup.orientation = "landscape" if len(columns) > 6 else "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


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
        texts = _totals_row(columns, totals)
        data.append([text if kind in NUMERIC and i else p(text, head)
                     for i, (text, (_, _, kind)) in enumerate(zip(texts, columns, strict=True))])

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
    footer = f"Generated {stamp}" + (f" by {generated_by}" if generated_by else "") + " · CIDMS"
    doc.build(story, canvasmaker=_numbered_canvas(pdf_safe(footer)))
    return out.getvalue()


# ---------- Word ----------

def to_docx(centre: TenantSettings | None, title: str, subtitle: str, columns: Sequence[Column], rows: Sequence[dict],
            totals: dict | None = None, generated_by: str = "") -> bytes:
    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = section.top_margin = DocxMm(14)
        section.bottom_margin = DocxMm(16)

    if centre:
        name = doc.add_paragraph()
        run = name.add_run(centre.legal_name)
        run.bold = True
        run.font.size = Pt(15)
        contact = [x for x in (centre.address.strip(), centre.phones.strip() and f"Phone: {centre.phones.strip()}") if x]
        if contact:
            cp = doc.add_paragraph()
            for i, line in enumerate(contact):
                if i:
                    cp.add_run().add_break()
                r = cp.add_run(line)
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    doc.add_heading(title, level=1)
    if subtitle:
        sp = doc.add_paragraph(subtitle)
        sp.runs[0].italic = True

    table = doc.add_table(rows=1, cols=max(len(columns), 1))
    table.style = "Light Grid Accent 1"

    def put(cell, text: str, kind: str, bold: bool = False):
        cell.text = text
        for para in cell.paragraphs:
            if kind in NUMERIC:
                para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            for r in para.runs:
                r.bold = bold
                r.font.size = Pt(9)

    head = table.rows[0].cells
    for c, (_, label, kind) in enumerate(columns):
        put(head[c], label, kind, bold=True)

    for row in rows:
        cells = table.add_row().cells
        for c, (key, _, kind) in enumerate(columns):
            put(cells[c], cell_text(row.get(key), kind), kind)

    if totals is not None:
        cells = table.add_row().cells
        for c, (text, (_, _, kind)) in enumerate(zip(_totals_row(columns, totals), columns, strict=True)):
            put(cells[c], text, kind, bold=True)

    if not rows:
        doc.add_paragraph("Nothing to show for these filters.")

    stamp = local_now().strftime("%d %b %Y %I:%M %p IST")
    footer = f"Generated {stamp}" + (f" by {generated_by}" if generated_by else "") + " · CIDMS"
    doc.add_paragraph()
    fp = doc.add_paragraph(footer)
    fp.runs[0].font.size = Pt(8)
    fp.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    out = io.BytesIO()
    doc.save(out)
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
