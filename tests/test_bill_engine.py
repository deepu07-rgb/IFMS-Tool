"""Synthetic evidence only; no real employee or source sample amounts."""

from copy import deepcopy

from ifms_suite.bill_engine import prepare_bill


def case():
    request = dict(
        kind="increment",
        employee_code="SYNTHETIC",
        start="2026-01-01",
        end="2026-02-28",
        effective_from="2026-01-01",
        old_basic="1000",
        new_basic="1100",
        pay_order_reference="Synthetic increment sanction",
        hra_eligible=True,
        hra_eligibility_reference="Synthetic eligibility",
        proration="calendar",
        rounding="rupee",
        rounding_scope="month",
        reviewed=True,
    )
    rates = [
        dict(
            allowance=h, rate=r, effective_from="2026-01-01", reference="Synthetic rate"
        )
        for h, r in [("DA", "50"), ("HRA", "10")]
    ]
    bills = []
    for month in ("2026-01", "2026-02"):
        bills.append(
            dict(
                employee_code="SYNTHETIC",
                pay_month=month,
                bill_no=month,
                bill_type="Regular Salary",
                complete=True,
                allowances={
                    "Basic": "1000",
                    "DA": "500",
                    "HRA": "100",
                    "RECOVERY": "-20",
                },
                deductions={"Tax": "30"},
                printed_gross="1580",
                printed_deductions="30",
                printed_net="1550",
                evidence=[{"page": 1, "text": "synthetic"}],
            )
        )
    return dict(bills=bills, issues=[]), request, rates


def test_multimonth_actual_drawn_signed_unchanged_and_source_reconciliation():
    facts, request, rates = case()
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    assert result["mode"] == "human_assisted"
    assert len(result["rows"]) == 2
    assert result["totals"]["difference"] == "320.00"
    recovery = next(
        c for c in result["rows"][0]["components"] if c["head"] == "RECOVERY"
    )
    assert recovery["due"] == recovery["drawn"] == "-20.00"
    assert result["rows"][0]["full_drawn_gross"] == "1580.00"


def test_revised_month_already_paid_has_zero_difference():
    facts, request, rates = case()
    facts["bills"][1].update(
        allowances={"Basic": "1100", "DA": "550", "HRA": "110", "RECOVERY": "-20"},
        printed_gross="1740",
        printed_net="1710",
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    assert result["rows"][1]["difference"] == "0.00"
    assert result["totals"]["difference"] == "160.00"


def test_inclusive_partial_dates_rate_change_and_explicit_coverage():
    facts, request, rates = case()
    request.update(start="2026-01-16", end="2026-01-31", rounding="paise")
    bill = facts["bills"][0]
    bill.update(
        covered_dates={"start": request["start"], "end": request["end"]},
        allowances={"Basic": "500", "DA": "250", "HRA": "50"},
        printed_gross="800",
        printed_net="770",
    )
    rates.append(
        dict(
            allowance="DA",
            rate="60",
            effective_from="2026-01-24",
            reference="Synthetic changed rate",
        )
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    da = next(c for c in result["rows"][0]["components"] if c["head"] == "DA")
    assert da["due"] == "312.26"
    assert da["drawn"] == "250.00"
    assert len(da["segments"]) == 2
    del bill["covered_dates"]
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_missing_month_preserves_verified_month_but_blocks_payable():
    facts, request, rates = case()
    facts["bills"].pop()
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "blocked"
    assert len(result["rows"]) == 1
    assert result["totals"]["net_payable"] is None


def test_hda_fraction_reference_required_and_independent_due_rounding():
    facts, request, rates = case()
    request.update(
        end="2026-01-31",
        hda_rule={
            "numerator": "1",
            "denominator": "12",
            "reference": "Synthetic HDA rule",
        },
    )
    bill = facts["bills"][0]
    bill["allowances"]["HDA"] = "125"
    bill.update(printed_gross="1705", printed_net="1675")
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    hda = next(c for c in result["rows"][0]["components"] if c["head"] == "HDA")
    assert (hda["due"], hda["drawn"], hda["difference"]) == (
        "138.00",
        "125.00",
        "13.00",
    )
    del request["hda_rule"]["reference"]
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_reconciliation_and_unknown_prior_credit_block():
    facts, request, rates = case()
    facts["bills"][0]["printed_net"] = "1551"
    assert prepare_bill(facts, request, rates)["status"] == "blocked"
    facts, request, rates = case()
    facts["bills"].append(
        dict(
            employee_code="SYNTHETIC",
            bill_type="DA arrear",
            allowances={"DA": "50"},
            complete=True,
            evidence=[{"page": 2}],
        )
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "blocked"
    assert any("covered" in b["message"].lower() for b in result["blockers"])


def test_prior_credit_requires_exact_month_head_allocation_and_deductions_explicit():
    facts, request, rates = case()
    facts["bills"].append(
        dict(
            employee_code="SYNTHETIC",
            bill_type="DA arrear",
            allowances={"DA": "50"},
            complete=True,
            evidence=[{"page": 2}],
            entitlement_period={"start": "2026-01-01", "end": "2026-01-31"},
        )
    )
    request["extra_deductions"] = [
        {
            "name": "Explicit tax",
            "mode": "fixed",
            "value": "10",
            "reference": "Synthetic instruction",
        }
    ]
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    assert result["totals"]["prior_settlement"] == "50.00"
    assert result["totals"]["net_payable"] == "260.00"


def test_hra_only_keeps_other_source_heads_and_uses_sanctioned_basic():
    facts, request, rates = case()
    request.update(kind="hra", end="2026-01-31", old_basic="1000", new_basic="1000")
    rates[1]["rate"] = "20"
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    assert result["totals"]["difference"] == "100.00"


def test_missing_rates_or_unknown_pages_do_not_become_zero():
    facts, request, rates = case()
    result = prepare_bill(facts, request, rates[:1])
    assert result["status"] == "blocked"
    facts["issues"] = [{"issue": "Unclassified financial page", "blocking": True}]
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_no_mutation_and_old_basic_not_needed_after_effective_date():
    facts, request, rates = case()
    originals = deepcopy((facts, request, rates))
    prepare_bill(facts, request, rates)
    assert (facts, request, rates) == originals
    del request["old_basic"]
    assert prepare_bill(facts, request, rates)["status"] == "ready"


def test_da_revision_updates_hda_only_with_explicit_rule():
    facts, request, rates = case()
    request.update(kind="da", end="2026-01-31", new_basic="1000")
    bill = facts["bills"][0]
    bill["allowances"]["HDA"] = "120"
    bill.update(printed_gross="1700", printed_net="1670")
    assert prepare_bill(facts, request, rates)["status"] == "blocked"
    request["hda_rule"] = dict(
        numerator="1", denominator="12", reference="Synthetic rule"
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    hda = next(c for c in result["rows"][0]["components"] if c["head"] == "HDA")
    assert hda["difference"] == "5.00"


def test_unresolved_prior_payment_never_disappears_and_duplicate_credits_block():
    facts, request, rates = case()
    prior = dict(
        employee_code="SYNTHETIC",
        bill_no="credit-1",
        bill_type="DA arrear",
        allowances={"DA": "50"},
        complete=True,
        evidence=[{"page": 2}],
        entitlement_period={"start": "2026-01-01", "end": "2026-01-31"},
        printed_gross="50",
        deductions={},
        printed_deductions="0",
        printed_net="50",
    )
    facts["bills"].extend([prior, deepcopy(prior)])
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_partial_hra_before_sanction_needs_explicit_prior_entitlement():
    facts, request, rates = case()
    request.update(kind="hra", end="2026-01-31", effective_from="2026-01-16")
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_expired_hda_rule_and_excess_deduction_block():
    facts, request, rates = case()
    request["extra_deductions"] = [
        {"name": "Tax", "mode": "fixed", "value": "9999", "reference": "Synthetic"}
    ]
    assert prepare_bill(facts, request, rates)["status"] == "blocked"
    del request["extra_deductions"]
    request["hda_rule"] = dict(
        numerator="1",
        denominator="12",
        reference="Synthetic",
        effective_to="2026-01-31",
    )
    for bill in facts["bills"]:
        bill["allowances"]["HDA"] = "125"
        bill.update(printed_gross="1705", printed_net="1675")
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "blocked"
    assert len(result["rows"]) == 1


def test_hra_proven_absent_zero_and_partial_zero_drawn_need_no_invented_allocation():
    facts, request, rates = case()
    request.update(kind="hra", start="2026-01-05", end="2026-01-31")
    del request["old_basic"]
    bill = facts["bills"][0]
    del bill["allowances"]["HRA"]
    bill.update(allowances_complete=True, printed_gross="1480", printed_net="1450")
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    hra = next(c for c in result["rows"][0]["components"] if c["head"] == "HRA")
    assert (hra["due"], hra["drawn"]) == ("87.00", "0.00")
    assert result["rows"][0]["full_drawn_gross"] == "1480.00"
    del bill["allowances_complete"]
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_hra_nonzero_partial_drawn_is_not_automatically_prorated():
    facts, request, rates = case()
    request.update(kind="hra", start="2026-01-05", end="2026-01-31")
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_dated_rate_must_match_sanction_and_da_does_not_need_hra_eligibility():
    facts, request, rates = case()
    request.update(kind="hra", rate="20")
    assert prepare_bill(facts, request, rates)["status"] == "blocked"
    request.update(kind="da", rate="50")
    del request["hra_eligible"]
    del request["hra_eligibility_reference"]
    assert prepare_bill(facts, request, rates)["status"] == "ready"


def test_other_employee_scoped_issue_does_not_block_verified_subject():
    facts, request, rates = case()
    facts["issues"] = [{"employee_code": "OTHER", "issue": "Missing monthly source"}]
    assert prepare_bill(facts, request, rates)["status"] == "ready"


def test_complete_da_only_credit_does_not_block_independent_hra_claim():
    facts, request, rates = case()
    request.update(kind="hra", end="2026-01-31")
    facts["bills"].append(
        dict(
            employee_code="SYNTHETIC",
            bill_no="prior",
            pay_month="2025-12",
            bill_type="DA arrear",
            allowances={"DA": "50"},
            printed_gross="50",
            complete=True,
            allowances_complete=True,
            evidence=[{"page": 3}],
        )
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    assert result["totals"]["difference"] == "0.00"
    facts["bills"][-1]["allowances_complete"] = False
    assert prepare_bill(facts, request, rates)["status"] == "blocked"


def test_unknown_amount_prior_arrear_cannot_disappear():
    facts, request, rates = case()
    facts["bills"].append(
        dict(
            employee_code="SYNTHETIC",
            bill_type="DA arrear",
            pay_month="2025-12",
            allowances={},
            printed_gross="50",
            complete=False,
            issues=["Unreadable DA"],
        )
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "blocked"
    assert any(
        "credit" in b["message"].lower() or "arrear" in b["message"].lower()
        for b in result["blockers"]
    )


def test_da_dependent_hda_credit_is_subtracted():
    facts, request, rates = case()
    request.update(
        kind="da",
        end="2026-01-31",
        hda_rule={
            "numerator": "1",
            "denominator": "12",
            "reference": "Synthetic governing rule",
        },
    )
    bill = facts["bills"][0]
    bill["allowances"]["HDA"] = "120"
    bill.update(printed_gross="1700", printed_net="1670")
    rates[0]["rate"] = "60"
    facts["bills"].append(
        dict(
            employee_code="SYNTHETIC",
            bill_type="HDA arrear",
            bill_no="prior",
            pay_month="2026-02",
            allowances={"HDA": "5"},
            printed_gross="5",
            complete=True,
            allowances_complete=True,
            evidence=[{"page": 3}],
            entitlement_period={"start": "2026-01-01", "end": "2026-01-31"},
        )
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "ready", result
    assert result["totals"]["difference"] == "108.00"
    assert result["totals"]["prior_settlement"] == "5.00"


def test_unknown_prior_coverage_preserves_monthly_work_but_blocks_payable():
    facts, request, rates = case()
    facts["bills"].append(
        dict(
            employee_code="SYNTHETIC",
            bill_type="DA arrear",
            pay_month="2025-12",
            allowances={"DA": "50"},
            printed_gross="50",
            complete=True,
            evidence=[{"page": 3}],
        )
    )
    result = prepare_bill(facts, request, rates)
    assert result["status"] == "blocked"
    assert len(result["rows"]) == 2
    assert result["totals"]["net_payable"] is None
    assert result["prior_credit_review_required"] is True
