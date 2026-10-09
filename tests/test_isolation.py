"""One client can never see or change another client's data: checked through the API and in the database itself."""

from sqlalchemy import select, text

from app.core.db import scoped_session
from app.models import ActivityLog, TenantSettings, User
from tests.conftest import browser, make_user


def test_a_session_only_works_at_its_own_address(alpha, beta):
    make_user(alpha, "owner@alpha.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    for host in ("beta.localhost", "admin.localhost", "localhost"):
        other = browser(host)
        other.cookies.update(dict(c.cookies))
        assert other.get("/api/auth/me").status_code == 401, host


def test_staff_lists_and_changes_stay_inside_the_client(alpha, beta):
    make_user(alpha, "owner@alpha.in", ["owner"])
    beta_person = make_user(beta, "owner@beta.in", ["owner"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    emails = [s["email"] for s in c.get("/api/staff", params={"active": "true"}).json()["items"]]
    assert emails == ["owner@alpha.in"]
    assert c.patch(f"/api/staff/{beta_person.id}", json={"full_name": "Taken over"}).status_code == 404
    assert c.post(f"/api/staff/{beta_person.id}/reset-password", json={"temporary_password": "Hijack-pass-123"}).status_code == 404


def test_the_same_email_can_work_at_two_clients(alpha, beta):
    make_user(alpha, "doctor@gmail.com", ["doctor"])
    make_user(beta, "doctor@gmail.com", ["doctor"], password="Beta-password-2")
    assert browser("alpha.localhost").login("doctor@gmail.com").status_code == 200
    assert browser("beta.localhost").login("doctor@gmail.com", "Beta-password-2").status_code == 200
    assert browser("beta.localhost").login("doctor@gmail.com").status_code == 401  # alpha's password doesn't open beta


def test_row_level_security_hides_other_clients_rows_in_the_database(alpha, beta):
    make_user(alpha, "a@alpha.in", ["owner"])
    make_user(beta, "b@beta.in", ["owner"])
    with scoped_session(alpha.id) as db:
        assert db.scalars(select(User.email)).all() == ["a@alpha.in"]
        assert [s.tenant_id for s in db.scalars(select(TenantSettings))] == [alpha.id]
    with scoped_session() as db:  # no client at all: sees no client rows
        assert db.scalars(select(User.email)).all() == []


def test_row_level_security_refuses_writes_into_another_client(alpha, beta):
    with scoped_session(alpha.id) as db:
        db.add(User(tenant_id=beta.id, email="spy@beta.in", full_name="Spy", password_hash="x"))
        try:
            db.flush()
            raise AssertionError("insert into another client should fail")
        except Exception as exc:  # psycopg InsufficientPrivilege wrapped by SQLAlchemy
            assert "row-level security" in str(exc)
        db.rollback()


def test_the_client_scope_does_not_leak_to_the_next_transaction(alpha):
    make_user(alpha, "a@alpha.in", ["owner"])
    with scoped_session(alpha.id) as db:
        db.execute(text("SELECT 1"))
        db.commit()
        db.info["tenant_id"] = None  # same session, next transaction, no client
        assert db.scalars(select(User.email)).all() == []


def test_the_app_cannot_rewrite_the_activity_log(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    browser("alpha.localhost").login("owner@alpha.in")
    with scoped_session(alpha.id) as db:
        try:
            db.execute(text("UPDATE activity_log SET action = 'nothing'"))
            raise AssertionError("activity log should be append-only")
        except Exception as exc:
            assert "permission denied" in str(exc)
        db.rollback()
        assert db.scalar(select(ActivityLog.action)) == "user.sign_in"
