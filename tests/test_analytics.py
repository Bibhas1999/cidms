"""Analytics and who sees business figures; the rules for changing your own email and password."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.db import scoped_session
from app.models import ActivityLog, PasswordReset
from tests.conftest import PASSWORD, browser, make_user

SECTIONS = ["summary", "trend", "heatmap", "departments", "tests", "doctors", "patients", "dues", "staff", "pipeline", "live", "options"]
PATIENT = {"name": "Ramen Kumar Dey", "guardian_name": "Self", "age_years": 61, "gender": "male", "mobile": "9000012345", "address": "Janai"}


def money(v) -> Decimal:
    return Decimal(str(v))


def _bill(c, tests, names, **kw):
    r = c.post("/api/bills", json={"patient": kw.pop("patient", PATIENT), "lines": [{"test_id": tests[n]} for n in names], **kw})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def clinic(alpha):
    """Alpha with an owner, an admin, a receptionist and an accounts person, a small catalogue and a few bills."""
    for email, role in [("owner@alpha.in", "owner"), ("admin@alpha.in", "admin"), ("front@alpha.in", "receptionist"),
                        ("accounts@alpha.in", "accounts")]:
        make_user(alpha, email, [role])
    people = {}
    for name in ["owner", "admin", "front", "accounts"]:
        people[name] = browser("alpha.localhost")
        assert people[name].login(f"{name}@alpha.in").status_code == 200
    owner = people["owner"]
    radiology = owner.post("/api/departments", json={"name": "Radiology"}).json()["id"]
    pathology = owner.post("/api/departments", json={"name": "Pathology"}).json()["id"]
    kind = owner.post("/api/test-types", json={"name": "General"}).json()["id"]
    tests = {}
    for name, dept, price in [("X-ray", radiology, "350"), ("CBC", pathology, "250.50"), ("Lipid", pathology, "600")]:
        tests[name] = owner.post("/api/tests", json={"name": name, "department_id": dept, "test_type_id": kind, "price": price}).json()["id"]
    doctor = owner.post("/api/doctors", json={"name": "Dr Sen"}).json()["id"]
    front = people["front"]
    a = _bill(front, tests, ["X-ray", "CBC"], referring_doctor_id=doctor, discount_type="amount", discount_value="50.50",
              payments=[{"mode": "cash", "amount": "300"}])
    b = _bill(front, tests, ["Lipid"], patient={**PATIENT, "name": "Suman Das", "mobile": "7000054321", "gender": "female", "age_years": 30},
              payments=[{"mode": "upi", "amount": "600", "reference": "U1"}])
    _bill(owner, tests, ["CBC"], patient={**PATIENT, "name": "Baby Roy", "mobile": "7980003591", "gender": "female", "age_years": 1})
    front.post(f"/api/bills/{a['id']}/payments", json={"mode": "cash", "amount": "100"})
    owner.post(f"/api/bills/{b['id']}/refunds", json={"mode": "upi", "amount": "100", "note": "Overcharged"})
    return {**people, "tests": tests, "doctor": doctor, "radiology": radiology, "tenant": alpha}


# ---------- who sees business figures ----------

@pytest.mark.parametrize("who", ["front", "accounts"])
def test_staff_other_than_owner_and_admin_cannot_see_analytics_but_see_totals(clinic, who):
    c = clinic[who]
    for section in SECTIONS:
        assert c.get(f"/api/analytics/{section}").status_code == 403, section
    assert c.get("/api/summary/overview").status_code == 403
    assert "analytics.view" not in c.get("/api/auth/me").json()["permissions"]
    sums = c.get("/api/bills").json()["sums"]
    assert money(sums["billed"]) > 0 and money(sums["paid"]) > 0 and money(sums["due"]) > 0  # totals are for everyone
    day = c.get("/api/summary/day").json()
    assert day["billed"] is not None and money(day["collected_total"]) > 0


@pytest.mark.parametrize("who", ["owner", "admin"])
def test_owner_and_admin_see_analytics(clinic, who):
    c = clinic[who]
    for section in SECTIONS:
        assert c.get(f"/api/analytics/{section}").status_code == 200, section
    assert c.get("/api/summary/overview").status_code == 200
    assert c.get("/api/bills").json()["sums"]["billed"] is not None


def test_the_desk_summary_shows_the_totals(clinic):
    for who in ["front", "accounts", "owner"]:
        r = clinic[who].get("/api/summary/desk")
        assert r.status_code == 200
        d = r.json()
        assert money(d["billed"]) == Decimal("1400.50") and "discounts" not in d  # 550 + 250.50 + 600
        assert {k: money(v) for k, v in d["collected"].items()} == {"cash": Decimal("400.00"), "upi": Decimal("500.00")}
        assert money(d["collected_total"]) == Decimal("900.00") and money(d["refunds"]) == Decimal("100.00")
        # X-ray + CBC 600.50 - 50.50 = 550, paid 400 -> 150 due; CBC 250.50 unpaid; Lipid paid then refunded 100 -> 100 due.
        assert money(d["outstanding_dues"]) == Decimal("500.50") and d["dues_count"] == 3
        assert money(d["due_on_bills"]) == Decimal("500.50") and d["due_bills"] == 3
        assert d["bills"] == 3 and d["pending_tests"] == {"billed": 4, "scanned": 0}
    assert clinic["front"].get("/api/summary/desk", params={"from": "2026-05-02", "to": "2026-05-01"}).status_code == 422


def test_analytics_reconcile_with_the_bills(clinic):
    c = clinic["owner"]
    bills = c.get("/api/bills").json()
    s = c.get("/api/analytics/summary").json()
    assert s["bills"] == bills["total"] == 3
    assert money(s["billed"]) == money(bills["sums"]["billed"]) == Decimal("1400.50")
    assert money(s["due_on_bills"]) == money(bills["sums"]["due"])
    assert money(s["collected"]) == Decimal("900.00") and money(s["refunds"]) == Decimal("100.00")
    assert money(s["discounts"]) == Decimal("50.50") and s["patients"] == 3 and s["tests"] == 4
    assert s["efficiency_pct"] == round(900 / 1400.50 * 100, 1)

    trend = c.get("/api/analytics/trend").json()["points"]
    assert sum(money(p["billed"]) for p in trend) == money(s["billed"])
    assert sum(money(p["collected"]) for p in trend) == money(s["collected"])
    assert sum(p["bills"] for p in trend) == 3
    assert sum(c_["bills"] for c_ in c.get("/api/analytics/heatmap").json()["cells"]) == 3
    depts = {d["name"]: money(d["amount"]) for d in c.get("/api/analytics/departments").json()["rows"]}
    assert depts == {"Pathology": Decimal("1101.00"), "Radiology": Decimal("350.00")}  # before the bill's discount
    tests = c.get("/api/analytics/tests").json()
    assert tests["by_count"][0]["name"] == "CBC" and tests["by_count"][0]["count"] == 2
    doctors = c.get("/api/analytics/doctors").json()
    assert doctors["rows"][0]["name"] == "Dr Sen" and doctors["rows"][0]["bills"] == 1 and doctors["self_referred"]["bills"] == 2
    patients = c.get("/api/analytics/patients").json()
    assert patients["new"] == 3 and patients["returning"] == 0
    ages = {a["band"]: a for a in patients["ages"]}
    assert ages["0–12"]["female"] == 1 and ages["30–44"]["female"] == 1 and ages["60+"]["male"] == 1
    dues = c.get("/api/analytics/dues").json()
    assert money(dues["total"]) == Decimal("500.50") and dues["rows"][0]["bills"] == 3
    staff = c.get("/api/analytics/staff").json()["rows"]
    assert sum(money(r["billed"]) for r in staff) == money(s["billed"])
    assert {r["name"]: r["bills"] for r in staff} == {"Front": 2, "Owner": 1}
    pipeline = c.get("/api/analytics/pipeline").json()
    assert pipeline["total"] == 4 and pipeline["stages"][0]["reached"] == 4
    live = c.get("/api/analytics/live").json()
    assert live["bills"] == 3 and money(live["collected"]) == Decimal("900.00") and len(live["recent"]) == 3
    assert sum(h["today"] for h in live["hours"]) == 3

    # Filters narrow every section the same way.
    by_doc = c.get("/api/analytics/summary", params={"doctor": clinic["doctor"]}).json()
    assert by_doc["bills"] == 1 and money(by_doc["billed"]) == Decimal("550.00")
    selfref = c.get("/api/analytics/summary", params={"doctor": "self"}).json()
    assert selfref["bills"] == 2
    radiology = c.get("/api/analytics/departments", params={"department_id": clinic["radiology"]}).json()["rows"]
    assert [r["name"] for r in radiology] == ["Radiology"]
    assert c.get("/api/analytics/summary", params={"from": "2026-05-02", "to": "2026-05-01"}).status_code == 422
    assert c.get("/api/analytics/summary", params={"doctor": "nobody"}).status_code == 422


def test_analytics_never_cross_centres(clinic, beta):
    make_user(beta, "owner@beta.in", ["owner"])
    other = browser("beta.localhost")
    other.login("owner@beta.in")
    s = other.get("/api/analytics/summary").json()
    assert s["bills"] == 0 and money(s["billed"]) == 0 and money(s["collected"]) == 0
    assert other.get("/api/analytics/live").json()["recent"] == []
    opts = other.get("/api/analytics/options").json()
    assert opts == {"departments": [], "doctors": [], "billers": []}
    # Asking for alpha's doctor from beta finds nothing.
    assert other.get("/api/analytics/summary", params={"doctor": clinic["doctor"]}).json()["bills"] == 0
    # An alpha session doesn't work at beta's address.
    stolen = browser("beta.localhost")
    stolen.cookies.update(dict(clinic["owner"].cookies))
    assert stolen.get("/api/analytics/summary").status_code == 401


# ---------- your own email and password ----------

def test_staff_cannot_change_their_own_password_or_email(clinic):
    for who in ["front", "accounts"]:
        c = clinic[who]
        assert c.get("/api/auth/me").json()["manage_own_account"] is False
        r = c.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "Brand-new-pass-9"})
        assert r.status_code == 403
        assert c.put("/api/auth/email", json={"email": "me@else.in", "current_password": PASSWORD}).status_code == 403
        assert c.login(f"{who}@alpha.in").status_code == 200  # the password is unchanged


def test_owner_and_admin_change_their_password(clinic):
    for who in ["owner", "admin"]:
        c = clinic[who]
        assert c.get("/api/auth/me").json()["manage_own_account"] is True
        r = c.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "Brand-new-pass-9"})
        assert r.status_code == 200


def test_owner_changes_their_email(clinic):
    c = clinic["owner"]
    wrong = c.put("/api/auth/email", json={"email": "boss@alpha.in", "current_password": "nope-nope"})
    assert wrong.status_code == 422 and wrong.json()["field"] == "current_password"
    taken = c.put("/api/auth/email", json={"email": "FRONT@alpha.in", "current_password": PASSWORD})
    assert taken.status_code == 409 and taken.json()["field"] == "email"
    assert c.put("/api/auth/email", json={"email": "not an email", "current_password": PASSWORD}).status_code == 422
    ok = c.put("/api/auth/email", json={"email": "  Boss@Alpha.in ", "current_password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["email"] == "boss@alpha.in"
    assert c.get("/api/auth/me").json()["email"] == "boss@alpha.in"  # still signed in
    assert browser("alpha.localhost").login("owner@alpha.in").status_code == 401
    assert browser("alpha.localhost").login("boss@alpha.in").status_code == 200
    with scoped_session(platform=True) as db:
        assert db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.action == "user.email_changed")) == 1


def test_the_same_email_is_fine_in_another_centre(clinic, beta):
    make_user(beta, "front@alpha.in", ["receptionist"])  # someone at beta happens to use it
    r = clinic["admin"].put("/api/auth/email", json={"email": "owner2@alpha.in", "current_password": PASSWORD})
    assert r.status_code == 200


def test_staff_given_a_temporary_password_still_choose_their_own_at_first_sign_in(clinic):
    staff = clinic["owner"].get("/api/staff", params={"search": "front"}).json()["items"][0]
    assert clinic["owner"].post(f"/api/staff/{staff['id']}/reset-password", json={"temporary_password": "Temp-pass-123"}).status_code == 204
    c = browser("alpha.localhost")
    assert c.login("front@alpha.in", "Temp-pass-123").json()["must_change_password"] is True
    ok = c.post("/api/auth/password", json={"current_password": "Temp-pass-123", "new_password": "Brand-new-pass-9"})
    assert ok.status_code == 200 and ok.json()["must_change_password"] is False
    # ...and only then: a second change is the owner's or admin's job.
    again = c.post("/api/auth/password", json={"current_password": "Brand-new-pass-9", "new_password": "Another-pass-10"})
    assert again.status_code == 403


def test_forgot_password_only_works_for_owner_and_admin(clinic):
    anon = browser("alpha.localhost")
    for email in ["front@alpha.in", "owner@alpha.in"]:
        assert anon.post("/api/auth/forgot-password", json={"email": email}).status_code == 202  # same answer either way
    with scoped_session(platform=True) as db:
        assert db.scalar(select(func.count()).select_from(PasswordReset)) == 1  # only the owner's link was made
