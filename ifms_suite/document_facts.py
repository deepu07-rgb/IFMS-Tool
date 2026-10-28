"""Geometry-backed printed document facts; unresolved recognition never becomes money.

The optional RapidOCR adapter supplies independent printed recognition. It is loaded
lazily: installations without it retain Tesseract and explicit unresolved facts.
All boxes are normalized page coordinates, and all monetary values are strings.
"""

import csv
import io
import re
import subprocess
from datetime import date
from decimal import Decimal
from statistics import median

FACTS_VERSION = "geometry-printed-v7"

# Fixed recognition gates are independent of reconciliation and expected totals.
NEURAL_CONFIDENCE = 0.85
TESSERACT_CONFIDENCE = 0.80

MONTHS = "January February March April May June July August September October November December".split()
ID = re.compile(r"RJ[A-Z]{2}\d{12}")
HEADS = {
    "basic": "Basic",
    "da": "DA",
    "hra": "HRA",
    "cca": "CCA",
    "hda": "HDA",
    "messall": "Mess All",
    "rop": "ROP",
    "fta": "FTA",
}


def _text(w):
    return re.sub(r"\s+", "", w["text"]).upper()


def _y(w):
    return (w["box"][1] + w["box"][3]) / 2


def _money(text):
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}", text.strip()):
        return None
    return format(Decimal(text.replace(",", "")), ".2f")


def _head(word):
    return HEADS.get(re.sub("[^a-z]", "", word["text"].lower()))


def _evidence(word, page):
    return dict(word, page=page)


def _reliable(word):
    threshold = (
        TESSERACT_CONFIDENCE
        if word.get("recognizer", "").startswith("tesseract")
        else NEURAL_CONFIDENCE
    )
    return word.get("confidence", 0) >= threshold and not word.get(
        "recognition_conflict", False
    )


def _recognition_flags(words):
    return [
        (
            "Recognition conflict: "
            if w.get("recognition_conflict")
            else "Low confidence: "
        )
        + w["text"]
        for w in words
        if not _reliable(w)
    ]


def _identity(words):
    ids = [_text(w) for w in words if ID.fullmatch(_text(w))]
    return ids[0] if len(set(ids)) == 1 else ""


def _classify_page(words):
    trusted = "".join(_text(w) for w in words if _reliable(w))
    if "PAYSLIP" in trusted and "EARNINGS" in trusted:
        return "salary_slip"
    if "GA55" in trusted or ("ALLOWANCES" in trusted and "GROSS" in trusted):
        return "ga55"
    if (
        "HOUSE" in trusted
        and "RENT" in trusted
        and any(ID.fullmatch(_text(w)) for w in words)
    ):
        return "hra_order"
    if "PAYTOBEDRAWN" in trusted and "PAYALREADYDRAWN" in trusted:
        return "reference_statement"
    return "unclassified" if words else "blank"


def _heads(words, page, start, end, left, right):
    region = [
        w
        for w in words
        if left <= w["box"][0] and w["box"][2] <= right and start <= _y(w) < end
    ]
    result = {}
    evidence = []
    issues = []
    for label in region:
        head = _head(label)
        if not head:
            continue
        lane_end = min(
            (
                w["box"][0] - 0.005
                for w in region
                if _head(w) and w["box"][0] > label["box"][0] + 0.04
            ),
            default=right,
        )
        candidates = [
            w
            for w in region
            if label["box"][2] < w["box"][0] < lane_end
            and abs(_y(w) - _y(label)) < 0.013
            and _money(w["text"]) is not None
        ]
        candidates.sort(key=lambda w: (abs(_y(w) - _y(label)), w["box"][0]))
        if not candidates:
            issues.append("Unreadable amount for " + head)
            continue
        value = candidates[0]
        issues.extend(_recognition_flags([label, value]))
        if head in result:
            issues.append("Repeated allowance " + head)
        else:
            result[head] = _money(value["text"])
            evidence.extend([_evidence(label, page), _evidence(value, page)])
    # An amount lacking a recognized head cannot silently disappear.
    used = {(tuple(w["box"]), w["text"]) for w in evidence}
    for w in region:
        if _money(w["text"]) is not None and (tuple(w["box"]), w["text"]) not in used:
            issues.append("Unassigned allowance amount " + w["text"])
    return result, evidence, issues


def _deduction_heads(words, page, start, end, geometry):
    """Read the two deduction lanes independently of totals and allowance lanes.

    Wrapped ROAD/WAYS labels are joined only when both printed fragments exist.
    Unknown printed labels remain literal heads; no money is inferred from totals.
    """
    if geometry is None:
        return {}, [], []
    left, right = geometry
    middle = (left + right) / 2
    result, evidence, issues = {}, [], []
    region = [
        w
        for w in words
        if left <= w["box"][0] and w["box"][2] <= right and start <= _y(w) < end
    ]
    used = set()
    for lane_left, lane_right in ((left, middle), (middle, right)):
        lane = [w for w in region if lane_left <= w["box"][0] < lane_right]
        labels = [
            w
            for w in lane
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9 ._/-]*", w["text"])
            and _text(w).strip("-_.")
            not in {
                "DEDUCTIONS",
                "TOTAL",
                "NET",
                "AMOUNT",
                "WAYS",
                "DEDUTI",
                "ON",
                "DEDUTION",
                "DEDUCTION",
            }
        ]
        consumed_labels = set()
        for label in sorted(labels, key=_y):
            if id(label) in consumed_labels:
                continue
            head = _text(label).strip("-_.")
            fragments = [label]
            if head == "ROAD":
                wrapped = sorted(
                    (
                        w
                        for w in lane
                        if abs(w["box"][0] - label["box"][0]) < 0.015
                        and 0 < _y(w) - _y(label) < 0.065
                        and _text(w).strip(".")
                        in {"WAYS", "DEDUTI", "ON", "DEDUTION", "DEDUCTION"}
                    ),
                    key=_y,
                )
                if wrapped and _text(wrapped[0]) == "WAYS":
                    head = "ROADWAYS"
                    fragments += wrapped
            if head == "RP":
                wrapped = sorted(
                    (
                        w
                        for w in lane
                        if abs(w["box"][0] - label["box"][0]) < 0.015
                        and 0 < _y(w) - _y(label) < 0.065
                        and _text(w) in {"KALYAN", "NIDHI"}
                    ),
                    key=_y,
                )
                if [_text(w) for w in wrapped] == ["KALYAN", "NIDHI"]:
                    head = "RP KALYAN NIDHI"
                    fragments += wrapped
                    consumed_labels.update(id(w) for w in wrapped)
            candidates = [
                w
                for w in lane
                if label["box"][2] <= w["box"][0]
                and abs(_y(w) - _y(label)) < 0.013
                and _money(w["text"]) is not None
            ]
            candidates.sort(key=lambda w: (abs(_y(w) - _y(label)), w["box"][0]))
            if not candidates:
                issues.append("Unreadable deduction amount for " + head)
                evidence.extend(_evidence(w, page) for w in fragments)
                continue
            value = candidates[0]
            key = (tuple(value["box"]), value["text"])
            if key in used or (
                len(candidates) > 1
                and abs(abs(_y(candidates[1]) - _y(label)) - abs(_y(value) - _y(label)))
                < 0.003
            ):
                issues.append("Ambiguous deduction amount for " + head)
                continue
            used.add(key)
            evidence.extend(_evidence(w, page) for w in fragments + [value])
            issues.extend(_recognition_flags(fragments + [value]))
            if head in result:
                issues.append("Repeated deduction " + head)
            else:
                result[head] = _money(value["text"])
    for word in region:
        if (
            _critical_kind(word) == "money"
            and (tuple(word["box"]), word["text"]) not in used
        ):
            issues.append("Unassigned deduction amount " + word["text"])
            evidence.append(_evidence(word, page))
    return result, evidence, issues


def _fiscal_year(text):
    match = re.fullmatch(r"(20\d{2})-(\d{2})", text)
    if match and (int(match[1]) + 1) % 100 == int(match[2]):
        return text
    return None


def _page_key(words):
    fy = next(
        (_text(w) for w in words if _reliable(w) and _fiscal_year(_text(w))),
        "",
    )
    group = next(
        (_text(w) for w in words if _reliable(w) and _text(w).startswith("GROUPNAME:")),
        "",
    )
    return fy, group


def _printed_page_number(words):
    values = set()
    for label in words:
        if label["box"][1] >= 0.2 or not _reliable(label):
            continue
        text = _text(label)
        combined = re.fullmatch(r"PAGE(?:NO)?[.:]*(\d{1,3})", text)
        if combined:
            values.add(int(combined[1]))
        elif re.fullmatch(r"PAGE(?:NO)?[.:]*", text):
            for value in words:
                if (
                    _reliable(value)
                    and re.fullmatch(r"\d{1,3}", value["text"])
                    and 0 <= value["box"][0] - label["box"][2] < 0.1
                    and abs(_y(value) - _y(label)) < 0.018
                ):
                    values.add(int(value["text"]))
    return next(iter(values)) if len(values) == 1 else None


def _printed_total(words, gross, geometry, name, page):
    """Read an optional printed total at the gross baseline, retaining failure."""
    if geometry is None:
        return None, [], []
    left, right = geometry
    candidates = [
        w
        for w in words
        if left <= w["box"][0] < right
        and abs(_y(w) - _y(gross)) < 0.015
        and _money(w["text"]) is not None
    ]
    if len(candidates) != 1:
        return None, [], ["Printed " + name + " unreadable or ambiguous"]
    value = candidates[0]
    return _money(value["text"]), [_evidence(value, page)], _recognition_flags([value])


def facts_from_pages(pages):
    """Build facts from word boxes, keeping document and employee boundaries."""
    bills = []
    salary_bills = []
    orders = []
    issues = []
    layout = None
    payment_layout = (None, None)
    deduction_layout = None
    previous = None
    classifications = []
    for page in pages:
        words = page["words"]
        number = page["page"]
        compact = " ".join(_text(w) for w in words)
        classification = _classify_page(words)
        classifications.append(dict(page=number, kind=classification))
        if classification == "salary_slip":
            from .salary_slip import salary_slip_fact

            bill, flags = salary_slip_fact(words, number)
            salary_bills.append(bill)
            if flags:
                issues.append(
                    dict(
                        kind="bill_unresolved",
                        blocking=True,
                        scope="bill",
                        bill_no=bill["bill_no"],
                        source_pages=[number],
                        employee_code=bill["employee_code"],
                        pay_month=bill["pay_month"],
                        issues=flags,
                    )
                )
            previous = None
            continue
        if classification == "unclassified":
            issues.append(
                dict(
                    page=number,
                    kind="unsupported_page",
                    scope="document",
                    blocking=True,
                    issue="Unclassified nonblank page; financial instructions and adjustments require resolution",
                    source_pages=[number],
                    evidence=[_evidence(w, number) for w in words],
                )
            )
        header_end = max(
            (w["box"][1] for w in words if _text(w).strip("-—–_=.") == "ALLOWANCES"),
            default=0.23,
        )
        header_identities = [
            w for w in words if w["box"][1] < header_end and ID.fullmatch(_text(w))
        ]
        employee = _identity(header_identities)
        profile_header = any(
            w["box"][1] < 0.23 and _text(w).startswith(("EMPLOYEE", "EMPLOVEE"))
            for w in words
        )
        printed_page = _printed_page_number(words)
        ga55 = "GA55" in compact or ("ALLOWANCES" in compact and "GROSS" in compact)
        if ga55:
            allowance = next(
                (w for w in words if _text(w).strip("-—–_=.") == "ALLOWANCES"), None
            )
            gross_header = next((w for w in words if _text(w) == "GROSS"), None)
            if allowance and gross_header:
                net_header = next(
                    (
                        w
                        for w in words
                        if _text(w) == "NET" and abs(_y(w) - _y(gross_header)) < 0.04
                    ),
                    None,
                )
                deduction_header = next(
                    (
                        w
                        for w in words
                        if (
                            _text(w) == "TOTAL"
                            or _text(w).startswith("TOTALDEDUCTIONS")
                        )
                        and abs(_y(w) - _y(gross_header)) < 0.04
                        and w["box"][0] > gross_header["box"][0]
                        and (not net_header or w["box"][0] < net_header["box"][0])
                    ),
                    None,
                )
                if deduction_header or net_header:
                    payment_layout = (
                        (
                            (
                                deduction_header["box"][0] - 0.025,
                                (
                                    net_header["box"][0] - 0.025
                                    if net_header
                                    else deduction_header["box"][2] + 0.05
                                ),
                            )
                            if deduction_header
                            else None
                        ),
                        (net_header["box"][0] - 0.025, 1) if net_header else None,
                    )
                section_header = next(
                    (
                        w
                        for w in words
                        if _text(w).strip("-—–_=.") == "DEDUCTIONS"
                        and gross_header["box"][2] < w["box"][0]
                        and (
                            not deduction_header
                            or w["box"][0] < deduction_header["box"][0] - 0.03
                        )
                        and abs(_y(w) - _y(gross_header)) < 0.05
                    ),
                    None,
                )
                if section_header and deduction_header:
                    deduction_layout = (
                        gross_header["box"][2] + 0.008,
                        deduction_header["box"][0] - 0.008,
                    )
                # Two label/value lanes; discover label starts from observed heads.
                labels = sorted(
                    w["box"][0]
                    for w in words
                    if _head(w)
                    and gross_header["box"][0] / 2
                    < w["box"][0]
                    < gross_header["box"][0]
                    and w["box"][1] > 0.25
                )
                if labels:
                    layout = (
                        min(labels) - 0.005,
                        gross_header["box"][0] - 0.005,
                        gross_header["box"][0],
                        gross_header["box"][2] + 0.025,
                    )
            if not layout:
                issues.append(
                    {
                        "page": number,
                        "issue": "Allowance column geometry unresolved",
                        "kind": "layout_unresolved",
                        "blocking": True,
                        "scope": "document",
                    }
                )
                # Preserve visible source rows when column labels cannot be read.
                # These are review candidates only: no totals or money are assigned.
                row_numbers = [
                    w
                    for w in words
                    if re.fullmatch(r"\d{9}", w["text"])
                    and 0.12 < w["box"][0] < 0.30
                    and w["box"][1] > header_end
                ]
                for candidate in row_numbers:
                    raw = [
                        _evidence(w, number)
                        for w in words
                        if abs(_y(w) - _y(candidate)) < 0.02
                    ]
                    salary_bills.append(
                        dict(
                            employee_code=employee,
                            pay_month="",
                            bill_no=candidate["text"],
                            bill_type="",
                            bill_type_reliable=False,
                            identity_reliable=False,
                            period_reliable=False,
                            allowances={},
                            deductions={},
                            printed_gross=None,
                            printed_deductions=None,
                            printed_net=None,
                            complete=False,
                            allowances_complete=False,
                            deductions_complete=False,
                            deductions_reconciled=None,
                            net_reconciled=None,
                            evidence=raw,
                            raw_fields=raw,
                            source_pages=[number],
                            source_subtype="ga55",
                            issues=["Allowance column geometry unresolved"],
                        )
                    )
                previous = None
                continue
            left, right, gx1, gx2 = layout
            summary_start = min(
                (_y(w) for w in words if _text(w).startswith("TOTALALLOWANCES")),
                default=0.93,
            )
            totals = [
                w
                for w in words
                if gx1 - 0.012 <= w["box"][0] <= gx2
                and _money(w["text"]) is not None
                and w["box"][1] > 0.12
            ]
            totals.sort(key=_y)
            # Annual totals are outside the gross lane and must not become bills.
            continuation_end = _y(totals[0]) - 0.025 if totals else summary_start
            carry_words = [
                w
                for w in words
                if _head(w)
                and left <= w["box"][0] < right
                and 0.12 < _y(w) < continuation_end
            ]
            carry_deductions, carry_ev, carry_flags = _deduction_heads(
                words, number, 0.12, continuation_end, deduction_layout
            )
            if previous and (carry_words or carry_ev or carry_flags):
                same_identity = bool(
                    employee
                    and all(_reliable(w) for w in header_identities)
                    and employee == previous["employee_code"]
                    and number == previous["source_pages"][-1] + 1
                )
                # Some printed continuations omit the identity: require adjacent pages,
                # matching fiscal year/group footer, and no replacement identity.
                key = _page_key(words)
                same_document = (
                    not header_identities
                    and not profile_header
                    and previous.get("identity_reliable") is True
                    and all(key)
                    and key == previous.get("_page_key")
                    and number == previous["source_pages"][-1] + 1
                )
                if same_identity or same_document:
                    heads, ev, flags = _heads(
                        words, number, 0.12, continuation_end, left, right
                    )
                    if set(heads) & set(previous["allowances"]):
                        previous["_issues"].append("Repeated heads in continuation")
                        previous["_allowance_flags"].append(
                            "Repeated heads in continuation"
                        )
                    else:
                        previous["allowances"].update(heads)
                        previous["evidence"].extend(ev)
                        previous["_issues"].extend(flags)
                        previous["_allowance_flags"].extend(flags)
                        previous["source_pages"].append(number)
                    for head, value in carry_deductions.items():
                        if head in previous["deductions"]:
                            previous["_deduction_flags"].append(
                                "Repeated deduction " + head + " in continuation"
                            )
                        else:
                            previous["deductions"][head] = value
                    previous["deduction_evidence"].extend(carry_ev)
                    previous["evidence"].extend(carry_ev)
                    previous["_deduction_flags"].extend(carry_flags)
                    if number not in previous["source_pages"]:
                        previous["source_pages"].append(number)
                else:
                    issues.append(
                        {
                            "page": number,
                            "issue": "Continuation identity unresolved",
                            "kind": "continuation_unresolved",
                            "blocking": True,
                            "scope": "document",
                        }
                    )
            inherited_employee = employee
            identity_evidence = [
                _evidence(w, number) for w in header_identities if _text(w) == employee
            ]
            if (
                not header_identities
                and not profile_header
                and previous
                and previous.get("identity_reliable") is True
                and _page_key(words) == previous.get("_page_key")
                and all(_page_key(words))
                and (
                    number == previous["source_pages"][-1]
                    or (
                        number == previous["source_pages"][-1] + 1
                        and printed_page is not None
                        and previous.get("_printed_page") is not None
                        and printed_page == previous["_printed_page"] + 1
                    )
                )
            ):
                inherited_employee = previous["employee_code"]
                identity_evidence = [
                    e
                    for e in previous["evidence"]
                    if ID.fullmatch(_text(e)) and _text(e) == inherited_employee
                ]
            for index, gross in enumerate(totals):
                start = _y(gross) - 0.025
                end = (
                    _y(totals[index + 1]) - 0.025
                    if index + 1 < len(totals)
                    else summary_start
                )
                region = [w for w in words if start <= _y(w) < end]
                months = [
                    w for w in region if w["box"][0] < left and w["text"] in MONTHS
                ]
                # OCR can lose one month spelling; preserve bill with unknown month.
                bill_words = [
                    w
                    for w in region
                    if 0.12 < w["box"][0] < left and re.fullmatch(r"\d{9}", w["text"])
                ]
                if not months and not bill_words:
                    continue
                month = months[0] if len(months) == 1 else None
                years = [
                    w
                    for w in region
                    if w["box"][0] < 0.12 and re.fullmatch(r"20\d{2}", w["text"])
                ]
                pay_month = (
                    f"{years[0]['text']}-{MONTHS.index(month['text'])+1:02d}"
                    if month and len(years) == 1
                    else ""
                )
                heads, ev, flags = _heads(words, number, start, end, left, right)
                flags.extend(
                    _recognition_flags(
                        identity_evidence
                        + [gross]
                        + ([month] if month else [])
                        + bill_words
                        + years
                    )
                )
                allowance_flags = list(flags)
                deduction_heads, deduction_ev, deduction_flags = _deduction_heads(
                    words, number, start, end, deduction_layout
                )
                deductions, deductions_ev, deductions_flags = _printed_total(
                    words, gross, payment_layout[0], "deductions", number
                )
                net, net_ev, net_flags = _printed_total(
                    words, gross, payment_layout[1], "net", number
                )
                flags.extend(deductions_flags + net_flags)
                net_reconciled = None
                if any(payment_layout):
                    net_reconciled = bool(
                        deductions is not None
                        and net is not None
                        and not deductions_flags
                        and not net_flags
                        and Decimal(_money(gross["text"])) - Decimal(deductions)
                        == Decimal(net)
                    )
                    if not net_reconciled:
                        flags.append(
                            "Printed gross, deductions and net do not reconcile"
                        )
                type_labels = [
                    w
                    for w in region
                    if 0.10 < w["box"][0] < 0.16 and not re.fullmatch(r"\d+", w["text"])
                ]
                flags.extend(_recognition_flags(type_labels))
                if not type_labels:
                    flags.append("Bill type unresolved")
                kind = " ".join(w["text"] for w in type_labels)
                if re.search(r"regul", kind, re.I):
                    kind = "Regular Salary"
                bill = dict(
                    employee_code=inherited_employee,
                    pay_month=pay_month,
                    identity_reliable=bool(
                        inherited_employee
                        and identity_evidence
                        and all(_reliable(w) for w in identity_evidence)
                    ),
                    period_reliable=bool(
                        pay_month
                        and month
                        and len(years) == 1
                        and all(_reliable(w) for w in [month] + years)
                    ),
                    bill_no=bill_words[0]["text"] if len(bill_words) == 1 else "",
                    bill_type=kind,
                    bill_type_reliable=bool(
                        type_labels and all(_reliable(w) for w in type_labels)
                    ),
                    allowances=heads,
                    deductions=deduction_heads,
                    deduction_evidence=deduction_ev,
                    _deduction_flags=deduction_flags + deductions_flags,
                    _deduction_layout=deduction_layout is not None,
                    printed_gross=_money(gross["text"]),
                    printed_deductions=deductions,
                    printed_net=net,
                    net_reconciled=net_reconciled,
                    allowances_complete=False,
                    complete=False,
                    source_pages=[number],
                    evidence=ev
                    + deduction_ev
                    + deductions_ev
                    + net_ev
                    + [_evidence(gross, number)]
                    + identity_evidence
                    + [_evidence(w, number) for w in type_labels]
                    + [
                        _evidence(w, number)
                        for w in ([month] if month else [])
                        + bill_words
                        + years
                        + [
                            w
                            for w in words
                            if ID.fullmatch(_text(w)) and _text(w) == inherited_employee
                        ]
                    ],
                    _issues=flags,
                    _allowance_flags=allowance_flags,
                    _page_key=_page_key(words),
                    _printed_page=printed_page,
                )
                bills.append(bill)
                previous = bill
            # An unreadable gross must not erase a visible month/bill row.
            covered = {
                (e["text"], tuple(e["box"]))
                for bill in bills
                for e in bill["evidence"]
                if e.get("page") == number and e.get("box")
            }
            unseen = [
                w
                for w in words
                if (0.23 if profile_header else 0.12) < _y(w) < summary_start
                and (
                    (w["text"] in MONTHS and w["box"][0] < min(0.12, left))
                    or (re.fullmatch(r"\d{9}", w["text"]) and 0.12 < w["box"][0] < left)
                )
                and (w["text"], tuple(w["box"])) not in covered
            ]
            if unseen:
                issues.append(
                    dict(
                        page=number,
                        kind="bill_row_unresolved",
                        scope="document",
                        blocking=True,
                        issue="Visible month/bill rows were not fully represented in extracted records",
                        evidence=[_evidence(w, number) for w in unseen],
                    )
                )
        else:
            previous = None
            if "HOUSE" not in compact or "RENT" not in compact:
                continue
            identities = [w for w in words if ID.fullmatch(_text(w))]
            date_words = []
            rate_words = []
            for q in words:
                m = re.fullmatch(r"(\d{2})[./:](\d{2})[./:](\d{4})", q["text"].strip())
                if m:
                    try:
                        date_words.append(
                            (date(int(m[3]), int(m[2]), int(m[1])).isoformat(), q)
                        )
                    except ValueError:
                        pass
                m = re.fullmatch(r"(\d{1,2})\s*%", q["text"].strip())
                if m:
                    rate_words.append((m[1], q))
            # Fit the common row slope from dated rows. Dates are to the right
            # of IDs; project both dates and rates back to the identity column.
            slopes = []
            for _, q in date_words:
                possible = [
                    w
                    for w in identities
                    if q["box"][0] > w["box"][2] and abs(_y(q) - _y(w)) < 0.02
                ]
                if possible:
                    nearest = min(possible, key=lambda w: abs(_y(q) - _y(w)))
                    slopes.append(
                        (_y(q) - _y(nearest)) / (q["box"][0] - nearest["box"][0])
                    )
            slope = median(slopes) if slopes else 0
            assigned_dates = {}
            assigned_rates = {}
            for candidates, assigned in [
                (date_words, assigned_dates),
                (rate_words, assigned_rates),
            ]:
                for value, q in candidates:
                    possible = [w for w in identities if q["box"][0] > w["box"][2]]
                    if not possible:
                        continue
                    distances = sorted(
                        (abs(_y(q) - slope * (q["box"][0] - w["box"][0]) - _y(w)), i)
                        for i, w in enumerate(possible)
                    )
                    if distances[0][0] < 0.012 and (
                        len(distances) == 1 or distances[1][0] - distances[0][0] > 0.003
                    ):
                        assigned.setdefault(id(possible[distances[0][1]]), []).append(
                            (value, q)
                        )
            for w in identities:
                dates = assigned_dates.get(id(w), [])
                rates = assigned_rates.get(id(w), [])
                unresolved_fields = []
                if not _reliable(w):
                    unresolved_fields.append("employee_code")
                if len(dates) != 1 or not all(_reliable(d[1]) for d in dates):
                    unresolved_fields.append("effective_from")
                if len(rates) != 1 or not all(_reliable(r[1]) for r in rates):
                    unresolved_fields.append("rate")
                rate_x = (
                    median(q[1]["box"][0] for q in rate_words) if rate_words else None
                )
                unreadable_rates = [
                    q
                    for q in words
                    if rate_x is not None
                    and abs(q["box"][0] - rate_x) < 0.025
                    and abs(_y(q) - slope * (q["box"][0] - w["box"][0]) - _y(w)) < 0.012
                    and q not in [r[1] for r in rates]
                ]
                if (
                    len(dates) == 1
                    and len(rates) == 1
                    and all(_reliable(q) for q in [w, dates[0][1], rates[0][1]])
                ):
                    orders.append(
                        dict(
                            employee_code=_text(w),
                            effective_from=dates[0][0],
                            rate=rates[0][0],
                            allowance="HRA",
                            source_pages=[number],
                            evidence=[
                                _evidence(q, number)
                                for q in [w, dates[0][1], rates[0][1]]
                            ],
                        )
                    )
                else:
                    issues.append(
                        {
                            "page": number,
                            "employee_code": _text(w),
                            "issue": "Employee order date/rate unresolved",
                            "kind": "order_unresolved",
                            "allowance": "HRA",
                            "scope": "employee",
                            "blocking": True,
                            "unresolved_fields": unresolved_fields,
                            "evidence": [
                                _evidence(q, number)
                                for q in [w]
                                + unreadable_rates
                                + [d[1] for d in dates]
                                + [r[1] for r in rates]
                            ],
                        }
                    )
    for bill in bills:
        flags = bill.pop("_issues")
        allowance_flags = bill.pop("_allowance_flags")
        deduction_flags = bill.pop("_deduction_flags")
        has_deduction_layout = bill.pop("_deduction_layout")
        printed_deductions = bill["printed_deductions"]
        bill["deductions_reconciled"] = (
            sum(map(Decimal, bill["deductions"].values()), Decimal(0))
            == Decimal(printed_deductions)
            if printed_deductions is not None and bill["deductions"]
            else None
        )
        bill["deductions_complete"] = bool(
            has_deduction_layout
            and bill["deductions_reconciled"]
            and not deduction_flags
        )
        if has_deduction_layout:
            flags.extend(deduction_flags)
            if not bill["deductions_reconciled"]:
                flags.append("Deduction heads do not reconcile to printed deductions")
        bill.pop("_page_key", None)
        bill.pop("_printed_page", None)
        reconciled = sum(
            map(Decimal, bill["allowances"].values()), Decimal(0)
        ) == Decimal(bill["printed_gross"])
        bill["complete"] = bool(
            reconciled
            and not flags
            and bill["employee_code"]
            and bill["pay_month"]
            and bill["bill_no"]
        )
        bill["allowances_complete"] = bool(
            reconciled
            and not allowance_flags
            and bill["employee_code"]
            and bill["pay_month"]
            and bill["bill_no"]
        )
        if not reconciled:
            flags.append("Allowance heads do not reconcile to printed gross")
        if not bill["employee_code"]:
            flags.append("Employee identity unresolved")
        if not bill["pay_month"]:
            flags.append("Pay month unresolved")
        if not bill["bill_no"]:
            flags.append("Bill number unresolved")
        if flags:
            issues.append(
                {
                    "bill_no": bill["bill_no"],
                    "source_pages": bill["source_pages"],
                    "issues": flags,
                    "kind": "bill_unresolved",
                    "scope": "bill",
                    "blocking": True,
                    "employee_code": bill["employee_code"],
                    "pay_month": bill["pay_month"],
                }
            )
    from .pay_orders import extract_pay_orders, extract_order_candidates

    return dict(
        bills=bills + salary_bills,
        orders=orders,
        issues=issues,
        page_classifications=classifications,
        pay_orders=extract_pay_orders(pages),
        order_candidates=extract_order_candidates(pages),
    )


def _tesseract_words(image, executable, env, psm=3):
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    result = subprocess.run(
        [
            executable,
            "stdin",
            "stdout",
            "-l",
            "eng",
            "--psm",
            str(psm),
            "-c",
            "tessedit_create_tsv=1",
        ],
        input=encoded.getvalue(),
        capture_output=True,
        env=dict(env, OMP_THREAD_LIMIT="1"),
        timeout=90,
    )
    if result.returncode:
        raise ValueError("Printed OCR failed")
    rows = csv.DictReader(
        io.StringIO(result.stdout.decode("utf-8")),
        delimiter="\t",
        quoting=csv.QUOTE_NONE,
    )
    words = []
    for r in rows:
        if not r.get("text", "").strip():
            continue
        x, y, width, height = [
            int(r[key]) for key in ("left", "top", "width", "height")
        ]
        words.append(
            dict(
                text=r["text"].strip(),
                box=[
                    x / image.width,
                    y / image.height,
                    (x + width) / image.width,
                    (y + height) / image.height,
                ],
                confidence=float(r["conf"]) / 100,
                recognizer="tesseract",
            )
        )
    return words


def _overlaps(a, b):
    ax, ay, bx, by = a["box"]
    cx, cy, dx, dy = b["box"]
    area = max(0, min(bx, dx) - max(ax, cx)) * max(0, min(by, dy) - max(ay, cy))
    return area > min((bx - ax) * (by - ay), (dx - cx) * (dy - cy)) * 0.35


def _critical_kind(word, is_order=False, rate_x=None):
    text = word["text"]
    if _money(text) is not None or (
        re.fullmatch(r"[+-]?[0-9OoIlLSB?,.:]+", text)
        and re.search(r"[.,:]\d{2}$", text)
        and any(c.isdigit() for c in text)
    ):
        return "money"
    if re.fullmatch(r"20\d{2}-\d{2}", _text(word)):
        return "fiscal_year"
    if ID.fullmatch(_text(word)) or re.fullmatch(r"[A-Z]{2,5}\d{10,13}", _text(word)):
        return "identity"
    if text in MONTHS:
        return "month"
    if _head(word):
        return "head"
    if re.fullmatch(r"20\d{2}", text) and word["box"][0] < 0.12:
        return "year"
    if re.fullmatch(r"\d{9}", text):
        return "bill"
    if is_order and re.fullmatch(r"\d{2}[./:]\d{2}[./:]\d{4}", text):
        return "date"
    if is_order and (
        re.fullmatch(r"\d{1,2}%", _text(word))
        or (
            rate_x is not None
            and abs(word["box"][0] - rate_x) < 0.025
            and re.search(r"\d", text)
        )
    ):
        return "rate"
    return None


def _candidate_value(word, kind):
    text = word["text"].strip()
    if kind == "money":
        return _money(text)
    if kind == "fiscal_year":
        return _fiscal_year(_text(word))
    if kind == "identity":
        return _text(word) if ID.fullmatch(_text(word)) else None
    if kind == "month":
        return text if text in MONTHS else None
    if kind == "head":
        return _head(word)
    if kind == "year":
        return text if re.fullmatch(r"20\d{2}", text) else None
    if kind == "bill":
        return text if re.fullmatch(r"\d{9}", text) else None
    if kind == "rate":
        return _text(word) if re.fullmatch(r"\d{1,2}%", _text(word)) else None
    if kind == "date":
        m = re.fullmatch(r"(\d{2})[./:](\d{2})[./:](\d{4})", text)
        if m:
            try:
                return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
            except ValueError:
                pass
    return None


def _candidate_copy(word):
    return {
        k: v
        for k, v in word.items()
        if k
        in (
            "text",
            "box",
            "confidence",
            "recognizer",
            "crop_box",
            "crop_dpi",
            "preprocessing",
        )
    }


def _merge_candidates(primary, others, kind):
    candidates = primary.setdefault(
        "recognition_candidates", [_candidate_copy(primary)]
    )
    for q in others:
        item = _candidate_copy(q)
        if item not in candidates:
            candidates.append(item)
    trusted = {
        _candidate_value(q, kind)
        for q in candidates
        if _reliable(q) and _candidate_value(q, kind) is not None
    }
    primary["recognition_conflict"] = len(trusted) > 1


def _resolve_crop_candidates(word, crops, kind):
    word.setdefault("recognition_candidates", [_candidate_copy(word)])
    word["recognition_candidates"].extend(_candidate_copy(q) for q in crops)
    reliable = [
        q for q in crops if _reliable(q) and _candidate_value(q, kind) is not None
    ]
    values = {_candidate_value(q, kind) for q in reliable}
    if len(values) > 1:
        word["recognition_conflict"] = True
        return
    if len(values) != 1:
        return
    value = next(iter(values))
    originals = {
        _candidate_value(q, kind)
        for q in word["recognition_candidates"]
        if not q.get("recognizer", "").endswith("-crop")
        and _candidate_value(q, kind) is not None
    }
    if word.get("recognition_conflict") and value not in originals:
        return
    chosen = max(reliable, key=lambda q: q["confidence"])
    if word.get("recognition_conflict"):
        word["conflict_resolved_by"] = [_candidate_copy(q) for q in reliable]
    word.setdefault("original_text", word["text"])
    word.update(
        text=chosen["text"],
        confidence=chosen["confidence"],
        recognizer=chosen["recognizer"],
        recognition_conflict=False,
    )


def _crop_candidates(page, word, recognizer, runtime, images=None):
    """Fixed crops at two source resolutions; no total or answer feedback."""
    from PIL import Image, ImageOps

    images = images if images is not None else {}
    candidates = []
    x1, y1, x2, y2 = word["box"]
    for dpi, scale, preprocessing in [
        (200, 3, "gray autocontrast"),
        (300, 2, "gray autocontrast"),
    ]:
        if dpi not in images:
            pix = page.get_pixmap(dpi=dpi)
            images[dpi] = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        image = images[dpi]
        box = [
            max(0, x1 * image.width - 4),
            max(0, y1 * image.height - 4),
            min(image.width, x2 * image.width + 4),
            min(image.height, y2 * image.height + 4),
        ]
        original = image.crop(box)
        gray = ImageOps.autocontrast(
            ImageOps.grayscale(
                original.resize((original.width * scale, original.height * scale))
            )
        )
        metadata = dict(
            crop_box=box,
            crop_dpi=dpi,
            crop_coordinate_space="rendered pixels",
            preprocessing=preprocessing + "; scale " + str(scale),
        )
        if runtime:
            recognized = _tesseract_words(gray, *runtime[:2], psm=7)
            candidates.append(
                dict(
                    text="".join(q["text"] for q in recognized),
                    confidence=min((q["confidence"] for q in recognized), default=0),
                    recognizer="tesseract-crop",
                    **metadata,
                )
            )
        if recognizer:
            # The neural recognizer receives source RGB at200dpi and the
            # prepared crop at300dpi, independent of Tesseract recognition.
            neural = original if dpi == 200 else gray
            encoded = io.BytesIO()
            neural.save(encoded, format="PNG")
            raw, _ = recognizer(encoded.getvalue(), use_det=False, use_cls=False)
            if raw and len(raw) == 1:
                candidates.append(
                    dict(
                        text=raw[0][0],
                        confidence=float(raw[0][1]),
                        recognizer="rapidocr-crop",
                        **dict(
                            metadata,
                            preprocessing=(
                                "source RGB"
                                if dpi == 200
                                else metadata["preprocessing"]
                            ),
                        ),
                    )
                )
    return candidates


def _recognize_page(page, recognizer, runtime):
    from PIL import Image

    pix = page.get_pixmap(dpi=200)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    words = []
    if recognizer:
        raw, _ = recognizer(pix.tobytes("png"))
        for polygon, text, confidence in raw or []:
            words.append(
                dict(
                    text=text,
                    confidence=float(confidence),
                    box=[
                        min(v[0] for v in polygon) / pix.width,
                        min(v[1] for v in polygon) / pix.height,
                        max(v[0] for v in polygon) / pix.width,
                        max(v[1] for v in polygon) / pix.height,
                    ],
                    recognizer="rapidocr",
                )
            )
    # A printed GA55 embedded low on a scanned sheet needs source resolution
    # appropriate to its own block. The title and observed text bound the crop;
    # no amounts, totals or reconciliation results select the recognition area.
    titles = [
        w for w in words if _text(w) == "GA55A" and _reliable(w) and w["box"][1] > 0.23
    ]
    source_block = None
    outside_words = []
    initial_block_words = []
    if len(titles) == 1:
        top = max(0, titles[0]["box"][1] - 0.025)
        bottom = min(1, max(w["box"][3] for w in words if w["box"][1] >= top) + 0.025)
        if bottom - top < 0.65:
            import pymupdf

            source_block = [0, top, 1, bottom]
            outside_words = [
                w for w in words if w["box"][3] < top or w["box"][1] > bottom
            ]
            initial_block_words = [w for w in words if w not in outside_words]
            clip = pymupdf.Rect(
                0, top * page.rect.height, page.rect.width, bottom * page.rect.height
            )
            pix = page.get_pixmap(dpi=350, clip=clip)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            raw, _ = recognizer(pix.tobytes("png"))
            words = [
                dict(
                    text=text,
                    confidence=float(confidence),
                    box=[
                        min(v[0] for v in polygon) / pix.width,
                        top + min(v[1] for v in polygon) / pix.height * (bottom - top),
                        max(v[0] for v in polygon) / pix.width,
                        top + max(v[1] for v in polygon) / pix.height * (bottom - top),
                    ],
                    recognizer="rapidocr",
                    source_block_box=source_block,
                    source_block_dpi=350,
                )
                for polygon, text, confidence in raw or []
            ]
            for original in initial_block_words:
                kind = _critical_kind(original)
                if not kind:
                    continue
                overlapping = [
                    w
                    for w in words
                    if _overlaps(original, w) and _critical_kind(w) == kind
                ]
                if overlapping:
                    # Enlargement is another reading of the same source, not
                    # authority to discard a reliable conflicting original.
                    for enlarged in overlapping:
                        _merge_candidates(enlarged, [original], kind)
                else:
                    words.append(original)
    secondary = _tesseract_words(image, *runtime[:2]) if runtime else []
    if source_block:
        for word in secondary:
            word["box"][1] = source_block[1] + word["box"][1] * (
                source_block[3] - source_block[1]
            )
            word["box"][3] = source_block[1] + word["box"][3] * (
                source_block[3] - source_block[1]
            )
            word.update(source_block_box=source_block, source_block_dpi=350)
    if not words:
        words = secondary
    compact = " ".join(_text(w) for w in words)
    is_order = "HOUSE" in compact and "RENT" in compact
    rates = [w["box"][0] for w in words if re.fullmatch(r"\d{1,2}%", _text(w))]
    rate_x = median(rates) if is_order and rates else None
    if recognizer and secondary:
        for candidate in secondary:
            kind = _critical_kind(candidate, is_order, rate_x)
            if not kind:
                # Preserve a trusted independent reading of missing structural
                # labels. Never turn a neural typo into a corrected number.
                label = _text(candidate).strip("-—–_=.")
                if (
                    label in {"ALLOWANCES", "GROSS", "NET"}
                    and candidate["box"][1] < 0.4
                    and _reliable(candidate)
                    and not any(_text(q).strip("-—–_=.") == label for q in words)
                ):
                    words.append(candidate)
                continue
            overlapping = [
                q
                for q in words
                if _overlaps(candidate, q)
                and _critical_kind(q, is_order, rate_x) == kind
            ]
            if overlapping:
                primary = max(
                    overlapping,
                    key=lambda q: min(q["box"][2], candidate["box"][2])
                    - max(q["box"][0], candidate["box"][0]),
                )
                _merge_candidates(primary, [candidate], kind)
            elif kind in ("head", "month", "identity"):
                words.append(candidate)
    images = {} if source_block else {200: image}
    for word in words:
        kind = _critical_kind(word, is_order, rate_x)
        if kind and (_candidate_value(word, kind) is None or not _reliable(word)):
            _resolve_crop_candidates(
                word, _crop_candidates(page, word, recognizer, runtime, images), kind
            )
    return outside_words + words


def extract_document_facts(pdf_bytes):
    """Recognize original PDF bytes locally and retain unresolved source facts."""
    import pymupdf
    from .documents import page_needs_ocr, ocr_runtime

    recognizer = None
    runtime = None
    recognition_issues = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        if len(document) > 200:
            raise ValueError("Split jobs into documents of at most 200 pages")
        if any(page_needs_ocr(page) for page in document):
            try:
                import onnxruntime

                onnxruntime.disable_telemetry_events()
                from rapidocr_onnxruntime import RapidOCR

                recognizer = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
            except Exception as error:
                recognition_issues.append(
                    {
                        "issue": f"Independent printed recognizer unavailable ({type(error).__name__}); using Tesseract",
                        "kind": "recognizer_unavailable",
                        "blocking": False,
                    }
                )
            try:
                runtime = ocr_runtime()
            except ValueError:
                recognition_issues.append(
                    {
                        "issue": "Tesseract unavailable for independent recognition",
                        "kind": "recognizer_unavailable",
                        "blocking": False,
                    }
                )
        pages = []
        failed_pages = []
        recognizers = set()
        for number, page in enumerate(document, 1):
            if page_needs_ocr(page):
                if not recognizer and not runtime:
                    failed_pages.append(dict(page=number, kind="unreadable"))
                    recognition_issues.append(
                        {
                            "page": number,
                            "issue": "No printed recognizer available",
                            "kind": "page_recognition",
                            "scope": "document",
                            "blocking": True,
                        }
                    )
                    continue
                try:
                    words = _recognize_page(page, recognizer, runtime)
                    if not words:
                        raise ValueError("No usable recognized words")
                except Exception as error:
                    failed_pages.append(dict(page=number, kind="unreadable"))
                    recognition_issues.append(
                        {
                            "page": number,
                            "issue": f"Printed page recognition unresolved ({type(error).__name__})",
                            "kind": "page_recognition",
                            "scope": "document",
                            "blocking": True,
                        }
                    )
                    continue
            else:
                words = [
                    dict(
                        text=w[4],
                        box=[
                            w[0] / page.rect.width,
                            w[1] / page.rect.height,
                            w[2] / page.rect.width,
                            w[3] / page.rect.height,
                        ],
                        confidence=1,
                        recognizer="pdf-text",
                    )
                    for w in page.get_text("words")
                ]
            recognizers.update(w.get("recognizer", "unknown") for w in words)
            pages.append(dict(page=number, words=words))
    facts = facts_from_pages(pages)
    facts["page_classifications"] = sorted(
        facts["page_classifications"] + failed_pages, key=lambda q: q["page"]
    )
    facts["issues"].extend(recognition_issues)
    facts["facts_version"] = FACTS_VERSION
    facts["recognizers"] = sorted(recognizers)
    return facts
