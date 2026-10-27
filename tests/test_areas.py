"""Work areas: where each person may work (reception, the OPD, departments), what /api/auth/me says, how staff are
given areas, and the server refusing work outside them. Also who may open the dev monitor."""

import pytest

from app.catalog import ROLES
from app.core.errors import Forbidden
from tests.conftest import browser, make_user

PATIENT = {"name": "Ramen Dey", "age_years": 61, "gender": "male", "mobile": "9000012345"}


@pytest.fixture
def centre(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    owner = browser("alpha.localhost")
    owner.login("owner@alpha.in")
    depts = {n: owner.post("/api/departments", json={"name": n}).json()["id"] for n in ("Radiology", "Pathology", "Cardiology")}
    owner.put(f"/api/departments/{depts['Cardiology']}", json={"name": "Cardiology", "is_active": False})
    xray = owner.post("/api/test-types", json={"name": "X-ray", "is_imaging": True}).json()["id"]
    tests = {}
    for name, dept in (("Chest X-ray", "Radiology"), ("CBC", "Pathology")):
        tests[name] = owner.post("/api/tests", json={"name": name, "department_id": depts[dept], "test_type_id": xray,
                                                     "price": "300"}).json()["id"]
    return {"owner": owner, "depts": depts, "tests": tests, "tenant": alpha}


def signed_in(tenant, email, roles, areas=None):
    make_user(tenant, email, roles, areas=areas)
    c = browser(f"{tenant.slug}.localhost")
    assert c.login(email).status_code == 200
    return c


def a_bill(c, tests):
    r = c.post("/api/bills", json={"patient": PATIENT, "lines": [{"test_id": tests["Chest X-ray"]}, {"test_id": tests["CBC"]}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_me_lists_every_area_and_where_each_person_works(centre):
    """Every area of the centre is listed (the chooser shows them all); allowed says which ones the person works in."""
    t, depts = centre["tenant"], centre["depts"]
    owner = centre["owner"].get("/api/auth/me").json()
    assert [a["key"] for a in owner["areas"]] == ["admin", "reception", "opd", f"department:{depts['Pathology']}",
                                                  f"department:{depts['Radiology']}"]  # switched-off Cardiology left out
    assert all(a["allowed"] for a in owner["areas"])
    assert owner["areas"][3] == {"key": f"department:{depts['Pathology']}", "kind": "department",
                                 "department_id": depts["Pathology"], "name": "Pathology", "allowed": True}

    def allowed(me):
        return {a["name"]: a["allowed"] for a in me["areas"]}

    tech = signed_in(t, "tech@alpha.in", ["technician"], areas=[depts["Radiology"], depts["Cardiology"]])
    assert allowed(tech.get("/api/auth/me").json()) == {"Reception": False, "OPD": False, "Pathology": False, "Radiology": True}
    login = browser("alpha.localhost").login("tech@alpha.in").json()
    assert [a["name"] for a in login["areas"] if a["allowed"]] == ["Radiology"]
    front = signed_in(t, "front@alpha.in", ["receptionist"], areas=["reception"])
    assert allowed(front.get("/api/auth/me").json()) == {"Reception": True, "OPD": False, "Pathology": False, "Radiology": False}
    nowhere = signed_in(t, "new@alpha.in", ["receptionist"], areas=[])
    assert not any(allowed(nowhere.get("/api/auth/me").json()).values())


def test_a_department_technician_works_only_in_their_department(centre):
    t, depts = centre["tenant"], centre["depts"]
    front = signed_in(t, "front@alpha.in", ["receptionist"], areas=["reception"])
    b = a_bill(front, centre["tests"])
    xray = next(i for i in b["items"] if i["test_name"] == "Chest X-ray")
    cbc = next(i for i in b["items"] if i["test_name"] == "CBC")
    tech = signed_in(t, "tech@alpha.in", ["technician"], areas=[depts["Radiology"]])
    assert tech.get("/api/bills").status_code == 403
    assert tech.get(f"/api/bills/{b['id']}").status_code == 403
    assert tech.get("/api/patients").status_code == 403
    assert tech.get("/api/worklist", params={"department_id": depts["Pathology"]}).status_code == 403
    assert tech.get("/api/worklist").status_code == 422
    rows = tech.get("/api/worklist", params={"department_id": depts["Radiology"]}).json()
    assert [r["test_name"] for r in rows["items"]] == ["Chest X-ray"]
    assert tech.post(f"/api/worklist/{xray['id']}/status", json={"status": "scanned"}).status_code == 204
    assert tech.post(f"/api/worklist/{cbc['id']}/status", json={"status": "scanned"}).status_code == 403
    # Reception marks tests ready or delivered from the bill page, whatever the department.
    assert front.post(f"/api/bills/{b['id']}/tests/status", json={"status": "reported"}).status_code == 204
    assert front.get("/api/worklist", params={"department_id": depts["Radiology"]}).status_code == 403


def test_reception_cannot_use_the_opd_unless_given_it(centre):
    t = centre["tenant"]
    front = signed_in(t, "front@alpha.in", ["receptionist"], areas=["reception"])
    assert front.get("/api/opd/doctors").status_code == 403
    assert front.get("/api/opd/visits").json()["message"] == "You don't work in the OPD."
    assert front.get("/api/bills").status_code == 200 and front.get("/api/bills/next-number").status_code == 200
    both = signed_in(t, "both@alpha.in", ["receptionist"], areas=["reception", "opd"])
    assert both.get("/api/opd/visits").status_code == 200


def test_the_opd_sees_bills_and_patients_but_does_not_bill(centre):
    desk = signed_in(centre["tenant"], "desk@alpha.in", ["receptionist"], areas=["opd"])
    assert desk.get("/api/bills").status_code == 200 and desk.get("/api/patients").status_code == 200
    assert desk.post("/api/patients", json=PATIENT).status_code == 201
    r = desk.post("/api/bills", json={"patient": PATIENT, "lines": [{"test_id": centre["tests"]["CBC"]}]})
    assert r.status_code == 403 and r.json()["message"] == "You don't work in reception."
    assert desk.get("/api/bills/next-number").status_code == 403
    assert desk.get("/api/dues/workbook").status_code == 403
    assert desk.get("/api/exports/bills.xlsx").status_code == 403


def test_the_owner_works_everywhere(centre):
    owner, depts = centre["owner"], centre["depts"]
    b = a_bill(owner, centre["tests"])
    assert owner.get("/api/worklist").json()["total"] == 2
    assert owner.get("/api/worklist", params={"department_id": depts["Pathology"]}).json()["total"] == 1
    item = b["items"][0]["id"]
    assert owner.post(f"/api/worklist/{item}/status", json={"status": "scanned"}).status_code == 204
    assert owner.get("/api/opd/visits").status_code == 200
    assert owner.post("/api/opd/doctors", json={"name": "Dr. A. Sen", "fee": "400"}).status_code == 201
    assert owner.get("/api/dues/workbook").status_code == 200


def _role_ids(c, *codes):
    roles = {r["code"]: r["id"] for r in c.get("/api/roles").json()}
    return [roles[code] for code in codes]


def test_staff_are_given_where_they_work(centre):
    owner, depts = centre["owner"], centre["depts"]
    base = {"full_name": "Piu Koley", "email": "piu@alpha.in", "role_ids": _role_ids(owner, "technician"),
            "temporary_password": "Temp-pass-123"}
    none = owner.post("/api/staff", json=base)
    assert none.status_code == 422 and none.json()["field"] == "areas"
    assert none.json()["message"] == "Choose where they work: reception, the OPD or a department."
    off = owner.post("/api/staff", json={**base, "areas": [{"area": "department", "department_id": depts["Cardiology"]}]})
    assert off.status_code == 422 and off.json()["field"] == "areas"
    unknown = owner.post("/api/staff", json={**base, "areas": [{"area": "department", "department_id": centre["tenant"].id.hex}]})
    assert unknown.status_code == 422
    no_dept = owner.post("/api/staff", json={**base, "areas": [{"area": "department"}]})
    assert no_dept.status_code == 422
    r = owner.post("/api/staff", json={**base, "areas": [{"area": "department", "department_id": depts["Radiology"]}]})
    assert r.status_code == 201, r.text
    assert r.json()["areas"] == [{"area": "department", "department_id": depts["Radiology"]}]
    # A role that works everywhere needs none.
    admin = owner.post("/api/staff", json={**base, "email": "adm@alpha.in", "role_ids": _role_ids(owner, "admin")})
    assert admin.status_code == 201 and admin.json()["areas"] == []

    uid = r.json()["id"]
    changed = owner.patch(f"/api/staff/{uid}", json={"areas": [{"area": "reception"}, {"area": "opd"}]})
    assert changed.status_code == 200
    assert {a["area"] for a in changed.json()["areas"]} == {"reception", "opd"}
    assert owner.patch(f"/api/staff/{uid}", json={"areas": []}).json()["field"] == "areas"
    listed = {s["email"]: s for s in owner.get("/api/staff").json()["items"]}
    assert {a["area"] for a in listed["piu@alpha.in"]["areas"]} == {"reception", "opd"}
    log = owner.get("/api/activity", params={"action": "staff.updated"}).json()["items"]
    assert log[0]["details"]["areas"] == [["Radiology"], ["OPD", "Reception"]]


def test_the_catalogue_has_the_new_permission_and_role():
    assert "areas.all" in ROLES["owner"][3] and "areas.all" in ROLES["admin"][3]
    assert ROLES["opd"][3] == {"patients.manage", "appointments.manage", "payments.collect"}
    assert "areas.all" not in ROLES["receptionist"][3]


# ---------- the dev monitor ----------

class _Person:
    def __init__(self, permissions):
        self.permissions = set(permissions)

    def can(self, p):
        return p in self.permissions


def test_only_owners_admins_and_developers_open_the_dev_monitor(monkeypatch):
    from types import SimpleNamespace

    from app.api import dev
    monkeypatch.setattr(dev, "get_settings", lambda: SimpleNamespace(environment="development"))
    for code in ("owner", "admin", "developer", "platform_owner"):
        person = _Person(ROLES[code][3])
        assert dev.developer(person) is person
    with pytest.raises(Forbidden, match="Only the owner, admins and developers"):
        dev.developer(_Person(ROLES["receptionist"][3]))
    monkeypatch.setattr(dev, "get_settings", lambda: SimpleNamespace(environment="test"))
    from app.core.errors import NotFound
    with pytest.raises(NotFound):
        dev.developer(_Person(ROLES["owner"][3]))
