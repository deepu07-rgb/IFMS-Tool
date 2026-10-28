"""Explicit informational salary deductions do not reduce arrears a second time."""

from copy import deepcopy
import pytest


def test_bill_engine_keeps_informational_deduction_without_counting_in_net():
    from test_bill_engine import case
    from ifms_suite.bill_engine import prepare_bill

    facts, request, rates = case()
    for bill in facts["bills"]:
        bill["deductions"]["Cooperative"] = "12"
        bill["deduction_effects"] = {"Cooperative": False}
    original = deepcopy(facts)
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    assert result["totals"]["difference"] == "320.00"
    assert result["rows"][0]["source_deductions"]["Cooperative"] == "12"
    assert facts == original


def test_source_review_retains_explicit_nonaccounting_effect_and_raw_amount():
    from test_source_bill_review import case
    from ifms_suite.source_bill_review import bill_review_requests, apply_bill_reviews

    facts = case()
    record = dict(
        facts["bills"][0],
        deductions={"GPF": "10", "Cooperative": "12"},
        deduction_effects={"Cooperative": False},
        printed_gross="100",
        printed_deductions="10",
        printed_net="90",
    )
    review = dict(
        request_id=bill_review_requests(facts)[0]["request_id"],
        reviewed=True,
        reference="Synthetic explicit non-accounting source column",
        record=record,
    )
    saved = apply_bill_reviews(facts, [review])["bills"][0]
    assert saved["deduction_effects"]["COOPERATIVE"] is False
    assert saved["deductions"]["COOPERATIVE"] == "12.00"
    record["deduction_effects"] = {"Cooperative": "false"}
    with pytest.raises(ValueError, match="effect|accounting|net pay"):
        apply_bill_reviews(facts, [review])
