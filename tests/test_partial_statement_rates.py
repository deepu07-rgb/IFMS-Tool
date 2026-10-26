import json
from test_suite_workflow import client
from ifms_suite.storage import database


def test_partial_statement_rate_recalculation_prorates_due_once(client):
    with client.application.app_context(), database() as db:
        id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            ("partial-synthetic", "partial.pdf", json.dumps({"statement_rows": []})),
        ).lastrowid
    response = client.post(
        "/suite/api/rates",
        json=dict(
            allowance="HRA",
            category="Y",
            effective_from="2026-01-01",
            rate="20",
            rounding="rupee",
            reference="Reviewed test order",
        ),
    )
    assert response.status_code == 201
    row = dict(
        month="2026-06",
        start="2026-06-21",
        end="2026-06-30",
        due={"Basic": "95900", "HRA": "6393"},
        drawn={"Basic": "92700", "HRA": "6180"},
    )
    p = dict(
        import_id=id,
        employee_code="SYNTHETIC",
        allowance="HRA",
        category="Y",
        method="rates",
        reviewed=True,
        amounts_cover_selected_period=True,
        rows=[row],
    )
    response = client.post("/suite/api/statement_claim", json=p)
    assert response.status_code == 201, response.json
    assert response.json["calculation"]["total"] == "213.00"
    assert response.json["calculation"]["rows"][0]["due"] == "6393.00"
    # Uploaded selected-period amounts stay actual; do not prorate them twice.
    p["method"] = "uploaded"
    response = client.post("/suite/api/statement_claim", json=p)
    assert response.status_code == 201, response.json
    assert response.json["calculation"]["total"] == "213.00"


def test_statement_finalization_blocks_unknown_prior_arrear_period(client):
    with client.application.app_context(), database() as db:
        id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            ("review-synthetic", "review.pdf", json.dumps({"statement_rows": []})),
        ).lastrowid
    prior = client.post(
        "/suite/api/payments/manual",
        json=dict(
            employee_code="SYNTHETIC",
            pay_month="2024-07",
            bill_type="Salary Arrear",
            bill_no="PRIOR",
            allowances={"BASIC": "50000"},
            reviewed=True,
            reference="Covered period unknown",
        ),
    )
    assert prior.status_code == 201
    r = client.post(
        "/suite/api/statement_claim",
        json=dict(
            import_id=id,
            employee_code="SYNTHETIC",
            allowance="BASIC",
            method="uploaded",
            reviewed=True,
            rows=[
                dict(month="2025-11", due={"Basic": "95900"}, drawn={"Basic": "92700"})
            ],
        ),
    )
    assert r.status_code == 201
    url = f"/suite/api/claims/{r.json['id']}/finalize"
    review = dict(reviewed=True, rule_reference="Pay order", drawn_reference="GA55")
    r = client.post(url, json=review)
    assert r.status_code == 400
    assert "period" in r.json["error"].lower()
    r = client.post(
        f"/suite/api/payments/{prior.json['id']}/allocate",
        json=dict(
            start="2024-07-01",
            end="2025-10-31",
            reviewed=True,
            reference="Confirmed prior sanction",
        ),
    )
    assert r.status_code == 200
    assert client.post(url, json=review).status_code == 200


def test_library_rupee_rounding_does_not_round_actual_drawn_paise(client):
    with client.application.app_context(), database() as db:
        id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            ("paise-synthetic", "paise.pdf", json.dumps({"statement_rows": []})),
        ).lastrowid
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="HRA",
            category="Y",
            effective_from="2026-01-01",
            rate="20",
            rounding="rupee",
            reference="Test order",
        ),
    )
    r = client.post(
        "/suite/api/statement_claim",
        json=dict(
            import_id=id,
            employee_code="SYNTHETIC",
            allowance="HRA",
            category="Y",
            method="rates",
            reviewed=True,
            rows=[
                dict(
                    month="2026-06",
                    due={"Basic": "95900", "HRA": "19180"},
                    drawn={"Basic": "92700", "HRA": "6180.45"},
                )
            ],
        ),
    )
    assert r.status_code == 201, r.json
    assert r.json["calculation"]["rows"][0]["drawn"] == "6180.45"
    assert r.json["calculation"]["total"] == "12999.55"


def test_reviewed_statement_cannot_omit_known_overlapping_prior_arrear(client):
    with client.application.app_context(), database() as db:
        id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            ("overlap-synthetic", "overlap.pdf", json.dumps({"statement_rows": []})),
        ).lastrowid
    prior = client.post(
        "/suite/api/payments/manual",
        json=dict(
            employee_code="SYNTHETIC",
            pay_month="2026-09",
            bill_type="Salary Arrear",
            bill_no="PRIOR-OVERLAP",
            allowances={"BASIC": "1000"},
            entitlement_period={"start": "2025-11-01", "end": "2025-11-30"},
            reviewed=True,
            reference="Confirmed overlapping sanction",
        ),
    )
    assert prior.status_code == 201
    r = client.post(
        "/suite/api/statement_claim",
        json=dict(
            import_id=id,
            employee_code="SYNTHETIC",
            allowance="BASIC",
            method="uploaded",
            reviewed=True,
            rows=[
                dict(month="2025-11", due={"Basic": "95900"}, drawn={"Basic": "92700"})
            ],
        ),
    )
    assert r.status_code == 201
    r = client.post(
        f"/suite/api/claims/{r.json['id']}/finalize",
        json=dict(reviewed=True, rule_reference="Pay order", drawn_reference="GA55"),
    )
    assert r.status_code == 400
    assert "overlap" in r.json["error"].lower()
