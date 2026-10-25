from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

import fitz
import openpyxl
import pytest

from app import app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.official_schedule_compare import (
    init_official_schedule_schema,
    parse_official_pdf,
    schedule_type_from_heading,
)
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "test_fixtures" / "official_schedules"
SAMPLE_1 = FIXTURE_DIR / "schedule_format_sample_1.pdf"
SAMPLES = sorted(FIXTURE_DIR.glob("schedule_format_sample_*.pdf"))


pytestmark = pytest.mark.skipif(not SAMPLE_1.exists(), reason="official schedule PDF fixtures are not available")


def _headings(path: Path) -> list[str]:
    text = "\n".join(page.get_text("text") for page in fitz.open(path))
    return [match.strip() for match in re.findall(r"^\s*Schedule\s+of\s+.+$", text, re.I | re.M)]


def _one(db_path, sql, params=()):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    row = db.execute(sql, params).fetchone()
    db.close()
    return row


def test_detects_all_schedule_headings_from_samples():
    detected = {sample.name: _headings(sample) for sample in SAMPLES}
    assert "Schedule of GPF 2004 (Budget Head 8009-01-101-03-00)" in detected["schedule_format_sample_1.pdf"]
    assert "Schedule of SI Premium (Budget Head 8011-00-105-01-01)" in detected["schedule_format_sample_1.pdf"]
    assert "Schedule of RGHS (Budget Head 8342-00-120-69-00)" in detected["schedule_format_sample_1.pdf"]
    assert "Schedule of Cooperative Account (ROAD WAYS DEDUTION)" in detected["schedule_format_sample_1.pdf"]
    assert "Schedule of Cooperative Account (PPSS JDR)" in detected["schedule_format_sample_1.pdf"]
    assert "Schedule of Advance Salary" in detected["schedule_format_sample_1.pdf"]
    assert "Schedule of Personal Dedcution 2" in detected["schedule_format_sample_2.pdf"]


def test_new_supported_layouts_parse_rows_and_grand_totals():
    parsed = parse_official_pdf(SAMPLE_1, SAMPLE_1.name)
    counts = Counter(row["schedule_type"] for row in parsed["rows"])
    assert counts["gpf_2004"] == 26
    assert counts["si_premium"] == 36
    assert counts["rghs"] == 36
    assert counts["roadways_deduction"] == 36
    assert counts["ppss_jdr"] == 5
    assert counts["advance_salary"] == 5

    sections = {section["schedule_type"]: section for section in parsed["sections"]}
    assert sections["gpf_2004"]["grand_total"] == 66250
    assert sections["si_premium"]["grand_total"] == 306843
    assert sections["rghs"]["grand_total"] == 20633
    assert sections["roadways_deduction"]["grand_total"] == 7200
    assert sections["ppss_jdr"]["grand_total"] == 500
    assert sections["advance_salary"]["grand_total"] == 40489

    rows = parsed["rows"]
    assert all("Grand Total" not in row["employee_name"] for row in rows)
    assert all("Rupees in Words" not in row["raw_text_block"] for row in rows)
    assert any(row["schedule_type"] == "si_premium" and row["policy_no"] for row in rows)
    assert any(row["schedule_type"] == "rghs" and row["basic_pay"] > 0 for row in rows)


def test_existing_supported_layouts_still_parse():
    parsed = parse_official_pdf(SAMPLE_1, SAMPLE_1.name)
    counts = Counter(row["schedule_type"] for row in parsed["rows"])
    assert counts["income_tax"] == 3
    assert counts["lic"] == 44
    assert counts["gpf"] == 10


def test_unknown_or_absent_layout_mappings_are_safe():
    assert schedule_type_from_heading("Schedule of SI Loan (Budget Head 8011-00-105-01-02)") == ("si_loan", "SUPPORTED")
    assert schedule_type_from_heading("Schedule of SII") == ("sii", "SUPPORTED")
    assert schedule_type_from_heading("Schedule of Personal Dedcution 2") == ("personal_dedcution_2", "NEEDS_LAYOUT_MAPPING")
    assert schedule_type_from_heading("Schedule of HBA-HDFC (Budget Head 8443-00-106-00-00)") == ("hba_hdfc", "NEEDS_LAYOUT_MAPPING")


def test_unsupported_sections_remain_visible_for_review():
    parsed = parse_official_pdf(SAMPLE_1, SAMPLE_1.name)
    unsupported = [section for section in parsed["sections"] if section["parse_status"] == "NEEDS_LAYOUT_MAPPING"]
    assert {section["schedule_type"] for section in unsupported} == {"rop"}
    assert all(section["rows_detected"] == 0 for section in unsupported)


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "official_layout_expansion.db"
    upload_dir = tmp_path / "uploads"
    official_dir = upload_dir / "official_schedules"
    export_dir = tmp_path / "exports"
    upload_dir.mkdir()
    official_dir.mkdir()
    export_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["OFFICIAL_SCHEDULE_UPLOAD_FOLDER"] = str(official_dir)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    init_db()
    init_v2_schema(str(db_path))
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    init_schedule_mapping_schema(db)
    init_official_schedule_schema(db)
    bill_id = db.execute("""
        INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no, bill_date)
        VALUES ('schedule_format_sample_1.pdf', 'Official Sample', 'May/2026', '509166102', '01/06/2026')
    """).lastrowid
    emp_id = db.execute("""
        INSERT INTO employees_v2 (
            bill_id, source_filename, page_no, sr_no, group_name, month_year,
            raw_name, normalized_name, final_designation_en, employee_id,
            gross_amount, sum_deduction, net_total, employee_data_status
        ) VALUES (?, 'schedule_format_sample_1.pdf', 9, 1, 'Official Sample', 'May/2026',
            'ARJUN  RAM', 'ARJUN RAM', 'Head Constable', 'RJJO200324005053',
            0, 0, 0, 'VERIFIED')
    """, (bill_id,)).lastrowid
    db.execute("""
        INSERT INTO employee_components_v2 (
            employee_id, bill_id, component_type, raw_head, normalized_head, amount, included_in_total, mapping_status, confidence
        ) VALUES (?, ?, 'deduction', 'RGHS', 'rghs', 658, 1, 'mapped', 1)
    """, (emp_id, bill_id))
    db.commit()
    db.close()
    with app.test_client() as test_client:
        yield test_client


def _upload(client):
    with SAMPLE_1.open("rb") as handle:
        response = client.post(
            "/api/v3/official_schedules/upload",
            data={"file": (handle, "schedule_format_sample_1.pdf")},
            content_type="multipart/form-data",
        )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_comparison_for_new_supported_layout_export_and_safety(client):
    payload = _upload(client)
    db_path = app.config["DATABASE"]
    before_employees = _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"]
    before_components = _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"]

    response = client.post(
        "/api/v3/official_schedules/compare",
        json={"upload_id": payload["upload_id"], "schedule_type": "rghs"},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    comparison = response.get_json()["comparison"]
    assert "MATCHED" in {row["match_status"] for row in comparison}
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employees_v2")["c"] == before_employees
    assert _one(db_path, "SELECT COUNT(*) AS c FROM employee_components_v2")["c"] == before_components

    export = client.post("/api/v3/official_schedules/export", json={"upload_id": payload["upload_id"], "schedule_type": "rghs"})
    assert export.status_code == 200
    generated = sorted(Path(app.config["EXPORT_FOLDER"]).glob("Official_Schedule_Comparison_*.xlsx"))
    workbook = openpyxl.load_workbook(generated[-1], read_only=True)
    assert "Unsupported Sections" in workbook.sheetnames


def test_official_schedule_ui_label_has_no_mojibake(client):
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert "Official Schedule Comparison" in html
    for bad in ("\u00c3\u00a2", "\u00c3\u0192", "\ufffd"):
        assert bad not in html
