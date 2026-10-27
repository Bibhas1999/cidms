"""Adding many departments, test types, tests and referring doctors at once, from a grid or an Excel sheet sent as a resumable upload."""

import io

import pytest
from openpyxl import Workbook, load_workbook

from tests.conftest import browser, make_user


@pytest.fixture
def owner(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    make_user(alpha, "front@alpha.in", ["receptionist"])
    c = browser("alpha.localhost")
    c.login("owner@alpha.in")
    return c


def xlsx(rows: list[list]) -> bytes:
    book = Workbook()
    for r in rows:
        book.active.append(r)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def upload(c, content: bytes, filename="tests.xlsx", chunk=9):
    """Send a file in small pieces, the way the browser does."""
    r = c.post("/api/uploads", json={"filename": filename, "size": len(content), "purpose": "catalogue"})
    assert r.status_code == 201, r.text
    up = r.json()
    for start in range(0, len(content), chunk):
        end = min(start + chunk, len(content)) - 1
        r = c.put(f"/api/uploads/{up['id']}", content=content[start:end + 1],
                  headers={"Content-Range": f"bytes {start}-{end}/{len(content)}", "Content-Type": "application/octet-stream"})
        assert r.status_code == 200, r.text
    assert r.json()["complete"]
    return up["id"]


def test_several_departments_are_added_at_once_or_none_at_all(owner):
    owner.post("/api/departments", json={"name": "Radiology"})
    r = owner.post("/api/catalogue/departments/bulk", json={"rows": [{"name": "Pathology"}, {"name": "radiology"}, {"name": "pathology "}]})
    assert r.status_code == 422
    fields = {d["field"]: d["message"] for d in r.json()["detail"]}
    assert "rows.1.name" in fields and "already" in fields["rows.1.name"]
    assert fields["rows.2.name"] == "Listed twice (also row 1)."
    assert [d["name"] for d in owner.get("/api/departments").json()] == ["Radiology"]

    r = owner.post("/api/catalogue/departments/bulk", json={"rows": [{"name": "Pathology"}, {"name": "Cardiology"}]})
    assert r.status_code == 201 and r.json() == {"added": 2}
    assert [d["name"] for d in owner.get("/api/departments").json()] == ["Cardiology", "Pathology", "Radiology"]


def test_test_types_take_yes_or_no_for_images(owner):
    r = owner.post("/api/catalogue/test-types/check", json={"rows": [{"name": "CT", "imaging": "yes"}, {"name": "ECG", "imaging": "maybe"}]})
    rows = r.json()["rows"]
    assert rows[0] == {"values": {"name": "CT", "imaging": "Yes"}, "errors": {}}
    assert rows[1]["errors"] == {"imaging": "Write Yes or No."}
    assert owner.post("/api/catalogue/test-types/bulk", json={"rows": [{"name": "CT", "imaging": "Yes"}]}).status_code == 201
    assert owner.get("/api/test-types").json()[0]["is_imaging"] is True


def test_several_doctors_and_hospitals_are_added_with_their_phones_checked(owner):
    owner.post("/api/doctors", json={"name": "Dr. Sen"})
    r = owner.post("/api/catalogue/doctors/check", json={"rows": [
        {"name": "Dr. Kakali Sarkar", "qualification": "MBBS, MD", "phone": "98765 43210"},
        {"name": "dr. sen", "qualification": "", "phone": ""},
        {"name": "City Nursing Home", "qualification": "", "phone": "12345"}]})
    rows = r.json()["rows"]
    assert rows[0] == {"values": {"name": "Dr. Kakali Sarkar", "qualification": "MBBS, MD", "phone": "+919876543210"}, "errors": {}}
    assert "already" in rows[1]["errors"]["name"]
    assert "phone" in rows[2]["errors"]
    assert owner.post("/api/catalogue/doctors/bulk", json={"rows": [rows[0]["values"]]}).status_code == 201
    names = {d["name"]: d["phone"] for d in owner.get("/api/doctors", params={"all": "true"}).json()["items"]}
    assert names["Dr. Kakali Sarkar"] == "+919876543210"
    template = load_workbook(io.BytesIO(owner.get("/api/catalogue/doctors/template").content)).active
    assert [c.value for c in template[1]] == ["Doctor or hospital", "Qualification", "Phone"]


def test_tests_are_read_from_an_excel_sheet_sent_in_pieces(owner):
    owner.post("/api/departments", json={"name": "Pathology"})
    owner.post("/api/test-types", json={"name": "Blood"})
    content = xlsx([["Rate list 2026"], ["Test name", "Code", "Department", "Type", "Rate"],
                    ["CBC", "cbc", "pathology", "blood", 250.5], [None, None, None, None, None],
                    ["Lipid profile", "", "Pathology", "", "₹1,200"], ["Thyroid", "", "Endocrine", "", "abc"]])
    upload_id = upload(owner, content)
    r = owner.post("/api/catalogue/tests/import", json={"upload_id": upload_id})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert [x["values"]["name"] for x in rows] == ["CBC", "Lipid profile", "Thyroid"]
    assert rows[0] == {"values": {"name": "CBC", "code": "CBC", "department": "Pathology", "test_type": "Blood", "price": "250.50"}, "errors": {}}
    assert rows[1]["values"]["price"] == "1200.00" and rows[1]["errors"] == {}
    assert set(rows[2]["errors"]) == {"department", "price"}
    # The upload is used up once read.
    assert owner.post("/api/catalogue/tests/import", json={"upload_id": upload_id}).status_code == 404

    r = owner.post("/api/catalogue/tests/bulk", json={"rows": [x["values"] for x in rows[:2]]})
    assert r.status_code == 201 and r.json()["added"] == 2
    tests = owner.get("/api/tests").json()["items"]
    assert {(t["name"], t["price"], t["department"]["name"]) for t in tests} == {("CBC", "250.50", "Pathology"), ("Lipid profile", "1200.00", "Pathology")}


def test_an_upload_resumes_from_where_the_server_got_to(owner):
    content = b"Department\nPathology\nRadiology\n"
    r = owner.post("/api/uploads", json={"filename": "d.csv", "size": len(content), "purpose": "catalogue"})
    up = r.json()["id"]
    h = {"Content-Type": "application/octet-stream"}
    assert owner.put(f"/api/uploads/{up}", content=content[:9], headers={**h, "Content-Range": f"bytes 0-8/{len(content)}"}).status_code == 200
    # A piece that skips ahead is refused; asking how far it got says 9. Pieces but the last come in threes.
    assert owner.put(f"/api/uploads/{up}", content=content[12:], headers={**h, "Content-Range": f"bytes 12-{len(content) - 1}/{len(content)}"}).status_code == 409
    assert owner.put(f"/api/uploads/{up}", content=content[9:13], headers={**h, "Content-Range": f"bytes 9-12/{len(content)}"}).status_code == 422
    assert owner.get(f"/api/uploads/{up}").json()["received"] == 9
    assert owner.post("/api/catalogue/departments/import", json={"upload_id": up}).status_code == 409  # not finished
    r = owner.put(f"/api/uploads/{up}", content=content[9:], headers={**h, "Content-Range": f"bytes 9-{len(content) - 1}/{len(content)}"})
    assert r.json()["complete"] is True
    rows = owner.post("/api/catalogue/departments/import", json={"upload_id": up}).json()["rows"]
    assert [x["values"]["name"] for x in rows] == ["Pathology", "Radiology"]


def test_uploads_are_private_and_checked(owner, alpha):
    r = owner.post("/api/uploads", json={"filename": "virus.exe", "size": 10, "purpose": "catalogue"})
    assert r.status_code == 422
    up = owner.post("/api/uploads", json={"filename": "a.csv", "size": 10, "purpose": "catalogue"}).json()["id"]
    front = browser("alpha.localhost")
    front.login("front@alpha.in")
    assert front.get(f"/api/uploads/{up}").status_code == 404  # someone else's upload
    assert front.post("/api/uploads", json={"filename": "a.csv", "size": 10, "purpose": "catalogue"}).status_code == 403
    assert front.post("/api/catalogue/departments/bulk", json={"rows": [{"name": "X-ray"}]}).status_code == 403


def test_a_bad_file_or_sheet_says_what_is_wrong(owner):
    up = upload(owner, b"not really a workbook", "x.xlsx")
    r = owner.post("/api/catalogue/tests/import", json={"upload_id": up})
    assert r.status_code == 422 and "couldn't read" in r.json()["message"]
    up = upload(owner, xlsx([["Something", "Else"], ["a", "b"]]))
    r = owner.post("/api/catalogue/tests/import", json={"upload_id": up})
    assert r.status_code == 422 and "Test name" in r.json()["message"]


def test_the_template_offers_the_centres_departments(owner):
    owner.post("/api/departments", json={"name": "Pathology"})
    r = owner.get("/api/catalogue/tests/template")
    assert r.status_code == 200
    book = load_workbook(io.BytesIO(r.content))
    assert [c.value for c in book.worksheets[0][1]] == ["Test name", "Short code", "Department", "Test type", "Price"]
    assert book["Lists"]["A2"].value == "Pathology"
