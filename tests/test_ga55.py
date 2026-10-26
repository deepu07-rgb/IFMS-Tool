from ifms_suite.documents import parse_ga55
from decimal import Decimal


def test_ga55_groups_payment_types_and_signed_components():
    text = """Employee ID\n:\nRJ1\nMarch\n2025\nRegular\nSalary\n123456789\nBasic\n50000.00\nDA\n26500.00\nROP\n-500.00\n76,000.00\nGPF\n1000.00\n1,000.00\n75,000.00\nMay\n2025\nDA\n234567890\nDA\n3000.00\n3,000.00\nGPF\n3000.00\n3,000.00\n0.00\nTotal Allowances"""
    r = parse_ga55([text])
    assert len(r["payments"]) == 2
    assert r["payments"][0]["bill_type"] == "Regular Salary"
    assert r["payments"][0]["allowances"]["ROP"] == "-500.00"
    assert r["payments"][1]["bill_type"] == "DA"
    assert r["payments"][1]["entitlement_period"] is None
    assert r["requires_review"] is True


def test_page_header_removed_from_continuation():
    a = "March\n2025\nRegular Salary\n123456789\nBasic\n50000.00\n50,000.00\nGPF\n1000.00\n1,000.00\n49,000.00"
    b = "RAJ IFMS 3.0\nGovernment Of Rajasthan\nGA55 A\nPage No.\n2\nHRA\n10000.00\nApril\n2025\nDA\n234567890\nDA\n1000.00\n1,000.00\nGPF\n1000.00\n1,000.00\n0.00\nTotal Allowances"
    r = parse_ga55([a, b])
    assert len(r["payments"]) == 2
    assert r["payments"][0]["source_pages"] == [1, 2]


def test_ga55_total_mismatch_is_visible_and_printed_totals_retained():
    text = "March\n2025\nRegular Salary\n123456789\nBasic\n50000.00\nDA\n26500.00\n76,500.00\nGPF\n1000.00\n2,000.00\n74,500.00\nTotal Allowances"
    r = parse_ga55([text])["payments"][0]
    assert r["printed_gross"] == "76500.00"
    assert r["printed_deductions"] == "2000.00"
    assert any("deduction" in i.lower() for i in r["issues"])


def test_multi_employee_document_keeps_identity_per_payment():
    one = "Employee ID\n:\nRJJO199324003478\nMarch\n2025\nRegular Salary\n123456789\nBasic\n50000.00\n50,000.00\nGPF\n1000.00\n1,000.00\n49,000.00\nTotal Allowances"
    two = one.replace("RJJO199324003478", "RJJO200324004061").replace(
        "123456789", "234567890"
    )
    rows = parse_ga55([one, two])["payments"]
    assert rows[0]["employee_code"] == "RJJO199324003478"
    assert rows[1]["employee_code"] == "RJJO200324004061"
