"""Every query about people, roles and their sessions. Row-level security already limits these to the
current client; the explicit tenant filters below make the intent plain and keep platform work exact."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Role, User, UserRole
from app.repositories.common import contains


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def by_email(self, tenant_id: uuid.UUID | None, email: str) -> User | None:
        tenant_filter = User.tenant_id.is_(None) if tenant_id is None else User.tenant_id == tenant_id
        return self.db.scalar(select(User).where(tenant_filter, User.email == email.strip().lower()))

    def get(self, tenant_id: uuid.UUID | None, user_id: uuid.UUID) -> User | None:
        tenant_filter = User.tenant_id.is_(None) if tenant_id is None else User.tenant_id == tenant_id
        return self.db.scalar(select(User).where(tenant_filter, User.id == user_id))

    def page(self, tenant_id: uuid.UUID | None, search: str, active: bool | None, page: int, size: int) -> tuple[list[User], int]:
        tenant_filter = User.tenant_id.is_(None) if tenant_id is None else User.tenant_id == tenant_id
        q = select(User).where(tenant_filter)
        if search:
            like = contains(search)
            q = q.where(or_(func.lower(User.full_name).like(like, escape="\\"), User.email.like(like, escape="\\"),
                            User.mobile.like(like, escape="\\")))
        if active is not None:
            q = q.where(User.is_active.is_(active))
        total = self.db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = self.db.scalars(q.order_by(User.full_name).offset((page - 1) * size).limit(size)).all()
        return list(rows), total

    def count_active(self, tenant_id: uuid.UUID) -> int:
        return self.db.scalar(select(func.count()).where(User.tenant_id == tenant_id, User.is_active.is_(True))) or 0

    def count_with_role(self, tenant_id: uuid.UUID, role_code: str, exclude: uuid.UUID | None = None) -> int:
        q = (select(func.count()).select_from(User).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
             .where(User.tenant_id == tenant_id, User.is_active.is_(True), Role.code == role_code))
        if exclude:
            q = q.where(User.id != exclude)
        return self.db.scalar(q) or 0

    def set_roles(self, user: User, roles: list[Role]) -> None:
        self.db.query(UserRole).filter(UserRole.user_id == user.id).delete()
        for role in roles:
            self.db.add(UserRole(user_id=user.id, role_id=role.id, tenant_id=user.tenant_id))
        self.db.flush()
        self.db.expire(user, ["roles"])


class RoleRepository:
    def __init__(self, db: Session):
        self.db = db

    def for_scope(self, scope: str) -> list[Role]:
        return list(self.db.scalars(select(Role).where(Role.scope == scope).order_by(Role.name)))

    def by_ids(self, scope: str, ids: list[uuid.UUID]) -> list[Role]:
        return list(self.db.scalars(select(Role).where(Role.scope == scope, Role.id.in_(ids))))

    def by_code(self, scope: str, code: str) -> Role | None:
        return self.db.scalar(select(Role).where(Role.scope == scope, Role.code == code, Role.tenant_id.is_(None)))
