"""Backups on the platform owner's schedule: time of day, how often, how long kept, and "Back up now"."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.db import scoped_session
from app.models import BackupSettings
from app.services import backups
from tests.conftest import browser, make_user

IST = ZoneInfo("Asia/Kolkata")


def _at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=IST).astimezone(UTC)


def test_next_backup_follows_the_time_and_the_cycle():
    s = BackupSettings(enabled=True, every_days=7, at_time="23:00", keep_days=30)
    # never run: today at 11 pm if that's still ahead, else tomorrow
    assert backups.plan_next(s, _at(12, 18), None) == _at(12, 23)
    assert backups.plan_next(s, _at(12, 23, 30), None) == _at(13, 23)
    # a week after the last one
    assert backups.plan_next(s, _at(13, 9), _at(12, 23)) == _at(19, 23)
    # the server was off past the slot: the next 11 pm, once
    assert backups.plan_next(s, _at(25, 9), _at(12, 23)) == _at(25, 23)
    s.enabled = False
    assert backups.plan_next(s, _at(12, 18), None) is None


def test_the_server_script_runs_what_is_due_once():
    with scoped_session(platform=True) as db, db.begin():
        s = backups._row(db)
        s.every_days, s.at_time, s.next_run_at = 2, "23:00", _at(12, 23)
        assert backups.start(db, now=_at(12, 22, 55)) is None          # not yet
        run, keep = backups.start(db, now=_at(12, 23, 2))
        assert run.trigger == "scheduled" and keep == 30
        assert backups.start(db, now=_at(12, 23, 7)) is None           # one at a time
        backups.finish(db, run.id, True, "backups/supreme-2026-10-12-2300.dump", 1800000)
        assert s.next_run_at == _at(14, 23)                             # every 2 days
        assert backups.start(db, now=_at(13, 23, 2)) is None


def test_owner_sets_the_schedule_and_asks_for_a_backup_now():
    make_user(None, "boss@platform.in", ["platform_owner"])
    c = browser("admin.localhost")
    c.login("boss@platform.in")
    o = c.get("/api/platform/backups").json()
    assert o["settings"]["at_time"] == "23:00" and o["settings"]["every_days"] == 1
    r = c.put("/api/platform/backups", json={"enabled": True, "every_days": 7, "at_time": "21:30", "keep_days": 90})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["every_days"] == 7 and r.json()["settings"]["next_run_at"]
    assert c.put("/api/platform/backups", json={"enabled": True, "every_days": 5, "at_time": "21:30", "keep_days": 90}).status_code == 422
    assert c.put("/api/platform/backups", json={"enabled": True, "every_days": 1, "at_time": "25:00", "keep_days": 30}).status_code == 422
    forever = c.put("/api/platform/backups", json={"enabled": True, "every_days": 7, "at_time": "21:30", "keep_days": 0})
    assert forever.status_code == 200 and forever.json()["settings"]["keep_days"] == 0, forever.text
    assert c.put("/api/platform/backups", json={"enabled": True, "every_days": 7, "at_time": "21:30", "keep_days": 45}).status_code == 422
    assert c.post("/api/platform/backups/run").json()["settings"]["requested_at"]
    with scoped_session(platform=True) as db, db.begin():
        run, _ = backups.start(db, now=datetime.now(UTC))
        assert run.trigger == "manual"
        backups.finish(db, run.id, False, message="disk full")
    runs = c.get("/api/platform/backups").json()["runs"]
    assert runs[0]["status"] == "failed" and runs[0]["message"] == "disk full"


def test_only_the_platform_owner_sees_backups(alpha):
    make_user(None, "help@platform.in", ["platform_support"])
    c = browser("admin.localhost")
    c.login("help@platform.in")
    assert c.get("/api/platform/backups").status_code == 403
    make_user(alpha, "owner@alpha.in", ["owner"])
    front = browser("alpha.localhost")
    front.login("owner@alpha.in")
    assert front.get("/api/platform/backups").status_code in (403, 404)


def test_a_backup_cut_off_mid_way_is_marked_failed():
    with scoped_session(platform=True) as db, db.begin():
        backups._row(db)
        run, _ = backups.start(db, now=_at(12, 10), force=True)
        later, _ = backups.start(db, now=_at(12, 10) + timedelta(hours=4), force=True)
        assert run.status == "failed" and later.status == "running"
