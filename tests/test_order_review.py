from copy import deepcopy

import pytest

from ifms_suite.order_review import apply_order_reviews, order_review_requests


def facts():
    return dict(
        facts_version="v1",
        source_sha256="a" * 64,
        bills=[dict(employee_code="RJAB203012345678")],
        order_candidates=[
            dict(
                kind="increment",
                employee_name="राम लाल",
                employee_code="",
                effective_from="",
                basic_amount=None,
                unresolved_fields=["employee_code", "effective_from", "basic_amount"],
                source_pages=[4],
                evidence=[
                    dict(
                        text="राम लाल",
                        page=4,
                        box=[0.1, 0.2, 0.3, 0.22],
                        confidence=0.4,
                        recognizer="tesseract",
                    )
                ],
            )
        ],
        issues=[dict(kind="unsupported_page", page=4, blocking=True)],
        orders=[],
        pay_orders=[],
    )


def review(f):
    r = order_review_requests(f)[0]
    return dict(
        request_id=r["request_id"],
        facts_version=f["facts_version"],
        source_sha256=f["source_sha256"],
        reviewed=True,
        reference="Page 4 signed increment row",
        employee_code="RJAB203012345678",
        effective_from="2026-07-01",
        basic_amount="50800",
        hra_eligible=False,
        hda_rule=dict(numerator="1", denominator="12", reference="Applicable rule 12"),
        entire_page_reviewed=True,
    )


def test_name_only_order_needs_explicit_employee_association_and_preserves_raw_source():
    f = facts()
    original = deepcopy(f)
    decision = review(f)
    result = apply_order_reviews(f, [decision])
    assert f == original
    assert result["order_candidates"] == original["order_candidates"]
    row = result["pay_orders"][0]
    assert row["basic_amount"] == "50800.00"
    assert row["employee_code"] == "RJAB203012345678"
    assert row["effective_from"] == "2026-07-01"
    assert row["hra_eligible"] is False
    assert row["hda_rule"]["denominator"] == "12"
    assert row["human_reviewed"] is True
    assert row["assisted"] is True
    assert row["evidence"] == original["order_candidates"][0]["evidence"]
    assert row["review_reference"] == decision["reference"]
    assert not result["issues"]


def test_missing_name_association_rejected():
    f = facts()
    decision = review(f)
    decision.pop("employee_code")
    with pytest.raises(ValueError, match="employee"):
        apply_order_reviews(f, [decision])


@pytest.mark.parametrize(
    "change",
    [
        dict(facts_version="v0"),
        dict(source_sha256="b" * 64),
        dict(reviewed=False),
        dict(reference=""),
        dict(effective_from="2026-02-31"),
        dict(basic_amount="NaN"),
        dict(hra_eligible="no"),
        dict(hda_rule=dict(numerator=1, denominator=0, reference="x")),
    ],
)
def test_invalid_reviews_rejected_atomically(change):
    f = facts()
    decision = review(f)
    decision.update(change)
    original = deepcopy(f)
    with pytest.raises(ValueError):
        apply_order_reviews(f, [decision])
    assert f == original


def test_request_binds_exact_raw_evidence_and_all_pages():
    f = facts()
    decision = review(f)
    f["order_candidates"][0]["evidence"][0]["text"] = "different name"
    with pytest.raises(ValueError, match="request"):
        apply_order_reviews(f, [decision])


def test_unsupported_page_can_be_targeted_without_inventing_ocr():
    f = facts()
    f["order_candidates"] = []
    f["issues"][0]["evidence"] = [dict(page=4, text="unreadable order")]
    decision = review(f)
    decision["kind"] = "increment"
    result = apply_order_reviews(f, [decision])
    assert result["pay_orders"][0]["evidence"] == f["issues"][0]["evidence"]
    assert result["pay_orders"][0]["assisted"]


def test_partial_page_review_keeps_page_blocker_and_other_issues():
    f = facts()
    f["issues"].append(dict(kind="identity_unresolved", page=4))
    decision = review(f)
    decision.pop("entire_page_reviewed")
    result = apply_order_reviews(f, [decision])
    assert result["issues"] == f["issues"]


def test_hra_and_da_reviews_store_dated_percentage_orders():
    for kind in ["HRA", "DA"]:
        f = facts()
        f["order_candidates"][0]["kind"] = kind
        decision = review(f)
        decision.pop("basic_amount")
        decision["rate"] = "20"
        result = apply_order_reviews(f, [decision])
        assert result["orders"][0]["allowance"] == kind
        assert result["orders"][0]["rate"] == "20"


def test_unknown_employee_and_repeated_request_rejected():
    f = facts()
    decision = review(f)
    decision["employee_code"] = "RJCD203012345678"
    with pytest.raises(ValueError, match="employee"):
        apply_order_reviews(f, [decision])
    decision = review(f)
    with pytest.raises(ValueError, match="request"):
        apply_order_reviews(f, [decision, decision])


def test_candidate_review_resolves_only_matching_order_issue():
    f = facts()
    f["issues"] += [
        dict(kind="pay_order_unresolved", page=4, order_candidate_index=0),
        dict(kind="pay_order_unresolved", page=5, order_candidate_index=1),
    ]
    result = apply_order_reviews(f, [review(f)])
    assert result["issues"] == [f["issues"][2]]


def test_multiple_issue_reviews_resolve_original_indexes_atomically():
    f = facts()
    f["order_candidates"] = []
    f["issues"] = [
        dict(kind="order_unresolved", page=4),
        dict(kind="order_unresolved", page=5),
    ]
    decisions = []
    for req in order_review_requests(f):
        decision = review(f)
        decision.update(request_id=req["request_id"], kind="increment")
        decisions.append(decision)
    result = apply_order_reviews(f, decisions)
    assert result["issues"] == []
    assert len(result["pay_orders"]) == 2


def test_increment_candidate_does_not_hide_separate_allowance_issue_on_same_page():
    f = facts()
    f["issues"].append(
        dict(
            kind="order_unresolved",
            allowance="HRA",
            page=4,
            employee_code="RJAB203012345678",
            unresolved_fields=["rate"],
        )
    )
    requests = order_review_requests(f)
    assert len(requests) == 2
    assert {r["kind"] for r in requests} == {"increment", "hra"}


def test_missing_source_binding_does_not_offer_review():
    for key in ["facts_version", "source_sha256"]:
        f = facts()
        f.pop(key)
        assert order_review_requests(f) == []


def test_reference_role_is_not_offered_as_an_order():
    f = facts()
    f["order_candidates"] = []
    f["issues"][0]["role"] = "reference_statement"
    assert order_review_requests(f) == []


def test_sequential_issue_review_ids_survive_resolution_of_earlier_page():
    f = facts()
    f["order_candidates"] = []
    f["issues"] = [
        dict(kind="order_unresolved", page=4),
        dict(kind="order_unresolved", page=5),
    ]
    first = review(f)
    first["kind"] = "increment"
    partial = apply_order_reviews(f, [first])
    second = review(partial)
    second["kind"] = "increment"
    result = apply_order_reviews(f, [first, second])
    assert len(result["pay_orders"]) == 2
    assert result["issues"] == []


def test_order_page_offers_explicit_association_for_employee_whose_row_was_not_read():
    f = facts()
    f["order_candidates"] = []
    f["page_classifications"] = [{"page": 4, "kind": "hra_order"}]
    f["issues"] = [
        dict(
            kind="order_unresolved",
            page=4,
            employee_code="RJZZ203012345678",
            allowance="HRA",
        )
    ]
    requests = order_review_requests(f)
    own = next(r for r in requests if r["employee_code"] == "RJAB203012345678")
    assert own["kind"] == "hra"
    assert own["candidate"]["recognition_status"] == "not_read_requires_source_review"
    decision = dict(
        request_id=own["request_id"],
        source_sha256=f["source_sha256"],
        facts_version=f["facts_version"],
        reviewed=True,
        reference="Original employee row checked",
        kind="hra",
        employee_code="RJAB203012345678",
        effective_from="2026-07-01",
        rate="20",
    )
    result = apply_order_reviews(f, [decision])
    assert result["orders"][0]["human_reviewed"] is True
    assert f["issues"] == result["issues"]


def test_review_supersedes_only_its_exact_incomplete_source_order():
    f = facts()
    candidate = f["order_candidates"][0]
    candidate["employee_code"] = "RJAB203012345678"
    candidate["complete"] = False
    f["pay_orders"] = [deepcopy(candidate)]
    decision = review(f)
    result = apply_order_reviews(f, [decision])
    assert len(result["pay_orders"]) == 1
    assert result["pay_orders"][0]["complete"] is True
    assert f["pay_orders"][0]["complete"] is False
