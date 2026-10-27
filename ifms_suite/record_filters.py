"""Shared document/employee/month/amount filters for on-screen and exported rows."""

from datetime import date
from .calculation import money


def amount_value(record, field):
    if field in ("gross", "net"):
        return record.get(field)
    if ":" in field:
        category, head = field.split(":", 1)
        mapping = record.get(
            {"allowance": "allowances", "deduction": "deductions"}.get(category, ""), {}
        )
        return next((v for k, v in mapping.items() if k.upper() == head.upper()), None)
    raise ValueError("Choose gross, net or a named allowance/deduction")


def filter_records(records, query):
    minimum = (
        money(query["minimum"]) if query.get("minimum") not in (None, "") else None
    )
    maximum = (
        money(query["maximum"]) if query.get("maximum") not in (None, "") else None
    )
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Minimum amount exceeds maximum")
    for key in ("month_from", "month_to"):
        if query.get(key):
            date.fromisoformat(query[key] + "-01")
    result = []
    for r in records:
        if query.get("kind") and r.get("document_type") != query["kind"]:
            continue
        if query.get("employee", "").upper() not in r.get("employee_code", "").upper():
            continue
        if query.get("bill_type", "").lower() not in r.get("bill_type", "").lower():
            continue
        if (
            query.get("search", "").lower()
            not in " ".join(
                str(r.get(k, ""))
                for k in (
                    "document",
                    "employee_code",
                    "pay_month",
                    "bill_type",
                    "bill_no",
                )
            ).lower()
        ):
            continue
        month = r.get("pay_month", "")
        if query.get("month_from") and (not month or month < query["month_from"]):
            continue
        if query.get("month_to") and (not month or month > query["month_to"]):
            continue
        if minimum is not None or maximum is not None:
            value = amount_value(r, query.get("amount_field", "gross"))
            if value in (None, ""):
                continue
            value = money(value)
            if minimum is not None and value < minimum:
                continue
            if maximum is not None and value > maximum:
                continue
        result.append(r)
    return result
