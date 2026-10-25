import os
import re
import sqlite3

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2

PDF12 = os.path.join("test_fixtures", "ifms_inner_sheets", "12.pdf")
LONG_NUMBER_RE = re.compile(r"\b\d{7,}\b")


def _setup(tmp_path):
    db_path = tmp_path / "pdf12_pcr_designation_editing.db"
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


def _employee_by_name(employees, name_fragment):
    for row in employees:
        if name_fragment in row["employee_name"]:
            return row
    raise AssertionError(f"Employee not found: {name_fragment}")


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


def test_pdf12_pcr_designation_display_edit_delete_source_flow(tmp_path):
    if not os.path.exists(PDF12):
        pytest.skip("PDF 12 PCR fixture is not available")

    client, db_path = _setup(tmp_path)
    process_file_v2(PDF12, "12.pdf", dict(app.config))

    bill = _one(
        db_path,
        """
        SELECT group_name, bill_no, month_year, page_count
        FROM bills_v2
        WHERE source_filename = '12.pdf'
        """,
    )
    assert bill["page_count"] == 17
    assert bill["group_name"] == "PCR"
    assert bill["bill_no"] == "509095038"
    assert bill["month_year"] == "May / 2026"

    response = client.get(
        "/api/employees",
        query_string={"source_file": "12.pdf", "page": 1, "per_page": 200, "sort": "sr_no"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    employees = payload["employees"]
    assert payload["total"] >= 4

    anil = _employee_by_name(employees, "ANIL SHARMA")
    ravindra = _employee_by_name(employees, "RAVINDRA KUMAR BOTHRA")
    manglesh = _employee_by_name(employees, "MANGLESH CHUNDAWAT")
    prem = _employee_by_name(employees, "PREM DHANDE")

    assert "RPS SELECTION SCALE" in anil["raw_designation_en"]
    assert "RPS SELECTION SCALE" in ravindra["raw_designation_en"]
    assert "ADDITIONAL DEPUTY COMMISSIONER POLICE" in ravindra["raw_designation_en"]
    assert not LONG_NUMBER_RE.search(ravindra["raw_designation_en"])
    assert not ravindra["raw_designation_en"].rstrip().endswith("-)")
    assert "RPS ORDINARY SCALE" in manglesh["raw_designation_en"]
    assert "RPS SENIOR SCALE" in prem["raw_designation_en"]
    assert anil["raw_designation_hi"]
    assert ravindra["raw_designation_hi"]
    assert manglesh["raw_designation_hi"]
    assert prem["raw_designation_hi"]
    assert anil["final_designation"] == "Needs Review"
    assert ravindra["final_designation"] == "Needs Review"
    assert manglesh["final_designation"] == "Needs Review"
    assert prem["final_designation"] == "Needs Review"

    selection_apply = _add_and_apply_mapping(client, "RPS SELECTION SCALE")
    ordinary_apply = _add_and_apply_mapping(client, "RPS ORDINARY SCALE")
    senior_apply = _add_and_apply_mapping(client, "RPS SENIOR SCALE")
    assert selection_apply["updated_count"] >= 2
    assert ordinary_apply["updated_count"] >= 1
    assert senior_apply["updated_count"] >= 1

    refreshed = client.get(
        "/api/employees",
        query_string={"source_file": "12.pdf", "page": 1, "per_page": 200, "sort": "sr_no"},
    ).get_json()["employees"]
    by_fragment = {fragment: _employee_by_name(refreshed, fragment) for fragment in (
        "ANIL SHARMA",
        "RAVINDRA KUMAR BOTHRA",
        "MANGLESH CHUNDAWAT",
        "PREM DHANDE",
    )}
    assert by_fragment["ANIL SHARMA"]["final_designation"] == "RPS"
    assert by_fragment["RAVINDRA KUMAR BOTHRA"]["final_designation"] == "RPS"
    assert by_fragment["MANGLESH CHUNDAWAT"]["final_designation"] == "RPS"
    assert by_fragment["PREM DHANDE"]["final_designation"] == "RPS"

    english = client.get(
        "/api/employees",
        query_string={
            "source_file": "12.pdf",
            "search": "ANIL SHARMA",
            "designation_display": "english",
        },
    ).get_json()["employees"][0]
    assert english["designation"] == "RPS"

    combined = client.get(
        "/api/employees",
        query_string={
            "source_file": "12.pdf",
            "search": "ANIL SHARMA",
            "designation_display": "english_hindi",
        },
    ).get_json()["employees"][0]
    assert combined["designation"].startswith("RPS / ")
    assert combined["raw_designation_hi"] in combined["designation"]

    edit = client.post(
        f"/api/v3/employees/{english['id']}/edit",
        json={"pan": "ABCDE1234F", "pay_scale": "L99c", "designation_scope": "employee"},
    )
    assert edit.status_code == 200
    edited = edit.get_json()["employee"]
    assert edited["pan"] == "ABCDE1234F"
    assert edited["pay_scale"] == "L99c"

    component_edit = client.post(
        f"/api/v3/employees/{english['id']}/edit",
        json={"lic": 1234, "designation_scope": "employee"},
    )
    assert component_edit.status_code == 200
    lic_component = _one(
        db_path,
        """
        SELECT amount, mapping_status, source_type
        FROM employee_components_v2
        WHERE employee_id = ? AND normalized_head = 'lic'
        """,
        (english["id"],),
    )
    assert lic_component["amount"] == 1234
    assert lic_component["mapping_status"] == "user_manual"
    assert lic_component["source_type"] == "manual_edit"

    source = client.get(f"/api/v3/employees/{english['id']}/source")
    assert source.status_code == 200
    source_payload = source.get_json()
    assert source_payload["source_file"] == "12.pdf"
    assert source_payload["raw_designation_full"]
    assert source_payload["raw_designation_en"]
    assert source_payload["raw_designation_hi"]
    assert source_payload["raw_text_block"]
    assert isinstance(source_payload["components"], list)
    assert isinstance(source_payload["validation_issues"], list)
    assert isinstance(source_payload["audit_log"], list)
    assert any(row["action_type"] == "employee_component_edit" for row in source_payload["audit_log"])

    delete = client.post(f"/api/v3/employees/{english['id']}/delete")
    assert delete.status_code == 200
    assert delete.get_json()["deleted"] is True

    hidden = client.get(
        "/api/employees",
        query_string={"source_file": "12.pdf", "search": "ANIL SHARMA"},
    ).get_json()
    assert hidden["total"] == 0

    active_scope = client.get(
        "/api/employees",
        query_string={"source_file": "12.pdf", "page": 1, "per_page": 200},
    ).get_json()
    assert active_scope["quality"]["bill_totals_matched"] is False

    visible_deleted = client.get(
        "/api/employees",
        query_string={"source_file": "12.pdf", "search": "ANIL SHARMA", "show_deleted": "1"},
    ).get_json()["employees"]
    assert len(visible_deleted) == 1
    assert visible_deleted[0]["is_deleted"] is True
    assert visible_deleted[0]["deleted_at"]

    restore = client.post(f"/api/v3/employees/{english['id']}/restore")
    assert restore.status_code == 200
    assert restore.get_json()["restored"] is True
    restored = client.get(
        "/api/employees",
        query_string={"source_file": "12.pdf", "search": "ANIL SHARMA"},
    ).get_json()["employees"]
    assert len(restored) == 1
    assert restored[0]["is_deleted"] is False
