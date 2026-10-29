"""Conservative, source-preserving extraction of ruled IFMS bill registers.

Amounts and identifiers remain strings. Image-only row rules are observed
geometrically when a text layer exists. Unknown layouts retain raw page text; this module never guesses digits or financial values.
"""

from __future__ import annotations

import re
from datetime import datetime

import pymupdf

COLUMNS = [
    "SrNo",
    "BillNo",
    "BillDate",
    "Type",
    "Month",
    "Year",
    "Gross",
    "Net",
    "IncomeTax",
    "TVNo",
    "TokenNo",
    "TVDate",
    "Status",
    "GroupName",
    "ECSNo",
]
_ALIASES = {
    "SrNo": ("srno",),
    "BillNo": ("billno",),
    "BillDate": ("billdate",),
    "Type": ("billtype", "type"),
    "Month": ("billmonth", "month"),
    "Year": ("billyear", "year"),
    "Gross": ("grossamount", "gross"),
    "Net": ("netamount", "net"),
    "IncomeTax": ("incometax",),
    "TVNo": ("tvno",),
    "TokenNo": ("tokenno",),
    "TVDate": ("tvdate",),
    "Status": ("billstatus", "status"),
    "GroupName": ("groupname",),
    "ECSNo": ("ecsno",),
}


def _normal(text):
    return re.sub("[^a-z0-9]", "", text.lower())


def _lines(words):
    """Group by text baseline, never by PDF stream order or text block."""
    lines = []
    for word in sorted(words, key=lambda w: (w[1], w[0])):
        if not lines or abs(word[1] - lines[-1][0][1]) > 2:
            lines.append([word])
        else:
            lines[-1].append(word)
    return [sorted(line, key=lambda w: w[0]) for line in lines]


def _image_rules(page, minimum_span):
    """Observe long horizontal dark rules in an image; never infer cell text."""
    if not page.get_images():
        return []
    scale = 2
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY, alpha=False
    )
    samples = pix.samples
    minimum_dark = int(minimum_span * scale * 0.85)
    detected = []
    for y in range(pix.height):
        scan = samples[y * pix.stride : y * pix.stride + pix.width]
        if sum(value < 160 for value in scan) < minimum_dark:
            continue
        dark = [x for x, value in enumerate(scan) if value < 160]
        if dark:
            detected.append((dark[0] / scale, dark[-1] / scale, y / scale))
    # A printed rule may occupy several raster rows. Merge those pixels into
    # one observed rule rather than generating zero-height table bands.
    clusters = []
    for rule in detected:
        if clusters and rule[2] - clusters[-1][-1][2] <= 1:
            clusters[-1].append(rule)
        else:
            clusters.append([rule])
    return [
        tuple(sum(r[i] for r in cluster) / len(cluster) for i in range(3))
        for cluster in clusters
    ]


def _layout(page, words):
    starts = [w[1] for w in words if _normal(w[4]) in ("sr", "srno")]
    if not starts:
        return None
    top = min(starts)
    candidates = [w for w in words if top - 2 <= w[1] <= top + 22 and w[3] - w[1] < 30]
    anchors = {}
    labels = {}
    for line in _lines(candidates):
        for i in range(len(line)):
            for count in (3, 2, 1):
                part = line[i : i + count]
                if len(part) != count:
                    continue
                label = _normal("".join(w[4] for w in part))
                for column, aliases in _ALIASES.items():
                    if label in aliases and column not in anchors:
                        labels[column] = " ".join(w[4] for w in part)
                        anchors[column] = (
                            min(w[0] for w in part),
                            min(w[1] for w in part),
                            max(w[2] for w in part),
                            max(w[3] for w in part),
                        )
    if set(anchors) != set(COLUMNS):
        return None
    groups = []
    for column in COLUMNS:
        a = anchors[column]
        if column == "BillDate" and abs(a[0] - anchors["BillNo"][0]) < 3:
            groups[-1]["columns"].append(column)
            groups[-1]["right"] = max(groups[-1]["right"], a[2])
        else:
            groups.append({"columns": [column], "left": a[0], "right": a[2]})
    if any(a["left"] >= b["left"] for a, b in zip(groups, groups[1:])):
        return None
    bottom = max(a[3] for a in anchors.values())
    rules = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if (
            rect.height <= 1
            and rect.width >= (anchors["ECSNo"][2] - anchors["SrNo"][0]) * 0.95
        ):
            rules.append((rect.x0, rect.x1, rect.y0))
    # Match the actual table's left edge so footer rules cannot become data rows.
    eligible = [r for r in rules if r[2] >= bottom - 1]
    image_rules = False
    if not eligible:
        rules = _image_rules(page, anchors["ECSNo"][2] - anchors["SrNo"][0])
        eligible = [r for r in rules if r[2] >= bottom - 1]
        image_rules = bool(eligible)
    if not eligible:
        return None
    first = min(eligible, key=lambda r: r[2])
    ys = sorted(
        {
            round(r[2], 2)
            for r in eligible
            if abs(r[0] - first[0]) < 2 and abs(r[1] - first[1]) < 2
        }
    )
    if len(ys) < 2:
        return None
    boundaries = (
        [first[0]]
        + [(a["right"] + b["left"]) / 2 for a, b in zip(groups, groups[1:])]
        + [first[1]]
    )
    # A wrapped Gross Amount header is two lines in the supplied IFMS layout.
    gross = anchors["Gross"]
    if _normal(labels["Gross"]) == "gross":
        amount = [
            w
            for w in candidates
            if _normal(w[4]) == "amount"
            and w[1] > gross[1] + 2
            and abs((w[0] + w[2]) / 2 - (gross[0] + gross[2]) / 2) < 20
        ]
        if len(amount) == 1:
            labels["Gross"] += "\n" + amount[0][4]
    return groups, boundaries, ys, labels, image_rules


def _band(words, groups, boundaries, page_number):
    row = dict.fromkeys(COLUMNS, "")
    fragments = []
    for index, group in enumerate(groups):
        cell = [
            w
            for w in words
            if boundaries[index] <= (w[0] + w[2]) / 2 < boundaries[index + 1]
        ]
        for line_number, line in enumerate(_lines(cell)):
            column = group["columns"][min(line_number, len(group["columns"]) - 1)]
            text = " ".join(w[4] for w in line)
            separator = "" if column == "ECSNo" else " "
            row[column] += (separator if row[column] else "") + text
            fragments.append(
                {
                    "page": page_number,
                    "column": column,
                    "text": text,
                    "bbox": [
                        round(min(w[0] for w in line), 3),
                        round(min(w[1] for w in line), 3),
                        round(max(w[2] for w in line), 3),
                        round(max(w[3] for w in line), 3),
                    ],
                }
            )
    return row, fragments


def parse_bill_pdf(data: bytes) -> dict:
    """Return canonical raw rows plus page/cell provenance and review issues.

    Supported layouts have all fifteen known headers (BillNo/BillDate may
    share a physical column) and horizontal row rules, including rules visible in embedded images. OCR
    characters are never corrected: image-only pages receive an explicit review issue.
    """
    result = {
        "columns": COLUMNS.copy(),
        "column_labels": {},
        "rows": [],
        "evidence": [],
        "issues": [],
        "raw_pages": [],
        "method": "digital_geometry",
        "requires_review": False,
    }
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        result["issues"].append(f"PDF could not be opened: {type(exc).__name__}.")
        result["requires_review"] = True
        return result
    with doc:
        if doc.needs_pass:
            result["issues"].append(
                "PDF is encrypted; provide an unlocked source for extraction."
            )
        else:
            for page_number, page in enumerate(doc, 1):
                result["raw_pages"].append(page.get_text())
                # Exclude oversized watermark text, retaining it in raw_pages.
                words = [w for w in page.get_text("words") if w[3] - w[1] < 30]
                layout = _layout(page, words)
                if not layout:
                    reason = (
                        "No digital text; OCR/manual review is required"
                        if not words
                        else "Unrecognized or unruled bill register layout"
                    )
                    result["issues"].append(
                        f"Page {page_number}: {reason}; raw text retained."
                    )
                    continue
                groups, boundaries, ys, labels, image_rules = layout
                if image_rules:
                    result["issues"].append(
                        f"Page {page_number}: table rows located from image rules; review OCR text and numeric identifiers against the source image."
                    )
                if not result["column_labels"]:
                    result["column_labels"] = labels
                bands = []
                for top, bottom in zip(ys, ys[1:]):
                    cell_words = [w for w in words if top <= (w[1] + w[3]) / 2 < bottom]
                    row, fragments = _band(cell_words, groups, boundaries, page_number)
                    if fragments:
                        bands.append((row, fragments))
                for band_index, (row, fragments) in enumerate(bands):
                    if not row["SrNo"].isdigit() or not row["BillNo"]:
                        # Only an isolated ECS suffix in the first band of the
                        # immediate following page can extend a preceding row.
                        previous = result["rows"][-1] if result["rows"] else None
                        evidence = result["evidence"][-1] if previous else None
                        next_row = (
                            bands[band_index + 1][0]
                            if band_index + 1 < len(bands)
                            else {}
                        )
                        isolated_ecs = row["ECSNo"].isdigit() and all(
                            not value for key, value in row.items() if key != "ECSNo"
                        )
                        previous_ecs_lines = (
                            [f for f in evidence["fragments"] if f["column"] == "ECSNo"]
                            if evidence
                            else []
                        )
                        safe_suffix = (
                            isolated_ecs
                            and band_index == 0
                            and previous
                            and evidence["source_pages"] == [page_number - 1]
                            and previous["SrNo"].isdigit()
                            and next_row.get("SrNo", "").isdigit()
                            and int(next_row["SrNo"]) == int(previous["SrNo"]) + 1
                            and len(previous_ecs_lines) == 2
                            and re.fullmatch(r"EPV\d+", previous["ECSNo"])
                        )
                        if safe_suffix:
                            previous["ECSNo"] += row["ECSNo"]
                            evidence["source_pages"].append(page_number)
                            evidence["fragments"].extend(fragments)
                            result["issues"].append(
                                f'Page {page_number}: ECSNo for row {previous["SrNo"]} reconstructed from an isolated page-top continuation; verify the recorded source fragments.'
                            )
                        else:
                            detail = "; ".join(f"{k}={v}" for k, v in row.items() if v)
                            result["issues"].append(
                                f"Page {page_number}: unassigned table fragment ({detail}); retained in raw page text."
                            )
                        continue
                    missing = [k for k, value in row.items() if not value]
                    if missing:
                        result["issues"].append(
                            f'Page {page_number}, row {row["SrNo"]}: empty source fields: {", ".join(missing)}.'
                        )
                    uncertain = [
                        k
                        for k in ("BillNo", "Year", "TVNo", "TokenNo")
                        if row[k] and not row[k].isdigit()
                    ]
                    if uncertain:
                        result["issues"].append(
                            f'Page {page_number}, row {row["SrNo"]}: unexpected identifier text in {", ".join(uncertain)}; source preserved without correction.'
                        )
                    for date_column in ("BillDate", "TVDate"):
                        if row[date_column]:
                            try:
                                datetime.strptime(row[date_column], "%d/%m/%Y")
                            except ValueError:
                                result["issues"].append(
                                    f'Page {page_number}, row {row["SrNo"]}: invalid observed date in {date_column}={row[date_column]}; source preserved without correction.'
                                )
                    result["evidence"].append(
                        {
                            "row_index": len(result["rows"]),
                            "source_pages": [page_number],
                            "fragments": fragments,
                        }
                    )
                    result["rows"].append(row)
    if not result["rows"] and not result["issues"]:
        result["issues"].append("No bill rows found; manual review is required.")
    result["requires_review"] = bool(result["issues"])
    return result
