"""HTTP contract, source integrity and revision protection for saved registers."""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
import sqlite3

from flask import Blueprint, Flask, jsonify
import pytest

from ifms_suite import bill_register_routes as routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        DATABASE=str(tmp_path / "db.sqlite"),
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
    )
    with sqlite3.connect(app.config["DATABASE"]) as db:
        routes.initialize_bill_register(db)
        db.execute(
            "CREATE TABLE suite_imports(id INTEGER PRIMARY KEY,sha256 TEXT,filename TEXT,payload TEXT)"
        )
    bp = Blueprint("test_register", __name__)
    routes.register_bill_register(bp)
    app.register_blueprint(bp, url_prefix="/suite")

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    def parse(data):
        if b"broken" in data:
            raise ValueError("unreadable PDF")
        return dict(
            columns=list(routes.COLUMNS),
            rows=[
                dict.fromkeys(routes.COLUMNS, "")
                | {"BillNo": "123", "Gross": "100", "Net": "90"}
            ],
            issues=[],
            evidence=[{"page": 1}],
            raw_pages=["Raw OCR 100 90"],
            method="text",
            requires_review=True,
        )

    monkeypatch.setattr(routes, "parse_bill_pdf", parse)
    return app.test_client()


def upload(client, entries=None):
    entries = entries or [("a.pdf", b"%PDF-1.4\noriginal")]
    return client.post(
        "/suite/api/bill-register",
        data={"files": [(BytesIO(data), name) for name, data in entries]},
        content_type="multipart/form-data",
    )


def test_batch_partial_failures_preserve_sources_and_raw_audit(client):
    response = upload(
        client,
        [
            ("good.pdf", b"%PDF-1.4 good"),
            ("bad.pdf", b"%PDF-1.4 broken"),
            ("invalid.pdf", b"not pdf"),
        ],
    )
    assert response.status_code == 201
    result = response.json
    p = result["payload"]
    assert len(p["rows"]) == 1
    assert [s["status"] for s in p["sources"]] == ["parsed", "failed", "failed"]
    assert len(p["issues"]) == 2
    assert p["requires_review"] and not p["reviewed"]
    ident = result["id"]
    assert client.get(f"/suite/api/bill-register/{ident}").json == result
    assert client.get("/suite/api/bill-register").json[0]["rows"] == 1
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        initial = json.loads(
            db.execute("SELECT new_payload FROM suite_bill_register_audit").fetchone()[
                0
            ]
        )
        assert initial == p
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE suite_bill_register_audit SET new_payload=?", ("{}",))


def test_duplicate_files_skipped_but_duplicate_bills_flagged(client):
    p = upload(
        client,
        [
            ("first.pdf", b"%PDF-1.4 first"),
            ("same.pdf", b"%PDF-1.4 first"),
            ("other.pdf", b"%PDF-1.4 other"),
        ],
    ).json["payload"]
    assert len(p["rows"]) == 2
    assert p["sources"][1]["status"] == "duplicate"
    assert {i["code"] for i in p["issues"]} == {
        "duplicate_file",
        "possible_duplicate_bill",
    }


def test_explicit_review_revision_and_immutable_extraction(client):
    saved = upload(client).json
    payload = deepcopy(saved["payload"])
    payload["rows"][0]["Net"] = "80"
    payload["raw_pages"] = ["forged"]
    url = f"/suite/api/bill-register/{saved['id']}"
    body = dict(payload=payload, revision=1)
    assert client.post(url, json=body).status_code == 400
    body.update(reviewed=True, reference="Original PDF page 1 checked")
    changed = client.post(url, json=body)
    assert changed.status_code == 200
    assert changed.json["revision"] == 2
    assert changed.json["payload"]["rows"][0]["Net"] == "80"
    assert changed.json["payload"]["raw_pages"] == saved["payload"]["raw_pages"]
    assert changed.json["payload"]["sources"] == saved["payload"]["sources"]
    assert client.post(url, json=body).status_code == 409
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        audits = db.execute(
            "SELECT new_payload FROM suite_bill_register_audit ORDER BY revision"
        ).fetchall()
    assert json.loads(audits[0][0])["rows"][0]["Net"] == "90"


@pytest.mark.parametrize("value", ["=1+2", "+SUM(A1)", "@SUM(A1)", "-CMD(x)"])
def test_edits_reject_formulas(client, value):
    saved = upload(client).json
    p = saved["payload"]
    p["rows"][0]["Gross"] = value
    response = client.post(
        f"/suite/api/bill-register/{saved['id']}",
        json=dict(payload=p, revision=1, reviewed=True, reference="PDF"),
    )
    assert response.status_code == 400


def test_source_hash_membership_and_tamper_detection(client):
    saved = upload(client).json
    ident = saved["id"]
    digest = saved["payload"]["sources"][0]["sha256"]
    url = f"/suite/api/bill-register/{ident}/source?source_sha256="
    assert client.get(url + digest).data == b"%PDF-1.4\noriginal"
    assert client.get(url + "a" * 64).status_code == 404
    assert client.get(url + "../evil").status_code == 400
    from pathlib import Path

    path = (
        Path(client.application.config["UPLOAD_FOLDER"])
        / "suite"
        / "bill-register"
        / (digest + ".pdf")
    )
    path.write_bytes(b"changed")
    assert client.get(url + digest).status_code == 400


def test_upload_limits_and_all_failed_record(client):
    assert client.post("/suite/api/bill-register").status_code == 400
    assert (
        upload(client, [(str(i) + ".pdf", b"%PDF-1.4") for i in range(21)]).status_code
        == 400
    )
    p = upload(client, [("large.pdf", b"%PDF-" + b"x" * routes.MAX_FILE)]).json[
        "payload"
    ]
    assert not p["rows"] and p["sources"][0]["status"] == "failed"
    assert p["issues"]


def test_export_validates_options_and_flags_draft(client, monkeypatch):
    saved = upload(client).json
    calls = []

    def export(payload, **kwargs):
        calls.append((payload, kwargs))
        return BytesIO(b"export")

    monkeypatch.setattr(routes, "export_register", export)
    url = f"/suite/api/bill-register/{saved['id']}/excel"
    response = client.get(url + "?mode=raw&paper=FS")
    assert response.status_code == 200
    assert "DRAFT" in response.headers["Content-Disposition"]
    assert calls[0][0]["draft"] and "UNREVIEWED" in calls[0][0]["status"]
    assert calls[0][1] == dict(mode="raw", format="excel", paper="FS")
    assert client.get(url + "?mode=bogus").status_code == 400


def test_outer_conversion_uses_original_extraction_and_labels_reference(client):
    from pathlib import Path

    data = small_pdf("Gross Amount: 100\nNet Amount: 90")
    digest = hashlib.sha256(data).hexdigest()
    folder = Path(client.application.config["UPLOAD_FOLDER"]) / "suite"
    folder.mkdir(parents=True)
    (folder / (digest + ".pdf")).write_bytes(data)
    original = dict(
        kind="outer",
        file_kind="pdf",
        extracted={
            "Reference Number": "REF-5",
            "Bill Date Parsed": "2026-07-01",
            "Bill Name": "Salary",
            "Gross Amount": 100,
            "Net Amount": 90,
            "Deductions": {"GPF": 10},
        },
    )
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        db.execute(
            "INSERT INTO suite_imports VALUES(1,?,?,?)",
            (digest, "outer.pdf", json.dumps(original)),
        )
    response = client.post(
        "/suite/api/bill-register/from-outer", json={"import_ids": [1]}
    )
    assert response.status_code == 201
    p = response.json["payload"]
    assert p["rows"][0]["BillNo"] == "Reference Number: REF-5"
    assert p["rows"][0]["Gross"] == "100"
    assert p["rows"][0]["IncomeTax"] == ""
    assert p["sources"][0]["original_payload"] == original
    assert any(i["code"] == "reference_not_bill_number" for i in p["issues"])
    assert (
        client.post(
            "/suite/api/bill-register/from-outer", json={"import_ids": [99]}
        ).status_code
        == 400
    )


def test_actual_small_pdf_retains_unrecognized_page_for_review(client, monkeypatch):
    import pymupdf
    from ifms_suite.bill_register_parser import parse_bill_pdf

    monkeypatch.setattr(routes, "parse_bill_pdf", parse_bill_pdf)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((50, 50), "Unrecognized source bill: amount 100.00")
    data = pdf.tobytes()
    pdf.close()
    response = upload(client, [("source.pdf", data)])
    assert response.status_code == 201
    p = response.json["payload"]
    assert p["requires_review"] is True
    assert (
        p["raw_pages"] and p["sources"][0]["sha256"] == hashlib.sha256(data).hexdigest()
    )
    assert not p["rows"]


def test_custom_columns_reorder_remove_and_add(client):
    saved = upload(client).json
    p = deepcopy(saved["payload"])
    p["columns"] = ["Notes", "Net", "BillNo"]
    p["rows"][0]["Notes"] = "Checked with original"
    response = client.post(
        f"/suite/api/bill-register/{saved['id']}",
        json=dict(payload=p, revision=1, reviewed=True, reference="Original page"),
    )
    assert response.status_code == 200
    current = response.json["payload"]
    assert current["columns"] == ["Notes", "Net", "BillNo"]
    assert current["rows"] == [
        {"Notes": "Checked with original", "Net": "90", "BillNo": "123"}
    ]
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        initial = json.loads(
            db.execute(
                "SELECT new_payload FROM suite_bill_register_audit WHERE revision=1"
            ).fetchone()[0]
        )
    assert initial["columns"] == routes.COLUMNS
    assert initial["rows"][0]["Gross"] == "100"


@pytest.mark.parametrize("columns", [[], ["A", "A"], [""], [" "], [None], ["A"] * 101])
def test_invalid_column_lists_are_rejected(client, columns):
    saved = upload(client).json
    p = saved["payload"]
    p["columns"] = columns
    response = client.post(
        f"/suite/api/bill-register/{saved['id']}",
        json=dict(payload=p, revision=1, reviewed=True, reference="Original"),
    )
    assert response.status_code == 400


def test_missing_cells_in_new_columns_stay_blank(client):
    saved = upload(client).json
    p = saved["payload"]
    p["columns"] = ["BillNo", "Custom blank"]
    response = client.post(
        f"/suite/api/bill-register/{saved['id']}",
        json=dict(payload=p, revision=1, reviewed=True, reference="Original"),
    )
    assert response.status_code == 200
    assert response.json["payload"]["rows"] == [{"BillNo": "123", "Custom blank": ""}]


def test_format_exposes_verified_reference_status(client):
    response = client.get("/suite/api/bill-register/format")
    assert response.status_code == 200
    assert response.json["verified"] is False
    assert response.json["notice"] == response.json["verification"]


def small_pdf(text=""):
    import pymupdf

    pdf = pymupdf.open()
    page = pdf.new_page()
    if text:
        page.insert_text((40, 40), text)
    data = pdf.tobytes()
    pdf.close()
    return data


# Keep the real route wrapper even while the basic HTTP fixture stubs it.
from ifms_suite.bill_register_routes import parse_bill_pdf as real_parse_wrapper


def test_scanned_source_uses_local_ocr_with_original_hash(client, monkeypatch):
    from ifms_suite import documents, bill_register_parser

    original = small_pdf()
    derivative = small_pdf("Recognized derivative source text")
    calls = []

    def ocr(data, language):
        calls.append((data, language))
        return ["Recognized derivative source text"], derivative

    monkeypatch.setattr(documents, "ocr_document", ocr)
    parser = bill_register_parser.parse_bill_pdf

    def parse(data):
        result = parser(data)
        if data == derivative:
            result["rows"] = [
                dict.fromkeys(routes.COLUMNS, "") | {"BillNo": "789", "Gross": "100"}
            ]
        return result

    monkeypatch.setattr(bill_register_parser, "parse_bill_pdf", parse)
    monkeypatch.setattr(routes, "parse_bill_pdf", real_parse_wrapper)
    response = upload(client, [("scan.pdf", original)])
    p = response.json["payload"]
    assert calls == [(original, "eng")]
    assert p["rows"][0]["BillNo"] == "789"
    assert p["sources"][0]["method"] == "local_ocr"
    assert p["sources"][0]["sha256"] == hashlib.sha256(original).hexdigest()
    assert p["requires_review"]
    assert "original_raw_pages" in str(p["evidence"])


def test_ocr_failure_keeps_original_and_explicit_issue(client, monkeypatch):
    from ifms_suite import documents

    def fail(*args, **kwargs):
        raise ValueError("OCR language data is not installed")

    monkeypatch.setattr(documents, "ocr_document", fail)
    monkeypatch.setattr(routes, "parse_bill_pdf", real_parse_wrapper)
    original = small_pdf()
    response = upload(client, [("scan.pdf", original)])
    p = response.json["payload"]
    assert not p["rows"] and p["requires_review"]
    assert "OCR language data is not installed" in str(p["issues"])
    digest = hashlib.sha256(original).hexdigest()
    assert (
        client.get(
            f"/suite/api/bill-register/{response.json['id']}/source?source_sha256={digest}"
        ).data
        == original
    )


def test_direct_digital_outer_maps_existing_parser_and_preserves_amount_precision(
    client, monkeypatch
):
    monkeypatch.setattr(routes, "parse_bill_pdf", real_parse_wrapper)
    original = small_pdf(
        "Salary Bill\nReference No : 123456789\nBill Date : 01/07/2026\nGross Amount : 100.25\nNet Amount : 90.15"
    )
    p = upload(client, [("outer.pdf", original)]).json["payload"]
    assert p["rows"][0]["BillNo"] == "Reference Number: 123456789"
    assert p["rows"][0]["Gross"] == "100.25"
    assert p["rows"][0]["Net"] == "90.15"
    assert p["sources"][0]["method"] == "outer_existing_extraction"
    assert "original_extracted" in str(p["evidence"])
    assert p["requires_review"]


def test_direct_outer_missing_net_never_invents_zero(client, monkeypatch):
    monkeypatch.setattr(routes, "parse_bill_pdf", real_parse_wrapper)
    original = small_pdf(
        "Salary Bill\nReference No : 123456789\nBill Date : 01/07/2026\nGross Amount : 100"
    )
    p = upload(client, [("outer.pdf", original)]).json["payload"]
    assert p["rows"][0]["Net"] == ""
    assert p["rows"][0]["IncomeTax"] == ""


def test_outer_heading_without_metadata_is_not_a_candidate(client, monkeypatch):
    monkeypatch.setattr(routes, "parse_bill_pdf", real_parse_wrapper)
    p = upload(
        client,
        [
            (
                "unknown.pdf",
                small_pdf("Salary Bill\nUnidentified sheet\nGross Amount : 100"),
            )
        ],
    ).json["payload"]
    assert not p["rows"] and p["requires_review"]


def test_source_printed_header_labels_preserved_with_conflicts_flagged(
    client, monkeypatch
):
    def parser(data):
        return dict(
            columns=routes.COLUMNS,
            rows=[],
            issues=[],
            evidence=[],
            raw_pages=[],
            method="text",
            column_labels={"BillNo": "Bill No" if b"first" in data else "Bill Number"},
        )

    monkeypatch.setattr(routes, "parse_bill_pdf", parser)
    p = upload(client, [("one.pdf", b"%PDF-first"), ("two.pdf", b"%PDF-other")]).json[
        "payload"
    ]
    assert p["column_labels"]["BillNo"] == "Bill No"
    assert any(i.get("code") == "column_label_conflict" for i in p["issues"])


def test_existing_outer_default_zeros_are_blank_without_source_evidence(client):
    from pathlib import Path

    original = small_pdf("Salary Bill source with no readable totals")
    digest = hashlib.sha256(original).hexdigest()
    folder = Path(client.application.config["UPLOAD_FOLDER"]) / "suite"
    folder.mkdir(parents=True)
    (folder / (digest + ".pdf")).write_bytes(original)
    payload = dict(file_kind="pdf", extracted={"Gross Amount": 0, "Net Amount": 0})
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        db.execute(
            "INSERT INTO suite_imports VALUES(1,?,?,?)",
            (digest, "outer.pdf", json.dumps(payload)),
        )
    response = client.post(
        "/suite/api/bill-register/from-outer", json={"import_ids": [1]}
    )
    row = response.json["payload"]["rows"][0]
    assert row["Gross"] == row["Net"] == ""


def test_existing_outer_preserves_printed_paise_instead_of_engine_rounding(client):
    from pathlib import Path

    original = small_pdf("Salary Bill\nGross Amount: 1,000.49\nNet Amount: 900.50")
    digest = hashlib.sha256(original).hexdigest()
    folder = Path(client.application.config["UPLOAD_FOLDER"]) / "suite"
    folder.mkdir(parents=True)
    (folder / (digest + ".pdf")).write_bytes(original)
    payload = dict(file_kind="pdf", extracted={"Gross Amount": 1000, "Net Amount": 901})
    with sqlite3.connect(client.application.config["DATABASE"]) as db:
        db.execute(
            "INSERT INTO suite_imports VALUES(1,?,?,?)",
            (digest, "outer.pdf", json.dumps(payload)),
        )
    response = client.post(
        "/suite/api/bill-register/from-outer", json={"import_ids": [1]}
    )
    row = response.json["payload"]["rows"][0]
    assert row["Gross"] == "1,000.49"
    assert row["Net"] == "900.50"
