import shutil
import pytest


def test_column_ocr_preserves_salary_heads_and_requires_review():
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract unavailable")
    import pymupdf
    from ifms_suite.ga55_table_ocr import parse_scanned_ga55_tables

    d = pymupdf.open()
    p = d.new_page(width=1000, height=700)
    for x, y, t in [
        (350, 50, "Government Of Rajasthan GA55 A"),
        (45, 300, "July"),
        (45, 315, "2026"),
        (125, 300, "Regular"),
        (125, 315, "Salary"),
        (180, 300, "510098131"),
        (305, 285, "Basic 53900.00"),
        (305, 305, "HRA 10780.00"),
        (305, 325, "Mess All 2850.00"),
        (425, 285, "DA 32340.00"),
        (425, 305, "CCA 620.00"),
        (425, 325, "HDA 7187.00"),
        (555, 285, "107677.00"),
        (850, 285, "21025.00"),
        (920, 285, "86652.00"),
    ]:
        p.insert_text((x, y), t, fontsize=10)
    data = d.tobytes()
    d.close()
    r = parse_scanned_ga55_tables(data)
    assert len(r["payments"]) == 1
    payment = r["payments"][0]
    assert payment["pay_month"] == "2026-07"
    assert payment["allowances"]["HRA"] == "10780.00"
    assert payment["allowances"]["Basic"] == "53900.00"
    assert r["calculation_ready"] is False
    assert payment["requires_review"] is True


from test_suite_workflow import client
from ifms_suite.storage import database


def test_column_candidates_cannot_be_approved_without_printed_totals(client):
    import json

    with client.application.app_context(), database() as db:
        id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            (
                "synthetic",
                "synthetic.pdf",
                json.dumps({"ga55": {"layout": "GA55 A column OCR"}}),
            ),
        ).lastrowid
    p = dict(
        employee_code="TEST",
        reviewed=True,
        payments=[
            dict(
                bill_no="B1",
                pay_month="2026-07",
                bill_type="Regular Salary",
                allowances={"Basic": "1000"},
                deductions={"GPF": "100"},
            )
        ],
    )
    assert client.post(f"/suite/api/imports/{id}/review", json=p).status_code == 400
    p["payments"][0].update(
        printed_gross="1000", printed_deductions="100", printed_net="900"
    )
    assert client.post(f"/suite/api/imports/{id}/review", json=p).status_code == 200


def test_monetary_ocr_repairs_are_explicit_candidates_not_silent_values():
    from ifms_suite.ga55_table_ocr import _heads

    values, issues = _heads("Basic $3900.00\nDA 3234000\nHRA 10780.00")
    assert values["Basic"] == "53900.00" and values["DA"] == "32340.00"
    assert any("$3900.00" in issue for issue in issues)
    assert any("3234000" in issue for issue in issues)


def test_unreadable_month_does_not_hide_a_surrender_bill():
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract unavailable")
    import pymupdf
    from ifms_suite.ga55_table_ocr import parse_scanned_ga55_tables

    d = pymupdf.open()
    p = d.new_page(width=1000, height=700)
    for x, y, t in [
        (350, 50, "Government Of Rajasthan GA55 A"),
        (115, 300, "Surrender"),
        (180, 300, "508366351"),
        (305, 285, "Basic 26950.00"),
        (425, 285, "DA 15631.00"),
        (555, 285, "42581.00"),
    ]:
        p.insert_text((x, y), t, fontsize=10)
    data = d.tobytes()
    d.close()
    r = parse_scanned_ga55_tables(data)
    assert len(r["payments"]) == 1
    assert r["payments"][0]["pay_month"] == ""
    assert r["payments"][0]["payment_class"] == "leave_encashment"


def test_guessed_digits_are_not_financial_values_without_gross_reconciliation():
    from ifms_suite.ga55_table_ocr import select_reconciled_heads

    heads = {"Basic": "539000.00", "DA": "31262.00"}
    issues = ["Verify OCR monetary correction Basic: $39000.00 -> 539000.00"]
    values, suggestions = select_reconciled_heads(heads, issues, "106509.00")
    assert "Basic" not in values
    assert suggestions["Basic"] == "539000.00"
