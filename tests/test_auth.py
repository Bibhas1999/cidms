"""Sign-in, sessions, CSRF, lockout and passwords."""

import bcrypt
from sqlalchemy import select

from app.core.db import scoped_session
from app.models import ActivityLog, User
from tests.conftest import PASSWORD, browser, make_tenant, make_user


def test_sign_in_sets_an_httponly_cookie_and_returns_the_csrf_token(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    r = c.login("Owner@Alpha.in")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "owner@alpha.in" and body["csrf_token"]
    assert "staff.manage" in body["permissions"]
    cookie = r.headers["set-cookie"]
    assert "sdms_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert body["csrf_token"] not in cookie  # the session token and the CSRF token are different secrets
    assert c.get("/api/auth/me").json()["id"] == body["id"]


def test_wrong_password_and_unknown_email_get_the_same_answer(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    wrong = c.login("owner@alpha.in", "nope")
    unknown = c.login("nobody@alpha.in", "nope")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"]


def test_account_locks_after_repeated_wrong_passwords(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    for _ in range(5):
        assert c.login("owner@alpha.in", "wrong").status_code == 401
    r = c.login("owner@alpha.in")  # right password, but locked
    assert r.status_code == 423
    with scoped_session(platform=True) as db:
        actions = db.scalars(select(ActivityLog.action)).all()
    assert actions.count("user.sign_in_failed") == 5


def test_deactivated_people_cannot_sign_in(alpha):
    u = make_user(alpha, "gone@alpha.in", ["receptionist"])
    with scoped_session(platform=True) as db, db.begin():
        db.get(User, u.id).is_active = False
    assert browser("alpha.localhost").login("gone@alpha.in").status_code == 401


def test_changes_need_the_csrf_token_and_the_same_site(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    body = {"legal_name": "Alpha", "invoice_prefix": "ALP"}
    assert c.put("/api/settings", json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert c.put("/api/settings", json=body, headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.put("/api/settings", json=body).status_code == 200


def test_a_temporary_password_must_be_changed_before_anything_else(alpha):
    make_user(alpha, "new@alpha.in", ["owner"], must_change=True)
    c = browser("alpha.localhost")
    assert c.login("new@alpha.in").json()["must_change_password"] is True
    blocked = c.get("/api/staff")
    assert blocked.status_code == 403 and blocked.json()["field"] == "must_change_password"
    assert c.get("/api/auth/me").status_code == 200

    weak = c.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert weak.status_code == 422 and weak.json()["field"] == "new_password"
    same = c.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert same.status_code == 422

    ok = c.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "Brand-new-pass-9"})
    assert ok.status_code == 200 and ok.json()["must_change_password"] is False
    assert c.get("/api/staff").status_code == 200


def test_changing_password_signs_out_other_browsers(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    laptop, phone = browser("alpha.localhost"), browser("alpha.localhost")
    laptop.login("owner@alpha.in")
    phone.login("owner@alpha.in")
    laptop.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "Brand-new-pass-9"})
    assert laptop.get("/api/auth/me").status_code == 200
    assert phone.get("/api/auth/me").status_code == 401


def test_sign_out_ends_the_session_on_the_server(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    stolen = dict(c.cookies)
    assert c.post("/api/auth/logout").status_code == 204
    replay = browser("alpha.localhost")
    replay.cookies.update(stolen)
    assert replay.get("/api/auth/me").status_code == 401


def test_passwords_from_the_old_laravel_app_work_once_then_are_rehashed(alpha):
    legacy = bcrypt.hashpw(b"old-laravel-pass1", bcrypt.gensalt()).decode().replace("$2b$", "$2y$", 1)
    u = make_user(alpha, "piu@alpha.in", ["receptionist"], password_hash=legacy)
    assert browser("alpha.localhost").login("piu@alpha.in", "old-laravel-pass1").status_code == 200
    with scoped_session(platform=True) as db:
        assert db.get(User, u.id).password_hash.startswith("$argon2")


def test_suspended_workspace_cannot_sign_in():
    t = make_tenant("paused", status="suspended")
    make_user(t, "owner@paused.in", ["owner"])
    r = browser("paused.localhost").login("owner@paused.in")
    assert r.status_code == 403 and "suspended" in r.json()["message"]


def test_sign_in_attempts_are_rate_limited_per_ip(alpha):
    c = browser("alpha.localhost")
    codes = [c.login(f"x{i}@alpha.in", "nope").status_code for i in range(21)]
    assert codes[-1] == 429
