"""Source-bound assisted order review. Raw recognition is never corrected here.

Requests describe one candidate or one unresolved source page. Human decisions
are derived records, explicitly marked assisted, and retain the original evidence.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

_ID = re.compile(r"RJ[A-Z]{2}\d{12}")


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _kind(value):
    text = str(value or "").lower()
    return text if text in {"increment", "hra", "da"} else ""


def _pages(candidate):
    pages = candidate.get("source_pages") or [candidate.get("page")]
    if (
        not isinstance(pages, list)
        or not pages
        or any(isinstance(p, bool) or not isinstance(p, int) or p < 1 for p in pages)
    ):
        return []
    return sorted(set(pages))


def _requests(facts):
    version, source = facts.get("facts_version"), facts.get("source_sha256")
    if (
        not isinstance(version, str)
        or not version.strip()
        or not isinstance(source, str)
        or not re.fullmatch(r"[a-fA-F0-9]{64}", source)
    ):
        return
    candidates = list(enumerate(facts.get("order_candidates", [])))
    covered = {p for _, c in candidates for p in _pages(c)}
    for index, issue in enumerate(facts.get("issues", [])):
        if issue.get("kind") not in {
            "unsupported_page",
            "order_unresolved",
            "pay_order_unresolved",
        }:
            continue
        if issue.get("role") in {"reference", "reference_statement"}:
            continue
        if not _pages(issue):
            continue
        if issue.get("kind") == "unsupported_page" and set(_pages(issue)) <= covered:
            continue
        if issue.get("order_candidate_index") is not None:
            continue
        candidates.append((f"issue:{index}", issue))
    # An identified order page may contain an unreadable target row even when
    # OCR recognized other employees. Offer source association, never an OCR fact.
    codes = {
        b.get("employee_code") for b in facts.get("bills", []) if b.get("employee_code")
    }
    for page in facts.get("page_classifications", []):
        kind = {
            "hra_order": "hra",
            "pay_order": "increment",
            "increment_order": "increment",
            "da_order": "da",
        }.get(page.get("kind"))
        if not kind:
            continue
        for code in sorted(codes):
            if any(
                c.get("employee_code") == code
                and kind == (_kind(c.get("kind")) or _kind(c.get("allowance")))
                and page["page"] in _pages(c)
                for _, c in candidates
            ):
                continue
            if any(
                o.get("employee_code") == code and page["page"] in _pages(o)
                for key in ("orders", "pay_orders")
                for o in facts.get(key, [])
            ):
                continue
            candidate = dict(
                kind=kind,
                employee_code=code,
                source_pages=[page["page"]],
                recognition_status="not_read_requires_source_review",
                unresolved_fields=[
                    "effective_from",
                    "basic_amount" if kind == "increment" else "rate",
                ],
                evidence=[
                    dict(page=page["page"], kind="explicit_source_page_association")
                ],
            )
            candidates.append((f"page:{page['page']}:{code}:{kind}", candidate))
    seen = set()
    reviewed = {
        row.get("review_request_id")
        for key in ("orders", "pay_orders")
        for row in facts.get(key, [])
    }
    for index, candidate in candidates:
        pages = _pages(candidate)
        if not pages:
            continue
        request_id = _digest([version, source, candidate])
        if request_id in seen or request_id in reviewed:
            continue
        seen.add(request_id)
        yield dict(
            request_id=request_id,
            facts_version=version,
            source_sha256=source,
            candidate_index=index,
            kind=_kind(candidate.get("kind")) or _kind(candidate.get("allowance")),
            employee_code=candidate.get("employee_code", ""),
            employee_name=candidate.get("employee_name", ""),
            source_pages=pages,
            evidence=deepcopy(candidate.get("evidence", [])),
            candidate=deepcopy(candidate),
            unresolved_fields=deepcopy(candidate.get("unresolved_fields", [])),
        )


def order_review_requests(facts):
    """List exact-source requests; name-only identities always need association."""
    return list(_requests(facts))


def _date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"Invalid {field} date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field} date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"Invalid {field} date")
    return value


def _number(value, label, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"Invalid {label}")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {label}") from exc
    if (
        not number.is_finite()
        or number <= 0
        or (maximum is not None and number > maximum)
    ):
        raise ValueError(f"Invalid {label}")
    return number


def apply_order_reviews(facts, reviews):
    """Validate all flat review decisions before deriving assisted order records.

    Required: request_id, facts_version, source_sha256, reviewed=True, reference,
    employee_code (explicit for name-only sources), effective_from, kind when
    unclassified, basic_amount for increment or rate for HRA/DA. Optional fields:
    effective_to, hra_eligible, hra_reference, hda_rule, entire_page_reviewed.
    Only entire-page confirmation removes matching unsupported-page blockers.
    """
    if not isinstance(reviews, list):
        raise ValueError("Order reviews must be a list")
    requests = {r["request_id"]: r for r in _requests(facts)}
    codes = {
        r.get("employee_code") for r in facts.get("bills", []) if r.get("employee_code")
    }
    accepted, seen = [], set()
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("Invalid order review")
        rid = review.get("request_id")
        if not isinstance(rid, str) or rid not in requests or rid in seen:
            raise ValueError("Stale, unknown or repeated order review request")
        request = requests[rid]
        if any(
            review.get(key) != request[key]
            for key in ("facts_version", "source_sha256")
        ):
            raise ValueError("Stale order review source or facts version")
        reference = review.get("reference")
        if (
            review.get("reviewed") is not True
            or not isinstance(reference, str)
            or not reference.strip()
        ):
            raise ValueError("Explicit review and a source reference are required")
        candidate = request["candidate"]
        code = review.get("employee_code", candidate.get("employee_code", ""))
        if not isinstance(code, str) or not _ID.fullmatch(code) or code not in codes:
            raise ValueError("Explicit imported employee association is required")
        # Even a syntactically valid OCR code cannot be silently reassigned.
        if candidate.get("employee_code") and code != candidate["employee_code"]:
            raise ValueError("Order employee differs from source candidate")
        kind = _kind(review.get("kind", request["kind"]))
        if not kind or (request["kind"] and kind != request["kind"]):
            raise ValueError("Explicit supported order kind is required")
        start = _date(
            review.get("effective_from", candidate.get("effective_from")),
            "effective_from",
        )
        row = dict(
            employee_code=code,
            effective_from=start,
            kind=kind,
            human_reviewed=True,
            assisted=True,
            complete=True,
            unresolved_fields=[],
            review_reference=reference.strip(),
            reference=reference.strip(),
            review_request_id=rid,
            facts_version=request["facts_version"],
            source_sha256=request["source_sha256"],
            source_pages=request["source_pages"],
            evidence=deepcopy(request["evidence"]),
            review_decision=deepcopy(review),
        )
        if review.get("effective_to"):
            row["effective_to"] = _date(review["effective_to"], "effective_to")
            if row["effective_to"] < start:
                raise ValueError("Order date range is reversed")
        if kind == "increment":
            amount = _number(
                review.get("basic_amount", candidate.get("basic_amount")),
                "basic amount",
            )
            if amount != amount.quantize(Decimal(".01")):
                raise ValueError("Basic amount supports at most two decimal places")
            row["basic_amount"] = format(amount, ".2f")
        else:
            row.update(
                allowance=kind.upper(),
                rate=str(
                    _number(
                        review.get("rate", candidate.get("rate")),
                        "percentage",
                        Decimal(100),
                    )
                ),
            )
        if "hra_eligible" in review:
            if not isinstance(review["hra_eligible"], bool):
                raise ValueError("HRA eligibility must be explicit boolean")
            row.update(
                hra_eligible=review["hra_eligible"], hra_reference=reference.strip()
            )
        if review.get("hda_rule") is not None:
            rule = review["hda_rule"]
            if (
                not isinstance(rule, dict)
                or not isinstance(rule.get("reference"), str)
                or not rule["reference"].strip()
            ):
                raise ValueError("HDA rule requires a reference")
            row["hda_rule"] = dict(
                numerator=str(_number(rule.get("numerator"), "HDA numerator")),
                denominator=str(_number(rule.get("denominator"), "HDA denominator")),
                reference=rule["reference"].strip(),
            )
        if "entire_page_reviewed" in review and not isinstance(
            review["entire_page_reviewed"], bool
        ):
            raise ValueError("Entire page review must be explicit boolean")
        accepted.append((request, row, review.get("entire_page_reviewed") is True))
        seen.add(rid)
    result = deepcopy(facts)
    for request, row, whole_page in accepted:
        key = "pay_orders" if row["kind"] == "increment" else "orders"
        result[key] = [
            old
            for old in result.get(key, [])
            if not (old == request["candidate"] and old.get("complete") is False)
        ]
        result.setdefault(
            "pay_orders" if row["kind"] == "increment" else "orders", []
        ).append(row)

    def resolved(index, issue):
        for request, _, whole_page in accepted:
            candidate_index = request["candidate_index"]
            same_pages = bool(_pages(issue)) and set(_pages(issue)) <= set(
                request["source_pages"]
            )
            if whole_page and same_pages and issue.get("kind") == "unsupported_page":
                return True
            if issue.get("kind") not in {"order_unresolved", "pay_order_unresolved"}:
                continue
            if isinstance(candidate_index, str) and candidate_index == f"issue:{index}":
                return True
            if (
                isinstance(candidate_index, int)
                and same_pages
                and issue.get("order_candidate_index") == candidate_index
            ):
                return True
        return False

    result["issues"] = [
        issue
        for index, issue in enumerate(result.get("issues", []))
        if not resolved(index, issue)
    ]
    return result
