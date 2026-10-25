import importlib
import os
import sqlite3

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


def _first_fixture_pdf():
    fixture_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "test_fixtures",
        "ifms_inner_sheets",
    )
    if not os.path.isdir(fixture_dir):
        return None
    pdfs = sorted(
        [f for f in os.listdir(fixture_dir) if f.lower().endswith(".pdf")]
    )
    if not pdfs:
        return None
    return os.path.join(fixture_dir, pdfs[0]), pdfs[0]


def test_v2_pipeline_smoke(tmp_path):
    # 1) app import smoke
    mod = importlib.import_module("app")
    assert hasattr(mod, "app")

    # 2) Isolated DB + export folder for this smoke test
    db_path = tmp_path / "v2_pipeline_smoke.db"
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    app.config["DATABASE"] = str(db_path)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    app.config["USE_V2_PARSER"] = True

    init_db()
    init_v2_schema(app.config["DATABASE"])

    # 3) Verify key V2 tables exist
    db = sqlite3.connect(app.config["DATABASE"])
    tables = {
        r[0]
        for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "bills_v2" in tables
    assert "employees_v2" in tables
    assert "employee_components_v2" in tables
    assert "validation_issues_v2" in tables
    assert "upload_jobs_v2" in tables
    db.close()

    # 4) Parse one real fixture PDF through active V2 processing function
    fixture = _first_fixture_pdf()
    if fixture is None:
        # Fixture availability is environment-dependent; skip cleanly if absent.
        # TODO: In CI, ensure test_fixtures are always present.
        return

    fpath, fname = fixture
    process_file_v2(fpath, fname, dict(app.config))

    db = sqlite3.connect(app.config["DATABASE"])
    bill_count = db.execute("SELECT COUNT(*) FROM bills_v2").fetchone()[0]
    emp_count = db.execute("SELECT COUNT(*) FROM employees_v2").fetchone()[0]
    assert bill_count >= 1 or emp_count >= 1

    # 5) Export endpoint smoke
    # TODO: Parser totals/accuracy are covered by dedicated regression tests later.
    # This smoke only verifies endpoint execution path and no crash.
    if emp_count == 0:
        db.execute(
            """
            INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no, reference_no)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fname, "SMOKE_GROUP", "Jan/2026", "B1", "R1"),
        )
        bill_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            """
            INSERT INTO employees_v2 (
                bill_id, source_filename, group_name, month_year,
                raw_name, normalized_name, raw_designation, normalized_designation,
                gross_amount, sum_deduction, net_total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bill_id,
                fname,
                "SMOKE_GROUP",
                "Jan/2026",
                "Smoke User",
                "Smoke User",
                "CONSTABLE",
                "CONSTABLE",
                1000,
                200,
                800,
            ),
        )
        emp_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            """
            INSERT INTO employee_components_v2 (
                employee_id, bill_id, component_type, raw_head, normalized_head, amount
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (emp_id, bill_id, "allowance", "Basic", "basic_pay", 1000),
        )
        db.commit()
    else:
        db.commit()
    db.close()

    client = app.test_client()
    resp = client.get("/api/export")
    assert resp.status_code == 200
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        in resp.content_type
    )
