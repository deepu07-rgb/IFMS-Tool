import os
import sqlite3
import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema

pytestmark = pytest.mark.v2


def _setup_pdf1(tmp_path):
    db_path = tmp_path / "pdf1_components.db"
    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    pdf_path = os.path.join("test_fixtures", "ifms_inner_sheets", "1.pdf")
    process_file_v2(pdf_path, "1.pdf", dict(app.config))
    return db_path


def test_pdf1_components_dictionary_schedule(tmp_path):
    _setup_pdf1(tmp_path)
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row

    bill = db.execute(
        """SELECT group_name, parsed_gross, parsed_deduction, parsed_net,
                  official_gross, official_deduction, official_net
           FROM bills_v2 WHERE source_filename='1.pdf'
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    emp_count = db.execute("SELECT COUNT(*) FROM employees_v2 WHERE source_filename='1.pdf'").fetchone()[0]
    assert bill["group_name"] == "Khandafalsa"
    assert emp_count == 36
    assert round(bill["parsed_gross"]) == 2707921
    assert round(bill["parsed_deduction"]) == 572559
    assert round(bill["parsed_net"]) == 2135362

    heads = {r[0] for r in db.execute("SELECT DISTINCT normalized_head FROM employee_components_v2").fetchall()}
    for h in ["basic_pay", "da", "hra", "gpf", "gpf_2004", "lic", "sip", "rghs"]:
        assert h in heads

    db.close()

    client = app.test_client()
    emp_res = client.get("/api/employees?group=Khandafalsa&page=1&per_page=50")
    assert emp_res.status_code == 200
    payload = emp_res.get_json()
    assert payload["total"] == 36
    assert any((e.get("basic", 0) or 0) > 0 for e in payload["employees"])
    assert any((e.get("da", 0) or 0) > 0 for e in payload["employees"])
    assert any((e.get("hra", 0) or 0) > 0 for e in payload["employees"])

    lic_res = client.get("/api/schedule_entries?schedule_type=lic&page=1&per_page=200")
    assert lic_res.status_code == 200
    lic = lic_res.get_json()
    assert lic["total"] > 0
    assert any(e.get("source_type") == "derived_from_inner_sheet" for e in lic["entries"])

    gpf_res = client.get("/api/schedule_entries?schedule_type=gpf&page=1&per_page=200")
    assert gpf_res.status_code == 200
    gpf = gpf_res.get_json()
    assert gpf["total"] > 0
    assert any(e.get("source_type") == "derived_from_inner_sheet" for e in gpf["entries"])

    gpf2004_res = client.get("/api/schedule_entries?schedule_type=gpf_2004&page=1&per_page=200")
    assert gpf2004_res.status_code == 200
    gpf2004 = gpf2004_res.get_json()
    assert gpf2004["total"] > 0

    an_res = client.get("/api/v2/analytics")
    assert an_res.status_code == 200
    labels = {d["name"] for d in an_res.get_json().get("designations", [])}
    allowed = {"Constable", "Head Constable", "Assistant Sub-Inspector", "Sub-Inspector", "Inspector", "Class IV", "Unmapped"}
    assert labels.issubset(allowed)
