"""The data move from the old Laravel app: the plain helpers, and one full dry run against the old database
when it's running locally (docker compose --profile legacy up -d legacy)."""

import os
import socket
from datetime import date

import pytest

from app.legacy_import import (
    DEFAULT_LEGACY_URL,
    doctor_display,
    doctor_key,
    parse_age,
    patient_key,
    run,
    strip_html,
)
from app.legacy_import import invoice_number as format_invoice_number
from tests.conftest import make_tenant


@pytest.mark.parametrize(("raw", "key"), [
    ("DR. S. K . HALDER", "SK HALDER"),
    ("Dr S.K.Halder", "SK HALDER"),
    ("DR.S.K HALDER", "SK HALDER"),
    ("  dr  mita   roy ", "MITA ROY"),
    ("MITA ROY", "MITA ROY"),
    ("DR, RANI BOSE", "RANI BOSE"),
    ("A.H.ASHA NURSING HOME", "AH ASHA NURSING HOME"),
    ("A. H. ASHA NURSING HOME", "AH ASHA NURSING HOME"),
    ("DRISHTI EYE CARE", "DRISHTI EYE CARE"),  # "DR" only as a whole word
    ("SELF", ""), (" self ", ""), ("-", ""), ("NA", ""), ("N.A.", ""), ("None", ""), ("", ""), (None, ""), ("DR.", ""),
])
def test_doctor_key(raw, key):
    assert doctor_key(raw) == key


def test_doctor_display_uses_the_most_common_spelling_in_nice_case():
    assert doctor_display({"DR. S. K . HALDER": 1, "DR. S.K.HALDER": 5, "S K HALDER": 1}) == "Dr. S.K. Halder"
    assert doctor_display({"MITA ROY": 3, "DR. MITA ROY": 1}) == "Dr. Mita Roy"
    assert doctor_display({"A.H.ASHA NURSING HOME": 2}) == "A.H. Asha Nursing Home"
    assert doctor_display({"MEDICAL COLLEGE AND HOSPITAL": 1}) == "Medical College and Hospital"
    assert doctor_display({"SSKM HOSPITAL": 1}) == "SSKM Hospital"
    assert doctor_display({"BAKSHA P. H. C": 1}) == "Baksha P.H.C."
    assert doctor_display({"DR. SUCHETA MUKHERJEE (DUTTA)": 1}) == "Dr. Sucheta Mukherjee (Dutta)"
    assert doctor_display({"DR. MD ABDUL MOKIT": 1}) == "Dr. MD Abdul Mokit"
    assert doctor_display({"DR. AH KHAN": 1}) == "Dr. AH Khan"
    assert doctor_display({"DR, RANI BOSE": 1}) == "Dr. Rani Bose"
    assert doctor_display({"PROF. (DR.) TARASANKAR DEY": 1}) == "Prof. (Dr.) Tarasankar Dey"


@pytest.mark.parametrize(("raw", "years", "how"), [
    ("61", 61, ""), (" 7 ", 7, ""), ("0", 0, ""), (45, 45, ""),
    ("1.5", 1, "decimal"), ("0.6", 0, "decimal"), ("11.5", 11, "decimal"),
    ("5 M", 0, "months"), ("6 MONTHS", 0, "months"), ("18 months", 1, "months"), ("2 Y 6 M", 2, "months"),
    ("20 DAYS", 0, "days"), ("3 weeks", 0, "days"), ("45 YRS", 45, ""),
    ("700", None, "out_of_range"), ("adult", None, "unreadable"), ("", None, "empty"), (None, None, "empty"),
])
def test_parse_age(raw, years, how):
    assert parse_age(raw) == (years, how)


def test_patient_key_needs_a_full_mobile():
    assert patient_key(" Ramen  Kumar dey ", "+91 90000-12345") == "RAMEN KUMAR DEY|9000012345"
    assert patient_key("RAMEN KUMAR DEY", "09000012345") == patient_key("ramen kumar dey", "9000012345")
    assert patient_key("RAMEN KUMAR DEY", "900001234") is None
    assert patient_key("RAMEN KUMAR DEY", None) is None
    assert patient_key("A", "9000012345") != patient_key("B", "9000012345")


def test_invoice_numbers_with_repeats():
    used: set[str] = set()
    assert format_invoice_number("SHC", date(2026, 6, 7), 2202, used) == "SHC/2026-27/002202"
    assert format_invoice_number("SHC", date(2026, 6, 7), 2202, used) == "SHC/2026-27/002202-B"
    assert format_invoice_number("SHC", date(2026, 6, 8), 2202, used) == "SHC/2026-27/002202-C"
    assert format_invoice_number("SHC", date(2026, 3, 31), 2202, used) == "SHC/2025-26/002202"  # another financial year
    assert format_invoice_number("SHC", date(2026, 2, 4), 3, used) == "SHC/2025-26/000003"


def test_strip_html():
    assert strip_html("<p>Fasting&nbsp;sample</p><p>Call <b>after</b> 5</p>") == "Fasting sample\nCall after 5"
    assert strip_html("line one<br/>line two<br>") == "line one\nline two"
    assert strip_html("plain & simple") == "plain & simple"
    assert strip_html(None) == ""
    assert strip_html("<p> </p>") == ""


def _legacy_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 3307), timeout=1):
            pass
        import pymysql
        pymysql.connect(host="localhost", port=3307, user="root", password="local-legacy-only", database="pos", connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _legacy_reachable(), reason="the old app's MariaDB database isn't running on localhost:3307")
def test_dry_run_against_the_old_database_reconciles(tmp_path):
    from sqlalchemy import create_engine, text

    tenant = make_tenant("supreme", "Supreme Health Care")
    outcome = run("supreme", DEFAULT_LEGACY_URL, target_url=os.environ["MIGRATION_DATABASE_URL"], dry_run=True, report_root=tmp_path)

    failed = [c for c in outcome.checks if not c[4]]
    assert outcome.ok, failed[:10]
    assert outcome.counts["invoices"].created == outcome.counts["invoices"].source > 0
    assert outcome.counts["patients"].created <= outcome.counts["patients"].source
    for name in ("report.md", "issues.csv", "doctors.csv", "reconciliation.csv"):
        assert (outcome.report_dir / name).is_file()
    # A dry run leaves nothing behind.
    with create_engine(os.environ["MIGRATION_DATABASE_URL"]).connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM invoices WHERE tenant_id = :t"), {"t": tenant.id}).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM patients WHERE tenant_id = :t"), {"t": tenant.id}).scalar() == 0
