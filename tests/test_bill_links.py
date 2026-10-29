"""The patient's public link to a bill (the QR code on the printout): issuing it, the check, lockout, isolation."""

import hashlib

import pytest
from sqlalchemy import text

from app.core.db import scoped_session
from app.services import bill_links
from tests.conftest import browser, make_user

NEW_PATIENT = {"name": "Ramen Kumar Dey", "guardian_name": "Self", "age_years": 61, "gender": "male", "mobile": "9000012345",
               "address": "Janai, Hooghly"}


def _centre(tenant, sub: str):
    host = f"{sub}.localhost"
    make_user(tenant, f"owner@{sub}.in", ["owner"])
    owner = browser(host)
    owner.login(f"owner@{sub}.in")
    dept = owner.post("/api/departments", json={"name": "Pathology"}).json()["id"]
    test_id = owner.post("/api/tests", json={"name": "CBC", "department_id": dept, "price": "250"}).json()["id"]
    r = owner.post("/api/bills", json={"patient": NEW_PATIENT, "lines": [{"test_id": test_id}]})
    assert r.status_code == 201, r.text
    return {"owner": owner, "tenant": tenant, "host": host, "bill": r.json()}


@pytest.fixture
def centre(alpha):
    return _centre(alpha, "alpha")


@pytest.fixture
def other(beta):
    return _centre(beta, "beta")


def share_token(c) -> str:
    share = c["owner"].post(f"/api/bills/{c['bill']['id']}/share").json()
    assert share["active"]
    return share["url"].rsplit("/", 1)[-1]


def test_a_bill_prints_a_patient_link_that_opens_with_the_mobile_digits(centre):
    token = share_token(centre)
    p = browser(centre["host"])

    info = p.get(f"/api/public/bills/{token}")
    assert info.status_code == 200
    assert info.json()["check"] == "mobile"
    wrong = p.post(f"/api/public/bills/{token}/open", json={"check": "0000"})
    assert wrong.status_code == 403 and "match" in wrong.json()["message"]
    ok = p.post(f"/api/public/bills/{token}/open", json={"check": "2345"})
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "no-store" and "noindex" in ok.headers["x-robots-tag"]
    body = ok.json()
    assert body["bill"]["id"] == centre["bill"]["id"] and body["patient_no"]

    with scoped_session(platform=True) as db:
        logged = sorted(db.execute(text("SELECT action FROM activity_log WHERE action LIKE 'bill.public%'")).scalars())
    assert logged == ["bill.public_check_failed", "bill.public_viewed"]
    assert centre["owner"].get(f"/api/bills/{centre['bill']['id']}/share").json()["views"] == 1

    with scoped_session(centre["tenant"].id) as db:
        stored = db.execute(text("SELECT token_hash FROM invoice_shares")).scalar()
    assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in stored


def test_wrong_checks_lock_the_bill_link(centre):
    token = share_token(centre)
    p = browser(centre["host"])
    for _ in range(bill_links.MAX_FAILED):
        assert p.post(f"/api/public/bills/{token}/open", json={"check": "1111"}).status_code == 403
    assert p.post(f"/api/public/bills/{token}/open", json={"check": "2345"}).status_code == 429


def test_revoked_expired_unknown_and_other_centre_links_are_not_found(centre, other):
    token = share_token(centre)
    assert browser(other["host"]).get(f"/api/public/bills/{token}").status_code == 404  # another centre's address
    assert browser(centre["host"]).get("/api/public/bills/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404

    new = centre["owner"].post(f"/api/bills/{centre['bill']['id']}/share", params={"replace": "true"}).json()
    p = browser(centre["host"])
    assert p.get(f"/api/public/bills/{token}").status_code == 404  # replaced
    new_token = new["url"].rsplit("/", 1)[-1]

    with scoped_session(platform=True) as db, db.begin():
        db.execute(text("UPDATE invoice_shares SET expires_at = now() - interval '1 minute' WHERE revoked_at IS NULL"))
    assert p.get(f"/api/public/bills/{new_token}").status_code == 404  # expired
    with scoped_session(platform=True) as db, db.begin():
        db.execute(text("UPDATE invoice_shares SET expires_at = now() + interval '1 day'"))
    assert p.get(f"/api/public/bills/{new_token}").status_code == 200

    centre["owner"].delete(f"/api/bills/{centre['bill']['id']}/share")
    assert p.get(f"/api/public/bills/{new_token}").status_code == 404  # revoked
