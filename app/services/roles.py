"""Roles and permissions: built-in roles (shared, read-only, kept in step with app/catalog.py by app.seed) and a
centre's own roles, which it can create, change, copy and delete.

Rules, all checked here (the screen only mirrors them):
- Built-in roles can't be changed or deleted; they can be copied into a centre's own role.
- Nobody can give a role a permission they don't hold themselves, and a centre's roles never carry platform
  permissions. A role that can do things you can't is read-only for you.
- Nobody can change or delete a role in a way that takes away their own access to roles & permissions.
- A role that people have can't be deleted until they're moved to another role (the delete can do that move).
- Permissions are read from the database on every request (app.core.security.load_permissions); there is no
  cache, so a change applies to everyone affected on their very next request.
- Every change is written to the activity log with the permissions added and removed.
"""

import re
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.catalog import CLIENT_PERMISSIONS, OWNER_ONLY_ROLES, PLATFORM_PERMISSIONS, ROLES
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.core.security import CurrentUser
from app.models import Role, RolePermission, User, UserRole, utcnow
from app.permission_groups import grouped, label_of
from app.schemas_roles import RoleIn
from app.services.audit import AuditService

BUILTIN_LOCK = "Built-in roles can't be changed — copy one to customise."
MANAGE = "roles.manage"


def permission_diff(before: set[str], after: set[str]) -> dict:
    return {"added": sorted(after - before), "removed": sorted(before - after)}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (s or "role")[:32]


class RoleService:
    def __init__(self, db: Session, current: CurrentUser):
        self.db = db
        self.current = current
        self.tenant_id = current.user.tenant_id
        self.scope = "platform" if self.tenant_id is None else "client"
        self.audit = AuditService(db)

    # ---------- reading ----------

    def _tenant_filter(self, column):
        return column.is_(None) if self.tenant_id is None else column == self.tenant_id

    def _visible(self):
        """Roles this workspace may use: the built-in ones of its scope, and (for a centre) its own."""
        q = select(Role).where(Role.scope == self.scope)
        if self.tenant_id is None:
            return q.where(Role.tenant_id.is_(None))
        return q.where((Role.tenant_id.is_(None)) | (Role.tenant_id == self.tenant_id))

    def _get(self, role_id: uuid.UUID) -> Role:
        role = self.db.scalar(self._visible().where(Role.id == role_id))
        if role is None:
            raise NotFound("We couldn't find that role.")
        return role

    def permissions_of(self, role_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
        out: dict[uuid.UUID, set[str]] = {rid: set() for rid in role_ids}
        if role_ids:
            for rid, code in self.db.execute(select(RolePermission.role_id, RolePermission.permission_code)
                                             .where(RolePermission.role_id.in_(role_ids))):
                out[rid].add(code)
        return out

    def _member_counts(self) -> dict[uuid.UUID, int]:
        rows = self.db.execute(
            select(UserRole.role_id, func.count()).join(User, User.id == UserRole.user_id)
            .where(self._tenant_filter(User.tenant_id), User.is_active.is_(True)).group_by(UserRole.role_id))
        return dict(rows.all())

    def _all_member_ids(self, role_id: uuid.UUID) -> list[uuid.UUID]:
        """Everyone with the role here, active or not (a deactivated person keeps their roles)."""
        return list(self.db.scalars(select(UserRole.user_id).join(User, User.id == UserRole.user_id)
                                    .where(UserRole.role_id == role_id, self._tenant_filter(User.tenant_id))))

    def _is_owner(self) -> bool:
        return any(r.code in OWNER_ONLY_ROLES and r.tenant_id is None for r in self.current.user.roles)

    def assignable(self, role: Role, perms: set[str]) -> bool:
        if role.tenant_id is None and role.code in OWNER_ONLY_ROLES and not self._is_owner():
            return False
        return perms <= self.current.permissions

    def lock_reason(self, role: Role, perms: set[str]) -> str:
        if role.tenant_id is None:
            return BUILTIN_LOCK
        if self.scope != "client" or not self.current.can(MANAGE):
            return "You don't have permission to change roles."
        if not perms <= self.current.permissions:
            return "This role can do things you can't, so you can't change it."
        return ""

    def describe(self, role: Role, perms: set[str], members: int) -> dict:
        reason = self.lock_reason(role, perms)
        creator = self.db.get(User, role.created_by_id) if role.created_by_id else None
        return {
            "id": role.id, "code": role.code, "name": role.name, "description": role.description, "scope": role.scope,
            "is_builtin": role.tenant_id is None, "permissions": sorted(perms), "member_count": members,
            "editable": not reason, "assignable": self.assignable(role, perms), "locked_reason": reason,
            "created_by_name": creator.full_name if creator else "", "created_at": role.created_at if role.tenant_id else None,
            "updated_at": role.updated_at if role.tenant_id else None,
        }

    def all_roles(self) -> list[dict]:
        roles = list(self.db.scalars(self._visible()))
        # Built-in roles first in the catalog's order, then the centre's own by name.
        order = {code: i for i, code in enumerate(ROLES)}
        roles.sort(key=lambda r: (r.tenant_id is not None, order.get(r.code, 999) if r.tenant_id is None else 0, r.name.lower()))
        perms = self.permissions_of([r.id for r in roles])
        counts = self._member_counts()
        return [self.describe(r, perms[r.id], counts.get(r.id, 0)) for r in roles]

    def detail(self, role_id: uuid.UUID) -> dict:
        role = self._get(role_id)
        return self.describe(role, self.permissions_of([role.id])[role.id], self._member_counts().get(role.id, 0))

    def members(self, role_id: uuid.UUID) -> list[User]:
        role = self._get(role_id)
        return list(self.db.scalars(select(User).join(UserRole, UserRole.user_id == User.id)
                                    .where(UserRole.role_id == role.id, self._tenant_filter(User.tenant_id))
                                    .order_by(User.is_active.desc(), User.full_name)))

    def catalog(self) -> list[dict]:
        groups = grouped(self.scope)
        for g in groups:
            for p in g["permissions"]:
                p["held"] = p["code"] in self.current.permissions
        return groups

    # ---------- rules ----------

    def _require_manage(self) -> None:
        if self.scope != "client":
            raise NotFound("Not available in the platform workspace.")
        if not self.current.can(MANAGE):
            raise Forbidden("You don't have permission to do that.")

    def _editable(self, role: Role) -> set[str]:
        perms = self.permissions_of([role.id])[role.id]
        reason = self.lock_reason(role, perms)
        if reason:
            raise Forbidden(reason)
        return perms

    def _check_permissions(self, before: set[str], after: set[str]) -> None:
        platform = sorted(p for p in after if p in PLATFORM_PERMISSIONS)
        if platform:
            raise Invalid("A centre's roles can't include platform permissions.", "permissions")
        unknown = sorted(p for p in after if p not in CLIENT_PERMISSIONS)
        if unknown:
            raise Invalid(f"Unknown permission: {', '.join(unknown)}.", "permissions")
        not_held = sorted((after - before) - self.current.permissions)
        if not_held:
            names = ", ".join(label_of(p) for p in not_held)
            raise Forbidden(f"You can't give a permission you don't have yourself: {names}.")

    def _keeps_my_access(self, role: Role, perms_after: set[str] | None, extra: set[str] = frozenset()) -> None:
        """Refuse a change that leaves the person making it unable to manage roles.
        perms_after None means the role goes away (deleted); extra is what they'd get instead (a reassignment)."""
        mine = list(self.current.user.roles)
        if not any(r.id == role.id for r in mine):
            return
        others = self.permissions_of([r.id for r in mine if r.id != role.id])
        remaining = set().union(*others.values()) | (perms_after or set()) | set(extra)
        if MANAGE not in remaining:
            raise Conflict("That would take away your own access to roles & permissions. "
                           "Ask another owner or admin to make this change.")

    def _unique_name(self, name: str, exclude: uuid.UUID | None = None) -> None:
        q = self._visible().where(func.lower(Role.name) == name.lower())
        if exclude:
            q = q.where(Role.id != exclude)
        if self.db.scalar(q) is not None:
            raise Conflict("There's already a role with that name.", "name")

    def _new_code(self, name: str) -> str:
        base = _slug(name)
        taken = set(ROLES) | set(self.db.scalars(select(Role.code).where(Role.tenant_id == self.tenant_id)))
        code, n = base, 2
        while code in taken:
            code = f"{base}_{n}"
            n += 1
        return code

    def _set_permissions(self, role: Role, perms: set[str]) -> None:
        self.db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        self.db.add_all(RolePermission(role_id=role.id, permission_code=p) for p in sorted(perms))
        self.db.flush()

    # ---------- changes ----------

    def create(self, data: RoleIn, copied_from: Role | None = None) -> Role:
        self._require_manage()
        perms = set(data.permissions)
        self._check_permissions(set(), perms)
        self._unique_name(data.name)
        role = Role(tenant_id=self.tenant_id, code=self._new_code(data.name), name=data.name, scope="client",
                    description=data.description, created_by_id=self.current.id)
        self.db.add(role)
        self.db.flush()
        self._set_permissions(role, perms)
        self.audit.record(self.tenant_id, self.current.id, "role.created", "role", role.id,
                          {"name": role.name, "code": role.code, "permissions": sorted(perms),
                           "permission_changes": permission_diff(set(), perms),
                           **({"copied_from": copied_from.name} if copied_from else {})})
        return role

    def copy(self, role_id: uuid.UUID, name: str | None) -> Role:
        self._require_manage()
        source = self._get(role_id)
        perms = self.permissions_of([source.id])[source.id]
        not_held = sorted(perms - self.current.permissions)
        if not_held:
            raise Forbidden(f"This role can do things you can't ({', '.join(label_of(p) for p in not_held)}), so you can't copy it.")
        new_name = " ".join((name or "").split())
        if not new_name:
            new_name, n = f"Copy of {source.name}", 2
            while self.db.scalar(self._visible().where(func.lower(Role.name) == new_name.lower())) is not None:
                new_name, n = f"Copy of {source.name} ({n})", n + 1
        return self.create(RoleIn(name=new_name[:100], description=source.description, permissions=sorted(perms)), copied_from=source)

    def update(self, role_id: uuid.UUID, data: RoleIn) -> Role:
        self._require_manage()
        role = self._get(role_id)
        before = self._editable(role)
        after = set(data.permissions)
        self._check_permissions(before, after)
        self._unique_name(data.name, exclude=role.id)
        self._keeps_my_access(role, after)
        changes: dict = {}
        if data.name != role.name:
            changes["name"] = [role.name, data.name]
            role.name = data.name
        if data.description != role.description:
            changes["description"] = [role.description, data.description]
            role.description = data.description
        if after != before:
            self._set_permissions(role, after)
            changes["permission_changes"] = permission_diff(before, after)
            changes["permissions"] = [sorted(before), sorted(after)]
            role.updated_at = utcnow()
        if changes:
            self.db.flush()
            self.audit.record(self.tenant_id, self.current.id, "role.updated", "role", role.id, {"role": role.name, **changes})
        return role

    def delete(self, role_id: uuid.UUID, reassign_to: uuid.UUID | None) -> int:
        """Delete a centre's role. People who have it are moved to `reassign_to` first; without it, a role in use
        is refused. Returns how many people were moved."""
        self._require_manage()
        role = self._get(role_id)
        perms = self._editable(role)
        member_ids = self._all_member_ids(role.id)
        target: Role | None = None
        if member_ids:
            if reassign_to is None:
                n = len(member_ids)
                raise Conflict(f"{n} {'person has' if n == 1 else 'people have'} this role. "
                               "Move them to another role first, then delete it.", "reassign_to")
            if reassign_to == role.id:
                raise Invalid("Choose a different role to move people to.", "reassign_to")
            target = self._get(reassign_to)
            target_perms = self.permissions_of([target.id])[target.id]
            if not self.assignable(target, target_perms):
                raise Forbidden("You can't give people that role.")
            self._keeps_my_access(role, None, target_perms if self.current.id in member_ids else set())
            have = set(self.db.scalars(select(UserRole.user_id).where(UserRole.role_id == target.id,
                                                                       UserRole.user_id.in_(member_ids))))
            for uid in member_ids:
                if uid not in have:
                    self.db.add(UserRole(user_id=uid, role_id=target.id, tenant_id=self.tenant_id))
        else:
            self._keeps_my_access(role, None)
        details = {"name": role.name, "code": role.code, "permissions": sorted(perms),
                   "permission_changes": permission_diff(perms, set())}
        if target is not None:
            details["reassigned_to"] = target.name
            details["reassigned_user_ids"] = [str(u) for u in member_ids]
        self.db.flush()
        self.db.execute(delete(UserRole).where(UserRole.role_id == role.id))
        self.db.delete(role)
        self.db.flush()
        for u in self.current.user.roles:
            if u.id == role.id:
                self.db.expire(self.current.user, ["roles"])
                break
        self.audit.record(self.tenant_id, self.current.id, "role.deleted", "role", role_id, details)
        return len(member_ids)
