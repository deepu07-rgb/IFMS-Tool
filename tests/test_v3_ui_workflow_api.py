import os
import sqlite3

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2

PDF10 = os.path.join("test_fixtures", "ifms_inner_sheets", "10.pdf")


def _setup(tmp_path):
    db_path = tmp_path / "v3_ui_workflow.db"
    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    return app.test_client(), db_path


def _process_pdf10():
    assert os.path.exists(PDF10)
    process_file_v2(PDF10, "10.pdf", dict(app.config))


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


def test_v3_ui_workflow_api_end_to_end(tmp_path):
    client, db_path = _setup(tmp_path)
    _process_pdf10()

    add = client.post(
        "/api/v2/dictionary",
        json={
            "category": "designation",
            "raw_text": "IPS, JUNIOR SCALE",
            "final_text": "IPS",
            "match_type": "contains",
            "priority": 100,
            "active": 1,
            "apply_existing": False,
        },
    )
    assert add.status_code == 200
    junior_mapping_id = add.get_json()["id"]

    apply = client.post("/api/v3/dictionary/apply", json={"mapping_id": junior_mapping_id})
    assert apply.status_code == 200
    assert apply.get_json()["updated_count"] >= 3

    employees = client.get("/api/employees?page=1&per_page=50").get_json()["employees"]
    by_name = {e["employee_name"]: e for e in employees}
    assert by_name["PRATEEK SINGH"]["designation"] == "IPS"
    assert by_name["KAMAL SHEKHAWAT"]["designation"] == "IPS"
    assert by_name["SHAHEEN C"]["designation"] == "IPS"

    prateek_id = by_name["PRATEEK SINGH"]["id"]
    edit_prateek = client.post(
        f"/api/v3/employees/{prateek_id}/edit",
        json={
            "employee_name": "PRATEEK SINGH EDITED",
            "pan": "ABCDE1234F",
            "designation_scope": "employee",
        },
    )
    assert edit_prateek.status_code == 200
    edited_api = client.get("/api/employees?page=1&per_page=50&search=PRATEEK%20SINGH%20EDITED")
    assert edited_api.status_code == 200
    edited = edited_api.get_json()["employees"][0]
    assert edited["employee_name"] == "PRATEEK SINGH EDITED"
    assert edited["pan"] == "ABCDE1234F"

    client.post("/api/delete_all")
    _process_pdf10()
    manish = _one(db_path, "SELECT id FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'")
    employee_only = client.post(
        f"/api/v3/employees/{manish['id']}/edit",
        json={"final_designation": "IPS", "designation_scope": "employee"},
    )
    assert employee_only.status_code == 200
    assert _one(
        db_path,
        "SELECT final_designation_en FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'",
    )["final_designation_en"] == "IPS"
    assert _one(
        db_path,
        "SELECT COUNT(*) AS c FROM dictionary_mappings_v3 WHERE raw_text LIKE '%IPS, SENIOR TIME SCALE%' AND active = 1",
    )["c"] == 0

    client.post("/api/delete_all")
    _process_pdf10()
    manish = _one(db_path, "SELECT id FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'")
    global_edit = client.post(
        f"/api/v3/employees/{manish['id']}/edit",
        json={"final_designation": "IPS", "designation_scope": "global"},
    )
    assert global_edit.status_code == 200
    senior_mapping = _one(
        db_path,
        "SELECT id FROM dictionary_mappings_v3 WHERE raw_text LIKE '%IPS, SENIOR TIME SCALE%' AND active = 1",
    )

    client.post("/api/delete_all")
    _process_pdf10()
    assert _one(
        db_path,
        "SELECT final_designation_en FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'",
    )["final_designation_en"] == "IPS"

    prateek = _one(db_path, "SELECT id FROM employees_v2 WHERE raw_name = 'PRATEEK SINGH'")
    component_edit = client.post(
        f"/api/v3/employees/{prateek['id']}/edit",
        json={"lic": 777, "income_tax": 8888, "designation_scope": "employee"},
    )
    assert component_edit.status_code == 200
    comps = {
        r["normalized_head"]: r["amount"]
        for r in _rows(
            db_path,
            """
            SELECT normalized_head, amount
            FROM employee_components_v2
            WHERE employee_id = ? AND normalized_head IN ('lic', 'income_tax')
            """,
            (prateek["id"],),
        )
    }
    assert comps["lic"] == 777
    assert comps["income_tax"] == 8888

    audit = client.get("/api/v3/audit_log")
    assert audit.status_code == 200
    actions = {r["action_type"] for r in audit.get_json()["audit_log"]}
    assert "employee_edit" in actions
    assert "mapping_applied_globally" in actions

    deactivated = client.post("/api/v3/dictionary/deactivate", json={"mapping_id": senior_mapping["id"]})
    assert deactivated.status_code == 200
    client.post("/api/delete_all")
    _process_pdf10()
    assert _one(
        db_path,
        "SELECT final_designation_en FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'",
    )["final_designation_en"] == "Needs Review"

    review = client.get("/api/v3/review_queue")
    assert review.status_code == 200
    issues = review.get_json()["issues"]
    assert issues
    assert any(i["raw_value"] for i in issues)
    assert all(
        not (i["issue_type"] == "UNKNOWN_COMPONENT_HEAD" and "Deduction Amount" in i["raw_value"])
        for i in issues
    )

    current_prateek = _one(db_path, "SELECT id FROM employees_v2 WHERE raw_name = 'PRATEEK SINGH'")
    assert client.get(f"/api/employees/{current_prateek['id']}").status_code == 200
    assert client.get("/api/v2/dictionary").status_code == 200
    assert client.post("/api/v3/dictionary/apply", json={"mapping_id": junior_mapping_id}).status_code in (200, 404)
    assert client.post("/api/v3/dictionary/deactivate", json={"mapping_id": junior_mapping_id}).status_code == 200
