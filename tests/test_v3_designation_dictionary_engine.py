import os
import re
import sqlite3

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema
from ifms_engine.dictionary import clean_designation_key, extract_english_designation


pytestmark = pytest.mark.v2

PDF10 = os.path.join("test_fixtures", "ifms_inner_sheets", "10.pdf")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
LONG_NUMBER_RE = re.compile(r"\b\d{7,}\b")


def _setup(tmp_path):
    db_path = tmp_path / "v3_designation_engine.db"
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


def _add_mapping(client, raw_text, final_text="IPS", apply_existing=False):
    resp = client.post(
        "/api/v2/dictionary",
        json={
            "category": "designation",
            "raw_text": raw_text,
            "final_text": final_text,
            "match_type": "contains",
            "priority": 100,
            "active": 1,
            "apply_existing": apply_existing,
        },
    )
    assert resp.status_code == 200
    return resp.get_json()["id"]


def test_english_designation_cleaners_strip_hindi_mojibake_and_long_numbers():
    raw = (
        "IPS, JUNIOR SCALE (ASSISTANT COMMISSIONER OF POLICE-"
        "à¤¸à¤¹à¤¾à¤¯à¤• à¤ªà¥à¤²à¤¿à¤¸ à¤†à¤¯à¥à¤•à¥à¤¤ (2055001091001))"
    )
    assert extract_english_designation(raw) == "IPS, JUNIOR SCALE (ASSISTANT COMMISSIONER OF POLICE)"
    assert clean_designation_key("IPS, Junior-Scale") == clean_designation_key("ips junior scale")
    assert clean_designation_key(raw) == "IPS JUNIOR SCALE ASSISTANT COMMISSIONER OF POLICE"


def test_v3_designation_dictionary_english_only_engine(tmp_path):
    client, db_path = _setup(tmp_path)
    _process_pdf10()

    watched = {
        "PRATEEK SINGH",
        "KAMAL SHEKHAWAT",
        "SHARAT KAVIRAJ IPS",
        "SHAHEEN C",
        "MANISH KUMAR CHOUDHARY",
    }
    rows = _rows(
        db_path,
        """
        SELECT raw_name, raw_designation_full, raw_designation_en, raw_designation_key,
               final_designation, final_designation_en, designation_needs_review
        FROM employees_v2
        WHERE raw_name IN (?,?,?,?,?)
        """,
        tuple(watched),
    )
    by_name = {r["raw_name"]: r for r in rows}
    assert watched <= set(by_name)
    for name in watched:
        row = by_name[name]
        assert row["raw_designation_full"]
        assert row["raw_designation_en"]
        assert not DEVANAGARI_RE.search(row["raw_designation_en"])
        assert not LONG_NUMBER_RE.search(row["raw_designation_en"])
        assert row["raw_designation_key"] == clean_designation_key(row["raw_designation_en"])
        assert row["final_designation"] == "Needs Review"
        assert row["final_designation_en"] == "Needs Review"
        assert row["designation_needs_review"] == 1

    junior_id = _add_mapping(client, "IPS, JUNIOR SCALE")
    apply = client.post("/api/v3/dictionary/apply", json={"mapping_id": junior_id})
    assert apply.status_code == 200
    assert apply.get_json()["matched_count"] >= 3
    assert apply.get_json()["resolved_issue_count"] >= 3

    for name in ("PRATEEK SINGH", "KAMAL SHEKHAWAT", "SHAHEEN C"):
        row = _one(db_path, "SELECT final_designation, final_designation_en, designation_needs_review FROM employees_v2 WHERE raw_name = ?", (name,))
        assert row["final_designation"] == "IPS"
        assert row["final_designation_en"] == "IPS"
        assert row["designation_needs_review"] == 0

    employee_payload = client.get("/api/employees?designation_language=hindi&page=1&per_page=50").get_json()
    api_rows = {r["employee_name"]: r for r in employee_payload["employees"]}
    assert api_rows["PRATEEK SINGH"]["designation"] == "IPS"
    assert api_rows["PRATEEK SINGH"]["final_designation_hi"] == ""

    assert _one(
        db_path,
        """
        SELECT COUNT(*) AS c
        FROM validation_issues_v2 v
        JOIN employees_v2 e ON e.id = v.employee_id
        WHERE v.issue_type = 'UNCONFIRMED_DESIGNATION'
          AND COALESCE(v.status, 'OPEN') != 'RESOLVED'
          AND e.raw_designation_full LIKE '%IPS, JUNIOR SCALE%'
        """,
    )["c"] == 0

    senior_id = _add_mapping(client, "IPS, SENIOR TIME SCALE")
    assert client.post("/api/v3/dictionary/apply", json={"mapping_id": senior_id}).status_code == 200
    assert _one(db_path, "SELECT final_designation FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'")["final_designation"] == "IPS"

    igp_id = _add_mapping(client, "INSPECTOR GENERAL OF POLICE")
    assert client.post("/api/v3/dictionary/apply", json={"mapping_id": igp_id}).status_code == 200
    assert _one(db_path, "SELECT final_designation FROM employees_v2 WHERE raw_name = 'SHARAT KAVIRAJ IPS'")["final_designation"] == "IPS"

    assert client.post("/api/delete_all").status_code == 200
    assert _one(db_path, "SELECT COUNT(*) AS c FROM dictionary_mappings_v3 WHERE category = 'designation'")["c"] >= 3
    _process_pdf10()
    assert _one(db_path, "SELECT final_designation FROM employees_v2 WHERE raw_name = 'PRATEEK SINGH'")["final_designation"] == "IPS"
    assert _one(db_path, "SELECT final_designation FROM employees_v2 WHERE raw_name = 'MANISH KUMAR CHOUDHARY'")["final_designation"] == "IPS"
    assert _one(db_path, "SELECT final_designation FROM employees_v2 WHERE raw_name = 'SHARAT KAVIRAJ IPS'")["final_designation"] == "IPS"

    assert client.post("/api/v3/dictionary/deactivate", json={"mapping_id": junior_id}).status_code == 200
    assert client.post("/api/delete_all").status_code == 200
    _process_pdf10()
    junior_rows = _rows(
        db_path,
        """
        SELECT final_designation, designation_needs_review
        FROM employees_v2
        WHERE raw_designation_full LIKE '%IPS, JUNIOR SCALE%'
        """,
    )
    assert junior_rows
    assert all(r["final_designation"] == "Needs Review" for r in junior_rows)
    assert all(r["designation_needs_review"] == 1 for r in junior_rows)

    dup_1 = _add_mapping(client, "IPS, JUNIOR SCALE")
    dup_2 = _add_mapping(client, "IPS, JUNIOR SCALE")
    assert dup_1 == dup_2
    assert _one(
        db_path,
        """
        SELECT COUNT(*) AS c
        FROM dictionary_mappings_v3
        WHERE category = 'designation'
          AND raw_text_key = ?
          AND COALESCE(final_text, final_text_en) = 'IPS'
          AND match_type = 'contains'
          AND active = 1
        """,
        (clean_designation_key("IPS, JUNIOR SCALE"),),
    )["c"] == 1

    dictionary_payload = client.get("/api/v2/dictionary").get_json()
    junior = [d for d in dictionary_payload if d["id"] == dup_1][0]
    assert junior["final_text"] == "IPS"
    assert junior["final_text_hi"] == ""
