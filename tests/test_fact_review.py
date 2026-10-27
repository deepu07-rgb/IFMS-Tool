"""Synthetic evidence for the narrow human HRA percentage review boundary."""

from copy import deepcopy

import pytest

from ifms_suite.fact_review import apply_rate_reviews, rate_review_requests


def word(text, confidence=0.96, recognizer="rapidocr", **extra):
    return dict(text=text, box=[0.1, 0.2, 0.3, 0.22], confidence=confidence,
                recognizer=recognizer, page=3, **extra)


def source():
    return {
        "facts_version": "synthetic-v3",
        "bills": [{"employee_code": "RJXY204012345678", "identity_reliable": True,
                   "allowances": {"Basic": "1200.00"}, "source_pages": [1]}],
        "orders": [],
        "issues": [{"kind": "order_unresolved", "employee_code": "RJXY204012345678",
                    "page": 3, "allowance": "HRA", "scope": "employee", "blocking": True,
                    "unresolved_fields": ["rate"], "evidence": [
                        word("RJXY204012345678"), word("07.11:2040"),
                        word("?%", confidence=0.12)]}],
    }


def review(facts, **changes):
    request = rate_review_requests(facts)[0]
    return dict(request_id=request["request_id"], facts_version=facts["facts_version"],
                rate="13.75", reviewed=True, reference="Checked original sanction row", **changes)


def test_offers_only_rate_using_trusted_identity_date_and_original_evidence():
    facts = source()
    original = deepcopy(facts)
    requests = rate_review_requests(facts)
    assert len(requests) == 1
    request = requests[0]
    assert {k: request[k] for k in ["employee_code", "effective_from", "page", "field", "facts_version"]} == {
        "employee_code": "RJXY204012345678", "effective_from": "2040-11-07", "page": 3,
        "field": "rate", "facts_version": "synthetic-v3"}
    assert len(request["request_id"]) == 64
    assert request["evidence"] == original["issues"][0]["evidence"]
    request["evidence"][0]["text"] = "mutated"
    assert facts == original


@pytest.mark.parametrize("change", ["no_bill", "bill_identity_uncertain", "extra_field", "duplicate_issue", "existing_order", "missing_version"])
def test_ambiguous_or_unmatched_sanction_never_requests_a_percentage(change):
    facts = source()
    if change == "no_bill":
        facts["bills"] = [{"employee_code": "RJZZ204012345678"}]
    elif change == "bill_identity_uncertain":
        facts["bills"][0]["identity_reliable"] = False
    elif change == "extra_field":
        facts["issues"][0]["unresolved_fields"].append("effective_from")
    elif change == "duplicate_issue":
        facts["issues"].append(deepcopy(facts["issues"][0]))
    elif change == "existing_order":
        facts["orders"].append({"employee_code": "RJXY204012345678", "allowance": "HRA"})
    else:
        facts.pop("facts_version")
    assert rate_review_requests(facts) == []


@pytest.mark.parametrize("text,confidence,recognizer,conflict,expected", [
    ("07/11.2040", .85, "rapidocr", False, True),
    ("07/11.2040", .849, "rapidocr", False, False),
    ("07/11.2040", .80, "tesseract-psm3", False, True),
    ("07/11.2040", .799, "tesseract", False, False),
    ("07/11.2040", 1, "pdf-text", False, True),
    ("07/11.2040", .99, "pdf-text", False, False),
    ("07/11.2040", .99, "rapidocr", True, False),
    ("31/02/2040", 1, "rapidocr", False, False),
    ("O7/11/2040", 1, "rapidocr", False, False),
])
def test_date_requires_literal_valid_calendar_value_and_recognizer_gate(text, confidence, recognizer, conflict, expected):
    facts = source()
    facts["issues"][0]["evidence"][1] = word(text, confidence, recognizer, recognition_conflict=conflict)
    assert bool(rate_review_requests(facts)) is expected


@pytest.mark.parametrize("change", ["second_date", "identity_conflict", "identity_low_confidence", "wrong_identity", "unknown_recognizer"])
def test_date_or_identity_ambiguity_blocks_field_review(change):
    facts = source()
    evidence = facts["issues"][0]["evidence"]
    if change == "second_date":
        evidence.append(word("08/11/2040"))
    elif change == "identity_conflict":
        evidence[0]["recognition_conflict"] = True
    elif change == "identity_low_confidence":
        evidence[0]["confidence"] = .3
    elif change == "wrong_identity":
        evidence[0]["text"] = "RJZZ204012345678"
    else:
        evidence[0]["recognizer"] = "unknown"
    assert rate_review_requests(facts) == []


def test_review_adds_only_confirmed_order_and_preserves_other_blockers_and_raw_facts():
    facts = source()
    unrelated = {"kind": "order_unresolved", "employee_code": "RJZZ204012345678", "page": 3,
                 "unresolved_fields": ["rate", "effective_from"], "blocking": True}
    bill_issue = {"kind": "bill_unresolved", "employee_code": "RJXY204012345678", "blocking": True}
    facts["issues"].extend([unrelated, bill_issue])
    original = deepcopy(facts)
    result = apply_rate_reviews(facts, [review(facts)])
    assert facts == original
    assert result["issues"] == [unrelated, bill_issue]
    assert result["bills"] == original["bills"]
    assert len(result["orders"]) == 1
    order = result["orders"][0]
    assert {k: order[k] for k in ["employee_code", "effective_from", "rate", "allowance", "human_reviewed", "review_reference", "source_pages"]} == {
        "employee_code": "RJXY204012345678", "effective_from": "2040-11-07", "rate": "13.75",
        "allowance": "HRA", "human_reviewed": True,
        "review_reference": "Checked original sanction row", "source_pages": [3]}
    assert order["evidence"] == original["issues"][0]["evidence"]


@pytest.mark.parametrize("field,value", [
    ("rate", True), ("rate", False), ("rate", 0), ("rate", -1), ("rate", "100.01"),
    ("rate", "NaN"), ("rate", "Infinity"), ("rate", None), ("rate", "bad"),
    ("reviewed", False), ("reviewed", "true"), ("reference", " "), ("reference", None),
    ("request_id", "stale"), ("facts_version", "stale"),
])
def test_rejects_invalid_or_unconfirmed_or_stale_reviews_without_mutation(field, value):
    facts = source()
    original = deepcopy(facts)
    entry = review(facts)
    entry[field] = value
    with pytest.raises(ValueError):
        apply_rate_reviews(facts, [entry])
    assert facts == original


def test_duplicate_review_rejected_and_request_identity_tracks_version_date_page_employee():
    facts = source()
    entry = review(facts)
    with pytest.raises(ValueError):
        apply_rate_reviews(facts, [entry, entry])
    baseline = rate_review_requests(facts)[0]["request_id"]
    assert rate_review_requests(deepcopy(facts))[0]["request_id"] == baseline
    for change in ["version", "date", "page", "employee"]:
        changed = deepcopy(facts)
        if change == "version":
            changed["facts_version"] = "synthetic-v4"
        elif change == "date":
            changed["issues"][0]["evidence"][1]["text"] = "08/11/2040"
        elif change == "page":
            changed["issues"][0]["page"] = 4
        else:
            changed["bills"][0]["employee_code"] = "RJZZ204012345678"
            changed["issues"][0]["employee_code"] = "RJZZ204012345678"
            changed["issues"][0]["evidence"][0]["text"] = "RJZZ204012345678"
        assert rate_review_requests(changed)[0]["request_id"] != baseline
        with pytest.raises(ValueError):
            apply_rate_reviews(changed, [entry])
