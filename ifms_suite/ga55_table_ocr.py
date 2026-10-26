"""Review-only OCR for the fixed-column Rajasthan GA55 A printed form.

Never repairs monetary digits from expected arrears or a reference statement.
Coordinates and raw OCR evidence stay with every candidate.
"""

import csv
import io
import re
import subprocess
from difflib import SequenceMatcher
from decimal import Decimal
from .documents import MONTHS, ocr_runtime
from .payment_types import classify_bill, entitlement_type


def _ocr(page, box, executable, env, tsv=False):
    import pymupdf

    w, h = page.rect.width, page.rect.height
    clip = pymupdf.Rect(box[0] * w, box[1] * h, box[2] * w, box[3] * h)
    pix = page.get_pixmap(dpi=300, clip=clip)
    cmd = [executable, "stdin", "stdout", "-l", "eng", "--psm", "6"]
    if tsv:
        cmd += ["-c", "tessedit_create_tsv=1"]
    r = subprocess.run(
        cmd, input=pix.tobytes("png"), capture_output=True, env=env, timeout=60
    )
    if r.returncode:
        raise ValueError("Column OCR failed; review the original document")
    return r.stdout.decode("utf-8", errors="replace"), pix.height


def _amount(text):
    text = text.strip()
    # Accept ordinary decimal punctuation only; do not turn letters into money.
    if not re.fullmatch(r"[-+]?(?:\d+|\d{1,3}(?:,\d{3})+)[.,]\d{2}", text):
        return None
    if "." not in text:
        text = text[:-3] + "." + text[-2:]
    try:
        return f"{Decimal(text.replace(',','')):.2f}"
    except Exception:
        return None


def _money_candidate(text):
    value = _amount(text)
    if value is not None:
        return value, False
    corrected = text
    if corrected.startswith("$"):
        corrected = "5" + corrected[1:]
    value = _amount(corrected)
    if value is None and re.fullmatch(r"[+-]?\d{7,}", corrected):
        value = f"{Decimal(corrected)/100:.2f}"
    return value, value is not None


def _heads(text):
    result = {}
    issues = []
    pattern = (
        r"(?i)\b(Basic|Basie|HRA|Mess\s+All|DA|CCA|OCA|HDA|FTA|ROP)\b\s*[:=]?\s*(\S+)"
    )
    aliases = {
        "basie": "Basic",
        "basic": "Basic",
        "hra": "HRA",
        "mess all": "Mess All",
        "da": "DA",
        "cca": "CCA",
        "oca": "CCA",
        "hda": "HDA",
        "fta": "FTA",
        "rop": "ROP",
    }
    for m in re.finditer(pattern, text):
        head = aliases[" ".join(m[1].lower().split())]
        amount, repaired = _money_candidate(m[2])
        if repaired:
            issues.append(
                "Verify OCR monetary correction " + head + ": " + m[2] + " -> " + amount
            )
        if amount is None:
            issues.append("Unreadable " + head + ": " + m[2])
            continue
        if head in result:
            issues.append("Repeated " + head)
            continue
        result[head] = amount
    return result, issues


def select_reconciled_heads(heads, issues, gross):
    repaired = {
        issue.split("correction ", 1)[1].split(":", 1)[0]
        for issue in issues
        if issue.startswith("Verify OCR monetary correction ")
    }
    if gross is not None and sum(Decimal(v) for v in heads.values()) == Decimal(gross):
        return heads, {}
    return {k: v for k, v in heads.items() if k not in repaired}, {
        k: v for k, v in heads.items() if k in repaired
    }


def parse_scanned_ga55_tables(data):
    import pymupdf

    executable, env, languages = ocr_runtime()
    if "eng" not in languages:
        raise ValueError("English OCR model required")
    records = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if len(doc) > 40:
            raise ValueError("Split column OCR into at most40 pages")
        for page in doc:
            title = page.get_text()
            if not re.search(r"(?i)Government\s+Of\s+Rajasthan", title):
                continue
            if not re.search(r"(?i)GA[S5]{2}", title.replace(" ", "")):
                continue
            box = (0.035, 0.12, 0.108, 0.92)
            raw, height = _ocr(page, box, executable, env, True)
            words = list(csv.DictReader(io.StringIO(raw), delimiter="\t"))
            anchors = []
            for index, word in enumerate(words):
                token = re.sub("[^a-z]", "", word.get("text", "").lower())
                if len(token) < 3:
                    continue
                ranked = sorted(
                    (
                        (SequenceMatcher(None, token, m.lower()).ratio(), m)
                        for m in MONTHS
                    ),
                    reverse=True,
                )
                score, month = ranked[0]
                if score < 0.8 or (score != 1 and ranked[1][0] == score):
                    continue
                y = box[1] + (int(word["top"]) + int(word["height"]) / 2) / height * (
                    box[3] - box[1]
                )
                year = ""
                for other in words[index + 1 : index + 8]:
                    if re.fullmatch(r"20\d{2}", other.get("text", "")):
                        oy = box[1] + int(other["top"]) / height * (box[3] - box[1])
                        if 0 <= oy - y < 0.04:
                            year = other["text"]
                            break
                fy = re.search(
                    r"\b(20\d{2})\s*[-–]\s*(?:20)?(\d{2})\b",
                    title,
                    re.I,
                )
                if fy and year and int(year) not in (int(fy[1]), int(fy[1]) + 1):
                    year = ""
                anchors.append((y, month, year, token))
            # A legible bill-type cell must not disappear merely because its month failed OCR.
            for word in page.get_text("words"):
                x, y = (word[0] + word[2]) / 2 / page.rect.width, (
                    word[1] + word[3]
                ) / 2 / page.rect.height
                if (
                    0.108 <= x <= 0.17
                    and 0.12 <= y <= 0.92
                    and word[4].lower() in ("surrender", "regular", "da")
                ):
                    if not any(abs(existing[0] - y) < 0.025 for existing in anchors):
                        anchors.append((y, "Unresolved month", "", "unreadable"))
            anchors.sort(key=lambda row: row[0])
            for i, (y, month, year, token) in enumerate(anchors):
                a = (
                    (anchors[i - 1][0] + y) / 2
                    if i
                    else max(
                        0.12,
                        y
                        - min(
                            0.08, (anchors[1][0] - y) / 2 if len(anchors) > 1 else 0.08
                        ),
                    )
                )
                b = (
                    (y + anchors[i + 1][0]) / 2
                    if i + 1 < len(anchors)
                    else min(
                        0.92, y + min(0.08, (y - anchors[i - 1][0]) / 2 if i else 0.08)
                    )
                )
                evidence = {}
                issues = [
                    "Scanned fixed-column candidate: verify identity, month, bill, digits and totals against source"
                ]
                for name, x1, x2 in [
                    ("left", 0.30, 0.418),
                    ("right", 0.42, 0.545),
                    ("bill", 0.17, 0.25),
                    ("type", 0.11, 0.17),
                    ("gross", 0.55, 0.605),
                ]:
                    evidence[name] = _ocr(page, (x1, a, x2, b), executable, env)[0]
                heads = {}
                for name in ("left", "right"):
                    found, flags = _heads(evidence[name])
                    heads.update(found)
                    issues.extend(flags)
                bills = re.findall(r"(?<!\d)\d{9}(?!\d)", evidence["bill"])
                bill = bills[0] if len(bills) == 1 else ""
                if not bill:
                    issues.append("Bill number unreadable; enter from source")
                if not year:
                    issues.append("Payment year unreadable; enter from source")
                if token != month.lower():
                    issues.append("Month spelling normalized from " + token)
                printed = [_amount(t) for t in evidence["gross"].split()]
                printed = [v for v in printed if v is not None]
                gross = printed[0] if len(printed) == 1 else None
                if gross is None:
                    issues.append("Printed gross unreadable")
                elif sum(Decimal(v) for v in heads.values()) != Decimal(gross):
                    issues.append(
                        "Recognized allowances do not reconcile to printed gross; correct missing or misread amounts"
                    )
                heads, suggestions = select_reconciled_heads(heads, issues, gross)
                kind = " ".join(evidence["type"].split())
                if re.search(r"(?i)regul", kind):
                    kind = "Regular Salary"
                p = dict(
                    employee_code="",
                    pay_month=(
                        f"{year}-{MONTHS.index(month)+1:02d}"
                        if year and month in MONTHS
                        else ""
                    ),
                    month_name=month,
                    bill_no=bill,
                    bill_type=kind or "Unclassified",
                    payment_class=classify_bill(kind),
                    allowances=heads,
                    deductions={},
                    source_pages=[page.number + 1],
                    source_region=[a, b],
                    ocr_evidence=evidence,
                    amount_suggestions=suggestions,
                    issues=issues,
                    requires_review=True,
                    entitlement_period=None,
                )
                p["entitlement_type"] = entitlement_type(p)
                if gross is not None:
                    p["printed_gross"] = gross
                records.append(p)
    return dict(
        payments=records,
        requires_review=True,
        calculation_ready=False,
        layout="GA55 A column OCR",
        extraction_status=(
            "candidates_require_review" if records else "unreadable_or_unsupported"
        ),
        notice="Column OCR candidates require correction and source review. Missing heads are unknown, never assumed zero. Identity and payment totals must be entered/verified before approval. Rows may be omitted: check every page and annual totals.",
    )
