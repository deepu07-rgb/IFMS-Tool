import sqlite3

from app import app, init_db
from ifms_engine.db import init_v2_schema


def test_delete_group_cleans_v1_and_v2_without_orphans(tmp_path):
    db_path = tmp_path / "delete_group_smoke.db"
    app.config["DATABASE"] = str(db_path)
    init_db()
    init_v2_schema(app.config["DATABASE"])

    db = sqlite3.connect(app.config["DATABASE"])

    group = "GROUP_X"
    fname = "group_x.pdf"

    # V1 seed
    db.execute(
        "INSERT INTO uploads (filename, sheet_type, group_name, month_year) VALUES (?, ?, ?, ?)",
        (fname, "inner", group, "Jan/2026"),
    )
    upload_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO employees (upload_id, group_name, month_year, name) VALUES (?, ?, ?, ?)",
        (upload_id, group, "Jan/2026", "Legacy User"),
    )
    db.execute(
        "INSERT INTO schedule_entries (upload_id, group_name, month_year, schedule_type, sr_no, employee_id, name) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (upload_id, group, "Jan/2026", "income_tax", 1, "E1", "Legacy User"),
    )

    # V2 seed
    db.execute(
        "INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no, reference_no) VALUES (?, ?, ?, ?, ?)",
        (fname, group, "Jan/2026", "B1", "R1"),
    )
    bill_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        """
        INSERT INTO employees_v2 (
            bill_id, source_filename, group_name, month_year, raw_name, normalized_name,
            raw_designation, normalized_designation, gross_amount, sum_deduction, net_total
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bill_id, fname, group, "Jan/2026", "V2 User", "V2 User", "CONSTABLE", "CONSTABLE", 1000, 200, 800),
    )
    employee_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        """
        INSERT INTO employee_components_v2 (
            employee_id, bill_id, component_type, raw_head, normalized_head, amount
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (employee_id, bill_id, "allowance", "Basic", "basic_pay", 1000),
    )
    db.execute(
        """
        INSERT INTO validation_issues_v2 (
            bill_id, employee_id, issue_type, severity, message, raw_value, suggested_value, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bill_id, employee_id, "GROSS_MISMATCH", "HIGH", "m", "1000", "1100", "OPEN"),
    )
    db.execute(
        "INSERT INTO upload_jobs_v2 (source_filename, status, started_at) VALUES (?, 'PROCESSING', CURRENT_TIMESTAMP)",
        (fname,),
    )

    db.commit()
    db.close()

    client = app.test_client()
    resp = client.post("/api/delete_group", json={"group_name": group})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "deleted_counts" in payload

    db = sqlite3.connect(app.config["DATABASE"])
    assert db.execute("SELECT COUNT(*) FROM employees WHERE group_name = ?", (group,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM uploads WHERE group_name = ?", (group,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM schedule_entries WHERE group_name = ?", (group,)).fetchone()[0] == 0

    assert db.execute("SELECT COUNT(*) FROM bills_v2 WHERE group_name = ?", (group,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM employees_v2 WHERE group_name = ?", (group,)).fetchone()[0] == 0
    assert (
        db.execute(
            """
            SELECT COUNT(*) FROM employee_components_v2 c
            JOIN employees_v2 e ON c.employee_id = e.id
            WHERE e.group_name = ?
            """,
            (group,),
        ).fetchone()[0]
        == 0
    )
    assert (
        db.execute(
            """
            SELECT COUNT(*) FROM validation_issues_v2 v
            JOIN bills_v2 b ON v.bill_id = b.id
            WHERE b.group_name = ?
            """,
            (group,),
        ).fetchone()[0]
        == 0
    )
    assert db.execute("SELECT COUNT(*) FROM upload_jobs_v2 WHERE source_filename = ?", (fname,)).fetchone()[0] == 0
    db.close()
