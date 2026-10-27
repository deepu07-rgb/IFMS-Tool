"""Conservative printed increment tables; values never come from payroll totals.

Only explicit column headings and row-local employee IDs are supported. Narrative
orders, name-only identities, merged cells, continuations, and rotated/skewed tables
remain unresolved for review. Callers retain unsupported-page issues for those.
"""

import re
from datetime import date
from decimal import Decimal


_ID = re.compile(r"RJ[A-Z]{2}\d{12}")
_ALIASES = {
    "employee_code": {"employeeid", "employeecode", "कार्मिकआईडी", "कर्मचारीआईडी"},
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
        for index, word in enumerate(line[:4]):
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
        for identity in identities:
            values = {"employee_code": "", "effective_from": "", "basic_amount": None}
            unresolved = []
            evidence = [dict(identity, page=page["page"])]
            used = [identity]
            for key in _ALIASES:
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
                if len(candidates) != 1 or not all(
                    _trusted(w) for w in span + candidates
                ):
                    unresolved.append(key)
                    continue
                word = candidates[0]
                value = (
                    word["text"].strip().upper()
                    if key == "employee_code"
                    else (
                        _date(word["text"])
                        if key == "effective_from"
                        else _basic(word["text"])
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
                    complete=not unresolved,
                    unresolved_fields=unresolved
                )
            )
    return result
