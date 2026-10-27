from copy import deepcopy
from decimal import Decimal


def facts():
    return dict(
        bills=[
            dict(
                employee_code="RJTEST42",
                pay_month="2026-07",
                bill_no="123456789",
                bill_type="Regular Salary",
                allowances={"Basic": "31000", "DA": "18600", "HDA": "4133"},
                printed_gross="53733",
                complete=True,
                source_pages=[1, 2],
            ),
            dict(
                employee_code="RJTEST42",
                pay_month="2026-08",
                bill_no="123456790",
                bill_type="Regular Salary",
                allowances={
                    "Basic": "31000",
                    "DA": "18600",
                    "HDA": "4133",
                    "HRA": "6200",
                },
                printed_gross="59933",
                complete=True,
                source_pages=[2],
            ),
        ],
        orders=[
            dict(
                employee_code="RJTEST42",
                effective_from="2026-07-05",
                rate="20",
                allowance="HRA",
                source_pages=[3],
            )
        ],
        issues=[],
    )


def test_partial_hra_from_matched_order_and_complete_bills():
    from ifms_suite.automatic_hra import reconcile_hra

    r = reconcile_hra(facts())
    assert not r["blockers"]
    c = r["drafts"][0]["calculation"]
    assert c["total"] == "5400.00"
    assert c["rows"][0]["days"] == 27
    assert c["rows"][1]["difference"] == "0.00"


def test_missing_continuation_or_wrong_total_blocks_instead_of_zero():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["bills"][0]["allowances"].pop("HDA")
    assert reconcile_hra(f)["blockers"]
    assert not reconcile_hra(f)["drafts"]


def test_unknown_prior_hra_coverage_blocks_and_wrong_employee_cannot_match():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["bills"].append(
        dict(
            employee_code="RJTEST42",
            bill_type="HRA Arrear",
            allowances={"HRA": "1000"},
            source_pages=[2],
        )
    )
    assert reconcile_hra(f)["blockers"]
    f = facts()
    f["orders"][0]["employee_code"] = "OTHER"
    assert not reconcile_hra(f)["drafts"]


def test_duplicate_month_and_rate_override_block():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["bills"].append(deepcopy(f["bills"][0]))
    assert reconcile_hra(f)["blockers"]
    assert reconcile_hra(
        facts(),
        [dict(allowance="HRA", category="Y", rate="25", effective_from="2024-01-01")],
    )["blockers"]


from test_suite_workflow import client


def test_automatic_route_uses_original_pdf_and_is_idempotent(client, monkeypatch):
    import io, sys, types, pymupdf

    d = pymupdf.open()
    d.new_page()
    data = d.tobytes()
    seen = []

    def extract(value):
        seen.append(value)
        return facts()

    monkeypatch.setitem(
        sys.modules,
        "ifms_suite.document_facts",
        types.SimpleNamespace(extract_document_facts=extract, FACTS_VERSION=1),
    )
    imported = client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(data), "bundle.pdf")},
    )
    url = f"/suite/api/imports/{imported.json['id']}/automatic_hra"
    response = client.post(url, json={})
    assert response.status_code == 200, response.json
    assert seen == [data]
    assert response.json["claims"][0]["calculation"]["total"] == "5400.00"
    assert (
        client.post(url, json={}).json["claims"][0]["id"]
        == response.json["claims"][0]["id"]
    )
    assert len(client.get("/suite/api/claims").json) == 1
    claim = response.json["claims"][0]["id"]
    forged = client.get("/suite/api/claims").json[0]["payload"]
    forged.update(entitlement_type="leave_encashment", machine_generated=False)
    assert client.post("/suite/api/claims", json=forged).status_code == 400

    assert client.get(f"/suite/api/claims/{claim}/pdf").data.startswith(b"%PDF")
    assert client.get(f"/suite/api/claims/{claim}/excel").data.startswith(b"PK")
    exported = client.get(f"/suite/api/claims/{claim}/pdf").data
    with pymupdf.open(stream=exported, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
        assert "Machine source evidence" in text and "Provisional" in text

    review = dict(
        reviewed=True, rule_reference="Order source", drawn_reference="Salary source"
    )
    assert (
        client.post(f"/suite/api/claims/{claim}/finalize", json=review).status_code
        == 400
    )
    review["machine_facts_reviewed"] = True
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="HRA",
            category="Y",
            rate="25",
            effective_from="2024-01-01",
            reference="Changed library",
        ),
    )
    assert (
        client.post(f"/suite/api/claims/{claim}/finalize", json=review).status_code
        == 400
    )


def test_order_list_other_employees_does_not_block_unique_salary_match():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["orders"].append(
        dict(
            employee_code="ANOTHER",
            effective_from="2026-07-02",
            rate="20",
            allowance="HRA",
        )
    )
    r = reconcile_hra(f)
    assert len(r["drafts"]) == 1 and not r["blockers"]


def test_nonpositive_basic_and_reused_bill_identifier_block():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["bills"][0]["allowances"]["Basic"] = "-31000"
    f["bills"][0]["printed_gross"] = "-8267"
    assert reconcile_hra(f)["blockers"]
    f = facts()
    f["bills"][1]["bill_no"] = f["bills"][0]["bill_no"]
    assert reconcile_hra(f)["blockers"]


def test_duplicate_prior_credit_and_out_of_period_allocation_block():
    from ifms_suite.automatic_hra import reconcile_hra

    prior = dict(
        employee_code="RJTEST42",
        pay_month="2026-09",
        bill_no="PREVIOUS",
        bill_type="HRA Arrear",
        allowances={"HRA": "1000"},
        entitlement_period={"start": "2026-07-05", "end": "2026-07-31"},
        allocations_by_head={
            "HRA": [dict(start="2026-07-05", end="2026-07-31", amount="1000")]
        },
    )
    f = facts()
    f["bills"] += [prior, deepcopy(prior)]
    assert reconcile_hra(f)["blockers"]
    f = facts()
    f["bills"].append(prior)
    prior["allocations_by_head"]["HRA"][0].update(start="2026-01-01", end="2026-01-31")
    assert reconcile_hra(f)["blockers"]


def test_printed_net_contradiction_blocks_and_leave_credit_is_not_salary():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["bills"][0].update(printed_deductions="0", printed_net="100")
    assert reconcile_hra(f)["blockers"]
    f = facts()
    f["bills"].append(
        dict(
            employee_code="RJTEST42",
            pay_month="2026-07",
            bill_no="LEAVE",
            bill_type="HRA Arrear",
            entitlement_type="leave_encashment",
            allowances={"HRA": "1000"},
        )
    )
    assert reconcile_hra(f)["drafts"][0]["calculation"]["total"] == "5400.00"


def test_saved_external_credit_recalculates_and_can_be_reviewed(client, monkeypatch):
    import io, sys, types, pymupdf

    monkeypatch.setitem(
        sys.modules,
        "ifms_suite.document_facts",
        types.SimpleNamespace(
            extract_document_facts=lambda value: facts(), FACTS_VERSION=1
        ),
    )
    r = client.post(
        "/suite/api/payments/manual",
        json=dict(
            employee_code="RJTEST42",
            pay_month="2026-09",
            bill_no="PREVIOUS",
            bill_type="HRA Arrear",
            allowances={"HRA": "1000"},
            entitlement_period={"start": "2026-07-05", "end": "2026-07-31"},
            allocations_by_head={
                "HRA": [dict(start="2026-07-05", end="2026-07-31", amount="1000")]
            },
            reviewed=True,
            reference="Source credit",
        ),
    )
    assert r.status_code == 201, r.json
    d = pymupdf.open()
    d.new_page()
    source = client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(d.tobytes()), "bundle.pdf")},
    )
    generated = client.post(
        f"/suite/api/imports/{source.json['id']}/automatic_hra", json={}
    ).json
    claim = generated["claims"][0]
    assert claim["calculation"]["total"] == "4400.00"
    final = client.post(
        f"/suite/api/claims/{claim['id']}/finalize",
        json=dict(
            reviewed=True,
            machine_facts_reviewed=True,
            rule_reference="Source order",
            drawn_reference="Source bill and credit",
        ),
    )
    assert final.status_code == 200, final.json


def test_negative_prior_allocation_cannot_increase_automatic_payable():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["bills"].append(
        dict(
            employee_code="RJTEST42",
            pay_month="2026-09",
            bill_no="SIGNED",
            bill_type="HRA Arrear",
            allowances={"HRA": "1000"},
            entitlement_period={"start": "2026-07-05", "end": "2026-09-30"},
            allocations_by_head={
                "HRA": [
                    dict(start="2026-07-05", end="2026-07-31", amount="-1000"),
                    dict(start="2026-08-01", end="2026-08-31", amount="0"),
                    dict(start="2026-09-01", end="2026-09-30", amount="2000"),
                ]
            },
        )
    )
    assert reconcile_hra(f)["blockers"]


def test_incomplete_prior_bill_does_not_establish_zero_hra():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["bills"].append(
        dict(
            employee_code="RJTEST42",
            pay_month="2026-07",
            bill_no="UNKNOWN",
            bill_type="DA Arrear",
            allowances={"DA": "1000"},
            complete=False,
        )
    )
    assert reconcile_hra(f)["blockers"]


def test_failed_page_and_unresolved_matching_order_block_but_other_order_does_not():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["issues"] = [
        dict(
            page=3, blocking=True, issue="Printed page recognition unresolved (Timeout)"
        )
    ]
    assert not reconcile_hra(f)["drafts"]
    f = facts()
    f["issues"] = [
        dict(
            page=3,
            employee_code="RJTEST42",
            issue="Employee order date/rate unresolved",
        )
    ]
    assert not reconcile_hra(f)["drafts"]
    f["issues"][0]["employee_code"] = "OTHER"
    assert reconcile_hra(f)["drafts"]


def test_partial_rounding_uses_library_policy_not_hardcoded_rupee():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    f["orders"][0]["effective_from"] = "2026-07-06"
    r = reconcile_hra(
        f,
        [
            dict(
                allowance="HRA",
                category="Y",
                rate="20",
                effective_from="2024-01-01",
                rounding="paise",
            )
        ],
    )
    assert r["drafts"][0]["calculation"]["total"] == "5200.00"
    f["bills"][0]["allowances"]["Basic"] = "31001"
    f["bills"][0]["printed_gross"] = "53734"
    r = reconcile_hra(
        f,
        [
            dict(
                allowance="HRA",
                category="Y",
                rate="20",
                effective_from="2024-01-01",
                rounding="paise",
            )
        ],
    )
    assert r["drafts"][0]["calculation"]["rows"][0]["due"] == "5200.17"


def test_rate_review_route_preserves_raw_facts_and_audits_confirmation(
    client, monkeypatch
):
    import io, sys, types, pymupdf
    from ifms_suite.fact_review import rate_review_requests

    f = facts()
    code = "RJXY204012345678"
    for bill in f["bills"]:
        bill["employee_code"] = code
    f.update(orders=[], facts_version="synthetic-v3")

    def word(text, confidence=0.96):
        return dict(
            text=text,
            confidence=confidence,
            recognizer="rapidocr",
            page=1,
            box=[0.1, 0.2, 0.5, 0.25],
        )

    f["issues"] = [
        dict(
            kind="order_unresolved",
            employee_code=code,
            page=1,
            allowance="HRA",
            scope="employee",
            blocking=True,
            unresolved_fields=["rate"],
            evidence=[word(code), word("05.07.2026"), word("?%", 0.2)],
        )
    ]
    monkeypatch.setitem(
        sys.modules,
        "ifms_suite.document_facts",
        types.SimpleNamespace(
            extract_document_facts=lambda _: deepcopy(f), FACTS_VERSION="synthetic-v3"
        ),
    )
    doc = pymupdf.open()
    doc.new_page()
    imported = client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(doc.tobytes()), "synthetic.pdf")},
    ).json
    base = f"/suite/api/imports/{imported['id']}"
    response = client.post(base + "/automatic_hra", json={})
    assert response.status_code == 200, response.json
    assert response.json["claims"] == []
    item = response.json["review_requests"][0]
    assert client.get(
        base + "/fact_review/" + item["request_id"] + "/image"
    ).data.startswith(b"\x89PNG")
    review = dict(
        request_id=item["request_id"],
        facts_version=item["facts_version"],
        rate="20",
        reviewed=False,
        reference="Synthetic source row",
    )
    assert client.post(base + "/fact_review", json=review).status_code == 400
    review["reviewed"] = True
    result = client.post(base + "/fact_review", json=review)
    assert result.status_code == 200, result.json
    assert result.json["claims"][0]["calculation"]["total"] == "5400.00"
    assert result.json["claims"][0]["human_assisted"] is True
    assert result.json["facts"] == f
    claims = client.get("/suite/api/claims").json
    assert claims[0]["payload"]["machine_evidence"]["order"]["human_reviewed"] is True
    pdf = client.get(f"/suite/api/claims/{claims[0]['id']}/pdf").data
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        assert "Human-confirmed rate" in "".join(p.get_text() for p in doc)
    from ifms_suite.storage import database
    import json

    with client.application.app_context(), database() as db:
        saved = json.loads(
            db.execute(
                "SELECT payload FROM suite_imports WHERE id=?", (imported["id"],)
            ).fetchone()["payload"]
        )
    assert saved["machine_facts"] == f
    assert saved["machine_fact_review_audit"][0]["source_sha256"]
    assert saved["machine_fact_review_audit"][0]["recorded_at"]
    review["facts_version"] = "stale"
    assert client.post(base + "/fact_review", json=review).status_code == 400


def test_unresolved_positive_prior_credit_cannot_reduce_draft():
    from ifms_suite.automatic_hra import reconcile_hra

    f = facts()
    prior = dict(
        employee_code="RJTEST42",
        pay_month="2026-09",
        bill_no="UNCERTAIN",
        bill_type="HRA Arrear",
        allowances={"HRA": "1000"},
        complete=False,
        printed_gross="9000",
        printed_deductions="0",
        printed_net="8000",
        entitlement_period={"start": "2026-07-05", "end": "2026-07-31"},
        allocations_by_head={
            "HRA": [dict(start="2026-07-05", end="2026-07-31", amount="1000")]
        },
    )
    f["bills"].append(prior)
    assert reconcile_hra(f)["drafts"] == []
    prior.update(complete=True, printed_gross="1000", printed_net="1000")
    f["issues"] = [
        dict(
            kind="recognition_conflict",
            scope="bill",
            blocking=True,
            employee_code="RJTEST42",
            bill_no="UNCERTAIN",
        )
    ]
    assert reconcile_hra(f)["drafts"] == []
