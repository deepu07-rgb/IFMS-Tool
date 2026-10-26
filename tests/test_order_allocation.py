from test_suite_workflow import client
from test_payroll_workflow import setup_history


def test_order_based_gpf_is_explicit_and_uses_deferred_period(client):
    setup_history(client)
    # Replace manual rate with a source reference with explicit payment timing.
    from ifms_suite.storage import database
    import json

    with client.application.app_context(), database() as db:
        r = db.execute("SELECT * FROM suite_rates").fetchone()
        p = json.loads(r["payload"])
        p["cash_from"] = "2025-04-01"
        p["verification"] = "official_source_checked"
        db.execute(
            "UPDATE suite_rates SET payload=? WHERE id=?", (json.dumps(p), r["id"])
        )
    with client.application.app_context(), database() as db:
        row = db.execute("SELECT * FROM suite_payments").fetchone()
        payment = json.loads(row["payload"])
        payment["allowances"]["BASIC"] = "50000"
        db.execute(
            "UPDATE suite_payments SET payload=? WHERE id=?",
            (json.dumps(payment), row["id"]),
        )
    r = client.post(
        "/suite/api/claims",
        json=dict(
            employee_code="RJ1",
            allowance="DA",
            start="2025-01-01",
            end="2025-01-31",
            source="history",
            allocation_policy="source_order",
            scheme="GPF-2004",
        ),
    )
    assert r.status_code == 201
    assert r.json["calculation"]["net_payable"] == "0.00"
    assert r.json["calculation"]["deductions"][0]["name"] == "GPF-2004"


def test_manual_rate_override_requires_explanation(client):
    setup_history(client)
    p = dict(
        allowance="DA",
        effective_from="2025-01-01",
        rate="57",
        reference="Revised order",
    )
    assert client.post("/suite/api/rates", json=p).status_code == 409
    p["override_reason"] = "Revised order verified"
    assert client.post("/suite/api/rates", json=p).status_code == 201
    assert len(client.get("/suite/api/rates").json) == 1
