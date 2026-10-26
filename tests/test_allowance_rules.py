from decimal import Decimal
from ifms_suite.calculation import calculate_claim
import pytest


def compute(s, **kwargs):
    return calculate_claim(
        "2025-03-13",
        "2025-03-31",
        [dict(start="2025-03-01", end="2025-03-31", **s)],
        **kwargs
    )


def test_fixed_custom_monthly_and_actual_drawn():
    r = compute(
        dict(basis="fixed", due_amount="1200", drawn_amount="500", drawn_basis="period")
    )
    assert r["rows"][0]["due"] == "735.48"
    assert r["rows"][0]["drawn"] == "500.00"
    assert r["total"] == "235.48"


def test_daily_allowance():
    r = compute(dict(basis="daily", due_amount="100", drawn_amount="80"))
    assert r["total"] == "380.00"


def test_hda_follows_da_and_revised_basic():
    r = compute(
        dict(
            basis="basic_da",
            basic="50000",
            drawn_basic="48000",
            due_da_rate="55",
            drawn_da_rate="53",
            due_rate="8",
            drawn_rate="8",
        )
    )
    assert r["rows"][0]["due"] == "3800.00"
    assert r["rows"][0]["drawn"] == "3600.93"
    assert r["total"] == "199.07"


def test_rupee_rounding_and_deduction_allocation():
    r = compute(
        dict(basic="50000", due_rate="55", drawn_rate="53", rounding="rupee"),
        deductions=[
            dict(name="GPF", mode="percent", value="50"),
            dict(name="Tax", mode="fixed", value="10"),
        ],
    )
    assert r["total"] == "613.00"
    assert r["total_deductions"] == "316.50"
    assert r["net_payable"] == "296.50"
    assert r["deductions"][0]["amount"] == "306.50"


def test_selected_components_and_30_day_policy_requires_explicit_rule():
    r = compute(
        dict(
            basis="components",
            due_components={"basic": "50000", "DA": "27500"},
            drawn_components={"basic": "50000", "DA": "26500"},
            due_rate="10",
            drawn_rate="10",
            proration="thirty",
        )
    )
    assert r["rows"][0]["denominator"] == 30
    assert r["total"] == "60.00"  # Explicit 30-day service convention excludes day 31.


@pytest.mark.parametrize(
    "s",
    [
        {"basis": "fixed", "due_amount": "100"},
        {"basis": "unknown", "basic": "100", "due_rate": "5", "drawn_rate": "2"},
    ],
)
def test_rule_never_guesses_missing_drawn_or_unknown_basis(s):
    with pytest.raises(ValueError):
        compute(s)


def test_monthly_rounding_is_applied_after_pay_slices_are_combined():
    rows = [
        dict(
            start="2025-01-01",
            end="2025-01-10",
            basis="fixed",
            due_amount="1",
            drawn_amount="0",
            rounding="rupee",
            rounding_scope="month",
        ),
        dict(
            start="2025-01-11",
            end="2025-01-20",
            basis="fixed",
            due_amount="1",
            drawn_amount="0",
            rounding="rupee",
            rounding_scope="month",
        ),
        dict(
            start="2025-01-21",
            end="2025-01-31",
            basis="fixed",
            due_amount="1",
            drawn_amount="0",
            rounding="rupee",
            rounding_scope="month",
        ),
    ]
    r = calculate_claim("2025-01-01", "2025-01-31", rows)
    assert r["total"] == "1.00"
    assert sum(Decimal(row["due"]) for row in r["rows"]) == Decimal("1.00")
    assert r["rows"][-1]["rounding_adjustment_due"] == "1.00"


def test_actual_drawn_paise_are_not_rounded_again_by_entitlement_policy():
    r = compute(
        dict(
            basis="fixed",
            due_amount="1200",
            drawn_amount="500.50",
            drawn_basis="period",
            rounding="rupee",
            rounding_scope="month",
        )
    )
    assert r["rows"][0]["due"] == "735.00"
    assert r["rows"][0]["drawn"] == "500.50"
    assert r["total"] == "234.50"


def test_daily_due_uses_actual_monthly_drawn_as_a_monthly_amount():
    r = compute(
        dict(
            basis="daily",
            due_amount="100",
            drawn_amount="900",
            drawn_basis="monthly_amount",
        )
    )
    assert r["rows"][0]["due"] == "1900.00"
    assert r["rows"][0]["drawn"] == "551.61"
