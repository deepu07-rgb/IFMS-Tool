"""Synthetic bill data only."""

from copy import deepcopy
from io import BytesIO

import pymupdf
from openpyxl import load_workbook


def synthetic_bill():
    return {
        "status": "ready",
        "mode": "human_assisted",
        "reviewed": True,
        "rows": [
            {
                "month": month,
                "days": days,
                "month_days": 31,
                "components": [
                    {
                        "head": "Basic",
                        "due": "1100.00",
                        "drawn": "1000.00",
                        "prior_settlement": "10.00",
                        "difference": "90.00",
                        "segments": [
                            {
                                "start": "2026-01-16",
                                "end": "2026-01-31",
                                "days": 16,
                                "rate": "50",
                                "reference": "Synthetic rate order",
                            }
                        ],
                        "evidence": [{"page": 3, "bill_no": "Synthetic source"}],
                    },
                    {
                        "head": "RECOVERY",
                        "due": "-20.00",
                        "drawn": "-15.00",
                        "prior_settlement": "0.00",
                        "difference": "-5.00",
                        "segments": [],
                        "evidence": [],
                    },
                    {
                        "head": "CCA",
                        "due": "25.00",
                        "drawn": "20.00",
                        "prior_settlement": "0.00",
                        "difference": "5.00",
                        "segments": [],
                        "evidence": [],
                    },
                ],
            }
            for month, days in [("2026-01", 16), ("2026-02", 28)]
        ],
        "totals": {
            "due": "2210.00",
            "drawn": "2010.00",
            "prior_settlement": "20.00",
            "difference": "180.00",
            "extra_deductions": "10.00",
            "net_payable": "170.00",
        },
        "extra_deductions": [
            {
                "name": "Synthetic tax",
                "amount": "10.00",
                "reference": "Synthetic instruction",
            }
        ],
        "blockers": [],
        "comparison": {"issues": ["Synthetic statement mismatch"]},
    }


def test_excel_preserves_months_all_heads_negative_numbers_and_audit_details():
    from ifms_suite.bill_exports import export_bill_excel

    bill = synthetic_bill()
    original = deepcopy(bill)
    stream = export_bill_excel(
        bill, {"employee_code": "SYNTHETIC", "note": '=HYPERLINK("unsafe")'}
    )
    assert isinstance(stream, BytesIO) and stream.tell() == 0
    book = load_workbook(stream)
    sheet = book["Monthly components"]
    headers = [cell.value for cell in sheet[2]]
    records = [
        dict(zip(headers, values))
        for values in sheet.iter_rows(min_row=3, values_only=True)
    ]
    assert {r["Month"] for r in records} == {"2026-01", "2026-02"}
    assert {r["Head"] for r in records} == {"Basic", "RECOVERY", "CCA"}
    assert next(r for r in records if r["Head"] == "RECOVERY")["Difference"] == -5
    assert records[0]["Days"] == 16 and records[0]["Month days"] == 31
    values = " ".join(str(c.value) for s in book for row in s for c in row)
    for text in (
        "Synthetic rate order",
        "Synthetic source",
        "Synthetic instruction",
        "Synthetic statement mismatch",
        "DRAFT",
        "human_assisted",
    ):
        assert text in values
    assert not any(c.data_type == "f" for s in book for row in s for c in row)
    assert bill == original


def test_pdf_includes_months_all_heads_sources_totals_and_draft_review_distinction():
    from ifms_suite.bill_exports import export_bill_pdf

    stream = export_bill_pdf(
        synthetic_bill(), {"employee_code": "SYNTHETIC", "note": "<review & verify>"}
    )
    assert isinstance(stream, BytesIO) and stream.tell() == 0
    with pymupdf.open(stream=stream.getvalue(), filetype="pdf") as document:
        text = " ".join(page.get_text() for page in document)
    for expected in (
        "2026-01",
        "2026-02",
        "RECOVERY",
        "CCA",
        "-5.00",
        "170.00",
        "Synthetic rate order",
        "Synthetic source",
        "Synthetic statement mismatch",
        "DRAFT",
        "human_assisted",
        "Human review",
        "<review & verify>",
    ):
        assert expected in text


def test_blocked_export_does_not_turn_missing_net_or_component_into_zero():
    from ifms_suite.bill_exports import export_bill_excel, export_bill_pdf

    bill = synthetic_bill()
    bill.update(status="blocked", blockers=[{"message": "Synthetic missing rate"}])
    bill["totals"]["net_payable"] = None
    bill["rows"][0]["components"][0]["due"] = None
    book = load_workbook(export_bill_excel(bill, {}))
    sheet = book["Monthly components"]
    headers = [c.value for c in sheet[2]]
    assert sheet.cell(3, headers.index("Due") + 1).value is None
    summary = dict(book["Summary"].iter_rows(min_row=3, max_col=2, values_only=True))
    assert summary["Net payable"] is None
    with pymupdf.open(
        stream=export_bill_pdf(bill, {}).getvalue(), filetype="pdf"
    ) as document:
        text = " ".join(p.get_text() for p in document)
    assert (
        "Synthetic missing rate" in text and "Unresolved" in text and "blocked" in text
    )


def test_engine_date_boundaries_supply_inclusive_days_when_counts_are_absent():
    from ifms_suite.bill_exports import export_bill_excel

    bill = synthetic_bill()
    first = bill["rows"][0]
    del first["days"], first["month_days"]
    first.update(start="2026-01-16", end="2026-01-31")
    book = load_workbook(export_bill_excel(bill, {}))
    values = list(
        book["Monthly components"].iter_rows(min_row=3, max_row=3, values_only=True)
    )[0]
    assert values[1:3] == (16, 31)


def test_prepared_engine_bill_exports_include_deductions_and_net():
    from test_bill_engine import case
    from ifms_suite.bill_engine import prepare_bill
    from ifms_suite.bill_exports import export_bill_excel, export_bill_pdf

    facts, request, rates = case()
    request["extra_deductions"] = [
        {
            "name": "Synthetic tax",
            "mode": "fixed",
            "value": "10",
            "reference": "Synthetic instruction",
        }
    ]
    bill = prepare_bill(facts, request, rates)
    book = load_workbook(export_bill_excel(bill, request))
    summary = dict(book["Summary"].iter_rows(min_row=3, max_col=2, values_only=True))
    assert summary["Net payable"] == 310
    assert summary["Total deductions"] == 10
    rows = list(book["Monthly components"].iter_rows(min_row=3, values_only=True))
    assert rows[0][1:3] == (31, 31)
    assert rows[-1][1:3] == (28, 28)
    with pymupdf.open(
        stream=export_bill_pdf(bill, request).getvalue(), filetype="pdf"
    ) as document:
        text = " ".join(p.get_text() for p in document)
    assert "310.00" in text and "Synthetic tax" in text and "Synthetic rate" in text


def test_finalized_exports_distinguish_recorded_review_from_draft():
    import pymupdf
    from ifms_suite.bill_exports import export_bill_pdf

    data = export_bill_pdf(
        {"rows": [], "totals": {}, "status": "ready", "mode": "human_assisted"},
        {"status": "finalized", "review_reference": "Original verified"},
    ).getvalue()
    text = "".join(p.get_text() for p in pymupdf.open(stream=data, filetype="pdf"))
    assert "FINALIZED AFTER SOURCE REVIEW" in text
