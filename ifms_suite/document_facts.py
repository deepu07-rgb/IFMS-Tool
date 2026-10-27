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

FACTS_VERSION = "geometry-printed-v2"

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


def _identity(words):
    ids = [_text(w) for w in words if ID.fullmatch(_text(w))]
    return ids[0] if len(set(ids)) == 1 else ""


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


def _page_key(words):
    fy = next((_text(w) for w in words if re.fullmatch(r"20\d{2}-\d{2}", _text(w))), "")
    group = next((_text(w) for w in words if _text(w).startswith("GROUPNAME:")), "")
    return fy, group


def facts_from_pages(pages):
    """Build facts from word boxes, keeping document and employee boundaries."""
    bills = []
    orders = []
    issues = []
    layout = None
    previous = None
    for page in pages:
        words = page["words"]
        number = page["page"]
        compact = " ".join(_text(w) for w in words)
        header_identities = [
            w for w in words if w["box"][1] < 0.23 and ID.fullmatch(_text(w))
        ]
        employee = _identity(header_identities)
        ga55 = "GA55" in compact or ("ALLOWANCES" in compact and "GROSS" in compact)
        if ga55:
            allowance = next((w for w in words if _text(w) == "ALLOWANCES"), None)
            gross_header = next((w for w in words if _text(w) == "GROSS"), None)
            if allowance and gross_header:
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
                    {"page": number, "issue": "Allowance column geometry unresolved"}
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
            if previous and carry_words:
                same_identity = bool(
                    employee
                    and employee == previous["employee_code"]
                    and number == previous["source_pages"][-1] + 1
                )
                # Some printed continuations omit the identity: require adjacent pages,
                # matching fiscal year/group footer, and no replacement identity.
                key = _page_key(words)
                same_document = (
                    not header_identities
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
                    else:
                        previous["allowances"].update(heads)
                        previous["evidence"].extend(ev)
                        previous["_issues"].extend(flags)
                        previous["source_pages"].append(number)
                else:
                    issues.append(
                        {"page": number, "issue": "Continuation identity unresolved"}
                    )
            inherited_employee = employee
            identity_evidence = [
                _evidence(w, number) for w in header_identities if _text(w) == employee
            ]
            if (
                not header_identities
                and previous
                and _page_key(words) == previous.get("_page_key")
                and all(_page_key(words))
                and number == previous["source_pages"][-1]
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
                type_words = [
                    w["text"]
                    for w in region
                    if 0.10 < w["box"][0] < 0.16 and not re.fullmatch(r"\d+", w["text"])
                ]
                kind = " ".join(type_words)
                if re.search(r"regul", kind, re.I):
                    kind = "Regular Salary"
                bill = dict(
                    employee_code=inherited_employee,
                    pay_month=pay_month,
                    bill_no=bill_words[0]["text"] if len(bill_words) == 1 else "",
                    bill_type=kind,
                    allowances=heads,
                    printed_gross=_money(gross["text"]),
                    complete=False,
                    source_pages=[number],
                    evidence=ev
                    + [_evidence(gross, number)]
                    + identity_evidence
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
                    _page_key=_page_key(words),
                )
                bills.append(bill)
                previous = bill
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
                if len(dates) == 1 and len(rates) == 1:
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
                            "evidence": [_evidence(w, number)],
                        }
                    )
    for bill in bills:
        flags = bill.pop("_issues")
        bill.pop("_page_key", None)
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
                }
            )
    return dict(bills=bills, orders=orders, issues=issues)


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


def _recognize_page(page, recognizer, runtime):
    from PIL import Image, ImageOps

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
    if runtime:
        executable, env, _ = runtime
        secondary = _tesseract_words(image, executable, env)
        if not words:
            words = secondary
        else:
            # Independent semantic labels may fill an undetected label. Monetary
            # disagreements never cause substitution of an already valid amount.
            for w in secondary:
                semantic = _head(w) or w["text"] in MONTHS or ID.fullmatch(_text(w))
                overlapping = [q for q in words if _overlaps(w, q)]
                if semantic and not any(
                    _head(q) or q["text"] in MONTHS or ID.fullmatch(_text(q))
                    for q in overlapping
                ):
                    words.append(w)
        compact = " ".join(_text(w) for w in words)
        is_order = "HOUSE" in compact and "RENT" in compact
        rate_x = (
            median([w["box"][0] for w in words if re.fullmatch(r"\d{1,2}%", _text(w))])
            if is_order and any(re.fullmatch(r"\d{1,2}%", _text(w)) for w in words)
            else None
        )
        for word in list(words):
            text = word["text"]
            malformed_money = bool(
                re.fullmatch(r"[+-]?[\d,.:]+", text)
                and re.search(r"[.,:]\d{2}$", text)
                and _money(text) is None
            )
            malformed_id = bool(
                re.fullmatch(r"[A-Z]{2,5}\d{10,13}", _text(word))
                and not ID.fullmatch(_text(word))
            )
            malformed_rate = bool(
                rate_x is not None
                and abs(word["box"][0] - rate_x) < 0.025
                and not re.fullmatch(r"\d{1,2}%", _text(word))
                and re.search(r"\d", text)
            )
            if not (malformed_money or malformed_id or malformed_rate):
                continue
            x1, y1, x2, y2 = word["box"]
            crop = image.crop(
                (
                    max(0, x1 * pix.width - 4),
                    max(0, y1 * pix.height - 4),
                    min(pix.width, x2 * pix.width + 4),
                    min(pix.height, y2 * pix.height + 4),
                )
            )
            original_crop = crop
            crop = ImageOps.autocontrast(
                ImageOps.grayscale(crop.resize((crop.width * 3, crop.height * 3)))
            )
            recognized = _tesseract_words(crop, executable, env, psm=7)
            candidate = "".join(w["text"] for w in recognized)
            valid = (
                _money(candidate) is not None
                if malformed_money
                else (
                    bool(ID.fullmatch(candidate))
                    if malformed_id
                    else bool(re.fullmatch(r"\d{1,2}%", candidate))
                )
            )
            crop_recognizer = "tesseract-crop"
            confidence = min((w["confidence"] for w in recognized), default=0)
            if not valid and malformed_money and recognizer:
                encoded = io.BytesIO()
                original_crop.save(encoded, format="PNG")
                raw, _ = recognizer(encoded.getvalue(), use_det=False, use_cls=False)
                if raw and len(raw) == 1 and _money(raw[0][0]) is not None:
                    candidate = raw[0][0]
                    confidence = float(raw[0][1])
                    valid = True
                    crop_recognizer = "rapidocr-crop"
            if valid:
                word["original_text"] = text
                word["text"] = candidate
                word["recognizer"] = crop_recognizer
                word["confidence"] = confidence
    return words


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
                        "issue": f"Independent printed recognizer unavailable ({type(error).__name__}); using Tesseract"
                    }
                )
            try:
                runtime = ocr_runtime()
            except ValueError:
                recognition_issues.append(
                    {"issue": "Tesseract unavailable for independent recognition"}
                )
        pages = []
        for number, page in enumerate(document, 1):
            if page_needs_ocr(page):
                if not recognizer and not runtime:
                    recognition_issues.append(
                        {"page": number, "issue": "No printed recognizer available"}
                    )
                    continue
                try:
                    words = _recognize_page(page, recognizer, runtime)
                except Exception as error:
                    recognition_issues.append(
                        {
                            "page": number,
                            "issue": f"Printed page recognition unresolved ({type(error).__name__})",
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
            pages.append(dict(page=number, words=words))
    facts = facts_from_pages(pages)
    facts["issues"].extend(recognition_issues)
    facts["facts_version"] = FACTS_VERSION
    return facts
