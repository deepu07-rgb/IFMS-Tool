"""A different sanction PDF must reuse verified salary from the persistent ledger."""

import io
import json
import pymupdf
from test_suite_workflow import client


def test_separate_sanction_case_reuses_saved_months_without_financial_reentry(
    client, monkeypatch
):
    from ifms_suite import document_facts
    from ifms_suite.storage import database
    from test_bill_engine import case

    facts, selection, rates = case()
    code = "RJXY204012345678"
    selection["employee_code"] = code
    for i, bill in enumerate(facts["bills"]):
        bill.update(
            employee_code=code,
            bill_no=str(123456780 + i),
            allowances_complete=True,
            deductions_complete=True,
            deductions_reconciled=True,
            net_reconciled=True,
        )

    def upload(source_facts, label):
        monkeypatch.setattr(
            document_facts, "extract_document_facts", lambda _: source_facts
        )
        document = pymupdf.open()
        document.new_page().insert_text((30, 30), label)
        response = client.post(
            "/suite/api/imports",
            data={
                "kind": "ga55",
                "file": (io.BytesIO(document.tobytes()), label + ".pdf"),
            },
        )
        assert response.status_code == 201
        ident = response.json["id"]
        assert client.get(f"/suite/api/imports/{ident}/case_review").status_code == 200
        return ident

    salary_import = upload(facts, "Synthetic drawn salary source")
    response = client.post(
        f"/suite/api/imports/{salary_import}/ledger",
        json={
            "bill_indexes": [0, 1],
            "reviewed": True,
            "reference": "Synthetic original monthly records verified",
        },
    )
    assert response.status_code == 201, response.json
    order_facts = dict(
        bills=[],
        issues=[],
        pay_orders=[
            dict(
                employee_code=code,
                effective_from=selection["effective_from"],
                basic_amount=selection["new_basic"],
                hra_eligible=True,
                reference="Synthetic separate sanctioned order",
                complete=True,
                evidence=[{"page": 1}],
            )
        ],
    )
    order_import = upload(order_facts, "Synthetic separate increment order")
    with client.application.app_context(), database() as db:
        for rate in rates:
            db.execute(
                "INSERT INTO suite_rates(payload) VALUES(?)", (json.dumps(rate),)
            )
    request = {
        k: selection[k]
        for k in (
            "employee_code",
            "kind",
            "start",
            "end",
            "proration",
            "rounding",
            "rounding_scope",
        )
    }
    result = client.post(
        f"/suite/api/imports/{order_import}/bill_prepare", json=request
    )
    assert result.status_code == 200, result.json
    assert result.json["status"] == "ready", result.json
    assert result.json["totals"]["difference"] == "320.00"
    assert len(result.json["rows"]) == 2
    assert all(
        any(item.get("payment_id") for item in row["evidence"])
        for row in result.json["rows"]
    )
    ledger = client.get("/suite/api/ledger", query_string={"employee_code": code}).json
    assert ledger["payment_count"] == 2
    assert all(
        row["regular_salary"][0]["ledger_source"]["source_import"] == salary_import
        for row in ledger["months"]
    )
