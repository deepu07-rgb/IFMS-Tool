import pytest
from decimal import Decimal
from ifms_suite.calculation import calculate_claim
from ifms_suite.documents import parse_ga55
from ifms_suite.history import prepare_segments
from test_suite_workflow import client


@pytest.mark.parametrize(
    "month,last,split", [("2025-02", 28, 14), ("2024-02", 29, 14), ("2025-01", 31, 15)]
)
def test_thirty_day_entitlement_conserved_across_slices(month, last, split):
    def row(a, b):
        return dict(
            start=f"{month}-{a:02d}",
            end=f"{month}-{b:02d}",
            basis="fixed",
            due_amount="3000",
            drawn_amount="0",
            proration="thirty",
        )

    whole = calculate_claim(f"{month}-01", f"{month}-{last}", [row(1, last)])
    sliced = calculate_claim(
        f"{month}-01", f"{month}-{last}", [row(1, split), row(split + 1, last)]
    )
    assert sliced["total"] == whole["total"] == "3000.00"


def test_identity_does_not_inherit_or_capture_payment_year():
    payments = parse_ga55(
        [
            "Employee Id\nRJ1234\nJanuary\n2025\nRegular Salary\n123456789\nDA\n100.00\nEmployee Id\nUNREADABLE\nFebruary\n2025\nRegular Salary\n223456789\nDA\n200.00"
        ]
    )["payments"]
    assert payments[0]["employee_code"] == "RJ1234"
    assert payments[1]["employee_code"] == ""
    assert any("identity" in s.lower() for s in payments[1]["issues"])


def history_inputs():
    return (
        [dict(allowance="DA", effective_from="2025-01-01", rate="55")],
        [
            dict(effective_from="2025-01-01", basic="50000"),
            dict(effective_from="2025-01-16", basic="60000"),
        ],
        [
            dict(
                id=1,
                bill_no="S",
                bill_type="Regular Salary",
                pay_month="2025-01",
                allowances={"DA": "27580.65"},
            )
        ],
    )


def test_partial_history_requires_explicit_drawn_allocation_review():
    rates, pay, payments = history_inputs()
    with pytest.raises(ValueError, match="drawn allocation"):
        prepare_segments("2025-01-16", "2025-01-31", "DA", rates, pay, payments, {})


def test_explicit_uniform_daily_drawn_assumption_is_retained():
    rates, pay, payments = history_inputs()
    rows = prepare_segments(
        "2025-01-16",
        "2025-01-31",
        "DA",
        rates,
        pay,
        payments,
        {"uniform_drawn_reviewed": True},
    )
    assert "reviewed uniform" in rows[0]["source"].lower()


REVIEW = dict(reviewed=True, rule_reference="Order", drawn_reference="Bill")


def save_manual(client, due, prior="0", ids=None):
    p = dict(
        employee_code="RJ1",
        allowance="DA",
        entitlement_type="leave_encashment",
        start="2025-01-01",
        end="2025-01-31",
        segments=[
            dict(
                start="2025-01-01",
                end="2025-01-31",
                basis="fixed",
                due_amount=str(due),
                drawn_amount="0",
                prior_settlement=prior,
                settlement_ids=ids or [],
            )
        ],
    )
    return client.post("/suite/api/claims", json=p)


def test_paid_leave_revision_validates_actual_settlement_server_side(client):
    first = save_manual(client, 1000).json["id"]
    assert (
        client.post(f"/suite/api/claims/{first}/finalize", json=REVIEW).status_code
        == 200
    )
    r = client.post(
        f"/suite/api/claims/{first}/settlement",
        json=dict(reviewed=True, reference="GA55", bill_no="A1", pay_month="2025-04"),
    )
    pid = r.json["payment_id"]
    revision = save_manual(client, 1200, "1000", [pid])
    assert revision.json["calculation"]["total"] == "200.00"
    assert (
        client.post(
            f"/suite/api/claims/{revision.json['id']}/finalize", json=REVIEW
        ).status_code
        == 200
    )


def test_manual_revision_cannot_claim_settlement_id_without_its_amount(client):
    first = save_manual(client, 1000).json["id"]
    client.post(f"/suite/api/claims/{first}/finalize", json=REVIEW)
    pid = client.post(
        f"/suite/api/claims/{first}/settlement",
        json=dict(reviewed=True, reference="GA55", bill_no="A1", pay_month="2025-04"),
    ).json["payment_id"]
    bad = save_manual(client, 1200, "0", [pid])
    assert bad.status_code == 400


def test_linked_settlement_retains_january_and_february_amounts(client):
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="DA", effective_from="2025-01-01", rate="55", reference="Order"
        ),
    )
    client.post(
        "/suite/api/pay_history",
        json=dict(
            employee_code="RJ1",
            effective_from="2025-01-01",
            basic="50000",
            reference="Order",
            reviewed=True,
        ),
    )
    for month in ("2025-01", "2025-02"):
        client.post(
            "/suite/api/payments/manual",
            json=dict(
                employee_code="RJ1",
                pay_month=month,
                bill_no=month,
                bill_type="Regular Salary",
                allowances={"DA": "26500"},
                reference="Bill",
                reviewed=True,
            ),
        )
    p = dict(
        employee_code="RJ1",
        allowance="DA",
        source="history",
        start="2025-01-01",
        end="2025-02-28",
    )
    response = client.post("/suite/api/claims", json=p)
    assert response.status_code == 201
    id = response.json["id"]
    assert response.json["calculation"]["total"] == "2000.00"
    client.post(f"/suite/api/claims/{id}/finalize", json=REVIEW)
    client.post(
        f"/suite/api/claims/{id}/settlement",
        json=dict(reviewed=True, reference="GA55", bill_no="A2", pay_month="2025-04"),
    )
    response = client.post("/suite/api/claims", json=dict(p, end="2025-01-31"))
    assert response.json["calculation"]["total"] == "0.00"
    assert response.json["calculation"]["rows"][0]["prior_settlement"] == "1000.00"


def test_imported_aggregate_arrear_requires_reviewed_monthly_allocations(client):
    from test_payroll_workflow import setup_history

    setup_history(client)
    payment = client.post(
        "/suite/api/payments/manual",
        json=dict(
            employee_code="RJ1",
            pay_month="2025-04",
            bill_type="DA",
            bill_no="A3",
            allowances={"DA": "2000"},
            entitlement_period={"start": "2025-01-01", "end": "2025-02-28"},
            reference="Bill",
            reviewed=True,
        ),
    )
    pid = payment.json["id"]
    p = dict(
        employee_code="RJ1",
        allowance="DA",
        source="history",
        start="2025-01-01",
        end="2025-01-31",
    )
    r = client.post("/suite/api/claims", json=p)
    assert r.status_code == 400 and "allocations" in r.json["error"]
    rows = [
        dict(start="2025-01-01", end="2025-01-31", amount="1000"),
        dict(start="2025-02-01", end="2025-02-28", amount="1000"),
    ]
    endpoint = f"/suite/api/payments/{pid}/period_allocations"
    assert (
        client.post(
            endpoint,
            json=dict(head="DA", rows=rows, reviewed=True, reference="Monthly bill"),
        ).status_code
        == 200
    )
    assert (
        client.post(
            endpoint,
            json=dict(head="DA", rows=rows, reviewed=True, reference="Duplicate"),
        ).status_code
        == 400
    )
    assert (
        client.post("/suite/api/claims", json=p).json["calculation"]["total"] == "0.00"
    )
