"""Conservative GA55 text extraction and local OCR. Parsed records require review."""

import re
from decimal import Decimal
from .payment_types import classify_bill, entitlement_type

MONTHS = "January February March April May June July August September October November December".split()
MONEY = re.compile(r"^[-+]?\d[\d,]*\.\d{2}$")
HEADS = {
    "basic": "Basic",
    "da": "DA",
    "hra": "HRA",
    "cca": "CCA",
    "hda": "HDA",
    "fta": "FTA",
    "mess all": "Mess All",
    "rop": "ROP",
    "bonus": "Bonus",
    "gpf": "GPF",
    "gpf 2004": "GPF 2004",
    "sip": "SIP",
    "sil": "SIL",
    "rghs": "RGHS",
    "lic": "LIC",
    "advance salary": "Advance Salary",
    "gi cc": "GI CC",
    "road ways dedution": "Roadways",
    "road ways deduti on": "Roadways",
    "r p kalyan nidhi": "R P Kalyan Nidhi",
    "sulabh complex": "Sulabh Complex",
    "sulabh comple x": "Sulabh Complex",
}
ALLOWANCES = {"Basic", "DA", "HRA", "CCA", "HDA", "FTA", "Mess All", "ROP", "Bonus"}


def parse_ga55(pages):
    tagged = []
    for i, text in enumerate(pages):
        tagged.extend(
            (line.strip(), i + 1) for line in text.splitlines() if line.strip()
        )
    starts = []
    for i, (line, page) in enumerate(tagged[:-1]):
        if line in MONTHS and re.fullmatch(r"20\d{2}", tagged[i + 1][0]):
            starts.append(i)
    identity_at = {}
    employee = ""
    for index, (line, page) in enumerate(tagged):
        if line.lower().replace(" ", "") == "employeeid":
            for candidate, p in tagged[index + 1 : index + 5]:
                value = candidate.strip().upper()
                if re.fullmatch(r"(?=.*[0-9])[A-Z0-9-]{4,30}", value):
                    employee = value
                    break
        identity_at[index] = employee
    payments = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(tagged)
        part = tagged[start:end]
        # The document summary lists annual amounts, not another payment.
        for k, (line, p) in enumerate(part):
            if line == "Total Allowances":
                part = part[:k]
                break
        bill_index = next(
            (
                k
                for k, (line, p) in enumerate(part[2:], 2)
                if re.fullmatch(r"\d{9}", line)
            ),
            None,
        )
        if bill_index is None:
            continue
        names = " ".join(x for x, p in part[2:bill_index])
        record = {
            "employee_code": identity_at.get(start, ""),
            "pay_month": f"{part[1][0]}-{MONTHS.index(part[0][0])+1:02d}",
            "bill_type": names,
            "bill_no": part[bill_index][0],
            "entitlement_period": None,
            "allowances": {},
            "deductions": {},
            "source_pages": sorted({p for t, p in part}),
            "issues": [],
            "raw_text": "\n".join(x for x, p in part),
        }
        record["payment_class"] = classify_bill(names)
        record["entitlement_type"] = entitlement_type(record)
        pending = []
        totals = []
        for line, page in part[bill_index + 1 :]:
            if MONEY.fullmatch(line):
                key = " ".join(pending).lower()
                head = HEADS.get(key)
                if head:
                    dest = (
                        record["allowances"]
                        if head in ALLOWANCES
                        else record["deductions"]
                    )
                    if head in dest:
                        record["issues"].append("Repeated component " + head)
                    dest[head] = f'{Decimal(line.replace(",","")):.2f}'
                elif any(re.search("[A-Za-z]", part) for part in pending):
                    record["issues"].append(
                        "Unmapped amount: " + " ".join(pending) + " = " + line
                    )
                else:
                    totals.append(Decimal(line.replace(",", "")))
                pending = []
            else:
                pending.append(line)
                # Look only at the shortest known tail; metadata cannot become a head.
                for size in range(1, min(5, len(pending)) + 1):
                    if " ".join(pending[-size:]).lower() in HEADS:
                        pending = pending[-size:]
                        break
                if len(pending) > 5:
                    pending = pending[-5:]
        if len(totals) == 3:
            record.update(
                printed_gross=f"{totals[0]:.2f}",
                printed_deductions=f"{totals[1]:.2f}",
                printed_net=f"{totals[2]:.2f}",
            )
            if sum(Decimal(v) for v in record["allowances"].values()) != totals[0]:
                record["issues"].append(
                    "Allowance components differ from printed gross"
                )
            if sum(Decimal(v) for v in record["deductions"].values()) != totals[1]:
                record["issues"].append(
                    "Deduction components differ from printed deduction total; check informational entries"
                )
            if totals[0] - totals[1] != totals[2]:
                record["issues"].append(
                    "Printed gross minus deductions does not equal printed net"
                )
        elif len(totals) == 2 and not record["deductions"]:
            record.update(
                printed_gross=f"{totals[0]:.2f}",
                printed_deductions="0.00",
                printed_net=f"{totals[1]:.2f}",
            )
            record["issues"].append(
                "No deduction entries read; confirm zero against the source"
            )
        else:
            record["issues"].append("Printed totals require manual verification")
        if names != "Regular Salary":
            record["issues"].append(
                "Allocate payment to entitlement period before settling a claim"
            )
        if not record["employee_code"]:
            record["issues"].append(
                "Employee identity not read; confirm it against the source"
            )
        record["issues"].append(
            "Verify component extraction against source and printed totals"
        )
        payments.append(record)
    return {
        "payments": payments,
        "requires_review": True,
        "layout": "GA55 text sequence",
        "notice": "Candidate payment records; verify before use. No entitlement periods inferred from payment months.",
    }


def ocr_runtime():
    import os, sys, shutil, subprocess
    from pathlib import Path

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = root / "ocr" / "tesseract.exe"
    executable = str(bundled) if bundled.is_file() else shutil.which("tesseract")
    env = os.environ.copy()
    models = root / "ocr" / "tessdata"
    if models.is_dir():
        env["TESSDATA_PREFIX"] = str(models)
    if not executable:
        raise ValueError("Local Tesseract is not installed")
    r = subprocess.run(
        [executable, "--list-langs"],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    languages = {s.strip() for s in r.stdout.splitlines()[1:] if s.strip()}
    return executable, env, languages


def page_needs_ocr(page):
    """Digital signatures and headers do not make a scanned bill searchable."""
    if len(page.get_text().strip()) < 20:
        return True
    import pymupdf

    area = page.rect.get_area()
    return area > 0 and any(
        (pymupdf.Rect(info["bbox"]) & page.rect).get_area() >= area * 0.5
        for info in page.get_image_info()
    )


def ocr_document(data, language="eng"):
    import subprocess, tempfile
    from pathlib import Path
    import pymupdf

    if language not in ("eng", "eng+hin"):
        raise ValueError("Unsupported OCR language")
    executable, env, languages = ocr_runtime()
    if not set(language.split("+")).issubset(languages):
        raise ValueError("Requested OCR language data is not installed")
    original = pymupdf.open(stream=data, filetype="pdf")
    combined = pymupdf.open()
    texts = []
    try:
        if len(original) > 200:
            raise ValueError("Split OCR jobs into documents of at most 200 pages")
        for page in original:
            text = page.get_text()
            if not page_needs_ocr(page):
                combined.insert_pdf(
                    original, from_page=page.number, to_page=page.number
                )
                texts.append(text)
                continue
            with tempfile.TemporaryDirectory(prefix="ifms-ocr-") as td:
                image = Path(td) / "page.png"
                output = Path(td) / "recognized"
                page.get_pixmap(dpi=240).save(image)
                r = subprocess.run(
                    [
                        executable,
                        str(image),
                        str(output),
                        "-l",
                        language,
                        "--psm",
                        "3",
                        "pdf",
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=90,
                )
                if r.returncode or not output.with_suffix(".pdf").is_file():
                    raise ValueError(
                        "OCR failed; check image quality and language installation"
                    )
                with pymupdf.open(output.with_suffix(".pdf")) as recognized:
                    texts.append(recognized[0].get_text())
                    combined.insert_pdf(recognized)
        return texts, combined.tobytes(garbage=4, deflate=True)
    finally:
        combined.close()
        original.close()
