import hashlib
import pytest
from test_suite_workflow import client


def test_shared_source_cache_preserves_original_and_rejects_changed_bytes(monkeypatch):
    from ifms_suite.source_evidence import source_facts
    from ifms_suite import document_facts

    seen = []
    monkeypatch.setattr(
        document_facts,
        "extract_document_facts",
        lambda data: seen.append(data) or {"bills": [], "issues": []},
    )
    data = b"%PDF-original"
    digest = hashlib.sha256(data).hexdigest()
    payload = {}
    first = source_facts(data, digest, payload)
    assert source_facts(data, digest, payload) == first
    assert seen == [data]
    with pytest.raises(ValueError, match="changed"):
        source_facts(b"changed", digest, payload)


def test_geometry_adapter_does_not_turn_missing_deductions_into_zero():
    from ifms_suite.source_evidence import payment_candidates

    facts = {
        "bills": [
            {
                "employee_code": "RJTEST",
                "pay_month": "2026-07",
                "bill_no": "123",
                "allowances": {"Basic": "100"},
                "complete": True,
                "printed_gross": "100",
                "printed_deductions": "10",
                "printed_net": "90",
                "source_pages": [1],
            }
        ],
        "issues": [],
    }
    result = payment_candidates(facts)
    row = result["payments"][0]
    assert row["deductions"] == {}
    assert row["printed_deductions"] == "10"
    assert any("deduction" in i.lower() for i in row["issues"])
    assert result["calculation_ready"] is False


def test_ga55_ocr_uses_same_original_facts_as_hra(client, monkeypatch):
    import io
    import pymupdf
    from ifms_suite import document_facts, documents
    from test_automatic_hra import facts

    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    seen = []
    monkeypatch.setattr(
        document_facts,
        "extract_document_facts",
        lambda raw: seen.append(raw) or facts(),
    )
    monkeypatch.setattr(
        documents,
        "ocr_document",
        lambda *a: pytest.fail("Legacy OCR must not reread GA55"),
    )
    ident = client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(data), "case.pdf")},
    ).json["id"]
    result = client.post(f"/suite/api/imports/{ident}/ocr", json={})
    assert result.status_code == 200, result.json
    assert result.json["ga55"]["payments"][0]["employee_code"] == "RJTEST42"
    automatic = client.post(f"/suite/api/imports/{ident}/automatic_hra", json={})
    assert automatic.status_code == 200, automatic.json
    assert seen == [data]
    assert automatic.json["claims"][0]["calculation"]["total"] == "5400.00"


def test_evidence_endpoint_preserves_raw_and_reuses_confirmed_fields(
    client, monkeypatch
):
    import io
    import pymupdf
    from ifms_suite import document_facts

    f = dict(
        facts_version=document_facts.FACTS_VERSION,
        bills=[
            dict(
                employee_code="",
                pay_month="2026-07",
                bill_no="123456789",
                bill_type="Regular Salary",
                allowances={"Basic": "100"},
                printed_gross="100",
                source_pages=[1],
                complete=False,
            )
        ],
        issues=[],
    )
    monkeypatch.setattr(document_facts, "extract_document_facts", lambda _: f)
    doc = pymupdf.open()
    doc.new_page()
    ident = client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(doc.tobytes()), "case.pdf")},
    ).json["id"]
    base = f"/suite/api/imports/{ident}/evidence"
    result = client.get(base)
    assert result.status_code == 200
    item = next(r for r in result.json["requests"] if r["field"] == "employee_code")
    review = {
        k: item[k] for k in ("request_id", "field", "source_sha256", "facts_version")
    }
    review.update(value="RJJO202024050123", reviewed=True, reference="Page 1 profile")
    saved = client.post(base, json=review)
    assert saved.status_code == 200, saved.json
    assert saved.json["facts"]["bills"][0]["employee_code"] == "RJJO202024050123"
    raw = client.get("/suite/api/imports").json[0]["payload"]["machine_facts"]
    assert raw["bills"][0]["employee_code"] == ""
    assert client.post(base, json=review).status_code == 400


def test_evidence_cannot_reopen_import_approved_during_extraction(client, monkeypatch):
    import io, json
    import pymupdf
    from ifms_suite import document_facts
    from ifms_suite.storage import database

    doc = pymupdf.open()
    doc.new_page()
    ident = client.post(
        "/suite/api/imports",
        data={"kind": "ga55", "file": (io.BytesIO(doc.tobytes()), "source.pdf")},
    ).json["id"]

    def extract(_):
        with database() as db:
            db.execute(
                "UPDATE suite_imports SET status='reviewed' WHERE id=?", (ident,)
            )
        return dict(facts_version=document_facts.FACTS_VERSION, bills=[], issues=[])

    monkeypatch.setattr(document_facts, "extract_document_facts", extract)
    result = client.get(f"/suite/api/imports/{ident}/evidence")
    assert result.status_code == 400
    assert client.get("/suite/api/imports").json[0]["status"] == "reviewed"


def test_shared_candidates_need_printed_net_totals_before_history_approval(client):
    import json
    from ifms_suite.storage import database

    with client.application.app_context(), database() as db:
        ident = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            (
                "a" * 64,
                "source.pdf",
                json.dumps({"ga55": {"layout": "Shared geometric source evidence"}}),
            ),
        ).lastrowid
    r = client.post(
        f"/suite/api/imports/{ident}/review",
        json=dict(
            employee_code="RJTEST",
            reviewed=True,
            reference="original",
            payments=[
                dict(
                    bill_no="123456789",
                    bill_type="Regular Salary",
                    pay_month="2026-07",
                    allowances={"Basic": "100"},
                    deductions={},
                )
            ],
        ),
    )
    assert r.status_code == 400


def test_new_extraction_archives_stale_field_reviews(monkeypatch):
    from ifms_suite.source_evidence import source_facts
    from ifms_suite import document_facts

    data = b"original"
    digest = hashlib.sha256(data).hexdigest()
    payload = {
        "machine_facts": {"bills": []},
        "machine_facts_version": "old",
        "bill_field_reviews": [{"request_id": "old"}],
    }
    monkeypatch.setattr(
        document_facts,
        "extract_document_facts",
        lambda _: {"bills": [{"changed": True}]},
    )
    source_facts(data, digest, payload)
    assert payload["bill_field_reviews"] == []
    assert payload["superseded_bill_field_reviews"][0]["reviews"] == [
        {"request_id": "old"}
    ]
