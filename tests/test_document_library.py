"""Synthetic, offline document-library API coverage; no private office files."""

import io
import sqlite3
import zipfile

import fitz
import pytest
from flask import Blueprint, Flask, jsonify


@pytest.fixture
def library(tmp_path):
    from ifms_suite.document_library import (
        initialize_library,
        register_document_library,
    )

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        DATABASE=str(tmp_path / "library.db"),
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
    )
    with sqlite3.connect(app.config["DATABASE"]) as db:
        initialize_library(db)
        initialize_library(db)  # Startup is repeatable and preserves archived records.
    blueprint = Blueprint("library_test", __name__, url_prefix="/suite")

    @blueprint.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    register_document_library(blueprint)
    app.register_blueprint(blueprint)
    return app.test_client(), app, tmp_path


def create(client, **changes):
    return client.post(
        "/suite/api/library/documents",
        json=dict(
            title="Travelling allowance rule",
            body="Mileage entitlement is reviewed locally.",
            **changes,
        ),
    )


def pdf_bytes(text="Daily journey entitlement"):
    with fitz.open() as doc:
        page = doc.new_page()
        if text:
            page.insert_text((50, 70), text)
        return doc.tobytes()


def docx_bytes(xml=None, extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "word/document.xml",
            xml
            or '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Daily travel rule</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Forty kilometres</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>',
        )
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def upload(client, data, name, **fields):
    return client.post(
        "/suite/api/library/documents",
        data=dict(title="Uploaded rule", file=(io.BytesIO(data), name), **fields),
        content_type="multipart/form-data",
    )


def test_categories_rename_and_revision_conflict(library):
    client, _, _ = library
    response = client.post(
        "/suite/api/library/categories", json={"name": "Travelling Allowance Rules"}
    )
    assert response.status_code == 201
    category = response.json
    assert category["revision"] == 1
    response = client.post(
        f"/suite/api/library/categories/{category['id']}",
        json={"name": "Travel rules", "revision": 1},
    )
    assert response.status_code == 200
    assert response.json["name"] == "Travel rules"
    assert response.json["revision"] == 2
    assert (
        client.post(
            f"/suite/api/library/categories/{category['id']}",
            json={"name": "Lost edit", "revision": 1},
        ).status_code
        == 409
    )
    assert client.get("/suite/api/library/categories").json == [response.json]
    assert (
        client.post(
            "/suite/api/library/categories", json={"name": "travel RULES"}
        ).status_code
        == 400
    )


def test_typed_metadata_search_and_category_filter(library):
    client, _, _ = library
    category = client.post(
        "/suite/api/library/categories", json={"name": "Travel"}
    ).json
    response = create(
        client,
        category_id=category["id"],
        order_number="FIN-2040-42",
        order_date="2040-04-01",
        effective_from="2040-05-01",
        effective_to="2041-04-30",
        tags="mileage, travel",
        notes="Reviewed circular",
    )
    assert response.status_code == 201
    document = response.json
    assert document["file_kind"] == "text"
    assert document["revision"] == 1
    assert document["archived"] is False
    for query in ("mileage", "FIN-2040", "Reviewed circular", "travelling"):
        found = client.get(
            "/suite/api/library/documents", query_string={"q": query}
        ).json
        assert [item["id"] for item in found] == [document["id"]]
    assert (
        len(
            client.get(
                "/suite/api/library/documents",
                query_string={"category_id": category["id"]},
            ).json
        )
        == 1
    )
    assert (
        client.get("/suite/api/library/documents", query_string={"q": "%"}).json == []
    )
    assert (
        client.get(f"/suite/api/library/documents/{document['id']}").json["body"]
        == "Mileage entitlement is reviewed locally."
    )


def test_metadata_edit_is_revision_checked_and_audited(library):
    client, app, _ = library
    document = create(client).json
    path = f"/suite/api/library/documents/{document['id']}"
    response = client.post(
        path,
        json={
            "revision": 1,
            "title": "Revised travel rule",
            "body": "A new searchable condition",
        },
    )
    assert response.status_code == 200
    assert response.json["revision"] == 2
    assert (
        client.post(path, json={"revision": 1, "body": "Stale overwrite"}).status_code
        == 409
    )
    assert client.post(path, json={"title": "Missing revision"}).status_code == 400
    assert (
        client.get("/suite/api/library/documents?q=searchable").json[0]["title"]
        == "Revised travel rule"
    )
    with sqlite3.connect(app.config["DATABASE"]) as db:
        rows = db.execute(
            "SELECT action,previous_payload,new_payload FROM suite_library_audit ORDER BY id"
        ).fetchall()
    assert [r[0] for r in rows] == ["create", "edit"]
    assert "Mileage entitlement" in rows[1][1]
    assert "new searchable condition" in rows[1][2]


def test_archive_restore_preserves_record_after_restart(library):
    client, app, _ = library
    document = create(client).json
    path = f"/suite/api/library/documents/{document['id']}/archive"
    assert (
        client.post(
            path, json={"revision": 1, "archived": True, "reason": ""}
        ).status_code
        == 400
    )
    archived = client.post(
        path, json={"revision": 1, "archived": True, "reason": "Superseded"}
    ).json
    assert archived["revision"] == 2 and archived["archived"] is True
    from ifms_suite.document_library import initialize_library

    with sqlite3.connect(app.config["DATABASE"]) as db:
        initialize_library(db)
    assert client.get("/suite/api/library/documents").json == []
    assert (
        client.get("/suite/api/library/documents?include_archived=true").json[0]["id"]
        == document["id"]
    )
    assert (
        client.post(
            path, json={"revision": 1, "archived": False, "reason": "Reviewed again"}
        ).status_code
        == 409
    )
    restored = client.post(
        path, json={"revision": 2, "archived": False, "reason": "Reviewed again"}
    )
    assert restored.json["revision"] == 3 and restored.json["archived"] is False
    with sqlite3.connect(app.config["DATABASE"]) as db:
        assert [
            row[0]
            for row in db.execute("SELECT action FROM suite_library_audit ORDER BY id")
        ] == ["create", "archive", "restore"]


def test_pdf_search_and_original_integrity(library):
    client, _, root = library
    raw = pdf_bytes()
    response = upload(client, raw, "../../travel.PDF")
    assert response.status_code == 201
    document = response.json
    assert document["file_kind"] == "pdf"
    assert document["file_name"] == "travel.PDF"
    assert "Daily journey entitlement" in document["extracted_text"]
    assert len(document["sha256"]) == 64
    assert (
        client.get("/suite/api/library/documents?q=journey").json[0]["id"]
        == document["id"]
    )
    content = client.get(f"/suite/api/library/documents/{document['id']}/content")
    assert content.status_code == 200 and content.data == raw
    assert (
        content.mimetype == "application/pdf"
        and "inline" in content.headers["Content-Disposition"]
    )
    original = root / "uploads" / "suite" / "library" / (document["sha256"] + ".pdf")
    original.write_bytes(b"tampered")
    assert (
        client.get(f"/suite/api/library/documents/{document['id']}/content").status_code
        == 409
    )


def test_scan_shows_metadata_only_search_limitation(library):
    client, _, _ = library
    response = upload(client, pdf_bytes(""), "scan.pdf", notes="Manual index elephant")
    assert response.status_code == 201
    assert response.json["extracted_text"] == ""
    assert "metadata" in response.json["text_search_note"].lower()
    assert (
        client.get("/suite/api/library/documents?q=elephant").json[0]["id"]
        == response.json["id"]
    )


def test_docx_paragraph_table_search_and_safe_download(library):
    client, _, _ = library
    raw = docx_bytes()
    response = upload(client, raw, "travel.docx")
    assert response.status_code == 201
    document = response.json
    assert (
        "Daily travel rule" in document["extracted_text"]
        and "Forty kilometres" in document["extracted_text"]
    )
    assert (
        client.get("/suite/api/library/documents?q=kilometres").json[0]["id"]
        == document["id"]
    )
    content = client.get(f"/suite/api/library/documents/{document['id']}/content")
    assert (
        content.data == raw and "attachment" in content.headers["Content-Disposition"]
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": ["Bad"]},
        {"title": "Bad", "body": {"html": "Bad"}},
        {"title": "Bad", "category_id": 999},
        {"title": "Bad", "category_id": True},
        {"title": "Bad", "effective_from": "2040-02-30"},
        {"title": "Bad", "effective_from": "2040-04-02", "effective_to": "2040-04-01"},
        {"title": "Bad", "order_date": []},
    ],
)
def test_invalid_metadata_returns_validation_error(library, payload):
    client, _, _ = library
    response = client.post("/suite/api/library/documents", json=payload)
    assert response.status_code == 400 and response.json["error"]
    assert client.get("/suite/api/library/documents").json == []


@pytest.mark.parametrize(
    "raw,name",
    [
        (b"<html>bad</html>", "evil.html"),
        (b"not a PDF", "fake.pdf"),
        (b"not a ZIP", "fake.docx"),
        (
            docx_bytes('<!DOCTYPE test [<!ENTITY x "explosion">]><test>&x;</test>'),
            "entities.docx",
        ),
        (docx_bytes(extra={"../escape.xml": "unsafe"}), "traversal.docx"),
        (docx_bytes(extra={"word/vbaProject.bin": b"active"}), "macro.docx"),
        (
            docx_bytes(
                extra={
                    "word/_rels/document.xml.rels": '<Relationships><Relationship TargetMode="External" Target="https://example.invalid"/></Relationships>'
                }
            ),
            "external.docx",
        ),
        (docx_bytes(extra={"word/huge.xml": "x" * (31 * 1024 * 1024)}), "bomb.docx"),
        (b"%PDF-" + b"x" * (10 * 1024 * 1024), "oversize.pdf"),
    ],
)
def test_unsafe_uploads_rejected_without_stored_original(library, raw, name):
    client, _, root = library
    response = upload(client, raw, name)
    assert response.status_code == 400 and response.json["error"]
    assert client.get("/suite/api/library/documents").json == []
    assert not list((root / "uploads").rglob("*.pdf"))
    assert not list((root / "uploads").rglob("*.docx"))


def test_missing_ids_and_malformed_controls(library):
    client, _, _ = library
    assert client.get("/suite/api/library/documents/999").status_code == 404
    assert client.get("/suite/api/library/documents/999/content").status_code == 404
    assert (
        client.get("/suite/api/library/documents?category_id=oops").status_code == 400
    )
    assert (
        client.get("/suite/api/library/documents?include_archived=oops").status_code
        == 400
    )
    document = create(client).json
    path = f"/suite/api/library/documents/{document['id']}"
    assert client.post(path, json={"revision": True, "title": "Bad"}).status_code == 400
    assert (
        client.post(
            path + "/archive",
            json={"revision": 1, "archived": "false", "reason": "Bad"},
        ).status_code
        == 400
    )


def test_local_language_upload_name_remains_readable(library):
    client, _, _ = library
    response = upload(client, pdf_bytes(), "यात्रा भत्ता नियम.pdf")
    assert response.status_code == 201
    assert response.json["file_name"] == "यात्रा भत्ता नियम.pdf"
    content = client.get(f"/suite/api/library/documents/{response.json['id']}/content")
    assert content.status_code == 200


def test_utf16_docx_entity_declarations_are_rejected(library):
    client, _, _ = library
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE w:document [<!ENTITY local "hidden text">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&local;</w:t></w:r></w:p></w:body></w:document>'
    assert (
        upload(client, docx_bytes(xml.encode("utf-16")), "encoded.docx").status_code
        == 400
    )


def test_original_remains_immutable_after_edit_archive_and_restore(library):
    client, _, _ = library
    raw = pdf_bytes("Original reference")
    document = upload(client, raw, "original.pdf").json
    path = f"/suite/api/library/documents/{document['id']}"
    response = client.post(
        path,
        json={
            "revision": 1,
            "body": "Reviewed typed addition",
            "sha256": "forged",
            "file_kind": "text",
            "extracted_text": "forged",
        },
    )
    assert response.status_code == 200
    assert response.json["sha256"] == document["sha256"]
    assert response.json["extracted_text"] == document["extracted_text"]
    assert (
        client.post(
            path + "/archive",
            json={"revision": 2, "archived": True, "reason": "Test supersession"},
        ).status_code
        == 200
    )
    assert client.get(path + "/content").data == raw
    assert (
        client.post(
            path + "/archive",
            json={"revision": 3, "archived": False, "reason": "Reference again"},
        ).status_code
        == 200
    )
    assert client.get(path + "/content").data == raw
    assert (
        client.get("/suite/api/library/documents?q=typed%20addition").json[0]["body"]
        == "Reviewed typed addition"
    )


@pytest.mark.parametrize(
    "raw,name",
    [
        (docx_bytes("<broken>"), "broken.docx"),
        (docx_bytes(extra={"word/embeddings/object.bin": b"embedding"}), "object.docx"),
    ],
)
def test_unsupported_docx_content_is_a_validation_error(library, raw, name):
    client, _, _ = library
    assert upload(client, raw, name).status_code == 400


def test_multi_file_request_cannot_silently_discard_other_upload(library):
    client, _, _ = library
    response = client.post(
        "/suite/api/library/documents",
        data={
            "title": "Two",
            "file": [
                (io.BytesIO(pdf_bytes()), "one.pdf"),
                (io.BytesIO(pdf_bytes()), "two.pdf"),
            ],
        },
    )
    assert response.status_code == 400
    assert client.get("/suite/api/library/documents").json == []
