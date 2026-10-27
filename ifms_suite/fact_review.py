"""Narrow human review of an unreadable HRA percentage, retaining source facts.

The caller must bind these requests to its immutable imported PDF and cached facts.
This module never repairs OCR digits or treats a submitted rate as recognition.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re


_ID = re.compile(r"RJ[A-Z]{2}\d{12}")
_DATE = re.compile(r"(\d{2})[./:](\d{2})[./:](\d{4})")


def _reliable(evidence):
    recognizer = str(evidence.get("recognizer", "")).lower()
    if recognizer.startswith("tesseract"):
        threshold = Decimal("0.80")
    elif recognizer.startswith("rapidocr"):
        threshold = Decimal("0.85")
    elif recognizer.startswith("pdf"):
        threshold = Decimal("1")
    else:
        return False
    try:
        confidence = Decimal(str(evidence.get("confidence", "")))
        return (confidence.is_finite() and threshold <= confidence <= 1
                and not evidence.get("recognition_conflict", False))
    except InvalidOperation:
        return False


def _code(text):
    return re.sub(r"\s+", "", str(text)).upper()


def _date(text):
    match = _DATE.fullmatch(str(text).strip())
    if match:
        try:
            return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
        except ValueError:
            pass
    return None


def _requests(facts):
    """Yield an issue index and request only for a unique matching sanction row."""
    version = facts.get("facts_version")
    if not isinstance(version, str) or not version.strip():
        return
    codes = {b.get("employee_code") for b in facts.get("bills", [])
             if b.get("employee_code") and b.get("identity_reliable") is not False}
    for code in sorted(codes):
        matching = [(i, issue) for i, issue in enumerate(facts.get("issues", []))
                    if issue.get("kind") == "order_unresolved"
                    and issue.get("employee_code") == code]
        if len(matching) != 1 or any(
            o.get("employee_code") == code and o.get("allowance") == "HRA"
            for o in facts.get("orders", [])
        ):
            continue
        index, issue = matching[0]
        if (issue.get("unresolved_fields") != ["rate"]
                or issue.get("allowance", "HRA") != "HRA"):
            continue
        page = issue.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            continue
        evidence = issue.get("evidence", [])
        identities = {_code(e.get("text", "")) for e in evidence
                      if _ID.fullmatch(_code(e.get("text", ""))) and _reliable(e)}
        dates = [_date(e.get("text", "")) for e in evidence
                 if _reliable(e) and _date(e.get("text", ""))]
        if identities != {code} or len(dates) != 1:
            continue
        identity = [version, code, dates[0], page, "rate"]
        request_id = hashlib.sha256(json.dumps(identity, separators=(",", ":"),
                                              ensure_ascii=True).encode()).hexdigest()
        yield index, dict(request_id=request_id, employee_code=code,
                          effective_from=dates[0], page=page, field="rate",
                          facts_version=version, evidence=deepcopy(evidence))


def rate_review_requests(facts):
    """Return field-only review requests; ambiguous rows remain unresolved."""
    return [request for _, request in _requests(facts)]


def apply_rate_reviews(facts, reviews):
    """Return copied facts with explicitly reviewed rates; reject stale/bad input.

    Each review requires request_id, facts_version, rate, reviewed=True and a
    nonempty reference. All entries validate before any derived result is built.
    The raw facts and every unrelated blocker/evidence object remain unchanged.
    """
    if not isinstance(reviews, list):
        raise ValueError("Rate reviews must be a list")
    requests = {r["request_id"]: (index, r) for index, r in _requests(facts)}
    accepted = []
    seen = set()
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("Invalid rate review")
        request_id = review.get("request_id")
        if not isinstance(request_id, str) or request_id not in requests or request_id in seen:
            raise ValueError("Stale, unknown or repeated rate review request")
        index, request = requests[request_id]
        if review.get("facts_version") != request["facts_version"]:
            raise ValueError("Stale rate review facts version")
        reference = review.get("reference")
        if review.get("reviewed") is not True or not isinstance(reference, str) or not reference.strip():
            raise ValueError("Explicit review and a source reference are required")
        value = review.get("rate")
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise ValueError("Invalid HRA percentage")
        try:
            rate = Decimal(str(value))
            if not rate.is_finite() or not 0 < rate <= 100:
                raise ValueError("Invalid HRA percentage")
        except InvalidOperation as exc:
            raise ValueError("Invalid HRA percentage") from exc
        seen.add(request_id)
        accepted.append((index, request, str(rate), reference.strip()))
    result = deepcopy(facts)
    matched = {index for index, _, _, _ in accepted}
    result["issues"] = [issue for index, issue in enumerate(result.get("issues", []))
                        if index not in matched]
    for _, request, rate, reference in accepted:
        result.setdefault("orders", []).append(dict(
            employee_code=request["employee_code"], effective_from=request["effective_from"],
            rate=rate, allowance="HRA", human_reviewed=True,
            review_reference=reference, reference=reference,
            review_request_id=request["request_id"], facts_version=request["facts_version"],
            evidence=deepcopy(request["evidence"]), source_pages=[request["page"]],
        ))
    return result
