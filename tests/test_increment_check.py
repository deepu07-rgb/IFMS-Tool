from test_suite_workflow import client


def setup(client):
    for head, rate, category in [("DA", "60", ""), ("HRA", "20", "Y")]:
        client.post(
            "/suite/api/rates",
            json=dict(
                allowance=head,
                rate=rate,
                category=category,
                effective_from="2026-01-01",
                reference="Reviewed rate",
            ),
        )
    return dict(
        employee_code="SYNTHETIC",
        start="2026-07-01",
        end="2026-07-31",
        new_basic="55500",
        category="Y",
        effective_from="2026-07-01",
        pay_order_reference="Approved matrix increment effective01July",
        reviewed=True,
        drawn={"BASIC": "53900", "DA": "32340", "HRA": "10780", "HDA": "7187"},
        hda_rule=dict(
            numerator="1", denominator="12", reference="Reviewed HDA fraction"
        ),
        unchanged_allowances={"CCA": "620", "Mess All": "2850"},
        printed_drawn_gross="107677",
    )


def test_increment_component_rounding_matches_reference_and_saves_exports(client):
    p = setup(client)
    r = client.post("/suite/api/increment_check", json=p)
    assert r.status_code == 201
    assert r.json["total"] == "3093.00"
    assert [row["difference"] for row in r.json["components"]] == [
        "1600.00",
        "960.00",
        "320.00",
        "213.00",
    ]
    assert (
        r.json["full_drawn_gross"] == "107677.00"
        and r.json["full_due_gross"] == "110770.00"
    )
    assert len(r.json["claim_ids"]) == 4
    for id in r.json["claim_ids"]:
        assert client.get(f"/suite/api/claims/{id}/excel").status_code == 200


def test_increment_uses_configured_rates_instead_of_sample_answers(client):
    p = setup(client)
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="DA",
            rate="55",
            effective_from="2026-01-01",
            reference="Changed",
            override_reason="Test override",
        ),
    )
    r = client.post("/suite/api/increment_check", json=p)
    assert r.status_code == 201 and r.json["total"] == "87.00"
    assert r.json["warnings"]


def test_missing_drawn_component_never_defaults_to_zero(client):
    p = setup(client)
    del p["drawn"]["HRA"]
    assert client.post("/suite/api/increment_check", json=p).status_code == 400


def test_changed_rate_blocks_finalizing_old_increment_snapshot(client):
    p = setup(client)
    r = client.post("/suite/api/increment_check", json=p)
    id = r.json["claim_ids"][1]
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="DA",
            rate="55",
            effective_from="2026-01-01",
            reference="Changed",
            override_reason="New order",
        ),
    )
    q = client.post(
        f"/suite/api/claims/{id}/finalize",
        json=dict(reviewed=True, rule_reference="Order", drawn_reference="GA55"),
    )
    assert q.status_code == 400 and "rates changed" in q.json["error"].lower()


def test_partial_increment_uses_explicit_period_workflow(client):
    p = setup(client)
    p["start"] = "2026-07-13"
    assert client.post("/suite/api/increment_check", json=p).status_code == 400


def test_existing_july_arrear_blocks_a_duplicate_increment_draft(client):
    p = setup(client)
    client.post(
        "/suite/api/payments/manual",
        json=dict(
            employee_code="SYNTHETIC",
            pay_month="2026-09",
            bill_no="PRIOR",
            bill_type="Arrear DA",
            allowances={"DA": "500"},
            entitlement_period={"start": "2026-07-01", "end": "2026-07-31"},
            reviewed=True,
            reference="Paid prior bill",
        ),
    )
    r = client.post("/suite/api/increment_check", json=p)
    assert r.status_code == 400 and "prior" in r.json["error"].lower()


def test_already_updated_august_salary_has_no_increment_arrear(client):
    p = setup(client)
    p.update(
        start="2026-08-01",
        end="2026-08-31",
        drawn={"BASIC": "55500", "DA": "33300", "HRA": "11100", "HDA": "7400"},
        printed_drawn_gross="110770",
    )
    r = client.post("/suite/api/increment_check", json=p)
    assert r.status_code == 201
    assert r.json["total"] == "0.00"


def test_midmonth_rate_added_after_drafting_blocks_finalization(client):
    p = setup(client)
    id = client.post("/suite/api/increment_check", json=p).json["claim_ids"][1]
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="DA",
            rate="65",
            effective_from="2026-07-15",
            reference="Interior rate change",
        ),
    )
    r = client.post(
        f"/suite/api/claims/{id}/finalize",
        json=dict(reviewed=True, rule_reference="Order", drawn_reference="GA55"),
    )
    assert r.status_code == 400


def test_bounded_midmonth_rate_cannot_be_missed_between_equal_endpoints(client):
    p = setup(client)
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="DA",
            rate="65",
            effective_from="2026-07-15",
            effective_to="2026-07-20",
            reference="Bounded interior rate",
        ),
    )
    r = client.post("/suite/api/increment_check", json=p)
    assert r.status_code == 400


def test_increment_cannot_be_claimed_before_approved_effective_date(client):
    p = setup(client)
    p.update(start="2026-06-01", end="2026-06-30", effective_from="2026-07-01")
    r = client.post("/suite/api/increment_check", json=p)
    assert r.status_code == 400


def test_increment_exports_retain_the_basic_and_rate_basis(client):
    p = setup(client)
    r = client.post("/suite/api/increment_check", json=p)
    saved = {row["id"]: row for row in client.get("/suite/api/claims").json}
    for id in r.json["claim_ids"]:
        assert saved[id]["calculation"]["rows"][0]["basic"] == "55500"
        assert saved[id]["calculation"]["rows"][0]["drawn_basic"] == "53900"
    assert saved[r.json["claim_ids"][1]]["calculation"]["rows"][0]["due_rate"] == "60"


def test_explicit_reviewed_hra_exemption_does_not_create_city_hra(client):
    p = setup(client)
    p.update(
        hra_eligible=False,
        hra_eligibility_reference="Reviewed accommodation eligibility",
        printed_drawn_gross="96897",
    )
    p["drawn"]["HRA"] = "0"
    response = client.post("/suite/api/increment_check", json=p)
    assert response.status_code == 201, response.json
    assert response.json["total"] == "2773.00"
    hra = next(r for r in response.json["components"] if r["head"] == "HRA")
    assert hra["due"] == "0.00" and hra["difference"] == "0.00"
    assert "HRA" not in response.json["rates"]
    payloads = client.get("/suite/api/claims").json
    assert all(c["payload"]["hra_eligible"] is False for c in payloads)
    assert all(
        c["payload"]["hra_eligibility_reference"]
        == "Reviewed accommodation eligibility"
        for c in payloads
    )


def test_hra_exemption_requires_reference_and_zero_drawn(client):
    p = setup(client)
    p.update(hra_eligible=False)
    assert client.post("/suite/api/increment_check", json=p).status_code == 400
    p["hra_eligibility_reference"] = "Checked eligibility"
    assert client.post("/suite/api/increment_check", json=p).status_code == 400
    p["hra_eligible"] = "false"
    assert client.post("/suite/api/increment_check", json=p).status_code == 400
