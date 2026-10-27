from test_suite_workflow import client
from test_payroll_workflow import setup_history


def test_scan_header_accepts_damaged_ga55_but_not_orders():
    from ifms_suite.ga55_table_ocr import is_ga55_header

    assert is_ga55_header("Goyernment Of Rajasthan GASS A")
    assert is_ga55_header("GA55 A Financial Year 2026-27 Employee Pay Month Gross")
    assert is_ga55_header(
        "Government Of Rajasthan ७५55 A Financial Year 2026-27 Pay Month Gross"
    )
    assert is_ga55_header(
        "GA55 A Financial Year 2026-27 Employee Name Employee ID GPF Number"
    )
    assert is_ga55_header(
        "Government Of Rajasthan ७५55 A Financial Year 2026-27 HRA CCA HDA"
    )
    assert not is_ga55_header("Government Of Rajasthan Promotion Order 2026")
    assert not is_ga55_header("OFFICE Due Drawn Basic DA HRA Gross")


def test_malformed_nonempty_ocr_still_uses_column_reader():
    from ifms_suite.ga55_table_ocr import needs_column_ocr

    assert needs_column_ocr(
        {
            "payments": [
                {
                    "bill_type": "November 2025 January 2026",
                    "allowances": {"HDA": "19415.00"},
                }
            ]
        }
    )
    assert not needs_column_ocr(
        {
            "payments": [
                {
                    "bill_type": "Regular Salary",
                    "printed_gross": "1600",
                    "allowances": {"Basic": "1000", "DA": "600"},
                }
            ]
        }
    )


def test_auto_gpf_rejects_pay_fixation_and_unknown_drawn_basic(client):
    import json
    from ifms_suite.storage import database

    setup_history(client)
    with client.application.app_context(), database() as db:
        rate = db.execute("SELECT * FROM suite_rates").fetchone()
        p = json.loads(rate["payload"])
        p.update(cash_from="2025-04-01", verification="official_source_checked")
        db.execute(
            "UPDATE suite_rates SET payload=? WHERE id=?", (json.dumps(p), rate["id"])
        )
    p = dict(
        employee_code="RJ1",
        allowance="DA",
        start="2025-01-01",
        end="2025-01-31",
        source="history",
        allocation_policy="source_order",
        scheme="GPF-2004",
    )
    r = client.post("/suite/api/claims", json=p)
    assert r.status_code == 400
    assert "basic" in r.json["error"].lower()
    with client.application.app_context(), database() as db:
        row = db.execute("SELECT * FROM suite_payments").fetchone()
        payment = json.loads(row["payload"])
        payment["allowances"]["BASIC"] = "49000"
        db.execute(
            "UPDATE suite_payments SET payload=? WHERE id=?",
            (json.dumps(payment), row["id"]),
        )
    r = client.post("/suite/api/claims", json=p)
    assert r.status_code == 400
    assert "basic" in r.json["error"].lower()


def test_partial_fixation_month_rounding_and_prior_credit():
    from ifms_suite.calculation import calculate_claim
    from decimal import Decimal as D

    total = D(0)
    for rate, drawn, prior, expected in [
        ("100", "35300", "0", "368"),
        ("60", "20474", "706", "221"),
        ("20", "7060", "0", "74"),
    ]:
        segments = [
            dict(
                start="2026-01-01",
                end="2026-01-28",
                basic="35300",
                due_rate=rate,
                drawn_amount=drawn,
                drawn_basis="monthly_amount",
                rounding="rupee",
                rounding_scope="month",
                prior_settlement=prior,
            ),
            dict(
                start="2026-01-29",
                end="2026-01-31",
                basic="39100",
                due_rate=rate,
                drawn_amount=drawn,
                drawn_basis="monthly_amount",
                rounding="rupee",
                rounding_scope="month",
            ),
        ]
        r = calculate_claim("2026-01-01", "2026-01-31", segments)
        assert D(r["total"]) == D(expected)
        total += D(r["total"])
    assert total == 663  # HDA adds 49; prior DA credit must not be paid again.


def test_fallback_preserves_valid_base_pages_and_handles_large_import(monkeypatch):
    import pymupdf
    import ifms_suite.ga55_table_ocr as g

    good = dict(
        source_pages=[1],
        bill_type="Salary",
        printed_gross="1600",
        allowances={"Basic": "1000", "DA": "600"},
    )
    bad = dict(source_pages=[2], bill_type="Unreadable", allowances={})
    replacement = dict(
        source_pages=[2],
        bill_type="Regular Salary",
        allowances={"Basic": "1000"},
        requires_review=True,
    )
    base = {"payments": [good, bad]}
    d = pymupdf.open()
    d.new_page()
    d.new_page()
    monkeypatch.setattr(
        g,
        "parse_scanned_ga55_tables",
        lambda data: dict(payments=[replacement], layout="GA55 A column OCR"),
    )
    result = g.improve_scanned_ga55(base, d.tobytes())
    assert result["payments"] == [good, replacement]
    for _ in range(39):
        d.new_page()
    result = g.improve_scanned_ga55(base, d.tobytes())
    assert result["payments"] == base["payments"]
    assert "40" in result["notice"]


import pytest


@pytest.mark.parametrize("pages", [2, 41])
def test_ocr_route_preserves_base_when_column_coverage_is_partial(
    client, monkeypatch, pages
):
    import io, pymupdf
    import ifms_suite.documents as documents
    import ifms_suite.ga55_table_ocr as g

    d = pymupdf.open()
    for _ in range(pages):
        d.new_page()
    data = d.tobytes()
    from ifms_suite import document_facts
    good = dict(source_pages=[1], employee_code="RJTEST", pay_month="2026-07",
                bill_no="123456789", bill_type="Regular Salary", complete=True,
                printed_gross="1600", allowances={"Basic":"1000", "DA":"600"})
    bad = dict(source_pages=[2], bill_type="Unreadable", allowances={}, complete=False)
    monkeypatch.setattr(document_facts, "extract_document_facts",
                        lambda raw: {"bills": [good, bad], "issues": []})
    imported = client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(data), "synthetic.pdf")},
    )
    assert imported.status_code == 201
    response = client.post(f"/suite/api/imports/{imported.json['id']}/ocr", json={})
    assert response.status_code == 200
    records = response.json["ga55"]["payments"]
    assert len(records) == 2
    assert records[0]["allowances"] == good["allowances"]
    assert records[0]["source_pages"] == [1]
    assert records[1]["complete"] is False
    assert response.json["ga55"]["calculation_ready"] is False


def test_ga55_header_with_only_numeric_form_suffix_needs_other_evidence():
    from ifms_suite.ga55_table_ocr import is_ga55_header

    assert is_ga55_header("Government Of Rajasthan ५५55 A Financial Year 2025-26")
    assert is_ga55_header("Government Of Rajasthan (355 A Financial Year 2025-26")
    assert is_ga55_header("(555 A Financial Year 2026-27 Employee Name GPF Number")
    assert not is_ga55_header("(555 A Employee Name GPF Number")
    assert not is_ga55_header("55 A Financial Year 2026-27 Total Allowances")
