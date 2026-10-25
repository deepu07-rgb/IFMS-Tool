import argparse
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, build_pdf_audit_rows, build_phase1_health, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


PDF12 = os.path.join(ROOT, "test_fixtures", "ifms_inner_sheets", "12.pdf")


def _connect(db_path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db


def _ensure_pdf12_processed(db_path):
    app.config["DATABASE"] = db_path
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(db_path)
    if not os.path.exists(PDF12):
        return False
    db = _connect(db_path)
    exists = db.execute(
        "SELECT COUNT(*) FROM bills_v2 WHERE source_filename = '12.pdf'"
    ).fetchone()[0]
    if not exists:
        db.execute(
            """
            INSERT INTO upload_jobs_v2 (
                source_filename, status, started_at, current_stage, message, percent_complete
            ) VALUES ('12.pdf', 'QUEUED', CURRENT_TIMESTAMP, 'queued', 'Queued for readiness QA', 0)
            """
        )
        db.commit()
        db.close()
        process_file_v2(PDF12, "12.pdf", dict(app.config))
    else:
        db.close()
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=app.config["DATABASE"])
    args = parser.parse_args()
    has_fixture = _ensure_pdf12_processed(args.db)
    db = _connect(args.db)
    health = build_phase1_health(db)
    audits = build_pdf_audit_rows(db, source_file="12.pdf" if has_fixture else None)
    db.close()
    result = {
        "fixture_available": has_fixture,
        "phase1_status": health.get("status_badge"),
        "total_pdfs_uploaded": health.get("total_pdfs_uploaded"),
        "total_employees_parsed": health.get("total_employees_parsed"),
        "pdf12_audit": audits[0] if audits else None,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
