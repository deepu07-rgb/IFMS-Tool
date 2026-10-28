"""Read explicitly headed monthly pay slips from source word geometry."""

import re
from decimal import Decimal


def salary_slip_fact(words, page):
    from .document_facts import (
        _text,
        _y,
        _money,
        _reliable,
        _evidence,
        _recognition_flags,
        ID,
        MONTHS,
    )

    flags, evidence = [], []

    def one(candidates, label):
        from .document_facts import _overlaps

        distinct = []
        for candidate in sorted(candidates, key=lambda w: -w.get("confidence", 0)):
            if not any(
                _text(candidate).lstrip(":：") == _text(w).lstrip(":：")
                and _overlaps(candidate, w)
                for w in distinct
            ):
                distinct.append(candidate)
        candidates = distinct
        if len(candidates) != 1:
            flags.append(label + " unresolved or ambiguous")
            return None
        word = candidates[0]
        evidence.append(_evidence(word, page))
        flags.extend(_recognition_flags([word]))
        return word

    def adjacent(label, pattern):
        labels = [w for w in words if re.fullmatch(label, _text(w))]
        anchor = one(labels, label)
        if not anchor:
            return None
        return one(
            [
                w
                for w in words
                if w["box"][0] >= anchor["box"][2]
                and abs(_y(w) - _y(anchor)) < 0.012
                and re.fullmatch(pattern, _text(w).lstrip(":："))
            ],
            label + " value",
        )

    employee_word = adjacent(r"EMPID", r"RJ[A-Z]{2}\d{12}")
    employee = _text(employee_word).lstrip(":：") if employee_word else ""
    # Independent words can overlap the combined recognition of a field; matching
    # literals are one reading, while distinct identity readings remain blocked.
    if employee_word:
        others = [
            w
            for w in words
            if abs(_y(w) - _y(employee_word)) < 0.012
            and w["box"][0] >= employee_word["box"][0] - 0.02
            and w["box"][0] < employee_word["box"][2]
            and _text(w).lstrip(":：").startswith("RJ")
        ]
        if any(_text(w).lstrip(":：") != employee for w in others):
            flags.append("Employee identity recognition disagreement")
    month_word = one(
        [w for w in words if re.fullmatch(r"MONTH[:：][A-Z]+/20\d{2}", _text(w))],
        "Pay month",
    )
    pay_month = ""
    if month_word:
        name, year = re.split("[:：]", _text(month_word))[1].split("/")
        matches = [i for i, m in enumerate(MONTHS, 1) if m.upper() == name]
        if matches:
            pay_month = f"{year}-{matches[0]:02d}"
    bill_word = adjacent(r"BILLNO[.,]*DATE", r"\d{9},\d{2}-\d{2}-20\d{2}")
    bill_no = _text(bill_word).lstrip(":：").split(",")[0] if bill_word else ""
    totals = {}
    for key, label in [
        ("printed_gross", "GROSSPAY"),
        ("printed_deductions", "TOTALDEDUCTIONS"),
        ("printed_net", "NETPAY"),
    ]:
        word = one(
            [
                w
                for w in words
                if re.fullmatch(label + r"[:：](?:₹)?\d[\d,]*\.\d{2}", _text(w))
            ],
            label,
        )
        totals[key] = (
            _money(re.split("[:：]", _text(word))[1].lstrip("₹")) if word else None
        )
    headings = {}
    for key, label in [
        ("earnings", r"EARNINGS\(RS[.]?\)"),
        ("accounting", "ACCOUNTING"),
        ("informational", "NONACCOUNTING"),
    ]:
        headings[key] = one(
            [w for w in words if re.fullmatch(label, _text(w))], key + " heading"
        )
    names = sorted(
        [
            w
            for w in words
            if _text(w) == "NAME"
            and headings["earnings"]
            and _y(w) > _y(headings["earnings"])
        ],
        key=lambda w: w["box"][0],
    )
    if len(names) != 3 or not all(headings.values()):
        flags.append("Component column geometry unresolved")
    allowances, deductions, effects, deduction_evidence = {}, {}, {}, []
    allowance_codes = {
        "100": "Basic",
        "104": "DA",
        "107": "HRA",
        "117": "Mess All",
        "119": "HDA",
        "120": "FTA",
    }
    aliases = {
        "basicpay": "Basic",
        "dearnessallowance": "DA",
        "dearnessallowances": "DA",
        "hra": "HRA",
        "houserentallowance": "HRA",
        "messallowance": "Mess All",
        "harddutyallowance": "HDA",
        "ftallowance": "FTA",
    }
    if len(names) == 3 and all(headings.values()):
        end = min((_y(w) for w in words if _text(w).startswith("GROSSPAY:")), default=1)
        for i, start in enumerate(names):
            right = names[i + 1]["box"][0] if i < 2 else 1
            region = [
                w
                for w in words
                if start["box"][0] - 0.008 <= w["box"][0]
                and w["box"][2] <= right + 0.003
                and _y(start) < _y(w) < end - 0.015
            ]
            labels = [
                w for w in region if re.fullmatch(r".+[（(]\d{3}[)）]", w["text"])
            ]
            used = set()
            for label in labels:
                value = one(
                    [
                        w
                        for w in region
                        if w["box"][0] >= label["box"][2]
                        and abs(_y(w) - _y(label)) < 0.009
                        and _money(w["text"]) is not None
                    ],
                    label["text"] + " amount",
                )
                evidence.append(_evidence(label, page))
                flags.extend(_recognition_flags([label]))
                if not value:
                    continue
                used.add(id(value))
                literal = re.sub(r"[（(]\d{3}[)）]$", "", label["text"]).strip()
                code = re.search(r"[（(](\d{3})[)）]$", label["text"])[1]
                head = (
                    allowance_codes.get(
                        code,
                        aliases.get(re.sub("[^a-z]", "", literal.lower()), literal),
                    )
                    if i == 0
                    else literal
                )
                target = allowances if i == 0 else deductions
                if head in target:
                    flags.append("Repeated component " + head)
                target[head] = _money(value["text"])
                if i:
                    effects[head] = i == 1
                    deduction_evidence.extend(
                        [_evidence(label, page), _evidence(value, page)]
                    )
            for word in region:
                if _money(word["text"]) is not None and id(word) not in used:
                    flags.append("Unassigned component amount " + word["text"])
    allowance_ok = totals["printed_gross"] is not None and sum(
        map(Decimal, allowances.values()), Decimal(0)
    ) == Decimal(totals["printed_gross"])
    deduction_ok = totals["printed_deductions"] is not None and sum(
        (Decimal(v) for k, v in deductions.items() if effects[k]), Decimal(0)
    ) == Decimal(totals["printed_deductions"])
    net_ok = all(v is not None for v in totals.values()) and Decimal(
        totals["printed_gross"]
    ) - Decimal(totals["printed_deductions"]) == Decimal(totals["printed_net"])
    for ok, label in [
        (allowance_ok, "Allowance heads"),
        (deduction_ok, "Accounting deductions"),
        (net_ok, "Printed net"),
    ]:
        if not ok:
            flags.append(label + " do not reconcile")
    complete = bool(
        allowance_ok
        and deduction_ok
        and net_ok
        and employee
        and pay_month
        and bill_no
        and not flags
    )
    bill = dict(
        employee_code=employee,
        pay_month=pay_month,
        bill_no=bill_no,
        bill_type="Regular Salary",
        bill_type_reliable=True,
        identity_reliable=bool(
            employee_word
            and _reliable(employee_word)
            and "Employee identity recognition disagreement" not in flags
        ),
        period_reliable=bool(pay_month and month_word and _reliable(month_word)),
        allowances=allowances,
        deductions=deductions,
        deduction_effects=effects,
        deduction_evidence=deduction_evidence,
        evidence=evidence,
        source_pages=[page],
        complete=complete,
        allowances_complete=complete,
        deductions_complete=bool(deduction_ok and not flags),
        deductions_reconciled=deduction_ok,
        net_reconciled=net_ok,
        source_subtype="salary_slip",
        **totals,
    )
    return bill, flags
