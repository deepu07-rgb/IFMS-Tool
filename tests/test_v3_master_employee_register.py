import sqlite3
from pathlib import Path

import openpyxl
import pytest

from app import app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.master_employee_register_v3 import init_master_register_schema
from ifms_engine.monthly_comparison_v3 import init_monthly_comparison_schema
from ifms_engine.official_schedule_compare import init_official_schedule_schema
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema


def _one(db_path, sql, params=()):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    row = db.execute(sql, params).fetchone()
    db.close()
    return row


def _insert_employee(db, bill_id, month_year, group, sr_no, name, employee_id, pan, designation, pay_scale, gross, deduction, net, components=None, gpf="", bank="", belt=""):
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
    for head, amount in (components or {"basic_pay": gross}).items():
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
    db_path = tmp_path / "master_register.db"
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
    init_master_register_schema(db)
    db.execute("""
        INSERT INTO dictionary_mappings_v3 (category, raw_text, raw_text_key, final_text, final_text_en, active)
        VALUES ('designation', 'CONSTABLE', 'CONSTABLE', 'Constable', 'Constable', 1)
    """)
    apr_bill = db.execute("""
        INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no)
        VALUES ('Apr_2026_Main.pdf', 'Main', 'Apr/2026', 'APR1')
    """).lastrowid
    may_bill = db.execute("""
        INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no)
        VALUES ('May_2026_Main.pdf', 'Main', 'May/2026', 'MAY1')
    """).lastrowid

    _insert_employee(db, apr_bill, "Apr/2026", "Main", 1, "ALPHA RAM", "RJMASTER001", "ABCDE1234F", "Constable", "L8", 40000, 5000, 35000, {"basic_pay": 25000}, gpf="GPF001", bank="1111111111", belt="1")
    _insert_employee(db, may_bill, "May/2026", "Main", 1, "ALPHA RAM", "RJMASTER001", "ABCDE1234F", "Head Constable", "L9", 45000, 6000, 39000, {"basic_pay": 28000}, gpf="GPF001", bank="1111111111", belt="1")
    _insert_employee(db, may_bill, "May/2026", "Main", 2, "BETA RAM", "", "BCDEF1234G", "Constable", "L8", 30000, 3000, 27000, {"basic_pay": 22000}, gpf="GPF002", bank="2222222222", belt="2")
    _insert_employee(db, apr_bill, "Apr/2026", "Main", 3, "GAMMA RAM", "RJMASTER003", "CCCCC1234H", "Constable", "L8", 30000, 3000, 27000, {"basic_pay": 22000}, gpf="GPF003", bank="3333333333", belt="3")
    _insert_employee(db, may_bill, "May/2026", "Main", 3, "GAMMA RAM", "RJMASTER003", "DDDDD1234H", "Constable", "L8", 30000, 3000, 27000, {"basic_pay": 22000}, gpf="GPF003", bank="3333333333", belt="3")
    _insert_employee(db, may_bill, "May/2026", "Main", 4, "DELTA RAM", "RJMASTER004", "ABCDE1234F", "Constable", "L8", 32000, 3000, 29000, {"basic_pay": 23000}, gpf="GPF004", bank="4444444444", belt="4")
    _insert_employee(db, apr_bill, "Apr/2026", "Main", 5, "EPSILON RAM", "RJMASTER005", "EEEEE1234J", "Constable", "L8", 32000, 3000, 29000, {"basic_pay": 23000}, gpf="GPF005", bank="5555555555", belt="5")
    _insert_employee(db, may_bill, "May/2026", "Other", 6, "ZETA RAM", "RJMASTER006", "FFFFF1234K", "Constable", "L8", 31000, 2000, 29000, {"basic_pay": 23000}, gpf="GPF006", bank="1111111111", belt="6")
    _insert_employee(db, may_bill, "May/2026", "Main", 7, "LOW CONF", "", "", "Follower", "", 20000, 1000, 19000, {"basic_pay": 18000}, gpf="", bank="", belt="7")
    db.commit()
    db.close()
    with app.test_client() as test_client:
        yield test_client


def _build(client):
    response = client.post("/api/v3/master_register/build")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_master_register_build_keys_conflicts_history_and_safety(client):
    db_path = app.config["DATABASE"]
    before_employees = _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"]
    before_components = _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"]
    before_dictionary = _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"]
    before_official = _one(db_path, "SELECT COUNT(*) AS c FROM official_schedule_comparison_v3")["c"]
    before_monthly = _one(db_path, "SELECT COUNT(*) AS c FROM monthly_comparison_results_v3")["c"]

    payload = _build(client)
    summary = payload["summary"]
    assert summary["total_master_employees"] >= 7
    assert summary["history_row_count"] == before_employees
    assert summary["inactive_count"] >= 1
    assert summary["identity_conflict_count"] >= 1
    assert summary["duplicate_review_count"] >= 1
    assert summary["needs_review_count"] >= 1

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    alpha = db.execute("SELECT * FROM master_employees_v3 WHERE employee_id = 'RJMASTER001'").fetchone()
    beta = db.execute("SELECT * FROM master_employees_v3 WHERE pan = 'BCDEF1234G'").fetchone()
    epsilon = db.execute("SELECT * FROM master_employees_v3 WHERE employee_id = 'RJMASTER005'").fetchone()
    issues = [dict(row) for row in db.execute("SELECT * FROM master_employee_issues_v3").fetchall()]
    db.close()

    assert alpha["master_employee_key"] == "EMPID:RJMASTER001"
    assert beta["master_employee_key"] == "PAN:BCDEF1234G"
    assert epsilon["status"] == "INACTIVE"
    issue_types = {row["issue_type"] for row in issues}
    assert "IDENTITY_CONFLICT" in issue_types
    assert "DESIGNATION_CHANGED" in issue_types
    assert "PAY_SCALE_CHANGED" in issue_types
    assert "DUPLICATE_REVIEW" in issue_types
    assert any(row["severity"] == "CRITICAL" for row in issues if row["issue_type"] == "IDENTITY_CONFLICT")

    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"] == before_employees
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"] == before_components
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"] == before_dictionary
    assert _one(db_path, "SELECT COUNT(*) AS c FROM official_schedule_comparison_v3")["c"] == before_official
    assert _one(db_path, "SELECT COUNT(*) AS c FROM monthly_comparison_results_v3")["c"] == before_monthly


def test_master_register_api_actions_export_and_ui(client):
    _build(client)
    summary = client.get("/api/v3/master_register/summary")
    assert summary.status_code == 200
    assert summary.get_json()["summary"]["total_master_employees"] > 0

    employees = client.get("/api/v3/master_register/employees?search=ALPHA")
    assert employees.status_code == 200
    alpha = employees.get_json()["employees"][0]
    detail = client.get(f"/api/v3/master_register/employees/{alpha['id']}")
    assert detail.status_code == 200
    history = client.get(f"/api/v3/master_register/history/{alpha['id']}")
    assert history.status_code == 200
    assert len(history.get_json()["history"]) == 2

    issues = client.get("/api/v3/master_register/issues?status=OPEN")
    assert issues.status_code == 200
    issue = issues.get_json()["issues"][0]
    resolved = client.post(f"/api/v3/master_register/issues/{issue['id']}/resolve")
    assert resolved.status_code == 200

    archived = client.post(f"/api/v3/master_register/archive/{alpha['id']}")
    assert archived.status_code == 200
    assert client.get(f"/api/v3/master_register/employees/{alpha['id']}").get_json()["employee"]["status"] == "ARCHIVED"

    export = client.post("/api/v3/master_register/export")
    assert export.status_code == 200
    generated = sorted(Path(app.config["EXPORT_FOLDER"]).glob("Master_Employee_Register_*.xlsx"))
    assert generated
    workbook = openpyxl.load_workbook(generated[-1], read_only=True)
    assert {
        "Export Metadata",
        "Master Summary",
        "Master Register",
        "Active Employees",
        "Inactive Employees",
        "New Employees",
        "Needs Review",
        "Identity Conflicts",
        "Duplicate Review",
        "Employee History",
        "Master Issues",
        "Data Quality Notes",
    }.issubset(set(workbook.sheetnames))

    html = client.get("/").get_data(as_text=True)
    assert "Master Register" in html
    assert "Export Master Employee Register" in html
    for bad in ("\u00c3\u00a2", "\u00c3\u0192", "\ufffd"):
        assert bad not in html


def test_master_register_update_is_idempotent(client):
    _build(client)
    first = client.get("/api/v3/master_register/summary").get_json()["summary"]
    update = client.post("/api/v3/master_register/update")
    assert update.status_code == 200
    second = update.get_json()["summary"]
    assert second["history_row_count"] == first["history_row_count"]
    assert second["total_master_employees"] == first["total_master_employees"]
