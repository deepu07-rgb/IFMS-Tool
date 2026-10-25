import os
import json
import pytest
from parser import parse_inner_sheet

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_fixtures', 'ifms_inner_sheets')

with open(os.path.join(FIXTURE_DIR, 'expected_bill_totals.json'), 'r') as f:
    EXPECTED_TOTALS = json.load(f)

@pytest.mark.parametrize("pdf_name, expected", EXPECTED_TOTALS.items())
def test_expected_totals(pdf_name, expected):
    pdf_path = os.path.join(PDF_DIR, pdf_name)
    assert os.path.exists(pdf_path), f"Test PDF not found: {pdf_path}"
    
    header, employees, grand_totals = parse_inner_sheet(pdf_path)
    
    # Calculate parsed totals
    parsed_gross = sum(e.get('gross_amount', 0) or 0 for e in employees)
    parsed_ded = sum(e.get('sum_deduction', 0) or 0 for e in employees)
    parsed_net = sum(e.get('net_total', 0) or 0 for e in employees)
    
    assert len(employees) == expected['employees'], f"Employee count mismatch for {pdf_name}"
    assert parsed_gross == expected['gross'], f"Gross total mismatch for {pdf_name}"
    assert parsed_ded == expected['deduction'], f"Deduction total mismatch for {pdf_name}"
    assert parsed_net == expected['net'], f"Net total mismatch for {pdf_name}"
