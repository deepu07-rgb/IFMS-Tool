"""Recognize the supplied Basic/DA/HRA due-drawn layout conservatively."""

from datetime import datetime, date
from decimal import Decimal
import re
from .calculation import money, rounded


def month_value(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m")
    text = " ".join(str(v or "").replace("\n", " ").split())
    for fmt in (
        "%b-%Y",
        "%b-%y",
        "%B %Y",
        "%b %Y",
        "%B-%Y",
        "%Y-%m",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    return None


def parse_statement_table(rows):
    layout = None
    for index, row in enumerate(rows[:30]):
        labels = [" ".join(str(c or "").lower().split()) for c in row]
        due = next((i for i, l in enumerate(labels) if l == "pay due"), None)
        drawn = next((i for i, l in enumerate(labels) if l == "pay drawn"), None)
        if due is not None and drawn is not None and drawn - due == 4 and due >= 1:
            layout = (index, due, drawn)
            break
    if layout is None:
        return []
    header, due, drawn = layout
    result = []
    for index, row in enumerate(rows[header + 1 :], header + 2):
        if len(row) < drawn + 4:
            continue
        month = month_value(row[due - 1])
        if not month:
            continue
        try:
            d = [money(v) for v in row[due : due + 4]]
            a = [money(v) for v in row[drawn : drawn + 4]]
        except ValueError:
            continue
        printed = None
        if len(row) > drawn + 7:
            try:
                printed = rounded(money(row[drawn + 7]))
            except ValueError:
                pass
        difference = rounded(d[3] - a[3])
        issues = []
        if rounded(sum(d[:3])) != rounded(d[3]):
            issues.append("Pay Due components do not match printed total")
        if rounded(sum(a[:3])) != rounded(a[3]):
            issues.append("Pay Drawn components do not match printed total")
        if printed is not None and printed != difference:
            issues.append("Printed difference does not match Due minus Drawn")
        result.append(
            dict(
                month=month,
                due=dict(zip(["Basic", "DA", "HRA"], [f"{v:.2f}" for v in d[:3]])),
                drawn=dict(zip(["Basic", "DA", "HRA"], [f"{v:.2f}" for v in a[:3]])),
                printed_due=f"{d[3]:.2f}",
                printed_drawn=f"{a[3]:.2f}",
                printed_difference=f"{printed:.2f}" if printed is not None else None,
                calculated_difference=f"{difference:.2f}",
                issues=issues,
                source_row=index,
                requires_review=True,
            )
        )
    return result


def parse_workbook(data):
    from io import BytesIO
    from zipfile import ZipFile
    from openpyxl import load_workbook

    with ZipFile(BytesIO(data)) as z:
        if sum(f.file_size for f in z.infolist()) > 200 * 1024 * 1024:
            raise ValueError("Workbook expanded size exceeds 200 MB")
    w = load_workbook(BytesIO(data), data_only=True, read_only=True)
    records = []
    source = []
    try:
        for s in w:
            if s.max_row * s.max_column > 300000:
                continue
            rows = list(s.iter_rows(values_only=True))
            parsed = parse_statement_table(rows)
            for r in parsed:
                r["source_sheet"] = s.title
            records.extend(parsed)
            if parsed:
                source.append(
                    "Worksheet: "
                    + s.title
                    + "\n"
                    + "\n".join(
                        " | ".join(str(v or "") for v in row[:40]) for row in rows[:300]
                    )
                )
    finally:
        w.close()
    return dict(
        statement_rows=records,
        pages=source,
        requires_review=True,
        notice="Cached workbook values were read; formulas were not executed. Compare sources and verify rates before creating a claim.",
    )


def parse_pdf_tables(data):
    import pymupdf

    d = pymupdf.open(stream=data, filetype="pdf")
    records = []
    try:
        for page in d:
            tables = page.find_tables().tables
            if not tables:
                tables = page.find_tables(strategy="text").tables
            for t in tables:
                for r in parse_statement_table(t.extract()):
                    r["source_page"] = page.number + 1
                    records.append(r)
    finally:
        d.close()
    return records
