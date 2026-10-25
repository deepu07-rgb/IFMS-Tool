import sqlite3

from app import app
from ifms_engine.db import init_v2_schema


def test_v2_issue_resolve_sets_resolved_at(tmp_path):
    db_path = tmp_path / "smoke_ifms.db"
    app.config["DATABASE"] = str(db_path)
    init_v2_schema(app.config["DATABASE"])

    db = sqlite3.connect(app.config["DATABASE"])
    db.execute(
        """
        INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no, reference_no)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("smoke.pdf", "TEST GROUP", "January/2026", "B1", "R1"),
    )
    bill_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    db.execute(
        """
        INSERT INTO employees_v2 (
            bill_id, source_filename, raw_name, normalized_name, raw_designation,
            normalized_designation, gross_amount, sum_deduction, net_total
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bill_id, "smoke.pdf", "Smoke User", "Smoke User", "CONSTABLE", "CONSTABLE", 1000, 200, 800),
    )
    employee_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    db.execute(
        """
        INSERT INTO validation_issues_v2 (
            bill_id, employee_id, issue_type, severity, message, raw_value, suggested_value, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (bill_id, employee_id, "GROSS_MISMATCH", "HIGH", "Smoke mismatch", "1000", "1100", "OPEN"),
    )
    issue_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()

    client = app.test_client()
    resp = client.post("/api/v2/issues/resolve", json={"issue_id": issue_id, "new_value": 1100})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"

    db = sqlite3.connect(app.config["DATABASE"])
    row = db.execute(
        "SELECT status, resolved_at FROM validation_issues_v2 WHERE id = ?",
        (issue_id,),
    ).fetchone()
    db.close()

    assert row is not None
    assert row[0] == "RESOLVED"
    assert row[1] is not None
