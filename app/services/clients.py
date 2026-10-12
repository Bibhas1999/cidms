"""Platform work: clients (tenants), their plans and status. Runs in a platform-scoped database session."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, Invalid, NotFound
from app.core.passwords import check_strength, hash_password
from app.core.security import CurrentUser
from app.core.tenancy import forget_tenant
from app.models import Plan, Tenant, TenantSettings, User, UserSession, utcnow
from app.repositories.common import contains
from app.repositories.users import RoleRepository, UserRepository
from app.schemas import ClientCreateIn, ClientUpdateIn
from app.services.audit import AuditService

RESERVED_SLUGS = {"admin", "api", "www", "app", "mail", "static", "support", "help", "status"}


class ClientService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.audit = AuditService(db)

    def page(self, search: str, status: str | None, page: int, size: int) -> tuple[list[Tenant], int]:
        q = select(Tenant)
        if search:
            like = contains(search)
            q = q.where(or_(func.lower(Tenant.name).like(like, escape="\\"), Tenant.slug.like(like, escape="\\")))
        if status:
            q = q.where(Tenant.status == status)
        total = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = self.db.scalars(q.order_by(Tenant.name).offset((page - 1) * size).limit(size)).unique().all()
        return list(rows), total

    def plans(self) -> list[Plan]:
        return list(self.db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_monthly)))

    def _plan(self, plan_id: uuid.UUID | None) -> Plan | None:
        if plan_id is None:
            return None
        plan = self.db.get(Plan, plan_id)
        if plan is None or not plan.is_active:
            raise Invalid("Choose a plan from the list.", "plan_id")
        return plan

    def create(self, data: ClientCreateIn) -> Tenant:
        if data.slug in RESERVED_SLUGS:
            raise Invalid("That address is reserved. Choose another.", "slug")
        if self.db.scalar(select(Tenant.id).where(Tenant.slug == data.slug)):
            raise Conflict("Another client already uses that address.", "slug")
        plan = self._plan(data.plan_id)
        check_strength(data.owner_temporary_password, "owner_temporary_password")
        tenant = Tenant(slug=data.slug, name=data.name.strip(), kind=data.kind, plan_id=plan.id if plan else None)
        self.db.add(tenant)
        self.db.flush()
        self.db.add(TenantSettings(tenant_id=tenant.id, legal_name=tenant.name,
                                   invoice_prefix="".join(w[0] for w in tenant.name.split()[:3]).upper() or "INV"))
        owner = User(tenant_id=tenant.id, email=data.owner_email.strip().lower(), full_name=data.owner_name.strip(),
                     password_hash=hash_password(data.owner_temporary_password), must_change_password=True)
        self.db.add(owner)
        self.db.flush()
        owner_role = RoleRepository(self.db).by_code("client", "owner")
        UserRepository(self.db).set_roles(owner, [owner_role])
        self.audit.record(tenant.id, self.current.id, "client.created", "tenant", tenant.id,
                          {"slug": tenant.slug, "owner_email": owner.email})
        self.audit.record(None, self.current.id, "client.created", "tenant", tenant.id, {"slug": tenant.slug})
        return tenant

    def update(self, tenant_id: uuid.UUID, data: ClientUpdateIn) -> Tenant:
        tenant = self.db.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFound("We couldn't find that client.")
        changes: dict = {}
        for field in ("name", "kind", "status"):
            value = getattr(data, field)
            if value is not None and value != getattr(tenant, field):
                changes[field] = [getattr(tenant, field), value]
                setattr(tenant, field, value)
        if "plan_id" in data.model_fields_set and data.plan_id != tenant.plan_id:
            self._plan(data.plan_id)
            changes["plan_id"] = [str(tenant.plan_id) if tenant.plan_id else None, str(data.plan_id) if data.plan_id else None]
            tenant.plan_id = data.plan_id
        if changes.get("status", [None, None])[1] == "suspended":
            # Sign everyone in the client out at once.
            for sess in self.db.scalars(select(UserSession).where(UserSession.tenant_id == tenant.id, UserSession.revoked_at.is_(None))):
                sess.revoked_at = utcnow()
        if changes:
            self.audit.record(None, self.current.id, "client.updated", "tenant", tenant.id, changes)
            self.audit.record(tenant.id, self.current.id, "client.updated", "tenant", tenant.id, changes)
            forget_tenant(tenant.slug)
        self.db.flush()
        self.db.refresh(tenant)
        return tenant


def platform_overview(db: Session) -> dict:
    """The platform's home page: centres, their people and use this month, and renewals coming up. Counts only:
    a centre's money is its own business (the platform sees plan values, not what centres bill)."""
    from datetime import timedelta

    from app.core.money import local_today
    from app.models import Invoice

    now = utcnow()
    month_start = local_today().replace(day=1)
    tenants = list(db.scalars(select(Tenant).where(Tenant.kind != "platform").order_by(Tenant.created_at.desc())))
    active = [t for t in tenants if t.status == "active"]
    staff = dict(db.execute(select(User.tenant_id, func.count()).where(User.tenant_id.is_not(None), User.is_active.is_(True))
                            .group_by(User.tenant_id)).all())
    platform_staff = db.scalar(select(func.count()).select_from(User).where(User.tenant_id.is_(None), User.is_active.is_(True))) or 0
    bills = dict(db.execute(select(Invoice.tenant_id, func.count()).where(Invoice.bill_date >= month_start, Invoice.status != "cancelled")
                            .group_by(Invoice.tenant_id)).all())

    def row(t: Tenant) -> dict:
        limit = t.plan.max_bills_per_month if t.plan else None
        used = bills.get(t.id, 0)
        return {"id": t.id, "slug": t.slug, "name": t.name, "kind": t.kind, "status": t.status,
                "plan": t.plan.name if t.plan else None, "paid_until": t.paid_until, "created_at": t.created_at,
                "staff": staff.get(t.id, 0), "bills_this_month": used, "bill_limit": limit,
                "usage_pct": round(used * 100 / limit) if limit else None}

    soon = now + timedelta(days=30)
    renewals = sorted((row(t) for t in active if t.paid_until is None or t.paid_until <= soon),
                      key=lambda r: (r["paid_until"] is not None, r["paid_until"] or now))
    return {
        "centres": len(tenants), "active": len(active), "suspended": sum(t.status == "suspended" for t in tenants),
        "by_kind": {k: sum(t.kind == k for t in tenants) for k in ("diagnostic", "opd", "clinic")},
        "staff": sum(staff.values()), "platform_staff": platform_staff,
        "bills_this_month": sum(bills.values()),
        "plan_value_monthly": sum((t.plan.price_monthly for t in active if t.plan), start=0),
        "renewals": renewals[:8],
        "overdue": sum(1 for r in renewals if r["paid_until"] is not None and r["paid_until"] < now),
        "centres_list": [row(t) for t in tenants[:10]],
    }
