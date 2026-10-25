import os
import re
import sqlite3

import pytest

from app import app, init_db
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
LONG_NUMBER_RE = re.compile(r"\b\d{7,}\b")


def _setup(tmp_path):
    db_path = tmp_path / "dictionary_reset_cleanup.db"
    app.config["DATABASE"] = str(db_path)
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


def _seed_dictionary(db_path):
    db = sqlite3.connect(db_path)
    rows = [
        (
            "designation",
            "IPS, JUNIOR SCALE (ASSISTANT COMMISSIONER OF POLICE-à¤¸à¤¹à¤¾à¤¯à¤• à¤ªà¥à¤²à¤¿à¤¸ à¤†à¤¯à¥à¤•à¥à¤¤ (2055001091001))",
            "",
            "IPS",
            "IPS",
            "आई पी एस",
            "contains",
            100,
            1,
        ),
        (
            "designation",
            "IPS, JUNIOR SCALE (ASSISTANT COMMISSIONER OF POLICE-à¤¸à¤¹à¤¾à¤¯à¤• à¤ªà¥à¤²à¤¿à¤¸ à¤†à¤¯à¥à¤•à¥à¤¤ (2055001091001))",
            "",
            "IPS",
            "IPS",
            "आई पी एस",
            "contains",
            90,
            1,
        ),
        (
            "designation",
            "IPS, SENIOR TIME SCALE (DEPUTY POLICE COMMISSIONER-à¤ªà¥à¤²à¤¿à¤¸ à¤‰à¤ªà¤¾à¤¯à¥à¤•à¥à¤¤ (2055001091001))",
            "",
            "IPS",
            "IPS",
            "पुिलस उपायुक",
            "contains",
            100,
            1,
        ),
        (
            "designation",
            "INSPECTOR GENERAL OF POLICE (à¤ªà¥à¤²à¤¿à¤¸ à¤†à¤¯à¥à¤•à¥à¤¤)",
            "",
            "IPS",
            "IPS",
            "आई पी एस",
            "exact",
            100,
            0,
        ),
    ]
    db.executemany(
        """
        INSERT INTO dictionary_mappings_v3 (
            category, raw_text, raw_text_key, final_text, final_text_en, final_text_hi,
            match_type, priority, active
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    db.commit()
    db.close()


def _seed_runtime_data(db_path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute(
        """
        INSERT INTO bills_v2 (source_filename, group_name, month_year, parsed_gross, parsed_deduction, parsed_net)
        VALUES ('sample.pdf', 'TEST GROUP', 'May/2026', 100, 10, 90)
        """
    )
    bill_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        """
        INSERT INTO employees_v2 (
            bill_id, source_filename, page_no, sr_no, group_name, raw_name, employee_id,
            pay_scale_raw, gross_amount, sum_deduction, net_total,
            raw_designation_full, raw_designation_en, raw_designation_key,
            final_designation, final_designation_en, normalized_designation
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            bill_id,
            "sample.pdf",
            1,
            1,
            "TEST GROUP",
            "TEST EMPLOYEE",
            "RJTEST001",
            "L10",
            100,
            10,
            90,
            "IPS, JUNIOR SCALE (पुिलस उपायुक)",
            "IPS, JUNIOR SCALE",
            "IPS JUNIOR SCALE",
            "Needs Review",
            "Needs Review",
            "Needs Review",
        ),
    )
    emp_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        """
        INSERT INTO validation_issues_v2 (bill_id, employee_id, issue_type, severity, message, raw_value, status)
        VALUES (?,?,?,?,?,?,?)
        """,
        (bill_id, emp_id, "UNCONFIRMED_DESIGNATION", "HIGH", "review", "IPS, JUNIOR SCALE", "OPEN"),
    )
    db.execute(
        """
        INSERT INTO review_queue_v3 (
            bill_id, employee_id, source_file, page_no, sr_no, employee_name,
            employee_id_text, field_name, raw_value, issue_type, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (bill_id, emp_id, "sample.pdf", 1, 1, "TEST EMPLOYEE", "RJTEST001", "designation", "IPS, JUNIOR SCALE", "UNCONFIRMED_DESIGNATION", "OPEN"),
    )
    db.commit()
    db.close()


def test_dictionary_sanitize_reset_and_clear_all_cleanup(tmp_path):
    client, db_path = _setup(tmp_path)
    _seed_dictionary(db_path)
    _seed_runtime_data(db_path)

    sanitize = client.post("/api/v3/dictionary/sanitize")
    assert sanitize.status_code == 200
    sanitize_payload = sanitize.get_json()
    assert sanitize_payload["scanned_count"] == 4
    assert sanitize_payload["sanitized_count"] >= 4
    assert sanitize_payload["hindi_removed_count"] >= 1
    assert sanitize_payload["numeric_removed_count"] >= 2
    assert sanitize_payload["duplicate_groups_found"] >= 1
    assert sanitize_payload["duplicates_deactivated"] >= 1

    mappings = _rows(db_path, "SELECT * FROM dictionary_mappings_v3 ORDER BY id")
    for row in mappings:
        assert row["raw_text_key"]
        assert not DEVANAGARI_RE.search(row["raw_text"] or "")
        assert not LONG_NUMBER_RE.search(row["raw_text"] or "")
        assert row["final_text_hi"] == ""

    duplicate_active = _one(
        db_path,
        """
        SELECT COUNT(*) AS c
        FROM (
            SELECT category, raw_text_key, COALESCE(final_text, final_text_en, '') AS final_text,
                   match_type, COUNT(*) AS n
            FROM dictionary_mappings_v3
            WHERE active = 1
            GROUP BY category, raw_text_key, final_text, match_type
            HAVING n > 1
        )
        """,
    )
    assert duplicate_active["c"] == 0

    default_dictionary = client.get("/api/v3/dictionary").get_json()
    assert default_dictionary
    assert all(row["active"] for row in default_dictionary)
    assert all("final_text_hi" not in row for row in default_dictionary)

    all_dictionary = client.get("/api/v3/dictionary?active=all").get_json()
    assert len(all_dictionary) == len(mappings)

    clear = client.post("/api/delete_all")
    assert clear.status_code == 200
    deleted = clear.get_json()["deleted_counts"]
    assert deleted["v2_employees"] == 1
    assert deleted["v2_bills"] == 1
    assert deleted["v2_validation_issues"] == 1
    assert deleted["v3_review_queue"] == 1
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"] == 0
    assert _one(db_path, "SELECT COUNT(*) AS c FROM bills_v2")["c"] == 0
    assert _one(db_path, "SELECT COUNT(*) AS c FROM validation_issues_v2")["c"] == 0
    assert _one(db_path, "SELECT COUNT(*) AS c FROM review_queue_v3")["c"] == 0
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"] == len(mappings)

    # Reset must preserve parsed employee data if it exists.
    _seed_runtime_data(db_path)
    reset = client.post("/api/v3/dictionary/reset")
    assert reset.status_code == 200
    assert reset.get_json()["deleted_count"] == len(mappings)
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3")["c"] == 0
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"] == 1
    assert _one(
        db_path,
        "SELECT COUNT(*) AS c FROM edit_audit_log_v3 WHERE action_type = 'DICTIONARY_RESET'",
    )["c"] >= 1

    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/employees").status_code == 200
    assert client.get("/api/v3/dictionary").status_code == 200
    assert client.get("/api/v3/review_queue").status_code == 200
