import os
import sqlite3
from io import BytesIO

import openpyxl
import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2

PDF12 = os.path.join("test_fixtures", "ifms_inner_sheets", "12.pdf")


def _setup(tmp_path):
    db_path = tmp_path / "pdf12_phase1_audit.db"
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    return app.test_client(), db_path


def _rows(db_path, sql, params=()):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    rows = db.execute(sql, params).fetchall()
    db.close()
    return rows


def _one(db_path, sql, params=()):
    rows = _rows(db_path, sql, params)
    assert rows
    return rows[0]


def _insert_job(db_path):
    db = sqlite3.connect(db_path)
    db.execute(
        """
        INSERT INTO upload_jobs_v2 (
            source_filename, status, started_at, current_stage, message, percent_complete
        ) VALUES ('12.pdf', 'QUEUED', CURRENT_TIMESTAMP, 'queued', 'Queued for parsing', 0)
        """
    )
    db.commit()
    db.close()


def _add_and_apply_mapping(client, raw_text):
    add = client.post(
        "/api/v2/dictionary",
        json={
            "category": "designation",
            "raw_text": raw_text,
            "final_text": "RPS",
            "match_type": "contains",
            "priority": 100,
            "active": 1,
            "apply_existing": False,
        },
    )
    assert add.status_code == 200
    mapping_id = add.get_json()["id"]
    apply = client.post("/api/v3/dictionary/apply", json={"mapping_id": mapping_id})
    assert apply.status_code == 200
    return apply.get_json()


def _workbook_sheet_names(response):
    assert response.status_code == 200
    workbook = openpyxl.load_workbook(BytesIO(response.data), data_only=True)
    return set(workbook.sheetnames)


def test_pdf12_pcr_phase1_audit_gate_and_exports(tmp_path):
    if not os.path.exists(PDF12):
        pytest.skip("PDF 12 PCR fixture is not available")

    client, db_path = _setup(tmp_path)
    _insert_job(db_path)
    process_file_v2(PDF12, "12.pdf", dict(app.config))

    bill = _one(
        db_path,
        """
        SELECT id, group_name, bill_no, month_year, page_count,
               official_gross, official_deduction, official_net,
               parsed_gross, parsed_deduction, parsed_net
        FROM bills_v2
        WHERE source_filename = '12.pdf'
        """,
    )
    assert bill["page_count"] == 17
    assert bill["group_name"] == "PCR"
    assert bill["bill_no"] == "509095038"
    assert bill["month_year"] == "May / 2026"
    assert bill["official_gross"] > 0
    assert bill["official_deduction"] > 0
    assert bill["official_net"] > 0
    assert bill["parsed_gross"] > 0
    assert bill["parsed_deduction"] > 0
    assert bill["parsed_net"] > 0
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2 WHERE bill_id = ?", (bill["id"],))["c"] > 50

    jobs = client.get("/api/v2/jobs").get_json()
    assert jobs
    assert all(j["raw_status"] not in {"QUEUED", "PROCESSING"} for j in jobs if j["filename"] == "12.pdf")
    assert jobs[0]["pages_total"] == 17
    assert jobs[0]["employees_saved"] > 50

    audit_response = client.get("/api/v3/pdf_audits")
    assert audit_response.status_code == 200
    audits = audit_response.get_json()["audits"]
    pcr_audit = next(row for row in audits if row["source_file"] == "12.pdf")
    assert pcr_audit["group_name"] == "PCR"
    assert pcr_audit["employees_saved"] > 50
    assert pcr_audit["official_gross"] > 0
    assert pcr_audit["parsed_gross"] > 0
    assert pcr_audit["status"] in {"VERIFIED", "VERIFIED_WITH_WARNINGS", "NEEDS_REVIEW"}

    designations = {
        row["raw_designation_en"].upper()
        for row in _rows(
            db_path,
            "SELECT DISTINCT raw_designation_en FROM employees_v2 WHERE bill_id = ?",
            (bill["id"],),
        )
    }
    joined_designations = " | ".join(designations)
    for marker in ["RPS", "CONSTABLE", "HEAD CONSTABLE", "ASSISTANT SUB-INSPECTOR", "SUB-INSPECTOR"]:
        assert marker in joined_designations

    assert _add_and_apply_mapping(client, "RPS SELECTION SCALE")["updated_count"] >= 2
    assert _add_and_apply_mapping(client, "RPS ORDINARY SCALE")["updated_count"] >= 1
    assert _add_and_apply_mapping(client, "RPS SENIOR SCALE")["updated_count"] >= 1

    audit_after_dictionary = client.get("/api/v3/pdf_audits?source_file=12.pdf").get_json()["audits"][0]
    assert audit_after_dictionary["dictionary_applied_count"] >= 4

    display = client.get(
        "/api/employees",
        query_string={
            "source_file": "12.pdf",
            "search": "ANIL SHARMA",
            "designation_display": "english_hindi",
        },
    ).get_json()["employees"][0]
    assert display["designation"].startswith("RPS / ")

    edit = client.post(
        f"/api/v3/employees/{display['id']}/edit",
        json={"pan": "ABCDE1234F", "pay_scale": "L99c", "designation_scope": "employee"},
    )
    assert edit.status_code == 200
    edited_audit = client.get("/api/v3/pdf_audits?source_file=12.pdf").get_json()["audits"][0]
    assert edited_audit["manually_edited_count"] >= 1

    delete = client.post(f"/api/v3/employees/{display['id']}/delete")
    assert delete.status_code == 200
    deleted_audit = client.get("/api/v3/pdf_audits?source_file=12.pdf").get_json()["audits"][0]
    assert deleted_audit["deleted_row_count"] == 1
    assert deleted_audit["active_employee_count"] == deleted_audit["employees_saved"] - 1
    assert deleted_audit["status"] in {"VERIFIED_WITH_WARNINGS", "NEEDS_REVIEW"}

    restore = client.post(f"/api/v3/employees/{display['id']}/restore")
    assert restore.status_code == 200
    restored_audit = client.get("/api/v3/pdf_audits?source_file=12.pdf").get_json()["audits"][0]
    assert restored_audit["deleted_row_count"] == 0

    health = client.get("/api/v3/phase1_health")
    assert health.status_code == 200
    health_payload = health.get_json()
    assert health_payload["total_pdfs_uploaded"] >= 1
    assert health_payload["total_employees_parsed"] > 50
    assert health_payload["status_badge"] in {
        "READY FOR MANUAL REVIEW",
        "NEEDS REVIEW",
        "FAILED PARSING",
        "NO DATA",
    }

    pdf_export_sheets = _workbook_sheet_names(
        client.post("/api/v3/pdf_audit_export", json={"bill_id": bill["id"]})
    )
    assert {
        "Audit Summary",
        "Employee Master Snapshot",
        "Needs Review Rows",
        "Missing Critical Fields",
        "Component Review Rows",
        "Row Total Mismatches",
        "Unknown Components",
        "Dictionary Applied Rows",
        "Deleted Rows",
        "Audit Log",
    }.issubset(pdf_export_sheets)

    manual_export_sheets = _workbook_sheet_names(client.post("/api/v3/manual_qa_export", json={}))
    assert {
        "Phase 1 Health Check",
        "PDF Audit Summary",
        "Employee Data",
        "Needs Review",
        "Missing Critical Fields",
        "Component Review",
        "Designation Review",
        "Dictionary Mappings",
        "Deleted Rows",
        "Manual Edits Audit",
        "Export Metadata",
    }.issubset(manual_export_sheets)
