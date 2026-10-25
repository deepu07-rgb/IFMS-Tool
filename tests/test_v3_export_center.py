import io
import os
import re
import sqlite3
from pathlib import Path

import openpyxl

from app import app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema


BAD_MOJIBAKE = (
    "\u00c3\u00b0\u00c5\u00b8",
    "\u00c3\u00a2",
    "\u00c3\u0192",
    "\ufffd",
)


def _setup(tmp_path):
    db_path = tmp_path / "export_center.db"
    export_dir = tmp_path / "exports"
    backup_dir = tmp_path / "backups"
    export_dir.mkdir()
    backup_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    app.config["BACKUP_FOLDER"] = str(backup_dir)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    init_schedule_mapping_schema(db)
    bill_id = db.execute(
        "INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no) VALUES (?,?,?,?)",
        ("export.pdf", "Export Group", "May / 2026", "E-1"),
    ).lastrowid
    emp_id = db.execute(
        """
        INSERT INTO employees_v2 (
            bill_id, source_filename, page_no, sr_no, group_name, month_year, raw_name,
            employee_id, final_designation, employee_data_status, gross_amount, sum_deduction, net_total
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (bill_id, "export.pdf", 1, 1, "Export Group", "May / 2026", "Export Employee", "EMP1", "CONSTABLE", "VERIFIED", 1000, 100, 900),
    ).lastrowid
    db.execute(
        """
        INSERT INTO employee_components_v2 (
            employee_id, bill_id, component_type, raw_head, normalized_head, amount, source_type
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (emp_id, bill_id, "deduction", "ITax", "income_tax", 100, "parsed"),
    )
    db.execute(
        """
        INSERT INTO dictionary_mappings_v3 (
            category, raw_text, raw_text_key, final_text, final_text_en, match_type, priority, active
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        ("designation", "CONSTABLE", "CONSTABLE", "CONSTABLE", "CONSTABLE", "exact", 100, 1),
    )
    db.execute(
        """
        INSERT INTO schedule_component_mappings_v3 (
            component_head, schedule_type, label, active, ignored, notes
        ) VALUES (?,?,?,?,?,?)
        """,
        ("export_component", "other_components", "Export Component", 1, 0, "seed"),
    )
    db.execute(
        """
        INSERT INTO validation_issues_v2 (
            bill_id, employee_id, issue_type, severity, message, raw_value, status
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (bill_id, emp_id, "TEST_REVIEW", "LOW", "Review seed", "employee_id", "OPEN"),
    )
    db.execute(
        "INSERT INTO edit_audit_log_v3 (action_type, table_name, record_id, field_name) VALUES (?,?,?,?)",
        ("employee_edit", "employees_v2", emp_id, "raw_name"),
    )
    db.commit()
    db.close()
    return app.test_client(), db_path, export_dir


def _filename(response):
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename=\"?([^\";]+)", disposition)
    assert match, disposition
    return match.group(1)


def _assert_metadata_sheet(response):
    workbook = openpyxl.load_workbook(io.BytesIO(response.data))
    assert "Export Metadata" in workbook.sheetnames


def test_export_center_endpoints_history_safety_and_existing_exports(tmp_path):
    parser_before = Path("parser.py").read_bytes()
    client, _db_path, export_dir = _setup(tmp_path)

    html = client.get("/").get_data(as_text=True)
    for label in (
        "Export Center",
        "Employee Data Exports",
        "Schedule Exports",
        "QA & Audit Exports",
        "Dictionary & Mapping Exports",
        "Backup Exports",
        "Export History",
    ):
        assert label in html
    for bad in BAD_MOJIBAKE:
        assert bad not in html

    history = client.get("/api/v3/export_center/history")
    assert history.status_code == 200

    generated = []
    for endpoint in (
        "/api/v3/export_center/review_issues",
        "/api/v3/export_center/dictionary_excel",
        "/api/v3/export_center/schedule_mappings_excel",
        "/api/v3/export_center/all_schedules",
    ):
        response = client.post(endpoint, json={})
        assert response.status_code == 200
        generated.append(_filename(response))
        _assert_metadata_sheet(response)

    listed = client.get("/api/v3/export_center/history").get_json()["exports"]
    listed_names = {row["file_name"] for row in listed}
    for name in generated:
        assert name in listed_names
        assert (export_dir / name).exists()

    download = client.get(f"/api/v3/export_center/download/{generated[0]}")
    assert download.status_code == 200

    delete = client.post("/api/v3/export_center/delete", json={"file_name": generated[0]})
    assert delete.status_code == 200
    assert not (export_dir / generated[0]).exists()

    assert client.get("/api/v3/export_center/download/%2e%2e/bad.xlsx").status_code == 400
    assert client.post("/api/v3/export_center/delete", json={"file_name": "../bad.xlsx"}).status_code == 400

    backup = client.post("/api/v3/backup/create")
    assert backup.status_code == 200

    schedule_export = client.post("/api/v3/schedules/export", json={"schedule_type": "income_tax"})
    assert schedule_export.status_code == 200

    employee_export = client.get("/api/export?group_name=Export%20Group")
    assert employee_export.status_code == 200
    assert _filename(employee_export).lower().endswith(".xlsx")

    assert Path("parser.py").read_bytes() == parser_before
