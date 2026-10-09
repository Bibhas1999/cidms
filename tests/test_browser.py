"""Browser checks of the main journeys in Microsoft Edge (Playwright). Needs the web app built (cd web && npm run build).
Skipped when the build or Edge isn't available."""

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
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception as exc:  # Edge not installed
            pytest.skip(f"Microsoft Edge not available: {exc}")
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
    page.locator("#new").fill("My-own-pass-2026")
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
