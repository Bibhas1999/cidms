"""Background jobs (queue, worker, scheduler) and notifications (service, API, live stream)."""

import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update

from app.api import notifications as notif_api
from app.core import jobs
from app.core.db import scoped_session
from app.models import Job, JobFile, JobSchedule, Notification, utcnow
from app.services import events
from app.services import notifications as svc
from app.worker import SCHEDULES, Schedule, Worker, tick
from tests.conftest import _owner_connection, browser, make_tenant, make_user

calls: list[dict] = []


@jobs.job("test.flaky", max_attempts=3)
def _flaky(ctx: jobs.JobContext):
    calls.append(ctx.payload)
    if ctx.attempt < ctx.payload.get("succeed_on", 99):
        raise RuntimeError(f"boom on attempt {ctx.attempt}")
    return {"attempt": ctx.attempt}


@jobs.job("test.permanent")
def _permanent(ctx: jobs.JobContext):
    raise jobs.PermanentError("bad payload")


@jobs.job("test.slow", max_attempts=1)
def _slow(ctx: jobs.JobContext):
    ctx.db.execute(text("SELECT pg_sleep(0.3)"))
    return {"ok": True}


@pytest.fixture(autouse=True)
def _clean_jobs():
    with _owner_connection() as conn:
        conn.execute(text("TRUNCATE jobs, job_files, job_schedules, job_workers, notifications, notification_preferences CASCADE"))
        conn.commit()
    calls.clear()
    yield


def _enqueue(tenant_id, kind="ping", payload=None, **kw) -> uuid.UUID:
    with scoped_session(tenant_id, platform=tenant_id is None) as db:
        jid = jobs.enqueue(db, kind, payload or {}, tenant_id=tenant_id, **kw)
        db.commit()
    return jid


def _job(jid) -> Job:
    with scoped_session(platform=True) as db:
        return db.get(Job, jid)


def _make_due(jid):
    with scoped_session(platform=True) as db:
        db.execute(update(Job).where(Job.id == jid).values(run_at=utcnow() - timedelta(seconds=1)))
        db.commit()


# ---------- the queue ----------

def test_enqueue_claim_and_run(alpha):
    jid = _enqueue(alpha.id, "ping")
    assert _job(jid).status == "queued"
    assert jobs.run_one("w1") == (jid, "done")
    j = _job(jid)
    assert j.status == "done" and j.attempts == 1 and j.result["pong"] is True and j.finished_at and j.locked_by is None
    assert jobs.run_one("w1") is None


def test_unknown_kind_is_refused(alpha):
    with scoped_session(alpha.id) as db, pytest.raises(ValueError):
        jobs.enqueue(db, "no.such.kind", {})


def test_retry_with_backoff_then_fail(alpha):
    jid = _enqueue(alpha.id, "test.flaky", {"succeed_on": 99})
    before = utcnow()
    assert jobs.run_one("w1") == (jid, "queued")
    j = _job(jid)
    assert j.attempts == 1 and "boom on attempt 1" in j.last_error and j.locked_by is None
    assert before + timedelta(seconds=14) < j.run_at < utcnow() + timedelta(seconds=16)  # first retry after 15 s
    assert jobs.run_one("w1") is None  # not due yet
    _make_due(jid)
    assert jobs.run_one("w1") == (jid, "queued")
    assert _job(jid).run_at > utcnow() + timedelta(seconds=25)  # then 30 s
    _make_due(jid)
    assert jobs.run_one("w1") == (jid, "failed")
    j = _job(jid)
    assert j.status == "failed" and j.attempts == 3 and j.finished_at is not None
    assert [jobs.backoff(n).total_seconds() for n in (1, 2, 3, 4)] == [15, 30, 60, 120]
    assert jobs.backoff(30) == timedelta(seconds=jobs.BACKOFF_MAX_S)


def test_retry_succeeds(alpha):
    jid = _enqueue(alpha.id, "test.flaky", {"succeed_on": 2})
    jobs.run_one("w1")
    _make_due(jid)
    assert jobs.run_one("w1") == (jid, "done")
    assert _job(jid).result == {"attempt": 2}


def test_permanent_error_fails_at_once(alpha):
    jid = _enqueue(alpha.id, "test.permanent")
    assert jobs.run_one("w1") == (jid, "failed")
    assert "bad payload" in _job(jid).last_error


def test_priority_and_run_at(alpha):
    later = _enqueue(alpha.id, "ping", run_at=utcnow() + timedelta(hours=1))
    low = _enqueue(alpha.id, "ping", priority=0)
    high = _enqueue(alpha.id, "ping", priority=5)
    assert jobs.run_one("w")[0] == high
    assert jobs.run_one("w")[0] == low
    assert jobs.run_one("w") is None
    assert _job(later).status == "queued"


def test_skip_locked_two_workers(alpha):
    first = _enqueue(alpha.id, "ping")
    second = _enqueue(alpha.id, "ping")
    # Worker 1 is in the middle of claiming the first job (row locked, not committed yet) …
    with scoped_session(platform=True) as w1:
        w1.execute(select(Job).where(Job.id == first).with_for_update())
        # … worker 2 doesn't wait for it: it takes the next one.
        c = jobs.claim("w2")
        assert c is not None and c.id == second
        w1.rollback()
    assert jobs.claim("w3").id == first


def test_two_workers_never_take_the_same_job(alpha):
    ids = {_enqueue(alpha.id, "test.slow") for _ in range(6)}
    taken: list[uuid.UUID] = []
    lock = threading.Lock()

    def work(name):
        while (r := jobs.run_one(name)) is not None:
            with lock:
                taken.append(r[0])

    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(taken, key=str) == sorted(ids, key=str)  # every job once, none twice


def test_dedupe_while_live(alpha, beta):
    a = _enqueue(alpha.id, "ping", dedupe_key="k1")
    assert _enqueue(alpha.id, "ping", dedupe_key="k1") == a
    assert _enqueue(beta.id, "ping", dedupe_key="k1") != a        # another client's key is its own
    assert _enqueue(None, "ping", dedupe_key="k1") != a           # and so is the platform's
    assert _enqueue(None, "ping", dedupe_key="k1") == _enqueue(None, "ping", dedupe_key="k1")
    while jobs.run_one("w"):
        pass
    assert _enqueue(alpha.id, "ping", dedupe_key="k1") != a       # finished: a new one can be queued


def test_stale_locks_are_recovered(alpha):
    jid = _enqueue(alpha.id, "test.flaky", {"succeed_on": 1})
    c = jobs.claim("dead-worker")
    assert c.id == jid
    assert jobs.recover_stale(minutes=10) == []                   # still fresh
    with scoped_session(platform=True) as db:
        db.execute(update(Job).where(Job.id == jid).values(locked_at=utcnow() - timedelta(minutes=11)))
        db.commit()
    jobs.touch([jid], "someone-else")                             # only its own worker refreshes it
    assert jobs.recover_stale(minutes=10) == [jid]
    j = _job(jid)
    assert j.status == "queued" and j.locked_by is None and "stopped responding" in j.last_error
    assert jobs.run_one("w2") == (jid, "done") and _job(jid).attempts == 2
    one_try = _enqueue(alpha.id, "ping")                          # out of tries: failed, not retried
    jobs.claim("dead-worker")
    with scoped_session(platform=True) as db:
        db.execute(update(Job).where(Job.id == one_try).values(locked_at=utcnow() - timedelta(minutes=11)))
        db.commit()
    assert jobs.recover_stale(minutes=10) == [one_try] and _job(one_try).status == "failed"


def test_cancel(alpha):
    jid = _enqueue(alpha.id, "ping")
    with scoped_session(alpha.id) as db:
        assert jobs.cancel(db, jid)
        db.commit()
    assert _job(jid).status == "cancelled"
    assert jobs.run_one("w") is None


def test_job_tenant_isolation(alpha, beta):
    a = _enqueue(alpha.id, "ping")
    p = _enqueue(None, "ping")
    with scoped_session(beta.id) as db:
        assert db.get(Job, a) is None and db.get(Job, p) is None
        with pytest.raises(Exception):  # noqa: B017 (row-level security refuses the row)
            jobs.enqueue(db, "ping", {}, tenant_id=alpha.id)
            db.flush()
    with scoped_session(alpha.id) as db:
        assert db.get(Job, a) is not None and db.get(Job, p) is None


def test_worker_runs_jobs_and_heartbeats(alpha):
    jid = _enqueue(alpha.id, "ping")
    w = Worker(concurrency=2, poll_s=0.05, scheduler=False)
    assert w.run(once=True) == 0
    assert _job(jid).status == "done" and w.done == 1
    with scoped_session(platform=True) as db:
        assert db.execute(text("SELECT status, jobs_done FROM job_workers WHERE worker_id = :w"), {"w": w.id}).one() == ("stopped", 1)


# ---------- the scheduler ----------

def test_schedule_next_run_in_ist():
    daily = Schedule("d", "daily_summary", time(21, 0))
    # 15:30 IST -> 21:00 IST the same day (15:30 UTC)
    assert daily.next_after(datetime(2026, 10, 10, 10, 0, tzinfo=UTC)) == datetime(2026, 10, 10, 15, 30, tzinfo=UTC)
    # exactly 21:00 IST -> the next day
    assert daily.next_after(datetime(2026, 10, 10, 15, 30, tzinfo=UTC)) == datetime(2026, 10, 11, 15, 30, tzinfo=UTC)
    # 23:00 UTC on the 10th is 04:30 IST on the 11th
    assert daily.next_after(datetime(2026, 10, 10, 23, 0, tzinfo=UTC)) == datetime(2026, 10, 11, 15, 30, tzinfo=UTC)
    monday = Schedule("w", "dues_digest", time(9, 0), weekday=0)
    # Saturday 10 Oct 2026 -> Monday 12 Oct, 09:00 IST = 03:30 UTC
    assert monday.next_after(datetime(2026, 10, 10, 10, 0, tzinfo=UTC)) == datetime(2026, 10, 12, 3, 30, tzinfo=UTC)
    assert monday.next_after(datetime(2026, 10, 12, 3, 30, tzinfo=UTC)) == datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
    assert {s.name for s in SCHEDULES} >= {"daily_summary", "dues_digest", "cleanup"}


def test_tick_fires_once_per_slot(alpha, beta):
    make_tenant("gamma", status="suspended")
    s = Schedule("daily_summary", "daily_summary", time(21, 0))
    now = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
    assert tick(now, [s]) == {}                                   # first sight: schedules the next 21:00
    at_nine = datetime(2026, 10, 10, 15, 31, tzinfo=UTC)
    assert tick(at_nine, [s]) == {"daily_summary": 2}             # one per active client
    assert tick(at_nine, [s]) == {}                               # taken once only
    with scoped_session(platform=True) as db:
        assert db.get(JobSchedule, "daily_summary").next_run_at == datetime(2026, 10, 11, 15, 30, tzinfo=UTC)
        rows = db.scalars(select(Job).where(Job.kind == "daily_summary")).all()
    assert {r.tenant_id for r in rows} == {alpha.id, beta.id}
    assert all(r.payload["day"] == "2026-10-10" for r in rows)
    cleanup = Schedule("cleanup", "cleanup", time(3, 30), per_tenant=False)
    tick(now, [cleanup])
    assert tick(now + timedelta(days=1), [cleanup]) == {"cleanup": 1}
    assert jobs.run_one("w", ["cleanup"])[1] == "done"


# ---------- notifications ----------

@pytest.fixture
def people(alpha, beta):
    return {
        "owner": make_user(alpha, "owner@alpha.test", ["owner"]),
        "admin": make_user(alpha, "admin@alpha.test", ["admin"]),
        "desk": make_user(alpha, "desk@alpha.test", ["receptionist"]),
        "beta_owner": make_user(beta, "owner@beta.test", ["owner"]),
    }


def _notify(tenant_id, **kw):
    with scoped_session(tenant_id) as db:
        out = svc.notify(db, tenant_id, **{"kind": "test", "title": "Hello", **kw})
        db.commit()
    return out


def test_notify_targets_roles_permissions_and_preferences(alpha, people):
    assert set(_notify(alpha.id, roles=("owner", "admin"))) == {people["owner"].id, people["admin"].id}
    assert set(_notify(alpha.id, permission="billing.create")) == {people["owner"].id, people["admin"].id, people["desk"].id}
    assert _notify(alpha.id, roles=("owner",), exclude=[people["owner"].id]) == []
    assert _notify(alpha.id, user_ids=[people["beta_owner"].id]) == []   # never someone from another client
    with scoped_session(alpha.id) as db:
        svc.save_preferences(db, db.merge(people["admin"]), ["bill.cancelled", "security.password_reset", "nonsense"], True)
        db.commit()
        assert svc.preferences(db, people["admin"].id).muted_kinds == ["bill.cancelled"]   # security alerts can't be muted
    assert set(_notify(alpha.id, kind="bill.cancelled", roles=("owner", "admin"))) == {people["owner"].id}


def test_events_reach_the_right_people(alpha, people):
    inv = type("Inv", (), {"tenant_id": alpha.id, "id": uuid.uuid4(), "invoice_no": "TST/1", "patient_name": "Asha",
                            "total": Decimal("500"), "subtotal": Decimal("1000"), "discount_amount": Decimal("500")})()
    with scoped_session(alpha.id) as db:
        desk = db.merge(people["desk"])
        assert set(events.bill_cancelled(db, inv, desk, "duplicate")) == {people["owner"].id, people["admin"].id}
        assert set(events.discount_over_limit(db, inv, desk, Decimal("20"))) == {people["owner"].id, people["admin"].id}
        assert events.daily_summary(db, alpha.id, {"day": datetime(2026, 10, 10).date(), "bills": 3, "billed": Decimal("900"),
                                                   "collected_total": Decimal("700"), "outstanding_dues": Decimal("200")})
        db.commit()
        n = db.scalar(select(Notification).where(Notification.user_id == people["owner"].id, Notification.kind == "bill.cancelled"))
    assert n.link == f"/bills/{inv.id}" and "duplicate" in n.body and n.severity == "warning"
    assert svc.safe_link("https://evil.example") == "" and svc.safe_link("//evil") == "" and svc.safe_link("/bills/1") == "/bills/1"


def test_notification_api_read_and_isolation(alpha, people):
    _notify(alpha.id, user_ids=[people["owner"].id], title="One")
    _notify(alpha.id, user_ids=[people["owner"].id], title="Two", severity="warning")
    _notify(alpha.id, user_ids=[people["admin"].id], title="For admin")
    owner = browser("alpha.localhost")
    assert owner.login("owner@alpha.test").status_code == 200
    assert owner.get("/api/notifications/unread-count").json() == {"count": 2}
    page = owner.get("/api/notifications").json()
    assert page["total"] == 2 and [i["title"] for i in page["items"]] == ["Two", "One"]
    assert owner.get("/api/notifications", params={"severity": "warning"}).json()["total"] == 1
    with scoped_session(alpha.id) as db:
        admins = db.scalar(select(Notification.id).where(Notification.user_id == people["admin"].id))
    assert owner.post(f"/api/notifications/{admins}/read").status_code == 404   # someone else's
    first = page["items"][0]["id"]
    assert owner.post(f"/api/notifications/{first}/read").json() == {"count": 1}
    assert owner.get("/api/notifications", params={"unread": True}).json()["total"] == 1
    assert owner.post("/api/notifications/read-all").json() == {"count": 0}
    assert owner.get("/api/notifications/unread-count").json() == {"count": 0}
    # Another client sees none of it.
    other = browser("beta.localhost")
    assert other.login("owner@beta.test").status_code == 200
    assert other.get("/api/notifications").json()["total"] == 0
    assert other.post(f"/api/notifications/{first}/read").status_code == 404
    with scoped_session(people["beta_owner"].tenant_id) as db:
        assert db.scalars(select(Notification)).all() == []
    assert browser("alpha.localhost").get("/api/notifications/unread-count").status_code == 401


def test_preferences_api(alpha, people):
    c = browser("alpha.localhost")
    c.login("admin@alpha.test")
    prefs = c.get("/api/notifications/preferences").json()
    kinds = {k["code"]: k for k in prefs["kinds"]}
    assert prefs["browser_popups"] is False and kinds["summary.daily"]["enabled"] and not kinds["security.password_reset"]["can_mute"]
    out = c.put("/api/notifications/preferences", json={"muted_kinds": ["summary.daily"], "browser_popups": True}).json()
    assert out["browser_popups"] is True and not {k["code"]: k for k in out["kinds"]}["summary.daily"]["enabled"]
    assert c.post("/api/notifications/test").json() == {"count": 1}


def test_stream_sends_events(alpha, people, monkeypatch):
    monkeypatch.setattr(notif_api, "MAX_STREAM_S", 1.5)
    monkeypatch.setattr(notif_api, "POLL_S", 0.2)
    monkeypatch.setattr(notif_api, "POLL_LISTENING_S", 0.2)
    _notify(alpha.id, user_ids=[people["owner"].id], title="Before")
    c = browser("alpha.localhost")
    c.login("owner@alpha.test")
    timer = threading.Timer(0.5, lambda: _notify(alpha.id, user_ids=[people["owner"].id], title="Live one"))
    timer.start()
    with c.stream("GET", "/api/notifications/stream") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    timer.join()
    first = body.split("\n\n")[0]
    assert "retry: 5000" in first and "event: unread" in first and '"count":1' in first
    assert "event: notification" in body and "Live one" in body and '"count":2' in body
    assert "Before" not in body.split("event: notification", 1)[1].split("\n\n")[0]
    assert browser("alpha.localhost").get("/api/notifications/stream").status_code == 401


# ---------- job files and exports ----------

def test_export_job_file_and_isolation(alpha, people, monkeypatch):
    import app.services.exports as exports

    def demo(db, current, rows=1):
        assert current.can("billing.create")
        return "Bills ₹.csv", "text/csv", b"a,b\n" * rows

    monkeypatch.setattr(exports, "BACKGROUND_EXPORTS", {"demo": demo}, raising=False)
    with scoped_session(alpha.id) as db:
        jid = jobs.enqueue(db, "export", {"function": "demo", "params": {"rows": 3}}, created_by=people["admin"].id)
        db.commit()
    assert jobs.run_one("w") == (jid, "done")
    admin = browser("alpha.localhost")
    admin.login("admin@alpha.test")
    status = admin.get(f"/api/jobs/{jid}").json()
    assert status["status"] == "done" and status["file_url"] == f"/api/jobs/{jid}/file"
    r = admin.get(f"/api/jobs/{jid}/file")
    assert r.status_code == 200 and r.content == b"a,b\n" * 3 and "attachment" in r.headers["content-disposition"]
    n = admin.get("/api/notifications").json()["items"][0]
    assert n["kind"] == "export.ready" and n["link"] == f"/api/jobs/{jid}/file"
    owner = browser("alpha.localhost")
    owner.login("owner@alpha.test")
    assert owner.get(f"/api/jobs/{jid}/file").status_code == 404              # not their export
    other = browser("beta.localhost")
    other.login("owner@beta.test")
    assert other.get(f"/api/jobs/{jid}").status_code == 404
    with scoped_session(people["beta_owner"].tenant_id) as db:
        assert db.scalars(select(JobFile)).all() == []
    with scoped_session(platform=True) as db:
        db.execute(update(JobFile).values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    assert admin.get(f"/api/jobs/{jid}/file").status_code == 404              # expired after 24 h


def test_unknown_export_fails_and_tells_the_requester(alpha, people):
    with scoped_session(alpha.id) as db:
        jid = jobs.enqueue(db, "export", {"function": "nope"}, created_by=people["admin"].id)
        db.commit()
    assert jobs.run_one("w") == (jid, "failed")
    with scoped_session(alpha.id) as db:
        n = db.scalar(select(Notification).where(Notification.user_id == people["admin"].id))
    assert n.kind == "job.failed" and n.severity == "danger"


def test_daily_summary_and_dues_digest_jobs(alpha, people):
    with scoped_session(alpha.id) as db:
        a = jobs.enqueue(db, "daily_summary", {"day": "2026-10-10"})
        b = jobs.enqueue(db, "dues_digest", {})
        db.commit()
    assert jobs.run_one("w") == (a, "done")
    assert jobs.run_one("w") == (b, "done")
    assert _job(a).result["skipped"] and _job(b).result == {"bills": 0, "sent": 0}   # a quiet day: no noise


def test_a_job_that_fails_for_good_raises_an_alert_once(monkeypatch):
    from app.core import alerts, mailer
    from app.core.config import get_settings
    sent = []
    monkeypatch.setattr(get_settings(), "alert_email", "ops@example.com, owner@example.com")
    monkeypatch.setattr(mailer, "send", lambda to, subject, body: sent.append((to, subject)))
    assert alerts.alert("test-key", "Something broke", "details") is True
    assert sorted(t for t, _ in sent) == ["ops@example.com", "owner@example.com"] and sent[0][1] == "[CIDMS] Something broke"
    assert alerts.alert("test-key", "Something broke", "again") is False  # the same alert: not again for 6 hours
    assert len(sent) == 2


def test_low_disk_space_raises_an_alert(monkeypatch, tmp_path):
    import shutil
    from collections import namedtuple

    from app.core import alerts
    raised = []
    monkeypatch.setattr(alerts, "alert", lambda key, subject, body: raised.append(key) or True)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(100, 95, 5))
    assert alerts.check_disk(str(tmp_path)) == 0.05 and raised == ["disk"]
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(100, 50, 50))
    raised.clear()
    alerts.check_disk(str(tmp_path))
    assert raised == []
