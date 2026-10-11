"""A signed report as an A4 PDF, laid out like the printed report (web/src/pages/reports/ReportPrint.svelte):
the centre's letterhead, the patient block, title, technique, findings, impression, the signature and a
verification line. Used for WhatsApp and for "Download PDF".

Findings and impression are the cleaned editor HTML (app.core.html_clean), turned into PDF paragraphs here."""

import html
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
from zoneinfo import ZoneInfo

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings

INLINE = {"strong": "b", "b": "b", "em": "i", "i": "i", "u": "u", "s": "strike", "sub": "sub", "sup": "super"}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    body = ParagraphStyle("body", parent=base, fontName="Helvetica", fontSize=10, leading=14, spaceAfter=4)
    return {
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555")),
        "h": ParagraphStyle("h", parent=body, fontName="Helvetica-Bold", fontSize=11, leading=15, spaceBefore=6, spaceAfter=3),
        "section": ParagraphStyle("section", parent=body, fontName="Helvetica-Bold", fontSize=10, leading=14, spaceBefore=8,
                                  spaceAfter=2, textColor=colors.HexColor("#333333")),
        "title": ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=17, alignment=TA_CENTER,
                                spaceBefore=6, spaceAfter=6),
        "centre": ParagraphStyle("centre", parent=body, fontName="Helvetica-Bold", fontSize=16, leading=20),
        "right": ParagraphStyle("right", parent=body, alignment=TA_RIGHT, spaceAfter=0),
        "quote": ParagraphStyle("quote", parent=body, leftIndent=12, textColor=colors.HexColor("#333333")),
    }


class _HtmlToFlowables(HTMLParser):
    """The small tag set the editor may produce, as reportlab flowables."""

    def __init__(self, styles: dict[str, ParagraphStyle]):
        super().__init__(convert_charrefs=True)
        self.s = styles
        self.out: list = []
        self.buf: list[str] = []
        self.block = "body"
        self.lists: list[list] = []  # [kind, counter]
        self.rows: list[list[str]] | None = None
        self.cell: list[str] | None = None

    def _flush(self) -> None:
        text = "".join(self.buf).strip()
        self.buf = []
        if not text:
            return
        if self.lists:
            kind = self.lists[-1]
            kind[1] += 1
            bullet = f"{kind[1]}." if kind[0] == "ol" else "•"
            style = ParagraphStyle("li", parent=self.s["body"], leftIndent=14 * len(self.lists), bulletIndent=14 * len(self.lists) - 10)
            self.out.append(Paragraph(text, style, bulletText=bullet))
        else:
            self.out.append(Paragraph(text, self.s[self.block]))

    def handle_starttag(self, tag, attrs):
        if self.cell is not None and tag in INLINE:
            self.cell.append(f"<{INLINE[tag]}>")
        elif tag in INLINE:
            self.buf.append(f"<{INLINE[tag]}>")
        elif tag == "br":
            (self.cell if self.cell is not None else self.buf).append("<br/>")
        elif tag in ("p", "h2", "h3", "h4", "blockquote", "li"):
            self._flush()
            self.block = "h" if tag.startswith("h") else "quote" if tag == "blockquote" else "body"
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag, 0])
        elif tag == "hr":
            self._flush()
            self.out.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey, spaceBefore=4, spaceAfter=4))
        elif tag == "table":
            self._flush()
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.rows.append([])
        elif tag in ("td", "th") and self.rows is not None:
            self.cell = ["<b>"] if tag == "th" else []

    def handle_endtag(self, tag):
        if self.cell is not None and tag in INLINE:
            self.cell.append(f"</{INLINE[tag]}>")
        elif tag in INLINE:
            self.buf.append(f"</{INLINE[tag]}>")
        elif tag in ("p", "h2", "h3", "h4", "blockquote", "li"):
            self._flush()
            self.block = "body"
        elif tag in ("ul", "ol") and self.lists:
            self._flush()
            self.lists.pop()
        elif tag in ("td", "th") and self.cell is not None and self.rows:
            if tag == "th":
                self.cell.append("</b>")
            self.rows[-1].append("".join(self.cell))
            self.cell = None
        elif tag == "table" and self.rows is not None:
            rows = [[Paragraph(c, self.s["body"]) for c in r] for r in self.rows if r]
            width = max((len(r) for r in rows), default=0)
            if width:
                rows = [r + [""] * (width - len(r)) for r in rows]
                t = Table(rows, hAlign="LEFT")
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                self.out.append(t)
            self.rows = None

    def handle_data(self, data):
        text = html.escape(data, quote=False)
        if self.cell is not None:
            self.cell.append(text)
        elif self.rows is None:
            self.buf.append(text)

    def result(self) -> list:
        self._flush()
        return self.out


def html_flowables(fragment: str, styles: dict[str, ParagraphStyle]) -> list:
    p = _HtmlToFlowables(styles)
    p.feed(fragment or "")
    p.close()
    return p.result()


def _when(value: datetime | None) -> str:
    if not value:
        return ""
    return value.astimezone(ZoneInfo(get_settings().display_timezone)).strftime("%d-%m-%Y %I:%M %p")


def _image(data: bytes | None, max_w: float, max_h: float) -> Image | None:
    if not data:
        return None
    try:
        img = Image(BytesIO(data))
    except Exception:
        return None
    scale = min(max_w / img.imageWidth, max_h / img.imageHeight, 1)
    img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
    return img


def qr_block(url: str, s: dict[str, ParagraphStyle]) -> Table:
    """The QR code for the patient's link, with a line saying what it is."""
    size = 24 * mm
    widget = QrCodeWidget(url, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    drawing.add(widget)
    t = Table([[drawing, Paragraph("Scan to view or download this report online.", s["small"])]], colWidths=[size + 4 * mm, 70 * mm],
              hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def report_pdf(data: dict, logo: bytes | None = None, signature: bytes | None = None) -> bytes:
    """data: what TestReportService.print_data returns."""
    s = _styles()
    c, item = data["centre"], data["item"]
    brand = colors.HexColor(c.get("brand_color") or "#0f6e6e")
    story: list = []

    # Letterhead
    head = [Paragraph(html.escape(c["legal_name"]), s["centre"])]
    if c.get("tagline"):
        head.append(Paragraph(html.escape(c["tagline"]), s["small"]))
    contact = " · ".join(x for x in (c.get("address", "").replace("\n", ", "), c.get("phones") and f"Phone: {c['phones']}",
                                       c.get("email")) if x)
    if contact:
        head.append(Paragraph(html.escape(contact), s["small"]))
    logo_img = _image(logo, 28 * mm, 22 * mm)
    top = Table([[logo_img, head]] if logo_img else [[head]], colWidths=[32 * mm, None] if logo_img else [None])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [top, HRFlowable(width="100%", thickness=1.5, color=brand, spaceBefore=4, spaceAfter=6)]

    # Patient block
    def kv(k: str, v: str) -> Paragraph:
        return Paragraph(f"<b>{html.escape(k)}:</b> {html.escape(v or '-')}", s["body"])
    age_sex = " / ".join(x for x in (item["patient_age"], item["patient_gender"].title()) if x)
    rows = [[kv("Patient", item["patient_name"]), kv("Age / Sex", age_sex)],
            [kv("Patient ID", data.get("patient_no", "")), kv("Bill no.", item["invoice_no"])],
            [kv("Referred by", item["referring_doctor_name"] or "Self"), kv("Date", item["bill_date"].strftime("%d-%m-%Y"))]]
    if item.get("accession_no"):
        rows.append([kv("Accession no.", item["accession_no"]), kv("Test", item["test_name"])])
    block = Table(rows, colWidths=["55%", "45%"])
    block.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.grey), ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [block, Spacer(1, 4)]

    title = html.escape(data["title"] or item["test_name"])
    story.append(Paragraph(title.upper(), s["title"]))
    if data.get("amended"):
        story.append(Paragraph(f"<font color='#b42318'><b>AMENDED REPORT</b></font> {html.escape(data.get('amend_reason') or '')}",
                               s["body"]))
    if data.get("technique"):
        story += [Paragraph("Technique", s["section"]), Paragraph(html.escape(data["technique"]), s["body"])]
    if data.get("findings"):
        story += [Paragraph("Findings", s["section"]), *html_flowables(data["findings"], s)]
    if data.get("impression"):
        story += [Paragraph("Impression", s["section"]), *html_flowables(data["impression"], s)]

    signer = data.get("signer")
    if signer:
        sign: list = [Spacer(1, 10)]
        sig_img = _image(signature, 45 * mm, 18 * mm)
        if sig_img:
            sig_img.hAlign = "RIGHT"
            sign.append(sig_img)
        sign.append(Paragraph(f"<b>{html.escape(signer['name'])}</b>", s["right"]))
        for line in (signer.get("degree"), signer.get("registration_no") and f"Reg. no. {signer['registration_no']}"):
            if line:
                sign.append(Paragraph(html.escape(line), s["right"]))
        story.append(KeepTogether(sign))

    if data.get("public_url"):
        story += [Spacer(1, 8), KeepTogether([qr_block(data["public_url"], s)])]

    verify = f"Report {data['verification']}"
    if signer and data.get("signed_at"):
        verify += f" · electronically signed by {signer['name']} on {_when(data['signed_at'])}"
    if not data.get("is_final"):
        verify += " · NOT SIGNED — not valid as a report"

    footer_text = c.get("report_footer", "")

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        y = 10 * mm
        if footer_text:
            canvas.drawString(doc.leftMargin, y + 9, footer_text.replace("\n", " ")[:160])
        canvas.drawString(doc.leftMargin, y, verify[:180])
        canvas.drawRightString(A4[0] - doc.rightMargin, y, f"Page {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=12 * mm, bottomMargin=22 * mm,
                            title=f"{item['test_name']} - {item['patient_name']}", author=c["legal_name"])
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
