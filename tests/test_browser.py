"""Browser checks of the main journeys in Microsoft Edge (Playwright). Needs the web app built (cd web && npm run build).
Skipped when the build or Edge isn't available."""

import os
import threading
import time
from pathlib import Path

import pytest

from tests.conftest import make_user

playwright = pytest.importorskip("playwright.sync_api")
PORT = 8765
DIST = Path(__file__).resolve().parent.parent / "web" / "dist" / "index.html"


@pytest.fixture(scope="module")
def live_server():
    if not DIST.exists():
        pytest.skip("web app not built")
    import uvicorn

    from app.main import app
    server = uvicorn.Server(uvicorn.Config(app, port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"localhost:{PORT}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def edge():
    # BROWSER_CHANNEL: msedge (the default, as installed on Windows) or chromium (Playwright's own, used in CI).
    channel = os.environ.get("BROWSER_CHANNEL", "msedge")
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel=None if channel == "chromium" else channel)
        except Exception as exc:  # that browser isn't installed
            pytest.skip(f"Browser {channel} not available: {exc}")
        yield browser
        browser.close()


@pytest.fixture
def page(edge, live_server):
    context = edge.new_context()
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.errors = errors
    yield page
    context.close()


def test_first_sign_in_forces_a_new_password_then_opens_the_dashboard(page, alpha, live_server):
    make_user(alpha, "owner@alpha.in", ["owner"], must_change=True)
    page.goto(f"http://alpha.{live_server}/staff")
    page.wait_for_url("**/login?next=%2Fstaff")
    assert page.get_by_role("heading", name="Welcome back").is_visible()
    assert page.get_by_text("Sign in to Alpha Diagnostics").is_visible()

    page.get_by_label("Email").fill("owner@alpha.in")
    page.get_by_label("Password", exact=True).fill("wrong-password")
    page.get_by_role("button", name="Sign in").click()
    toast = page.locator(".toast.is-error")
    toast.wait_for()
    assert "Sign-in failed" in toast.inner_text() and "don't match" in toast.inner_text()

    page.get_by_label("Password", exact=True).fill("Test-password-1")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/change-password")
    page.locator("#current").fill("Test-password-1")
    page.locator("#next").fill("My-own-pass-2026")
    page.locator("#confirm").fill("My-own-pass-2026")
    page.get_by_role("button", name="Save password").click()
    page.wait_for_url(f"http://alpha.{live_server}/")
    assert page.get_by_role("heading", name="Good", exact=False).is_visible()
    assert page.errors == []


def test_owner_adds_a_receptionist(page, alpha, live_server):
    make_user(alpha, "owner@alpha.in", ["owner"])
    page.goto(f"http://alpha.{live_server}/login")
    page.get_by_label("Email").fill("owner@alpha.in")
    page.get_by_label("Password", exact=True).fill("Test-password-1")
    page.get_by_role("button", name="Sign in").click()
    page.get_by_role("button", name="Account menu", exact=False).click()
    page.get_by_role("link", name="Settings").click()
    page.get_by_role("link", name="Staff and roles").click()
    page.get_by_role("button", name="Add a person").click()
    dialog = page.get_by_role("dialog", name="Add a person")
    dialog.get_by_label("Full name").fill("Piu Koley")
    dialog.get_by_label("Email").fill("piu@alpha.in")
    dialog.get_by_label("Receptionist").check()
    dialog.page.get_by_role("button", name="Add person").click()
    row = page.get_by_role("row", name="Piu Koley")
    row.wait_for()
    assert "Temporary password" in row.inner_text()
    assert page.errors == []


def test_a_screen_that_crashes_shows_a_fallback_and_reports_it(page, alpha, live_server):
    make_user(alpha, "owner@alpha.in", ["owner"])
    reports: list[str] = []
    page.on("request", lambda r: reports.append(r.post_data or "") if r.url.endswith("/api/client-errors") else None)
    page.goto(f"http://alpha.{live_server}/login")
    page.get_by_label("Email").fill("owner@alpha.in")
    page.get_by_label("Password", exact=True).fill("Test-password-1")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"http://alpha.{live_server}/")
    # The server sends something the screen can't draw (roles missing): the error boundary takes over.
    page.route("**/api/staff?*", lambda route: route.fulfill(json={"items": [{"id": "1", "full_name": "X", "email": "x", "mobile": "",
                                                                             "is_active": True, "must_change_password": False,
                                                                             "last_login_at": None, "created_at": "2026-01-01T00:00:00Z",
                                                                             "roles": [None]}], "total": 1, "page": 1, "size": 25}))
    page.goto(f"http://alpha.{live_server}/settings/staff")
    page.get_by_role("heading", name="This screen ran into a problem").wait_for()
    assert page.get_by_role("link", name="Bills", exact=True).is_visible()  # the rest of the app still works
    page.wait_for_timeout(300)
    assert any('"kind":"boundary"' in r for r in reports)
    page.get_by_role("link", name="Bills", exact=True).click()
    page.get_by_role("heading", name="Bills").wait_for()


def test_an_ended_session_returns_to_sign_in(page, alpha, live_server):
    make_user(alpha, "owner@alpha.in", ["owner"])
    page.goto(f"http://alpha.{live_server}/login")
    page.get_by_label("Email").fill("owner@alpha.in")
    page.get_by_label("Password", exact=True).fill("Test-password-1")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"http://alpha.{live_server}/")
    page.wait_for_load_state("networkidle")  # the dashboard has finished loading
    page.context.clear_cookies()  # as if signed out elsewhere or timed out
    page.get_by_role("link", name="Bills", exact=True).click()
    page.wait_for_url("**/login?next=%2Fbills")
    cookie_js = page.evaluate("document.cookie")
    assert "sdms_session" not in cookie_js  # HttpOnly: never visible to scripts


def test_the_dashboard_asks_the_server_once(page, alpha, live_server):
    """Nothing on the dashboard (or the session behind it) asks the server again and again (the top loader flickered)."""
    make_user(alpha, "owner@alpha.in", ["owner"])
    page.goto(f"http://alpha.{live_server}/login")
    page.get_by_label("Email").fill("owner@alpha.in")
    page.get_by_label("Password", exact=True).fill("Test-password-1")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"http://alpha.{live_server}/")
    asked: dict[str, int] = {}
    page.on("request", lambda r: asked.update({r.url.split("?")[0]: asked.get(r.url.split("?")[0], 0) + 1}))
    page.wait_for_timeout(3000)
    assert all(n <= 1 for n in asked.values()), asked


def test_screens_and_payments_work_offline_from_encrypted_saved_copies(page, alpha, live_server):
    from tests.conftest import browser
    make_user(alpha, "owner@alpha.in", ["owner"])
    api = browser("alpha.localhost")
    api.login("owner@alpha.in")
    dept = api.post("/api/departments", json={"name": "Pathology"}).json()["id"]
    test = api.post("/api/tests", json={"name": "CBC", "department_id": dept, "price": "300"}).json()["id"]
    bill = api.post("/api/bills", json={"patient": {"name": "Tapasi Mondal", "age_years": 40, "gender": "female", "mobile": "9000011111",
                                                    "address": "Hooghly"}, "lines": [{"test_id": test}]}).json()

    page.goto(f"http://alpha.{live_server}/login")
    page.get_by_label("Email").fill("owner@alpha.in")
    page.get_by_label("Password", exact=True).fill("Test-password-1")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"http://alpha.{live_server}/")
    page.goto(f"http://alpha.{live_server}/bills")                     # opened once while online: saved
    page.get_by_text(bill["invoice_no"]).first.wait_for()
    page.goto(f"http://alpha.{live_server}/bills/{bill['id']}")
    page.get_by_role("heading", name=bill["invoice_no"]).wait_for()
    page.wait_for_timeout(500)

    page.context.set_offline(True)
    page.get_by_role("link", name="Bills", exact=True).first.click()  # within the app: from the saved copy
    page.get_by_text(bill["invoice_no"]).first.wait_for()
    assert page.locator(".offline-banner").is_visible()
    page.go_back()
    page.get_by_role("heading", name=bill["invoice_no"]).wait_for()

    # A payment taken offline waits on this computer.
    page.get_by_role("button", name="Collect", exact=False).first.click()
    page.get_by_role("button", name="Receive", exact=False).click()
    page.get_by_text("Payment saved offline").wait_for()

    # What's kept is encrypted: no patient name anywhere in the saved copies, the catalogue copy or the waiting payment.
    raw = page.evaluate("""() => new Promise((ok) => {
        const r = indexedDB.open("cidms-offline");
        r.onsuccess = () => {
          const tx = r.result.transaction(["responses", "outbox", "cache", "bills"]);
          const out = [];
          const dump = (v) => JSON.stringify(v, (k, x) => x instanceof ArrayBuffer ? new TextDecoder().decode(x) : x);
          tx.objectStore("responses").getAll().onsuccess = (e) => out.push(...e.target.result.map(dump));
          tx.objectStore("outbox").getAll().onsuccess = (e) => out.push(...e.target.result.map(dump));
          tx.objectStore("cache").getAll().onsuccess = (e) => out.push(...e.target.result.map(dump));
          tx.objectStore("bills").getAll().onsuccess = (e) => out.push(...e.target.result.map(dump));
          tx.oncomplete = () => ok(out);
        };
    })""")
    assert len(raw) >= 3 and not any("Tapasi" in r or "Mondal" in r for r in raw)

    # Back online: the payment is sent by itself, once.
    page.context.set_offline(False)
    for _ in range(40):
        if api.get(f"/api/bills/{bill['id']}").json()["paid"] in ("300.00", "300"):
            break
        page.wait_for_timeout(500)
    saved = api.get(f"/api/bills/{bill['id']}").json()
    assert saved["paid"] in ("300.00", "300") and len([p for p in saved["payments"] if p["kind"] == "payment"]) == 1


def test_new_bill_waits_for_a_test_caps_the_payment_and_clears_its_draft(page, alpha, live_server):
    from tests.conftest import browser
    make_user(alpha, "owner@alpha.in", ["owner"])
    api = browser("alpha.localhost")
    api.login("owner@alpha.in")
    d = api.post("/api/departments", json={"name": "Pathology"}).json()["id"]
    api.post("/api/tests", json={"name": "CBC", "department_id": d, "price": "250"})
    page.goto(f"http://alpha.{live_server}/login")
    page.get_by_label("Email").fill("owner@alpha.in")
    page.get_by_label("Password", exact=True).fill("Test-password-1")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"http://alpha.{live_server}/")
    page.goto(f"http://alpha.{live_server}/bills/new")

    def add_cbc():
        page.locator("#nb-test").click()
        page.locator("#nb-test").fill("CBC")
        page.get_by_role("option", name="CBC", exact=False).first.click()
        page.keyboard.press("Escape")

    # Nothing in the summary works until a test is on the bill.
    assert page.locator("#pay-now").is_disabled() and page.locator("#pay-mode").is_disabled()
    assert page.get_by_role("button", name="Save bill").is_disabled()
    add_cbc()
    assert page.locator("#pay-now").is_enabled()

    # Paid now can't be more than the bill: an error at once, and the bill isn't saved until it's put right.
    page.locator("#pay-now").fill("900")
    assert "more than the total" in page.locator("#pay-now-error").inner_text()
    assert page.locator("#pay-now").get_attribute("aria-invalid") == "true"
    page.locator("#pay-now").fill("250")
    assert page.locator("#pay-now-error").count() == 0

    # The draft is kept, and can be cleared.
    page.get_by_text("Draft saved on this computer").wait_for()
    page.get_by_role("button", name="Clear draft").first.click()
    page.get_by_role("dialog").get_by_role("button", name="Clear draft").click()
    page.get_by_text("Draft cleared.").wait_for()
    assert page.locator("#pay-now").is_disabled() and page.get_by_text("Draft saved on this computer").count() == 0

    # Saving the bill removes its draft: New bill opens empty afterwards.
    add_cbc()
    page.get_by_role("button", name="New patient", exact=False).first.click()
    page.locator("#np-name").fill("Rina Das")
    page.locator("#np-age_years").fill("33")
    page.locator("#np-gender").select_option("female")
    page.get_by_role("button", name="Save bill").click()
    page.get_by_text("Bill saved").wait_for()
    page.goto(f"http://alpha.{live_server}/bills/new")
    page.locator("#nb-test").wait_for()
    assert page.get_by_text("Your unsaved bill is back").count() == 0
    assert page.get_by_text("Draft saved on this computer").count() == 0
    assert page.errors == []
