import os
import sqlite3
from io import BytesIO

import openpyxl
import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2


def _setup(tmp_path):
    db_path = tmp_path / "schedule_mapping_workflow.db"
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


def _insert_component(db_path, head, raw_head, amount):
    db = _db(db_path)
    employee = db.execute(
        "SELECT id, bill_id FROM employees_v2 WHERE COALESCE(is_deleted,0)=0 ORDER BY id LIMIT 1"
    ).fetchone()
    db.execute(
        """
        INSERT INTO employee_components_v2 (
            employee_id, bill_id, component_type, raw_head, normalized_head, amount, source_type
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (employee["id"], employee["bill_id"], "deduction", raw_head, head, amount, "parsed"),
    )
    db.commit()
    db.close()


def _unmapped_heads(client):
    response = client.get("/api/v3/schedules/unmapped_components")
    assert response.status_code == 200
    return {row["component_head"]: row for row in response.get_json()["unmapped_components"]}


def _schedule(client, schedule_type, **params):
    query = "&".join([f"schedule_type={schedule_type}", "page_size=500"] + [f"{k}={v}" for k, v in params.items()])
    response = client.get("/api/v3/schedules?" + query)
    assert response.status_code == 200
    return response.get_json()


def test_schedule_mapping_modal_manager_ignore_and_unmapped_export_workflow(tmp_path):
    client, db_path = _setup(tmp_path)

    initial_unmapped_count = client.get("/api/v3/schedules?page_size=10").get_json()["summary"]["audit"][
        "components_not_mapped_to_schedule_types"
    ]
    _insert_component(db_path, "workflow_component_one", "Workflow Component One", 4321)
    _insert_component(db_path, "workflow_component_two", "Workflow Component Two", 5432)

    after_insert = client.get("/api/v3/schedules?page_size=10").get_json()["summary"]["audit"][
        "components_not_mapped_to_schedule_types"
    ]
    assert after_insert == initial_unmapped_count + 2
    unmapped = _unmapped_heads(client)
    assert unmapped["workflow_component_one"]["total_amount"] == 4321
    assert unmapped["workflow_component_two"]["total_amount"] == 5432

    map_response = client.post(
        "/api/v3/schedules/component_mappings",
        json={
            "component_head": "workflow_component_one",
            "schedule_type": "other_components",
            "label": "Workflow Component One",
            "notes": "Mapped by Patch J workflow test",
            "active": True,
        },
    )
    assert map_response.status_code == 200
    assert "workflow_component_one" not in _unmapped_heads(client)
    other = _schedule(client, "other_components", amount_operator="equals", amount_value=4321)
    assert any(row["component_head"] == "workflow_component_one" for row in other["entries"])

    ignore_response = client.post(
        "/api/v3/schedules/component_mappings/ignore",
        json={"component_head": "workflow_component_two", "notes": "Not needed for schedule review"},
    )
    assert ignore_response.status_code == 200
    assert "workflow_component_two" not in _unmapped_heads(client)
    db = _db(db_path)
    ledger_count = db.execute(
        "SELECT COUNT(*) FROM employee_components_v2 WHERE normalized_head = ?",
        ("workflow_component_two",),
    ).fetchone()[0]
    db.close()
    assert ledger_count == 1

    after_review = client.get("/api/v3/schedules?page_size=10").get_json()["summary"]["audit"][
        "components_not_mapped_to_schedule_types"
    ]
    assert after_review == initial_unmapped_count

    mappings = client.get("/api/v3/schedules/component_mappings")
    assert mappings.status_code == 200
    custom = mappings.get_json()["custom"]
    mapped = [row for row in custom if row["component_head"] == "workflow_component_one"]
    assert mapped and mapped[-1]["schedule_type"] == "other_components"

    deactivate = client.post(
        "/api/v3/schedules/component_mappings/deactivate",
        json={"id": mapped[-1]["id"], "component_head": "workflow_component_one"},
    )
    assert deactivate.status_code == 200
    other_after_deactivate = _schedule(client, "other_components", amount_operator="equals", amount_value=4321)
    assert not any(row["component_head"] == "workflow_component_one" for row in other_after_deactivate["entries"])
    assert "workflow_component_one" in _unmapped_heads(client)

    export = client.post("/api/v3/schedules/unmapped_components/export", json={})
    assert export.status_code == 200
    workbook = openpyxl.load_workbook(BytesIO(export.data))
    for sheet in ("Export Metadata", "Unmapped Components", "Sample Employees", "Suggested Mappings", "Notes"):
        assert sheet in workbook.sheetnames

    html = client.get("/").get_data(as_text=True)
    for label in (
        "Map Component to Schedule Type",
        "Component Mappings",
        "Export Unmapped Components Review",
        "This component will remain preserved in Employee Data",
    ):
        assert label in html
    for bad in ("\u00c3\u00b0\u00c5\u00b8", "\u00c3\u00a2", "\u00c3\u0192", "\ufffd"):
        assert bad not in html
