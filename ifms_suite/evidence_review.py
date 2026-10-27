"""Explicit source-bound corrections to existing bill fields, never OCR repair.

Callers retain immutable machine facts and persist review entries separately. The
returned copy carries field-level audit entries; it is never blanket reviewed.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

_FIELDS = (
    "employee_code",
    "pay_month",
    "bill_no",
    "printed_gross",
    "printed_deductions",
    "printed_net",
)
_RECONCILIATION = {
    "Allowance heads do not reconcile to printed gross",
    "Printed gross, deductions and net do not reconcile",
}
_MISSING = {
    "Employee identity unresolved": "employee_code",
    "Pay month unresolved": "pay_month",
    "Bill number unresolved": "bill_no",
}


def _binding(facts, source_sha256, facts_version):
    if (
        not isinstance(source_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
        or not isinstance(facts_version, str)
        or not facts_version.strip()
        or facts.get("facts_version") != facts_version
    ):
        raise ValueError("Invalid source SHA or stale facts version")


def _value(bill, field):
    return (
        bill.get("allowances", {}).get(field[11:])
        if field.startswith("allowances.")
        else bill.get(field)
    )


def _normalize(field, value):
    if field == "employee_code":
        if not isinstance(value, str) or not re.fullmatch(r"RJ[A-Z]{2}\d{12}", value):
            raise ValueError("Invalid employee identity")
        return value
    if field == "bill_no":
        if not isinstance(value, str) or not re.fullmatch(r"\d{9}", value):
            raise ValueError("Invalid bill number")
        return value
    if field == "pay_month":
        if not isinstance(value, str) or not re.fullmatch(r"20\d{2}-\d{2}", value):
            raise ValueError("Invalid pay month")
        try:
            date.fromisoformat(value + "-01")
        except ValueError as exc:
            raise ValueError("Invalid pay month") from exc
        return value
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Invalid monetary value")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", str(value)):
        raise ValueError(
            "Monetary value must be literal with at most two decimal places"
        )
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError("Invalid monetary value")
        return format(amount, ".2f")
    except InvalidOperation as exc:
        raise ValueError("Invalid monetary value") from exc


def evidence_requests(facts, source_sha256, facts_version):
    """Offer field reviews only for existing incomplete bill records/heads.

    Every request carries original page provenance and evidence. Missing allowance
    heads are deliberately not invented. Snapshot IDs also reject changed facts.
    """
    _binding(facts, source_sha256, facts_version)
    snapshot = hashlib.sha256(
        json.dumps(
            facts, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()
    requests = []
    for index, bill in enumerate(facts.get("bills", [])):
        if bill.get("complete") is True:
            continue
        pages = bill.get("source_pages", [])
        if not pages or any(
            isinstance(p, bool) or not isinstance(p, int) or p < 1 for p in pages
        ):
            continue
        fields = list(_FIELDS) + [
            "allowances." + head for head in bill.get("allowances", {})
        ]
        for field in fields:
            if field in bill.get("field_reviews", {}):
                continue
            identity = [source_sha256, facts_version, snapshot, index, field]
            request_id = hashlib.sha256(
                json.dumps(identity, separators=(",", ":")).encode()
            ).hexdigest()
            requests.append(
                dict(
                    request_id=request_id,
                    source_sha256=source_sha256,
                    facts_version=facts_version,
                    bill_index=index,
                    field=field,
                    value=deepcopy(_value(bill, field)),
                    employee_code=bill.get("employee_code", ""),
                    pay_month=bill.get("pay_month", ""),
                    bill_no=bill.get("bill_no", ""),
                    source_pages=deepcopy(pages),
                    evidence=deepcopy(bill.get("evidence", [])),
                )
            )
    return requests


def _issue_matches(issue, bill):
    return issue.get("kind") == "bill_unresolved" and all(
        issue.get(k) == bill.get(k)
        for k in ("employee_code", "pay_month", "bill_no", "source_pages")
    )


def _flags_remaining(flags, original, bill):
    reviewed = bill.get("field_reviews", {})
    remaining = []
    for flag in flags:
        if flag in _RECONCILIATION:
            continue  # These are recomputed below, including after a bad correction.
        if flag in _MISSING and _MISSING[flag] in reviewed:
            continue
        if isinstance(flag, str) and flag.startswith(
            ("Low confidence: ", "Recognition conflict: ")
        ):
            text = flag.split(": ", 1)[1]
            fields = []
            for field in list(_FIELDS) + [
                "allowances." + h for h in original.get("allowances", {})
            ]:
                old = reviewed.get(field, {}).get(
                    "original_value", _value(original, field)
                )
                tokens = {str(old)}
                if (
                    field == "pay_month"
                    and isinstance(old, str)
                    and re.fullmatch(r"20\d{2}-(?:0[1-9]|1[0-2])", old)
                ):
                    year, month = old.split("-")
                    names = "January February March April May June July August September October November December".split()
                    tokens.update((year, names[int(month) - 1]))
                monetary = field.startswith("allowances.") or field.startswith(
                    "printed_"
                )
                money_matches = False
                if monetary and re.fullmatch(
                    r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}", text
                ):
                    try:
                        money_matches = Decimal(text.replace(",", "")) == Decimal(
                            str(old)
                        )
                    except InvalidOperation:
                        pass
                if text in tokens or money_matches:
                    fields.append(field)
            if fields and all(field in reviewed for field in fields):
                continue
        remaining.append(flag)
    return remaining


def _valid(field, bill):
    try:
        _normalize(field, _value(bill, field))
        return True
    except ValueError:
        return False


def _recalculate(original, bill, issues):
    matches = [i for i, issue in enumerate(issues) if _issue_matches(issue, original)]
    # Ambiguous duplicate issue associations remain blockers.
    flags = (
        _flags_remaining(issues[matches[0]].get("issues", []), original, bill)
        if len(matches) == 1
        else []
    )
    valid_identity = all(_valid(f, bill) for f in _FIELDS[:3])
    reliable = (
        bill.get("identity_reliable") is True
        and bill.get("period_reliable") is True
        and bill.get("bill_type_reliable") is True
    )
    try:
        heads = bill.get("allowances", {})
        reconciled = bool(heads) and all(_valid("allowances." + h, bill) for h in heads)
        reconciled = bool(
            reconciled
            and _valid("printed_gross", bill)
            and sum((Decimal(str(v)) for v in heads.values()), Decimal(0))
            == Decimal(str(bill["printed_gross"]))
        )
    except (InvalidOperation, TypeError):
        reconciled = False
    if not reconciled:
        flags.append("Allowance heads do not reconcile to printed gross")
    payment_present = (
        any(bill.get(k) is not None for k in ("printed_deductions", "printed_net"))
        or bill.get("net_reconciled") is not None
    )
    net_ok = None
    if payment_present:
        net_ok = all(_valid(f, bill) for f in _FIELDS[3:])
        if net_ok:
            net_ok = Decimal(str(bill["printed_gross"])) - Decimal(
                str(bill["printed_deductions"])
            ) == Decimal(str(bill["printed_net"]))
        if not net_ok:
            flags.append("Printed gross, deductions and net do not reconcile")
    bill["net_reconciled"] = net_ok
    complete = bool(
        valid_identity
        and reliable
        and reconciled
        and not flags
        and len(matches) <= 1
        and not bill.get("issues")
    )
    bill["allowances_complete"] = complete
    bill["complete"] = complete and net_ok is True
    if len(matches) == 1:
        issue = issues[matches[0]]
        if not bill["complete"] and not flags:
            flags.append("Bill field reliability unresolved")
        if flags:
            issue["issues"] = flags
            for key in ("employee_code", "pay_month", "bill_no"):
                issue[key] = bill.get(key)
        else:
            issues.pop(matches[0])


def apply_evidence_reviews(facts, reviews, source_sha256, facts_version):
    """Validate all entries, then return corrected derived facts with audit data.

    Reviews require request_id, field, value, source_sha256, facts_version,
    reviewed=True and a nonempty reference. Unknown/stale/duplicate fields fail.
    Unrelated document, order and bill blockers are retained.
    """
    requests = {
        r["request_id"]: r
        for r in evidence_requests(facts, source_sha256, facts_version)
    }
    if not isinstance(reviews, list):
        raise ValueError("Evidence reviews must be a list")
    accepted, seen = [], set()
    allowed = {
        "request_id",
        "field",
        "value",
        "source_sha256",
        "facts_version",
        "reviewed",
        "reference",
    }
    for review in reviews:
        if not isinstance(review, dict) or set(review) - allowed:
            raise ValueError("Unknown evidence review fields")
        request_id = review.get("request_id")
        if (
            not isinstance(request_id, str)
            or request_id not in requests
            or request_id in seen
        ):
            raise ValueError("Stale, duplicate or unknown evidence review")
        request = requests[request_id]
        if any(
            review.get(k) != request[k]
            for k in ("field", "source_sha256", "facts_version")
        ):
            raise ValueError("Stale source/version or unknown field")
        reference = review.get("reference")
        if (
            review.get("reviewed") is not True
            or not isinstance(reference, str)
            or not reference.strip()
        ):
            raise ValueError("Explicit review and original source reference required")
        value = _normalize(request["field"], review.get("value"))
        accepted.append((request, value, reference.strip()))
        seen.add(request_id)
    result = deepcopy(facts)
    touched = set()
    for request, value, reference in accepted:
        index, field = request["bill_index"], request["field"]
        bill = result["bills"][index]
        if field.startswith("allowances."):
            bill["allowances"][field[11:]] = value
        else:
            bill[field] = value
        if field == "employee_code":
            bill["identity_reliable"] = True
        elif field == "pay_month":
            bill["period_reliable"] = True
        bill.setdefault("field_reviews", {})[field] = dict(
            request_id=request["request_id"],
            facts_version=facts_version,
            source_sha256=source_sha256,
            reference=reference,
            reviewed=True,
            original_value=deepcopy(request["value"]),
            value=value,
            source_pages=deepcopy(request["source_pages"]),
        )
        touched.add(index)
    for index in sorted(touched):
        _recalculate(
            facts["bills"][index],
            result["bills"][index],
            result.setdefault("issues", []),
        )
    return result
