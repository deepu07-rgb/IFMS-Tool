"""Pure source-backed consolidated monthwise bill preparation.

``prepare_bill(facts, request, rates)`` never reads a database or infers entitlement
from a supplied due/drawn statement. ``facts['bills']`` uses document_facts' bill
shape: employee_code, pay_month (YYYY-MM), bill_type/payment_class, allowances,
printed_gross, deductions, printed_deductions, printed_net, complete, evidence.
A partial month's actual payment must have explicit ``covered_dates`` (start/end).
Regular bills for a month must be unique; overlapping/aggregated records need review.
Prior arrears need entitlement_period and, for multi-month/head periods,
``allocations_by_head`` mapping heads to [{start,end,amount}]. No automatic credit
proration is permitted. Unchanged signed source heads are carried on both sides.

Request: kind increment/hra/da, employee_code, start/end, effective_from,
old_basic/new_basic, pay_order_reference, hra_eligible (boolean),
hra_eligibility_reference, proration (calendar/thirty), rounding (rupee/paise),
rounding_scope (month/segment), reviewed=True or complete=True with evidence.
Optional category, hda_rule {numerator, denominator, reference, effective_from,
effective_to}, extra_deductions [{name,mode,value,reference}]. Explicitly reviewed
requests are labelled human_assisted. Rates are dated library dictionaries with
allowance, rate, effective_from, optional effective_to/category and reference.

Ready means the deterministic inputs reconcile; it is not payment approval.
Blocked results preserve verified monthly rows but never expose a final payable.
All monetary output is serialized decimal text. Input dictionaries are untouched.
"""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from .calculation import calculate_claim, money, rounded
from .history import active
from .payment_types import payment_class, entitlement_type

ZERO = Decimal(0)


def _head(value):
    return " ".join(str(value).upper().split())


def _amounts(mapping):
    result = {}
    for key, value in mapping.items():
        head = _head(key)
        if not head or head in result:
            raise ValueError("Missing or duplicate component head")
        amount = money(value)
        if amount != rounded(amount):
            raise ValueError("Actual amounts may have at most two decimal places")
        result[head] = amount
    return result


def _span(value):
    a, b = date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
    if a > b:
        raise ValueError("Invalid covered dates")
    return a, b


def _months(a, b):
    while a <= b:
        last = min(b, date(a.year, a.month, monthrange(a.year, a.month)[1]))
        yield a, last
        a = last + timedelta(days=1)


def _trusted(row, label):
    if row.get("complete") is not True or not row.get("evidence"):
        raise ValueError(label + " requires complete source evidence")
    if row.get("issues"):
        raise ValueError(label + " has unresolved source issues")


def _reconcile(bill):
    _trusted(bill, "Actual drawn bill")
    heads = _amounts(bill["allowances"])
    if not heads:
        raise ValueError("Missing drawn component heads")
    gross = money(bill["printed_gross"])
    if sum(heads.values(), ZERO) != gross:
        raise ValueError("Drawn components do not reconcile with printed gross")
    deductions = _amounts(bill.get("deductions", {}))
    effects = {_head(k): v for k, v in bill.get("deduction_effects", {}).items()}
    if any(type(v) is not bool for v in effects.values()) or set(effects) - set(
        deductions
    ):
        raise ValueError("Verify source deduction effects on net pay")
    deducted = money(bill["printed_deductions"])
    if any(v < 0 for v in deductions.values()) or deducted < 0:
        raise ValueError("Source deductions must be nonnegative")
    if (
        sum((v for k, v in deductions.items() if effects.get(k, True)), ZERO)
        != deducted
    ):
        raise ValueError(
            "Source deduction heads do not reconcile with printed deductions"
        )
    if gross - deducted != money(bill["printed_net"]):
        raise ValueError("Drawn gross, deductions and net do not reconcile")
    return heads


def _rule_rates(rates, head, request):
    return [
        r
        for r in rates
        if _head(r.get("allowance", "")) == head
        and r.get("category", "")
        == (request.get("category", "") if head == "HRA" else "")
    ]


def _rate(rates, day, head):
    row = active(rates, day, head + " rate")
    if not str(row.get("reference", "")).strip():
        raise ValueError(head + " rate requires source reference")
    value = money(row["rate"])
    if value < 0:
        raise ValueError(head + " rate must be nonnegative")
    return value, row


def _cuts(a, b, request, rates):
    cuts = {a, b + timedelta(days=1)}
    for record in rates + [request.get("hda_rule") or {}, request]:
        for key in ("effective_from", "effective_to"):
            if record.get(key):
                day = date.fromisoformat(record[key])
                if key == "effective_to":
                    day += timedelta(days=1)
                if a < day <= b:
                    cuts.add(day)
    ordered = sorted(cuts)
    return list(zip(ordered, [d - timedelta(days=1) for d in ordered[1:]]))


def _changed_heads(request):
    kind = request["kind"]
    heads = {"BASIC", "DA", "HRA"} if kind == "increment" else {kind.upper()}
    if kind in ("increment", "da") and request.get("hda_rule"):
        heads.add("HDA")
    return heads


def _month_row(a, b, bill, request, rates, credits):
    drawn = _reconcile(bill)
    full_a = date(a.year, a.month, 1)
    full_b = date(a.year, a.month, monthrange(a.year, a.month)[1])
    coverage = bill.get("covered_dates")
    kind = request["kind"]
    requested_heads = _changed_heads(request)
    if kind == "hra" and "HRA" not in drawn and bill.get("allowances_complete") is True:
        drawn["HRA"] = ZERO  # Complete reconciled source head coverage proves absence.
    if coverage:
        if _span(coverage) != (a, b):
            raise ValueError(
                "Actual drawn covered dates do not match selected monthly period"
            )
    elif (a, b) != (full_a, full_b) and any(
        drawn.get(h, ZERO) != 0 for h in requested_heads
    ):
        raise ValueError("Partial month needs explicit actual drawn covered dates")
    changed = _changed_heads(request)
    if kind in ("increment", "da") and "HDA" in drawn and not request.get("hda_rule"):
        raise ValueError("Drawn HDA needs an explicit sanctioned HDA fraction rule")
    if any(h not in drawn for h in changed):
        raise ValueError(
            "Missing actual drawn head: " + ", ".join(sorted(changed - drawn.keys()))
        )
    if request.get("effective_to") and b > date.fromisoformat(request["effective_to"]):
        raise ValueError("Selected period exceeds sanction expiry")
    effective = date.fromisoformat(request["effective_from"])
    if kind != "increment" and a < effective:
        raise ValueError(
            "Selected period precedes sanction; prior entitlement requires review"
        )
    da_rates = _rule_rates(rates, "DA", request)
    hra_rates = _rule_rates(rates, "HRA", request)
    relevant_rates = (da_rates if changed & {"DA", "HDA"} else []) + (
        hra_rates if "HRA" in changed and request["hra_eligible"] else []
    )
    pieces = {h: [] for h in changed}
    evidence = list(bill["evidence"])
    for first, last in _cuts(a, b, request, relevant_rates):
        if kind != "increment" and not coverage:
            if "BASIC" not in drawn:
                raise ValueError("Missing source Basic for allowance entitlement")
            basic = drawn["BASIC"]
        elif first >= effective:
            basic = money(request["new_basic"])
        else:
            basic = money(request.get("old_basic", drawn.get("BASIC")))
            if not request.get("old_basic") and (a, b) != (full_a, full_b):
                raise ValueError(
                    "Partial pre-increment period needs sanctioned old monthly basic"
                )
        due = {"BASIC": basic}
        references = {"BASIC": request["pay_order_reference"]}
        if changed & {"DA", "HDA"}:
            da, source = _rate(da_rates, first, "DA")
            if (
                kind == "da"
                and request.get("rate") is not None
                and da != money(request["rate"])
            ):
                raise ValueError("Sanctioned DA rate does not match dated rate library")
            due["DA"] = basic * da / 100
            references["DA"] = source["reference"]
            evidence.append(dict(kind="rate", head="DA", **source))
        if "HRA" in changed:
            if request["hra_eligible"]:
                hra, source = _rate(hra_rates, first, "HRA")
                if (
                    kind == "hra"
                    and request.get("rate") is not None
                    and hra != money(request["rate"])
                ):
                    raise ValueError(
                        "Sanctioned HRA rate does not match dated rate library"
                    )
                due["HRA"] = basic * hra / 100
                references["HRA"] = source["reference"]
                evidence.append(dict(kind="rate", head="HRA", **source))
            else:
                due["HRA"] = ZERO
                references["HRA"] = request["hra_eligibility_reference"]
        if "HDA" in changed:
            rule = request["hda_rule"]
            if (
                rule.get("effective_from")
                and first < date.fromisoformat(rule["effective_from"])
            ) or (
                rule.get("effective_to")
                and last > date.fromisoformat(rule["effective_to"])
            ):
                raise ValueError("Missing HDA rule coverage")
            due["HDA"] = (
                (basic + due["DA"])
                * money(rule["numerator"])
                / money(rule["denominator"])
            )
            references["HDA"] = rule["reference"]
        for head in changed:
            pieces[head].append(
                dict(
                    start=str(first),
                    end=str(last),
                    basis="fixed",
                    due_amount=str(due[head]),
                    drawn_amount=str(drawn[head]) if first == a else "0",
                    drawn_basis="period",
                    proration=request["proration"],
                    rounding=request["rounding"],
                    rounding_scope=request["rounding_scope"],
                    source="Source bill " + str(bill.get("bill_no", "")),
                    rule_reference=references[head],
                )
            )
    components = []
    for head in sorted(
        drawn, key=lambda h: (h not in ("BASIC", "DA", "HRA", "HDA"), h)
    ):
        if head in changed:
            calc = calculate_claim(str(a), str(b), pieces[head])
            due = sum((money(r["due"]) for r in calc["rows"]), ZERO)
            segments = calc["rows"]
        else:
            due, segments = drawn[head], []
        prior = credits.get((str(a), str(b), head), ZERO)
        if prior and head not in changed:
            raise ValueError(
                "Prior credit on an unchanged head requires entitlement review: " + head
            )
        components.append(
            dict(
                head=head,
                due=f"{due:.2f}",
                drawn=f"{drawn[head]:.2f}",
                prior_settlement=f"{prior:.2f}",
                difference=f"{due-drawn[head]-prior:.2f}",
                segments=segments,
                evidence=list(bill["evidence"]),
            )
        )
    sums = {
        key: sum((money(c[key]) for c in components), ZERO)
        for key in ("due", "drawn", "prior_settlement", "difference")
    }
    return dict(
        month=str(a)[:7],
        start=str(a),
        end=str(b),
        components=components,
        **{k: f"{v:.2f}" for k, v in sums.items()},
        full_due_gross=f"{sums['due']:.2f}",
        full_drawn_gross=f"{sums['drawn']:.2f}",
        source_deductions=dict(bill.get("deductions", {})),
        source_net=str(bill["printed_net"]),
        evidence=evidence,
    )


def _credits(bills, start, end, periods, changed):
    credits = {}
    seen = set()
    for bill in bills:
        if (
            payment_class(bill) != "allowance_arrear"
            or entitlement_type(bill) != "salary"
        ):
            continue
        key = (bill.get("bill_no"), bill.get("pay_month"))
        if key[0]:
            if key in seen:
                raise ValueError("Duplicate prior credit source bill")
            seen.add(key)
        heads = _amounts(bill.get("allowances", {}))
        if not any(v for h, v in heads.items() if h in changed) and any(heads.values()):
            if (
                bill.get("complete") is True
                and bill.get("allowances_complete") is True
                and sum(heads.values(), ZERO) == money(bill.get("printed_gross"))
            ):
                continue
        if not any(heads.values()):
            if not (
                bill.get("complete") is True
                and bill.get("allowances_complete") is True
                and heads
                and money(bill.get("printed_gross")) == 0
            ):
                raise ValueError("Prior arrear credit amounts are unresolved")
            continue
        period = bill.get("entitlement_period")
        if not period:
            raise ValueError("Prior credit needs covered entitlement dates")
        a, b = _span(period)
        if b < start or end < a:
            continue
        _trusted(bill, "Prior credit")
        allocations = {
            _head(k): v for k, v in bill.get("allocations_by_head", {}).items()
        }
        for head, amount in heads.items():
            if not amount:
                continue
            if amount < 0:
                raise ValueError(
                    "Negative prior credit requires explicit settlement review"
                )
            parts = allocations.get(head)
            if not parts:
                parts = [dict(start=str(a), end=str(b), amount=str(amount))]
            allocated = ZERO
            used = []
            for part in parts:
                x, y = _span(part)
                value = money(part["amount"])
                if value < 0 or value != rounded(value) or x < a or y > b:
                    raise ValueError("Invalid prior credit allocation")
                if any(x <= old_y and old_x <= y for old_x, old_y in used):
                    raise ValueError("Overlapping prior credit allocations")
                used.append((x, y))
                allocated += value
                if y < start or end < x:
                    continue
                if (x, y) not in periods:
                    raise ValueError(
                        "Prior credit requires exact monthly covered dates and head allocations"
                    )
                key = (str(x), str(y), head)
                credits[key] = credits.get(key, ZERO) + value
            if allocated != amount:
                raise ValueError(
                    "Prior credit allocations do not reconcile with paid head"
                )
    return credits


def prepare_bill(facts, request, rates):
    """Return deterministic verified monthly rows and dependency blockers."""
    result = dict(
        status="blocked",
        mode="human_assisted" if request.get("reviewed") is True else "source_backed",
        rows=[],
        totals={},
        blockers=[],
        evidence=list(request.get("evidence", [])),
        employee_code=request.get("employee_code"),
        start=request.get("start"),
        end=request.get("end"),
        kind=request.get("kind"),
    )

    def block(code, error, **context):
        result["blockers"].append(dict(code=code, message=str(error), **context))

    try:
        start, end = _span(request)
        if (end - start).days > 36600:
            raise ValueError("Claim period exceeds 100 years")
        if request.get("kind") not in ("increment", "hra", "da"):
            raise ValueError("Unsupported entitlement kind")
        code = _head(request.get("employee_code", ""))
        if not code:
            raise ValueError("Employee identity required")
        if request.get("reviewed") is not True:
            _trusted(request, "Sanctioned request")
        if not str(request.get("pay_order_reference", "")).strip():
            raise ValueError("Sanctioned pay order reference required")
        date.fromisoformat(request["effective_from"])
        for key in ("old_basic", "new_basic"):
            if key == "old_basic" and key not in request:
                continue
            if money(request[key]) < 0:
                raise ValueError("Basic pay must be nonnegative")
        if request["kind"] in ("increment", "hra") and (
            not isinstance(request.get("hra_eligible"), bool)
            or not str(request.get("hra_eligibility_reference", "")).strip()
        ):
            raise ValueError("Explicit HRA eligibility and source reference required")
        if request.get("proration") not in ("calendar", "thirty"):
            raise ValueError("Explicit proration rule required")
        if request.get("rounding") not in ("paise", "rupee") or request.get(
            "rounding_scope"
        ) not in ("month", "segment"):
            raise ValueError("Explicit rounding policy and scope required")
        if request.get("hda_rule"):
            rule = request["hda_rule"]
            if (
                not str(rule.get("reference", "")).strip()
                or money(rule["numerator"]) <= 0
                or money(rule["denominator"]) <= 0
            ):
                raise ValueError(
                    "HDA needs positive explicit fraction and governing reference"
                )
        periods = list(_months(start, end))
        bills = []
        for bill in facts.get("bills", []):
            employee = _head(bill.get("employee_code", ""))
            if not employee:
                block("identity", "Source bill has unresolved employee identity")
            elif employee == code:
                bills.append(bill)
        for issue in facts.get("issues", []):
            if isinstance(issue, dict):
                # Scope only when the evidence identifies the dependency explicitly.
                if issue.get("employee_code") and _head(issue["employee_code"]) != code:
                    continue
                if (
                    issue.get("pay_month")
                    and not str(start)[:7] <= issue["pay_month"] <= str(end)[:7]
                ):
                    continue
            block(
                "source_issue",
                issue.get("issue", issue) if isinstance(issue, dict) else issue,
            )
        for bill in bills:
            if payment_class(bill) == "regular_salary" and not bill.get("pay_month"):
                block("payment_period", "Regular source bill has unresolved pay month")
        changed = _changed_heads(request)
        try:
            credits = _credits(bills, start, end, periods, changed)
        except (ValueError, KeyError, TypeError) as error:
            block("credit_review", error)
            result["prior_credit_review_required"] = True
            credits = {}
        # A credit on a missing/non-selected head must never silently disappear.
        consumed_credits = set()
        for a, b in periods:
            month = str(a)[:7]
            selected = [
                p
                for p in bills
                if payment_class(p) == "regular_salary" and p.get("pay_month") == month
            ]
            try:
                if len(selected) != 1:
                    raise ValueError(
                        "Missing or ambiguous actual drawn regular salary for " + month
                    )
                row = _month_row(a, b, selected[0], request, rates, credits)
                result["rows"].append(row)
                result["evidence"].extend(row["evidence"])
                consumed_credits.update(
                    (str(a), str(b), c["head"]) for c in row["components"]
                )
            except (ValueError, KeyError, TypeError) as error:
                block("month_inputs", error, month=month)
        if any(key not in consumed_credits for key in credits):
            block(
                "credit_allocation",
                "Prior credit does not match a verified monthly component",
            )
        for bill in bills:
            if payment_class(bill) == "other" and entitlement_type(bill) == "salary":
                block(
                    "payment_class",
                    "Classify potentially relevant payment "
                    + str(bill.get("bill_no", "")),
                )
    except (ValueError, KeyError, TypeError) as error:
        block("required_inputs", error)
    sums = {
        key: sum((money(row[key]) for row in result["rows"]), ZERO)
        for key in ("due", "drawn", "prior_settlement", "difference")
    }
    result["totals"] = {k: f"{v:.2f}" for k, v in sums.items()}
    deductions = []
    deducted = ZERO
    try:
        for deduction in request.get("extra_deductions", []):
            if not str(deduction.get("reference", "")).strip():
                raise ValueError("Extra deduction needs explicit source reference")
        if request.get("extra_deductions"):
            # Reuse the shared deduction validation and rounding without recalculating heads.
            calc = calculate_claim(
                "2000-01-01",
                "2000-01-31",
                [
                    dict(
                        start="2000-01-01",
                        end="2000-01-31",
                        basis="fixed",
                        due_amount=str(sums["difference"]),
                        drawn_amount="0",
                        drawn_basis="period",
                    )
                ],
                request["extra_deductions"],
            )
            deductions, deducted = calc["deductions"], money(calc["total_deductions"])
    except (ValueError, KeyError, TypeError) as error:
        block("deductions", error)
    result["totals"].update(total_deductions=f"{deducted:.2f}", net_payable=None)
    result["deductions"] = deductions
    result["evidence"].extend(
        dict(kind="prior_credit", **bill)
        for bill in locals().get("bills", [])
        if payment_class(bill) == "allowance_arrear"
    )
    if not result["blockers"]:
        result["status"] = "ready"
        result["totals"]["net_payable"] = f"{sums['difference']-deducted:.2f}"
    return result
