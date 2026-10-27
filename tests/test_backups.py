"""Backups on the platform owner's schedule: time of day, how often, how long kept, and "Back up now"."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.db import scoped_session
from app.models import BackupSettings
from app.services import backups
from tests.conftest import PASSWORD, browser, make_user

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


def _backup_on_disk(tmp_path, monkeypatch) -> str:
    """A finished backup whose .dump and .sql.gz are in a backup folder the app can read."""
    import gzip
    monkeypatch.setattr(backups, "backup_dir", lambda: tmp_path)
    (tmp_path / "supreme-2026-10-12-2300.dump").write_bytes(b"PGDMP fake")
    with gzip.open(tmp_path / "supreme-2026-10-12-2300.sql.gz", "wb") as f:
        f.write(b"-- PostgreSQL database dump\nSELECT 1;\n")
    with scoped_session(platform=True) as db, db.begin():
        run, _ = backups.start(db, now=_at(12, 23), force=True)
        backups.finish(db, run.id, True, "backups/supreme-2026-10-12-2300.dump", 10)
        return str(run.id)


def test_the_owner_downloads_a_backup_as_dump_or_sql(tmp_path, monkeypatch):
    run_id = _backup_on_disk(tmp_path, monkeypatch)
    make_user(None, "boss@platform.in", ["platform_owner"])
    c = browser("admin.localhost")
    c.login("boss@platform.in")
    row = c.get("/api/platform/backups").json()["runs"][0]
    assert row["dump"] and row["sql"]
    dump = c.get(f"/api/platform/backups/{run_id}/download")
    assert dump.status_code == 200 and dump.content == b"PGDMP fake"
    assert "supreme-2026-10-12-2300.dump" in dump.headers["content-disposition"]
    sql = c.get(f"/api/platform/backups/{run_id}/download?format=sql")
    assert sql.status_code == 200 and sql.text.startswith("-- PostgreSQL database dump")
    assert 'filename="supreme-2026-10-12-2300.sql"' in sql.headers["content-disposition"]
    (tmp_path / "supreme-2026-10-12-2300.sql.gz").unlink()
    assert c.get(f"/api/platform/backups/{run_id}/download?format=sql").status_code == 404


def test_a_restore_is_asked_for_called_off_and_carried_out(tmp_path, monkeypatch):
    run_id = _backup_on_disk(tmp_path, monkeypatch)
    make_user(None, "boss@platform.in", ["platform_owner"])
    c = browser("admin.localhost")
    c.login("boss@platform.in")
    assert c.post(f"/api/platform/backups/{run_id}/restore", json={"confirm": "restore"}).status_code == 422
    asked = c.post(f"/api/platform/backups/{run_id}/restore", json={"confirm": "RESTORE", "password": PASSWORD})
    assert asked.status_code == 200 and asked.json()["restore"]["status"] == "requested", asked.text
    assert c.post(f"/api/platform/backups/{run_id}/restore", json={"confirm": "RESTORE", "password": PASSWORD}).status_code == 409
    assert c.post("/api/platform/backups/run").status_code == 409          # no backup while a restore waits
    assert c.delete("/api/platform/backups/restore").json()["restore"] is None
    c.post(f"/api/platform/backups/{run_id}/restore", json={"confirm": "RESTORE", "password": PASSWORD})

    # what deploy/restore.sh does, around putting the copy back
    with scoped_session(platform=True) as db, db.begin():
        run = backups.restore_start(db)
        assert run.status == "running" and run.file.endswith("2300.dump")
        assert backups.restore_start(db) is None                           # once
        backups.record(db, "backups/supreme-2026-10-13-1000-before-restore.dump", 20, "Taken just before restoring")
        import json
        saved = json.loads(json.dumps(backups.history_save(db), default=str))
        restore_id = run.id
    with scoped_session(platform=True) as db, db.begin():                  # as if the copy had no history at all
        db.execute(backups.delete(backups.BackupRun))
    with scoped_session(platform=True) as db, db.begin():
        backups.history_load(db, saved)
        backups.finish(db, restore_id, True, "backups/supreme-2026-10-12-2300.dump", message="Restored.")
    assert c.get("/api/platform/backups").status_code == 401               # everyone signs in again
    c.login("boss@platform.in")
    o = c.get("/api/platform/backups").json()
    assert o["restore"] is None
    assert {r["trigger"] for r in o["runs"]} == {"manual", "restore"} and len(o["runs"]) == 3


def test_a_backup_whose_file_is_gone_cant_be_restored(tmp_path, monkeypatch):
    run_id = _backup_on_disk(tmp_path, monkeypatch)
    (tmp_path / "supreme-2026-10-12-2300.dump").unlink()
    make_user(None, "boss@platform.in", ["platform_owner"])
    c = browser("admin.localhost")
    c.login("boss@platform.in")
    assert c.post(f"/api/platform/backups/{run_id}/restore", json={"confirm": "RESTORE", "password": PASSWORD}).status_code == 422
    assert c.get(f"/api/platform/backups/{run_id}/download").status_code == 404
