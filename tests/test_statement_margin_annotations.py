"""Review-only transcriptions for observed edge ink without inventing columns."""

import json
import pytest
from test_statement_corrections import client, grid_source
from ifms_suite.storage import database


@pytest.fixture
def margin_source(client, grid_source):
    ident, raw = grid_source
    raw["source_margin_regions"] = [
        dict(
            region_id="right_margin_r0",
            row=0,
            column=None,
            source_polygon=[[200, 20], [240, 20], [240, 40], [200, 40]],
            text=None,
            amount=None,
            status="source_geometry_unresolved",
            review_required=True,
            candidates=[
                dict(text="1O0", confidence=0.98),
                dict(text="100", confidence=0.99),
            ],
        )
    ]
    with client.application.app_context(), database() as db:
        payload = json.loads(
            db.execute(
                "SELECT payload FROM suite_imports WHERE id=?", (ident,)
            ).fetchone()["payload"]
        )
        payload["statement_grids"]["1"] = raw
        db.execute(
            "UPDATE suite_imports SET payload=? WHERE id=?",
            (json.dumps(payload), ident),
        )
    return ident, raw


def _binding(response):
    return {
        k: response[k]
        for k in ("source_sha256", "grid_revision", "correction_revision")
    }


def test_margin_annotation_is_separate_audited_human_text_not_semantic_value(
    client, margin_source
):
    ident, raw = margin_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    initial = client.post(url, json={"page": 1}).json
    binding = _binding(initial)
    result = client.post(
        url,
        json=dict(
            binding,
            page=1,
            margin_corrections=[dict(region_id="right_margin_r0", text="100")],
            reviewed=True,
            reference="Original clipped edge",
        ),
    ).json
    assert result.get("correction_revision") == 1, result
    assert result["corrected_margins"] == [
        dict(region_id="right_margin_r0", text="100", origin="human")
    ]
    assert result["editable_margin_regions"][0]["editable_text"] == "100"
    assert result["source_margin_regions"] == raw["source_margin_regions"]
    assert result["corrected_cells"] == []
    assert result["table_rows"] == raw["table_rows"]
    assert result["semantic_rows"] == []
    event = result["correction_audit"][-1]
    assert event["changes"] == [
        dict(region_id="right_margin_r0", before=None, after="100", origin="human")
    ]
    assert event["reference"] == "Original clipped edge"
    assert event["source_sha256"] == raw["source_sha256"]
    assert (
        client.post(url, json={"page": 1}).json["corrected_margins"]
        == result["corrected_margins"]
    )
    assert (
        client.post(
            url,
            json=dict(
                binding,
                page=1,
                margin_corrections=[],
                reviewed=True,
                reference="Stale editor",
            ),
        ).status_code
        == 400
    )
    with client.application.app_context(), database() as db:
        payload = json.loads(
            db.execute(
                "SELECT payload FROM suite_imports WHERE id=?", (ident,)
            ).fetchone()["payload"]
        )
    assert payload["statement_grids"]["1"] == raw
    assert (
        payload["statement_cell_corrections"]["1"]["margins"]
        == result["corrected_margins"]
    )


def test_margin_rejects_unknown_region_and_unreviewed_or_stale_source(
    client, margin_source
):
    ident, _ = margin_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    initial = client.post(url, json={"page": 1}).json
    binding = _binding(initial)
    valid = dict(
        binding,
        page=1,
        margin_corrections=[dict(region_id="right_margin_r0", text="100")],
        reviewed=True,
        reference="Original",
    )
    invalid = [
        dict(valid, reviewed=False),
        dict(valid, source_sha256="stale"),
        dict(valid, grid_revision="stale"),
        dict(valid, margin_corrections=[dict(region_id="invented_column", text="100")]),
        dict(
            valid,
            margin_corrections=[
                dict(region_id="right_margin_r0", text="100", amount="100")
            ],
        ),
        dict(valid, margin_corrections=valid["margin_corrections"] * 2),
    ]
    for query in invalid:
        assert client.post(url, json=query).status_code == 400
    assert client.post(url, json={"page": 1}).json["correction_revision"] == 0


def test_margin_and_cell_reviews_share_revision_but_never_merge_into_columns(
    client, margin_source
):
    ident, _ = margin_source
    url = f"/suite/api/imports/{ident}/statement_grid"
    initial = client.post(url, json={"page": 1}).json
    mapped = client.post(
        url,
        json=dict(
            _binding(initial),
            page=1,
            corrections=[
                dict(row=0, column=0, text="Jul-2026"),
                dict(row=0, column=2, text="100"),
            ],
            mapping={
                "month_column": 0,
                "groups": {
                    "due": {"Basic": 1, "Total": 3},
                    "drawn": {"Basic": 2, "Total": 4},
                },
            },
            reviewed=True,
            reference="Original cells and headers",
        ),
    ).json
    assert len(mapped["semantic_rows"]) == 1
    margin = client.post(
        url,
        json=dict(
            _binding(mapped),
            page=1,
            margin_corrections=[dict(region_id="right_margin_r0", text="999")],
            reviewed=True,
            reference="Original margin",
        ),
    ).json
    assert margin["correction_revision"] == 2
    assert margin["corrected_cells"] == mapped["corrected_cells"]
    assert margin["semantic_rows"] == []
    assert len(margin["table_rows"][0]) == 5
    cell = client.post(
        url,
        json=dict(
            _binding(margin),
            page=1,
            corrections=[dict(row=0, column=1, text="125")],
            reviewed=True,
            reference="Original cell",
        ),
    ).json
    assert cell["corrected_margins"] == margin["corrected_margins"]
