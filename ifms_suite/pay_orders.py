"""Conservative printed increment tables; values never come from payroll totals.

Explicit columns and labeled narrative fields retain page-local evidence. Name-only
identities remain unresolved for explicit employee association; ambiguous layouts
remain candidates for source-bound review.
"""

import re
from datetime import date
from decimal import Decimal


_ID = re.compile(r"RJ[A-Z]{2}\d{12}")
_ALIASES = {
    "employee_code": {"employeeid", "employeecode", "कार्मिकआईडी", "कर्मचारीआईडी"},
    "employee_name": {
        "employeename",
        "कर्मचारीकानाम",
        "कार्मिककानाम",
        "कर्मचारीनाम",
        "नाम",
    },
    "old_basic": {
        "oldbasic",
        "oldbasicpay",
        "existingbasic",
        "पुरानामूलवेतन",
        "वर्तमानमूलवेतन",
    },
    "effective_from": {
        "effectivefrom",
        "effectivedate",
        "incrementdate",
        "dateofincrement",
        "वेतनवृद्धिदिनांक",
        "प्रभावीदिनांक",
    },
    "basic_amount": {
        "newbasic",
        "newbasicpay",
        "sanctionedbasic",
        "sanctionedbasicpay",
        "revisedbasicpay",
        "नयामूलवेतन",
        "स्वीकृतमूलवेतन",
    },
}


def _compact(text):
    return re.sub(r"[\s.:\-_/()]", "", text).lower()


def _y(word):
    return (word["box"][1] + word["box"][3]) / 2


def _trusted(word):
    threshold = 0.80 if word.get("recognizer", "").startswith("tesseract") else 0.85
    return word.get("confidence", 0) >= threshold and not word.get(
        "recognition_conflict", False
    )


def _headers(words):
    """Find exact headings, including headings split into adjacent OCR words."""
    found = {key: [] for key in _ALIASES}
    ordered = sorted(words, key=lambda w: (_y(w), w["box"][0]))
    for start in ordered:
        line = sorted(
            (
                w
                for w in words
                if abs(_y(w) - _y(start)) < 0.008 and w["box"][0] >= start["box"][0]
            ),
            key=lambda w: w["box"][0],
        )
        phrase = ""
        for index, word in enumerate(line[:5]):
            if index and word["box"][0] - line[index - 1]["box"][2] > 0.035:
                break
            phrase += _compact(word["text"])
            for key, aliases in _ALIASES.items():
                if phrase in aliases:
                    span = line[: index + 1]
                    if span not in found[key]:
                        found[key].append(span)
    return found


def _date(text):
    match = re.fullmatch(r"(\d{2})[./-](\d{2})[./-](\d{4})", text.strip())
    if match:
        try:
            return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
        except ValueError:
            pass
    return None


def _basic(text):
    match = re.fullmatch(r"(\d+|\d{1,3}(?:,\d{3})+)(\.\d{2})?(?:/-)?", text.strip())
    if not match:
        return None
    value = Decimal(match[1].replace(",", "") + (match[2] or ""))
    return format(value, ".2f") if value > 0 else None


def extract_pay_orders(pages):
    """Return increment rows with provenance and explicit unresolved fields.

    Input matches ``facts_from_pages``: dictionaries with ``page`` and ``words``;
    words carry text, normalized box, confidence and optional recognition conflict.
    No employee identity is inherited from another page or payroll statement.
    An empty list means no supported increment table was found, not completeness.
    """
    result = []
    for page in pages:
        words = page["words"]
        found = _headers(words)
        marker = any(
            _compact(w["text"]) in {"incrementorder", "वेतनवृद्धिआदेश"} and _trusted(w)
            for w in words
        )
        if not marker and not (found["effective_from"] and found["basic_amount"]):
            continue
        headers = {key: spans[0] for key, spans in found.items() if len(spans) == 1}
        # Require a single aligned heading row; repeated/competing layouts fail closed.
        aligned = (
            bool(headers)
            and max(_y(span[0]) for span in headers.values())
            - min(_y(span[0]) for span in headers.values())
            < 0.025
        )
        if not aligned:
            narrative = _narrative(page, headers, marker)
            if narrative:
                result.append(narrative)
            continue
        bottom = max(
            (w["box"][3] for span in headers.values() for w in span), default=0
        )
        summary_start = min(
            (
                _y(w) - 0.012
                for w in words
                if _compact(w["text"]) in {"total", "grandtotal", "कुल", "योग"}
                and _y(w) > bottom
            ),
            default=1,
        )
        identities = [
            w
            for w in words
            if _ID.fullmatch(w["text"].strip().upper())
            and bottom < _y(w) < summary_start
        ]
        name_span = headers.get("employee_name")
        if not identities and name_span:
            left = name_span[0]["box"][0] - 0.015
            right = min(
                (
                    span[0]["box"][0] - 0.015
                    for span in headers.values()
                    if span[0]["box"][0] > name_span[-1]["box"][2]
                ),
                default=1,
            )
            name_words = [
                w
                for w in words
                if left <= w["box"][0] < right and bottom < _y(w) < summary_start
            ]
            # Build one anchor per geometric line; later column extraction retains words.
            identities = []
            for word in sorted(name_words, key=lambda w: (_y(w), w["box"][0])):
                if not any(abs(_y(word) - _y(other)) < 0.012 for other in identities):
                    identities.append(word)
        for identity in identities:
            values = {"employee_code": "", "effective_from": "", "basic_amount": None}
            unresolved = []
            evidence = [dict(identity, page=page["page"])]
            used = [identity]
            for key in _ALIASES:
                if key in {"old_basic", "employee_name"} and key not in headers:
                    continue
                span = headers.get(key)
                if not span or not aligned:
                    unresolved.append(key)
                    continue
                evidence.extend(dict(w, page=page["page"]) for w in span)
                used.extend(span)
                left = span[0]["box"][0] - 0.015
                next_columns = [
                    other[0]["box"][0] - 0.015
                    for other in headers.values()
                    if other[0]["box"][0] > span[-1]["box"][2]
                ]
                right = min(next_columns, default=min(1, span[-1]["box"][2] + 0.10))
                candidates = [
                    w
                    for w in words
                    if left <= w["box"][0] < right and abs(_y(w) - _y(identity)) < 0.012
                ]
                # The employee ID must itself occupy its explicitly labelled column.
                if key == "employee_code":
                    candidates = [
                        w
                        for w in candidates
                        if _ID.fullmatch(w["text"].strip().upper())
                    ]
                evidence.extend(
                    dict(w, page=page["page"]) for w in candidates if w is not identity
                )
                used.extend(candidates)
                if (
                    (len(candidates) != 1 and key != "employee_name")
                    or not candidates
                    or not all(_trusted(w) for w in span + candidates)
                ):
                    unresolved.append(key)
                    continue
                word = candidates[0]
                value = (
                    " ".join(
                        w["text"].strip()
                        for w in sorted(candidates, key=lambda w: w["box"][0])
                    )
                    if key == "employee_name"
                    else (
                        word["text"].strip().upper()
                        if key == "employee_code"
                        else (
                            _date(word["text"])
                            if key == "effective_from"
                            else _basic(word["text"])
                        )
                    )
                )
                if value is None:
                    unresolved.append(key)
                else:
                    values[key] = value
            result.append(
                dict(
                    kind="increment",
                    **values,
                    source_pages=[page["page"]],
                    evidence=evidence,
                    confidence=min(w.get("confidence", 0) for w in used),
                    complete=not [key for key in unresolved if key != "old_basic"],
                    unresolved_fields=[key for key in unresolved if key != "old_basic"]
                )
            )
    return result


def _narrative(page, headers, marker):
    """Read only single, explicitly labeled fields; never choose a nearby issue date."""
    if not marker or not any(k in headers for k in ("employee_name", "employee_code")):
        return None
    # Multiple employee labels/identities cannot share a narrative sanction.
    found = _headers(page["words"])
    if any(
        len(found[k]) > 1
        for k in ("employee_name", "employee_code", "effective_from", "basic_amount")
    ):
        return None
    values = dict(employee_code="", effective_from="", basic_amount=None)
    evidence, unresolved, used = [], [], []
    for key in _ALIASES:
        span = headers.get(key)
        if not span:
            if key in ("employee_code", "effective_from", "basic_amount"):
                unresolved.append(key)
            continue
        line = sorted(
            (
                w
                for w in page["words"]
                if w["box"][0] >= span[-1]["box"][2] - 0.002
                and abs(_y(w) - _y(span[-1])) < 0.012
            ),
            key=lambda w: w["box"][0],
        )
        # Another label on the same line bounds this field.
        right = min(
            (
                other[0]["box"][0]
                for other in headers.values()
                if other[0]["box"][0] > span[-1]["box"][2]
                and abs(_y(other[0]) - _y(span[-1])) < 0.012
            ),
            default=1,
        )
        line = [w for w in line if w["box"][0] < right]
        evidence.extend(dict(w, page=page["page"]) for w in span + line)
        used.extend(span + line)
        text = " ".join(w["text"].strip() for w in line)
        value = (
            text
            if key == "employee_name"
            else (
                text.upper()
                if key == "employee_code" and _ID.fullmatch(text.upper())
                else (
                    _date(text)
                    if key == "effective_from"
                    else _basic(text) if key in ("basic_amount", "old_basic") else None
                )
            )
        )
        if not value or not all(_trusted(w) for w in span + line):
            if key in (
                "employee_code",
                "effective_from",
                "basic_amount",
                "employee_name",
            ):
                unresolved.append(key)
        else:
            values[key] = value
    if not evidence:
        return None
    return dict(
        kind="increment",
        **values,
        source_pages=[page["page"]],
        evidence=evidence,
        confidence=min(w.get("confidence", 0) for w in used),
        complete=not unresolved,
        unresolved_fields=unresolved
    )


def extract_order_candidates(pages):
    """Return incomplete row candidates plus marked but unreadable order pages.

    A fallback candidate carries no guessed identity, amount or effective date.
    It exposes raw evidence for explicit assisted review of that exact source page.
    """
    result = [row for row in extract_pay_orders(pages) if not row["complete"]]
    covered = {p for row in extract_pay_orders(pages) for p in row["source_pages"]}
    for page in pages:
        if page["page"] in covered:
            continue
        if not any(
            _compact(w["text"]) in {"incrementorder", "वेतनवृद्धिआदेश"}
            for w in page["words"]
        ):
            continue
        result.append(
            dict(
                kind="increment",
                employee_code="",
                effective_from="",
                basic_amount=None,
                complete=False,
                unresolved_fields=["employee_code", "effective_from", "basic_amount"],
                source_pages=[page["page"]],
                evidence=[dict(w, page=page["page"]) for w in page["words"]],
            )
        )
    return result
