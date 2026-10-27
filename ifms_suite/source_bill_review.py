"""Explicit reconciliation of an existing source bill; originals stay immutable."""

from copy import deepcopy
from datetime import date
import hashlib
import json
import re
from .calculation import money, rounded
from .payment_types import classify_bill


def bill_review_requests(facts):
    if not facts.get("source_sha256") or not facts.get("facts_version"):
        raise ValueError("Source hash and extraction version required")
    return [
        dict(
            request_id=hashlib.sha256(
                json.dumps(
                    [facts["source_sha256"], facts["facts_version"], i, b],
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            bill_index=i,
            record=deepcopy(b),
            source_pages=b.get("source_pages", []),
        )
        for i, b in enumerate(facts.get("bills", []))
        if not b.get("source_bill_review")
    ]


def apply_bill_reviews(facts, reviews):
    result = deepcopy(facts)
    available = {r["request_id"]: r for r in bill_review_requests(facts)}
    seen = set()
    for review in reviews:
        rid = review.get("request_id")
        if rid not in available or rid in seen:
            raise ValueError("Stale or repeated source bill review")
        if (
            review.get("reviewed") is not True
            or not str(review.get("reference", "")).strip()
        ):
            raise ValueError("Explicit original source review and reference required")
        req = available[rid]
        old = result["bills"][req["bill_index"]]
        record = review.get("record", {})
        code = record.get("employee_code", "")
        if not re.fullmatch(r"RJ[A-Z]{2}\d{12}", code):
            raise ValueError("Verify source employee identity")
        if old.get("employee_code") and code != old["employee_code"]:
            raise ValueError("Cannot reassign an identified source bill")
        month = record.get("pay_month", "")
        date.fromisoformat(month + "-01")
        if not re.fullmatch(r"\d{9}", record.get("bill_no", "")):
            raise ValueError("Verify source bill number")
        category = classify_bill(record.get("bill_type", ""))
        if category == "other":
            raise ValueError("Source bill type requires classification")
        values = {}
        for kind in ("allowances", "deductions"):
            mapping = record.get(kind, {})
            if not isinstance(mapping, dict):
                raise ValueError("Source components must be named amounts")
            values[kind] = {}
            for key, value in mapping.items():
                head = str(key).strip().upper()
                if not head or head in values[kind]:
                    raise ValueError("Missing or duplicate source component")
                amount = money(value)
                if amount != rounded(amount):
                    raise ValueError("Source money supports at most two decimals")
                values[kind][head] = format(amount, ".2f")
        if not values["allowances"]:
            raise ValueError("Source allowance heads required")
        gross = sum((money(v) for v in values["allowances"].values()), money("0"))
        deducted = sum((money(v) for v in values["deductions"].values()), money("0"))
        for key, total in [
            ("printed_gross", gross),
            ("printed_deductions", deducted),
            ("printed_net", gross - deducted),
        ]:
            if money(record.get(key)) != total:
                raise ValueError(
                    "Source components do not reconcile with printed gross/deductions/net"
                )
        updated = deepcopy(old)
        for key in (
            "employee_code",
            "pay_month",
            "bill_no",
            "bill_type",
            "printed_gross",
            "printed_deductions",
            "printed_net",
        ):
            updated[key] = record[key]
        updated.update(
            values,
            complete=True,
            allowances_complete=True,
            deductions_complete=True,
            deductions_reconciled=True,
            net_reconciled=True,
            identity_reliable=True,
            period_reliable=True,
            bill_type_reliable=True,
            human_reviewed=True,
            issues=[],
            source_bill_review=deepcopy(review),
            payment_class=category,
        )
        updated["evidence"] = old.get("evidence") or [
            dict(
                source_pages=old.get("source_pages", []),
                reference=review["reference"],
                human_reviewed=True,
            )
        ]
        for field in ("covered_dates", "entitlement_period"):
            if record.get(field):
                span = record[field]
                a, b = date.fromisoformat(span["start"]), date.fromisoformat(
                    span["end"]
                )
                if a > b or (
                    field == "covered_dates"
                    and (str(a)[:7] != month or str(b)[:7] != month)
                ):
                    raise ValueError("Invalid source coverage dates")
                updated[field] = dict(start=str(a), end=str(b))
        if record.get("monthly_basic") not in (None, ""):
            monthly = money(record["monthly_basic"])
            if monthly < 0 or monthly != rounded(monthly):
                raise ValueError("Invalid source monthly basic")
            updated["monthly_basic"] = format(monthly, ".2f")
        if record.get("allocations_by_head"):
            from .payroll import validate_period_allocations

            updated["allocations_by_head"] = validate_period_allocations(
                updated, record["allocations_by_head"]
            )
        result["bills"][req["bill_index"]] = updated
        result["issues"] = [
            issue
            for issue in result.get("issues", [])
            if not (
                issue.get("kind") == "bill_unresolved"
                and all(
                    issue.get(k) == old.get(k)
                    for k in ("employee_code", "pay_month", "source_pages")
                )
                and (not issue.get("bill_no") or issue["bill_no"] == old.get("bill_no"))
            )
        ]
        seen.add(rid)
    return result
