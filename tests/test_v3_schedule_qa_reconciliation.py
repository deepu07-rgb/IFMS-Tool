import os
import sqlite3
from io import BytesIO

import openpyxl
import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2


def _setup(tmp_path):
    db_path = tmp_path / "schedule_qa_reconciliation.db"
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    for pdf_name in ("1.pdf", "10.pdf", "12.pdf"):
        process_file_v2(
            os.path.join("test_fixtures", "ifms_inner_sheets", pdf_name),
            pdf_name,
            dict(app.config),
        )
    return app.test_client(), db_path


def _db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _schedule(client, schedule_type, **params):
    query = "&".join([f"schedule_type={schedule_type}", "page_size=500"] + [f"{k}={v}" for k, v in params.items()])
    response = client.get("/api/v3/schedules?" + query)
    assert response.status_code == 200
    return response.get_json()


def _ledger_total(db_path, heads):
    db = _db(db_path)
    ph = ",".join("?" for _ in heads)
    value = db.execute(
        f"""
        SELECT COALESCE(SUM(c.amount),0)
        FROM employee_components_v2 c
        JOIN employees_v2 e ON e.id = c.employee_id
        WHERE c.normalized_head IN ({ph})
          AND c.amount IS NOT NULL
          AND c.amount != 0
          AND COALESCE(e.is_deleted,0) = 0
        """,
        list(heads),
    ).fetchone()[0]
    db.close()
    return value


def test_schedule_qa_reconciliation_mapping_ignore_and_export(tmp_path):
    client, db_path = _setup(tmp_path)

    reconciliation = client.get("/api/v3/schedules/reconciliation")
    assert reconciliation.status_code == 200
    rows = reconciliation.get_json()["reconciliation"]
    known = {row["schedule_type"]: row for row in rows}
    for key in ("lic", "income_tax", "gpf_2004", "rop"):
        assert known[key]["status"] in {"matched", "no_data"}

    assert _schedule(client, "lic")["summary"]["total_amount"] == _ledger_total(db_path, ("lic",))
    assert _schedule(client, "income_tax")["summary"]["total_amount"] == _ledger_total(db_path, ("income_tax", "itax"))
    assert _schedule(client, "gpf_2004")["summary"]["total_amount"] == _ledger_total(db_path, ("gpf_2004",))
    rop = _schedule(client, "rop")
    assert rop["summary"]["total_amount"] == _ledger_total(db_path, ("rop",))
    assert any(row["amount"] < 0 for row in rop["entries"])

    db = _db(db_path)
    emp = db.execute("SELECT id, bill_id FROM employees_v2 WHERE COALESCE(is_deleted,0)=0 ORDER BY id LIMIT 1").fetchone()
    emp_id = emp["id"]
    db.execute(
        """
        INSERT INTO employee_components_v2 (
            employee_id, bill_id, component_type, raw_head, normalized_head, amount, source_type
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (emp_id, emp["bill_id"], "deduction", "Mystery Head", "mystery_component", 4321, "parsed"),
    )
    db.commit()
    db.close()

    unmapped = client.get("/api/v3/schedules/unmapped_components").get_json()["unmapped_components"]
    mystery = [row for row in unmapped if row["component_head"] == "mystery_component"]
    assert mystery and mystery[0]["total_amount"] == 4321

    map_response = client.post(
        "/api/v3/schedules/component_mappings",
        json={"component_head": "mystery_component", "schedule_type": "other_components", "label": "Mystery Component"},
    )
    assert map_response.status_code == 200
    other = _schedule(client, "other_components", amount_operator="equals", amount_value=4321)
    assert any(row["component_head"] == "mystery_component" for row in other["entries"])

    deactivate = client.post(
        "/api/v3/schedules/component_mappings/deactivate",
        json={"component_head": "mystery_component"},
    )
    assert deactivate.status_code == 200
    ignore = client.post(
        "/api/v3/schedules/component_mappings/ignore",
        json={"component_head": "mystery_component"},
    )
    assert ignore.status_code == 200
    unmapped_after_ignore = client.get("/api/v3/schedules/unmapped_components").get_json()["unmapped_components"]
    assert "mystery_component" not in {row["component_head"] for row in unmapped_after_ignore}

    income_tax = _schedule(client, "income_tax")
    target = income_tax["entries"][0]
    before_total = income_tax["summary"]["total_amount"]
    edit = client.post(
        f"/api/v3/employees/{target['employee_db_id']}/edit",
        json={"income_tax": target["amount"] + 1111, "designation_scope": "employee"},
    )
    assert edit.status_code == 200
    after_total = _schedule(client, "income_tax")["summary"]["total_amount"]
    assert after_total == before_total + 1111

    delete = client.post(f"/api/v3/employees/{target['employee_db_id']}/delete")
    assert delete.status_code == 200
    assert target["employee_db_id"] not in {row["employee_db_id"] for row in _schedule(client, "income_tax")["entries"]}
    assert target["employee_db_id"] in {row["employee_db_id"] for row in _schedule(client, "income_tax", show_deleted=1)["entries"]}

    export = client.post("/api/v3/schedules/export", json={"schedule_type": "income_tax", "show_deleted": "1"})
    assert export.status_code == 200
    workbook = openpyxl.load_workbook(BytesIO(export.data))
    for sheet in ("Schedule Entries", "Schedule Summary", "Reconciliation", "Unmapped Components", "Data Quality Notes"):
        assert sheet in workbook.sheetnames

    html = client.get("/").get_data(as_text=True)
    for label in (
        "Schedule QA",
        "Reconciliation",
        "Unmapped Components",
        "Schedules are derived from verified Employee Data and component ledger.",
    ):
        assert label in html
    for bad in ("\u00c3\u00b0\u00c5\u00b8", "\u00c3\u00a2", "\u00c3\u0192", "\ufffd"):
        assert bad not in html
