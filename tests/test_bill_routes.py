import io
import json
import pymupdf
from test_suite_workflow import client


def imported(client, monkeypatch, facts):
    from ifms_suite import document_facts

    monkeypatch.setattr(document_facts, "extract_document_facts", lambda _: facts)
    doc = pymupdf.open()
    doc.new_page()
    return client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(doc.tobytes()), "case.pdf")},
    ).json["id"]


def test_complete_bill_refuses_client_financial_source_substitution(
    client, monkeypatch
):
    ident = imported(client, monkeypatch, {"bills": [], "orders": [], "issues": []})
    response = client.post(
        f"/suite/api/imports/{ident}/bill_prepare",
        json={"kind": "increment", "new_basic": "99999", "drawn": {"Basic": "1"}},
    )
    assert response.status_code == 400
    assert "source" in response.json["error"].lower()


def test_complete_bill_requires_employee_order_and_keeps_no_guess_claim(
    client, monkeypatch
):
    ident = imported(client, monkeypatch, {"bills": [], "orders": [], "issues": []})
    response = client.post(
        f"/suite/api/imports/{ident}/bill_prepare",
        json={
            "kind": "increment",
            "employee_code": "RJTEST",
            "start": "2026-07-01",
            "end": "2026-07-31",
        },
    )
    assert response.status_code == 200, response.json
    assert response.json["status"] == "blocked"
    assert not client.get("/suite/api/bills").json


def ready_case(client, monkeypatch):
    from test_bill_engine import case
    from ifms_suite.storage import database

    f, p, rates = case()
    f["pay_orders"] = [
        dict(
            employee_code=p["employee_code"],
            effective_from=p["effective_from"],
            basic_amount=p["new_basic"],
            hra_eligible=True,
            reference="Synthetic sanctioned order",
            complete=True,
            evidence=[{"page": 1}],
        )
    ]
    with client.application.app_context(), database() as db:
        for r in rates:
            db.execute("INSERT INTO suite_rates(payload) VALUES(?)", (json.dumps(r),))
    ident = imported(client, monkeypatch, f)
    selection = {
        k: p[k]
        for k in (
            "kind",
            "employee_code",
            "start",
            "end",
            "proration",
            "rounding",
            "rounding_scope",
        )
    }
    return ident, selection


def test_complete_bill_source_to_multimonth_exports_is_idempotent(client, monkeypatch):
    ident, p = ready_case(client, monkeypatch)
    url = f"/suite/api/imports/{ident}/bill_prepare"
    r = client.post(url, json=p)
    assert r.status_code == 200, r.json
    assert r.json["status"] == "ready", r.json
    assert r.json["totals"]["difference"] == "320.00"
    billid = r.json["bill_id"]
    assert client.post(url, json=p).json["bill_id"] == billid
    assert len(client.get("/suite/api/bills").json) == 1
    for kind in ("pdf", "excel"):
        result = client.get(f"/suite/api/bills/{billid}/{kind}")
        assert result.status_code == 200, result.data[:100]
        assert len(result.data) > 1000


def test_final_approval_recalculates_and_rejects_stale_rate_library(
    client, monkeypatch
):
    from ifms_suite.storage import database

    ident, p = ready_case(client, monkeypatch)
    bill = client.post(f"/suite/api/imports/{ident}/bill_prepare", json=p).json
    url = f"/suite/api/bills/{bill['bill_id']}/finalize"
    assert client.post(url, json={}).status_code == 400
    with client.application.app_context(), database() as db:
        row = db.execute("SELECT * FROM suite_rates LIMIT 1").fetchone()
        rate = json.loads(row["payload"])
        rate["rate"] = "60"
        db.execute(
            "UPDATE suite_rates SET payload=? WHERE id=?", (json.dumps(rate), row["id"])
        )
    response = client.post(
        url,
        json={
            "reviewed": True,
            "deductions_reviewed": True,
            "reference": "All sources checked",
        },
    )
    assert response.status_code == 400
    assert "changed" in response.json["error"].lower()


def test_router_preserves_explicit_hra_ineligibility_and_monthly_partial_basis():
    from ifms_suite.bill_routes import _prepare
    from test_bill_engine import case

    f, p, rates = case()
    rates[1]["rate"] = "20"
    f["orders"] = [
        dict(
            allowance="HRA",
            employee_code=p["employee_code"],
            effective_from="2026-01-01",
            rate="20",
            reference="Synthetic sanction",
            complete=True,
            evidence=[{"page": 1}],
            hra_eligible=False,
        )
    ]
    b = f["bills"][0]
    b["allowances"]["HRA"] = "0"
    b.update(printed_gross="1480", printed_net="1450")
    selection = {
        k: p[k]
        for k in (
            "employee_code",
            "start",
            "end",
            "proration",
            "rounding",
            "rounding_scope",
        )
    }
    selection.update(kind="hra", end="2026-01-31")
    result = _prepare(f, selection, rates)
    assert result["status"] == "ready", result
    assert result["totals"]["difference"] == "0.00"
    f["orders"][0]["hra_eligible"] = True
    selection.update(start="2026-01-16", rounding="paise")
    b.update(
        covered_dates={"start": "2026-01-16", "end": "2026-01-31"},
        monthly_basic="1000",
        allowances={"Basic": "500", "DA": "250", "HRA": "50"},
        printed_gross="800",
        printed_net="770",
    )
    result = _prepare(f, selection, rates)
    assert result["status"] == "ready", result
    assert result["totals"]["difference"] == "53.23"
    del b["monthly_basic"]
    assert _prepare(f, selection, rates)["status"] == "blocked"


def test_saved_prior_payment_history_is_checked_by_complete_bill(client, monkeypatch):
    from ifms_suite.storage import database

    ident, p = ready_case(client, monkeypatch)
    with client.application.app_context(), database() as db:
        payment = dict(
            employee_code=p["employee_code"],
            bill_no="987654321",
            pay_month="2025-12",
            bill_type="DA arrear",
            allowances={"DA": "50"},
            deductions={},
            reviewed=True,
            reference="Earlier arrear payment",
        )
        db.execute(
            "INSERT INTO suite_payments(import_id,employee_code,payload) VALUES(?,?,?)",
            (0, p["employee_code"], json.dumps(payment)),
        )
    result = client.post(f"/suite/api/imports/{ident}/bill_prepare", json=p)
    assert result.status_code == 200, result.json
    assert result.json["status"] == "blocked"
    assert any(
        "covered" in b["message"].lower() or "prior" in b["message"].lower()
        for b in result.json["blockers"]
    )


def test_complete_bill_can_be_finalized_and_overlapping_bill_cannot(
    client, monkeypatch
):
    ident, p = ready_case(client, monkeypatch)
    url = f"/suite/api/imports/{ident}/bill_prepare"
    first = client.post(url, json=p).json
    review = {
        "reviewed": True,
        "deductions_reviewed": True,
        "reference": "Independent original and deduction review",
    }
    assert (
        client.post(
            f"/suite/api/bills/{first['bill_id']}/finalize", json=review
        ).status_code
        == 200
    )
    second = client.post(url, json=dict(p, end="2026-01-31")).json
    response = client.post(
        f"/suite/api/bills/{second['bill_id']}/finalize", json=review
    )
    assert response.status_code == 400
    assert "overlap" in response.json["error"].lower()


def test_blocked_verified_rows_are_saved_as_provisional_without_payable(
    client, monkeypatch
):
    from ifms_suite.storage import database

    ident, p = ready_case(client, monkeypatch)
    with client.application.app_context(), database() as db:
        payment = dict(
            employee_code=p["employee_code"],
            bill_no="987654321",
            pay_month="2025-12",
            bill_type="DA arrear",
            allowances={"DA": "50"},
            deductions={},
            reviewed=True,
            reference="Earlier payment",
        )
        db.execute(
            "INSERT INTO suite_payments(import_id,employee_code,payload) VALUES(?,?,?)",
            (0, p["employee_code"], json.dumps(payment)),
        )
    result = client.post(f"/suite/api/imports/{ident}/bill_prepare", json=p).json
    assert result["status"] == "blocked"
    assert result["totals"]["net_payable"] is None
    assert result["bill_id"]
    assert client.get("/suite/api/bills").json[0]["status"] == "blocked"
