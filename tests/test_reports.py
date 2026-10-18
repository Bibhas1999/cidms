"""Reports and exports: the numbers add up, files open, permissions hold and centres stay apart."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import select, text

from app.core.db import scoped_session
from app.core.money import local_today
from app.models import ActivityLog
from tests.conftest import browser, make_tenant, make_user

TODAY = local_today()
PATIENT = {"name": "Ramen Kumar Dey", "guardian_name": "Self", "age_years": 61, "gender": "male", "mobile": "9000012345",
           "address": "Janai, Hooghly"}


def money(v) -> Decimal:
    return Decimal(str(v))


@pytest.fixture
def centre(alpha):
    make_user(alpha, "owner@alpha.in", ["owner"])
    make_user(alpha, "front@alpha.in", ["receptionist"])
    owner = browser("alpha.localhost")
    owner.login("owner@alpha.in")
    radiology = owner.post("/api/departments", json={"name": "Radiology"}).json()["id"]
    pathology = owner.post("/api/departments", json={"name": "Pathology"}).json()["id"]
    xray = owner.post("/api/test-types", json={"name": "X-ray", "is_imaging": True}).json()["id"]
    blood = owner.post("/api/test-types", json={"name": "Blood"}).json()["id"]
    tests = {}
    for name, dept, kind, price in [("Chest X-ray PA", radiology, xray, "350"), ("CBC", pathology, blood, "250.50"),
                                    ("Lipid profile", pathology, blood, "600")]:
        tests[name] = owner.post("/api/tests", json={"name": name, "department_id": dept, "test_type_id": kind, "price": price}).json()["id"]
    front = browser("alpha.localhost")
    front.login("front@alpha.in")
    return {"owner": owner, "front": front, "tests": tests, "tenant": alpha, "pathology": pathology}


def bill(c, tests, names, **kw):
    r = c.post("/api/bills", json={"patient": PATIENT, "lines": [{"test_id": tests[n]} for n in names], **kw})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def books(centre):
    """A: 600 less 100 discount, 500 cash, 100 refunded. B: CBC paid by UPI then cash. C: X-ray + CBC from 40 days ago,
    referred by a doctor, 100 collected today. D: cancelled."""
    t, front, owner = centre["tests"], centre["front"], centre["owner"]
    a = bill(front, t, ["Lipid profile"], discount_type="amount", discount_value="100", payments=[{"mode": "cash", "amount": "500"}])
    owner.post(f"/api/bills/{a['id']}/refunds", json={"mode": "cash", "amount": "100", "note": "Overcharged"})
    b = bill(front, t, ["CBC"], payments=[{"mode": "upi", "amount": "200", "reference": "U1"}])
    front.post(f"/api/bills/{b['id']}/payments", json={"mode": "cash", "amount": "50.50"})
    c = bill(front, t, ["Chest X-ray PA", "CBC"], referring_doctor_name="Dr. Halder")
    with scoped_session(centre["tenant"].id) as db, db.begin():
        db.execute(text("UPDATE invoices SET bill_date = :d WHERE id = :i"), {"d": TODAY - timedelta(days=40), "i": c["id"]})
    assert front.post(f"/api/bills/{c['id']}/payments", json={"mode": "cash", "amount": "100"}).status_code == 200
    d = bill(front, t, ["CBC"])
    assert owner.post(f"/api/bills/{d['id']}/cancel", json={"reason": "Patient left"}).status_code == 200
    return {"a": a, "b": b, "c": c, "d": d}


WIDE = {"from": (TODAY - timedelta(days=60)).isoformat(), "to": TODAY.isoformat()}


def get(c, name, **params):
    r = c.get(f"/api/reports/{name}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_collection_adds_up_by_day_week_month_and_year(centre, books):
    rep = get(centre["owner"], "collection", **{"from": TODAY.isoformat(), "to": TODAY.isoformat()})
    assert [c["key"] for c in rep["columns"]][:3] == ["period", "bills", "billed"]
    row = rep["rows"][0]
    assert row["bills"] == 2 and money(row["billed"]) == Decimal("750.50") and money(row["discounts"]) == Decimal("100.00")
    assert money(row["cash"]) == Decimal("550.50") and money(row["upi"]) == Decimal("200.00")
    assert money(row["refunds"]) == Decimal("100.00") and money(row["net"]) == Decimal("750.50")
    assert money(row["dues_collected"]) == Decimal("100.00")
    assert money(rep["totals"]["net"]) == Decimal("750.50")

    month = get(centre["owner"], "collection")  # this month by default, one row per day
    assert len(month["rows"]) == TODAY.day and money(month["totals"]["net"]) == Decimal("750.50")

    jan1 = TODAY.replace(month=1, day=1)
    by_month = get(centre["owner"], "collection", group="month", **{"from": jan1.isoformat(), "to": TODAY.isoformat()})
    assert len(by_month["rows"]) == TODAY.month
    assert money(by_month["rows"][TODAY.month - 1]["net"]) == Decimal("750.50")
    assert money(by_month["totals"]["dues_collected"]) == Decimal("100.00")

    by_week = get(centre["owner"], "collection", group="week", **{"from": jan1.isoformat(), "to": TODAY.isoformat()})
    assert by_week["rows"][0]["period"] <= jan1.isoformat()  # weeks start on Monday
    assert money(by_week["totals"]["net"]) == Decimal("750.50")

    by_year = get(centre["owner"], "collection", group="year", all="true")
    assert by_year["rows"][-1]["period"] == str(TODAY.year) and money(by_year["totals"]["net"]) == Decimal("750.50")

    too_long = centre["owner"].get("/api/reports/collection", params={"from": "2020-01-01", "to": TODAY.isoformat()})
    assert too_long.status_code == 422 and too_long.json()["field"] == "group"


def test_dues_with_ageing(centre, books):
    rep = get(centre["owner"], "dues")
    assert [r["invoice_no"] for r in rep["rows"]] == [books["c"]["invoice_no"], books["a"]["invoice_no"]]  # oldest first
    assert rep["rows"][0]["age"] == 40 and money(rep["rows"][0]["due"]) == Decimal("500.50")
    assert money(rep["totals"]["due"]) == Decimal("600.50")
    ageing = {s["label"]: money(s["value"]) for s in rep["summary"] if s["label"].endswith("days")}
    assert ageing == {"0-30 days": Decimal("100.00"), "31-60 days": Decimal("500.50"), "61-90 days": 0, "90+ days": 0}
    assert "31-60 days" in rep["subtitle"]
    recent = get(centre["owner"], "dues", **{"from": (TODAY - timedelta(days=7)).isoformat()})
    assert len(recent["rows"]) == 1


def test_doctors_tests_departments_staff_discounts_and_payments(centre, books):
    owner = centre["owner"]
    docs = get(owner, "referring-doctors", **WIDE)
    assert [(r["doctor"], r["bills"], money(r["billed"])) for r in docs["rows"]] == [("Self", 2, Decimal("750.50")),
                                                                                    ("Dr. Halder", 1, Decimal("600.50"))]
    assert money(docs["rows"][0]["average"]) == Decimal("375.25")

    tests = {r["test"]: (r["count"], money(r["amount"])) for r in get(owner, "tests", **WIDE)["rows"]}
    assert tests == {"CBC": (2, Decimal("501.00")), "Lipid profile": (1, Decimal("600.00")), "Chest X-ray PA": (1, Decimal("350.00"))}
    path_only = get(owner, "tests", department_id=centre["pathology"], **WIDE)
    assert {r["test"] for r in path_only["rows"]} == {"CBC", "Lipid profile"} and "Pathology" in path_only["subtitle"]

    depts = get(owner, "departments", **WIDE)
    assert {r["department"]: (r["tests"], r["bills"], money(r["amount"])) for r in depts["rows"]} == {
        "Pathology": (3, 3, Decimal("1101.00")), "Radiology": (1, 1, Decimal("350.00"))}
    assert depts["totals"]["bills"] == 3

    staff = {r["staff"]: r for r in get(owner, "staff", **WIDE)["rows"]}
    assert staff["Front"]["bills"] == 3 and staff["Front"]["payments"] == 4 and money(staff["Front"]["received"]) == Decimal("850.50")
    assert staff["Owner"]["refunds_count"] == 1 and money(staff["Owner"]["net"]) == Decimal("-100.00")

    disc = get(owner, "discounts", **WIDE)
    assert len(disc["rows"]) == 1 and money(disc["rows"][0]["percent"]) == Decimal("16.67")

    pays = get(owner, "payments", **WIDE)
    assert len(pays["rows"]) == 5 and money(pays["totals"]["amount"]) == Decimal("750.50")
    assert sorted(money(r["amount"]) for r in pays["rows"])[0] == Decimal("-100.00")
    assert {s["label"]: money(s["value"]) for s in pays["summary"]}["Cash"] == Decimal("550.50")

    names = [r["name"] for r in owner.get("/api/reports").json()]
    assert {"collection", "dues", "referring-doctors", "tests", "departments", "staff", "discounts", "payments"} == set(names)
    assert owner.get("/api/reports/nope").status_code == 404
    assert owner.get("/api/reports/payments", params={"from": TODAY.isoformat(), "to": "2000-01-01"}).status_code == 422


def test_report_files_open_and_carry_totals(centre, books):
    owner = centre["owner"]
    r = owner.get("/api/reports/collection", params={"format": "xlsx"})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    assert "collection-by-day-" in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content)).active
    last = [c.value for c in ws[ws.max_row]]
    header = [c.value for c in ws[4]]
    assert "Card" not in header and "Cash" in header  # modes nobody used are left out
    assert last[0] == "Total" and Decimal(str(last[header.index("Net collected")])) == Decimal("750.50")
    assert ws.freeze_panes == "A5"
    for name, extra in (("dues", {}), ("payments", {"mode": "cash"}), ("staff", {}), ("collection", {"group": "month"})):
        pdf = owner.get(f"/api/reports/{name}", params={"format": "pdf", **extra})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"


def test_whole_workbook_has_a_sheet_per_report_including_dues(centre, books):
    owner = centre["owner"]
    r = owner.get("/api/reports/workbook.xlsx", params=WIDE)
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    assert "billing-reports-" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Collection", "Payments", "Dues", "Discounts", "Tests", "Departments", "Referring doctors", "Staff"]
    dues = wb["Dues"]
    assert dues.cell(row=1, column=1).value == "Dues" and dues[dues.max_row][0].value == "Total"
    # Accounts staff only get the sheets they may see.
    make_user(centre["tenant"], "acc2@alpha.in", ["accounts"])
    acc = browser("alpha.localhost")
    acc.login("acc2@alpha.in")
    names = load_workbook(io.BytesIO(acc.get("/api/reports/workbook.xlsx").content)).sheetnames
    assert names == ["Payments", "Dues"]


def test_front_desk_sees_the_totals_but_not_the_analytics(centre, books):
    front = centre["front"]  # a receptionist: no analytics.view
    page = front.get("/api/bills", params=WIDE).json()
    assert money(page["sums"]["billed"]) == Decimal("1351.00") and page["sums"]["due"] is not None
    ws = load_workbook(io.BytesIO(front.get("/api/exports/bills.xlsx", params=WIDE).content)).active
    header = [c.value for c in ws[4]]
    assert Decimal(str(ws[ws.max_row][header.index("Total")].value)) == Decimal("1351.00")
    assert front.get("/api/reports/collection").status_code == 403  # the breakdowns stay with the owner and admin


def test_a_search_stays_within_the_dates_given(centre, books):
    """Search respects the filters; the screen offers to clear them (registry style) before searching everything."""
    owner = centre["owner"]
    month = {"from": TODAY.replace(day=1).isoformat(), "to": TODAY.isoformat()}
    old = books["c"]["invoice_no"]  # from 40 days ago
    assert owner.get("/api/bills", params={**month, "search": old}).json()["items"] == []
    assert [b["invoice_no"] for b in owner.get("/api/bills", params={"search": old}).json()["items"]] == [old]


def test_bills_export_matches_the_list_and_is_logged(centre, books):
    front, owner = centre["front"], centre["owner"]
    params = {"from": (TODAY - timedelta(days=60)).isoformat(), "to": TODAY.isoformat()}
    r = owner.get("/api/exports/bills.xlsx", params=params)
    assert r.status_code == 200
    assert f'bills-{params["from"]}-to-{params["to"]}.xlsx' in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content)).active
    header = [c.value for c in ws[4]]
    assert header[:6] == ["Bill no", "Date", "Patient", "Mobile", "Referred by", "Tests"]
    body = list(ws.iter_rows(min_row=5, max_row=ws.max_row - 1, values_only=True))
    assert len(body) == 4
    c_row = next(row for row in body if row[0] == books["c"]["invoice_no"])
    assert c_row[4] == "Dr. Halder" and c_row[5] == "Chest X-ray PA, CBC"
    d_row = next(row for row in body if row[0] == books["d"]["invoice_no"])
    assert d_row[10] == "Cancelled" and not d_row[5]
    totals = [c.value for c in ws[ws.max_row]]
    assert totals[0] == "Total" and Decimal(str(totals[6])) == Decimal("1351.00")  # 500 + 250.50 + 600.50, cancelled left out
    assert Decimal(str(totals[9])) == Decimal("600.50")

    dues = owner.get("/api/exports/bills.xlsx", params={"payment": "due"})
    assert load_workbook(io.BytesIO(dues.content)).active.max_row == 4 + 2 + 1

    # The front desk gets the same file, totals included.
    mine = load_workbook(io.BytesIO(front.get("/api/exports/bills.xlsx", params=params).content)).active
    assert Decimal(str(mine[mine.max_row][6].value)) == Decimal("1351.00")
    pdf = owner.get("/api/exports/bills.pdf", params={"search": "ramen"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    with scoped_session(centre["tenant"].id) as db:
        logs = db.scalars(select(ActivityLog).where(ActivityLog.action == "export.bills").order_by(ActivityLog.id)).all()
    assert len(logs) == 4 and logs[0].details["rows"] == 4 and logs[1].details["filters"] == {"payment": "due"}


def test_receptionists_cannot_see_reports_but_can_export_bills(centre, books):
    front = centre["front"]
    assert front.get("/api/reports").status_code == 403
    assert front.get("/api/reports/dues").status_code == 403
    assert front.get("/api/reports/dues", params={"format": "xlsx"}).status_code == 403
    assert front.get("/api/exports/bills.pdf").status_code == 200
    assert browser("alpha.localhost").get("/api/exports/bills.xlsx").status_code == 401


def test_another_centres_figures_never_appear(centre, books):
    beta = make_tenant("beta")
    make_user(beta, "owner@beta.in", ["owner"])
    other = browser("beta.localhost")
    other.login("owner@beta.in")
    assert get(other, "dues")["rows"] == []
    assert money(get(other, "collection", **WIDE)["totals"]["net"]) == 0
    assert get(other, "payments", **WIDE)["rows"] == [] and get(other, "tests", **WIDE)["rows"] == []
    assert get(other, "staff", **WIDE)["rows"] == [] and get(other, "referring-doctors", **WIDE)["rows"] == []
    ws = load_workbook(io.BytesIO(other.get("/api/exports/bills.xlsx").content)).active
    assert ws.max_row == 5 and ws.cell(row=5, column=1).value == "Total"
    assert b"Alpha" not in other.get("/api/exports/bills.pdf").content
    # Alpha's department id means nothing at Beta.
    assert other.get("/api/reports/tests", params={"department_id": centre["pathology"]}).status_code == 422


def test_turnover_reports_are_for_owners_and_admins_only(centre, books):
    make_user(centre["tenant"], "accounts@alpha.in", ["accounts"])
    acc = browser("alpha.localhost")
    acc.login("accounts@alpha.in")
    assert {r["name"] for r in acc.get("/api/reports").json()} == {"dues", "payments"}
    assert acc.get("/api/reports/dues").status_code == 200 and acc.get("/api/reports/payments").status_code == 200
    for name in ("collection", "departments", "referring-doctors", "tests", "staff", "discounts"):
        assert acc.get(f"/api/reports/{name}").status_code == 403, name
    assert acc.get("/api/reports/staff", params={"format": "pdf"}).status_code == 403


def test_bills_workbook_has_a_summary_and_a_sheet_per_referring_doctor(centre, books):
    r = centre["front"].get("/api/exports/bills-by-doctor.xlsx", params=WIDE)
    assert r.status_code == 200 and "bills-by-doctor-" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Dr. Halder", "Self"]
    summary = wb["Summary"]
    rows = list(summary.iter_rows(min_row=5, values_only=True))
    assert rows[0][:2] == ("Dr. Halder", 1) and Decimal(str(rows[0][2])) == Decimal("600.50")
    assert rows[1][:2] == ("Self", 2) and Decimal(str(rows[1][2])) == Decimal("750.50")  # the cancelled bill isn't counted
    assert rows[2][0] == "All doctors" and Decimal(str(rows[2][2])) == Decimal("1351.00")
    assert summary["A5"].hyperlink.location == "'Dr. Halder'!A1" or "Dr. Halder" in str(summary["A5"].hyperlink.target or summary["A5"].hyperlink.location)
    self_sheet = wb["Self"]
    assert [c.value for c in self_sheet[4]][:5] == ["Bill no", "Date", "Patient", "Mobile", "Tests"]  # no "Referred by" column
    assert self_sheet.max_row == 4 + 3 + 1 and self_sheet.auto_filter.ref.startswith("A4:")
    assert self_sheet[4][0].fill.fgColor.rgb.endswith("004AAD")
