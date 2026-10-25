from __future__ import annotations

import sqlite3
from pathlib import Path

import openpyxl
import pytest

from app import app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.monthly_comparison_v3 import init_monthly_comparison_schema
from ifms_engine.official_schedule_compare import init_official_schedule_schema
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema


def _one(db_path, sql, params=()):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    row = db.execute(sql, params).fetchone()
    db.close()
    return row


def _insert_employee(db, bill_id, month_year, group, sr_no, name, employee_id, pan, designation, pay_scale, gross, deduction, net, components, gpf="", bank="", belt=""):
    emp_id = db.execute("""
        INSERT INTO employees_v2 (
            bill_id, source_filename, page_no, sr_no, group_name, month_year,
            raw_name, normalized_name, final_designation_en, pan_raw, employee_id,
            gpf_pran_raw, bank_acc, belt_no, pay_scale_raw, gross_amount,
            sum_deduction, net_total, employee_data_status
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VERIFIED')
    """, (
        bill_id, f"{month_year}_{group}.pdf", sr_no, group, month_year, name, name.upper(),
        designation, pan, employee_id, gpf, bank, belt, pay_scale, gross, deduction, net,
    )).lastrowid
    for head, amount in components.items():
        ctype = "allowance" if head in {"basic_pay", "da", "hra"} else "deduction"
        db.execute("""
            INSERT INTO employee_components_v2 (
                employee_id, bill_id, component_type, raw_head, normalized_head,
                amount, included_in_total, mapping_status, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 'mapped', 1)
        """, (emp_id, bill_id, ctype, head, head, amount))
    return emp_id


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "monthly_compare.db"
    export_dir = tmp_path / "exports"
    upload_dir = tmp_path / "uploads"
    export_dir.mkdir()
    upload_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["OFFICIAL_SCHEDULE_UPLOAD_FOLDER"] = str(upload_dir / "official_schedules")
    Path(app.config["OFFICIAL_SCHEDULE_UPLOAD_FOLDER"]).mkdir()
    init_db()
    init_v2_schema(str(db_path))
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    init_schedule_mapping_schema(db)
    init_official_schedule_schema(db)
    init_monthly_comparison_schema(db)
    base_bill = db.execute("""
        INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no)
        VALUES ('Apr_2026_Main.pdf', 'Main', 'Apr/2026', 'BASE1')
    """).lastrowid
    compare_bill = db.execute("""
        INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no)
        VALUES ('May_2026_Main.pdf', 'Main', 'May/2026', 'CMP1')
    """).lastrowid

    _insert_employee(db, base_bill, "Apr/2026", "Main", 1, "ALPHA RAM", "RJTEST000000001", "ABCDE1234F", "Constable", "L10", 50000, 8000, 42000, {
        "basic_pay": 30000, "da": 12000, "hra": 6000, "income_tax": 1000, "gpf": 3000, "lic": 500,
    }, gpf="GPF001", bank="111", belt="1")
    _insert_employee(db, compare_bill, "May/2026", "Main", 1, "ALPHA RAM", "RJTEST000000001", "ABCDE1234F", "Head Constable", "L11", 65000, 15000, 50000, {
        "basic_pay": 35000, "da": 14000, "hra": 7000, "income_tax": 2000, "gpf": 4000, "gpf_2004": 1500, "rghs": 658,
    }, gpf="GPF001", bank="111", belt="1")

    _insert_employee(db, base_bill, "Apr/2026", "Main", 2, "BETA RAM", "RJTEST000000002", "BCDEF1234G", "Constable", "L8", 40000, 6000, 34000, {
        "basic_pay": 25000, "da": 9000, "hra": 4000, "lic": 700,
    }, gpf="GPF002", bank="222", belt="2")

    _insert_employee(db, compare_bill, "May/2026", "Main", 3, "GAMMA RAM", "RJTEST000000003", "CDEFG1234H", "Constable", "L8", 41000, 7000, 34000, {
        "basic_pay": 25000, "da": 9000, "hra": 4000, "lic": 700, "itax": 500,
    }, gpf="GPF003", bank="333", belt="3")

    _insert_employee(db, base_bill, "Apr/2026", "Main", 4, "DELTA RAM", "RJTEST000000004", "DZZZZ1234I", "Constable", "L9", 45000, 5000, 40000, {
        "basic_pay": 28000, "gpf": 2500,
    }, gpf="GPF004", bank="444", belt="4")
    _insert_employee(db, compare_bill, "May/2026", "Main", 4, "DELTA RAM", "RJTEST000000004", "EZZZZ1234I", "Constable", "L9", 45000, 5000, 40000, {
        "basic_pay": 28000, "gpf": 2500,
    }, gpf="GPF004", bank="444", belt="4")

    _insert_employee(db, base_bill, "Apr/2026", "Main", 5, "EPSILON RAM", "RJTEST000000005", "FZZZZ1234J", "Constable", "L8", 30000, 5000, 25000, {
        "basic_pay": 25000, "da": 5000,
    }, gpf="GPF005", bank="555", belt="5")
    _insert_employee(db, compare_bill, "May/2026", "Main", 5, "EPSILON RAM", "RJTEST000000005", "FZZZZ1234J", "Constable", "L8", 50000, 5000, 45000, {
        "basic_pay": 25000, "da": 25000,
    }, gpf="GPF005", bank="555", belt="5")

    _insert_employee(db, base_bill, "Apr/2026", "Main", 6, "ZETA RAM", "RJTEST000000006", "GZZZZ1234K", "Constable", "L8", 30000, 1500, 28500, {
        "basic_pay": 30000, "lic": 1500,
    }, gpf="GPF006", bank="666", belt="6")
    _insert_employee(db, compare_bill, "May/2026", "Main", 6, "ZETA RAM", "RJTEST000000006", "GZZZZ1234K", "Constable", "L8", 30000, 0, 30000, {
        "basic_pay": 30000,
    }, gpf="GPF006", bank="666", belt="6")

    _insert_employee(db, base_bill, "Apr/2026", "Main", 7, "ETA RAM", "RJTEST000000007", "HZZZZ1234L", "Constable", "L8", 30000, 0, 30000, {
        "basic_pay": 30000,
    }, gpf="GPF007", bank="777", belt="7")
    _insert_employee(db, compare_bill, "May/2026", "Main", 7, "ETA RAM", "RJTEST000000007", "HZZZZ1234L", "Constable", "L8", 30000, 1500, 28500, {
        "basic_pay": 30000, "rghs": 1500,
    }, gpf="GPF007", bank="777", belt="7")

    db.commit()
    db.close()
    with app.test_client() as test_client:
        yield test_client


def _run(client):
    response = client.post("/api/v3/monthly_comparison/run", json={
        "base_month": "Apr",
        "base_year": "2026",
        "base_group": "Main",
        "compare_month": "May",
        "compare_year": "2026",
        "compare_group": "Main",
        "match_strategy": "employee_id",
        "amount_threshold": 1000,
        "percent_threshold": 10,
    })
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_monthly_comparison_detects_changes_and_preserves_source_tables(client):
    db_path = app.config["DATABASE"]
    before_employees = _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"]
    before_components = _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"]
    before_dictionary = _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"]
    before_official = _one(db_path, "SELECT COUNT(*) AS c FROM official_schedule_comparison_v3")["c"]

    payload = _run(client)
    summary = payload["summary"]
    rows = payload["results"]
    statuses = {row["match_status"] for row in rows}
    change_types = {row["change_type"] for row in rows}

    assert summary["matched_count"] >= 1
    assert summary["new_employee_count"] == 1
    assert summary["removed_employee_count"] == 1
    assert "MATCHED" in statuses
    assert "NEW_EMPLOYEE" in statuses
    assert "REMOVED_EMPLOYEE" in statuses
    assert "IDENTITY_CONFLICT" in statuses
    assert {"BASIC_CHANGED", "DESIGNATION_CHANGED", "PAY_SCALE_CHANGED"} & change_types
    assert "HIGH_VARIANCE" in change_types
    assert "COMPONENT_STARTED" in change_types
    assert "COMPONENT_STOPPED" in change_types
    assert "NEW_EMPLOYEE" in change_types
    assert "REMOVED_EMPLOYEE" in change_types
    alpha = next(row for row in rows if row["employee_id"] == "RJTEST000000001")
    assert alpha["basic_difference"] == 5000
    assert "income_tax" in alpha["component_changes_json"] or "itax" in alpha["component_changes_json"]
    assert "gpf_2004" in alpha["component_changes_json"]
    assert "lic" in alpha["component_changes_json"]
    assert alpha["gross_difference"] == 15000
    assert alpha["net_difference"] == 8000

    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"] == before_employees
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"] == before_components
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"] == before_dictionary
    assert _one(db_path, "SELECT COUNT(*) AS c FROM official_schedule_comparison_v3")["c"] == before_official


def test_monthly_comparison_options_results_review_export_and_ui(client):
    options = client.get("/api/v3/monthly_comparison/options")
    assert options.status_code == 200
    assert "Apr" in options.get_json()["months"]
    assert "May" in options.get_json()["months"]

    payload = _run(client)
    run_id = payload["summary"]["run_id"]
    listed = client.get("/api/v3/monthly_comparison/runs")
    assert listed.status_code == 200
    assert any(row["id"] == run_id for row in listed.get_json()["runs"])

    results = client.get(f"/api/v3/monthly_comparison/results?run_id={run_id}&status=MATCHED")
    assert results.status_code == 200
    rows = results.get_json()["results"]
    assert rows
    reviewed = client.post("/api/v3/monthly_comparison/mark_reviewed", json={"result_id": rows[0]["id"]})
    assert reviewed.status_code == 200

    export = client.post("/api/v3/monthly_comparison/export", json={"run_id": run_id})
    assert export.status_code == 200
    generated = sorted(Path(app.config["EXPORT_FOLDER"]).glob("Monthly_Comparison_*.xlsx"))
    assert generated
    workbook = openpyxl.load_workbook(generated[-1], read_only=True)
    assert {
        "Export Metadata",
        "Comparison Summary",
        "Matched Employees",
        "New Employees",
        "Removed Employees",
        "Pay Changes",
        "Allowance Changes",
        "Deduction Changes",
        "Net Salary Changes",
        "Identity Changes",
        "High Variance",
        "Needs Review",
        "Raw Comparison Rows",
        "Data Quality Notes",
    }.issubset(set(workbook.sheetnames))

    html = client.get("/").get_data(as_text=True)
    assert "Monthly Comparison" in html
    for bad in ("\u00c3\u00a2", "\u00c3\u0192", "\ufffd"):
        assert bad not in html


def test_monthly_comparison_delete_run_is_separate(client):
    payload = _run(client)
    run_id = payload["summary"]["run_id"]
    delete = client.post("/api/v3/monthly_comparison/delete_run", json={"run_id": run_id})
    assert delete.status_code == 200
    remaining = client.get(f"/api/v3/monthly_comparison/results?run_id={run_id}").get_json()["results"]
    assert remaining == []
    assert client.post("/api/v3/monthly_comparison/delete_run", json={"run_id": "../bad"}).status_code == 400
