"""Roles and permissions: a centre's own roles, the rules around them, and assigning them to staff."""

from sqlalchemy import select

from app.catalog import CLIENT_PERMISSIONS
from app.core.db import scoped_session
from app.models import Role, RolePermission
from tests.conftest import browser, make_user


def _signed_in(tenant, email, roles):
    make_user(tenant, email, roles)
    c = browser(f"{tenant.slug}.localhost")
    assert c.login(email).status_code == 200
    return c


def _roles(c):
    return {r["code"]: r for r in c.get("/api/roles").json()}


def _make_role(c, name="Front desk lead", perms=("patients.manage", "billing.create"), description="Runs the counter"):
    r = c.post("/api/roles", json={"name": name, "description": description, "permissions": list(perms)})
    assert r.status_code == 201, r.text
    return r.json()


def _give_role(tenant, email, role_id):
    """A person holding just one custom role (made directly, as the API would)."""
    from app.models import UserRole
    u = make_user(tenant, email, [])
    with scoped_session(platform=True) as db, db.begin():
        db.add(UserRole(user_id=u.id, role_id=role_id, tenant_id=tenant.id))
    return u


def test_permission_catalog_is_grouped_and_marks_what_you_hold(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    groups = owner.get("/api/permissions").json()
    labels = [g["label"] for g in groups]
    assert "Front desk & billing" in labels and "Staff & settings" in labels and "Platform" not in labels
    codes = {p["code"] for g in groups for p in g["permissions"]}
    assert codes == set(CLIENT_PERMISSIONS)
    assert all(p["held"] and p["label"] and p["description"] for g in groups for p in g["permissions"])

    rec = _signed_in(alpha, "front@alpha.in", ["receptionist"])
    assert rec.get("/api/permissions").status_code == 403


def test_owner_and_admin_hold_roles_manage_others_do_not(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    roles = _roles(owner)
    assert "roles.manage" in roles["owner"]["permissions"] and "roles.manage" in roles["admin"]["permissions"]
    assert all("roles.manage" not in roles[c]["permissions"] for c in ("receptionist", "technician", "doctor", "accounts"))
    assert roles["owner"]["member_count"] == 1 and roles["owner"]["is_builtin"] and not roles["owner"]["editable"]
    assert "Built-in roles can't be changed" in roles["owner"]["locked_reason"]


def test_create_read_update_and_delete_a_custom_role(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    role = _make_role(owner)
    assert role["code"] == "front_desk_lead" and not role["is_builtin"] and role["editable"] and role["member_count"] == 0
    assert role["permissions"] == ["billing.create", "patients.manage"] and role["created_by_name"]
    assert owner.get(f"/api/roles/{role['id']}").json()["name"] == "Front desk lead"

    dup = owner.post("/api/roles", json={"name": "front desk LEAD", "permissions": []})
    assert dup.status_code == 409 and dup.json()["field"] == "name"
    assert owner.post("/api/roles", json={"name": "Receptionist", "permissions": []}).status_code == 409  # a built-in name
    assert owner.post("/api/roles", json={"name": " ", "permissions": []}).status_code == 422
    assert owner.post("/api/roles", json={"name": "Odd", "permissions": ["no.such"]}).status_code == 422

    r = owner.put(f"/api/roles/{role['id']}", json={"name": "Counter lead", "description": "",
                                                    "permissions": ["patients.manage", "payments.collect"]})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Counter lead" and r.json()["permissions"] == ["patients.manage", "payments.collect"]

    assert owner.delete(f"/api/roles/{role['id']}").status_code == 204
    assert owner.get(f"/api/roles/{role['id']}").status_code == 404


def test_a_custom_role_never_takes_a_built_in_code(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    role = _make_role(owner, name="Owner!", perms=["patients.manage"])
    assert role["code"] != "owner"
    tech = _give_role(alpha, "fake@alpha.in", role["id"])
    c = browser("alpha.localhost")
    c.login("fake@alpha.in")
    assert "staff.manage" not in c.get("/api/auth/me").json()["permissions"]
    # Someone with a custom role called "Owner" isn't an owner: the real owner still can't be the last removed.
    assert tech


def test_built_in_roles_are_read_only_but_can_be_copied(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    rec = _roles(owner)["receptionist"]
    assert owner.put(f"/api/roles/{rec['id']}", json={"name": "Receptionist", "permissions": []}).status_code == 403
    assert owner.delete(f"/api/roles/{rec['id']}").status_code == 403
    copy = owner.post(f"/api/roles/{rec['id']}/copy", json={})
    assert copy.status_code == 201, copy.text
    assert copy.json()["name"] == "Copy of Receptionist" and copy.json()["permissions"] == rec["permissions"]
    again = owner.post(f"/api/roles/{rec['id']}/copy", json={"name": "Evening receptionist"})
    assert again.json()["name"] == "Evening receptionist" and not again.json()["is_builtin"]
    assert owner.post(f"/api/roles/{rec['id']}/copy").json()["name"] == "Copy of Receptionist (2)"
    # The built-in role itself is unchanged.
    with scoped_session(platform=True) as db:
        perms = set(db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == rec["id"])))
    assert perms == set(rec["permissions"])


def test_nobody_grants_a_permission_they_do_not_hold(alpha):
    _signed_in(alpha, "owner@alpha.in", ["owner"])
    owner = browser("alpha.localhost")
    owner.login("owner@alpha.in")
    manager = _make_role(owner, name="Role manager", perms=["roles.manage", "staff.manage", "patients.manage"])
    _give_role(alpha, "mgr@alpha.in", manager["id"])
    mgr = browser("alpha.localhost")
    mgr.login("mgr@alpha.in")

    r = mgr.post("/api/roles", json={"name": "Sneaky", "permissions": ["patients.manage", "analytics.view"]})
    assert r.status_code == 403 and "don't have yourself" in r.json()["message"]
    assert mgr.post("/api/roles", json={"name": "Fine", "permissions": ["patients.manage"]}).status_code == 201
    # Platform permissions are never allowed in a centre's role, even for an owner.
    assert owner.post("/api/roles", json={"name": "Plat", "permissions": ["platform.clients.view"]}).status_code == 422
    # A role that can do more than you is read-only for you, and can't be copied or handed out by you.
    roles = _roles(mgr)
    assert roles["admin"]["assignable"] is False and roles["receptionist"]["assignable"] is False
    big = _make_role(owner, name="Big", perms=["patients.manage", "billing.create"])
    assert _roles(mgr)[big["code"]]["editable"] is False
    assert mgr.put(f"/api/roles/{big['id']}", json={"name": "Big", "permissions": []}).status_code == 403
    assert mgr.post(f"/api/roles/{roles['admin']['id']}/copy").status_code == 403
    tech = make_user(alpha, "tech@alpha.in", ["technician"])
    r = mgr.put(f"/api/staff/{tech.id}/roles", json={"role_ids": [roles["admin"]["id"]]})
    assert r.status_code == 403


def test_only_an_owner_assigns_the_owner_role(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    admin = _signed_in(alpha, "admin@alpha.in", ["admin"])
    tech = make_user(alpha, "tech@alpha.in", ["technician"])
    roles = _roles(admin)
    assert roles["owner"]["assignable"] is False
    r = admin.put(f"/api/staff/{tech.id}/roles", json={"role_ids": [roles["owner"]["id"]]})
    assert r.status_code == 403 and "owner" in r.json()["message"]

    owner = browser("alpha.localhost")
    owner.login("owner@alpha.in")
    r = owner.put(f"/api/staff/{tech.id}/roles", json={"role_ids": [roles["owner"]["id"]]})
    assert r.status_code == 200 and [x["code"] for x in r.json()["roles"]] == ["owner"]


def test_a_centre_always_keeps_an_active_owner(alpha):
    me = make_user(alpha, "owner@alpha.in", ["owner"])
    owner = browser("alpha.localhost")
    owner.login("owner@alpha.in")
    roles = _roles(owner)
    r = owner.put(f"/api/staff/{me.id}/roles", json={"role_ids": [roles["admin"]["id"]]})
    assert r.status_code == 409 and "owner" in r.json()["message"]
    other = make_user(alpha, "second@alpha.in", ["admin"])
    assert owner.put(f"/api/staff/{other.id}/roles", json={"role_ids": [roles["owner"]["id"]]}).status_code == 200
    assert owner.put(f"/api/staff/{me.id}/roles", json={"role_ids": [roles["admin"]["id"]]}).status_code == 200


def test_you_cannot_remove_your_own_access_to_roles(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    owner = browser("alpha.localhost")
    owner.login("owner@alpha.in")
    manager = _make_role(owner, name="Role manager", perms=["roles.manage", "staff.manage"])
    me = _give_role(alpha, "mgr@alpha.in", manager["id"])
    mgr = browser("alpha.localhost")
    mgr.login("mgr@alpha.in")
    r = mgr.put(f"/api/roles/{manager['id']}", json={"name": "Role manager", "permissions": ["staff.manage"]})
    assert r.status_code == 409 and "your own access" in r.json()["message"]
    tech = _roles(mgr)["technician"]
    assert mgr.put(f"/api/staff/{me.id}/roles", json={"role_ids": [tech["id"]]}).status_code in (403, 409)
    r = mgr.delete(f"/api/roles/{manager['id']}", params={"reassign_to": tech["id"]})
    assert r.status_code in (403, 409)
    # The owner can make the same change for them.
    assert owner.put(f"/api/roles/{manager['id']}", json={"name": "Role manager", "permissions": ["staff.manage"]}).status_code == 200


def test_deleting_a_role_in_use_is_refused_unless_people_are_moved(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    role = _make_role(owner)
    u1 = _give_role(alpha, "a@alpha.in", role["id"])
    _give_role(alpha, "b@alpha.in", role["id"])
    assert _roles(owner)[role["code"]]["member_count"] == 2
    members = owner.get(f"/api/roles/{role['id']}/members").json()
    assert sorted(m["email"] for m in members) == ["a@alpha.in", "b@alpha.in"]

    r = owner.delete(f"/api/roles/{role['id']}")
    assert r.status_code == 409 and "2 people have this role" in r.json()["message"]
    rec = _roles(owner)["receptionist"]
    assert owner.delete(f"/api/roles/{role['id']}", params={"reassign_to": role["id"]}).status_code == 422
    assert owner.delete(f"/api/roles/{role['id']}", params={"reassign_to": rec["id"]}).status_code == 204
    staff = {s["email"]: s for s in owner.get("/api/staff").json()["items"]}
    assert [x["code"] for x in staff["a@alpha.in"]["roles"]] == ["receptionist"]
    assert u1


def test_custom_roles_are_private_to_their_centre(alpha, beta):
    a = _signed_in(alpha, "owner@alpha.in", ["owner"])
    b = _signed_in(beta, "owner@beta.in", ["owner"])
    role = _make_role(a, name="Alpha only")
    assert "alpha_only" not in _roles(b)
    assert b.get(f"/api/roles/{role['id']}").status_code == 404
    assert b.get(f"/api/roles/{role['id']}/members").status_code == 404
    assert b.put(f"/api/roles/{role['id']}", json={"name": "Hijack", "permissions": []}).status_code == 404
    assert b.delete(f"/api/roles/{role['id']}").status_code == 404
    assert b.post(f"/api/roles/{role['id']}/copy").status_code == 404
    beta_tech = make_user(beta, "tech@beta.in", ["technician"])
    assert b.put(f"/api/staff/{beta_tech.id}/roles", json={"role_ids": [role["id"]]}).status_code == 422
    # The same name is fine in another centre.
    assert _make_role(b, name="Alpha only")["code"] == "alpha_only"
    with scoped_session(alpha.id) as db:
        names = set(db.scalars(select(Role.name).where(Role.tenant_id.is_not(None))))
    assert names == {"Alpha only"}


def test_a_permission_change_applies_on_the_next_request(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    role = _make_role(owner, name="Desk", perms=["patients.manage"])
    _give_role(alpha, "desk@alpha.in", role["id"])
    desk = browser("alpha.localhost")
    desk.login("desk@alpha.in")
    assert desk.get("/api/staff").status_code == 403
    assert owner.put(f"/api/roles/{role['id']}", json={"name": "Desk", "permissions": ["patients.manage", "staff.manage"]}).status_code == 200
    assert desk.get("/api/staff").status_code == 200
    assert "staff.manage" in desk.get("/api/auth/me").json()["permissions"]
    assert owner.put(f"/api/roles/{role['id']}", json={"name": "Desk", "permissions": ["patients.manage"]}).status_code == 200
    assert desk.get("/api/staff").status_code == 403


def test_role_changes_are_in_the_activity_log(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    role = _make_role(owner, name="Desk", perms=["patients.manage"])
    owner.put(f"/api/roles/{role['id']}", json={"name": "Desk", "permissions": ["billing.create"]})
    tech = make_user(alpha, "tech@alpha.in", ["technician"])
    owner.put(f"/api/staff/{tech.id}/roles", json={"role_ids": [role["id"]]})
    owner.delete(f"/api/roles/{role['id']}", params={"reassign_to": _roles(owner)["technician"]["id"]})

    log = {e["action"]: e["details"] for e in owner.get("/api/activity", params={"action": "role."}).json()["items"]}
    assert log["role.created"]["permission_changes"] == {"added": ["patients.manage"], "removed": []}
    assert log["role.updated"]["permission_changes"] == {"added": ["billing.create"], "removed": ["patients.manage"]}
    assert log["role.deleted"]["reassigned_to"] == "Technician"
    staff_log = owner.get("/api/activity", params={"action": "staff.roles_changed"}).json()["items"]
    # A technician loses the worklist and report-progress rights when moved to "Desk".
    assert staff_log[0]["details"]["permission_changes"] == {"added": ["billing.create"], "removed": ["reports.deliver", "worklist.update"]}


def test_staff_screen_still_lists_roles_for_staff_managers(alpha):
    owner = _signed_in(alpha, "owner@alpha.in", ["owner"])
    _make_role(owner, name="Night shift", perms=["worklist.update"])
    codes = [r["code"] for r in owner.get("/api/roles").json()]
    assert codes[:6] == ["owner", "admin", "receptionist", "technician", "doctor", "accounts"] and "night_shift" in codes
    tech = _signed_in(alpha, "tech@alpha.in", ["technician"])
    assert tech.get("/api/roles").status_code == 403
    assert tech.post("/api/roles", json={"name": "Xyz", "permissions": []}).status_code == 403
