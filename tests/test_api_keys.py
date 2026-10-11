"""API keys and the integration API (/api/v1): managing keys, who may, scopes, revoked / expired / IP-limited
keys, other centres, the rate limit, the call log, and that nothing financial ever comes out."""

import re
import typing
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select, update

import app.schemas_api_v1 as v1_schemas
from app.core.db import scoped_session
from app.main import app
from app.models import ApiKey, ApiRequest, utcnow
from app.services import integrations
from tests.conftest import browser, make_user

FINANCIAL = re.compile(r"price|amount|total|paid|due|discount|refund|payment|rate|fee|revenue|balance", re.IGNORECASE)
ALL_SCOPES = sorted(integrations.SCOPES)
PATIENT = {"name": "Ramen Kumar Dey", "age_years": 61, "gender": "male", "mobile": "9000012345", "address": "Janai"}


@pytest.fixture(autouse=True)
def fresh_limits():
    integrations.rate_limiter.reset()
    integrations.forget_touches()
    yield
    integrations.rate_limiter.limit = integrations.RATE_LIMIT_PER_MINUTE
    integrations.rate_limiter.reset()


def setup_centre(tenant, slug: str) -> dict:
    make_user(tenant, f"owner@{slug}.in", ["owner"])
    make_user(tenant, f"admin@{slug}.in", ["admin"])
    make_user(tenant, f"front@{slug}.in", ["receptionist"])
    host = f"{slug}.localhost"
    owner, front, admin = browser(host), browser(host), browser(host)
    assert owner.login(f"owner@{slug}.in").status_code == 200
    assert front.login(f"front@{slug}.in").status_code == 200
    assert admin.login(f"admin@{slug}.in").status_code == 200
    dept = owner.post("/api/departments", json={"name": "Radiology"}).json()["id"]
    kind = owner.post("/api/test-types", json={"name": "X-ray", "is_imaging": True}).json()["id"]
    test = owner.post("/api/tests", json={"name": "Chest X-ray PA", "department_id": dept, "test_type_id": kind, "price": "1234.56"}).json()["id"]
    bill = front.post("/api/bills", json={"patient": PATIENT, "lines": [{"test_id": test}], "referring_doctor_name": "Dr. K. Roy"})
    assert bill.status_code == 201, bill.text
    return {"owner": owner, "admin": admin, "front": front, "host": host, "bill": bill.json(), "tenant": tenant}


@pytest.fixture
def centre(alpha):
    return setup_centre(alpha, "alpha")


def make_key(c, scopes=None, **kw) -> tuple[str, dict]:
    r = c.post("/api/integrations/keys", json={"name": "Hospital HIS", "scopes": scopes or ALL_SCOPES, **kw})
    assert r.status_code == 201, r.text
    return r.json()["key"], r.json()["api_key"]


def api(host: str, key: str | None = None, header: str = "bearer") -> TestClient:
    c = TestClient(app, base_url=f"http://{host}")
    if key and header == "bearer":
        c.headers["Authorization"] = f"Bearer {key}"
    elif key:
        c.headers["X-API-Key"] = key
    return c


# ---------- managing keys ----------

def test_a_key_is_shown_once_listed_without_its_secret_and_audited(centre):
    owner = centre["owner"]
    key, info = make_key(owner, ["patients:read"], expires_on=(utcnow() + timedelta(days=30)).date().isoformat(),
                         allowed_ips=["203.0.113.7", "10.0.0.0/8"])
    assert re.fullmatch(r"sdms_live_[A-Za-z0-9]{8}_[A-Za-z0-9]{43}", key)
    assert key.startswith(info["prefix"] + "_")
    assert info["status"] == "active" and info["scopes"] == ["patients:read"] and info["allowed_ips"] == ["203.0.113.7/32", "10.0.0.0/8"]
    listed = owner.get("/api/integrations/keys")
    assert listed.status_code == 200
    assert key not in listed.text and key[len(info["prefix"]):] not in listed.text
    assert "secret" not in listed.text and "hash" not in listed.text
    with scoped_session(centre["tenant"].id) as db:
        stored = db.scalar(select(ApiKey))
        assert stored.secret_hash == integrations.key_hash(key) and key not in stored.secret_hash
    activity = owner.get("/api/activity").json()["items"]
    assert any(a["action"] == "api_key.created" for a in activity)
    assert key not in owner.get("/api/activity").text


def test_creating_a_key_checks_what_was_asked(centre):
    owner = centre["owner"]
    assert owner.post("/api/integrations/keys", json={"name": "x", "scopes": []}).status_code == 422
    assert owner.post("/api/integrations/keys", json={"name": "x", "scopes": ["billing:read"]}).status_code == 422
    assert owner.post("/api/integrations/keys", json={"name": "x", "scopes": ["patients:read"], "allowed_ips": ["not-an-ip"]}).status_code == 422
    assert owner.post("/api/integrations/keys", json={"name": "x", "scopes": ["patients:read"], "expires_on": "2020-01-01"}).status_code == 422


def test_only_the_owner_and_centre_admin_manage_keys(centre):
    front = centre["front"]
    assert front.get("/api/integrations/keys").status_code == 403
    assert front.post("/api/integrations/keys", json={"name": "x", "scopes": ["patients:read"]}).status_code == 403
    assert front.get("/api/integrations/usage").status_code == 403
    assert centre["admin"].get("/api/integrations/keys").status_code == 200
    _, info = make_key(centre["admin"])
    assert front.post(f"/api/integrations/keys/{info['id']}/revoke").status_code == 403


def test_revoking_a_key_stops_it(centre):
    owner = centre["owner"]
    key, info = make_key(owner)
    assert api(centre["host"], key).get("/api/v1/patients").status_code == 200
    r = owner.post(f"/api/integrations/keys/{info['id']}/revoke")
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    r = api(centre["host"], key).get("/api/v1/patients")
    assert r.status_code == 401 and "revoked" in r.json()["message"] and r.json()["request_id"]
    assert owner.post(f"/api/integrations/keys/{info['id']}/revoke").status_code == 409
    assert any(a["action"] == "api_key.revoked" for a in owner.get("/api/activity").json()["items"])


def test_rolling_a_key_gives_a_new_one_and_retires_the_old(centre):
    owner = centre["owner"]
    old_key, old = make_key(owner, ["patients:read"])
    r = owner.post(f"/api/integrations/keys/{old['id']}/roll", json={"grace_hours": 0})
    assert r.status_code == 200, r.text
    new_key, new = r.json()["key"], r.json()["api_key"]
    assert new_key != old_key and new["scopes"] == ["patients:read"] and new["name"] == old["name"]
    assert api(centre["host"], old_key).get("/api/v1/patients").status_code == 401
    assert api(centre["host"], new_key).get("/api/v1/patients").status_code == 200

    # With a grace period both work until it ends.
    r = owner.post(f"/api/integrations/keys/{new['id']}/roll", json={"grace_hours": 24})
    newest_key = r.json()["key"]
    assert api(centre["host"], new_key).get("/api/v1/patients").status_code == 200
    assert api(centre["host"], newest_key).get("/api/v1/patients").status_code == 200
    statuses = {k["id"]: k["status"] for k in owner.get("/api/integrations/keys").json()}
    assert statuses[new["id"]] == "rolling" and statuses[old["id"]] == "revoked"
    assert owner.post(f"/api/integrations/keys/{new['id']}/roll", json={}).status_code == 409


# ---------- calling the API ----------

def test_bearer_or_x_api_key_and_no_cookies_or_csrf(centre):
    key, _ = make_key(centre["owner"])
    for header in ("bearer", "x-api-key"):
        r = api(centre["host"], key, header).get("/api/v1/me")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["centre"] == "Alpha Diagnostics" and r.headers["cache-control"] == "no-store"
        assert "set-cookie" not in r.headers
    # A signed-in browser can't use the API without a key.
    owner = centre["owner"]
    assert owner.get("/api/v1/patients").status_code == 401
    assert owner.get("/api/v1/me").status_code == 401
    # Nonsense and unknown keys.
    assert api(centre["host"], "sdms_live_nope").get("/api/v1/me").status_code == 401
    fake = "sdms_live_AAAAAAAA_" + "B" * 43
    r = api(centre["host"], fake).get("/api/v1/me")
    assert r.status_code == 401 and r.json()["message"] == "That API key isn't valid."


def test_scopes_are_enforced(centre):
    key, _ = make_key(centre["owner"], ["patients:read"])
    c = api(centre["host"], key)
    assert c.get("/api/v1/patients").status_code == 200
    for path in ("/api/v1/orders", "/api/v1/reports", "/api/v1/tests", "/api/v1/doctors", "/api/v1/studies"):
        r = c.get(path)
        assert r.status_code == 403, path
        assert "scope" in r.json()["message"]


def test_an_expired_key_is_refused(centre):
    key, info = make_key(centre["owner"])
    with scoped_session(centre["tenant"].id) as db, db.begin():
        db.execute(update(ApiKey).where(ApiKey.prefix == info["prefix"]).values(expires_at=utcnow() - timedelta(minutes=1)))
    r = api(centre["host"], key).get("/api/v1/patients")
    assert r.status_code == 401 and "expired" in r.json()["message"]
    assert centre["owner"].get("/api/integrations/keys").json()[0]["status"] == "expired"


def test_the_ip_allowlist(centre):
    key, _ = make_key(centre["owner"], allowed_ips=["203.0.113.0/24"])
    r = api(centre["host"], key).get("/api/v1/me")  # the test client calls from "testclient", no address
    assert r.status_code == 403
    allowed = api(centre["host"], key)
    allowed.headers["X-Forwarded-For"] = "203.0.113.9"
    assert allowed.get("/api/v1/me").status_code == 200
    other = api(centre["host"], key)
    other.headers["X-Forwarded-For"] = "198.51.100.1"
    assert other.get("/api/v1/me").status_code == 403


def test_a_key_works_only_at_its_own_centre(centre, beta):
    other = setup_centre(beta, "beta")
    key_a, _ = make_key(centre["owner"])
    key_b, _ = make_key(other["owner"])
    for host in ("beta.localhost", "admin.localhost", "localhost", "nobody.localhost"):
        assert api(host, key_a).get("/api/v1/patients").status_code == 401, host
    # Each key sees only its own centre's rows.
    a_orders = api("alpha.localhost", key_a).get("/api/v1/orders").json()["data"]
    b_orders = api("beta.localhost", key_b).get("/api/v1/orders").json()["data"]
    assert {o["bill_id"] for o in a_orders} == {centre["bill"]["id"]}
    assert {o["bill_id"] for o in b_orders} == {other["bill"]["id"]}
    b_patient = b_orders[0]["patient"]["id"]
    assert api("alpha.localhost", key_a).get(f"/api/v1/patients/{b_patient}").status_code == 404
    assert api("alpha.localhost", key_a).get(f"/api/v1/orders/{b_orders[0]['id']}").status_code == 404
    with scoped_session(centre["tenant"].id) as db:
        assert [k.tenant_id for k in db.scalars(select(ApiKey))] == [centre["tenant"].id]


def test_the_rate_limit(centre):
    key, _ = make_key(centre["owner"])
    integrations.rate_limiter.limit = 3
    c = api(centre["host"], key)
    assert [c.get("/api/v1/me").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/api/v1/me")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and r.json()["request_id"]


def test_every_call_is_logged_without_bodies_and_last_used_is_kept(centre):
    owner = centre["owner"]
    key, info = make_key(owner)
    c = api(centre["host"], key)
    c.get("/api/v1/patients", params={"search": "Ramen"})
    c.get("/api/v1/orders")
    usage = owner.get("/api/integrations/usage", params={"key_id": info["id"]}).json()
    assert usage["total"] == 2
    assert {u["path"] for u in usage["items"]} == {"/api/v1/patients", "/api/v1/orders"}
    assert all(u["status"] == 200 and u["key_prefix"] == info["prefix"] for u in usage["items"])
    assert "Ramen" not in owner.get("/api/integrations/usage").text
    listed = owner.get("/api/integrations/keys").json()[0]
    assert listed["last_used_at"] is not None
    with scoped_session(centre["tenant"].id) as db:
        assert db.scalar(select(ApiRequest.method)) == "GET"


# ---------- the data ----------

def test_orders_patients_tests_and_doctors_come_back_with_paging(centre):
    owner, front = centre["owner"], centre["front"]
    test_id = centre["bill"]["items"][0]["test_id"]
    for _ in range(2):
        assert front.post("/api/bills", json={"patient": PATIENT, "lines": [{"test_id": test_id}]}).status_code == 201
    key, _ = make_key(owner)
    c = api(centre["host"], key)
    seen, cursor = [], None
    while True:
        r = c.get("/api/v1/orders", params={"limit": 2, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        seen += r.json()["data"]
        cursor = r.json()["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 3 and len({o["id"] for o in seen}) == 3
    o = seen[0]
    assert o["test"]["name"] == "Chest X-ray PA" and o["department"]["name"] == "Radiology" and o["status"] == "billed"
    assert c.get("/api/v1/orders", params={"status": "reported"}).json()["data"] == []
    assert c.get("/api/v1/orders", params={"status": "paid"}).status_code == 422
    assert c.get("/api/v1/orders", params={"cursor": "garbage!"}).status_code == 422
    assert c.get(f"/api/v1/orders/{o['id']}").json()["data"]["id"] == o["id"]
    patients = c.get("/api/v1/patients", params={"search": "ramen"}).json()["data"]
    assert patients and patients[0]["name"] == "Ramen Kumar Dey"
    tests = c.get("/api/v1/tests").json()["data"]
    assert tests[0]["name"] == "Chest X-ray PA" and tests[0]["modality"] == "X-ray"
    doctors = c.get("/api/v1/doctors").json()["data"]
    assert [d["name"] for d in doctors] == ["Dr. K. Roy"]
    assert c.get("/api/v1/studies").json() == {"data": [], "next_cursor": None}
    assert c.get("/api/v1/reports").json() == {"data": [], "next_cursor": None}


def _model_fields(model: type[BaseModel], seen: set) -> typing.Iterator[tuple[str, str]]:
    if model in seen:
        return
    seen.add(model)
    for name, f in model.model_fields.items():
        yield model.__name__, name
        for t in _types(f.annotation):
            if isinstance(t, type) and issubclass(t, BaseModel):
                yield from _model_fields(t, seen)


def _types(annotation) -> typing.Iterator:
    yield annotation
    for arg in typing.get_args(annotation):
        yield from _types(arg)


def test_no_v1_shape_has_a_financial_field():
    models = [m for m in vars(v1_schemas).values() if isinstance(m, type) and issubclass(m, BaseModel) and m is not BaseModel]
    assert len(models) >= 10
    seen: set = set()
    fields = [pair for m in models for pair in _model_fields(m, seen)]
    bad = [f"{m}.{n}" for m, n in fields if FINANCIAL.search(n)]
    assert bad == []
    # And the published description of the API agrees.
    spec = TestClient(app, base_url="http://alpha.localhost").get("/api/v1/openapi.json").json()
    for name, schema in spec["components"]["schemas"].items():
        for prop in schema.get("properties", {}):
            assert not FINANCIAL.search(prop), f"{name}.{prop}"
    assert "ApiKey" in spec["components"]["securitySchemes"]
    assert all(p.startswith("/") and not p.startswith("/api/") for p in spec["paths"])  # only the v1 routes


def test_no_money_in_actual_answers(centre):
    key, _ = make_key(centre["owner"])
    c = api(centre["host"], key)
    bill = centre["bill"]
    figures = {str(bill[k]) for k in ("total", "subtotal") if k in bill} | {"1234.56", "1234.5"}
    for path in ("/api/v1/orders", "/api/v1/tests", "/api/v1/patients", "/api/v1/doctors", "/api/v1/reports", "/api/v1/studies",
                 f"/api/v1/orders/{bill['items'][0]['id']}"):
        r = c.get(path)
        assert r.status_code == 200, path
        for figure in figures:
            assert figure not in r.text, (path, figure)

        def walk(value, where=path):
            if isinstance(value, dict):
                for k, v in value.items():
                    assert not FINANCIAL.search(k), f"{where}.{k}"
                    walk(v, f"{where}.{k}")
            elif isinstance(value, list):
                for v in value:
                    walk(v, where)
        walk(r.json())


def test_docs_are_served_for_the_v1_api():
    c = TestClient(app, base_url="http://alpha.localhost")
    r = c.get("/api/v1/docs")
    assert r.status_code == 200 and "/api/v1/openapi.json" in r.text
    assert "cdn.jsdelivr.net" in r.headers["content-security-policy"]


def test_signed_reports_their_pdf_and_studies(centre):
    from app.models import ImagingStudy
    make_user(centre["tenant"], "doc@alpha.in", ["doctor"])
    doc = browser(centre["host"])
    assert doc.login("doc@alpha.in").status_code == 200
    item = centre["bill"]["items"][0]["id"]
    base = f"/api/test-reports/for-item/{item}"
    rep = doc.post(base, json={}).json()["report"]
    key, _ = make_key(centre["owner"], ["reports:read", "images:read", "orders:read"])
    c = api(centre["host"], key)
    assert c.get("/api/v1/reports").json()["data"] == []  # drafts never leave the centre
    rep = doc.put(base, json={"version": rep["version"], "title": "X-ray chest PA", "findings": "<p>Lungs are clear.</p>",
                              "impression": "<p>Normal study.</p>"}).json()["report"]
    assert doc.put("/api/test-reports/my-signature", json={"display_name": "Dr. A. Sen", "degree": "MBBS, MD",
                                                            "registration_no": "WBMC 12345"}).status_code == 200
    assert doc.post(f"{base}/sign", json={"version": rep["version"]}).status_code == 200

    reports = c.get("/api/v1/reports", params={"status": "signed"}).json()["data"]
    assert len(reports) == 1
    r = reports[0]
    assert r["order_id"] == item and r["signer"]["name"] == "Dr. A. Sen" and "Lungs are clear" in r["findings_html"]
    assert r["pdf_url"] == f"/api/v1/reports/{r['id']}/pdf"
    assert c.get(f"/api/v1/reports/{r['id']}").json()["data"]["id"] == r["id"]
    assert c.get("/api/v1/reports", params={"status": "draft"}).status_code == 422
    assert c.get(f"/api/v1/orders/{item}").json()["data"]["report_id"] == r["id"]
    pdf = c.get(r["pdf_url"])
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")

    with scoped_session(centre["tenant"].id) as db, db.begin():
        db.add(ImagingStudy(tenant_id=centre["tenant"].id, invoice_item_id=item, study_instance_uid="1.2.3.4", orthanc_study_id="abc",
                            modality="CR", series_count=1, instance_count=2))
    studies = c.get("/api/v1/studies", params={"order_id": item}).json()["data"]
    assert [(s["study_instance_uid"], s["modality"], s["instance_count"]) for s in studies] == [("1.2.3.4", "CR", 2)]
