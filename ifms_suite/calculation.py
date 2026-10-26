"""Decimal allowance arithmetic. Rules and inputs are explicit, never inferred."""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")


def money(value):
    try:
        if value is None or isinstance(value, bool):
            raise ValueError("Missing or invalid monetary value")
        result = Decimal(str(value).replace(",", ""))
        if not result.is_finite():
            raise ValueError("Money and rates must be finite")
        return result
    except (InvalidOperation, TypeError):
        raise ValueError("Missing or invalid monetary value") from None


def rounded(value, policy="paise"):
    if policy not in ("paise", "rupee"):
        raise ValueError("Unknown rounding policy")
    return value.quantize(
        Decimal("1") if policy == "rupee" else CENT, rounding=ROUND_HALF_UP
    )


def required(s, key):
    if key not in s or s[key] in ("", None):
        raise ValueError("Missing " + key)
    return money(s[key])


def base_amount(s, side):
    basis = s.get("basis", "basic")
    if basis in ("fixed", "daily"):
        return required(s, side + "_amount")
    if basis == "components":
        components = s.get(side + "_components")
        if not isinstance(components, dict) or not components:
            raise ValueError("Select " + side + " pay components")
        return sum((money(v) for v in components.values()), Decimal(0))
    basic = (
        required(s, "basic")
        if side == "due"
        else money(s.get("drawn_basic", s.get("basic")))
    )
    if basis == "basic":
        return basic
    if basis == "basic_da":
        return basic * (1 + required(s, side + "_da_rate") / 100)
    raise ValueError("Unknown allowance basis")


def calculate_claim(start, end, segments, deductions=None):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end:
        raise ValueError("Start date must precede end date")
    if (end - start).days > 36600:
        raise ValueError("Claim period exceeds 100 years")
    if not isinstance(segments, list):
        raise ValueError("Segments must be a list")
    prepared = []
    for index, s in enumerate(segments):
        try:
            a, b = date.fromisoformat(s["start"]), date.fromisoformat(s["end"])
        except (KeyError, TypeError):
            raise ValueError("Segment start/end required") from None
        if a > b:
            raise ValueError("Invalid segment dates")
        basis = s.get("basis", "basic")
        if basis not in ("basic", "basic_da", "fixed", "daily", "components"):
            raise ValueError("Unknown allowance basis")
        if s.get("proration", "calendar") not in ("calendar", "thirty"):
            raise ValueError("Unknown proration policy")
        if s.get("drawn_basis", "monthly") not in (
            "monthly",
            "monthly_amount",
            "period",
        ):
            raise ValueError("Unknown drawn basis")
        if (s.get("drawn_basis") == "period" or s.get("due_basis") == "period") and (
            max(a, start).year,
            max(a, start).month,
        ) != (min(b, end).year, min(b, end).month):
            raise ValueError(
                "An actual drawn amount must cover one monthly segment; split multi-month records"
            )
        # Validate all fields before generating any result.
        base_amount(s, "due")
        if "drawn_amount" not in s:
            base_amount(s, "drawn")
        if basis not in ("fixed", "daily"):
            required(s, "due_rate")
            if "drawn_amount" not in s:
                required(s, "drawn_rate")
        if s.get("rounding_scope", "segment") not in ("segment", "month"):
            raise ValueError("Unknown rounding scope")
        prepared.append((a, b, s, index))
    rows = []
    cursor = start
    total = Decimal(0)
    while cursor <= end:
        matches = [(a, b, s, i) for a, b, s, i in prepared if a <= cursor <= b]
        if len(matches) != 1:
            raise ValueError("Missing or overlapping segment at " + str(cursor))
        a, b, s, index = matches[0]
        month_end = date(
            cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]
        )
        last = min(end, b, month_end)
        if any(cursor < x <= last for x, y, t, i in prepared if i != index):
            raise ValueError("Overlapping segments")
        days = (last - cursor).days + 1
        denominator = 30 if s.get("proration") == "thirty" else month_end.day
        factor = (
            Decimal(1)
            if cursor.day == 1 and last == month_end
            else Decimal(days) / denominator
        )
        basis = s.get("basis", "basic")
        rounding = s.get("rounding", "paise")

        def entitlement(side):
            if side == "due" and s.get("due_basis") == "period":
                return required(s, "due_amount")
            if side == "drawn" and "drawn_amount" in s:
                value = required(s, "drawn_amount")
                return (
                    value
                    if s.get("drawn_basis") == "period"
                    else value
                    * (
                        factor
                        if s.get("drawn_basis") == "monthly_amount"
                        else (days if basis == "daily" else factor)
                    )
                )
            value = base_amount(s, side)
            if basis == "daily":
                return value * days
            if basis != "fixed":
                value = value * required(s, side + "_rate") / 100
            return value * factor

        raw_due, raw_drawn = entitlement("due"), entitlement("drawn")
        actual_due = s.get("due_basis") == "period"
        actual_drawn = "drawn_amount" in s and s.get("drawn_basis") in (
            "period",
            "monthly_amount",
        )
        for side, actual in [("due", actual_due), ("drawn", actual_drawn)]:
            if actual and required(s, side + "_amount") != rounded(
                required(s, side + "_amount")
            ):
                raise ValueError("Actual amounts may have at most two decimal places")
        due, drawn = rounded(raw_due, "paise" if actual_due else rounding), rounded(
            raw_drawn, "paise" if actual_drawn else rounding
        )
        prior = (
            rounded(money(s.get("prior_settlement", "0")))
            if cursor == max(start, a)
            else Decimal(0)
        )
        difference = rounded(due - drawn - prior)
        total += difference
        rows.append(
            dict(
                start=str(cursor),
                end=str(last),
                days=days,
                denominator=denominator,
                basis=basis,
                basic=str(s.get("basic") or "0"),
                drawn_basic=str(s.get("drawn_basic") or s.get("basic") or "0"),
                due_rate=str(s.get("due_rate", "0")),
                drawn_rate=str(s.get("drawn_rate", "0")),
                due=f"{due:.2f}",
                drawn=f"{drawn:.2f}",
                prior_settlement=f"{prior:.2f}",
                difference=f"{difference:.2f}",
                source=s.get("source", "Manual inputs"),
                rule_reference=s.get("rule_reference", "Manual rate"),
                rounding=rounding,
                rounding_scope=s.get("rounding_scope", "segment"),
                _raw_due=raw_due,
                _raw_drawn=raw_drawn,
                _actual_due=actual_due,
                _actual_drawn=actual_drawn,
                proration=s.get("proration", "calendar"),
            )
        )
        cursor = last + timedelta(days=1)
    monthly = {}
    for row in rows:
        if row["rounding_scope"] == "month":
            monthly.setdefault((row["start"][:7], row["rounding"]), []).append(row)
    for (month, policy), parts in monthly.items():
        for key in ("due", "drawn"):
            actual = [row for row in parts if row["_actual_" + key]]
            computed = [row for row in parts if not row["_actual_" + key]]
            target = rounded(
                sum((row["_raw_" + key] for row in computed), Decimal(0)), policy
            ) + rounded(sum((row["_raw_" + key] for row in actual), Decimal(0)))
            adjustment = target - sum((money(row[key]) for row in parts), Decimal(0))
            last = (computed or actual)[-1]
            last[key] = f"{money(last[key])+adjustment:.2f}"
            last["rounding_adjustment_" + key] = f"{adjustment:.2f}"
    total = Decimal(0)
    for row in rows:
        row.pop("_raw_due")
        row.pop("_raw_drawn")
        row.pop("_actual_due")
        row.pop("_actual_drawn")
        row["difference"] = (
            f"{rounded(money(row['due'])-money(row['drawn'])-money(row['prior_settlement'])):.2f}"
        )
        total += money(row["difference"])
    allocations = []
    deducted = Decimal(0)
    for d in deductions or []:
        if not str(d.get("name", "")).strip():
            raise ValueError("Deduction name required")
        v = required(d, "value")
        if v < 0:
            raise ValueError("Deduction must be nonnegative")
        if d.get("mode") == "percent":
            amount = rounded(max(total, Decimal(0)) * v / 100)
        elif d.get("mode") == "fixed":
            amount = rounded(v)
        else:
            raise ValueError("Unknown deduction mode")
        allocations.append(
            dict(name=d["name"], mode=d["mode"], value=str(v), amount=f"{amount:.2f}")
        )
        deducted += amount
    if deducted > max(total, Decimal(0)):
        raise ValueError("Deductions exceed positive gross arrear")
    return dict(
        rows=rows,
        total=f"{total:.2f}",
        deductions=allocations,
        total_deductions=f"{deducted:.2f}",
        net_payable=f"{total-deducted:.2f}",
        rounding="HALF_UP; due and drawn separately; explicit segment/month scope. Monthly adjustments are carried by the final slice.",
        proration="Explicit per-segment calendar or thirty-day policy",
    )
