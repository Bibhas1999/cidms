"""Test reports: writing, signing, amending, versions and conflicts, permissions, separation between centres,
HTML cleaning, images (with a stand-in image server), the DICOMweb proxy, the patient's link (QR) and WhatsApp."""

import hashlib
import hmac
import io
import json
import re
from datetime import timedelta

import httpx
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from sqlalchemy import text

from app.core import orthanc as orthanc_module
from app.core.config import get_settings
from app.core.db import scoped_session
from app.services import report_links
from app.services import whatsapp as whatsapp_module
from tests.conftest import browser, make_user

# ---------- a stand-in Orthanc ----------------------------------------------------------------


def dicom_bytes(study_uid: str, series_uid: str | None = None, modality: str = "CR") -> bytes:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset("x.dcm", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientID, ds.PatientName, ds.Modality = "P1", "Test^Patient", modality
    ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID = study_uid, series_uid or generate_uid(), meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.StudyDescription = "CHEST PA"
    ds.Rows, ds.Columns, ds.BitsAllocated, ds.BitsStored, ds.HighBit = 2, 2, 8, 8, 7
    ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PixelRepresentation = 1, "MONOCHROME2", 0
    ds.PixelData = b"\0\1\2\3"
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


class FakeOrthanc:
    def __init__(self):
        self.instances: dict[str, dict] = {}   # instance id -> {study, series, modality}
        self.studies: dict[str, dict] = {}     # orthanc study id -> {uid, labels, description}
        self.dicomweb_calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if method == "POST" and path == "/instances":
            from pydicom import dcmread
            try:
                ds = dcmread(io.BytesIO(request.content))
                uid, sop = str(ds.StudyInstanceUID), str(ds.SOPInstanceUID)
            except Exception:
                return httpx.Response(400, json={"Message": "Bad file format"})
            sid = "s-" + hashlib.sha1(uid.encode(), usedforsecurity=False).hexdigest()[:12]
            iid = "i-" + hashlib.sha1(sop.encode(), usedforsecurity=False).hexdigest()[:12]
            self.studies.setdefault(sid, {"uid": uid, "labels": [], "description": str(ds.get("StudyDescription", ""))})
            already = iid in self.instances
            self.instances[iid] = {"study": sid, "series": str(ds.SeriesInstanceUID), "modality": str(ds.Modality)}
            return httpx.Response(200, json={"ID": iid, "ParentStudy": sid, "Status": "AlreadyStored" if already else "Success"})
        m = re.fullmatch(r"/studies/([^/]+)(/.*)?", path)
        if m and m.group(1) in self.studies:
            sid, rest, st = m.group(1), m.group(2) or "", self.studies[m.group(1)]
            inst = [i for i in self.instances.values() if i["study"] == sid]
            series = sorted({i["series"] for i in inst})
            if rest == "":
                return httpx.Response(200, json={"MainDicomTags": {"StudyInstanceUID": st["uid"], "StudyDescription": st["description"]},
                                                 "Series": series, "Labels": st["labels"]})
            if rest == "/statistics":
                return httpx.Response(200, json={"CountSeries": len(series), "CountInstances": len(inst), "DiskSize": str(100 * len(inst))})
            if rest == "/series":
                return httpx.Response(200, json=[{"MainDicomTags": {"Modality": next(i["modality"] for i in inst if i["series"] == s)}}
                                                 for s in series])
            if rest.startswith("/labels/") and method == "PUT":
                st["labels"].append(rest.split("/")[-1])
                return httpx.Response(200, json={})
        if method == "DELETE" and path.startswith("/instances/"):
            self.instances.pop(path.split("/")[-1], None)
            return httpx.Response(200, json={})
        if path.startswith("/dicom-web/"):
            self.dicomweb_calls.append(path)
            if path == "/dicom-web/studies":
                return httpx.Response(200, json=[{"0020000D": {"vr": "UI", "Value": [s["uid"]]}} for s in self.studies.values()],
                                      headers={"content-type": "application/dicom+json"})
            if path.endswith("/metadata"):
                body = [{"7FE00010": {"vr": "OB", "BulkDataURI": "http://127.0.0.1:8042/dicom-web/studies/1/series/2/instances/3/bulk/7FE00010"}}]
                return httpx.Response(200, json=body, headers={"content-type": "application/dicom+json"})
            if "/frames/" in path:
                return httpx.Response(200, content=b"--frame-bytes--", headers={"content-type": "multipart/related; type=application/octet-stream"})
            return httpx.Response(200, json=[], headers={"content-type": "application/dicom+json"})
        if path == "/system":
            return httpx.Response(200, json={"Version": "fake"})
        return httpx.Response(404, json={})


@pytest.fixture
def fake_orthanc(monkeypatch):
    fake = FakeOrthanc()
    monkeypatch.setattr(orthanc_module, "transport", httpx.MockTransport(fake.handler))
    return fake


# ---------- a centre with a bill ------------------------------------------------------------------

PATIENT = {"name": "Ramen Kumar Dey", "age_years": 61, "gender": "male", "mobile": "9000012345", "address": "Janai"}


def _centre(tenant, slug: str) -> dict:
    make_user(tenant, f"owner@{slug}.in", ["owner"])
    make_user(tenant, f"doc@{slug}.in", ["doctor"])
    make_user(tenant, f"front@{slug}.in", ["receptionist"])
    make_user(tenant, f"tech@{slug}.in", ["technician"])
    host = f"{slug}.localhost"
    people = {}
    for who in ("owner", "doc", "front", "tech"):
        people[who] = browser(host)
        assert people[who].login(f"{who}@{slug}.in").status_code == 200
    owner = people["owner"]
    dept = owner.post("/api/departments", json={"name": "Radiology"}).json()["id"]
    kind = owner.post("/api/test-types", json={"name": "X-ray", "is_imaging": True}).json()["id"]
    test = owner.post("/api/tests", json={"name": "Chest X-ray PA", "department_id": dept, "test_type_id": kind, "price": "350"}).json()["id"]
    bill = people["front"].post("/api/bills", json={"patient": PATIENT, "lines": [{"test_id": test}]}).json()
    return {**people, "host": host, "test_id": test, "bill": bill, "item_id": bill["items"][0]["id"], "tenant": tenant}


@pytest.fixture
def centre(alpha):
    return _centre(alpha, "alpha")


@pytest.fixture
def other(beta):
    return _centre(beta, "beta")


def url(item_id: str, action: str = "") -> str:
    return f"/api/test-reports/for-item/{item_id}" + (f"/{action}" if action else "")


def signature(c) -> None:
    r = c["doc"].put("/api/test-reports/my-signature", json={"display_name": "Dr. A. Sen", "degree": "MBBS, MD (Radiology)",
                                                              "registration_no": "WBMC 12345"})
    assert r.status_code == 200, r.text


def signed_report(c) -> dict:
    doc, item = c["doc"], c["item_id"]
    rep = doc.post(url(item), json={}).json()["report"]
    rep = doc.put(url(item), json={"version": rep["version"], "title": "X-ray chest PA", "findings": "<p>Lungs are clear.</p>",
                                   "impression": "<p>Normal study.</p>"}).json()["report"]
    signature(c)
    r = doc.post(url(item, "sign"), json={"version": rep["version"]})
    assert r.status_code == 200, r.text
    return r.json()["report"]


# ---------- writing, signing, amending ---------------------------------------------------------------

def test_a_report_is_written_finalised_signed_and_amended_with_every_version_kept(centre):
    doc, item = centre["doc"], centre["item_id"]
    w = doc.post(url(item), json={}).json()
    assert w["report"]["status"] == "draft" and w["report"]["version"] == 1 and w["report"]["title"] == "Chest X-ray PA"
    saved = doc.put(url(item), json={"version": 1, "title": "Chest PA", "technique": "Digital radiograph",
                                      "findings": "<p>Both <b>lung</b> fields are clear.</p>", "impression": "<p>No abnormality.</p>"}).json()
    assert saved["report"]["version"] == 2 and saved["report"]["findings"] == "<p>Both <b>lung</b> fields are clear.</p>"
    # An autosave with nothing changed doesn't add a version.
    same = doc.put(url(item), json={"version": 2, "title": "Chest PA", "technique": "Digital radiograph",
                                     "findings": "<p>Both <b>lung</b> fields are clear.</p>", "impression": "<p>No abnormality.</p>"}).json()
    assert same["report"]["version"] == 2
    final = doc.post(url(item, "finalise"), json={"version": 2}).json()
    assert final["report"]["status"] == "final"

    no_profile = doc.post(url(item, "sign"), json={"version": 3})
    assert no_profile.status_code == 422 and no_profile.json()["field"] == "signature"
    signature(centre)
    signed = doc.post(url(item, "sign"), json={"version": 3}).json()
    assert signed["report"]["status"] == "signed" and signed["report"]["signer_name"] == "Dr. A. Sen"
    assert signed["item"]["status"] == "reported"
    # A signed report isn't edited; it is amended, with a reason.
    assert doc.put(url(item), json={"version": 4, "findings": "<p>x</p>"}).status_code == 409
    assert doc.post(url(item, "amend"), json={"version": 4, "findings": "<p>x</p>", "reason": ""}).status_code == 422
    amended = doc.post(url(item, "amend"), json={"version": 4, "title": "Chest PA", "findings": "<p>Small left effusion.</p>",
                                                  "impression": "<p>Left pleural effusion.</p>", "reason": "Effusion missed"}).json()
    assert amended["report"]["status"] == "amended" and amended["report"]["amendments"] == 1
    assert [v["action"] for v in amended["versions"]] == ["amended", "signed", "finalised", "saved", "created"]
    first = doc.get(url(item, "versions/2")).json()
    assert first["findings"] == "<p>Both <b>lung</b> fields are clear.</p>"
    with scoped_session(platform=True) as db:
        actions = set(db.execute(text("SELECT action FROM activity_log WHERE entity IN ('test_report', 'invoice_item')")).scalars())
    assert {"report.created", "report.saved", "report.finalised", "report.signed", "report.amended", "test.reported"} <= actions


def test_saving_over_someone_elses_newer_version_is_refused(centre):
    doc, owner, item = centre["doc"], centre["owner"], centre["item_id"]
    doc.post(url(item), json={})
    assert owner.put(url(item), json={"version": 1, "findings": "<p>Owner's words</p>"}).status_code == 200
    late = doc.put(url(item), json={"version": 1, "findings": "<p>Doctor's words</p>"})
    assert late.status_code == 409 and late.json()["field"] == "version" and "Owner" in late.json()["message"]
    assert doc.post(url(item, "finalise"), json={"version": 1}).status_code == 409


def test_report_html_is_cleaned_before_saving(centre):
    doc, item = centre["doc"], centre["item_id"]
    doc.post(url(item), json={})
    dirty = ('<p onclick="steal()">Normal <script>alert(1)</script><img src=x onerror=alert(1)>'
             '<a href="javascript:alert(1)">link</a><span style="color:red">text</span></p><h2>Head</h2><ul><li>one</li></ul>')
    r = doc.put(url(item), json={"version": 1, "findings": dirty, "impression": "<iframe src='https://evil'></iframe>"}).json()["report"]
    assert r["findings"] == "<p>Normal linktext</p><h2>Head</h2><ul><li>one</li></ul>"
    assert r["impression"] == ""


def test_who_may_write_sign_and_see_reports(centre):
    item = centre["item_id"]
    assert centre["front"].post(url(item), json={}).status_code == 403
    assert centre["tech"].post(url(item), json={}).status_code == 403
    rep = centre["doc"].post(url(item), json={}).json()["report"]
    # Others in the centre don't see drafts...
    assert centre["front"].get(url(item)).json()["report"] is None
    assert centre["front"].get("/api/test-reports", params={"status": "draft"}).json()["total"] == 0
    assert centre["front"].get(url(item, "versions/1")).status_code == 403
    assert centre["front"].get("/api/test-reports/my-signature").status_code == 403
    assert centre["front"].post("/api/test-reports/templates", json={"name": "Chest"}).status_code == 403
    # ...but do see (and print) a signed one.
    centre["doc"].put(url(item), json={"version": rep["version"], "findings": "<p>Clear.</p>"})
    signature(centre)
    centre["doc"].post(url(item, "sign"), json={"version": 2})
    seen = centre["front"].get(url(item)).json()
    assert seen["report"]["status"] == "signed" and seen["versions"] == []
    assert centre["front"].get(url(item, "print")).json()["signer"]["registration_no"] == "WBMC 12345"


def test_the_reporting_worklist_tabs(centre):
    doc, item = centre["doc"], centre["item_id"]
    pending = doc.get("/api/test-reports", params={"status": "pending"}).json()
    assert pending["total"] == 1 and pending["items"][0]["report_id"] is None
    doc.post(url(item), json={})
    assert doc.get("/api/test-reports", params={"status": "pending"}).json()["total"] == 0
    assert doc.get("/api/test-reports", params={"status": "draft", "search": "ramen"}).json()["total"] == 1


def test_templates_fill_a_new_report(centre):
    owner, doc, item = centre["owner"], centre["doc"], centre["item_id"]
    t = owner.post("/api/test-reports/templates", json={"name": "Normal chest", "test_id": centre["test_id"], "title": "Chest PA view",
                                                        "findings": "<p>Lungs clear.<script>x</script></p>", "impression": "<p>Normal.</p>"})
    assert t.status_code == 201 and t.json()["findings"] == "<p>Lungs clear.</p>" and t.json()["test_name"] == "Chest X-ray PA"
    listed = doc.get("/api/test-reports/templates", params={"test_id": centre["test_id"], "active": True}).json()
    assert [x["name"] for x in listed] == ["Normal chest"]
    rep = doc.post(url(item), json={"template_id": t.json()["id"]}).json()["report"]
    assert rep["title"] == "Chest PA view" and rep["findings"] == "<p>Lungs clear.</p>"
    assert owner.post("/api/test-reports/templates", json={"name": "normal CHEST"}).status_code == 422
    assert owner.delete(f"/api/test-reports/templates/{t.json()['id']}").status_code == 204


def test_legacy_reports_are_imported(centre):
    from app.services.report_import import import_legacy_reports
    with scoped_session(platform=True) as db, db.begin():
        db.execute(text("UPDATE invoice_items SET legacy_report = :r WHERE id = :i"),
                   {"r": json.dumps({"study": "Lungs clear\nHeart normal", "impression": "NAD", "tech": "Dr. Old", "reg_no": "123"}),
                    "i": centre["item_id"]})
    from sqlalchemy import create_engine
    with create_engine(get_settings().migration_database_url).begin() as conn:
        assert import_legacy_reports(conn) == 1
        assert import_legacy_reports(conn) == 0  # only once
    rep = centre["doc"].get(url(centre["item_id"])).json()["report"]
    assert rep["imported"] and rep["status"] == "signed" and rep["findings"] == "<p>Lungs clear</p><p>Heart normal</p>"


# ---------- separation between centres -------------------------------------------------------------

def test_another_centre_cannot_see_or_touch_a_report(centre, other):
    signed_report(centre)
    item = centre["item_id"]
    for c in (other["doc"], other["owner"]):
        assert c.get(url(item)).status_code == 404
        assert c.put(url(item), json={"version": 3, "findings": "<p>x</p>"}).status_code == 404
        assert c.get(url(item, "print")).status_code == 404
        assert c.get("/api/test-reports", params={"status": "signed"}).json()["total"] == 0
    with scoped_session(other["tenant"].id) as db:
        assert db.execute(text("SELECT count(*) FROM test_reports")).scalar() == 0
        assert db.execute(text("SELECT count(*) FROM test_report_versions")).scalar() == 0


def test_saved_versions_cannot_be_rewritten(centre):
    signed_report(centre)
    with scoped_session(centre["tenant"].id) as db, pytest.raises(Exception, match="permission denied"):
        db.execute(text("UPDATE test_report_versions SET findings = 'x'"))
        db.flush()


# ---------- images ---------------------------------------------------------------------------------

def upload(c, item_id, files):
    return c.post(f"/api/imaging/items/{item_id}/upload", files=[("files", (n, d, "application/octet-stream")) for n, d in files])


def test_dicom_upload_records_the_study_and_marks_the_scan_done(centre, fake_orthanc):
    uid = generate_uid()
    series = generate_uid()
    archive = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("IMG/0002.dcm", dicom_bytes(uid, series))
        z.writestr("__MACOSX/._x", b"junk")
    r = upload(centre["tech"], centre["item_id"], [("a.dcm", dicom_bytes(uid, series)), ("b.zip", archive.getvalue()), ("note.txt", b"hello")])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["stored"] == 2 and out["rejected"] == 1 and len(out["studies"]) == 1
    study = out["studies"][0]
    assert study["study_instance_uid"] == uid and study["instance_count"] == 2 and study["modality"] == "CR"
    assert study["viewer_url"] == f"/viewer/viewer?StudyInstanceUIDs={uid}"
    label = f"tenant_{centre['tenant'].id.hex}"
    assert label in next(iter(fake_orthanc.studies.values()))["labels"]
    w = centre["doc"].get(url(centre["item_id"])).json()
    assert w["item"]["status"] == "scanned" and len(w["studies"]) == 1
    assert centre["front"].post(f"/api/imaging/items/{centre['item_id']}/upload", files=[("files", ("a.dcm", b"x"))]).status_code == 403


def test_a_study_held_by_another_centre_is_refused(centre, other, fake_orthanc):
    uid = generate_uid()
    assert len(upload(centre["tech"], centre["item_id"], [("a.dcm", dicom_bytes(uid))]).json()["studies"]) == 1
    before = len(fake_orthanc.instances)
    theirs = upload(other["tech"], other["item_id"], [("b.dcm", dicom_bytes(uid))]).json()
    assert theirs["studies"] == [] and "another centre" in theirs["messages"][0]
    assert len(fake_orthanc.instances) == before  # their new file was taken back off the image server
    assert other["doc"].get(f"/api/imaging/items/{centre['item_id']}/studies").status_code == 404


def test_dicomweb_proxy_serves_only_the_centres_own_studies(centre, other, fake_orthanc):
    mine, theirs = generate_uid(), generate_uid()
    upload(centre["tech"], centre["item_id"], [("a.dcm", dicom_bytes(mine))])
    upload(other["tech"], other["item_id"], [("b.dcm", dicom_bytes(theirs))])
    c = centre["doc"]
    found = c.get("/api/dicom-web/studies").json()
    assert [s["0020000D"]["Value"][0] for s in found] == [mine]  # the other centre's study is filtered out
    meta = c.get(f"/api/dicom-web/studies/{mine}/series/1/metadata")
    assert meta.status_code == 200
    assert meta.json()[0]["7FE00010"]["BulkDataURI"].startswith("http://alpha.localhost/api/dicom-web/studies/")
    frame = c.get(f"/api/dicom-web/studies/{mine}/series/1/instances/2/frames/1")
    assert frame.status_code == 200 and frame.content == b"--frame-bytes--"
    calls = len(fake_orthanc.dicomweb_calls)
    assert c.get(f"/api/dicom-web/studies/{theirs}/series").status_code == 404
    assert c.get(f"/api/dicom-web/studies/{theirs}/series/1/instances/2/frames/1").status_code == 404
    assert c.get("/api/dicom-web/system").status_code == 404                       # only DICOMweb paths are passed on
    assert c.get("/api/dicom-web/studies/..%2F..%2Fsystem/series").status_code == 404
    assert c.post(f"/api/dicom-web/studies/{mine}/series").status_code == 405       # reads only
    assert len(fake_orthanc.dicomweb_calls) == calls  # never even asked the image server
    assert browser("alpha.localhost").get(f"/api/dicom-web/studies/{mine}/series").status_code == 401


def test_viewer_needs_a_session(centre):
    r = browser("alpha.localhost").get("/viewer/viewer?StudyInstanceUIDs=1.2", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


# ---------- the patient's link (QR code) ---------------------------------------------------------

def public(c):
    return browser(c["host"])


def share_token(c, report_id: str) -> str:
    share = c["doc"].get(f"/api/test-reports/{report_id}/share").json()
    assert share["active"]
    return share["url"].rsplit("/", 1)[-1]


def test_signing_issues_a_patient_link_that_opens_with_the_mobile_digits(centre):
    rep = signed_report(centre)
    token = share_token(centre, rep["id"])
    assert centre["doc"].get(url(centre["item_id"], "print")).json()["public_url"] == f"http://alpha.localhost/r/{token}"
    with scoped_session(centre["tenant"].id) as db:
        stored = db.execute(text("SELECT token_hash FROM report_shares")).scalar()
    assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in stored

    p = public(centre)
    info = p.get(f"/api/public/reports/{token}")
    assert info.json() == {"centre_name": "Alpha Diagnostics", "has_logo": False, "check": "mobile"}
    wrong = p.post(f"/api/public/reports/{token}/open", json={"check": "0000"})
    assert wrong.status_code == 403 and "match" in wrong.json()["message"]
    ok = p.post(f"/api/public/reports/{token}/open", json={"check": "2345"})
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "no-store" and "noindex" in ok.headers["x-robots-tag"]
    assert ok.headers["referrer-policy"] == "no-referrer"
    body = ok.json()
    assert body["report"]["findings"] == "<p>Lungs are clear.</p>" and body["report"]["signer"]["name"] == "Dr. A. Sen"
    pdf = p.get(body["pdf_url"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["cache-control"] == "no-store"
    assert p.get(f"/api/public/reports/{token}/pdf?grant=1.abc").status_code == 403
    with scoped_session(platform=True) as db:
        logged = list(db.execute(text("SELECT action FROM activity_log WHERE action LIKE 'report.public%'")).scalars())
    assert sorted(logged) == ["report.public_check_failed", "report.public_downloaded", "report.public_viewed"]
    assert centre["doc"].get(f"/api/test-reports/{rep['id']}/share").json()["views"] == 1


def test_wrong_checks_lock_the_link(centre):
    rep = signed_report(centre)
    token = share_token(centre, rep["id"])
    p = public(centre)
    for _ in range(report_links.MAX_FAILED):
        assert p.post(f"/api/public/reports/{token}/open", json={"check": "1111"}).status_code == 403
    assert p.post(f"/api/public/reports/{token}/open", json={"check": "2345"}).status_code == 429


def test_revoked_expired_unknown_and_other_centre_links_are_not_found(centre, other):
    rep = signed_report(centre)
    token = share_token(centre, rep["id"])
    assert public(other).get(f"/api/public/reports/{token}").status_code == 404           # another centre's address
    assert public(other).post(f"/api/public/reports/{token}/open", json={"check": "2345"}).status_code == 404
    assert public(centre).get("/api/public/reports/AAAAAAAAAAAAAAAAAAAAAA").status_code == 404
    assert centre["front"].post(f"/api/test-reports/{rep['id']}/share").status_code == 403  # issuing needs reports.write
    new = centre["doc"].post(f"/api/test-reports/{rep['id']}/share").json()
    assert public(centre).get(f"/api/public/reports/{token}").status_code == 404           # replaced
    new_token = new["url"].rsplit("/", 1)[-1]
    with scoped_session(platform=True) as db, db.begin():
        db.execute(text("UPDATE report_shares SET expires_at = now() - interval '1 minute' WHERE revoked_at IS NULL"))
    assert public(centre).get(f"/api/public/reports/{new_token}").status_code == 404       # expired
    with scoped_session(platform=True) as db, db.begin():
        db.execute(text("UPDATE report_shares SET expires_at = now() + interval '1 day'"))
    assert public(centre).get(f"/api/public/reports/{new_token}").status_code == 200
    centre["doc"].delete(f"/api/test-reports/{rep['id']}/share")
    assert public(centre).get(f"/api/public/reports/{new_token}").status_code == 404       # revoked


def test_amending_keeps_the_link_and_shows_the_amendment(centre):
    rep = signed_report(centre)
    token = share_token(centre, rep["id"])
    centre["doc"].post(url(centre["item_id"], "amend"), json={"version": rep["version"], "findings": "<p>Revised.</p>", "reason": "Typo fixed"})
    assert share_token(centre, rep["id"]) == token
    body = public(centre).post(f"/api/public/reports/{token}/open", json={"check": "2345"}).json()
    assert body["report"]["findings"] == "<p>Revised.</p>" and body["report"]["amended"]


def test_pdf_download(centre):
    rep = signed_report(centre)
    r = centre["front"].get(f"/api/test-reports/{rep['id']}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")


# ---------- WhatsApp ---------------------------------------------------------------------------------

class FakeMeta:
    def __init__(self, fail_send: bool = False):
        self.fail_send = fail_send
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer test-token"
        if request.url.path.endswith("/media"):
            assert b"application/pdf" in request.content and b"%PDF" in request.content
            return httpx.Response(200, json={"id": "media-1"})
        if request.url.path.endswith("/messages"):
            if self.fail_send:
                return httpx.Response(400, json={"error": {"message": "Template name does not exist", "code": 132001}})
            return httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})
        return httpx.Response(404)


@pytest.fixture
def whatsapp_on(monkeypatch):
    s = get_settings()
    for k, v in {"whatsapp_provider": "meta", "whatsapp_token": "test-token", "whatsapp_phone_number_id": "123",
                 "whatsapp_app_secret": "app-secret", "whatsapp_verify_token": "verify-me"}.items():
        monkeypatch.setattr(s, k, v)
    meta = FakeMeta()
    monkeypatch.setattr(whatsapp_module, "transport", httpx.MockTransport(meta.handler))
    return meta


def test_sending_a_signed_report_on_whatsapp(centre, whatsapp_on):
    rep = signed_report(centre)
    r = centre["doc"].post(f"/api/test-reports/{rep['id']}/whatsapp", json={})
    assert r.status_code == 200, r.text
    d = r.json()["deliveries"][0]
    assert d["status"] == "sent" and d["to"] == "+919000012345"
    sent = json.loads(whatsapp_on.requests[-1].content)
    assert sent["to"] == "919000012345" and sent["template"]["components"][0]["parameters"][0]["document"]["id"] == "media-1"
    body = [p["text"] for p in sent["template"]["components"][1]["parameters"]]
    assert body[0] == "Ramen Kumar Dey" and body[2].startswith("http://alpha.localhost/r/")

    # Meta reports delivery and reading to the webhook.
    payload = json.dumps({"entry": [{"changes": [{"value": {"statuses": [
        {"id": "wamid.ABC", "status": "delivered", "timestamp": "1760000000"}, {"id": "wamid.ABC", "status": "read", "timestamp": "1760000100"}]}}]}]}).encode()
    hook = browser("alpha.localhost")
    assert hook.post("/api/webhooks/whatsapp", content=payload, headers={"X-Hub-Signature-256": "sha256=bad"}).status_code == 403
    sig = "sha256=" + hmac.new(b"app-secret", payload, hashlib.sha256).hexdigest()
    assert hook.post("/api/webhooks/whatsapp", content=payload, headers={"X-Hub-Signature-256": sig}).json() == {"updated": 2}
    assert centre["doc"].get(f"/api/test-reports/{rep['id']}/whatsapp").json()["deliveries"][0]["status"] == "read"
    assert hook.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                       "hub.challenge": "42"}).text == "42"
    assert hook.get("/api/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "42"}).status_code == 403


def test_a_failed_whatsapp_send_is_recorded(centre, whatsapp_on):
    whatsapp_on.fail_send = True
    rep = signed_report(centre)
    d = centre["doc"].post(f"/api/test-reports/{rep['id']}/whatsapp", json={"to": "+91 98765 43210"}).json()["deliveries"][0]
    assert d["status"] == "failed" and "132001" in d["error"] and d["to"] == "+919876543210"
    bad = centre["doc"].post(f"/api/test-reports/{rep['id']}/whatsapp", json={"to": "12345"})
    assert bad.status_code == 422 and bad.json()["field"] == "to"


def test_whatsapp_not_set_up_offers_a_manual_link(centre):
    rep = signed_report(centre)
    info = centre["doc"].get(f"/api/test-reports/{rep['id']}/whatsapp").json()
    assert info["configured"] is False and info["default_to"] == "+919000012345"
    assert info["wa_link"] == "https://wa.me/919000012345?text=Alpha%20Diagnostics%3A%20your%20report%20is%20ready."
    assert centre["doc"].post(f"/api/test-reports/{rep['id']}/whatsapp", json={}).status_code == 409


def test_whatsapp_permissions_and_separation(centre, other, whatsapp_on):
    rep = signed_report(centre)
    assert centre["front"].post(f"/api/test-reports/{rep['id']}/whatsapp", json={}).status_code == 403
    assert other["doc"].post(f"/api/test-reports/{rep['id']}/whatsapp", json={}).status_code == 404
    assert other["doc"].get(f"/api/test-reports/{rep['id']}/whatsapp").status_code == 404
    assert whatsapp_on.requests == []


def test_whatsapp_needs_a_signed_report(centre, whatsapp_on):
    rep = centre["doc"].post(url(centre["item_id"]), json={}).json()["report"]
    assert centre["doc"].post(f"/api/test-reports/{rep['id']}/whatsapp", json={}).status_code == 409


def test_link_lifetime_setting(centre, monkeypatch):
    monkeypatch.setattr(get_settings(), "report_link_days", 7)
    rep = signed_report(centre)
    share = centre["doc"].get(f"/api/test-reports/{rep['id']}/share").json()
    from datetime import datetime
    life = datetime.fromisoformat(share["expires_at"]) - datetime.fromisoformat(share["created_at"])
    assert abs(life - timedelta(days=7)) < timedelta(seconds=5)




# ---------- the reporting dashboard ------------------------------------------------------------------

def test_reporting_dashboard_counts_work_and_turnaround(centre, other):
    s = centre["doc"].get("/api/test-reports/summary").json()
    assert s["kpis"]["waiting"] == 1 and s["kpis"]["signed"] == 0 and s["kpis"]["avg_turnaround_hours"] is None
    assert s["oldest_waiting"][0]["state"] == "on_time" and s["oldest_waiting"][0]["target_hours"] == 24
    rep = centre["doc"].post(url(centre["item_id"]), json={}).json()["report"]
    assert centre["doc"].get("/api/test-reports/summary").json()["my_drafts"][0]["item_id"] == centre["item_id"]
    centre["doc"].put(url(centre["item_id"]), json={"version": rep["version"], "findings": "<p>Clear.</p>"})
    centre["doc"].post(url(centre["item_id"], "finalise"), json={"version": 2})
    assert centre["doc"].get("/api/test-reports/summary").json()["kpis"]["ready_to_sign"] == 1
    signature(centre)
    centre["doc"].post(url(centre["item_id"], "sign"), json={"version": 3})
    s = centre["doc"].get("/api/test-reports/summary").json()
    k = s["kpis"]
    assert k["waiting"] == 0 and k["signed"] == 1 and k["avg_turnaround_hours"] is not None and k["p90_turnaround_hours"] is not None
    assert s["by_doctor"][0]["name"] == "Dr. A. Sen" and s["by_department"][0]["name"] == "Radiology"
    assert s["recently_signed"][0]["item_id"] == centre["item_id"] and len(s["trend"]) == 1
    # Another centre's dashboard counts only its own work; people who don't report can't see it.
    o = other["doc"].get("/api/test-reports/summary").json()
    assert o["kpis"]["signed"] == 0 and o["kpis"]["waiting"] == 1 and o["recently_signed"] == []
    assert centre["front"].get("/api/test-reports/summary").status_code == 403


def test_overdue_after_the_target(centre):
    with scoped_session(platform=True) as db, db.begin():
        db.execute(text("UPDATE invoices SET created_at = now() - interval '30 hours'"))
    s = centre["doc"].get("/api/test-reports/summary").json()
    assert s["kpis"]["overdue"] == 1 and s["oldest_waiting"][0]["state"] == "overdue"


# ---------- a report uploaded as a PDF ---------------------------------------------------------------

def pdf_bytes(pages: int = 2) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for n in range(pages):
        c.drawString(72, 720, f"Outside lab report, page {n + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def send_pdf(centre: dict, content: bytes, name: str = "lab-report.pdf") -> str:
    c = centre["doc"]
    up = c.post("/api/uploads", json={"filename": name, "size": len(content), "purpose": "report_pdf"})
    assert up.status_code == 201, up.text
    up = up.json()
    step = up["chunk_size"]
    for start in range(0, len(content), step):
        end = min(start + step, len(content)) - 1
        r = c.put(f"/api/uploads/{up['id']}", content=content[start:end + 1],
                  headers={"Content-Range": f"bytes {start}-{end}/{len(content)}", "Content-Type": "application/octet-stream"})
        assert r.status_code == 200, r.text
    return up["id"]


def test_a_report_can_be_an_uploaded_pdf_signed_and_shared_with_a_cover_page(centre):
    from pypdf import PdfReader
    doc, item = centre["doc"], centre["item_id"]
    # Attaching starts the report when there isn't one yet.
    w = doc.post(url(item, "attachment"), json={"upload_id": send_pdf(centre, pdf_bytes(2))})
    assert w.status_code == 200, w.text
    rep = w.json()["report"]
    assert rep["attachment_name"] == "lab-report.pdf" and rep["attachment_pages"] == 2 and rep["status"] == "draft"
    assert w.json()["versions"][0]["action"] == "attached"
    raw = doc.get(url(item, "attachment"))
    assert raw.status_code == 200 and raw.content.startswith(b"%PDF")
    # No typed findings are needed to sign it.
    signature(centre)
    signed = doc.post(url(item, "sign"), json={"version": rep["version"]})
    assert signed.status_code == 200, signed.text
    report_id = signed.json()["report"]["id"]
    pdf = doc.get(f"/api/test-reports/{report_id}/pdf")
    assert pdf.status_code == 200
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) >= 3  # the signed cover page, then both uploaded pages
    # Replacing the PDF of a signed report is an amendment, with a reason.
    version = signed.json()["report"]["version"]
    assert doc.post(url(item, "attachment"), json={"upload_id": send_pdf(centre, pdf_bytes(1)), "version": version}).status_code == 422
    r = doc.post(url(item, "attachment"), json={"upload_id": send_pdf(centre, pdf_bytes(1)), "version": version, "reason": "Corrected value"})
    assert r.status_code == 200 and r.json()["report"]["status"] == "amended" and r.json()["report"]["attachment_pages"] == 1
    assert doc.delete(url(item, "attachment"), params={"version": r.json()["report"]["version"]}).status_code == 409


def test_only_real_pdfs_are_attached_by_those_who_may_write_reports(centre):
    doc, front, item = centre["doc"], centre["front"], centre["item_id"]
    r = doc.post(url(item, "attachment"), json={"upload_id": send_pdf(centre, b"%PDF-1.4 not really", "x.pdf")})
    assert r.status_code == 422 and "couldn't be read" in r.json()["message"]
    assert doc.post("/api/uploads", json={"filename": "x.docx", "size": 10, "purpose": "report_pdf"}).status_code == 422
    assert front.post("/api/uploads", json={"filename": "x.pdf", "size": 10, "purpose": "report_pdf"}).status_code == 403
    with scoped_session(platform=True) as db:  # kept in the database, not on disk
        assert db.execute(text("SELECT count(*) FROM uploads")).scalar() >= 1
