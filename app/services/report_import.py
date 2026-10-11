"""Bring the old app's typed reports (kept on each bill line as invoice_items.legacy_report) across as test
reports marked "imported". Run by migration 0008 (as the tables' owner, for every client) and safe to run
again: lines that already have a report are left alone.

    python -m app.services.report_import

Old keys: study (the findings), impression, modality, name (the title), tech / tech_degree / reg_no (who
signed), tech_specialisation, signature, file.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Connection, text

from app.core.html_clean import clean_html


def _html(value: object) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if "<" not in s:  # plain text from the old app: keep its lines
        s = "".join(f"<p>{line}</p>" for line in (ln.strip() for ln in s.replace("&", "&amp;").replace("<", "&lt;").splitlines()) if line)
    return clean_html(s)


def _text(value: object, size: int) -> str:
    return " ".join(str(value or "").split())[:size]


def import_legacy_reports(conn: Connection) -> int:
    rows = conn.execute(text("""
        SELECT i.id, i.tenant_id, i.test_name, i.legacy_report, i.status_changed_at, v.created_at
        FROM invoice_items i JOIN invoices v ON v.id = i.invoice_id
        WHERE i.legacy_report IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM test_reports r WHERE r.invoice_item_id = i.id)
    """)).all()
    done = 0
    for item_id, tenant_id, test_name, legacy, changed_at, billed_at in rows:
        if not isinstance(legacy, dict):
            continue
        findings, impression = _html(legacy.get("study")), _html(legacy.get("impression"))
        if not findings and not impression:
            continue
        signer = _text(legacy.get("tech"), 200)
        when = changed_at or billed_at or datetime.now(UTC)
        report = {
            "id": uuid.uuid4(), "tenant_id": tenant_id, "item": item_id, "status": "signed" if signer else "final",
            "title": _text(legacy.get("name"), 200) or test_name, "modality": _text(legacy.get("modality"), 40),
            "findings": findings, "impression": impression, "by": signer, "degree": _text(legacy.get("tech_degree"), 200),
            "reg": _text(legacy.get("reg_no"), 60), "signed_at": when if signer else None, "at": when,
        }
        conn.execute(text("""
            INSERT INTO test_reports (id, tenant_id, invoice_item_id, status, title, modality, findings, impression,
                reported_by_name, signer_name, signer_degree, signer_registration_no, signed_at, imported, version, created_at, updated_at)
            VALUES (:id, :tenant_id, :item, :status, :title, :modality, :findings, :impression,
                :by, :by, :degree, :reg, :signed_at, true, 1, :at, :at)
        """), report)
        conn.execute(text("""
            INSERT INTO test_report_versions (id, tenant_id, report_id, version, action, status, title, modality, findings,
                impression, reason, saved_by_name, created_at)
            VALUES (:vid, :tenant_id, :id, 1, 'imported', :status, :title, :modality, :findings, :impression,
                'Brought across from the old app', :by, :at)
        """), {**report, "vid": uuid.uuid4()})
        done += 1
    return done


if __name__ == "__main__":
    from sqlalchemy import create_engine

    from app.core.config import get_settings

    with create_engine(get_settings().migration_database_url).begin() as c:
        print(f"Imported {import_legacy_reports(c)} report(s).")
