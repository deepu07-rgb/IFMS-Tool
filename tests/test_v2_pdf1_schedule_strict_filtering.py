import os
import sqlite3

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema

pytestmark = pytest.mark.v2


def _setup_pdf(tmp_path, pdf_name, db_name):
    db_path = tmp_path / db_name
    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    process_file_v2(os.path.join("test_fixtures", "ifms_inner_sheets", pdf_name), pdf_name, dict(app.config))
    return app.test_client()


def _setup_pdf1(tmp_path):
    return _setup_pdf(tmp_path, "1.pdf", "pdf1_schedule_strict.db")


def _schedule(client, schedule_type):
    res = client.get(f"/api/schedule_entries?schedule_type={schedule_type}&page=1&per_page=500")
    assert res.status_code == 200
    return res.get_json()


def test_pdf1_strict_derived_schedule_filtering_and_identity(tmp_path):
    client = _setup_pdf1(tmp_path)

    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    bill = db.execute(
        """SELECT parsed_gross, parsed_deduction, parsed_net
           FROM bills_v2 WHERE source_filename='1.pdf'
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert db.execute("SELECT COUNT(*) FROM employees_v2").fetchone()[0] == 36
    assert round(bill["parsed_gross"]) == 2707921
    assert round(bill["parsed_deduction"]) == 572559
    assert round(bill["parsed_net"]) == 2135362
    db.close()

    expectations = {
        "lic": "lic",
        "gpf": "gpf",
        "gpf_2004": "gpf_2004",
    }
    for schedule_type, head in expectations.items():
        payload = _schedule(client, schedule_type)
        rows = payload["entries"]
        assert payload["total"] > 0
        assert rows
        assert all(r["normalized_head"] == head for r in rows)
        assert payload["summary"]["grand_total"] == sum(r["component_amount"] for r in rows)
        assert all(r["total"] == r["component_amount"] for r in rows)
        assert any(r["employee_id"] for r in rows)
        assert all(r["source_type"] == "derived_from_inner_sheet" for r in rows)
        assert all(r["source_file"] == "1.pdf" for r in rows)
        assert all(r["source_page"] > 0 for r in rows)

    rop = _schedule(client, "rop")
    assert rop["total"] == 0
    assert rop["summary"]["grand_total"] == 0
    assert rop["entries"] == []

    for noisy_type in ["lic", "gpf", "si_premium", "rghs", "cooperative_roadways"]:
        rop_check = _schedule(client, "rop")
        assert not any(r.get("normalized_head") == noisy_type for r in rop_check["entries"])

    emp_res = client.get("/api/employees?group=Khandafalsa&page=1&per_page=100")
    assert emp_res.status_code == 200
    employees = emp_res.get_json()["employees"]
    forbidden_suffixes = (
        " CONSTABLE",
        " HEAD CONSTABLE",
        " ASSISTANT SUB-INSPECTOR",
        " SUB-INSPECTOR",
        " INSPECTOR",
    )
    assert all(not e["name"].upper().endswith(forbidden_suffixes) for e in employees)

    analytics = client.get("/api/v2/analytics").get_json()
    labels = {d["name"] for d in analytics["designations"]}
    allowed = {"Constable", "Head Constable", "Assistant Sub-Inspector", "Sub-Inspector", "Inspector", "Class IV", "Unmapped"}
    assert labels.issubset(allowed)


def test_new_rt_rop_schedule_keeps_negative_amounts(tmp_path):
    pdf_path = os.path.join("test_fixtures", "ifms_inner_sheets", "14.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("14.pdf / NEW RT 2025 sample is not available")

    client = _setup_pdf(tmp_path, "14.pdf", "pdf14_rop_schedule.db")
    rop = _schedule(client, "rop")

    rows = rop["entries"]
    assert rop["total"] > 0
    assert rows
    assert all(r["normalized_head"] == "rop" for r in rows)
    assert all(r["component_amount"] != 0 for r in rows)
    assert any(r["component_amount"] < 0 for r in rows)
    assert rop["summary"]["grand_total"] == sum(r["component_amount"] for r in rows)
    assert rop["summary"]["grand_total"] < 0
    assert {-521.0, -3768.0}.issubset({r["component_amount"] for r in rows})
