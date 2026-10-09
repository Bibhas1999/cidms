"""Permissions, staff rules, centre settings, and the platform's client management."""

from sqlalchemy import select

from app.core.db import scoped_session
from app.models import Plan, Role
from tests.conftest import PASSWORD, browser, make_user


def _role_ids(c, *codes):
    roles = {r["code"]: r["id"] for r in c.get("/api/roles").json()}
    return [roles[code] for code in codes]


def test_a_receptionist_cannot_manage_staff_or_settings(alpha):
    make_user(alpha, "front@alpha.in", ["receptionist"])
    c = browser("alpha.localhost")
    c.login("front@alpha.in")
    assert c.get("/api/staff").status_code == 403
    assert c.put("/api/settings", json={"legal_name": "X", "invoice_prefix": "X"}).status_code == 403
    assert c.get("/api/settings").status_code == 200  # reading what bills show is fine


def test_client_people_cannot_reach_the_platform(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    assert c.get("/api/platform/clients").status_code == 404


def test_owner_adds_staff_who_must_then_choose_a_password(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    r = c.post("/api/staff", json={"full_name": "Piu Koley", "email": "Piu@Alpha.in", "mobile": "98765 43210",
                                   "role_ids": _role_ids(c, "receptionist"), "temporary_password": "Temp-pass-123"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "piu@alpha.in" and r.json()["must_change_password"] is True
    dup = c.post("/api/staff", json={"full_name": "Again", "email": "piu@alpha.in", "role_ids": _role_ids(c, "receptionist"),
                                     "temporary_password": "Temp-pass-123"})
    assert dup.status_code == 409 and dup.json()["field"] == "email"
    piu = browser("alpha.localhost")
    assert piu.login("piu@alpha.in", "Temp-pass-123").json()["must_change_password"] is True


def test_validation_errors_name_the_field_and_carry_a_request_id(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    r = c.post("/api/staff", json={"full_name": "X", "email": "not-an-email", "role_ids": [], "temporary_password": "a"})
    body = r.json()
    assert r.status_code == 422 and body["request_id"] == r.headers["x-request-id"]
    fields = {d["field"] for d in body["detail"]}
    assert {"full_name", "email", "role_ids"} <= fields
    assert any(d["message"] == "Enter a valid email address." for d in body["detail"])


def test_nobody_can_deactivate_themselves_or_remove_the_last_owner(alpha):
    me = make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    assert c.patch(f"/api/staff/{me.id}", json={"is_active": False}).status_code == 422
    r = c.patch(f"/api/staff/{me.id}", json={"role_ids": _role_ids(c, "admin")})
    assert r.status_code == 409 and "owner" in r.json()["message"]


def test_an_admin_cannot_create_owners(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    make_user(alpha, "admin@alpha.in", ["admin"])
    c = browser("alpha.localhost")
    c.login("admin@alpha.in")
    r = c.post("/api/staff", json={"full_name": "Sneaky", "email": "s@alpha.in", "role_ids": _role_ids(c, "owner"),
                                   "temporary_password": "Temp-pass-123"})
    assert r.status_code == 403


def test_deactivating_someone_signs_them_out(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    tech = make_user(alpha, "tech@alpha.in", ["technician"])
    boss, them = browser("alpha.localhost"), browser("alpha.localhost")
    boss.login("owner@alpha.in")
    them.login("tech@alpha.in")
    assert boss.patch(f"/api/staff/{tech.id}", json={"is_active": False}).status_code == 200
    assert them.get("/api/auth/me").status_code == 401


def test_the_plan_limits_active_staff(alpha):
    with scoped_session(platform=True) as db, db.begin():
        plan = Plan(code="tiny", name="Tiny", max_users=1, max_bills_per_month=10, storage_gb=1, price_monthly=0)
        db.add(plan)
        db.flush()
        from app.models import Tenant
        db.get(Tenant, alpha.id).plan_id = plan.id
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    r = c.post("/api/staff", json={"full_name": "One Too Many", "email": "x@alpha.in", "role_ids": _role_ids(c, "technician"),
                                   "temporary_password": "Temp-pass-123"})
    assert r.status_code == 409 and "plan" in r.json()["message"]


def test_settings_are_saved_and_logged(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    r = c.put("/api/settings", json={"legal_name": "Alpha Diagnostics Pvt Ltd", "invoice_prefix": "ALP", "gst_number": "19ABCDE1234F1Z5"})
    assert r.status_code == 200 and r.json()["invoice_prefix"] == "ALP"
    assert c.put("/api/settings", json={"legal_name": "A", "invoice_prefix": "bad prefix"}).status_code == 422
    log = c.get("/api/activity", params={"action": "settings."}).json()
    assert log["total"] == 1 and log["items"][0]["details"]["invoice_prefix"] == ["TST", "ALP"]


def test_platform_owner_onboards_a_client_whose_owner_can_sign_in():
    make_user(None, "boss@platform.in", ["platform_owner"])
    p = browser("admin.localhost")
    assert p.login("boss@platform.in").status_code == 200
    plan_id = p.get("/api/platform/plans").json()[0]["id"]
    r = p.post("/api/platform/clients", json={"slug": "gamma-labs", "name": "Gamma Labs", "kind": "diagnostic", "plan_id": plan_id,
                                              "owner_name": "Gamma Owner", "owner_email": "owner@gamma.in",
                                              "owner_temporary_password": "Welcome-12345"})
    assert r.status_code == 201, r.text
    assert p.post("/api/platform/clients", json={"slug": "gamma-labs", "name": "Again", "owner_name": "X Y",
                                                 "owner_email": "x@y.in", "owner_temporary_password": "Welcome-12345"}).status_code == 409
    assert p.post("/api/platform/clients", json={"slug": "admin", "name": "Admin", "owner_name": "X Y",
                                                 "owner_email": "x@y.in", "owner_temporary_password": "Welcome-12345"}).status_code == 422

    owner = browser("gamma-labs.localhost")
    me = owner.login("owner@gamma.in", "Welcome-12345").json()
    assert me["workspace"]["name"] == "Gamma Labs" and me["roles"] == ["Owner"]

    # Suspending signs everyone out and keeps them out.
    client_id = r.json()["id"]
    assert p.patch(f"/api/platform/clients/{client_id}", json={"status": "suspended"}).json()["status"] == "suspended"
    assert owner.get("/api/auth/me").status_code == 401
    assert browser("gamma-labs.localhost").login("owner@gamma.in", "Welcome-12345").status_code == 403


def test_platform_staff_list_shows_only_platform_people(alpha):
    make_user(None, "boss@platform.in", ["platform_owner"])
    make_user(alpha, "owner@alpha.in", ["owner"])
    p = browser("admin.localhost")
    p.login("boss@platform.in")
    assert [s["email"] for s in p.get("/api/staff").json()["items"]] == ["boss@platform.in"]
    assert {r["code"] for r in p.get("/api/roles").json()} == {"platform_owner", "platform_support"}


def test_built_in_roles_match_the_catalogue():
    with scoped_session(platform=True) as db:
        codes = set(db.scalars(select(Role.code).where(Role.tenant_id.is_(None))))
    assert {"owner", "admin", "receptionist", "technician", "doctor", "accounts", "platform_owner", "platform_support"} == codes


def test_unknown_addresses_have_no_workspace():
    c = browser("nowhere.localhost")
    assert c.get("/api/workspace").json()["kind"] == "none"
    assert c.login("a@b.in", PASSWORD).status_code == 404
