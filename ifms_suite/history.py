"""Build monthly calculation segments from reviewed history; missing data blocks output."""

from datetime import date, timedelta
from calendar import monthrange
from decimal import Decimal
from .calculation import money, rounded
from .payment_types import payment_class, entitlement_type


def active(items, day, label):
    options = [
        r
        for r in items
        if date.fromisoformat(r["effective_from"]) <= day
        and (not r.get("effective_to") or day <= date.fromisoformat(r["effective_to"]))
    ]
    if not options:
        raise ValueError("Missing " + label + " at " + str(day))
    latest = max(date.fromisoformat(r["effective_from"]) for r in options)
    matches = [r for r in options if date.fromisoformat(r["effective_from"]) == latest]
    if len(matches) != 1:
        raise ValueError("Ambiguous " + label + " at " + str(day))
    return matches[0]


def prepare_segments(start, end, allowance, rates, pay_history, payments, rule):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end:
        raise ValueError("Invalid dates")
    allowance = allowance.strip().upper()
    category = rule.get("category", "")
    rates = [
        r
        for r in rates
        if r["allowance"].strip().upper() == allowance
        and r.get("category", "") == category
    ]
    if not pay_history:
        raise ValueError("Missing approved pay history")
    cuts = {start, end + timedelta(days=1)}
    for h in (
        rates
        + pay_history
        + (rule.get("da_rates", []) if rule.get("basis") == "basic_da" else [])
    ):
        for key in ("effective_from", "effective_to", "cash_from"):
            if h.get(key):
                d = date.fromisoformat(h[key]) + (
                    timedelta(days=1) if key == "effective_to" else timedelta(0)
                )
                if start < d <= end:
                    cuts.add(d)
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
        if start < cursor <= end:
            cuts.add(cursor)
    previous = []
    for p in payments:
        kind = payment_class(p)
        if kind in ("regular_salary", "leave_encashment", "bonus") or entitlement_type(
            p
        ) != rule.get("entitlement_type", "salary"):
            continue
        heads = {str(k).upper(): v for k, v in p.get("allowances", {}).items()}
        if allowance in heads and money(heads[allowance]) != 0:
            if kind != "allowance_arrear":
                raise ValueError(
                    "Classify payment "
                    + str(p.get("bill_no", ""))
                    + " before using it as an arrear settlement"
                )
            period = p.get("entitlement_period")
            if not period:
                raise ValueError(
                    "Allocate previous arrear bill "
                    + str(p.get("bill_no", ""))
                    + " to its entitlement period"
                )
            a, b = date.fromisoformat(period["start"]), date.fromisoformat(
                period["end"]
            )
            if a > b:
                raise ValueError("Invalid settlement period")
            if a <= end and b >= start:
                previous.append(
                    (a, b, money(heads[allowance]), p.get("bill_no", ""), p.get("id"))
                )
    points = sorted(cuts)
    rows = []
    for a, stop in zip(points, points[1:]):
        b = stop - timedelta(days=1)
        rate = active(rates, a, "allowance rate")
        pay = active(pay_history, a, "pay history")
        month = a.strftime("%Y-%m")
        drawn = [
            p
            for p in payments
            if p.get("pay_month") == month and payment_class(p) == "regular_salary"
        ]
        if len(drawn) != 1:
            raise ValueError("Missing or ambiguous reviewed drawn payment for " + month)
        p = drawn[0]
        heads = {str(k).upper(): v for k, v in p.get("allowances", {}).items()}
        if allowance not in heads:
            raise ValueError(
                "Missing drawn "
                + allowance
                + " for "
                + month
                + "; confirm zero explicitly if not paid"
            )
        row = dict(
            start=str(a),
            end=str(b),
            basic=str(pay["basic"]),
            basis=rule.get("basis", "basic"),
            due_rate=str(rate["rate"]),
            due_amount=str(rate["rate"]),
            drawn_amount=str(heads[allowance]),
            drawn_basis="monthly_amount",
            source="Bill "
            + str(p.get("bill_no", ""))
            + " / payment "
            + str(p.get("id", "")),
            rule_reference=rate.get("reference", "") + " " + rate.get("order_date", ""),
            cash_from=rate.get("cash_from"),
            rate_verification=rate.get("verification", "manual"),
            proration=rule.get("proration", "calendar"),
            rounding=rule.get("rounding", "paise"),
            rounding_scope=rule.get("rounding_scope", "segment"),
            prior_settlement="0.00",
        )
        if row["basis"] == "basic_da":
            da = active(
                [
                    r
                    for r in rule.get("da_rates", [])
                    if r["allowance"].strip().upper() == "DA"
                ],
                a,
                "DA rate",
            )
            row["due_da_rate"] = str(da["rate"])
            # Actual drawn allowance is used, not a reconstructed drawn DA formula.
        if row["basis"] == "components":
            row["due_components"] = {
                k: str(pay.get("components", {})[k])
                for k in rule.get("components", [])
                if k in pay.get("components", {})
            }
            if len(row["due_components"]) != len(rule.get("components", [])):
                raise ValueError("Missing selected pay components")
        if pay.get("eligible") is False:
            row.update(basis="fixed", due_amount="0")
        row["settlement_ids"] = []
        rows.append(row)
    for a, b, amount, bill, payment_id in previous:
        eligible = [
            r
            for r in rows
            if date.fromisoformat(r["start"]) <= b and date.fromisoformat(r["end"]) >= a
        ]
        total_days = (b - a).days + 1
        selected_days = sum(
            (
                min(b, date.fromisoformat(r["end"]))
                - max(a, date.fromisoformat(r["start"]))
            ).days
            + 1
            for r in eligible
        )
        target = rounded(amount * selected_days / total_days)
        allocated = Decimal(0)
        for index, r in enumerate(eligible):
            days = (
                min(b, date.fromisoformat(r["end"]))
                - max(a, date.fromisoformat(r["start"]))
            ).days + 1
            part = (
                target - allocated
                if index == len(eligible) - 1
                else rounded(amount * days / total_days)
            )
            allocated += part
            if payment_id is not None:
                r["settlement_ids"].append(payment_id)
            r["prior_settlement"] = f"{money(r['prior_settlement'])+part:.2f}"
            r["source"] += "; prior bill " + str(bill)
    return rows
