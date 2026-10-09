"""Staff: a client's people (or the platform's own staff, for platform work)."""

import uuid

from sqlalchemy.orm import Session

from app.catalog import OWNER_ONLY_ROLES
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.passwords import check_strength, hash_password
from app.core.security import CurrentUser, revoke_user_sessions
from app.models import Tenant, User
from app.repositories.users import RoleRepository, UserRepository
from app.schemas import StaffCreateIn, StaffUpdateIn
from app.services.audit import AuditService


class StaffService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.scope = "platform" if self.tenant_id is None else "client"
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.audit = AuditService(db)

    def _get(self, user_id: uuid.UUID) -> User:
        user = self.users.get(self.tenant_id, user_id)
        if user is None:
            raise NotFound("We couldn't find that person.")
        return user

    def _is_owner(self, user: User) -> bool:
        return any(r.code in OWNER_ONLY_ROLES for r in user.roles)

    def _resolve_roles(self, role_ids: list[uuid.UUID]):
        roles = self.roles.by_ids(self.scope, role_ids)
        if len(roles) != len(set(role_ids)):
            raise Invalid("Choose roles from the list.", "role_ids")
        if any(r.code in OWNER_ONLY_ROLES for r in roles) and not self._is_owner(self.current.user):
            raise Forbidden("Only an owner can make someone an owner.")
        return roles

    def _check_user_limit(self) -> None:
        if self.tenant_id is None:
            return
        tenant = self.db.get(Tenant, self.tenant_id)
        if tenant and tenant.plan and self.users.count_active(self.tenant_id) >= tenant.plan.max_users:
            raise Conflict(f"Your plan allows {tenant.plan.max_users} active staff. Deactivate someone or ask us to change your plan.")

    def page(self, search: str, active: bool | None, page: int, size: int):
        return self.users.page(self.tenant_id, search, active, page, size)

    def create(self, data: StaffCreateIn) -> User:
        email = data.email.strip().lower()
        if self.users.by_email(self.tenant_id, email):
            raise Conflict("Someone here already uses that email.", "email")
        roles = self._resolve_roles(data.role_ids)
        check_strength(data.temporary_password, "temporary_password")
        self._check_user_limit()
        user = User(tenant_id=self.tenant_id, email=email, full_name=data.full_name.strip(), mobile=data.mobile,
                    password_hash=hash_password(data.temporary_password), must_change_password=True)
        self.db.add(user)
        self.db.flush()
        self.users.set_roles(user, roles)
        self.audit.record(self.tenant_id, self.current.id, "staff.created", "user", user.id,
                          {"email": email, "roles": [r.code for r in roles]})
        return user

    def update(self, user_id: uuid.UUID, data: StaffUpdateIn) -> User:
        user = self._get(user_id)
        changes: dict = {}
        was_owner = self._is_owner(user)
        if data.full_name is not None and data.full_name.strip() != user.full_name:
            changes["full_name"] = [user.full_name, data.full_name.strip()]
            user.full_name = data.full_name.strip()
        if data.mobile is not None and data.mobile != user.mobile:
            changes["mobile"] = [user.mobile, data.mobile]
            user.mobile = data.mobile
        if data.role_ids is not None:
            roles = self._resolve_roles(data.role_ids)
            if was_owner and not self._is_owner(self.current.user):
                raise Forbidden("Only an owner can change another owner's roles.")
            new_codes = sorted(r.code for r in roles)
            old_codes = sorted(r.code for r in user.roles)
            if new_codes != old_codes:
                if was_owner and not any(r.code in OWNER_ONLY_ROLES for r in roles):
                    self._keep_an_owner(user)
                self.users.set_roles(user, roles)
                changes["roles"] = [old_codes, new_codes]
        if data.is_active is not None and data.is_active != user.is_active:
            if user.id == self.current.id:
                raise Invalid("You can't deactivate yourself.", "is_active")
            if not data.is_active:
                if was_owner:
                    self._keep_an_owner(user)
                revoke_user_sessions(self.db, user.id)
            else:
                self._check_user_limit()
            user.is_active = data.is_active
            changes["is_active"] = [not data.is_active, data.is_active]
        if changes:
            self.audit.record(self.tenant_id, self.current.id, "staff.updated", "user", user.id, changes)
        return user

    def reset_password(self, user_id: uuid.UUID, temporary_password: str) -> None:
        user = self._get(user_id)
        if self._is_owner(user) and not self._is_owner(self.current.user):
            raise Forbidden("Only an owner can reset an owner's password.")
        check_strength(temporary_password, "temporary_password")
        user.password_hash = hash_password(temporary_password)
        user.must_change_password = True
        user.failed_logins = 0
        user.locked_until = None
        revoke_user_sessions(self.db, user.id)
        self.audit.record(self.tenant_id, self.current.id, "staff.password_reset", "user", user.id)

    def _keep_an_owner(self, user: User) -> None:
        if self.tenant_id is not None and self.users.count_with_role(self.tenant_id, "owner", exclude=user.id) == 0:
            raise Conflict("Every centre needs at least one active owner. Make someone else an owner first.")
