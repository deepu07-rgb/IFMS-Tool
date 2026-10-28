"""Conservative ruled-statement extraction, independent of expected amounts.

Geometry is measured from printed rules. Recognition candidates and source polygons
survive even when faint headers prevent any semantic interpretation.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import re

GRID_EXTRACTION_VERSION = "3"


def literal_money(text):
    """Accept a complete numeric token; never repair letters, dashes or fragments."""
    value = str(text or "").strip()
    if not re.fullmatch(
        r"(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d{1,2})?", value
    ):
        return None
    try:
        return str(Decimal(value.replace(",", "")))
    except InvalidOperation:
        return None


def _lines(binary, horizontal):
    import cv2
    import numpy as np

    height, width = binary.shape
    minimum = (width if horizontal else height) * 0.28
    found = cv2.HoughLinesP(
        binary, 1, np.pi / 1800, threshold=80, minLineLength=int(minimum), maxLineGap=25
    )
    if found is None:
        return []
    measured = []
    center = width / 2 if horizontal else height / 2
    for x1, y1, x2, y2 in found.reshape(-1, 4):
        dx, dy = float(x2 - x1), float(y2 - y1)
        if horizontal:
            if abs(dx) < minimum or abs(dy) > abs(dx) * 0.15:
                continue
            slope = dy / dx
            intercept = y1 - slope * x1
        else:
            if abs(dy) < minimum or abs(dx) > abs(dy) * 0.15:
                continue
            slope = dx / dy
            intercept = x1 - slope * y1
        measured.append(
            (
                slope * center + intercept,
                slope,
                intercept,
                abs(dx if horizontal else dy),
            )
        )
    groups = []
    for item in sorted(measured):
        if groups and abs(item[0] - np.median([x[0] for x in groups[-1]])) <= 6:
            groups[-1].append(item)
        else:
            groups.append([item])
    return [
        (
            float(np.median([x[1] for x in group])),
            float(np.median([x[2] for x in group])),
        )
        for group in groups
    ]


def _intersection(horizontal, vertical):
    hs, hb = horizontal
    vs, vb = vertical
    x = (vs * hb + vb) / (1 - vs * hs)
    return [x, hs * x + hb]


def _binary(image, offset=12):
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, offset
    )


def _positions(mask, horizontal):
    import numpy as np

    extent = mask.shape[1 if horizontal else 0]
    support = np.count_nonzero(mask, axis=1 if horizontal else 0)
    indices = np.flatnonzero(support >= extent * 0.35)
    groups = []
    for index in indices:
        if groups and index - groups[-1][-1] <= 4:
            groups[-1].append(int(index))
        else:
            groups.append([int(index)])
    return [int(round(sum(group) / len(group))) for group in groups]


def extract_statement_grid(
    image,
    recognizer=None,
    *,
    source_sha256=None,
    page_number=1,
    template_mapping=None,
    minimum_confidence=0.93
):
    """Extract cells from an RGB array/PIL image or image path.

    A template mapping is explicit assistance: ``{"month_column": 0,
    "groups": {"due": {"Basic": 1, "Total": 2}, "drawn": ...}}``.
    It labels existing columns only; it cannot supply amounts or missing months.
    No OCR backend is loaded unless supplied by the caller. Unreadable cells keep
    ``text=None`` and ``amount=None``; candidates retain raw text and confidence.
    """
    import cv2
    import numpy as np
    from pathlib import Path
    from .due_drawn import parse_statement_table

    if not 0.93 <= minimum_confidence <= 1:
        raise ValueError("Minimum confidence must be at least 0.93")
    if isinstance(image, (str, Path)):
        raw_bytes = Path(image).read_bytes()
        source_sha256 = source_sha256 or hashlib.sha256(raw_bytes).hexdigest()
        bgr = cv2.imdecode(np.frombuffer(raw_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Unreadable source image")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    else:
        rgb = np.asarray(image.convert("RGB") if hasattr(image, "convert") else image)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("An RGB image is required")
        source_sha256 = source_sha256 or hashlib.sha256(rgb.tobytes()).hexdigest()
    result = dict(
        extraction_version=GRID_EXTRACTION_VERSION,
        source_sha256=source_sha256,
        source_page=page_number,
        raster_size=[int(rgb.shape[1]), int(rgb.shape[0])],
        assisted=template_mapping is not None,
        cells=[],
        source_margin_regions=[],
        table_rows=[],
        semantic_rows=[],
        issues=[],
        review_required=True,
        coordinate_space="source raster pixels",
    )
    # Faint printed outer rules can disappear at the OCR ink threshold, clipping
    # the first handwriting baseline before recognition ever sees it. Geometry
    # uses the same sensitive threshold here as the normalized rule detection.
    binary = _binary(rgb, offset=2)
    horizontal, vertical = _lines(binary, True), _lines(binary, False)
    # Long text baselines can trigger Hough. Require continuous source ink
    # along the proposed rule, not merely a collinear run of glyphs.
    h, w = binary.shape

    def supported(line, is_horizontal):
        slope, intercept = line
        axis = np.arange(
            int((w if is_horizontal else h) * 0.1),
            int((w if is_horizontal else h) * 0.9),
        )
        other = np.rint(slope * axis + intercept).astype(int)
        if np.any(other < 3) or np.any(other >= (h if is_horizontal else w) - 3):
            return False
        samples = np.array(
            [
                binary[other + d, axis] if is_horizontal else binary[axis, other + d]
                for d in range(-2, 3)
            ]
        )
        return float(np.mean(np.any(samples, axis=0))) >= 0.45

    horizontal = [line for line in horizontal if supported(line, True)]
    vertical = [line for line in vertical if supported(line, False)]
    if len(horizontal) < 3 or len(vertical) < 3:
        result["issues"].append("Insufficient ruled-table grid evidence")
        return result
    corners = np.float32(
        [
            _intersection(horizontal[0], vertical[0]),
            _intersection(horizontal[0], vertical[-1]),
            _intersection(horizontal[-1], vertical[-1]),
            _intersection(horizontal[-1], vertical[0]),
        ]
    )
    width = int(
        round(
            max(
                np.linalg.norm(corners[1] - corners[0]),
                np.linalg.norm(corners[2] - corners[3]),
            )
        )
    )
    height = int(
        round(
            max(
                np.linalg.norm(corners[3] - corners[0]),
                np.linalg.norm(corners[2] - corners[1]),
            )
        )
    )
    if min(width, height) < 20:
        result["issues"].append("Degenerate ruled-table geometry")
        return result
    target = np.float32(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]
    )
    transform = cv2.getPerspectiveTransform(corners, target)
    inverse = np.linalg.inv(transform)
    # A scan may cut off the outer rule. Retain the strip beyond the final
    # measured vertical only when multiple printed rules visibly continue into
    # it. The page edge bounds evidence; it does not establish another column.
    continuing_rules = 0
    for line in horizontal:
        edge_x = _intersection(line, vertical[-1])[0]
        axis = np.arange(int(edge_x) + 5, w - 5)
        other = np.rint(line[0] * axis + line[1]).astype(int)
        valid = (other >= 3) & (other < h - 3)
        axis, other = axis[valid], other[valid]
        if (
            axis.size >= 16
            and np.mean(np.any([binary[other + d, axis] for d in range(-2, 3)], axis=0))
            >= 0.25
        ):
            continuing_rules += 1
    margin_width = 0
    if continuing_rules >= 2:
        page_edge = np.float32(
            [
                [
                    [w - 1, line[0] * (w - 1) + line[1]]
                    for line in (horizontal[0], horizontal[-1])
                ]
            ]
        )
        edge_positions = cv2.perspectiveTransform(page_edge, transform)[0, :, 0]
        margin_width = max(0, int(np.floor(np.min(edge_positions))) - width)
        if margin_width < 16:
            margin_width = 0
    normalized = cv2.warpPerspective(
        rgb, transform, (width + margin_width, height), borderValue=(255, 255, 255)
    )
    normalized_binary = _binary(normalized)
    # Geometry alone uses a sensitive threshold for faded printed rules.
    geometry_binary = cv2.adaptiveThreshold(
        cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY),
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        35,
        2,
    )
    hmask = cv2.morphologyEx(
        geometry_binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1)),
    )
    vmask = cv2.morphologyEx(
        geometry_binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, height // 8))),
    )
    xs, ys = _positions(vmask[:, :width], False), _positions(
        cv2.dilate(hmask[:, :width], np.ones((7, 1), np.uint8)), True
    )
    # Warping can clip the outer rules by a pixel; their measured corners remain evidence.
    xs = sorted(set([0, *[x for x in xs if 5 < x < width - 6], width - 1]))
    ys = sorted(set([0, *[y for y in ys if 5 < y < height - 6], height - 1]))
    result.update(
        source_grid_polygon=corners.tolist(),
        normalized_size=[width, height],
        source_to_normalized=transform.tolist(),
        column_rules=xs,
        row_rules=ys,
    )
    clean = cv2.subtract(normalized_binary, cv2.bitwise_or(hmask, vmask))
    for row, (top, bottom) in enumerate(zip(ys, ys[1:])):
        values = []
        spans = list(zip(xs, xs[1:]))
        if margin_width:
            spans.append((width, width + margin_width - 1))
        for column, (left, right) in enumerate(spans):
            is_margin = column == len(xs) - 1
            inset = 3
            box = [left + inset, top + inset, right - inset, bottom - inset]
            polygon = cv2.perspectiveTransform(
                np.float32(
                    [[[left, top], [right, top], [right, bottom], [left, bottom]]]
                ),
                inverse,
            )[0].tolist()
            cell = dict(
                row=row,
                column=column,
                source_sha256=source_sha256,
                source_page=page_number,
                source_polygon=polygon,
                source_box=[
                    min(p[0] for p in polygon),
                    min(p[1] for p in polygon),
                    max(p[0] for p in polygon),
                    max(p[1] for p in polygon),
                ],
                normalized_box=[left, top, right, bottom],
                text=None,
                amount=None,
                candidates=[],
                status="blank_or_unreadable",
            )
            if box[2] > box[0] and box[3] > box[1]:
                crop = normalized[box[1] : box[3], box[0] : box[2]]
                ink = clean[box[1] : box[3], box[0] : box[2]]
                # Skip only essentially empty interiors, preserving blank cell provenance.
                if (
                    np.count_nonzero(ink) >= max(8, ink.size * 0.004)
                    and recognizer is not None
                ):
                    try:
                        # Multiple handwriting baselines within one physical cell
                        # are alternatives, never concatenated into a larger amount.
                        foreground = np.count_nonzero(ink, axis=1)
                        active = np.flatnonzero(
                            foreground >= max(2, ink.shape[1] * 0.08)
                        )
                        bands = []
                        for y in active:
                            if bands and y - bands[-1][-1] <= 5:
                                bands[-1].append(int(y))
                            else:
                                bands.append([int(y)])
                        bands = [band for band in bands if band[-1] - band[0] >= 6]
                        for line_index, band in enumerate(bands):
                            line_top, line_bottom = max(0, band[0] - 2), min(
                                crop.shape[0], band[-1] + 3
                            )
                            prepared = cv2.resize(
                                crop[line_top:line_bottom],
                                None,
                                fx=2,
                                fy=2,
                                interpolation=cv2.INTER_CUBIC,
                            )
                            prepared = cv2.copyMakeBorder(
                                prepared,
                                8,
                                8,
                                8,
                                8,
                                cv2.BORDER_CONSTANT,
                                value=(255, 255, 255),
                            )
                            raw, _ = recognizer(prepared, use_det=False, use_cls=False)
                            for entry in raw or []:
                                if len(entry) != 2 or not isinstance(entry[0], str):
                                    continue
                                text, confidence = entry[0].strip(), float(entry[1])
                                line_ink = ink[line_top:line_bottom]
                                boundary_ink = bool(
                                    np.count_nonzero(line_ink[:, :2]) >= 3
                                    or np.count_nonzero(line_ink[:, -2:]) >= 3
                                )
                                line_box = [
                                    box[0],
                                    box[1] + line_top,
                                    box[2],
                                    box[1] + line_bottom,
                                ]
                                line_polygon = cv2.perspectiveTransform(
                                    np.float32(
                                        [
                                            [
                                                [line_box[0], line_box[1]],
                                                [line_box[2], line_box[1]],
                                                [line_box[2], line_box[3]],
                                                [line_box[0], line_box[3]],
                                            ]
                                        ]
                                    ),
                                    inverse,
                                )[0].tolist()
                                cell["candidates"].append(
                                    dict(
                                        text=text,
                                        confidence=confidence,
                                        line_index=line_index,
                                        source_polygon=line_polygon,
                                        boundary_ink=boundary_ink,
                                        review_required=True,
                                        recognizer="rapidocr-cell",
                                        preprocessing="source RGB; per-cell text line; scale 2; white padding",
                                        literal_amount=literal_money(text),
                                    )
                                )
                        accepted = [
                            c
                            for c in cell["candidates"]
                            if c["confidence"] >= minimum_confidence
                            and not c["boundary_ink"]
                        ]
                        if not is_margin and len(bands) == 1 and len(accepted) == 1:
                            cell.update(
                                text=accepted[0]["text"],
                                amount=accepted[0]["literal_amount"],
                                status="recognized",
                            )
                        elif len(bands) > 1:
                            cell["status"] = "ambiguous_multiple_lines"
                        elif cell["candidates"]:
                            cell["status"] = "uncertain"
                    except Exception as exc:
                        cell["status"] = "recognition_error"
                        cell["error"] = type(exc).__name__
            if is_margin:
                cell.update(
                    column=None,
                    region_id="right_margin_r{}".format(row),
                    status="source_geometry_unresolved",
                    review_required=True,
                    boundary_evidence="Observed horizontal rules continue beyond last vertical; source page edge bounds unassigned region",
                    text=None,
                    amount=None,
                )
                result["source_margin_regions"].append(cell)
            else:
                result["cells"].append(cell)
                values.append(cell["text"])
        result["table_rows"].append(values)
    if margin_width:
        result["issues"].append(
            "Source content beyond the last measured vertical rule retained as unassigned margin evidence; no statement column established"
        )
    rows = result["table_rows"]
    if template_mapping is not None:
        rows = _mapped_rows(rows, template_mapping)
        result["issues"].append(
            "Explicit template mapping used; assisted extraction requires review"
        )
    result["semantic_rows"] = parse_statement_table(_literal_statement_rows(rows))
    if not result["semantic_rows"]:
        # Preserve an explicit unknown header and a reviewable source band.
        typical_height = float(np.median(np.diff(ys)))
        header_polygon = cv2.perspectiveTransform(
            np.float32(
                [
                    [
                        [0, -2 * typical_height],
                        [width - 1, -2 * typical_height],
                        [width - 1, 0],
                        [0, 0],
                    ]
                ]
            ),
            inverse,
        )[0].tolist()
        result["unknown_header_row"] = [None] * (len(xs) - 1)
        result["header_evidence"] = dict(
            status="unresolved",
            source_polygon=header_polygon,
            source_page=page_number,
            source_sha256=source_sha256,
            reason="Printed header labels not established from source recognition",
        )
        result["issues"].append(
            "Unknown or unreadable statement headers/months; explicit template mapping or source review required"
        )
    if any(
        c["status"] in {"uncertain", "recognition_error", "ambiguous_multiple_lines"}
        for c in result["cells"]
    ):
        result["issues"].append("Uncertain cells retained without filling amounts")
    return result


def _mapped_rows(rows, mapping):
    """Validate user-supplied labels; never infer layout from financial values."""
    from .due_drawn import _COMPONENTS

    if not isinstance(mapping, dict) or set(mapping) != {"month_column", "groups"}:
        raise ValueError("Template mapping requires month_column and groups")
    month = mapping["month_column"]
    groups = mapping["groups"]
    width = max(map(len, rows), default=0)
    if type(month) is not int or not 0 <= month < width:
        raise ValueError("Invalid month column")
    if (
        not isinstance(groups, dict)
        or not {"due", "drawn"}.issubset(groups)
        or set(groups) - {"due", "drawn", "difference"}
    ):
        raise ValueError("Template mapping requires due/drawn groups")
    used = {month}
    selected = [month]
    group_header, component_header = ["Month"], [""]
    for group in ("due", "drawn", "difference"):
        if group not in groups:
            continue
        components = groups[group]
        if (
            not isinstance(components, dict)
            or "Total" not in components
            or len(components) < 2
        ):
            raise ValueError("Every mapped group requires components and Total")
        for i, (component, column) in enumerate(components.items()):
            if (
                component not in set(_COMPONENTS.values())
                or type(column) is not int
                or not 0 <= column < width
                or column in used
            ):
                raise ValueError("Invalid or overlapping component column")
            used.add(column)
            selected.append(column)
            group_header.append(group if i == 0 else "")
            component_header.append(component)
    if set(groups["due"]) != set(groups["drawn"]):
        raise ValueError("Due/drawn components must match")
    return [group_header, component_header] + [
        [
            (
                row[c]
                if c < len(row) and i == 0
                else literal_money(row[c]) if c < len(row) else None
            )
            for i, c in enumerate(selected)
        ]
        for row in rows
    ]


def _literal_statement_rows(rows):
    """Guard downstream parser from permissive currency text normalization."""
    from .due_drawn import _layout, _COMPONENTS, month_value

    safe = [list(row) for row in rows]
    layout = None
    for index, row in enumerate(rows):
        found = _layout(rows, index, _COMPONENTS)
        if found is not None:
            layout = found
        if layout is None:
            continue
        header_end, month_column, groups = layout
        if (
            index <= header_end
            or month_column >= len(row)
            or month_value(row[month_column]) is None
        ):
            continue
        for columns in groups.values():
            for column in columns.values():
                if column < len(row):
                    safe[index][column] = literal_money(row[column])
    return safe
