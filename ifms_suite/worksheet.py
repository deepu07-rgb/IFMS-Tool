"""Human-assisted monthly salary arithmetic; OCR is never an input authority."""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from .calculation import money, rounded
from .supplied_form import HEADS, TEMPLATES

VERSION = "ifms-assisted-worksheet-v1"
KINDS = ("hra", "da", "increment", "manual")
DEDUCTION_KEYS = tuple(
    dict.fromkeys(k for t in TEMPLATES.values() for k in t["deduction_keys"])
)
REFERENCES = (
    "salary_reference",
    "order_reference",
    "history_reference",
    "deduction_reference",
)
# Flat literal columns make Excel copy/paste and the app use the same schema.
COLUMNS = (
    ("month", "Month (YYYY-MM)", "dates"),
    ("start", "Effective from", "dates"),
    ("end", "Through (inclusive)", "dates"),
    ("presentation", "Presentation: period / whole_month", "dates"),
    *(("drawn_" + h, "Drawn " + h, "drawn") for h in HEADS),
    ("new_basic", "Revised monthly basic", "entitlement"),
    ("da_rate", "DA %", "entitlement"),
    ("hra_rate", "HRA %", "entitlement"),
    ("hda_divisor", "HDA divisor: (Basic + DA) / divisor", "entitlement"),
    *(("due_" + h, "Manual monthly due " + h, "manual") for h in HEADS),
    *(("prior_" + h, "Earlier paid " + h, "prior") for h in HEADS),
    *(("ded_" + k, "Extra / disclosure " + k, "deductions") for k in DEDUCTION_KEYS),
    ("salary_reference", "Salary source reference", "references"),
    ("order_reference", "Entitlement / rate / HDA authority", "references"),
    ("history_reference", "Earlier payment check / allocation reference", "references"),
    ("deduction_reference", "Additional deduction authority / none", "references"),
    ("history_reviewed", "Earlier payments checked: Yes / No", "references"),
    ("deductions_reviewed", "Extra deductions checked: Yes / No", "references"),
    ("bill_no", "Bill number", "details"),
    ("bill_date", "Bill date", "details"),
    ("tv_no", "TV number", "details"),
    ("tv_date", "TV date", "details"),
    ("ledger_payment_id", "Saved ledger ID (do not edit)", "link"),
    ("ledger_snapshot", "Saved ledger fingerprint (do not edit)", "link"),
)
AMOUNT_FIELDS = {
    k for k, _, g in COLUMNS if g in ("drawn", "manual", "prior", "deductions")
}


def required_numeric_fields(payload):
    fields = ["drawn_" + h for h in HEADS] + ["prior_" + h for h in HEADS]
    fields += [
        "ded_" + k
        for k in TEMPLATES.get(
            payload.get("template_id"), TEMPLATES["jodhpur_classic"]
        )["deduction_keys"]
    ]
    kind = payload.get("kind")
    if kind == "manual":
        fields += ["due_" + h for h in HEADS]
    if kind == "increment":
        fields += ["new_basic", "da_rate", "hra_rate"]
    elif kind == "da":
        fields += ["da_rate"]
    elif kind == "hra":
        fields += ["hra_rate"]
    if kind in ("increment", "da") and payload.get("include_hda") is True:
        fields += ["hda_divisor"]
    return fields


def _date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Use YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if str(parsed) != value:
        raise ValueError("Use YYYY-MM-DD")
    return parsed


def monthly_due(payload, row, values):
    kind = payload["kind"]
    due = {h: values["drawn_" + h] for h in HEADS}
    if kind == "manual":
        return {h: values["due_" + h] for h in HEADS}
    if kind == "increment":
        due["BASIC"] = values["new_basic"]
    if kind in ("increment", "da"):
        due["DA"] = due["BASIC"] * values["da_rate"] / 100
    if kind in ("increment", "hra"):
        due["HRA"] = due["BASIC"] * values["hra_rate"] / 100
    if kind in ("increment", "da") and payload.get("include_hda") is True:
        due["HDA"] = (due["BASIC"] + due["DA"]) / values["hda_divisor"]
    return due


def calculate_worksheet(payload):
    """Return field errors rather than guessing missing facts; never mutate input."""
    if not isinstance(payload, dict):
        raise ValueError("Expected a worksheet object")
    errors, rows, audits = [], [], []

    def error(index, field, message):
        errors.append(dict(row=index, field=field, message=message))

    for key in ("employee_code", "employee_name"):
        if (
            not isinstance(payload.get(key), str)
            or not payload[key].strip()
            or len(payload[key]) > 200
        ):
            error(
                None, key, "Enter " + key.replace("_", " ") + " (up to 200 characters)"
            )
    if payload.get("kind") not in KINDS:
        error(
            None, "kind", "Choose HRA, DA, basic revision or explicit monthly amounts"
        )
    if payload.get("template_id") not in TEMPLATES:
        error(None, "template_id", "Choose one of the supplied forms")
    if payload.get("rounding") not in ("rupee", "paise"):
        error(None, "rounding", "Choose rupee or paise rounding")
    if not isinstance(payload.get("include_hda", False), bool):
        error(None, "include_hda", "Choose whether the sanctioned HDA rule applies")
    inputs = payload.get("rows")
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 120:
        error(None, "rows", "Enter 1–120 monthly rows")
        inputs = []
    header_errors = len(errors)
    seen, previous_end = set(), None
    details = {}
    required = required_numeric_fields(payload)
    for index, row in enumerate(inputs):
        before = len(errors)
        if not isinstance(row, dict):
            error(index, "row", "Expected a monthly record")
            continue
        try:
            start, end = _date(row.get("start")), _date(row.get("end"))
            month = row.get("month")
            if start > end or str(start)[:7] != month or str(end)[:7] != month:
                raise ValueError(
                    "Dates must be within the stated month, from start through end"
                )
            if month in seen:
                raise ValueError(
                    "Only one effective segment per month is supported; use reviewed monthly amounts for multiple changes"
                )
            if previous_end and start != previous_end + timedelta(days=1):
                raise ValueError(
                    "Monthly claim dates must be consecutive and sorted without gaps"
                )
            seen.add(month)
            previous_end = end
        except (ValueError, TypeError):
            error(
                index,
                "start",
                "Use consecutive, inclusive dates in one stated month; duplicate months are not supported",
            )
        if row.get("presentation") not in ("period", "whole_month"):
            error(index, "presentation", "Choose period or whole_month")
        for key in REFERENCES:
            if (
                not isinstance(row.get(key), str)
                or not row[key].strip()
                or len(row[key]) > 500
            ):
                error(
                    index,
                    key,
                    "Enter a reference (including an explicit none-found check when applicable), up to 500 characters",
                )
        for key in ("history_reviewed", "deductions_reviewed"):
            if row.get(key) is not True:
                error(index, key, "Confirm this check against the source")
        for key in ("bill_no", "bill_date", "tv_no", "tv_date"):
            if not isinstance(row.get(key, ""), str) or len(row.get(key, "")) > 200:
                error(index, key, "Enter text up to 200 characters")
        values = {}
        for key in required:
            try:
                value = money(row.get(key))
                if value < 0 or value > 100000000:
                    raise ValueError(
                        "Enter a nonnegative amount no greater than 100,000,000"
                    )
                if key in AMOUNT_FIELDS or key == "new_basic":
                    if value != rounded(value):
                        raise ValueError("Amounts support at most two decimal places")
                if key in ("da_rate", "hra_rate") and value > 1000:
                    raise ValueError("Percentage cannot exceed 1000")
                if key == "hda_divisor" and value <= 0:
                    raise ValueError("HDA needs a positive sanctioned divisor")
                values[key] = value
            except ValueError as exc:
                error(index, key, str(exc))
        # Never silently discard figures placed under the other deduction layout.
        active_deductions = TEMPLATES.get(
            payload.get("template_id"), TEMPLATES["jodhpur_classic"]
        )["deduction_keys"]
        for key in DEDUCTION_KEYS:
            if key not in active_deductions and row.get("ded_" + key) not in (
                None,
                "",
                "0",
                "0.00",
                0,
            ):
                error(
                    index,
                    "ded_" + key,
                    "This deduction does not belong to the selected supplied form",
                )
        if header_errors or len(errors) > before:
            continue
        days, month_days = (end - start).days + 1, monthrange(start.year, start.month)[
            1
        ]
        fraction = Decimal(days) / month_days
        due = monthly_due(payload, row, values)
        components, head_audit = [], {}
        for head in HEADS:
            monthly_drawn = values["drawn_" + head]
            if row["presentation"] == "whole_month":
                due_amount = rounded(
                    monthly_drawn * (1 - fraction) + due[head] * fraction,
                    payload["rounding"],
                )
                drawn_amount = monthly_drawn
            else:
                due_amount = rounded(due[head] * fraction, payload["rounding"])
                drawn_amount = rounded(monthly_drawn * fraction, payload["rounding"])
            prior = values["prior_" + head]
            components.append(
                dict(
                    head=head,
                    due=f"{due_amount:.2f}",
                    drawn=f"{drawn_amount:.2f}",
                    prior_settlement=f"{prior:.2f}",
                    difference=f"{due_amount - drawn_amount - prior:.2f}",
                )
            )
            head_audit[head] = dict(
                monthly_drawn=f"{monthly_drawn:.2f}",
                monthly_due=str(due[head]),
                salary_reference=row["salary_reference"],
                order_reference=row["order_reference"],
                prior_reference=row["history_reference"],
                origin="human_reviewed_inputs",
            )
        deductions = {key: f"{values['ded_' + key]:.2f}" for key in active_deductions}
        # New GPF form has two informational already-deducted columns.
        net_keys = (
            active_deductions
            if payload["template_id"] == "jodhpur_classic"
            else ("GPF_TO_DEDUCT", "I_TAX")
        )
        total_deductions = sum((values["ded_" + key] for key in net_keys), Decimal(0))
        details[month] = dict(
            deductions=deductions,
            total_deductions=f"{total_deductions:.2f}",
            **{k: row.get(k, "") for k in ("bill_no", "bill_date", "tv_no", "tv_date")},
        )
        evidence = [
            dict(kind="human_reviewed_inputs", reference=row["salary_reference"])
        ]
        if any(values["prior_" + h] for h in HEADS):
            evidence.append(
                dict(
                    kind="prior_credit",
                    reference=row["history_reference"],
                    pay_month=month,
                )
            )
        rows.append(
            dict(
                month=month,
                start=str(start),
                end=str(end),
                components=components,
                evidence=evidence,
                total_deductions=f"{total_deductions:.2f}",
            )
        )
        audits.append(
            dict(
                row=index,
                month=month,
                days=days,
                month_days=month_days,
                presentation=row["presentation"],
                heads=head_audit,
                deduction_reference=row["deduction_reference"],
            )
        )
    totals = None
    if not errors:
        totals = {
            key: f"{sum((money(c[key]) for r in rows for c in r['components']), Decimal(0)):.2f}"
            for key in ("due", "drawn", "prior_settlement", "difference")
        }
        deducted = sum((money(r["total_deductions"]) for r in rows), Decimal(0))
        totals.update(
            total_deductions=f"{deducted:.2f}",
            net_payable=f"{money(totals['difference']) - deducted:.2f}",
        )
    status = "incomplete" if errors else "ready"
    return dict(
        version=VERSION,
        status=status,
        errors=errors,
        audit=audits,
        bill=dict(
            status="blocked" if errors else "ready",
            blockers=errors,
            rows=rows,
            totals=totals,
            deductions=[],
            evidence=[e for r in rows for e in r["evidence"]],
        ),
        metadata=dict(
            employee_code=payload.get("employee_code", ""),
            employee_name=payload.get("employee_name", ""),
            supplied_template_id=payload.get("template_id"),
            supplied_form_rows=details,
            status="draft",
        ),
    )
