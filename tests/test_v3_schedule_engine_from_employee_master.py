import os
import sqlite3
from io import BytesIO

import openpyxl
import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2


def _setup(tmp_path):
    db_path = tmp_path / "schedule_engine_v3.db"
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    return app.test_client(), db_path


def _process(pdf_name):
    process_file_v2(
        os.path.join("test_fixtures", "ifms_inner_sheets", pdf_name),
        pdf_name,
        dict(app.config),
    )


def _db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(client, schedule_type, source_file=None, page_size=500, show_deleted=False):
    params = [f"schedule_type={schedule_type}", f"page_size={page_size}"]
    if source_file:
        params.append(f"source_file={source_file}")
    if show_deleted:
        params.append("show_deleted=1")
    response = client.get("/api/v3/schedules?" + "&".join(params))
    assert response.status_code == 200
    return response.get_json()


def _amount_by_name(payload, name):
    for row in payload["entries"]:
        if row["employee_name"] == name:
            return row["amount"]
    raise AssertionError(f"{name} not found")


def test_v3_schedules_derive_from_employee_master_and_component_ledger(tmp_path):
    client, db_path = _setup(tmp_path)

    _process("1.pdf")
    db = _db(db_path)
    for schedule_type, head in [("lic", "lic"), ("gpf", "gpf"), ("gpf_2004", "gpf_2004")]:
        payload = _rows(client, schedule_type, "1.pdf")
        expected = db.execute(
            """
            SELECT COUNT(*) AS c
            FROM employee_components_v2 c
            JOIN employees_v2 e ON e.id = c.employee_id
            WHERE e.source_filename = '1.pdf'
              AND c.normalized_head = ?
              AND c.amount IS NOT NULL
              AND c.amount != 0
              AND COALESCE(e.is_deleted,0) = 0
            """,
            (head,),
        ).fetchone()["c"]
        assert payload["summary"]["entry_count"] == expected
        assert all((row["amount"] or 0) != 0 for row in payload["entries"])

    rop_component_count = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM employee_components_v2 c
        JOIN employees_v2 e ON e.id = c.employee_id
        WHERE e.source_filename = '1.pdf'
          AND c.normalized_head = 'rop'
          AND c.amount IS NOT NULL
          AND c.amount != 0
        """
    ).fetchone()["c"]
    rop = _rows(client, "rop", "1.pdf")
    assert rop["summary"]["entry_count"] == rop_component_count
    if rop_component_count:
        assert any(row["amount"] < 0 for row in rop["entries"])
    db.close()

    _process("10.pdf")
    income_tax = _rows(client, "income_tax", "10.pdf")
    assert _amount_by_name(income_tax, "KAMAL SHEKHAWAT") == 60000
    assert _amount_by_name(income_tax, "SHARAT KAVIRAJ IPS") == 45000
    assert _amount_by_name(income_tax, "SHAHEEN C") == 8000
    assert "PRATEEK SINGH" not in {row["employee_name"] for row in income_tax["entries"]}

    assert _amount_by_name(_rows(client, "gpf", "10.pdf"), "KAMAL SHEKHAWAT") == 10500
    assert _amount_by_name(_rows(client, "ais_gpf", "10.pdf"), "SHARAT KAVIRAJ IPS") == 25000
    rghs = _rows(client, "rghs", "10.pdf")
    assert any(row["amount"] == 875 for row in rghs["entries"])

    _process("12.pdf")
    pcr_itax = _rows(client, "income_tax", "12.pdf")
    assert pcr_itax["summary"]["entry_count"] > 0
    assert all(row["amount"] > 0 for row in pcr_itax["entries"])
    assert _rows(client, "gpf_2004", "12.pdf")["summary"]["entry_count"] > 0
    assert _rows(client, "advance_salary", "12.pdf")["summary"]["entry_count"] > 0
    assert _rows(client, "roadways_deduction", "12.pdf")["summary"]["entry_count"] > 0

    first_page = client.get("/api/v3/schedules?schedule_type=rghs&source_file=12.pdf&page_size=10")
    assert first_page.status_code == 200
    first_payload = first_page.get_json()
    assert len(first_payload["entries"]) == 10
    assert first_payload["pagination"]["total"] > 10

    db = _db(db_path)
    emp = db.execute(
        """
        SELECT e.id
        FROM employees_v2 e
        JOIN employee_components_v2 c ON c.employee_id = e.id
        WHERE e.source_filename = '12.pdf'
          AND c.normalized_head = 'income_tax'
          AND c.amount != 0
        ORDER BY e.id
        LIMIT 1
        """
    ).fetchone()
    emp_id = emp["id"]
    db.close()

    delete_response = client.post(f"/api/v3/employees/{emp_id}/delete")
    assert delete_response.status_code == 200
    assert all(row["employee_db_id"] != emp_id for row in _rows(client, "income_tax", "12.pdf")["entries"])
    assert any(row["employee_db_id"] == emp_id for row in _rows(client, "income_tax", "12.pdf", show_deleted=True)["entries"])

    before_total = _rows(client, "income_tax", "12.pdf", show_deleted=True)["summary"]["total_amount"]
    edit_response = client.post(
        f"/api/v3/employees/{emp_id}/edit",
        json={"income_tax": 12345, "designation_scope": "employee"},
    )
    assert edit_response.status_code == 200
    after = _rows(client, "income_tax", "12.pdf", show_deleted=True)
    edited_rows = [row for row in after["entries"] if row["employee_db_id"] == emp_id]
    assert edited_rows
    assert edited_rows[0]["amount"] == 12345
    assert after["summary"]["total_amount"] != before_total
    assert after["summary"]["audit"]["rows_from_manual_edits"] >= 1


def test_v3_schedule_export_and_ui_labels_are_clean(tmp_path):
    client, _db_path = _setup(tmp_path)
    _process("10.pdf")

    response = client.post("/api/v3/schedules/export", json={"schedule_type": "income_tax"})
    assert response.status_code == 200
    assert "IFMS_V3_Derived_Schedule_Export" in response.headers["Content-Disposition"]

    workbook = openpyxl.load_workbook(BytesIO(response.data))
    assert {
        "Export Metadata",
        "Schedule Entries",
        "Schedule Summary",
        "Applied Filters",
        "Data Quality Notes",
    }.issubset(set(workbook.sheetnames))

    html = client.get("/").get_data(as_text=True)
    for label in [
        "Derived from verified Employee Data",
        "Schedule Type",
        "Export Schedule",
        "No matching schedule entries found.",
    ]:
        assert label in html
    for bad in ["\u00c3\u00b0\u00c5\u00b8", "\u00c3\u00a2", "\u00c3\u0192", "\ufffd"]:
        assert bad not in html
