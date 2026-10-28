"""Full-subscription references never create payroll deductions."""

import json
import sqlite3

import pytest
from flask import Blueprint, Flask, jsonify


def schedule(**changes):
    body = dict(
        name="Office authority",
        scheme="GPF",
        basis="basic",
        category="",
        effective_from="2026-01-01",
        effective_to=None,
        reference="Office order 123",
        rounding="rupee",
        slabs=[
            dict(lower=0, upper=50000, kind="fixed", value=1000),
            dict(lower=50000, upper=None, kind="percent", value=6),
        ],
    )
    body.update(changes)
    return body


def test_initialize_is_idempotent_and_never_seeds_authority():
    from ifms_suite.slab_library import initialize_slabs

    db = sqlite3.connect(":memory:")
    initialize_slabs(db)
    initialize_slabs(db)
    assert db.execute("SELECT COUNT(*) FROM suite_slabs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM suite_slab_audit").fetchone()[0] == 0


@pytest.fixture
def client(tmp_path):
    from ifms_suite.slab_library import initialize_slabs, register_slabs

    app = Flask(__name__)
    app.config.update(TESTING=True, DATABASE=str(tmp_path / "slabs.sqlite"))
    with sqlite3.connect(app.config["DATABASE"]) as db:
        initialize_slabs(db)
    bp = Blueprint("slab_test", __name__)
    register_slabs(bp)
    app.register_blueprint(bp)

    @app.errorhandler(ValueError)
    def bad_request(exc):
        return jsonify(error=str(exc)), 400

    return app.test_client()


def create(client, **changes):
    response = client.post("/api/slabs", json=schedule(**changes))
    assert response.status_code == 201, response.json
    return response.json


def suggest(client, **params):
    query = dict(scheme="GPF", on="2026-02-01", basic=50000)
    query.update(params)
    return client.get("/api/slabs/suggest", query_string=query)


def test_create_get_search_and_audit_preserve_authority(client):
    row = create(client)
    assert row["revision"] == 1 and row["archived"] is False
    assert row["audit_count"] == 1
    assert client.get(f"/api/slabs/{row['id']}").json["reference"] == "Office order 123"
    assert len(client.get("/api/slabs?q=order+123&scheme=GPF").json["slabs"]) == 1
    assert client.get("/api/slabs?scheme=SI").json["slabs"] == []
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        audit = db.execute(
            "SELECT action,previous_payload,new_payload FROM suite_slab_audit"
        ).fetchone()
    assert audit[0] == "create" and audit[1] is None
    assert json.loads(audit[2])["reference"] == "Office order 123"


@pytest.mark.parametrize(
    "basic,expected", [(0, 1000), (49999.99, 1000), (50000, 3000), (60000, 3600)]
)
def test_lower_inclusive_upper_exclusive_and_percent(client, basic, expected):
    create(client)
    response = suggest(client, basic=basic)
    assert response.status_code == 200
    assert response.json["amount"] == f"{expected:.2f}"
    assert response.json["status"] == "ok"
    assert response.json["full_subscription_reference_only"] is True
    assert response.json["reference"] == "Office order 123"
    assert response.json["schedule"]["id"]
    assert response.json["slab"]["lower"] == (0 if basic < 50000 else 50000)


@pytest.mark.parametrize(
    "basis,inputs,rounding,expected",
    [
        ("basic_da", dict(basic=10000, da=2500), "rupee", 751),
        ("gross", dict(gross=12500), "paise", 750.63),
        ("basic", dict(basic=12500), "paise", 750.63),
    ],
)
def test_basis_and_decimal_half_up_rounding(client, basis, inputs, rounding, expected):
    create(
        client,
        basis=basis,
        rounding=rounding,
        slabs=[dict(lower=0, upper=None, kind="percent", value="6.005")],
    )
    assert suggest(client, **inputs).json["amount"] == f"{expected:.2f}"


def test_direct_suggestion_and_api_do_not_write_any_records(client):
    from ifms_suite.slab_library import suggest_slab

    create(client)
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        db.row_factory = sqlite3.Row
        before = db.total_changes
        result = suggest_slab(db, "GPF", "2026-03-01", basic=50000)
        assert result["amount"] == "3000.00"
        assert db.total_changes == before
        assert {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } == {"suite_slabs", "suite_slab_audit"}
    assert suggest(client).json["amount"] == "3000.00"


def test_latest_schedule_exact_category_and_effective_end(client):
    create(client)
    create(
        client,
        name="Future",
        effective_from="2026-04-01",
        effective_to="2026-04-30",
        slabs=[dict(lower=0, upper=None, kind="fixed", value=2222)],
    )
    create(
        client,
        category="special",
        slabs=[dict(lower=0, upper=None, kind="fixed", value=999)],
    )
    assert suggest(client, on="2026-03-31").json["amount"] == "3000.00"
    assert suggest(client, on="2026-04-01").json["amount"] == "2222.00"
    assert suggest(client, on="2026-04-30").json["amount"] == "2222.00"
    assert suggest(client, on="2026-05-01").json["amount"] == "3000.00"
    assert suggest(client, category="special").json["amount"] == "999.00"
    assert suggest(client, category="other").json["status"] == "missing"


@pytest.mark.parametrize(
    "changes,query",
    [
        ({"effective_from": "2027-01-01"}, {}),
        ({"effective_to": "2026-01-31"}, {}),
        ({"slabs": [dict(lower=100, upper=500, kind="fixed", value=10)]}, {"basic": 0}),
        ({"slabs": [dict(lower=0, upper=500, kind="fixed", value=10)]}, {"basic": 500}),
        (
            {
                "slabs": [
                    dict(lower=0, upper=100, kind="fixed", value=10),
                    dict(lower=200, upper=None, kind="fixed", value=20),
                ]
            },
            {"basic": 150},
        ),
    ],
)
def test_uncovered_date_salary_and_gaps_return_missing_never_zero(
    client, changes, query
):
    create(client, **changes)
    result = suggest(client, **query).json
    assert result["status"] == "missing" and result["amount"] is None


def test_same_latest_effective_date_is_ambiguous(client):
    create(client)
    create(client, name="Conflicting authority")
    result = suggest(client).json
    assert result["status"] == "ambiguous" and result["amount"] is None


def test_edit_archive_restore_require_current_revision_and_keep_audit(client):
    row = create(client)
    route = f"/api/slabs/{row['id']}"
    edited = client.post(
        route,
        json=dict(schedule(name="Edited"), revision=1, reason="Correct authority"),
    )
    assert edited.status_code == 200 and edited.json["revision"] == 2
    assert client.post(route, json=dict(schedule(), revision=1)).status_code == 409
    assert (
        client.post(
            route + "/archive",
            json=dict(revision=2, reason="Superseded", archived=True),
        ).json["revision"]
        == 3
    )
    assert client.get("/api/slabs").json["slabs"] == []
    assert (
        client.get("/api/slabs?include_archived=true").json["slabs"][0]["archived"]
        is True
    )
    assert suggest(client).json["status"] == "missing"
    assert (
        client.post(
            route + "/archive", json=dict(revision=2, reason="Stale", archived=False)
        ).status_code
        == 409
    )
    restored = client.post(
        route + "/archive", json=dict(revision=3, reason="Reinstated", archived=False)
    )
    assert restored.status_code == 200 and restored.json["revision"] == 4
    assert restored.json["audit_count"] == 4
    assert suggest(client).json["amount"] == "3000.00"
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        assert [
            r[0] for r in db.execute("SELECT action FROM suite_slab_audit ORDER BY id")
        ] == ["create", "edit", "archive", "restore"]


@pytest.mark.parametrize(
    "changes",
    [
        {"scheme": "invented"},
        {"basis": "net"},
        {"rounding": "truncate"},
        {"reference": ""},
        {"name": ""},
        {"effective_from": "2026-02-30"},
        {"effective_to": "2025-01-01"},
        {"category": []},
        {"slabs": []},
        {"slabs": {}},
        {"slabs": [dict(lower=-1, upper=None, kind="fixed", value=1)]},
        {"slabs": [dict(lower=0, upper=0, kind="fixed", value=1)]},
        {"slabs": [dict(lower=0, upper=None, kind="fixed", value="NaN")]},
        {"slabs": [dict(lower="Infinity", upper=None, kind="fixed", value=1)]},
        {"slabs": [dict(lower=0, upper=None, kind="fixed", value=-1)]},
        {"slabs": [dict(lower=False, upper=None, kind="fixed", value=1)]},
        {"slabs": [dict(lower=0, upper=None, kind="mystery", value=1)]},
        {
            "slabs": [
                dict(lower=100, upper=200, kind="fixed", value=1),
                dict(lower=0, upper=100, kind="fixed", value=1),
            ]
        },
        {
            "slabs": [
                dict(lower=0, upper=200, kind="fixed", value=1),
                dict(lower=100, upper=None, kind="fixed", value=1),
            ]
        },
        {
            "slabs": [
                dict(lower=0, upper=None, kind="fixed", value=1),
                dict(lower=100, upper=None, kind="fixed", value=1),
            ]
        },
    ],
)
def test_malformed_authority_is_rejected_without_write(client, changes):
    response = client.post("/api/slabs", json=schedule(**changes))
    assert response.status_code == 400
    assert client.get("/api/slabs").json["slabs"] == []


@pytest.mark.parametrize(
    "query",
    [
        {"basic": "nan"},
        {"basic": -1},
        {"on": "invalid"},
        {"gross": "inf"},
        {"da": -1},
        {"scheme": "unknown"},
    ],
)
def test_invalid_suggestion_inputs_are_rejected(client, query):
    create(client)
    assert suggest(client, **query).status_code == 400


def test_missing_salary_inputs_are_visible_and_archive_needs_reason(client):
    row = create(client, basis="basic_da")
    result = suggest(client).json
    assert result["status"] == "missing" and result["amount"] is None
    assert (
        client.post(
            f"/api/slabs/{row['id']}/archive", json=dict(revision=1, archived=True)
        ).status_code
        == 400
    )
    assert client.get("/api/slabs/99999").status_code == 404
