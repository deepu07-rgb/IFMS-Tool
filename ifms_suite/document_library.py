"""Local, revisioned reference documents with bounded, passive text extraction."""

import hashlib
import io
import json
from datetime import date
from pathlib import Path, PurePosixPath
import re
import sqlite3
import zipfile
from xml.etree import ElementTree

from flask import current_app, jsonify, request, send_file

from .storage import database

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT = 2_000_000
MAX_ZIP_BYTES = 30 * 1024 * 1024
_METADATA = {
    "title": 500,
    "order_number": 500,
    "order_date": 10,
    "effective_from": 10,
    "effective_to": 10,
    "tags": 2000,
    "notes": 100_000,
    "body": MAX_TEXT,
}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def initialize_library(db):
    """Create only library-owned tables; safe on each normal suite startup."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS suite_library_categories (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL,
            name_key TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS suite_library_documents (
            id INTEGER PRIMARY KEY, revision INTEGER NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS suite_library_audit (
            id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL, revision INTEGER NOT NULL,
            action TEXT NOT NULL, previous_payload TEXT,
            new_payload TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """
    )


def _json_body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(name + " must be a positive integer")
    if isinstance(value, str) and not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError(name + " must be a positive integer")
    number = int(value)
    if not 0 < number <= 2**63 - 1:
        raise ValueError(name + " must be a positive integer")
    return number


def _text(value, field, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError(field + " must be text within " + str(limit) + " characters")
    value = value.strip()
    if required and not value:
        raise ValueError(field + " is required")
    return value


def _metadata(db, payload, previous=None):
    result = dict(previous or {})
    for field, limit in _METADATA.items():
        result[field] = _text(
            payload.get(field, result.get(field, "")), field, limit, field == "title"
        )
    for field in ("order_date", "effective_from", "effective_to"):
        if result[field]:
            try:
                parsed = date.fromisoformat(result[field])
            except (ValueError, TypeError):
                raise ValueError(field + " must be an ISO date (YYYY-MM-DD)") from None
            if parsed.isoformat() != result[field]:
                raise ValueError(field + " must be an ISO date (YYYY-MM-DD)")
    if (
        result["effective_from"]
        and result["effective_to"]
        and result["effective_to"] < result["effective_from"]
    ):
        raise ValueError("effective_to must not precede effective_from")
    category_id = payload.get("category_id", result.get("category_id"))
    if category_id in ("", None):
        category_id = None
    else:
        category_id = _positive_int(category_id, "category_id")
        if not db.execute(
            "SELECT id FROM suite_library_categories WHERE id=?", (category_id,)
        ).fetchone():
            raise ValueError("Unknown category_id")
    result["category_id"] = category_id
    return result


def _document(row):
    return dict(
        json.loads(row["payload"]),
        id=row["id"],
        revision=row["revision"],
        archived=bool(row["archived"]),
    )


def _find(db, document_id):
    row = db.execute(
        "SELECT * FROM suite_library_documents WHERE id=?", (document_id,)
    ).fetchone()
    return _document(row) if row else None


def _audit(db, kind, document, action, previous=None, reason=""):
    db.execute(
        """INSERT INTO suite_library_audit
        (entity_type,entity_id,revision,action,previous_payload,new_payload,reason)
        VALUES (?,?,?,?,?,?,?)""",
        (
            kind,
            document["id"],
            document["revision"],
            action,
            json.dumps(previous, ensure_ascii=False) if previous is not None else None,
            json.dumps(document, ensure_ascii=False),
            reason,
        ),
    )


def _xml(raw):
    declarations = raw.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise ValueError("DOCX XML declarations and entities are not supported")
    try:
        return ElementTree.fromstring(raw)
    except (ElementTree.ParseError, ValueError):
        raise ValueError("Invalid DOCX XML") from None


def _docx_text(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            items = archive.infolist()
            if (
                len(items) > 1000
                or sum(item.file_size for item in items) > MAX_ZIP_BYTES
            ):
                raise ValueError("DOCX exceeds bounded extraction limits")
            seen = set()
            for item in items:
                path = PurePosixPath(item.filename)
                low = item.filename.lower()
                if (
                    item.filename in seen
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in item.filename
                    or item.flag_bits & 1
                    or ((item.external_attr >> 16) & 0o170000) == 0o120000
                ):
                    raise ValueError("Unsafe DOCX archive entry")
                seen.add(item.filename)
                if (
                    "vba" in low
                    or low.startswith("word/embeddings/")
                    or low.endswith((".exe", ".dll", ".js"))
                ):
                    raise ValueError("Active DOCX content is not supported")
            if "[Content_Types].xml" not in seen or "word/document.xml" not in seen:
                raise ValueError("A DOCX document is required")
            content_types = _xml(archive.read("[Content_Types].xml"))
            if not any(
                node.attrib.get("PartName") == "/word/document.xml"
                and node.attrib.get("ContentType")
                == "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                for node in content_types
            ):
                raise ValueError("A non-macro DOCX document is required")
            for item in items:
                if item.filename.lower().endswith(".rels"):
                    relationships = _xml(archive.read(item))
                    if any(
                        node.attrib.get("TargetMode", "").lower() == "external"
                        for node in relationships.iter()
                    ):
                        raise ValueError(
                            "External DOCX relationships are not supported"
                        )
            root = _xml(archive.read("word/document.xml"))
            if root.tag != _W + "document":
                raise ValueError("Invalid DOCX document body")
            if any(
                node.tag in (_W + "altChunk", _W + "object") for node in root.iter()
            ):
                raise ValueError("Embedded DOCX content is not supported")
            paragraphs = []
            count = 0
            for paragraph in root.iter(_W + "p"):
                text = "".join(node.text or "" for node in paragraph.iter(_W + "t"))
                count += len(text) + 1
                if count > MAX_TEXT:
                    raise ValueError("DOCX text exceeds bounded extraction limits")
                paragraphs.append(text)
            return (
                "\n".join(paragraphs).strip(),
                "Search includes DOCX paragraph and table text; original Word layout is available in the download.",
            )
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
        raise ValueError("Invalid or unsupported DOCX archive") from None


def _pdf_text(raw):
    import fitz

    try:
        with fitz.open(stream=raw, filetype="pdf") as document:
            if document.needs_pass:
                raise ValueError("Password-protected PDFs are not supported")
            if document.page_count > 500 or document.xref_length() > 100_000:
                raise ValueError("PDF exceeds bounded extraction limits (500 pages)")
            text = []
            length = 0
            for page in document:
                value = page.get_text("text")
                length += len(value)
                if length > MAX_TEXT:
                    raise ValueError("PDF text exceeds bounded extraction limits")
                text.append(value)
            value = "\n".join(text).strip()
            note = (
                "Search includes selectable PDF text; image-only pages are not searched (no OCR)."
                if value
                else "No selectable PDF text found: metadata-only search; add typed text or notes for scanned content (no OCR)."
            )
            return value, note
    except ValueError:
        raise
    except Exception:
        raise ValueError("Invalid or unsupported PDF document") from None


def _upload():
    files = request.files.getlist("file")
    if len(files) != 1 or not files[0].filename:
        raise ValueError("Upload exactly one PDF or DOCX file")
    source = files[0]
    name = _text(
        source.filename.replace("\\", "/").rsplit("/", 1)[-1], "file_name", 255, True
    )
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("Invalid control character in file_name")
    suffix = Path(name).suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise ValueError("Only PDF and DOCX uploads are supported")
    raw = source.stream.read(MAX_FILE_BYTES + 1)
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Each document must be nonempty and no larger than 10 MB")
    if suffix == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF document")
        text, note = _pdf_text(raw)
    else:
        text, note = _docx_text(raw)
    return raw, dict(
        file_kind=suffix[1:],
        file_name=name,
        sha256=hashlib.sha256(raw).hexdigest(),
        extracted_text=text,
        text_search_note=note,
    )


def _original_path(document):
    root = (Path(current_app.config["UPLOAD_FOLDER"]) / "suite" / "library").resolve()
    digest, kind = document.get("sha256"), document.get("file_kind")
    if (
        kind not in ("pdf", "docx")
        or not isinstance(digest, str)
        or not re.fullmatch("[0-9a-f]{64}", digest)
    ):
        raise ValueError("Invalid original-file reference")
    path = root / (digest + "." + kind)
    if path.resolve().parent != root or path.is_symlink():
        raise ValueError("Invalid original-file path")
    return path


def _save_original(raw, document):
    path = _original_path(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        with path.open("rb") as stream:
            existing = stream.read(MAX_FILE_BYTES + 1)
        if hashlib.sha256(existing).hexdigest() != document["sha256"]:
            raise ValueError(
                "Stored original failed integrity check; restore a verified backup"
            )


def _conflict():
    return jsonify(error="This record has changed. Reload before saving."), 409


def register_document_library(suite):
    """Attach library routes to the existing suite blueprint."""

    @suite.route("/api/library/categories", methods=["GET", "POST"])
    def library_categories():
        with database() as db:
            if request.method == "GET":
                return jsonify(
                    [
                        dict(row)
                        for row in db.execute(
                            "SELECT id,name,revision FROM suite_library_categories ORDER BY name COLLATE NOCASE,id"
                        )
                    ]
                )
            payload = _json_body()
            name = _text(payload.get("name"), "name", 200, True)
            try:
                cursor = db.execute(
                    "INSERT INTO suite_library_categories(name,name_key,revision) VALUES (?,?,1)",
                    (name, name.casefold()),
                )
            except sqlite3.IntegrityError:
                raise ValueError("A category with this name already exists") from None
            category = dict(id=cursor.lastrowid, name=name, revision=1)
            _audit(db, "category", category, "category_create")
            return jsonify(category), 201

    @suite.post("/api/library/categories/<int:category_id>")
    def library_category_edit(category_id):
        payload = _json_body()
        revision = _positive_int(payload.get("revision"), "revision")
        name = _text(payload.get("name"), "name", 200, True)
        with database() as db:
            row = db.execute(
                "SELECT id,name,revision FROM suite_library_categories WHERE id=?",
                (category_id,),
            ).fetchone()
            if not row:
                return jsonify(error="Category not found"), 404
            if row["revision"] != revision:
                return _conflict()
            try:
                cursor = db.execute(
                    "UPDATE suite_library_categories SET name=?,name_key=?,revision=revision+1 WHERE id=? AND revision=?",
                    (name, name.casefold(), category_id, revision),
                )
            except sqlite3.IntegrityError:
                raise ValueError("A category with this name already exists") from None
            if cursor.rowcount != 1:
                return _conflict()
            category = dict(id=category_id, name=name, revision=revision + 1)
            _audit(db, "category", category, "category_rename", dict(row))
            return jsonify(category)

    @suite.route("/api/library/documents", methods=["GET", "POST"])
    def library_documents():
        with database() as db:
            if request.method == "GET":
                flag = request.args.get("include_archived", "false").lower()
                if flag not in ("true", "false", "1", "0"):
                    raise ValueError("include_archived must be true or false")
                category = request.args.get("category_id")
                category = _positive_int(category, "category_id") if category else None
                query = _text(request.args.get("q", ""), "q", 1000).casefold()
                categories = {
                    r["id"]: r["name"]
                    for r in db.execute("SELECT id,name FROM suite_library_categories")
                }
                rows = db.execute(
                    "SELECT * FROM suite_library_documents WHERE archived=0 OR ? ORDER BY id DESC",
                    (flag in ("true", "1"),),
                )
                documents = []
                for row in rows:
                    value = _document(row)
                    if category is not None and value["category_id"] != category:
                        continue
                    haystack = "\n".join(
                        [str(value.get(key, "")) for key in _METADATA]
                        + [
                            value["extracted_text"],
                            value["file_name"],
                            categories.get(value["category_id"], ""),
                        ]
                    ).casefold()
                    if not query or query in haystack:
                        documents.append(value)
                return jsonify(documents)
            payload = _json_body() if request.is_json else request.form.to_dict()
            document = _metadata(db, payload)
            raw = None
            if request.files:
                raw, source = _upload()
            else:
                if not request.is_json:
                    raise ValueError(
                        "Upload a PDF/DOCX file or submit typed rules as JSON"
                    )
                source = dict(
                    file_kind="text",
                    file_name="",
                    sha256="",
                    extracted_text="",
                    text_search_note="Search includes typed text and metadata.",
                )
                if not document["body"]:
                    raise ValueError("Typed rules require body text")
            document.update(source)
            if raw is not None:
                _save_original(raw, document)
            cursor = db.execute(
                "INSERT INTO suite_library_documents(revision,archived,payload) VALUES (1,0,?)",
                (json.dumps(document, ensure_ascii=False),),
            )
            document.update(id=cursor.lastrowid, revision=1, archived=False)
            _audit(db, "document", document, "create")
            return jsonify(document), 201

    @suite.route("/api/library/documents/<int:document_id>", methods=["GET", "POST"])
    def library_document(document_id):
        with database() as db:
            previous = _find(db, document_id)
            if previous is None:
                return jsonify(error="Document not found"), 404
            if request.method == "GET":
                return jsonify(previous)
            payload = _json_body()
            revision = _positive_int(payload.get("revision"), "revision")
            if previous["revision"] != revision:
                return _conflict()
            document = _metadata(db, payload, previous)
            if document["file_kind"] == "text" and not document["body"]:
                raise ValueError("Typed rules require body text")
            document["revision"] = revision + 1
            cursor = db.execute(
                "UPDATE suite_library_documents SET payload=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?",
                (json.dumps(document, ensure_ascii=False), document_id, revision),
            )
            if cursor.rowcount != 1:
                return _conflict()
            _audit(db, "document", document, "edit", previous)
            return jsonify(document)

    @suite.post("/api/library/documents/<int:document_id>/archive")
    def library_document_archive(document_id):
        payload = _json_body()
        revision = _positive_int(payload.get("revision"), "revision")
        archived = payload.get("archived")
        if not isinstance(archived, bool):
            raise ValueError("archived must be true or false")
        reason = _text(payload.get("reason"), "reason", 2000, True)
        with database() as db:
            previous = _find(db, document_id)
            if previous is None:
                return jsonify(error="Document not found"), 404
            if previous["revision"] != revision:
                return _conflict()
            document = dict(previous, revision=revision + 1, archived=archived)
            cursor = db.execute(
                "UPDATE suite_library_documents SET archived=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND revision=?",
                (archived, document_id, revision),
            )
            if cursor.rowcount != 1:
                return _conflict()
            _audit(
                db,
                "document",
                document,
                "archive" if archived else "restore",
                previous,
                reason,
            )
            return jsonify(document)

    @suite.get("/api/library/documents/<int:document_id>/content")
    def library_document_content(document_id):
        with database() as db:
            document = _find(db, document_id)
        if document is None or document["file_kind"] == "text":
            return jsonify(error="Original document not found"), 404
        try:
            path = _original_path(document)
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
        except (OSError, ValueError):
            return (
                jsonify(
                    error="Original document missing or unsafe; restore a verified backup"
                ),
                409,
            )
        if (
            len(raw) > MAX_FILE_BYTES
            or hashlib.sha256(raw).hexdigest() != document["sha256"]
        ):
            return (
                jsonify(
                    error="Original document failed its SHA256 integrity check; restore a verified backup"
                ),
                409,
            )
        is_pdf = document["file_kind"] == "pdf"
        response = send_file(
            io.BytesIO(raw),
            mimetype=(
                "application/pdf"
                if is_pdf
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            download_name=document["file_name"],
            as_attachment=not is_pdf,
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response
