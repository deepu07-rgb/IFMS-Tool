from __future__ import annotations

import sqlite3
from pathlib import Path

import openpyxl
import pytest

from app import app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.official_schedule_compare import init_official_schedule_schema
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "test_fixtures" / "official_schedules"
SAMPLE_1 = FIXTURE_DIR / "schedule_format_sample_1.pdf"


pytestmark = pytest.mark.skipif(not SAMPLE_1.exists(), reason="official schedule PDF fixtures are not available")


def _one(db_path, sql, params=()):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    row = db.execute(sql, params).fetchone()
    db.close()
    return row


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "official_compare.db"
    upload_dir = tmp_path / "uploads"
    official_dir = upload_dir / "official_schedules"
    export_dir = tmp_path / "exports"
    upload_dir.mkdir()
    official_dir.mkdir()
    export_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["OFFICIAL_SCHEDULE_UPLOAD_FOLDER"] = str(official_dir)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    init_db()
    init_v2_schema(str(db_path))
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    init_schedule_mapping_schema(db)
    init_official_schedule_schema(db)
    bill_id = db.execute("""
        INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no, bill_date)
        VALUES ('schedule format sample 1.pdf', 'Official Sample', 'May/2026', '509166102', '01/06/2026')
    """).lastrowid
    employees = [
        ("BALVANT RAM", "RJHA199616019828", "ADOPR5112M", 80000, {"income_tax": 15000, "lic": 490, "gpf": 10000}),
        ("GOVIND RAM", "RJJO198424017330", "AKWPR9290B", 55500, {"income_tax": 4000, "lic": 4494, "gpf": 10000}),
        ("MANOHAR LAL", "RJJO198924014042", "AHAPL0297K", 55500, {"gpf": 10000}),
    ]
    for sr_no, (name, employee_id, pan, basic, comps) in enumerate(employees, start=1):
        emp_id = db.execute("""
            INSERT INTO employees_v2 (
                bill_id, source_filename, page_no, sr_no, group_name, month_year,
                raw_name, normalized_name, final_designation_en, pan_raw, employee_id,
                pay_scale_raw, gross_amount, sum_deduction, net_total, employee_data_status
            ) VALUES (?, 'schedule format sample 1.pdf', 1, ?, 'Official Sample', 'May/2026',
                ?, ?, 'Constable', ?, ?, 'L10', 0, 0, 0, 'VERIFIED')
        """, (bill_id, sr_no, name, name.upper(), pan, employee_id)).lastrowid
        db.execute("""
            INSERT INTO employee_components_v2 (
                employee_id, bill_id, component_type, raw_head, normalized_head, amount, included_in_total, mapping_status, confidence
            ) VALUES (?, ?, 'allowance', 'Basic', 'basic_pay', ?, 1, 'mapped', 1)
        """, (emp_id, bill_id, basic))
        for head, amount in comps.items():
            db.execute("""
                INSERT INTO employee_components_v2 (
                    employee_id, bill_id, component_type, raw_head, normalized_head, amount, included_in_total, mapping_status, confidence
                ) VALUES (?, ?, 'deduction', ?, ?, ?, 1, 'mapped', 1)
            """, (emp_id, bill_id, head, head, amount))
    db.commit()
    db.close()
    with app.test_client() as test_client:
        yield test_client


def _upload(client):
    with SAMPLE_1.open("rb") as handle:
        response = client.post(
            "/api/v3/official_schedules/upload",
            data={"file": (handle, "schedule_format_sample_1.pdf")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_upload_stores_official_sections_and_rows(client):
    payload = _upload(client)
    assert payload["sections_detected"] == 10
    assert payload["rows_detected"] == 201
    assert {row["schedule_type"] for row in payload["supported_sections"]} >= {
        "income_tax", "lic", "gpf", "gpf_2004", "si_premium", "rghs",
        "roadways_deduction", "ppss_jdr", "advance_salary",
    }

    sections = client.get(f"/api/v3/official_schedules/sections?upload_id={payload['upload_id']}").get_json()["sections"]
    assert any(row["schedule_type"] == "income_tax" and row["bill_no"] == "509166102" for row in sections)
    rows = client.get(f"/api/v3/official_schedules/rows?upload_id={payload['upload_id']}&schedule_type=lic").get_json()["rows"]
    assert len(rows) == 44


def test_comparison_statuses_export_and_read_only_tables(client):
    payload = _upload(client)
    db_path = app.config["DATABASE"]
    before_employees = _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"]
    before_components = _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"]
    before_dictionary = _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"]

    compare = client.post(
        "/api/v3/official_schedules/compare",
        json={"upload_id": payload["upload_id"], "schedule_type": "income_tax"},
    )
    assert compare.status_code == 200, compare.get_data(as_text=True)
    rows = compare.get_json()["comparison"]
    statuses = {row["match_status"] for row in rows}
    assert "MATCHED" in statuses
    assert "AMOUNT_MISMATCH" in statuses
    assert "EXTRA_IN_OFFICIAL" in statuses
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"] == before_employees
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"] == before_components
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"] == before_dictionary

    db = sqlite3.connect(db_path)
    db.execute("""
        INSERT INTO employee_components_v2 (
            employee_id, bill_id, component_type, raw_head, normalized_head, amount, included_in_total, mapping_status, confidence
        )
        SELECT id, bill_id, 'deduction', 'Income Tax', 'income_tax', 123, 1, 'mapped', 1
        FROM employees_v2
        WHERE employee_id = 'RJHA199616019828'
    """)
    db.execute("UPDATE employees_v2 SET employee_id = 'RJTEST999999999' WHERE employee_id = 'RJHA199616019828'")
    db.commit()
    db.close()
    compare_missing = client.post(
        "/api/v3/official_schedules/compare",
        json={"upload_id": payload["upload_id"], "schedule_type": "income_tax"},
    )
    assert compare_missing.status_code == 200
    assert "MISSING_IN_OFFICIAL" in {row["match_status"] for row in compare_missing.get_json()["comparison"]}

    export = client.post("/api/v3/official_schedules/export", json={"upload_id": payload["upload_id"], "schedule_type": "income_tax"})
    assert export.status_code == 200
    generated = sorted(Path(app.config["EXPORT_FOLDER"]).glob("Official_Schedule_Comparison_*.xlsx"))
    assert generated
    workbook = openpyxl.load_workbook(generated[-1], read_only=True)
    assert {
        "Export Metadata",
        "Comparison Summary",
        "Matched Rows",
        "Missing in Official",
        "Extra in Official",
        "Amount Mismatches",
        "Official Parsed Rows",
        "Official Employee Aggregates",
        "Derived Schedule Rows",
        "Unsupported Sections",
        "Data Quality Notes",
    }.issubset(set(workbook.sheetnames))

    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"] == before_employees


def test_inner_sheet_upload_rejected_and_delete_path_uses_upload_id(client):
    inner = Path(__file__).resolve().parents[1] / "test_fixtures" / "ifms_inner_sheets" / "1.pdf"
    if inner.exists():
        with inner.open("rb") as handle:
            response = client.post(
                "/api/v3/official_schedules/upload",
                data={"file": (handle, "inner_sheet.pdf")},
                content_type="multipart/form-data",
            )
        assert response.status_code == 400
    assert client.post("/api/v3/official_schedules/delete_upload", json={"upload_id": "../bad.pdf"}).status_code == 400
