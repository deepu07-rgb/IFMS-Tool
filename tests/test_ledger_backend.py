"""Reusable ledger behavior uses synthetic payments and source bytes only."""

import hashlib
import json
from copy import deepcopy

import pytest
from flask import Flask
from ifms_suite.storage import initialize, database
from ifms_suite.payroll import reviewed_payment

CODE = "RJXY204012345678"


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config.update(DATABASE=str(tmp_path / "ledger.db"), UPLOAD_FOLDER=str(tmp_path))
    with app.app_context():
        initialize()
        yield app


def payment(**changes):
    return dict(
        dict(
            employee_code=CODE,
            pay_month="2040-01",
            bill_no="123456789",
            bill_type="Regular Salary",
            allowances={"BASIC": "100", "DA": "50"},
            deductions={},
            reviewed=True,
            reference="Synthetic verified bill",
        ),
        **changes,
    )


def source(db, app):
    from ifms_suite.document_facts import FACTS_VERSION
    from ifms_suite.source_bill_review import bill_review_requests

    data = b"%PDF-synthetic-immutable-evidence"
    digest = hashlib.sha256(data).hexdigest()
    raw = dict(payment(), source_pages=[1], complete=False)
    facts = dict(facts_version=FACTS_VERSION, bills=[raw], issues=[])
    req = bill_review_requests(dict(facts, source_sha256=digest))[0]
    review = dict(
        request_id=req["request_id"],
        reviewed=True,
        reference="Original synthetic bill",
        record=dict(
            raw, printed_gross="150", printed_deductions="0", printed_net="150"
        ),
    )
    payload = dict(
        file_kind="pdf",
        machine_facts=facts,
        machine_facts_version=FACTS_VERSION,
        source_bill_reviews=[review],
    )
    ident = db.execute(
        "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
        (digest, "synthetic.pdf", json.dumps(payload)),
    ).lastrowid
    from pathlib import Path

    folder = Path(app.config["UPLOAD_FOLDER"]) / "suite"
    folder.mkdir(exist_ok=True)
    (folder / (digest + ".pdf")).write_bytes(data)
    return ident, payload


def test_saved_regular_salary_reused_with_missing_heads_preserved(app):
    from ifms_suite.bill_routes import _history_facts

    with database() as db:
        pid = reviewed_payment(db, payment())
        facts = _history_facts(db, {"bills": [], "issues": []}, CODE)
    assert len(facts["bills"]) == 1
    assert facts["bills"][0]["id"] == pid
    assert "HRA" not in facts["bills"][0]["allowances"]


def test_monthly_ledger_separates_drawn_and_prior_credit_and_blocks_conflict(app):
    from ifms_suite.ledger import employee_ledger

    with database() as db:
        reviewed_payment(db, payment())
        reviewed_payment(db, payment(bill_no="223456789", bill_type="DA arrear"))
        first = employee_ledger(db, CODE)
        assert len(first["months"][0]["regular_salary"]) == 1
        assert len(first["months"][0]["prior_credits"]) == 1
        assert first["months"][0]["status"] == "reviewed"
        reviewed_payment(db, payment(bill_no="323456789"))
        assert employee_ledger(db, CODE)["months"][0]["status"] == "conflict"


def test_source_import_requires_actual_source_review_and_detects_staleness(app):
    from ifms_suite.ledger import save_source_payments, employee_ledger

    with database() as db:
        ident, payload = source(db, app)
        ids = save_source_payments(db, ident, [0])
        assert len(ids) == 1
        record = employee_ledger(db, CODE)["months"][0]["regular_salary"][0]
        assert record["id"] == ids[0]
        assert record["ledger_source"]["source_import"] == ident
        assert record["ledger_source"]["source_pages"] == [1]
        with pytest.raises(ValueError, match="already saved"):
            save_source_payments(db, ident, [0])
        payload["source_bill_reviews"] = []
        db.execute(
            "UPDATE suite_imports SET payload=? WHERE id=?",
            (json.dumps(payload), ident),
        )
        assert employee_ledger(db, CODE)["months"][0]["status"] == "stale"
        from ifms_suite.bill_routes import _history_facts

        with pytest.raises(ValueError, match="stale|changed"):
            _history_facts(db, {"bills": []}, CODE)


def test_unreviewed_source_cannot_be_saved_by_client_confirmation(app):
    from ifms_suite.ledger import save_source_payments

    with database() as db:
        ident, payload = source(db, app)
        payload["source_bill_reviews"] = []
        db.execute(
            "UPDATE suite_imports SET payload=? WHERE id=?",
            (json.dumps(payload), ident),
        )
        with pytest.raises(ValueError, match="review"):
            save_source_payments(db, ident, [0])
        assert db.execute("SELECT COUNT(*) FROM suite_payments").fetchone()[0] == 0


def test_same_source_bill_with_different_deductions_blocks_history(app):
    from ifms_suite.bill_routes import _history_facts

    with database() as db:
        reviewed_payment(db, payment(deductions={"GPF": "10"}))
        facts = _history_facts(db, {"bills": [payment(deductions={"GPF": "20"})]}, CODE)
        assert any(i["kind"] == "history_conflict" for i in facts["issues"])


def test_bulk_confirmation_saves_only_complete_reconciled_machine_bills(app):
    from ifms_suite.ledger import save_source_payments

    with database() as db:
        ident, payload = source(db, app)
        payload["source_bill_reviews"] = []
        raw = payload["machine_facts"]["bills"][0]
        raw.update(
            complete=True,
            printed_gross="150",
            printed_deductions="0",
            printed_net="150",
        )
        db.execute(
            "UPDATE suite_imports SET payload=? WHERE id=?",
            (json.dumps(payload), ident),
        )
        assert (
            len(save_source_payments(db, ident, [0], reference="Original bulk check"))
            == 1
        )


def test_source_batch_save_rolls_back_when_a_selected_bill_conflicts(app):
    from ifms_suite.ledger import save_source_payments

    with database() as db:
        ident, payload = source(db, app)
        reviewed_payment(db, payment(bill_no="999999999"))
        with pytest.raises(ValueError, match="regular salary"):
            save_source_payments(db, ident, [0])
        assert db.execute("SELECT COUNT(*) FROM suite_payments").fetchone()[0] == 1


def test_original_bytes_tampering_marks_saved_source_stale(app):
    from pathlib import Path
    from ifms_suite.ledger import save_source_payments, employee_ledger

    with database() as db:
        ident, _ = source(db, app)
        save_source_payments(db, ident, [0])
        original = next((Path(app.config["UPLOAD_FOLDER"]) / "suite").glob("*.pdf"))
        original.write_bytes(b"changed original")
        month = employee_ledger(db, CODE)["months"][0]
        assert month["status"] == "stale"
        assert "Original source changed" in month["issues"][0]


def test_atomic_batch_rejects_late_conflict_without_partial_saves(app):
    from ifms_suite.ledger import save_source_payments
    from ifms_suite.source_bill_review import bill_review_requests

    with database() as db:
        ident, payload = source(db, app)
        raw = payload["machine_facts"]["bills"][0]
        payload["machine_facts"]["bills"].append(dict(raw, pay_month="2040-02"))
        from ifms_suite.bill_routes import case_facts

        # Adding a second bill does not change the request ID of the first bill.
        req = bill_review_requests(
            dict(
                payload["machine_facts"],
                source_sha256=db.execute(
                    "SELECT sha256 FROM suite_imports WHERE id=?", (ident,)
                ).fetchone()[0],
            )
        )[1]
        payload["source_bill_reviews"].append(
            dict(
                payload["source_bill_reviews"][0],
                request_id=req["request_id"],
                record=dict(
                    payload["source_bill_reviews"][0]["record"], pay_month="2040-02"
                ),
            )
        )
        db.execute(
            "UPDATE suite_imports SET payload=? WHERE id=?",
            (json.dumps(payload), ident),
        )
        reviewed_payment(db, payment(pay_month="2040-02", bill_no="999999999"))
        with pytest.raises(ValueError, match="regular salary"):
            save_source_payments(db, ident, [0, 1])
        assert db.execute("SELECT COUNT(*) FROM suite_payments").fetchone()[0] == 1


def test_ledger_http_contract_requires_confirmation_and_does_not_accept_payment_values(
    app,
):
    from flask import Blueprint
    from ifms_suite.ledger_routes import register_ledger

    suite = Blueprint("ledger_test", __name__)
    register_ledger(suite)
    app.register_blueprint(suite, url_prefix="/suite")

    @app.errorhandler(ValueError)
    def invalid(error):
        return {"error": str(error)}, 400

    with database() as db:
        ident, _ = source(db, app)
    client = app.test_client()
    response = client.post(
        f"/suite/api/imports/{ident}/ledger", json={"bill_indexes": [0]}
    )
    assert response.status_code == 400
    response = client.post(
        f"/suite/api/imports/{ident}/ledger",
        json={"reviewed": True, "bill_indexes": [0], "allowances": {"BASIC": "9999"}},
    )
    assert response.status_code == 201
    listing = client.get("/suite/api/ledger", query_string={"employee_code": CODE}).json
    assert listing["months"][0]["regular_salary"][0]["allowances"]["BASIC"] == "100.00"


def test_reused_salary_retains_original_page_evidence_and_ledger_link(app):
    from ifms_suite.bill_routes import _history_facts

    with database() as db:
        pid = reviewed_payment(
            db, payment(evidence=[{"page": 2, "text": "Synthetic original BASIC 100"}])
        )
        bill = _history_facts(db, {"bills": []}, CODE)["bills"][0]
        assert any(e.get("page") == 2 for e in bill["evidence"])
        assert any(e.get("payment_id") == pid for e in bill["evidence"])


def test_saved_employee_directory_includes_unregistered_codes_once(app):
    from flask import Blueprint
    from ifms_suite.ledger_routes import register_ledger

    suite = Blueprint("ledger_directory_test", __name__)
    register_ledger(suite)
    app.register_blueprint(suite, url_prefix="/suite")
    with database() as db:
        reviewed_payment(db, payment())
        reviewed_payment(db, payment(pay_month="2040-02"))
        reviewed_payment(db, payment(employee_code="RJZZ204012345678"))
        db.execute(
            "INSERT INTO suite_employees VALUES(?,?,?)",
            (CODE, "Synthetic Person", "{}"),
        )
    response = app.test_client().get("/suite/api/ledger/employees")
    assert response.status_code == 200
    assert response.json == [
        {"employee_code": CODE, "name": "Synthetic Person"},
        {"employee_code": "RJZZ204012345678", "name": ""},
    ]


@pytest.mark.parametrize(
    "field,source_value,saved_value",
    [
        (
            "covered_dates",
            {"start": "2040-01-01", "end": "2040-01-31"},
            {"start": "2040-01-16", "end": "2040-01-31"},
        ),
        ("monthly_basic", 0, "100"),
        (
            "allocations_by_head",
            {"BASIC": [{"start": "2040-01-01", "end": "2040-01-31", "amount": "10"}]},
            {"BASIC": [{"start": "2040-01-01", "end": "2040-01-31", "amount": "100"}]},
        ),
    ],
)
def test_source_metadata_conflicts_never_get_overwritten(
    app, field, source_value, saved_value
):
    from ifms_suite.bill_routes import _history_facts

    saved = payment(**{field: saved_value})
    if field == "allocations_by_head":
        saved["entitlement_period"] = {"start": "2040-01-01", "end": "2040-01-31"}
    with database() as db:
        reviewed_payment(db, saved)
        raw = payment(**{field: source_value})
        facts = _history_facts(db, {"bills": [raw]}, CODE)
    assert any(i["kind"] == "history_conflict" for i in facts["issues"])
    assert facts["bills"][0][field] == source_value


@pytest.mark.parametrize(
    "source_changes,saved_changes",
    [
        ({"bill_type": "Regular Salary"}, {"bill_type": "DA arrear"}),
        ({"entitlement_type": "salary"}, {"entitlement_type": "leave_encashment"}),
        ({"printed_gross": "151"}, {"printed_gross": "150"}),
        ({"printed_deductions": "1"}, {"printed_deductions": "0"}),
        ({"printed_net": "149"}, {"printed_net": "150"}),
    ],
)
def test_same_bill_category_entitlement_and_printed_totals_conflicts_block(
    app, source_changes, saved_changes
):
    from ifms_suite.bill_routes import _history_facts

    with database() as db:
        reviewed_payment(db, payment(**saved_changes))
        raw = payment(**source_changes)
        facts = _history_facts(db, {"bills": [raw]}, CODE)
    assert any(
        i["kind"] == "history_conflict" and i["blocking"]
        for i in facts.get("issues", [])
    )
    assert facts["bills"][0] == raw


def test_equivalent_bill_type_wording_and_totals_do_not_conflict(app):
    from ifms_suite.bill_routes import _history_facts

    with database() as db:
        reviewed_payment(
            db, payment(bill_type="Regular Salary Bill", printed_gross="150.00")
        )
        facts = _history_facts(
            db,
            {"bills": [payment(bill_type="regular salary", printed_gross="150")]},
            CODE,
        )
    assert not facts.get("issues")
