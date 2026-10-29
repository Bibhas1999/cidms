"""Database tables: platform, clients, people, permissions, sessions, the activity log (phase 1) and
billing: catalogue, patients, bills and payments (phase 2).

Tables with a tenant_id are protected by row-level security (see migrations). A NULL tenant_id on users,
roles and sessions means platform staff or a built-in role shared by every client.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


Id = UUID(as_uuid=True)
Timestamp = DateTime(timezone=True)


class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    max_users: Mapped[int] = mapped_column(Integer)
    max_bills_per_month: Mapped[int] = mapped_column(Integer)
    storage_gb: Mapped[int] = mapped_column(Integer)
    price_monthly: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


class Tenant(Base):
    """A client: one diagnostic centre, OPD or clinic, reached at <slug>.<base domain>."""
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="diagnostic")  # diagnostic | opd | clinic
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | suspended
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"))
    paid_until: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)

    plan: Mapped[Plan | None] = relationship(lazy="joined")


class TenantSettings(Base):
    """What a client shows on its bills and reports."""
    __tablename__ = "tenant_settings"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(Text, default="")
    phones: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    gst_number: Mapped[str] = mapped_column(String(20), default="")
    invoice_prefix: Mapped[str] = mapped_column(String(10), default="INV")
    bill_footer: Mapped[str] = mapped_column(Text, default="")
    report_footer: Mapped[str] = mapped_column(Text, default="")
    max_discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20"))
    bill_paper: Mapped[str] = mapped_column(String(4), default="A5")  # A4 | A5
    brand_color: Mapped[str] = mapped_column(String(7), default="#0f6e6e")
    tagline: Mapped[str] = mapped_column(String(120), default="")
    logo_file: Mapped[str] = mapped_column(String(100), default="")  # version code of the logo ("" = no logo)
    logo_data: Mapped[str] = mapped_column(Text, default="")         # the logo as base64 PNG
    logo_mime: Mapped[str] = mapped_column(String(40), default="")
    # The wide logo with the centre's name and slogan, also base64 PNG (sign-in page, menu, bills, PDFs).
    wordmark_file: Mapped[str] = mapped_column(String(100), default="")
    wordmark_data: Mapped[str] = mapped_column(Text, default="")
    wordmark_mime: Mapped[str] = mapped_column(String(40), default="")
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class Permission(Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(60), primary_key=True)
    scope: Mapped[str] = mapped_column(String(10))  # platform | client
    description: Mapped[str] = mapped_column(String(200))


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))  # NULL = built in
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(10))  # platform | client
    description: Mapped[str] = mapped_column(String(300), default="")
    # A centre's own roles (Settings > Roles & permissions): who made them and when. NULL for built-in roles.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime | None] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)

    @property
    def is_builtin(self) -> bool:
        return self.tenant_id is None


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(200))  # stored lower-case; unique per client (see migration)
    full_name: Mapped[str] = mapped_column(String(200))
    mobile: Mapped[str] = mapped_column(String(20), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(Timestamp)
    last_login_at: Mapped[datetime | None] = mapped_column(Timestamp)
    legacy_id: Mapped[int | None] = mapped_column(Integer)  # users.id in the old Laravel app
    avatar_file: Mapped[str] = mapped_column(String(100), default="")  # version code of the picture ("" = none)
    avatar_data: Mapped[str] = mapped_column(Text, default="")         # profile picture as base64 PNG
    avatar_mime: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)

    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin", order_by=Role.name)


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class UserSession(Base):
    """A signed-in browser. The cookie holds a random token; only its SHA-256 hash is stored here."""
    __tablename__ = "sessions"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str] = mapped_column(String(300), default="")

    user: Mapped[User] = relationship(lazy="joined")


class PayloadKey(Base):
    """An AES key agreed with one browser tab (ECDH) for encrypted request and response bodies. Kept for a day."""
    __tablename__ = "payload_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


class PasswordReset(Base):
    """A "forgot password" link. The email carries a random token; only its SHA-256 hash is stored."""
    __tablename__ = "password_resets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    used_at: Mapped[datetime | None] = mapped_column(Timestamp)
    ip_address: Mapped[str | None] = mapped_column(INET)

    user: Mapped[User] = relationship(lazy="joined")


class ActivityLog(Base):
    """Who did what and when: sign-ins, sign-outs and every change. Never edited or removed by the app."""
    __tablename__ = "activity_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    request_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, index=True)

    user: Mapped[User | None] = relationship(lazy="joined")


# ---------- phase 2: billing ----------------------------------------------------------------------------

class Counter(Base):
    """Running numbers per client: patient numbers, and bill numbers per financial year ("invoice:2026-27").
    Taken under a row lock, so two people saving at once never get the same number."""
    __tablename__ = "counters"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0)


class Operation(Base):
    """A change sent with an Idempotency-Key: its answer is kept, so a retry (double click, flaky network)
    gets the same answer instead of creating a second bill or taking a second payment."""
    __tablename__ = "operations"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer)


class TestType(Base):
    """Kind of test, e.g. X-ray, CT scan, ECG, pathology. Imaging types get images and an accession number."""
    __tablename__ = "test_types"
    __test__ = False  # not a pytest test class
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    is_imaging: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer)


class LabTest(Base):
    """A test the centre offers, with its current price. Bills keep their own copy of name and price."""
    __tablename__ = "tests"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20), default="")
    name: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"))
    test_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("test_types.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)

    department: Mapped[Department] = relationship(lazy="joined")
    test_type: Mapped[TestType | None] = relationship(lazy="joined")


class ReferringDoctor(Base):
    __tablename__ = "referring_doctors"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    qualification: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    patient_no: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    guardian_name: Mapped[str] = mapped_column(String(200), default="")  # C/O on the old bills
    age_years: Mapped[int | None] = mapped_column(Integer)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String(10))  # male | female | other
    mobile: Mapped[str] = mapped_column(String(20), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    legacy_customer_ids: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class Invoice(Base):
    """A bill. Keeps a copy of the patient's details as billed. Paid and due are worked out from its payments."""
    __tablename__ = "invoices"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    invoice_no: Mapped[str] = mapped_column(String(40))
    legacy_no: Mapped[int | None] = mapped_column(Integer)
    legacy_id: Mapped[int | None] = mapped_column(Integer)  # invoices.id in the old Laravel app
    bill_date: Mapped[date] = mapped_column(Date)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id"))
    patient_name: Mapped[str] = mapped_column(String(200))
    patient_age: Mapped[str] = mapped_column(String(20), default="")
    patient_gender: Mapped[str] = mapped_column(String(10), default="")
    patient_mobile: Mapped[str] = mapped_column(String(20), default="")
    patient_address: Mapped[str] = mapped_column(Text, default="")
    guardian_name: Mapped[str] = mapped_column(String(200), default="")
    referring_doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("referring_doctors.id"))
    referring_doctor_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(12), default="confirmed")  # confirmed | on_hold | cancelled
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_type: Mapped[str] = mapped_column(String(8), default="none")  # none | percent | amount
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    due: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str] = mapped_column(Text, default="")
    cancel_reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)
    # Made while the internet was down (on the desk computer) and sent later: its provisional number and when.
    offline_no: Mapped[str] = mapped_column(String(40), default="")
    made_offline_at: Mapped[datetime | None] = mapped_column(Timestamp)

    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice", order_by="InvoiceItem.position", lazy="selectin")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", order_by="Payment.received_at", lazy="selectin")


class InvoiceItem(Base):
    """One test on a bill, with its own progress: billed, scanned, reported, delivered (or cancelled)."""
    __tablename__ = "invoice_items"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    test_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tests.id"))
    test_name: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    department_name: Mapped[str] = mapped_column(String(100), default="")
    is_imaging: Mapped[bool] = mapped_column(Boolean, default=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(12), default="billed")
    accession_no: Mapped[str] = mapped_column(String(32), default="")
    status_changed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    legacy_id: Mapped[int | None] = mapped_column(Integer)
    legacy_report: Mapped[dict | None] = mapped_column(JSONB)  # the old app's typed report, until phase 4

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Payment(Base):
    """Money received for a bill (kind=payment) or given back (kind=refund). Never edited or deleted."""
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(8), default="payment")  # payment | refund
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    mode: Mapped[str] = mapped_column(String(10))  # cash | upi | card | bank | other
    reference: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(String(300), default="")
    received_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    received_on: Mapped[date] = mapped_column(Date)  # the centre's local date, for daily collection
    received_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    received_by_name: Mapped[str] = mapped_column(String(200), default="")
    legacy_id: Mapped[int | None] = mapped_column(Integer)

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


# ---------- phase 4: test reports and images ------------------------------------------------------------

class TestReport(Base):
    """The written report for one test on a bill: draft, final, signed, or amended after signing."""
    __tablename__ = "test_reports"
    __test__ = False  # not a pytest test class
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    invoice_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoice_items.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | final | signed | amended
    title: Mapped[str] = mapped_column(String(200), default="")
    technique: Mapped[str] = mapped_column(String(500), default="")
    modality: Mapped[str] = mapped_column(String(40), default="")
    findings: Mapped[str] = mapped_column(Text, default="")    # sanitised HTML
    impression: Mapped[str] = mapped_column(Text, default="")  # sanitised HTML
    reported_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reported_by_name: Mapped[str] = mapped_column(String(200), default="")
    signed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    signed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    signer_name: Mapped[str] = mapped_column(String(200), default="")
    signer_degree: Mapped[str] = mapped_column(String(200), default="")
    signer_registration_no: Mapped[str] = mapped_column(String(60), default="")
    signature_data: Mapped[str] = mapped_column(Text, default="")
    signature_mime: Mapped[str] = mapped_column(String(40), default="")
    amend_reason: Mapped[str] = mapped_column(Text, default="")
    amendments: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[bool] = mapped_column(Boolean, default=False)
    # An uploaded PDF report (base64), instead of or as well as the typed findings. Loaded only when asked for.
    attachment_name: Mapped[str] = mapped_column(String(200), default="")
    attachment_pages: Mapped[int] = mapped_column(Integer, default=0)
    attachment_size: Mapped[int] = mapped_column(Integer, default=0)
    attachment_data: Mapped[str] = mapped_column(Text, default="", deferred=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class Upload(Base):
    """A file being sent in pieces (resumable): base64 of what has arrived so far. Removed once used, or after a day."""
    __tablename__ = "uploads"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    received: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[str] = mapped_column(Text, default="", deferred=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


class TestReportVersion(Base):
    """Every saved state of a report, in order. Never edited or removed."""
    __tablename__ = "test_report_versions"
    __test__ = False
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_reports.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(12))  # created | saved | finalised | signed | amended | imported
    status: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200), default="")
    technique: Mapped[str] = mapped_column(String(500), default="")
    modality: Mapped[str] = mapped_column(String(40), default="")
    findings: Mapped[str] = mapped_column(Text, default="")
    impression: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    attachment_name: Mapped[str] = mapped_column(String(200), default="")
    saved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    saved_by_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


class ReportTemplate(Base):
    """Ready-made wording for a report, for one test or for any."""
    __tablename__ = "report_templates"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    test_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tests.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200), default="")
    technique: Mapped[str] = mapped_column(String(500), default="")
    findings: Mapped[str] = mapped_column(Text, default="")
    impression: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class DoctorSignature(Base):
    """How a doctor signs reports: name, degree, registration number and a picture of the signature (base64 PNG)."""
    __tablename__ = "doctor_signatures"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(200))
    degree: Mapped[str] = mapped_column(String(200), default="")
    registration_no: Mapped[str] = mapped_column(String(60), default="")
    signature_data: Mapped[str] = mapped_column(Text, default="")
    signature_mime: Mapped[str] = mapped_column(String(40), default="")
    signature_version: Mapped[str] = mapped_column(String(20), default="")
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class ImagingStudy(Base):
    """A DICOM study kept on the image server (Orthanc), belonging to one test on a bill."""
    __tablename__ = "imaging_studies"
    __table_args__ = (UniqueConstraint("tenant_id", "study_instance_uid", name="uq_imaging_studies_uid"),)
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    invoice_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoice_items.id", ondelete="CASCADE"))
    study_instance_uid: Mapped[str] = mapped_column(String(128))
    orthanc_study_id: Mapped[str] = mapped_column(String(64))
    modality: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    series_count: Mapped[int] = mapped_column(Integer, default=0)
    instance_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_by_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class MessageDelivery(Base):
    """A report sent to a patient (WhatsApp now), with what the provider says happened to it."""
    __tablename__ = "message_deliveries"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_reports.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(12), default="whatsapp")
    to: Mapped[str] = mapped_column(String(20))  # E.164
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | delivered | read | failed
    provider: Mapped[str] = mapped_column(String(20), default="")
    provider_message_id: Mapped[str] = mapped_column(String(128), default="")
    error: Mapped[str] = mapped_column(String(500), default="")
    report_version: Mapped[int] = mapped_column(Integer, default=1)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sent_by_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(Timestamp)
    delivered_at: Mapped[datetime | None] = mapped_column(Timestamp)
    read_at: Mapped[datetime | None] = mapped_column(Timestamp)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class InvoiceShare(Base):
    """A link to a bill for the patient (the QR code on it). Only the token's SHA-256 is stored."""
    __tablename__ = "invoice_shares"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    views: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    failed_checks: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(Timestamp)


class ReportShare(Base):
    """A link to a signed report for the patient (the QR code on it). Only the token's SHA-256 is stored."""
    __tablename__ = "report_shares"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_reports.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    views: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    failed_checks: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(Timestamp)


# ---------- integrations: API keys for other systems (medical data only, never financial) ----------------

class ApiKey(Base):
    """A key another system uses to read the centre's medical data at /api/v1. The key itself is shown once;
    only its SHA-256 is stored. `prefix` (sdms_live_ + 8 characters) identifies it in lists and logs."""
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(32))
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list)
    allowed_ips: Mapped[list] = mapped_column(ARRAY(CIDR), default=list)  # empty = from anywhere
    expires_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(Timestamp)
    last_used_ip: Mapped[str | None] = mapped_column(INET)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)  # may be in the future: a rolled key's grace period
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_by_name: Mapped[str] = mapped_column(String(200), default="")
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))


class ApiRequest(Base):
    """One call to /api/v1: which key, what, the answer's status and how long it took. Never the bodies."""
    __tablename__ = "api_requests"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    key_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(300))
    status: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    ip_address: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


# ---------- background jobs and notifications (app/core/jobs.py, app/worker.py, app/services/notifications.py) ----

from sqlalchemy.types import LargeBinary  # noqa: E402


class Job(Base):
    """Work done in the background by `python -m app.worker`. tenant_id NULL = platform work (e.g. cleanup)."""
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | running | done | failed | cancelled
    priority: Mapped[int] = mapped_column(Integer, default=0)          # higher runs first
    run_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str] = mapped_column(Text, default="")
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    result: Mapped[dict | None] = mapped_column(JSONB)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)


class JobFile(Base):
    """A file a job produced (an export), kept for a day and downloaded at GET /api/jobs/{job_id}/file."""
    __tablename__ = "job_files"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)


class JobSchedule(Base):
    """When each recurring job (app/worker.py SCHEDULES) runs next. Platform only."""
    __tablename__ = "job_schedules"
    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    next_run_at: Mapped[datetime] = mapped_column(Timestamp)
    last_run_at: Mapped[datetime | None] = mapped_column(Timestamp)


class JobWorker(Base):
    """A running worker process and its heartbeat. Platform only."""
    __tablename__ = "job_workers"
    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(200), default="")
    pid: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    jobs_done: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="running")


class Notification(Base):
    """A message for one person in the app (the bell), and as a browser pop-up if they allow it."""
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(500), default="")
    severity: Mapped[str] = mapped_column(String(10), default="info")  # info | success | warning | danger
    read_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)


class NotificationPreference(Base):
    """What one person wants to hear about: kinds they've turned off, and browser pop-ups on or off."""
    __tablename__ = "notification_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    muted_kinds: Mapped[list] = mapped_column(JSONB, default=list)
    browser_popups: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class BackupSettings(Base):
    """When the whole database is copied (one row): set in Settings > Backups, carried out by the server's cron
    (deploy/backup.sh). Platform only."""
    __tablename__ = "backup_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    every_days: Mapped[int] = mapped_column(Integer, default=1)
    at_time: Mapped[str] = mapped_column(String(5), default="23:00")     # HH:MM, India time
    keep_days: Mapped[int] = mapped_column(Integer, default=30)
    next_run_at: Mapped[datetime | None] = mapped_column(Timestamp)
    requested_at: Mapped[datetime | None] = mapped_column(Timestamp)    # "Back up now", until the server picks it up
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class ClientBackupSettings(Base):
    """When a client's own data is copied (one row per client), set by the centre's owner in Settings > Backups."""
    __tablename__ = "client_backup_settings"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    every_days: Mapped[int] = mapped_column(Integer, default=1)
    at_time: Mapped[str] = mapped_column(String(5), default="23:30")     # HH:MM, India time
    keep_days: Mapped[int] = mapped_column(Integer, default=30)          # 0: forever
    next_run_at: Mapped[datetime | None] = mapped_column(Timestamp)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow)


class ClientBackup(Base):
    """One copy of a client's data (or one restore of a copy): when, why, how it went, and what it held."""
    __tablename__ = "client_backups"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(10))                     # scheduled | manual | restore
    status: Mapped[str] = mapped_column(String(10), default="running")   # running | ok | failed
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_by_name: Mapped[str] = mapped_column(String(200), default="")
    source_id: Mapped[uuid.UUID | None] = mapped_column(Id)              # a restore: the copy it put back
    scheduled_for: Mapped[datetime | None] = mapped_column(Timestamp)
    started_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)
    file: Mapped[str] = mapped_column(String(200), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    schema_version: Mapped[str] = mapped_column(String(64), default="")
    counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    message: Mapped[str] = mapped_column(String(500), default="")


class BackupRun(Base):
    """One backup: when, why (scheduled or asked for), and how it went. Platform only."""
    __tablename__ = "backup_runs"
    id: Mapped[uuid.UUID] = mapped_column(Id, primary_key=True, default=new_id)
    trigger: Mapped[str] = mapped_column(String(10))                    # scheduled | manual
    scheduled_for: Mapped[datetime | None] = mapped_column(Timestamp)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(Timestamp)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running | ok | failed
    file: Mapped[str] = mapped_column(String(200), default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    message: Mapped[str] = mapped_column(String(500), default="")
