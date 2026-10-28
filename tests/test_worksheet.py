"""Independent synthetic arithmetic for the assisted worksheet, without OCR."""

from copy import deepcopy
import pytest


def example(**changes):
    row = dict(
        month="2040-07",
        start="2040-07-01",
        end="2040-07-31",
        presentation="period",
        drawn_BASIC="24800",
        drawn_DA="14880",
        drawn_HRA="0",
        drawn_HDA="3307",
        drawn_CCA="0",
        hra_rate="20",
        salary_reference="Synthetic July salary",
        order_reference="Synthetic HRA sanction",
        history_reference="Checked source: no previous HRA payment",
        deduction_reference="No additional deductions sanctioned",
        history_reviewed=True,
        deductions_reviewed=True,
        bill_no="SYN-1",
    )
    for head in ("BASIC", "DA", "HRA", "HDA", "CCA"):
        row["prior_" + head] = "0"
    for key in (
        "GPF",
        "SI",
        "CM_CORONA",
        "I_TAX",
        "GPF_TO_DEDUCT",
        "GPF_ALREADY_DEDUCTED",
        "SIF_ALREADY_DEDUCTED",
    ):
        row["ded_" + key] = "0"
    return dict(
        dict(
            employee_code="SYN-01",
            employee_name="Synthetic Person",
            kind="hra",
            template_id="jodhpur_classic",
            rounding="rupee",
            include_hda=False,
            rows=[row],
        ),
        **changes
    )


def calculate(payload):
    from ifms_suite.worksheet import calculate_worksheet

    return calculate_worksheet(payload)


def test_hra_uses_actual_drawn_and_explicit_none_adjustments():
    p = example()
    before = deepcopy(p)
    r = calculate(p)
    assert r["status"] == "ready", r
    assert r["bill"]["totals"]["difference"] == "4960.00"
    assert r["bill"]["totals"]["net_payable"] == "4960.00"
    assert r["bill"]["rows"][0]["components"][2]["drawn"] == "0.00"
    assert p == before


def test_partial_period_includes_both_dates_and_rounds_separate_heads():
    p = example()
    p["rows"][0]["start"] = "2040-07-05"
    r = calculate(p)
    assert r["bill"]["totals"]["difference"] == "4320.00"
    assert r["audit"][0]["days"] == 27
    assert r["audit"][0]["month_days"] == 31


def test_whole_month_keeps_unaffected_pay_before_effective_date():
    p = example(kind="increment", include_hda=True)
    p["rows"][0].update(
        month="2040-03",
        start="2040-03-22",
        end="2040-03-31",
        presentation="whole_month",
        drawn_BASIC="49500",
        drawn_DA="29700",
        drawn_HRA="9900",
        drawn_HDA="6600",
        new_basic="52300",
        da_rate="60",
        hra_rate="20",
        hda_divisor="12",
    )
    r = calculate(p)
    heads = {h["head"]: h for h in r["bill"]["rows"][0]["components"]}
    assert heads["BASIC"]["due"] == "50403.00"
    assert heads["DA"]["due"] == "30242.00"
    assert heads["HRA"]["due"] == "10081.00"
    assert heads["HDA"]["due"] == "6720.00"
    assert r["bill"]["totals"]["difference"] == "1746.00"


def test_prior_credit_is_added_to_drawn_once_and_not_prorated_again():
    p = example()
    p["rows"][0].update(start="2040-07-05", prior_HRA="1000", ded_GPF="120")
    r = calculate(p)
    assert r["bill"]["totals"]["prior_settlement"] == "1000.00"
    assert r["bill"]["totals"]["difference"] == "3320.00"
    assert r["bill"]["totals"]["net_payable"] == "3200.00"
    from ifms_suite.supplied_form import _prepared

    _, rows, _ = _prepared(r["bill"], r["metadata"])
    assert rows[0][11] == 1000  # already-drawn HRA
    assert rows[0][26] == 3200


def test_newer_gpf_columns_do_not_double_subtract_already_deducted_disclosures():
    p = example(template_id="jodhpur_gpf_arrear")
    p["rows"][0].update(
        ded_GPF_TO_DEDUCT="100",
        ded_GPF_ALREADY_DEDUCTED="800",
        ded_SIF_ALREADY_DEDUCTED="300",
        ded_I_TAX="50",
    )
    r = calculate(p)
    assert r["bill"]["totals"]["total_deductions"] == "150.00"
    assert r["bill"]["totals"]["net_payable"] == "4810.00"
    from ifms_suite.supplied_form import _prepared

    _, rows, _ = _prepared(r["bill"], r["metadata"])
    assert rows[0][21:27] == [100, 800, 300, 50, 150, 4810]


@pytest.mark.parametrize(
    "field,value",
    [
        ("drawn_HRA", ""),
        ("hra_rate", None),
        ("salary_reference", ""),
        ("order_reference", ""),
        ("history_reviewed", False),
        ("deductions_reviewed", False),
        ("prior_HRA", ""),
        ("ded_GPF", ""),
        ("hra_rate", "NaN"),
        ("drawn_BASIC", True),
        ("prior_HRA", "-1"),
        ("drawn_BASIC", "1.001"),
    ],
)
def test_missing_or_invalid_fields_block_without_guessing_zero(field, value):
    p = example()
    p["rows"][0][field] = value
    r = calculate(p)
    assert r["status"] == "incomplete"
    assert any(e["field"] == field for e in r["errors"]), r
    assert r["bill"]["totals"] is None


def test_signed_recovery_is_preserved():
    p = example()
    p["rows"][0]["drawn_HRA"] = "5000"
    r = calculate(p)
    assert r["bill"]["totals"]["difference"] == "-40.00"
    assert r["bill"]["totals"]["net_payable"] == "-40.00"


def test_manual_monthly_due_amounts_and_paise_rounding():
    p = example(kind="manual", rounding="paise")
    p["rows"][0].update(
        start="2040-07-05",
        **{
            "due_" + h: str(v)
            for h, v in zip(
                ("BASIC", "DA", "HRA", "HDA", "CCA"), (24800, 14880, 4960, 3307, 0)
            )
        }
    )
    r = calculate(p)
    assert r["bill"]["totals"]["difference"] == "4320.00"
    assert r["audit"][0]["heads"]["HRA"]["order_reference"] == "Synthetic HRA sanction"


def test_duplicate_or_cross_month_or_gapped_dates_are_not_merged():
    p = example()
    p["rows"].append(deepcopy(p["rows"][0]))
    assert calculate(p)["status"] == "incomplete"
    p = example()
    p["rows"][0]["end"] = "2040-08-01"
    assert calculate(p)["status"] == "incomplete"
    p = example()
    row = deepcopy(p["rows"][0])
    row.update(month="2040-09", start="2040-09-01", end="2040-09-30")
    p["rows"].append(row)
    assert calculate(p)["status"] == "incomplete"
