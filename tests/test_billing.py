"""Billing: money rules, numbering, dues, refunds, cancelling, editing, worklist, the day's summary, separation."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db import scoped_session
from app.core.money import financial_year, local_today
from tests.conftest import browser, make_tenant, make_user

FY = financial_year(local_today())


@pytest.fixture
def centre(alpha):
    """Alpha with an owner, a receptionist, a technician and a small catalogue."""
    make_user(alpha, "owner@alpha.in", ["owner"])
    make_user(alpha, "front@alpha.in", ["receptionist"])
    make_user(alpha, "tech@alpha.in", ["technician"])
    owner = browser("alpha.localhost")
    owner.login("owner@alpha.in")
    radiology = owner.post("/api/departments", json={"name": "Radiology"}).json()["id"]
    pathology = owner.post("/api/departments", json={"name": "Pathology"}).json()["id"]
    xray = owner.post("/api/test-types", json={"name": "X-ray", "is_imaging": True}).json()["id"]
    blood = owner.post("/api/test-types", json={"name": "Blood"}).json()["id"]
    tests = {}
    for name, dept, kind, price in [("Chest X-ray PA", radiology, xray, "350"), ("CBC", pathology, blood, "250.50"),
                                    ("Lipid profile", pathology, blood, "600")]:
        r = owner.post("/api/tests", json={"name": name, "department_id": dept, "test_type_id": kind, "price": price})
        assert r.status_code == 201, r.text
        tests[name] = r.json()["id"]
    front = browser("alpha.localhost")
    front.login("front@alpha.in")
    return {"owner": owner, "front": front, "tests": tests, "tenant": alpha}


NEW_PATIENT = {"name": "Phoni  Bhusan Bag", "guardian_name": "Self", "age_years": 61, "gender": "male", "mobile": "9051136089",
               "address": "Janai, Hooghly"}


def bill(c, tests, names, **kw):
    body = {"patient": NEW_PATIENT, "lines": [{"test_id": tests[n]} for n in names], **kw}
    return c.post("/api/bills", json=body)


def money(v) -> Decimal:
    return Decimal(str(v))


def test_a_bill_is_priced_from_the_catalogue_and_numbered_per_financial_year(centre):
    r = bill(centre["front"], centre["tests"], ["Chest X-ray PA", "CBC"], payments=[{"mode": "cash", "amount": "300"}],
             referring_doctor_name="Dr. S.K. Halder")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["invoice_no"] == f"TST/{FY}/000001"
    assert money(b["subtotal"]) == Decimal("600.50") and money(b["total"]) == Decimal("600.50")
    assert money(b["paid"]) == Decimal("300") and money(b["due"]) == Decimal("300.50")
    assert b["patient_name"] == "Phoni Bhusan Bag" and b["patient_age"] == "61 Y" and b["referring_doctor_name"] == "Dr. S.K. Halder"
    xray = next(i for i in b["items"] if i["test_name"] == "Chest X-ray PA")
    assert xray["is_imaging"] and xray["accession_no"].startswith("A")
    assert next(i for i in b["items"] if i["test_name"] == "CBC")["accession_no"] == ""
    assert b["payments"][0]["received_by_name"] == "Front"

    second = centre["front"].post("/api/bills", json={"patient_id": b["patient_id"], "lines": [{"test_id": centre["tests"]["CBC"]}]}).json()
    assert second["invoice_no"] == f"TST/{FY}/000002"
    assert second["referring_doctor_name"] == ""  # no doctor given: "Self"


def test_the_browser_cannot_set_prices(centre):
    body = {"patient": NEW_PATIENT, "lines": [{"test_id": centre["tests"]["CBC"], "unit_price": "1", "amount": "1"}], "total": "1"}
    b = centre["front"].post("/api/bills", json=body).json()
    assert money(b["total"]) == Decimal("250.50")


def test_discounts_within_the_limit_and_above_it(centre):
    tests = centre["tests"]
    ok = bill(centre["front"], tests, ["Lipid profile"], discount_type="percent", discount_value="10").json()
    assert money(ok["discount_amount"]) == Decimal("60.00") and money(ok["total"]) == Decimal("540.00")
    over = bill(centre["front"], tests, ["Lipid profile"], discount_type="percent", discount_value="25")
    assert over.status_code == 403 and over.json()["field"] == "discount_value"
    by_owner = bill(centre["owner"], tests, ["Lipid profile"], discount_type="amount", discount_value="300")
    assert by_owner.status_code == 201 and money(by_owner.json()["total"]) == Decimal("300.00")
    too_big = bill(centre["owner"], tests, ["Lipid profile"], discount_type="amount", discount_value="601")
    assert too_big.status_code == 422


def test_cannot_take_more_than_the_bill(centre):
    r = bill(centre["front"], centre["tests"], ["CBC"], payments=[{"mode": "cash", "amount": "200"}, {"mode": "upi", "amount": "100", "reference": "UPI123"}])
    assert r.status_code == 422 and r.json()["field"] == "payments"


def test_collecting_a_due_in_instalments(centre):
    b = bill(centre["front"], centre["tests"], ["Lipid profile"]).json()
    url = f"/api/bills/{b['id']}/payments"
    assert centre["front"].post(url, json={"mode": "cash", "amount": "700"}).status_code == 422
    assert money(centre["front"].post(url, json={"mode": "cash", "amount": "250"}).json()["due"]) == Decimal("350")
    last = centre["front"].post(url, json={"mode": "upi", "amount": "350", "reference": "T123"}).json()
    assert money(last["due"]) == 0 and len(last["payments"]) == 2
    assert centre["front"].post(url, json={"mode": "cash", "amount": "1"}).status_code == 409


def test_a_retried_request_never_creates_a_second_bill_or_payment(centre):
    key = {"Idempotency-Key": "bill-key-0001"}
    body = {"patient": NEW_PATIENT, "lines": [{"test_id": centre["tests"]["CBC"]}]}
    first = centre["front"].post("/api/bills", json=body, headers=key)
    again = centre["front"].post("/api/bills", json=body, headers=key)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"] and again.headers["idempotent-replayed"] == "true"
    assert centre["front"].get("/api/bills").json()["total"] == 1

    pay_key = {"Idempotency-Key": "pay-key-0001"}
    url = f"/api/bills/{first.json()['id']}/payments"
    centre["front"].post(url, json={"mode": "cash", "amount": "100"}, headers=pay_key)
    replay = centre["front"].post(url, json={"mode": "cash", "amount": "100"}, headers=pay_key)
    assert len(replay.json()["payments"]) == 1 and money(replay.json()["paid"]) == Decimal("100")
    # Someone else can't reuse it.
    other = centre["owner"].post(url, json={"mode": "cash", "amount": "100"}, headers=pay_key)
    assert other.status_code == 409


def test_refunds_need_a_reason_and_cannot_exceed_what_was_paid(centre):
    b = bill(centre["front"], centre["tests"], ["CBC"], payments=[{"mode": "cash", "amount": "250.50"}]).json()
    url = f"/api/bills/{b['id']}/refunds"
    assert centre["front"].post(url, json={"mode": "cash", "amount": "10"}).status_code == 422  # no reason
    assert centre["front"].post(url, json={"mode": "cash", "amount": "300", "note": "Test not done"}).status_code == 422
    r = centre["front"].post(url, json={"mode": "cash", "amount": "250.50", "note": "Test not done"}).json()
    assert money(r["paid"]) == 0 and money(r["due"]) == Decimal("250.50") and r["payments"][-1]["kind"] == "refund"


def test_cancelling_needs_the_money_refunded_first_and_freezes_the_bill(centre):
    b = bill(centre["front"], centre["tests"], ["CBC"], payments=[{"mode": "cash", "amount": "100"}]).json()
    owner = centre["owner"]
    assert centre["front"].post(f"/api/bills/{b['id']}/cancel", json={"reason": "Patient left"}).status_code == 403  # no billing.edit
    blocked = owner.post(f"/api/bills/{b['id']}/cancel", json={"reason": "Patient left"})
    assert blocked.status_code == 409 and "Refund" in blocked.json()["message"]
    owner.post(f"/api/bills/{b['id']}/refunds", json={"mode": "cash", "amount": "100", "note": "Patient left"})
    done = owner.post(f"/api/bills/{b['id']}/cancel", json={"reason": "Patient left"}).json()
    assert done["status"] == "cancelled" and all(i["status"] == "cancelled" for i in done["items"])
    assert owner.post(f"/api/bills/{b['id']}/payments", json={"mode": "cash", "amount": "1"}).status_code == 409
    assert owner.post(f"/api/bills/{b['id']}/hold", json={"reason": "x"}).status_code in (409, 422)


def test_editing_a_bill_adds_and_removes_tests_with_a_reason(centre):
    t = centre["tests"]
    b = bill(centre["front"], t, ["Chest X-ray PA", "CBC"], payments=[{"mode": "cash", "amount": "500"}]).json()
    xray = next(i for i in b["items"] if i["test_name"] == "Chest X-ray PA")
    cbc = next(i for i in b["items"] if i["test_name"] == "CBC")
    owner = centre["owner"]
    url = f"/api/bills/{b['id']}"

    no_reason = owner.put(url, json={"lines": [{"id": xray["id"]}]})
    assert no_reason.status_code == 422
    # Dropping the X-ray would leave less than was paid.
    too_low = owner.put(url, json={"lines": [{"id": cbc["id"]}], "reason": "Wrong test"})
    assert too_low.status_code == 422 and "Refund" in too_low.json()["message"]
    swapped = owner.put(url, json={"lines": [{"id": xray["id"]}, {"test_id": t["Lipid profile"]}], "reason": "Doctor changed CBC to lipid profile"}).json()
    assert money(swapped["total"]) == Decimal("950.00") and money(swapped["due"]) == Decimal("450.00")
    assert {i["test_name"]: i["status"] for i in swapped["items"]} == {"Chest X-ray PA": "billed", "CBC": "cancelled", "Lipid profile": "billed"}

    # Once scanned, the X-ray can't be taken off.
    make_user(centre["tenant"], "tech2@alpha.in", ["technician"])
    tech = browser("alpha.localhost")
    tech.login("tech2@alpha.in")
    assert tech.post(f"/api/worklist/{xray['id']}/status", json={"status": "scanned"}).status_code == 204
    lipid = next(i for i in swapped["items"] if i["test_name"] == "Lipid profile")
    r = owner.put(url, json={"lines": [{"id": lipid["id"]}], "reason": "Remove x-ray"})
    assert r.status_code == 422 and "scanned" in r.json()["message"]


def test_worklist_progress(centre):
    b = bill(centre["front"], centre["tests"], ["Chest X-ray PA", "CBC"]).json()
    xray = next(i for i in b["items"] if i["is_imaging"])
    cbc = next(i for i in b["items"] if not i["is_imaging"])
    tech = browser("alpha.localhost")
    tech.login("tech@alpha.in")
    rows = tech.get("/api/worklist").json()
    assert rows["total"] == 2
    assert centre["front"].post(f"/api/worklist/{xray['id']}/status", json={"status": "scanned"}).status_code == 403
    assert tech.post(f"/api/worklist/{cbc['id']}/status", json={"status": "scanned"}).status_code == 422  # not a scan
    assert tech.post(f"/api/worklist/{xray['id']}/status", json={"status": "scanned"}).status_code == 204
    assert tech.post(f"/api/worklist/{xray['id']}/status", json={"status": "delivered"}).status_code == 204
    assert [r["test_name"] for r in tech.get("/api/worklist").json()["items"]] == ["CBC"]
    assert tech.get("/api/worklist", params={"status": "delivered"}).json()["items"][0]["test_name"] == "Chest X-ray PA"


def test_the_days_summary_adds_up(centre):
    t, front = centre["tests"], centre["front"]
    a = bill(front, t, ["Lipid profile"], discount_type="amount", discount_value="100", payments=[{"mode": "cash", "amount": "500"}]).json()
    b = bill(front, t, ["CBC"], payments=[{"mode": "upi", "amount": "200", "reference": "U1"}]).json()
    front.post(f"/api/bills/{b['id']}/payments", json={"mode": "cash", "amount": "50.50"})
    centre["owner"].post(f"/api/bills/{a['id']}/refunds", json={"mode": "cash", "amount": "100", "note": "Overcharged"})
    s = front.get("/api/summary/day").json()
    assert s["bills"] == 2
    assert money(s["billed"]) == Decimal("750.50") and money(s["discounts"]) == Decimal("100.00")
    assert {k: money(v) for k, v in s["collected"].items()} == {"cash": Decimal("450.50"), "upi": Decimal("200.00")}
    assert money(s["collected_total"]) == Decimal("650.50") and money(s["refunds"]) == Decimal("100.00")
    assert money(s["outstanding_dues"]) == Decimal("100.00")
    assert s["items_by_status"] == {"billed": 2}


def test_bill_search_filters_and_totals(centre):
    t, front = centre["tests"], centre["front"]
    a = bill(front, t, ["CBC"]).json()
    front.post("/api/bills", json={"patient": {**NEW_PATIENT, "name": "Suman Das", "mobile": "7980003590"},
                                   "lines": [{"test_id": t["Lipid profile"]}], "payments": [{"mode": "cash", "amount": "600"}]})
    assert front.get("/api/bills", params={"search": "suman"}).json()["items"][0]["patient_name"] == "Suman Das"
    assert front.get("/api/bills", params={"search": "0003590"}).json()["total"] == 1
    assert front.get("/api/bills", params={"search": a["invoice_no"]}).json()["items"][0]["id"] == a["id"]
    assert front.get("/api/bills", params={"search": "1"}).json()["items"][0]["id"] == a["id"]  # bill 000001
    dues = front.get("/api/bills", params={"due": "true"}).json()
    assert dues["total"] == 1 and money(dues["sums"]["due"]) == Decimal("250.50")
    assert money(front.get("/api/bills").json()["sums"]["billed"]) == Decimal("850.50")


def test_patients_are_numbered_and_family_members_share_a_mobile(centre):
    front = centre["front"]
    p1 = front.post("/api/patients", json=NEW_PATIENT).json()
    p2 = front.post("/api/patients", json={**NEW_PATIENT, "name": "Pooja Bag", "gender": "female", "age_years": 23}).json()
    assert (p1["patient_no"], p2["patient_no"]) == ("P000001", "P000002")
    same = front.get("/api/patients/same-mobile", params={"mobile": "+91 90511 36089"}).json()
    assert {p["name"] for p in same} == {"Phoni Bhusan Bag", "Pooja Bag"}
    assert front.post("/api/patients", json={**NEW_PATIENT, "age_years": None}).status_code == 422


def test_another_centres_bills_and_tests_are_out_of_reach(centre):
    b = bill(centre["front"], centre["tests"], ["CBC"]).json()
    beta = make_tenant("beta")
    make_user(beta, "owner@beta.in", ["owner"])
    other = browser("beta.localhost")
    other.login("owner@beta.in")
    assert other.get(f"/api/bills/{b['id']}").status_code == 404
    assert other.post(f"/api/bills/{b['id']}/payments", json={"mode": "cash", "amount": "1"}).status_code == 404
    r = other.post("/api/bills", json={"patient": NEW_PATIENT, "lines": [{"test_id": centre["tests"]["CBC"]}]})
    assert r.status_code == 422 and r.json()["field"] == "lines"
    assert other.get("/api/bills").json()["total"] == 0 and other.get("/api/tests").json()["total"] == 0


def test_switched_off_tests_cannot_be_billed(centre):
    owner, t = centre["owner"], centre["tests"]
    cbc = owner.get("/api/tests", params={"search": "cbc"}).json()["items"][0]
    owner.put(f"/api/tests/{t['CBC']}", json={"name": "CBC", "department_id": cbc["department"]["id"],
                                              "test_type_id": cbc["test_type"]["id"], "price": "250.50", "is_active": False})
    r = bill(centre["front"], t, ["CBC"])
    assert r.status_code == 422 and "switched off" in r.json()["message"]


def test_the_database_itself_keeps_the_money_consistent(centre):
    b = bill(centre["front"], centre["tests"], ["CBC"], payments=[{"mode": "cash", "amount": "50"}]).json()
    with scoped_session(centre["tenant"].id) as db:
        with pytest.raises(Exception, match=r"ck_invoices_(total|due)"):
            db.execute(text("UPDATE invoices SET total = 1 WHERE id = :i"), {"i": b["id"]})
        db.rollback()
        with pytest.raises(Exception, match="permission denied"):
            db.execute(text("UPDATE payments SET amount = 1"))
        db.rollback()
        with pytest.raises(Exception, match="permission denied"):
            db.execute(text("DELETE FROM invoices"))
        db.rollback()


def test_catalogue_changes_need_permission_and_names_are_unique(centre):
    front, owner = centre["front"], centre["owner"]
    assert front.post("/api/departments", json={"name": "Cardiology"}).status_code == 403
    assert owner.post("/api/departments", json={"name": "radiology"}).status_code == 409
    assert front.get("/api/tests", params={"search": "x-ray"}).json()["items"][0]["name"] == "Chest X-ray PA"
