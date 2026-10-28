"""Synthetic source tests; no personal statements or OCR dependency."""

import hashlib
import io
import json
import pymupdf
import pytest
from test_suite_workflow import client
from ifms_suite.storage import database
from ifms_suite.statement_grid import GRID_EXTRACTION_VERSION


@pytest.fixture
def grid_source(client):
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    ident = client.post(
        "/suite/api/imports",
        data={"kind": "due_drawn", "file": (io.BytesIO(data), "synthetic.pdf")},
    ).json["id"]
    grid = {
        "extraction_version": GRID_EXTRACTION_VERSION,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_page": 1,
        "cells": [
            {
                "row": 0,
                "column": 0,
                "text": None,
                "candidates": [{"text": "Jul-2026", "confidence": 0.6}],
                "status": "uncertain",
            },
            {
                "row": 0,
                "column": 1,
                "text": "120",
                "candidates": [],
                "status": "recognized",
            },
            {
                "row": 0,
                "column": 2,
                "text": None,
                "candidates": [{"text": "1O0", "confidence": 0.8}],
                "status": "uncertain",
            },
        ],
        "table_rows": [[None, "120", None, "120", "100"]],
        "semantic_rows": [],
    }
    with client.application.app_context(), database() as db:
        row = db.execute(
            "SELECT payload FROM suite_imports WHERE id=?", (ident,)
        ).fetchone()
        payload = json.loads(row["payload"])
        payload["statement_grids"] = {"1": grid}
        db.execute(
            "UPDATE suite_imports SET payload=? WHERE id=?",
            (json.dumps(payload), ident),
        )
    return ident, grid


def test_corrections_are_separate_audited_reloadable_and_source_bound(
    client, grid_source
):
    ident, raw = grid_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    initial = client.post(url, json={"page": 1}).json
    assert initial.get(
        "grid_revision"
    ), "Every editor response must bind the immutable grid"
    binding = {
        k: initial[k] for k in ("source_sha256", "grid_revision", "correction_revision")
    }
    response = client.post(
        url,
        json=dict(
            binding,
            page=1,
            corrections=[
                {"row": 0, "column": 0, "text": "Jul-2026"},
                {"row": 0, "column": 2, "text": "100"},
            ],
            reviewed=True,
            reference="Checked original synthetic page",
        ),
    )
    assert response.status_code == 200
    saved = response.json
    assert saved["editable_rows"] == [["Jul-2026", "120", "100", "120", "100"]]
    assert saved["table_rows"] == raw["table_rows"]
    assert saved["cells"] == raw["cells"]
    assert saved["semantic_rows"] == []
    assert saved["correction_revision"] == 1
    assert (
        client.post(url, json={"page": 1}).json["editable_rows"]
        == saved["editable_rows"]
    )
    with client.application.app_context(), database() as db:
        payload = json.loads(
            db.execute(
                "SELECT payload FROM suite_imports WHERE id=?", (ident,)
            ).fetchone()["payload"]
        )
    assert payload["statement_grids"]["1"] == raw
    audit = payload["statement_cell_corrections"]["1"]["audit"]
    assert audit[0]["source_sha256"] == raw["source_sha256"]
    assert audit[0]["reference"] == "Checked original synthetic page"
    assert audit[0]["changes"][1]["before"] == "1O0"
    assert audit[0]["changes"][1]["after"] == "100"
    assert audit[0]["recorded_at"]
    assert (
        client.post(
            url, json=dict(binding, page=1, corrections=[], reference="Old editor")
        ).status_code
        == 400
    )
    for field in ("source_sha256", "grid_revision"):
        bad = dict(binding, correction_revision=1)
        bad[field] = "stale"
        assert (
            client.post(
                url, json=dict(bad, page=1, corrections=[], reference="Bad source")
            ).status_code
            == 400
        )


def test_reviewed_mapping_uses_corrected_reference_only(client, grid_source):
    ident, raw = grid_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    initial = client.post(url, json={"page": 1}).json
    binding = {
        k: initial.get(k)
        for k in ("source_sha256", "grid_revision", "correction_revision")
    }
    mapping = {
        "month_column": 0,
        "groups": {"due": {"Basic": 1, "Total": 3}, "drawn": {"Basic": 2, "Total": 4}},
    }
    result = client.post(
        url,
        json=dict(
            binding,
            page=1,
            corrections=[
                {"row": 0, "column": 0, "text": "Jul-2026"},
                {"row": 0, "column": 2, "text": "100"},
            ],
            mapping=mapping,
            reviewed=True,
            reference="Original headings and cells",
        ),
    )
    assert result.status_code == 200
    assert result.json["semantic_rows"][0]["due"]["Basic"] == "120.00"
    assert result.json["semantic_rows"][0]["drawn"]["Basic"] == "100.00"
    assert result.json["reference_only"] is True
    assert result.json["table_rows"] == raw["table_rows"]


def test_cell_outside_grid_and_unreviewed_mapping_rejected(client, grid_source):
    ident, _ = grid_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    initial = client.post(url, json={"page": 1}).json
    binding = {
        k: initial.get(k)
        for k in ("source_sha256", "grid_revision", "correction_revision")
    }
    result = client.post(
        url,
        json=dict(
            binding,
            page=1,
            corrections=[{"row": 12, "column": 0, "text": "100"}],
            reviewed=True,
            reference="Check",
        ),
    )
    assert result.status_code == 400
    assert (
        client.post(
            url, json=dict(binding, page=1, mapping={}, reference="Headers")
        ).status_code
        == 400
    )


def test_source_image_has_png_and_checks_page(client, grid_source):
    ident, _ = grid_source
    response = client.get(f"/suite/api/imports/{ident}/statement_grid/1/image")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert (
        client.get(f"/suite/api/imports/{ident}/statement_grid/999/image").status_code
        == 400
    )


def test_multiple_candidate_lines_do_not_join_into_one_editable_amount():
    from ifms_suite.statement_corrections import editor_response

    raw = dict(
        table_rows=[[None]],
        cells=[
            dict(
                row=0,
                column=0,
                text=None,
                candidates=[dict(text="120"), dict(text="100")],
            )
        ],
    )
    response = editor_response(raw, None)
    assert response["editable_rows"] == [[None]]
    assert response["cells"][0]["candidates"] == raw["cells"][0]["candidates"]


def test_editing_cells_invalidates_previously_promoted_reference_rows(
    client, grid_source
):
    ident, _ = grid_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    grid = client.post(url, json={"page": 1}).json
    binding = {
        k: grid[k] for k in ("source_sha256", "grid_revision", "correction_revision")
    }
    mapping = {
        "month_column": 0,
        "groups": {"due": {"Basic": 1, "Total": 3}, "drawn": {"Basic": 2, "Total": 4}},
    }
    promoted = client.post(
        url,
        json=dict(
            binding,
            page=1,
            corrections=[
                {"row": 0, "column": 0, "text": "Jul-2026"},
                {"row": 0, "column": 2, "text": "100"},
            ],
            mapping=mapping,
            reviewed=True,
            reference="Original checked",
        ),
    ).json
    assert len(promoted["semantic_rows"]) == 1
    binding["correction_revision"] = promoted["correction_revision"]
    edited = client.post(
        url,
        json=dict(
            binding,
            page=1,
            corrections=[{"row": 0, "column": 2, "text": ""}],
            reviewed=True,
            reference="Unreadable after recheck",
        ),
    ).json
    assert edited["semantic_rows"] == []
    assert edited["editable_rows"][0][2] == ""
    with client.application.app_context(), database() as db:
        payload = json.loads(
            db.execute(
                "SELECT payload FROM suite_imports WHERE id=?", (ident,)
            ).fetchone()["payload"]
        )
    assert "1" not in payload["statement_reference_rows"]


def test_original_source_bytes_must_still_match_before_editing(client, grid_source):
    from pathlib import Path

    ident, grid = grid_source
    path = (
        Path(client.application.config["UPLOAD_FOLDER"])
        / "suite"
        / (grid["source_sha256"] + ".pdf")
    )
    path.write_bytes(b"changed synthetic source")
    assert (
        client.post(
            f"/suite/api/imports/{ident}/statement_grid", json={"page": 1}
        ).status_code
        == 400
    )
    assert (
        client.get(f"/suite/api/imports/{ident}/statement_grid/1/image").status_code
        == 400
    )


def test_saving_cell_corrections_requires_explicit_original_review(client, grid_source):
    ident, _ = grid_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    initial = client.post(url, json={"page": 1}).json
    binding = {
        k: initial[k] for k in ("source_sha256", "grid_revision", "correction_revision")
    }
    for reviewed in (None, False, "true"):
        result = client.post(
            url,
            json=dict(
                binding,
                page=1,
                corrections=[{"row": 0, "column": 2, "text": "100"}],
                reference="Original",
                reviewed=reviewed,
            ),
        )
        assert result.status_code == 400
        assert "review" in result.json["error"].lower()
    assert client.post(url, json={"page": 1}).json["correction_revision"] == 0


def test_machine_facts_refresh_invalidates_mapped_statement_only_preserving_raw_audit(
    monkeypatch,
):
    import hashlib
    from copy import deepcopy
    from ifms_suite import document_facts
    from ifms_suite.source_evidence import source_facts

    data = b"synthetic immutable source"
    raw = {"1": {"table_rows": [["original machine cell"]]}}
    corrections = {
        "1": {
            "cells": [{"row": 0, "column": 0, "text": "corrected"}],
            "audit": [{"reference": "Original page"}],
        }
    }
    payload = dict(
        machine_facts={"facts_version": "obsolete"},
        machine_facts_version="obsolete",
        statement_grids=deepcopy(raw),
        statement_cell_corrections=deepcopy(corrections),
        statement_reference_rows={"1": [{"month": "2026-07"}]},
        statement_column_reviews=[{"page": 1, "reference": "Old mapping"}],
    )
    monkeypatch.setattr(
        document_facts,
        "extract_document_facts",
        lambda _: {"facts_version": document_facts.FACTS_VERSION, "bills": []},
    )
    source_facts(data, hashlib.sha256(data).hexdigest(), payload, refresh=True)
    assert payload["statement_reference_rows"] == {}
    assert payload["statement_column_reviews"] == []
    assert payload["statement_grids"] == raw
    assert payload["statement_cell_corrections"] == corrections
    archived = payload["superseded_case_reviews"][-1]["reviews"]
    assert archived["statement_reference_rows"] == {"1": [{"month": "2026-07"}]}
    assert archived["statement_column_reviews"][0]["reference"] == "Old mapping"


def test_cached_machine_facts_cannot_keep_reference_rows_from_obsolete_grid():
    import hashlib
    from copy import deepcopy
    from ifms_suite.document_facts import FACTS_VERSION
    from ifms_suite.statement_grid import GRID_EXTRACTION_VERSION
    from ifms_suite.source_evidence import source_facts

    data = b"synthetic unchanged machine source"
    sha = hashlib.sha256(data).hexdigest()
    raw = {"1": {"extraction_version": "obsolete-grid", "source_sha256": sha}}
    corrections = {"1": {"audit": [{"reference": "Preserve historical cell review"}]}}
    payload = dict(
        machine_facts={"facts_version": FACTS_VERSION},
        machine_facts_version=FACTS_VERSION,
        statement_grids=deepcopy(raw),
        statement_cell_corrections=deepcopy(corrections),
        statement_reference_rows={"1": [{"month": "2026-07"}]},
        statement_column_reviews=[
            {"page": 1, "source_sha256": sha, "reference": "Old mapping"}
        ],
    )
    assert GRID_EXTRACTION_VERSION != raw["1"]["extraction_version"]
    source_facts(data, sha, payload)
    assert payload["statement_reference_rows"] == {}
    assert payload["statement_column_reviews"] == []
    assert payload["statement_grids"] == raw
    assert payload["statement_cell_corrections"] == corrections
    archive = payload["superseded_case_reviews"][-1]
    assert archive["reason"] == "statement_grid_changed"
    assert archive["reviews"]["statement_reference_rows"]["1"][0]["month"] == "2026-07"
