"""Each centre's own backups: made on its schedule or when asked, downloaded as Excel, SQL or the copy, restored."""

import gzip
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.core import jobs
from app.core.db import scoped_session
from app.models import ClientBackup, ClientBackupSettings
from app.services import client_backups as cb
from tests.conftest import PASSWORD, browser, make_user
from tests.test_billing import bill, centre  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "_dir", lambda tenant_id: tmp_path / str(tenant_id))
    return tmp_path


def run_jobs() -> None:
    while jobs.run_one("test", ["client_backup", "client_restore"]):
        pass


def back_up(c) -> dict:
    assert c.post("/api/backups/run").status_code == 200
    run_jobs()
    latest = c.get("/api/backups").json()["runs"][0]
    assert latest["status"] == "ok", latest
    return latest


def test_a_copy_is_made_downloaded_and_restored(centre):  # noqa: F811
    owner = centre["owner"]
    assert bill(owner, centre["tests"], ["CBC"]).status_code == 201
    copy = back_up(owner)
    assert copy["counts"]["invoices"] == 1 and copy["counts"]["patients"] == 1 and copy["restorable"]

    # The workbook has the bill; the SQL has its INSERT; the copy is the gzip'd JSON.
    from openpyxl import load_workbook
    xlsx = owner.get(f"/api/backups/{copy['id']}/download?format=xlsx")
    assert xlsx.status_code == 200
    wb = load_workbook(io.BytesIO(xlsx.content))
    assert wb["Bills"].max_row == 2 and wb["Patients"]["B2"].value == "Ramen Kumar Dey"
    assert "Staff" in wb.sheetnames
    sql = owner.get(f"/api/backups/{copy['id']}/download?format=sql").text
    assert sql.startswith("-- CIDMS backup of Alpha Diagnostics") and "INSERT INTO invoices" in sql and sql.rstrip().endswith("COMMIT;")
    raw = json.loads(gzip.decompress(owner.get(f"/api/backups/{copy['id']}/download?format=copy").content))
    assert raw["meta"]["format"] == "cidms-client-backup" and "password_hash" not in json.dumps(raw)

    # After the copy: another bill, and a test renamed. Restoring undoes the rename, but the new bill -
    # made after the copy, and not in it - stays: a restore only puts things back, never removes anything.
    assert bill(owner, centre["tests"], ["Lipid profile"]).status_code == 201
    test_id = centre["tests"]["CBC"]
    owner.patch(f"/api/tests/{test_id}", json={"name": "CBC (renamed)"})
    assert owner.post(f"/api/backups/{copy['id']}/restore", json={"confirm": "yes"}).status_code == 422
    # Their own password again, or nothing happens.
    wrong = owner.post(f"/api/backups/{copy['id']}/restore", json={"confirm": "RESTORE", "password": "not-it-123"})
    assert wrong.status_code == 403 and wrong.json()["field"] == "password"
    assert owner.post(f"/api/backups/{copy['id']}/restore", json={"confirm": "RESTORE"}).status_code == 403
    assert owner.post(f"/api/backups/{copy['id']}/restore", json={"confirm": "RESTORE", "password": PASSWORD}).status_code == 200
    run_jobs()
    assert owner.get("/api/bills").status_code == 401, [r["message"] for r in owner.get("/api/backups").json()["runs"][:2]]  # everyone signs in again
    owner.login("owner@alpha.in")
    assert owner.get("/api/bills").json()["total"] == 2  # the Lipid profile bill, made after the copy, is still there
    tests = {t["id"]: t["name"] for t in owner.get("/api/tests").json()["items"]}
    assert tests[test_id] == "CBC"  # the rename is undone
    runs = owner.get("/api/backups").json()["runs"]
    assert runs[0]["trigger"] == "restore" and runs[0]["status"] == "ok", runs[0]
    assert runs[1]["message"].startswith("The data just before restoring")   # the copy made first
    assert runs[1]["counts"]["invoices"] == 2


def test_only_the_owner_has_backups(centre):  # noqa: F811
    make_user(centre["tenant"], "admin@alpha.in", ["admin"])
    admin = browser("alpha.localhost")
    admin.login("admin@alpha.in")
    assert admin.get("/api/backups").status_code == 403
    assert centre["front"].get("/api/backups").status_code == 403
    assert centre["owner"].get("/api/backups").status_code == 200


def test_a_centre_cannot_reach_another_centres_copies(centre, beta):  # noqa: F811
    copy = back_up(centre["owner"])
    make_user(beta, "owner@beta.in", ["owner"])
    other = browser("beta.localhost")
    other.login("owner@beta.in")
    assert other.get(f"/api/backups/{copy['id']}/download").status_code == 404
    assert other.post(f"/api/backups/{copy['id']}/restore", json={"confirm": "RESTORE", "password": PASSWORD}).status_code == 404
    assert other.get("/api/backups").json()["runs"] == []


def test_the_platform_backs_up_and_restores_any_client(centre):  # noqa: F811
    make_user(None, "boss@platform.in", ["platform_owner"])
    p = browser("admin.localhost")
    p.login("boss@platform.in")
    t = centre["tenant"].id
    assert p.post(f"/api/platform/clients/{t}/backups/run").status_code == 200
    run_jobs()
    copy = p.get(f"/api/platform/clients/{t}/backups").json()["runs"][0]
    assert copy["status"] == "ok"
    assert p.get(f"/api/platform/clients/{t}/backups/{copy['id']}/download?format=sql").status_code == 200
    assert p.post(f"/api/platform/clients/{t}/backups/{copy['id']}/restore", json={"confirm": "RESTORE", "password": PASSWORD}).status_code == 200
    run_jobs()
    assert p.get(f"/api/platform/clients/{t}/backups").json()["runs"][0]["status"] == "ok"


def test_a_copy_from_another_version_is_kept_but_not_restored(centre):  # noqa: F811
    copy = back_up(centre["owner"])
    with scoped_session(platform=True) as db, db.begin():
        db.get(ClientBackup, copy["id"]).schema_version = "0001_foundation"
    row = centre["owner"].get("/api/backups").json()["runs"][0]
    assert row["available"] and not row["restorable"]
    assert centre["owner"].post(f"/api/backups/{copy['id']}/restore", json={"confirm": "RESTORE", "password": PASSWORD}).status_code == 422
    assert centre["owner"].get(f"/api/backups/{copy['id']}/download?format=xlsx").status_code == 200


def test_the_schedule_runs_each_centre_at_its_own_time(centre):  # noqa: F811
    owner = centre["owner"]
    r = owner.put("/api/backups", json={"enabled": True, "every_days": 1, "at_time": "02:15", "keep_days": 0})
    assert r.status_code == 200 and r.json()["settings"]["keep_days"] == 0
    with scoped_session(platform=True) as db, db.begin():
        s = db.scalar(select(ClientBackupSettings).where(ClientBackupSettings.tenant_id == centre["tenant"].id))
        s.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    assert cb.enqueue_due() == 1
    assert cb.enqueue_due() == 0                                 # once per slot
    run_jobs()
    run = owner.get("/api/backups").json()["runs"][0]
    assert run["trigger"] == "scheduled" and run["status"] == "ok"
    with scoped_session(platform=True) as db:
        assert db.scalar(text("SELECT count(*) FROM client_backup_settings WHERE next_run_at > now()")) >= 1
