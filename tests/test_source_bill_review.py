from copy import deepcopy
import pytest


def case():
    raw = {
        "facts_version": "v6",
        "source_sha256": "a" * 64,
        "bills": [
            {
                "employee_code": "RJXY204012345678",
                "pay_month": "2040-01",
                "bill_no": "123456789",
                "bill_type": "Regular Salary",
                "allowances": {"Basic": "100"},
                "deductions": {},
                "source_pages": [2],
                "complete": False,
            }
        ],
        "issues": [
            {
                "kind": "bill_unresolved",
                "employee_code": "RJXY204012345678",
                "pay_month": "2040-01",
                "bill_no": "123456789",
                "source_pages": [2],
                "blocking": True,
                "issues": ["unreadable deduction"],
            },
            {"kind": "unsupported_page", "page": 3, "blocking": True},
        ],
    }
    return raw


def test_reviewed_source_bill_reconciles_without_changing_raw_or_other_pages():
    from ifms_suite.source_bill_review import bill_review_requests, apply_bill_reviews

    raw = case()
    before = deepcopy(raw)
    req = bill_review_requests(raw)[0]
    review = dict(
        request_id=req["request_id"],
        reviewed=True,
        reference="Original bill page 2",
        record=dict(
            raw["bills"][0],
            deductions={"GPF": "10"},
            printed_gross="100",
            printed_deductions="10",
            printed_net="90",
        ),
    )
    result = apply_bill_reviews(raw, [review])
    assert raw == before
    assert result["bills"][0]["complete"] is True
    assert result["bills"][0]["human_reviewed"] is True
    assert len(result["issues"]) == 1
    assert result["issues"][0]["kind"] == "unsupported_page"
    review["record"]["printed_net"] = "99"
    with pytest.raises(ValueError, match="reconcile"):
        apply_bill_reviews(raw, [review])


def test_review_retains_valid_partial_and_prior_allocation_dependencies():
    from ifms_suite.source_bill_review import bill_review_requests, apply_bill_reviews

    raw = case()
    req = bill_review_requests(raw)[0]
    record = dict(
        raw["bills"][0],
        bill_type="Basic arrear",
        deductions={"GPF": "10"},
        printed_gross="100",
        printed_deductions="10",
        printed_net="90",
        covered_dates={"start": "2040-01-16", "end": "2040-01-31"},
        monthly_basic="200",
        entitlement_period={"start": "2039-12-01", "end": "2039-12-31"},
        allocations_by_head={
            "BASIC": [{"start": "2039-12-01", "end": "2039-12-31", "amount": "100"}]
        },
    )
    review = dict(
        request_id=req["request_id"],
        reviewed=True,
        reference="Source coverage checked",
        record=record,
    )
    result = apply_bill_reviews(raw, [review])["bills"][0]
    assert result["covered_dates"] == record["covered_dates"]
    assert result["monthly_basic"] == "200.00"
    assert result["entitlement_period"] == record["entitlement_period"]
    assert result["allocations_by_head"]["BASIC"][0]["amount"] == "100.00"
