"""Reviewed increment reconciliation using dated library rates and actual drawn heads."""

import json
from datetime import date, timedelta
from calendar import monthrange
from decimal import Decimal
from flask import request, jsonify
from .storage import database
from .calculation import money, rounded, calculate_claim
from .history import active
from .payroll import identity, payment_records
from .payment_types import payment_class, entitlement_type


def period_rate(rates, start, end, label):
    selected = active(rates, start, label)
    boundaries = {end}
    for row in rates:
        first = date.fromisoformat(row["effective_from"])
        if start < first <= end:
            boundaries.add(first)
        if row.get("effective_to"):
            last = date.fromisoformat(row["effective_to"])
            if start <= last < end:
                boundaries.add(last + timedelta(days=1))
    if any(active(rates, day, label) is not selected for day in boundaries):
        raise ValueError(
            "Split the period at every effective rate change; use dated segments"
        )
    return selected


def guard_prior_increment(db, code, start, end, heads):
    for payment in payment_records(db, code):
        if (
            payment_class(payment) in ("regular_salary", "leave_encashment", "bonus")
            or entitlement_type(payment) != "salary"
        ):
            continue
        if not any(
            identity(k) in heads and money(v) != 0
            for k, v in payment.get("allowances", {}).items()
        ):
            continue
        period = payment.get("entitlement_period")
        if not period or (period["start"] <= end and start <= period["end"]):
            raise ValueError(
                "Review prior arrear bill "
                + str(payment.get("bill_no", ""))
                + ": allocate its entitlement period; use the history/manual settlement workflow if it overlaps this increment"
            )


def register_increments(suite):
    @suite.post("/api/increment_check")
    def increment_check():
        p = request.get_json() or {}
        if (
            p.get("reviewed") is not True
            or not p.get("pay_order_reference")
            or not p.get("effective_from")
            or not identity(p.get("employee_code"))
        ):
            raise ValueError(
                "Review the increment order, employee, actual drawn amounts and allowance eligibility"
            )
        a, b = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        if (
            a > b
            or (a.year, a.month) != (b.year, b.month)
            or a.day != 1
            or b.day != monthrange(b.year, b.month)[1]
        ):
            raise ValueError(
                "Check one full calendar month; use manual dated segments for a partial increment period"
            )
        effective = date.fromisoformat(p["effective_from"])
        if a < effective:
            raise ValueError(
                "The increment is not effective for the whole selected month; use the dated-period workflow if it starts midmonth"
            )
        basic = money(p["new_basic"])
        if basic < 0:
            raise ValueError("Basic pay must be nonnegative")
        drawn = {identity(k): money(v) for k, v in p.get("drawn", {}).items()}
        heads = ["BASIC", "DA", "HRA"] + (["HDA"] if p.get("hda_rule") else [])
        if any(h not in drawn for h in heads):
            raise ValueError(
                "Every selected drawn component is required, including an explicitly reviewed zero"
            )
        if any(v != rounded(v) for v in drawn.values()):
            raise ValueError("Drawn amounts may have at most two decimals")
        warnings = []
        with database() as db:
            guard_prior_increment(
                db, identity(p["employee_code"]), str(a), str(b), heads
            )
            rates = [
                json.loads(r["payload"])
                for r in db.execute("SELECT payload FROM suite_rates")
            ]
            selected = {}
            for head in ("DA", "HRA"):
                eligible = [
                    r
                    for r in rates
                    if identity(r["allowance"]) == head
                    and r.get("category", "")
                    == (p.get("category", "") if head == "HRA" else "")
                ]
                rate = period_rate(eligible, a, b, head + " rate")
                selected[head] = rate
            da = money(selected["DA"]["rate"])
            hra = money(selected["HRA"]["rate"])
            due = {"BASIC": basic, "DA": basic * da / 100, "HRA": basic * hra / 100}
            formula = {
                "BASIC": "Approved pay-matrix value from reviewed increment order",
                "DA": f"Basic x {da}%",
                "HRA": f"Basic x {hra}%",
            }
            if p.get("hda_rule"):
                rule = p["hda_rule"]
                n, d = money(rule["numerator"]), money(rule["denominator"])
                if n <= 0 or d <= 0 or not rule.get("reference"):
                    raise ValueError(
                        "HDA needs a positive fraction and a reviewed rule reference"
                    )
                due["HDA"] = (basic + due["DA"]) * n / d
                formula["HDA"] = f"(Basic + DA) x {n}/{d}; " + rule["reference"]
            if (
                drawn["BASIC"]
                and rounded(drawn["BASIC"] * da / 100, "rupee") != drawn["DA"]
            ):
                warnings.append(
                    "Drawn DA differs from the selected library rate applied to drawn basic; review the dated order and actual payment"
                )
            others = {
                str(k): money(v) for k, v in p.get("unchanged_allowances", {}).items()
            }
            if any(identity(k) in heads for k in others):
                raise ValueError(
                    "A changed allowance cannot also be entered as unchanged"
                )
            selected_drawn = sum((drawn[h] for h in heads), Decimal(0))
            full_drawn = selected_drawn + sum(others.values(), Decimal(0))
            if p.get("printed_drawn_gross") not in ("", None) and full_drawn != money(
                p["printed_drawn_gross"]
            ):
                raise ValueError(
                    "Drawn components plus unchanged heads do not match GA55 gross"
                )
            display_rates = {"BASIC": "100", "DA": str(da), "HRA": str(hra)}
            if "HDA" in heads:
                display_rates["HDA"] = f"{100*n/d:.6f}"
            components = []
            ids = []
            total = Decimal(0)
            due_total = Decimal(0)
            for head in heads:
                reference = (
                    (
                        selected[head].get("reference", "")
                        + " "
                        + selected[head].get("order_date", "")
                    )
                    if head in selected
                    else p["pay_order_reference"] if head == "BASIC" else formula[head]
                )
                segment = dict(
                    start=str(a),
                    end=str(b),
                    basis="fixed",
                    basic=str(basic),
                    drawn_basic=str(drawn["BASIC"]),
                    due_rate=display_rates[head],
                    due_amount=str(due[head]),
                    drawn_amount=str(drawn[head]),
                    drawn_basis=(
                        "period"
                        if p.get("drawn_covers_selected_period") is True
                        else "monthly_amount"
                    ),
                    rounding="rupee",
                    rounding_scope="month",
                    rule_reference=reference,
                    source="Source-reviewed GA55; " + p.get("drawn_reference", ""),
                    proration="calendar",
                )
                calculation = calculate_claim(str(a), str(b), [segment])
                row = calculation["rows"][0]
                components.append(
                    dict(
                        head=head,
                        due=row["due"],
                        drawn=row["drawn"],
                        difference=row["difference"],
                        formula=formula[head],
                        reference=reference,
                    )
                )
                total += money(row["difference"])
                due_total += money(row["due"])
                payload = dict(
                    employee_code=identity(p["employee_code"]),
                    allowance=head,
                    start=str(a),
                    end=str(b),
                    source="reviewed_increment",
                    segments=[segment],
                    rule_reference=reference,
                    pay_order_reference=p["pay_order_reference"],
                    increment_effective_from=str(effective),
                    drawn_reference=p.get("drawn_reference", "Source-reviewed GA55"),
                    formula=formula[head],
                    rate_snapshot=selected,
                    increment_heads=heads,
                    category=p.get("category", ""),
                )
                id = db.execute(
                    "INSERT INTO suite_claims(payload,calculation) VALUES(?,?)",
                    (json.dumps(payload), json.dumps(calculation)),
                ).lastrowid
                ids.append(id)
            return (
                jsonify(
                    components=components,
                    total=f"{total:.2f}",
                    claim_ids=ids,
                    selected_due=f"{due_total:.2f}",
                    selected_drawn=f"{selected_drawn:.2f}",
                    full_due_gross=f"{due_total+sum(others.values(),Decimal(0)):.2f}",
                    full_drawn_gross=f"{full_drawn:.2f}",
                    rates=selected,
                    warnings=warnings,
                    status="draft",
                    notice="Reviewed-input calculation, not automatic OCR approval. HDA uses the explicitly confirmed fraction, not a newly certified government rule.",
                ),
                201,
            )
