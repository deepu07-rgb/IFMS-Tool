"""Source-bound, append-only reviews over immutable machine grid results."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json


def grid_revision(grid):
    return hashlib.sha256(
        json.dumps(grid, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _rows(grid, raw_candidates=False):
    rows = deepcopy(grid.get("table_rows", []))
    if raw_candidates:
        for cell in grid.get("cells", []):
            r, c = cell["row"], cell["column"]
            if r < len(rows) and c < len(rows[r]):
                value = cell.get("text")
                if value is None:
                    candidates = cell.get("candidates", [])
                    # Several baselines are alternatives, never one numeric token.
                    value = candidates[0].get("text") if len(candidates) == 1 else None
                if value:
                    rows[r][c] = value
    return rows


def correction_state(payload, page, grid, sha):
    state = payload.get("statement_cell_corrections", {}).get(str(page))
    if state and (
        state.get("source_sha256") != sha
        or state.get("grid_revision") != grid_revision(grid)
    ):
        return None  # Historical review remains stored, but cannot relabel a new grid.
    return state


def reviewed_rows(grid, state, *, raw_candidates=False):
    rows = _rows(grid, raw_candidates)
    if state:
        for cell in state.get("cells", []):
            rows[cell["row"]][cell["column"]] = cell["text"]
    return rows


def validate_binding(query, grid, sha, state):
    if query.get("source_sha256") != sha or query.get("grid_revision") != grid_revision(
        grid
    ):
        raise ValueError("Source or grid changed; reload the statement before review")
    revision = state.get("revision", 0) if state else 0
    if (
        type(query.get("correction_revision")) is not int
        or query["correction_revision"] != revision
    ):
        raise ValueError("Statement corrections changed; reload before saving")


def save_corrections(payload, page, grid, sha, query):
    state = correction_state(payload, page, grid, sha)
    validate_binding(query, grid, sha, state)
    if query.get("reviewed") is not True:
        raise ValueError(
            "Confirm review of the cell entries against the original source"
        )
    reference = query.get("reference")
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 2000:
        raise ValueError("Provide a source review reference")
    corrections = query.get("corrections", [])
    if not isinstance(corrections, list) or len(corrections) > 10000:
        raise ValueError("Corrections must be a bounded list of source cells")
    before = reviewed_rows(grid, state, raw_candidates=True)
    seen, changes = set(), []
    merged = {
        (c["row"], c["column"]): deepcopy(c) for c in (state or {}).get("cells", [])
    }
    for cell in corrections:
        if not isinstance(cell, dict) or set(cell) != {"row", "column", "text"}:
            raise ValueError("Each correction requires row, column and text")
        r, c, value = cell["row"], cell["column"], cell["text"]
        if (
            type(r) is not int
            or type(c) is not int
            or r < 0
            or c < 0
            or r >= len(before)
            or c >= len(before[r])
        ):
            raise ValueError("Correction is outside the original grid")
        if (r, c) in seen or not isinstance(value, str) or len(value) > 2000:
            raise ValueError("Duplicate cell or invalid correction text")
        seen.add((r, c))
        changes.append(dict(row=r, column=c, before=before[r][c], after=value))
        merged[r, c] = dict(row=r, column=c, text=value)
    margin_corrections = query.get("margin_corrections", [])
    if not isinstance(margin_corrections, list) or len(margin_corrections) > 10000:
        raise ValueError(
            "Margin corrections must be a bounded list of observed regions"
        )
    observed = {
        region["region_id"]: region for region in grid.get("source_margin_regions", [])
    }
    margins = {
        item["region_id"]: deepcopy(item) for item in (state or {}).get("margins", [])
    }
    seen_margins = set()
    for annotation in margin_corrections:
        if not isinstance(annotation, dict) or set(annotation) != {"region_id", "text"}:
            raise ValueError(
                "Margin annotation requires an observed region ID and text"
            )
        region_id, value = annotation["region_id"], annotation["text"]
        if not isinstance(region_id, str) or region_id not in observed:
            raise ValueError("Unknown original source margin region")
        if region_id in seen_margins or not isinstance(value, str) or len(value) > 2000:
            raise ValueError("Duplicate region or invalid margin annotation text")
        seen_margins.add(region_id)
        previous_text = margins.get(region_id, {}).get(
            "text", observed[region_id].get("text")
        )
        changes.append(
            dict(region_id=region_id, before=previous_text, after=value, origin="human")
        )
        margins[region_id] = dict(region_id=region_id, text=value, origin="human")
    revision = (state or {}).get("revision", 0) + 1
    event = dict(
        source_sha256=sha,
        grid_revision=grid_revision(grid),
        revision=revision,
        reference=reference.strip(),
        recorded_at=datetime.now(timezone.utc).isoformat(),
        changes=changes,
    )
    # Never mutate historical events, even when an OCR-version change makes them stale.
    previous = payload.get("statement_cell_corrections", {}).get(str(page), {})
    state = dict(
        source_sha256=sha,
        grid_revision=grid_revision(grid),
        revision=revision,
        cells=list(merged.values()),
        margins=list(margins.values()),
        audit=previous.get("audit", []) + [event],
    )
    payload.setdefault("statement_cell_corrections", {})[str(page)] = state
    return state


def editor_response(grid, state):
    response = deepcopy(grid)
    margins = {item["region_id"]: item for item in (state or {}).get("margins", [])}
    editable_margins = deepcopy(grid.get("source_margin_regions", []))
    for region in editable_margins:
        annotation = margins.get(region["region_id"])
        region["editable_text"] = (
            annotation["text"] if annotation else region.get("text")
        )
        region["origin"] = "human" if annotation else "machine"
    response.update(
        grid_revision=grid_revision(grid),
        correction_revision=(state or {}).get("revision", 0),
        editable_rows=reviewed_rows(grid, state, raw_candidates=True),
        corrected_cells=deepcopy((state or {}).get("cells", [])),
        corrected_margins=deepcopy((state or {}).get("margins", [])),
        editable_margin_regions=editable_margins,
        correction_audit=deepcopy((state or {}).get("audit", [])),
        reference_only=True,
    )
    return response
