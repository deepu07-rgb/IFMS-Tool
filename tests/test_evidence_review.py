"""Bill field reviews remain source-bound and preserve unresolved evidence."""

from copy import deepcopy
import importlib

import pytest

SHA = "a" * 64
VERSION = "geometry-test"


def api():
    return importlib.import_module("ifms_suite.evidence_review")


def source():
    return dict(
        facts_version=VERSION,
        bills=[
            dict(
                employee_code="",
                pay_month="",
                bill_no="",
                identity_reliable=False,
                period_reliable=False,
                bill_type="Regular Salary",
                bill_type_reliable=True,
                allowances={"Basic": "100.00", "HRA": "20.00"},
                printed_gross="120.00",
                printed_deductions="10.00",
                printed_net="110.00",
                net_reconciled=True,
                complete=False,
                allowances_complete=False,
                source_pages=[2, 3],
                evidence=[
                    dict(text="100.00", page=2, confidence=0.2, recognizer="rapidocr")
                ],
            )
        ],
        issues=[
            dict(
                kind="bill_unresolved",
                employee_code="",
                pay_month="",
                bill_no="",
                source_pages=[2, 3],
                blocking=True,
                issues=[
                    "Employee identity unresolved",
                    "Pay month unresolved",
                    "Bill number unresolved",
                    "Low confidence: 100.00",
                ],
            )
        ],
    )


def entries(facts, values):
    requests = api().evidence_requests(facts, SHA, VERSION)
    return [
        dict(
            request_id=r["request_id"],
            source_sha256=SHA,
            facts_version=VERSION,
            field=r["field"],
            value=values[r["field"]],
            reviewed=True,
            reference="Original PDF page 2, bill row",
        )
        for r in requests
        if r["field"] in values
    ]


VALUES = dict(
    employee_code="RJXY204012345678",
    pay_month="2040-11",
    bill_no="123456789",
    **{"allowances.Basic": "100.00"}
)


def test_requests_preserve_provenance_and_offer_existing_records_only():
    facts = source()
    requests = api().evidence_requests(facts, SHA, VERSION)
    assert {"employee_code", "pay_month", "bill_no", "allowances.Basic"} <= {
        r["field"] for r in requests
    }
    assert "allowances.DA" not in {r["field"] for r in requests}
    assert all(
        r["source_pages"] == [2, 3] and r["source_sha256"] == SHA for r in requests
    )
    requests[0]["evidence"][0]["text"] = "changed"
    assert facts["bills"][0]["evidence"][0]["text"] == "100.00"


def test_explicit_repairs_recalculate_complete_without_blanket_review_or_raw_mutation():
    facts = source()
    original = deepcopy(facts)
    result = api().apply_evidence_reviews(facts, entries(facts, VALUES), SHA, VERSION)
    assert facts == original
    bill = result["bills"][0]
    assert bill["complete"] and bill["allowances_complete"] and bill["net_reconciled"]
    assert bill["identity_reliable"] and bill["period_reliable"]
    assert bill.get("reviewed") is not True
    assert bill["evidence"] == original["bills"][0]["evidence"]
    assert bill["field_reviews"]["allowances.Basic"]["reference"]
    assert result["issues"] == []


def test_partial_review_and_unrelated_blockers_stay_incomplete():
    facts = source()
    facts["issues"][0]["issues"].append("Repeated heads in continuation")
    facts["issues"].append(dict(kind="unsupported_page", page=4, blocking=True))
    result = api().apply_evidence_reviews(facts, entries(facts, VALUES), SHA, VERSION)
    assert result["bills"][0]["complete"] is False
    assert result["issues"][0]["issues"] == ["Repeated heads in continuation"]
    assert result["issues"][1] == facts["issues"][1]
    partial = api().apply_evidence_reviews(
        source(),
        entries(source(), {"employee_code": VALUES["employee_code"]}),
        SHA,
        VERSION,
    )
    assert partial["bills"][0]["complete"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("employee_code", "BAD"),
        ("pay_month", "2040-13"),
        ("pay_month", "2040-2"),
        ("bill_no", "123"),
        ("allowances.Basic", True),
        ("allowances.Basic", "NaN"),
        ("allowances.Basic", "Infinity"),
        ("allowances.Basic", "100.001"),
        ("allowances.Basic", "1e2"),
    ],
)
def test_invalid_review_value_is_rejected_atomically(field, value):
    facts = source()
    original = deepcopy(facts)
    values = dict(VALUES, **{field: value})
    with pytest.raises(ValueError):
        api().apply_evidence_reviews(facts, entries(facts, values), SHA, VERSION)
    assert facts == original


@pytest.mark.parametrize(
    "key,value",
    [
        ("request_id", "unknown"),
        ("facts_version", "old"),
        ("source_sha256", "b" * 64),
        ("reviewed", "true"),
        ("reference", " "),
        ("field", "allowances.DA"),
    ],
)
def test_stale_unconfirmed_or_unknown_reviews_are_rejected(key, value):
    facts = source()
    reviews = entries(facts, VALUES)
    reviews[0][key] = value
    with pytest.raises(ValueError):
        api().apply_evidence_reviews(facts, reviews, SHA, VERSION)


def test_duplicate_and_stale_snapshot_rejected():
    facts = source()
    reviews = entries(facts, VALUES)
    with pytest.raises(ValueError):
        api().apply_evidence_reviews(facts, [reviews[0], reviews[0]], SHA, VERSION)
    facts["bills"][0]["printed_gross"] = "121.00"
    with pytest.raises(ValueError):
        api().apply_evidence_reviews(facts, reviews, SHA, VERSION)


def test_mismatched_totals_never_complete_and_absent_totals_never_guessed_zero():
    facts = source()
    facts["bills"][0].update(printed_net=None, net_reconciled=False)
    result = api().apply_evidence_reviews(facts, entries(facts, VALUES), SHA, VERSION)
    assert result["bills"][0]["printed_net"] is None
    assert result["bills"][0]["complete"] is False
    values = dict(VALUES, printed_net="109.00")
    result = api().apply_evidence_reviews(facts, entries(facts, values), SHA, VERSION)
    assert not result["bills"][0]["net_reconciled"]
    assert not result["bills"][0]["complete"]


@pytest.mark.parametrize("sha,version", [("bad", VERSION), (SHA, "stale")])
def test_invalid_binding_is_rejected(sha, version):
    with pytest.raises(ValueError):
        api().evidence_requests(source(), sha, version)


def test_month_and_formatted_money_confidence_resolve_only_with_their_review():
    facts = source()
    bill = facts["bills"][0]
    bill.update(pay_month="2040-11", period_reliable=False)
    bill["allowances"]["Basic"] = "1000.00"
    bill.update(printed_gross="1020.00", printed_net="1010.00")
    issue = facts["issues"][0]
    issue.update(pay_month="2040-11")
    issue["issues"] = [
        "Employee identity unresolved",
        "Bill number unresolved",
        "Low confidence: November",
        "Recognition conflict: 1,000.00",
    ]
    values = dict(VALUES, **{"allowances.Basic": "1000.00"})
    result = api().apply_evidence_reviews(facts, entries(facts, values), SHA, VERSION)
    assert result["bills"][0]["complete"] is True
    assert result["issues"] == []


def test_unknown_bill_type_and_document_blocker_cannot_be_overridden_by_money_review():
    facts = source()
    facts["bills"][0]["bill_type_reliable"] = False
    facts["issues"][0]["issues"].append("Bill type unresolved")
    result = api().apply_evidence_reviews(facts, entries(facts, VALUES), SHA, VERSION)
    assert not result["bills"][0]["complete"]
    assert "Bill type unresolved" in result["issues"][0]["issues"]
    assert all(
        r["field"] != "bill_type" for r in api().evidence_requests(facts, SHA, VERSION)
    )


def test_no_provenance_and_complete_bills_never_offer_mutations():
    facts = source()
    facts["bills"][0]["source_pages"] = []
    assert api().evidence_requests(facts, SHA, VERSION) == []
    facts["bills"][0]["source_pages"] = [2]
    facts["bills"][0]["complete"] = True
    assert api().evidence_requests(facts, SHA, VERSION) == []


def test_reviews_do_not_infer_missing_allowance_heads_or_zero_from_empty_values():
    facts = source()
    values = dict(VALUES, **{"allowances.Basic": "-100.00"})
    result = api().apply_evidence_reviews(facts, entries(facts, values), SHA, VERSION)
    assert result["bills"][0]["allowances"]["Basic"] == "-100.00"
    assert "DA" not in result["bills"][0]["allowances"]
    assert not result["bills"][0]["complete"]
    assert api().apply_evidence_reviews(facts, [], SHA, VERSION) == facts


def test_absent_both_net_totals_cannot_become_complete_payment():
    facts = source()
    facts["bills"][0].pop("printed_deductions")
    facts["bills"][0].pop("printed_net")
    facts["bills"][0].pop("net_reconciled")
    result = api().apply_evidence_reviews(facts, entries(facts, VALUES), SHA, VERSION)
    assert result["bills"][0]["complete"] is False
