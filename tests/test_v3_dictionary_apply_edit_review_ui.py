import os
import sqlite3

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2

PDF10 = os.path.join("test_fixtures", "ifms_inner_sheets", "10.pdf")


def _setup(tmp_path):
    db_path = tmp_path / "v3_dictionary_apply.db"
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


def test_v3_dictionary_apply_edit_review_and_summary_contamination(tmp_path):
    client, db_path = _setup(tmp_path)
    _process_pdf10()

    before = client.get("/api/employees?page=1&per_page=50").get_json()["employees"]
    ips_junior_before = [r for r in before if "IPS, JUNIOR SCALE" in r["raw_designation_full"]]
    assert len(ips_junior_before) >= 3
    assert all(r["final_designation_en"] == "Needs Review" for r in ips_junior_before)

    add = client.post(
        "/api/v2/dictionary",
        json={
            "category": "designation",
            "raw_text": "IPS, JUNIOR SCALE",
            "final_text_en": "IPS",
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
    assert apply.get_json()["updated"] >= 3

    mapped = {
        r["raw_name"]: r
        for r in _rows(
            db_path,
            """
            SELECT raw_name, final_designation_en, designation_needs_review
            FROM employees_v2
            WHERE raw_designation_full LIKE '%IPS, JUNIOR SCALE%'
            """,
        )
    }
    assert mapped["PRATEEK SINGH"]["final_designation_en"] == "IPS"
    assert mapped["KAMAL SHEKHAWAT"]["final_designation_en"] == "IPS"
    assert mapped["SHAHEEN C"]["final_designation_en"] == "IPS"
    assert all(r["designation_needs_review"] == 0 for r in mapped.values())

    active_junior_reviews = _rows(
        db_path,
        """
        SELECT v.id
        FROM validation_issues_v2 v
        JOIN employees_v2 e ON e.id = v.employee_id
        WHERE v.issue_type = 'UNCONFIRMED_DESIGNATION'
          AND COALESCE(v.status, 'OPEN') != 'RESOLVED'
          AND e.raw_designation_full LIKE '%IPS, JUNIOR SCALE%'
        """,
    )
    assert not active_junior_reviews

    after_api = client.get("/api/employees?page=1&per_page=50").get_json()["employees"]
    assert {
        r["employee_name"]: r["designation"]
        for r in after_api
        if "IPS, JUNIOR SCALE" in r["raw_designation_full"]
    }["PRATEEK SINGH"] == "IPS"

    dictionary = client.get("/api/v2/dictionary").get_json()
    assert any(d["id"] == mapping_id and d["raw_text"] == "IPS, JUNIOR SCALE" for d in dictionary)

    deactivate = client.post("/api/v3/dictionary/deactivate", json={"mapping_id": mapping_id})
    assert deactivate.status_code == 200
    assert client.post("/api/delete_all").status_code == 200
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3 WHERE id = ?", (mapping_id,))["c"] == 1
    _process_pdf10()
    reupload_junior = _rows(
        db_path,
        """
        SELECT final_designation_en, designation_needs_review
        FROM employees_v2
        WHERE raw_designation_full LIKE '%IPS, JUNIOR SCALE%'
        """,
    )
    assert reupload_junior
    assert all(r["final_designation_en"] == "Needs Review" for r in reupload_junior)
    assert all(r["designation_needs_review"] == 1 for r in reupload_junior)

    manish = _one(db_path, "SELECT id FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'")
    edit_once = client.put(
        f"/api/employees/{manish['id']}",
        json={"final_designation_en": "IPS", "designation_scope": "employee"},
    )
    assert edit_once.status_code == 200
    only_manish = _rows(
        db_path,
        "SELECT raw_name, final_designation_en FROM employees_v2 WHERE raw_designation_full LIKE '%IPS, SENIOR TIME SCALE%'",
    )
    assert only_manish == [only_manish[0]]
    assert only_manish[0]["raw_name"] == "MANISH KUMAR CHOUDHARY"
    assert only_manish[0]["final_designation_en"] == "IPS"
    assert _one(db_path, "SELECT COUNT(*) AS c FROM edit_audit_log_v3 WHERE action_type LIKE 'employee%'")["c"] >= 1

    client.post("/api/delete_all")
    _process_pdf10()
    manish = _one(db_path, "SELECT id FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'")
    global_edit = client.post(
        f"/api/v3/employees/{manish['id']}/edit",
        json={"final_designation_en": "IPS", "designation_scope": "global"},
    )
    assert global_edit.status_code == 200
    assert _one(
        db_path,
        "SELECT COUNT(*) AS c FROM dictionary_mappings_v3 WHERE raw_text LIKE '%IPS, SENIOR TIME SCALE%' AND active = 1",
    )["c"] >= 1

    client.post("/api/delete_all")
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3 WHERE raw_text LIKE '%IPS, SENIOR TIME SCALE%'")["c"] >= 1
    _process_pdf10()
    assert _one(
        db_path,
        "SELECT final_designation_en FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'",
    )["final_designation_en"] == "IPS"

    no_summary_unknown = _one(
        db_path,
        """
        SELECT COUNT(*) AS c
        FROM validation_issues_v2
        WHERE issue_type = 'UNKNOWN_COMPONENT_HEAD'
          AND raw_value LIKE '%Deduction Amount%'
        """,
    )["c"]
    assert no_summary_unknown == 0
    review_payload = client.get("/api/v3/review_queue").get_json()
    assert "issues" in review_payload
    assert all(
        not (i["issue_type"] == "UNKNOWN_COMPONENT_HEAD" and "Deduction Amount" in i["raw_value"])
        for i in review_payload["issues"]
    )
    if review_payload["issues"]:
        assert "actions" in review_payload["issues"][0]
        assert "action_data" in review_payload["issues"][0]

    prateek = _one(db_path, "SELECT id FROM employees_v2 WHERE raw_name = 'PRATEEK SINGH'")
    edit_fields = client.post(
        f"/api/v3/employees/{prateek['id']}/edit",
        json={
            "employee_name": "PRATEEK SINGH TEST",
            "employee_id": "RJTEST000001",
            "pan": "ABCDE1234F",
            "pay_scale": "L15",
            "final_designation_en": "IPS",
            "designation_scope": "employee",
            "basic": 12345,
            "lic": 678,
        },
    )
    assert edit_fields.status_code == 200
    edited = _one(
        db_path,
        "SELECT raw_name, employee_id, pan_raw, pay_scale_raw, final_designation_en FROM employees_v2 WHERE id = ?",
        (prateek["id"],),
    )
    assert edited["raw_name"] == "PRATEEK SINGH TEST"
    assert edited["employee_id"] == "RJTEST000001"
    assert edited["pan_raw"] == "ABCDE1234F"
    assert edited["pay_scale_raw"] == "L15"
    assert edited["final_designation_en"] == "IPS"
    comps = {
        r["normalized_head"]: r["amount"]
        for r in _rows(
            db_path,
            "SELECT normalized_head, amount FROM employee_components_v2 WHERE employee_id = ? AND normalized_head IN ('basic_pay','lic')",
            (prateek["id"],),
        )
    }
    assert comps["basic_pay"] == 12345
    assert comps["lic"] == 678
    assert _one(db_path, "SELECT COUNT(*) AS c FROM edit_audit_log_v3")["c"] >= 3
