"""The OPD: its doctors, the day's queue with tokens per doctor, consultation fees as bills, and moving a visit along."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db import scoped_session
from tests.conftest import browser, make_user

PATIENT = {"name": "Mita Saha", "age_years": 34, "gender": "female", "mobile": "9000011111"}


@pytest.fixture
def opd(alpha):
    """Alpha with an owner and an OPD desk (the opd role, working in the OPD)."""
    make_user(alpha, "owner@alpha.in", ["owner"])
    make_user(alpha, "desk@alpha.in", ["opd"])
    owner, desk = browser("alpha.localhost"), browser("alpha.localhost")
    owner.login("owner@alpha.in")
    desk.login("desk@alpha.in")
    sen = desk.post("/api/opd/doctors", json={"name": "Dr. A. Sen", "qualification": "MBBS, MD", "fee": "500"})
    assert sen.status_code == 201, sen.text
    bose = desk.post("/api/opd/doctors", json={"name": "Dr. B. Bose", "fee": "300"}).json()
    return {"owner": owner, "desk": desk, "sen": sen.json(), "bose": bose, "tenant": alpha}


def visit(c, doctor, fee, payment=None, **kw):
    body = {"patient": PATIENT, "doctor_id": doctor["id"], "fee": fee, **kw}
    if payment:
        body["payment"] = payment
    return c.post("/api/opd/visits", json=body)


def money(v) -> Decimal:
    return Decimal(str(v))


def test_opd_doctors_are_added_changed_and_switched_off(opd):
    desk, sen = opd["desk"], opd["sen"]
    assert sen["qualification"] == "MBBS, MD" and money(sen["fee"]) == Decimal("500") and sen["is_active"]
    dup = desk.post("/api/opd/doctors", json={"name": "dr. a. sen", "fee": "100"})
    assert dup.status_code == 409 and dup.json()["message"] == "There's already a doctor called dr. a. sen in the OPD."
    assert desk.post("/api/opd/doctors", json={"name": "Dr. C", "fee": "100001"}).status_code == 422
    off = desk.put(f"/api/opd/doctors/{sen['id']}", json={"name": "Dr. A. Sen", "qualification": "MBBS", "fee": "600",
                                                          "is_active": False})
    assert off.status_code == 200 and not off.json()["is_active"]
    assert [d["name"] for d in desk.get("/api/opd/doctors").json()] == ["Dr. B. Bose"]
    assert [d["name"] for d in desk.get("/api/opd/doctors", params={"all": "true"}).json()] == ["Dr. A. Sen", "Dr. B. Bose"]
    assert visit(desk, sen, "600").json()["field"] == "doctor_id"  # switched off: no new visits
    log = opd["owner"].get("/api/activity", params={"action": "opd.doctor"}).json()["items"]
    assert {e["action"] for e in log} == {"opd.doctor_created", "opd.doctor_updated"}


def test_changing_the_opd_doctors_needs_permission(opd, alpha):
    make_user(alpha, "acc@alpha.in", ["accounts"], areas=["opd"])
    acc = browser("alpha.localhost")
    acc.login("acc@alpha.in")
    assert acc.get("/api/opd/doctors").status_code == 200  # works in the OPD, may see who's there
    assert acc.post("/api/opd/doctors", json={"name": "Dr. X Y", "fee": "1"}).status_code == 403
    assert visit(acc, opd["sen"], "500").status_code == 403  # no appointments.manage


def test_a_visit_takes_the_fee_as_a_bill_and_gives_a_token_per_doctor(opd):
    desk, sen, bose = opd["desk"], opd["sen"], opd["bose"]
    r = visit(desk, sen, "500", {"mode": "cash", "amount": "200"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["token_no"] == 1 and v["status"] == "waiting" and v["doctor"] == {"id": sen["id"], "name": "Dr. A. Sen"}
    assert money(v["fee"]) == Decimal("500") and money(v["paid"]) == Decimal("200") and money(v["due"]) == Decimal("300")
    assert v["patient"]["name"] == "Mita Saha" and v["patient"]["patient_no"] == "P000001" and v["created_by_name"] == "Desk"
    assert v["invoice_no"].startswith("TST/") and v["invoice_id"]

    bill = desk.get(f"/api/bills/{v['invoice_id']}").json()  # the OPD opens a visit's fee bill
    assert [(i["test_name"], i["department_name"], i["test_id"]) for i in bill["items"]] == [("Consultation – Dr. A. Sen", "OPD", None)]
    assert money(bill["total"]) == Decimal("500") and bill["payments"][0]["mode"] == "cash"

    again = desk.post("/api/opd/visits", json={"patient_id": v["patient"]["id"], "doctor_id": sen["id"], "fee": "500"}).json()
    other = visit(desk, bose, "0").json()
    assert again["token_no"] == 2 and other["token_no"] == 1
    assert other["invoice_id"] is None and other["invoice_no"] == "" and money(other["due"]) == 0  # no fee, no bill

    queue = desk.get("/api/opd/visits").json()
    assert [(q["doctor"]["name"], q["token_no"]) for q in queue] == [("Dr. A. Sen", 1), ("Dr. A. Sen", 2), ("Dr. B. Bose", 1)]
    assert len(desk.get("/api/opd/visits", params={"doctor_id": bose["id"]}).json()) == 1
    assert desk.get("/api/opd/visits", params={"date": "2020-01-01"}).json() == []
    log = opd["owner"].get("/api/activity", params={"action": "opd.visit_created"}).json()
    assert log["total"] == 3


def test_paid_now_cannot_be_more_than_the_fee(opd):
    r = visit(opd["desk"], opd["sen"], "500", {"mode": "upi", "amount": "600", "reference": "U1"})
    assert r.status_code == 422 and r.json()["field"] == "payment.amount"
    assert r.json()["message"] == "Paid now can't be more than the fee, ₹500.00."
    free = visit(opd["desk"], opd["sen"], "0", {"mode": "cash", "amount": "1"})
    assert free.status_code == 422 and free.json()["field"] == "payment.amount"
    assert opd["desk"].get("/api/opd/visits").json() == []  # nothing was saved


def test_a_retried_visit_is_saved_once(opd):
    key = {"Idempotency-Key": "opd-visit-0001"}
    body = {"patient": PATIENT, "doctor_id": opd["sen"]["id"], "fee": "500"}
    first = opd["desk"].post("/api/opd/visits", json=body, headers=key)
    again = opd["desk"].post("/api/opd/visits", json=body, headers=key)
    assert first.status_code == again.status_code == 201 and first.json()["id"] == again.json()["id"]
    assert len(opd["desk"].get("/api/opd/visits").json()) == 1


def test_the_queue_moves_one_step_at_a_time(opd):
    desk = opd["desk"]
    v = visit(desk, opd["sen"], "500").json()
    url = f"/api/opd/visits/{v['id']}/status"
    assert desk.post(url, json={"status": "done"}).status_code == 409  # not seen yet
    called = desk.post(url, json={"status": "with_doctor"}).json()
    assert called["status"] == "with_doctor" and called["called_at"]
    done = desk.post(url, json={"status": "done"}).json()
    assert done["status"] == "done" and done["done_at"]
    assert desk.get(f"/api/bills/{v['invoice_id']}").json()["items"][0]["status"] == "delivered"
    assert desk.post(url, json={"status": "cancelled", "reason": "Left"}).status_code == 409  # already seen
    undo = desk.post(url, json={"status": "with_doctor"}).json()
    assert undo["status"] == "with_doctor" and undo["done_at"] is None
    assert desk.get(f"/api/bills/{v['invoice_id']}").json()["items"][0]["status"] == "billed"
    back = desk.post(url, json={"status": "waiting"}).json()
    assert back["status"] == "waiting" and back["called_at"] is None

    no_reason = desk.post(url, json={"status": "cancelled", "reason": "x"})
    assert no_reason.status_code == 422 and no_reason.json()["field"] == "reason"
    gone = desk.post(url, json={"status": "cancelled", "reason": "Patient left"}).json()
    assert gone["status"] == "cancelled" and gone["cancel_reason"] == "Patient left"
    assert desk.post(url, json={"status": "waiting"}).status_code == 409
    # The fee's bill is left as it is: money is given back from the bill.
    assert desk.get(f"/api/bills/{v['invoice_id']}").json()["status"] == "confirmed"
    actions = [e["action"] for e in opd["owner"].get("/api/activity", params={"action": "opd.visit_"}).json()["items"]]
    assert {"opd.visit_with_doctor", "opd.visit_done", "opd.visit_waiting", "opd.visit_cancelled"} <= set(actions)


def test_visits_are_private_to_their_centre_and_kept_by_the_database(opd, beta):
    v = visit(opd["desk"], opd["sen"], "500").json()
    make_user(beta, "owner@beta.in", ["owner"])
    other = browser("beta.localhost")
    other.login("owner@beta.in")
    assert other.get("/api/opd/visits").json() == [] and other.get("/api/opd/doctors").json() == []
    assert other.post(f"/api/opd/visits/{v['id']}/status", json={"status": "with_doctor"}).status_code == 404
    assert visit(other, opd["sen"], "500").status_code == 404
    with scoped_session(opd["tenant"].id) as db:
        with pytest.raises(Exception, match="permission denied"):
            db.execute(text("DELETE FROM opd_visits"))
        db.rollback()
