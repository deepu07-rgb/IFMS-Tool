from test_suite_workflow import client
from test_payroll_workflow import setup_history


def test_paid_claim_allows_a_later_rate_revision_after_deducting_settlement(client):
    setup_history(client)
    p = dict(
        employee_code="RJ1",
        allowance="DA",
        source="history",
        start="2025-01-01",
        end="2025-01-31",
    )
    first = client.post("/suite/api/claims", json=p).json["id"]
    review = dict(reviewed=True, rule_reference="Order", drawn_reference="Bill")
    assert (
        client.post(f"/suite/api/claims/{first}/finalize", json=review).status_code
        == 200
    )
    settled = client.post(
        f"/suite/api/claims/{first}/settlement",
        json=dict(
            reviewed=True,
            bill_no="ARREAR1",
            pay_month="2025-04",
            reference="Paid GA55 entry",
        ),
    )
    assert settled.status_code == 200
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="DA",
            effective_from="2025-01-01",
            rate="57",
            reference="Revised order",
            override_reason="Later revision",
        ),
    )
    second = client.post("/suite/api/claims", json=p)
    assert second.json["calculation"]["total"] == "1000.00"
    assert (
        client.post(
            f"/suite/api/claims/{second.json['id']}/finalize", json=review
        ).status_code
        == 200
    )


def test_unallocated_payment_can_get_one_reviewed_period(client):
    p = dict(
        employee_code="RJ1",
        bill_no="A1",
        bill_type="DA",
        pay_month="2025-04",
        allowances={"DA": "1000"},
        reviewed=True,
        reference="GA55",
    )
    id = client.post("/suite/api/payments/manual", json=p).json["id"]
    r = client.post(
        f"/suite/api/payments/{id}/allocate",
        json=dict(
            start="2025-01-01",
            end="2025-03-31",
            reviewed=True,
            reference="Arrear sanction",
        ),
    )
    assert r.status_code == 200
    payments = client.get("/suite/api/payments?employee_code=RJ1").json
    assert payments[0]["entitlement_period"]["end"] == "2025-03-31"
