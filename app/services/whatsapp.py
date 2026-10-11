"""Sending a signed report's PDF to the patient on WhatsApp.

- Providers sit behind one small interface (WhatsAppProvider). The first is Meta's WhatsApp Business Cloud API:
  the PDF is uploaded (POST /{phone_number_id}/media), then an approved template message is sent with the PDF as
  its document header, and in the body the patient's name ({{1}}), the centre's name ({{2}}) and the patient's
  link to view the report online ({{3}}, the same link as the QR code).
- Sending is two steps: queue() records a delivery row (status "queued") and deliver() does the sending and
  records the outcome. The API runs both at once for now; a background job can run deliver() later instead.
- Meta reports what happened next (sent, delivered, read, failed) to the webhook, which updates the row.
- The access token is never logged or stored with a delivery.
"""

import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.phone import normalise_mobile
from app.core.security import CurrentUser
from app.models import Invoice, InvoiceItem, MessageDelivery, TenantSettings, TestReport, utcnow
from app.services.audit import AuditService

log = logging.getLogger("app.whatsapp")

transport: httpx.BaseTransport | None = None  # tests swap the network for an httpx.MockTransport
TIMEOUT = 15
STATUS_ORDER = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}


class SendFailed(Exception):
    """The provider refused or couldn't be reached. The message is safe to show and store (no secrets)."""


@dataclass
class Document:
    to: str            # E.164, "+919876543210"
    pdf: bytes
    filename: str
    params: list[str]  # template body parameters


class WhatsAppProvider(Protocol):
    name: str

    def send_document(self, doc: Document) -> str:
        """Send it; return the provider's message id. Raise SendFailed when it can't be sent."""
        ...


class MetaCloudProvider:
    name = "meta"

    def __init__(self) -> None:
        s = get_settings()
        self.base = f"https://graph.facebook.com/{s.whatsapp_api_version}/{s.whatsapp_phone_number_id}"
        self.token = s.whatsapp_token
        self.template, self.lang = s.whatsapp_template, s.whatsapp_template_lang

    @staticmethod
    def _error(r: httpx.Response) -> str:
        try:
            err = r.json().get("error", {})
            text = err.get("error_user_msg") or err.get("message") or ""
            code = err.get("code")
        except ValueError:
            text, code = "", None
        return (f"WhatsApp refused the message ({r.status_code}{f', code {code}' if code else ''}): {text}" if text
                else f"WhatsApp refused the message ({r.status_code}).")[:500]

    def send_document(self, doc: Document) -> str:
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            with httpx.Client(timeout=TIMEOUT, transport=transport, headers=headers) as http:
                up = http.post(f"{self.base}/media", data={"messaging_product": "whatsapp", "type": "application/pdf"},
                               files={"file": (doc.filename, doc.pdf, "application/pdf")})
                if up.status_code >= 400 or "id" not in up.json():
                    raise SendFailed(self._error(up))
                message = {
                    "messaging_product": "whatsapp", "to": doc.to.lstrip("+"), "type": "template",
                    "template": {"name": self.template, "language": {"code": self.lang}, "components": [
                        {"type": "header", "parameters": [{"type": "document", "document": {"id": up.json()["id"], "filename": doc.filename}}]},
                        {"type": "body", "parameters": [{"type": "text", "text": p} for p in doc.params]},
                    ]},
                }
                sent = http.post(f"{self.base}/messages", json=message)
                if sent.status_code >= 400:
                    raise SendFailed(self._error(sent))
                ids = sent.json().get("messages") or [{}]
                return str(ids[0].get("id", ""))
        except httpx.HTTPError as exc:
            log.warning("WhatsApp unreachable: %s", type(exc).__name__)  # never the request (it carries the token)
            raise SendFailed("Couldn't reach WhatsApp. Please try again in a few minutes.") from exc


def provider() -> WhatsAppProvider | None:
    s = get_settings()
    if s.whatsapp_provider == "meta" and s.whatsapp_token and s.whatsapp_phone_number_id:
        return MetaCloudProvider()
    return None


def is_configured() -> bool:
    return provider() is not None


def wa_me_link(to: str, centre: str) -> str:
    """A link that opens WhatsApp with a short note to the patient: only the centre's name, nothing about the report."""
    digits = to.lstrip("+")
    return f"https://wa.me/{digits}?text={quote(f'{centre}: your report is ready.')}" if digits else ""


class WhatsAppService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.audit = AuditService(db)

    def report(self, report_id: uuid.UUID) -> tuple[TestReport, InvoiceItem, Invoice]:
        row = self.db.execute(select(TestReport, InvoiceItem, Invoice).join(InvoiceItem, InvoiceItem.id == TestReport.invoice_item_id)
                              .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                              .where(TestReport.tenant_id == self.tenant_id, TestReport.id == report_id)).first()
        if row is None:
            raise NotFound("We couldn't find that report.")
        return row[0], row[1], row[2]

    def centre_name(self) -> str:
        settings = self.db.get(TenantSettings, self.tenant_id)
        return (settings.legal_name if settings else "") or (self.current.tenant.name if self.current.tenant else "")

    def history(self, report_id: uuid.UUID) -> list[MessageDelivery]:
        self.report(report_id)
        return list(self.db.scalars(select(MessageDelivery).where(MessageDelivery.tenant_id == self.tenant_id,
                                                                  MessageDelivery.report_id == report_id)
                                    .order_by(MessageDelivery.created_at.desc())))

    def default_to(self, invoice: Invoice) -> str:
        try:
            return normalise_mobile(invoice.patient_mobile)
        except ValueError:
            return ""

    def queue(self, report_id: uuid.UUID, to: str | None) -> MessageDelivery:
        if not self.current.can("reports.write"):
            raise Forbidden("You don't have permission to do that.")
        report, item, invoice = self.report(report_id)
        if report.status not in ("signed", "amended"):
            raise Conflict("Only a signed report can be sent to the patient.")
        if not is_configured():
            raise Conflict("WhatsApp isn't set up yet. Download the PDF and send it yourself.", "whatsapp")
        try:
            number = normalise_mobile(to) if to else self.default_to(invoice)
        except ValueError as exc:
            raise Invalid(str(exc), "to") from exc
        if not number:
            raise Invalid("Enter the patient's WhatsApp number.", "to")
        d = MessageDelivery(id=uuid.uuid4(), tenant_id=self.tenant_id, report_id=report.id, channel="whatsapp", to=number,
                            status="queued", provider=get_settings().whatsapp_provider, report_version=report.version,
                            sent_by=self.current.id, sent_by_name=self.current.user.full_name)
        self.db.add(d)
        self.db.flush()
        self.audit.record(self.tenant_id, self.current.id, "report.whatsapp_queued", "test_report", report.id, {
            "invoice_no": invoice.invoice_no, "test": item.test_name, "to": number, "delivery": str(d.id)})
        return d

    def deliver(self, delivery: MessageDelivery, pdf: bytes, filename: str, patient_name: str, link: str = "") -> MessageDelivery:
        """Send a queued delivery and record the outcome (never raises for a provider failure)."""
        p = provider()
        try:
            if p is None:
                raise SendFailed("WhatsApp isn't set up.")
            delivery.provider_message_id = p.send_document(Document(delivery.to, pdf, filename,
                                                                         [patient_name, self.centre_name(), link or "-"]))
            delivery.status, delivery.sent_at, delivery.error = "sent", utcnow(), ""
        except SendFailed as exc:
            delivery.status, delivery.error = "failed", str(exc)[:500]
        delivery.updated_at = utcnow()
        self.audit.record(self.tenant_id, self.current.id, f"report.whatsapp_{delivery.status}", "test_report", delivery.report_id, {
            "to": delivery.to, "delivery": str(delivery.id), "error": delivery.error})
        return delivery


# ---------- the webhook (Meta calls it; no user, no client address) ----------

def signature_ok(body: bytes, header: str) -> bool:
    secret = get_settings().whatsapp_app_secret
    if not secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def apply_statuses(db: Session, payload: dict) -> int:
    """Status updates from a webhook call. db must be a platform session: the message ids say whose rows they are."""
    updated = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for st in (change.get("value") or {}).get("statuses") or []:
                msg_id, new = str(st.get("id", "")), str(st.get("status", ""))
                if not msg_id or new not in ("sent", "delivered", "read", "failed"):
                    continue
                d = db.scalar(select(MessageDelivery).where(MessageDelivery.provider_message_id == msg_id))
                if d is None:
                    continue
                when = datetime.fromtimestamp(int(st.get("timestamp") or 0), UTC) if st.get("timestamp") else utcnow()
                if new == "failed":
                    errors = st.get("errors") or [{}]
                    d.status = "failed"
                    d.error = str(errors[0].get("title") or errors[0].get("message") or "WhatsApp couldn't deliver it.")[:500]
                elif STATUS_ORDER.get(new, 0) > STATUS_ORDER.get(d.status, -1):  # never step back (they can arrive out of order)
                    d.status = new
                if new == "sent" and not d.sent_at:
                    d.sent_at = when
                if new == "delivered":
                    d.delivered_at = d.delivered_at or when
                if new == "read":
                    d.read_at = d.read_at or when
                    d.delivered_at = d.delivered_at or when
                d.updated_at = utcnow()
                AuditService(db).record(d.tenant_id, None, f"report.whatsapp_{new}", "test_report", d.report_id, {"delivery": str(d.id)})
                updated += 1
    return updated
