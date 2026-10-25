from __future__ import annotations

from pathlib import Path

import pytest

from ifms_engine.official_schedule_compare import classify_pdf, parse_official_pdf


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "test_fixtures" / "official_schedules"
SAMPLE_1 = FIXTURE_DIR / "schedule_format_sample_1.pdf"
INNER_SHEET = Path(__file__).resolve().parents[1] / "test_fixtures" / "ifms_inner_sheets" / "1.pdf"


pytestmark = pytest.mark.skipif(not SAMPLE_1.exists(), reason="official schedule PDF fixtures are not available")


def test_sample_1_detects_supported_official_schedule_sections():
    parsed = parse_official_pdf(SAMPLE_1, SAMPLE_1.name)
    assert parsed["classification"] == "official_schedule"

    sections = {section["schedule_type"]: section for section in parsed["sections"]}
    assert sections["income_tax"]["parse_status"] == "SUPPORTED"
    assert sections["lic"]["parse_status"] == "SUPPORTED"
    assert sections["gpf"]["parse_status"] == "SUPPORTED"
    assert sections["gpf_2004"]["parse_status"] == "SUPPORTED"
    assert sections["si_premium"]["parse_status"] == "SUPPORTED"
    assert sections["rghs"]["parse_status"] == "SUPPORTED"
    assert sections["roadways_deduction"]["parse_status"] == "SUPPORTED"
    assert sections["ppss_jdr"]["parse_status"] == "SUPPORTED"
    assert sections["advance_salary"]["parse_status"] == "SUPPORTED"

    assert sections["income_tax"]["bill_no"] == "509166102"
    assert sections["income_tax"]["month_year"] == "May/2026"
    assert sections["income_tax"]["grand_total"] == 26000
    assert sections["lic"]["grand_total"] == 52833


def test_sample_1_parses_rows_and_preserves_layout_boundaries():
    parsed = parse_official_pdf(SAMPLE_1, SAMPLE_1.name)
    rows = parsed["rows"]
    income_tax = [row for row in rows if row["schedule_type"] == "income_tax"]
    lic = [row for row in rows if row["schedule_type"] == "lic"]
    gpf = [row for row in rows if row["schedule_type"] == "gpf"]

    assert len(income_tax) == 3
    assert len(lic) == 44
    assert len(gpf) == 10
    assert income_tax[0]["employee_id"] == "RJHA199616019828"
    assert income_tax[0]["pan"] == "ADOPR5112M"
    assert income_tax[0]["total_amount"] == 15000
    assert gpf[0]["gpf_no"] == "1012187"

    lic_employee_ids = [row["employee_id"] for row in lic]
    assert lic_employee_ids.count("RJHA199616019828") > 1
    assert all("Grand Total" not in row["employee_name"] for row in rows)
    assert all("Rupees in Words" not in row["raw_text_block"] for row in rows)


def test_unsupported_sections_are_detected_without_parsing_as_employee_rows():
    parsed = parse_official_pdf(SAMPLE_1, SAMPLE_1.name)
    unsupported = [section for section in parsed["sections"] if section["parse_status"] == "NEEDS_LAYOUT_MAPPING"]
    assert unsupported
    assert any(section["schedule_type"] == "rop" for section in unsupported)
    assert all(section["rows_detected"] == 0 for section in unsupported)


def test_inner_sheet_pdf_is_classified_separately():
    if not INNER_SHEET.exists():
        pytest.skip("inner sheet fixture missing")
    assert classify_pdf(INNER_SHEET)["classification"] == "inner_sheet"
