"""Dated office rates, reversible removal and assisted-workbook rate safeguards."""

from copy import deepcopy
import pytest
from test_suite_workflow import client
from test_worksheet import example


def rate(client, **changes):
    p = dict(
        allowance="DA",
        effective_from="2040-01-01",
        rate="60",
        basis="basic",
        reference="Synthetic DA60 order",
        order_date="2040-04-01",
    )
    p.update(changes)
    response = client.post("/suite/api/rates", json=p)
    assert response.status_code == 201, response.data
    return response.json


def increment():
    p = example(kind="increment", include_hda=True)
    p["hra_category"] = "Y"
    p["rows"][0].update(
        new_basic="25500", da_rate="60", hra_rate="20", hda_divisor="12"
    )
    return p


def test_wrong_da_rate_is_visible_and_blocks_pdf_until_corrected(client):
    rate(client)
    rate(client, allowance="HRA", category="Y", rate="20", reference="Synthetic HRA20")
    p = increment()
    p["rows"][0]["da_rate"] = "62"
    calc = client.post("/suite/api/worksheets/calculate", json=p).json
    assert calc["status"] == "incomplete"
    assert any(
        e["field"] == "da_rate" and "60" in e["message"] and "62" in e["message"]
        for e in calc["errors"]
    )
    saved = client.post("/suite/api/worksheets", json={"payload": p}).json
    assert client.get(f"/suite/api/worksheets/{saved['id']}/pdf").status_code == 400
    p["rows"][0]["da_rate"] = "60"
    good = client.post("/suite/api/worksheets/calculate", json=p).json
    assert good["status"] == "ready", good
    assert any(
        c["head"] == "DA" and c["status"] == "matched" for c in good["rate_checks"]
    )


def test_new_dated_rate_does_not_rewrite_earlier_months_and_rechecks_saved_draft(
    client,
):
    rate(client)
    p = increment()
    saved = client.post("/suite/api/worksheets", json={"payload": p}).json
    rate(
        client,
        effective_from="2040-07-01",
        rate="62",
        reference="Synthetic future revision",
    )
    loaded = client.get(f"/suite/api/worksheets/{saved['id']}").json
    assert loaded["result"]["status"] == "incomplete"
    assert client.get(f"/suite/api/worksheets/{saved['id']}/pdf").status_code == 400
    jan = increment()
    jan["rows"][0].update(month="2040-01", start="2040-01-01", end="2040-01-31")
    assert (
        client.post("/suite/api/worksheets/calculate", json=jan).json["status"]
        == "ready"
    )


def test_known_mismatch_requires_explicit_exception_reference(client):
    rate(client)
    p = increment()
    p["rows"][0].update(
        da_rate="62",
        da_override_reason="Synthetic employee-specific order overrides general DA60; independently checked",
    )
    calc = client.post("/suite/api/worksheets/calculate", json=p).json
    assert calc["status"] == "ready", calc
    assert any(
        w["field"] == "da_rate" and "exception" in w["message"].lower()
        for w in calc["warnings"]
    )


def test_midmonth_rate_change_and_hra_exemption_are_not_silently_accepted(client):
    rate(client)
    rate(client, effective_from="2040-07-15", rate="62")
    p = increment()
    calc = client.post("/suite/api/worksheets/calculate", json=p).json
    assert any(
        e["field"] == "da_rate" and "within" in e["message"].lower()
        for e in calc["errors"]
    )
    rate(client, allowance="HRA", category="Y", rate="20")
    p = example(hra_category="Y")
    p["rows"][0].update(hra_rate="0", hra_exempt=True)
    calc = client.post("/suite/api/worksheets/calculate", json=p).json
    assert calc["status"] == "incomplete"
    p["rows"][0][
        "hra_exemption_reference"
    ] = "Synthetic govt accommodation/non-eligible sanction checked"
    calc = client.post("/suite/api/worksheets/calculate", json=p).json
    assert calc["status"] == "ready", calc
    assert any(c["status"] == "exempt" for c in calc["rate_checks"])


def test_missing_rate_coverage_is_warning_not_false_rate_validation(client):
    p = increment()
    calc = client.post("/suite/api/worksheets/calculate", json=p).json
    assert calc["status"] == "ready"
    assert any(
        w["field"] == "da_rate" and "no" in w["message"].lower()
        for w in calc["warnings"]
    )


def test_archived_official_rate_stays_removed_after_seeding_and_can_restore(client):
    from ifms_suite.storage import database
    from ifms_suite.reference import load_reference

    with client.application.app_context(), database() as db:
        load_reference(db)
    existing = client.get("/suite/api/rates").json[0]
    response = client.post(
        f"/suite/api/rates/{existing['id']}/archive",
        json={
            "revision": existing.get("revision", 1),
            "reason": "Synthetic erroneous applicability removal",
            "archived": True,
        },
    )
    assert response.status_code == 200, response.data
    with client.application.app_context(), database() as db:
        load_reference(db)
    assert all(r["id"] != existing["id"] for r in client.get("/suite/api/rates").json)
    archived = client.get("/suite/api/rates/archived").json
    record = next(r for r in archived if r["id"] == existing["id"])
    restored = client.post(
        f"/suite/api/rates/{existing['id']}/archive",
        json={
            "revision": record["revision"],
            "reason": "Synthetic restore applicability",
            "archived": False,
        },
    )
    assert restored.status_code == 200
    assert any(r["id"] == existing["id"] for r in client.get("/suite/api/rates").json)
    assert len(client.get(f"/suite/api/rates/{existing['id']}/audit").json) >= 2


def test_rate_edit_conflict_and_negative_amount_are_rejected(client):
    saved = rate(client)
    p = dict(
        saved,
        rate="61",
        override_reason="Synthetic amendment",
        revision=saved.get("revision", 1),
    )
    edited = client.post(f"/suite/api/rates/{saved['id']}", json=p)
    assert edited.status_code == 200
    assert client.post(f"/suite/api/rates/{saved['id']}", json=p).status_code == 409
    assert (
        client.post(
            "/suite/api/rates",
            json=dict(
                allowance="DA", rate="-1", effective_from="2041-01-01", reference="bad"
            ),
        ).status_code
        == 400
    )
    custom = rate(client, allowance="UNIFORM ALLOWANCE", basis="fixed", rate="7000")
    assert custom["basis"] == "fixed"
