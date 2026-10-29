"""Persistent, source-backed bill register drafts and explicit reviewed revisions."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from flask import current_app, jsonify, request, send_file
from .storage import database

COLUMNS = [
    "SrNo",
    "BillNo",
    "BillDate",
    "Type",
    "Month",
    "Year",
    "Gross",
    "Net",
    "IncomeTax",
    "TVNo",
    "TokenNo",
    "TVDate",
    "Status",
    "GroupName",
    "ECSNo",
]
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024


def initialize_bill_register(db):
    db.executescript(
        """
    CREATE TABLE IF NOT EXISTS suite_bill_register(
      id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS suite_bill_register_audit(
      id INTEGER PRIMARY KEY, register_id INTEGER NOT NULL, revision INTEGER NOT NULL,
      previous_payload TEXT, new_payload TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(register_id,revision));
    CREATE TRIGGER IF NOT EXISTS bill_register_audit_no_update
      BEFORE UPDATE ON suite_bill_register_audit BEGIN SELECT RAISE(ABORT,'Audit is immutable'); END;
    CREATE TRIGGER IF NOT EXISTS bill_register_audit_no_delete
      BEFORE DELETE ON suite_bill_register_audit BEGIN SELECT RAISE(ABORT,'Audit is immutable'); END;
    """
    )


def _direct_outer(data, text):
    """Use the retained outer engine only for a positively identified source.

    Its default zero amounts are never evidence. Printed decimal amounts remain
    literal source strings because the retained engine rounds amounts to rupees.
    """
    import tempfile
    from outer_engine.parser import extract_pdf_data

    if not re.search(r"\b(?:salary|surrender|outer)\s+(?:bill|sheet)\b", text, re.I):
        return None
    reference = re.search(r"\b(Reference|Bill)\s*No\s*[:\s]+(\d{9})\b", text, re.I)
    date = re.search(r"Bill\s*Date\s*[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})", text, re.I)
    gross = re.search(r"Gross\s*(?:Amount)?\s*[:\s]+([\d,]+(?:\.\d+)?)", text, re.I)
    if not (reference and date and gross):
        return None
    with tempfile.TemporaryDirectory(prefix="ifms-register-outer-") as temporary:
        path = Path(temporary) / "source.pdf"
        path.write_bytes(data)
        extracted = extract_pdf_data(str(path), "source.pdf")
    if not extracted.get("Bill Date Parsed") or not extracted.get("Reference Number"):
        return None
    row = {column: "" for column in COLUMNS}
    actual_bill = reference.group(1).lower() == "bill"
    row["BillNo"] = (
        reference.group(2) if actual_bill else "Reference Number: " + reference.group(2)
    )
    row["BillDate"] = date.group(1)
    row["Type"] = extracted.get("Bill Name", "")
    row["GroupName"] = extracted.get("Group Name", "")
    row["Gross"] = gross.group(1)
    net = re.search(r"Net\s*Amount\s*[:\s]+[₹\s]*([\d,]+(?:\.\d+)?)", text, re.I)
    if not net:
        net = re.search(
            r"(?:Please\s*Order\s*to\s*pay|Pay\s*Rs\.)\s*[₹Rs.\s]*([\d,]+(?:\.\d+)?)",
            text,
            re.I,
        )
    if net:
        row["Net"] = net.group(1)
    issues = [
        "Outer bill converted with the existing extraction engine; verify all mapped and missing register fields against the original source."
    ]
    if not actual_bill:
        issues.append(
            "Reference Number is retained with its original label; it is not a verified bill number."
        )
    if not net:
        issues.append(
            "Net amount was not identified in source text; blank retained instead of the outer engine default zero."
        )
    issues.extend(extracted.get("Confidence_Reasons", []))
    return dict(
        columns=list(COLUMNS),
        rows=[row],
        raw_pages=[text],
        method="outer_existing_extraction",
        issues=issues,
        requires_review=True,
        evidence=[
            dict(
                original_extracted=extracted,
                printed_fields=dict(
                    gross=gross.group(0),
                    net=net.group(0) if net else "",
                    reference=reference.group(0),
                    date=date.group(0),
                ),
            )
        ],
    )


def parse_bill_pdf(data):
    from .bill_register_parser import parse_bill_pdf as parse
    from .documents import ocr_document, page_needs_ocr
    import pymupdf

    initial = parse(data)
    working = data
    result = initial
    original_pages = deepcopy(initial.get("raw_pages", []))
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            needs_ocr = not document.needs_pass and any(
                page_needs_ocr(page) for page in document
            )
    except Exception:
        return initial
    ocr_used = False
    if needs_ocr:
        try:
            texts, derivative = ocr_document(data, language="eng")
            result = parse(derivative)
            working = derivative
            result["raw_pages"] = texts
            ocr_used = True
        except Exception as exc:
            initial.setdefault("issues", []).append(
                "Local OCR failed: "
                + str(exc)
                + "; original PDF retained for manual review."
            )
            initial.update(method="local_ocr_failed", requires_review=True)
            return initial
    if not result.get("rows"):
        try:
            outer = _direct_outer(working, "\n".join(result.get("raw_pages", [])))
            if outer:
                outer["raw_pages"] = deepcopy(result.get("raw_pages", []))
                result = outer
        except Exception as exc:
            result.setdefault("issues", []).append(
                "Outer fallback failed: " + str(exc) + "; original source retained."
            )
            result["requires_review"] = True
    if ocr_used:
        extraction_method = result.get("method", "unknown")
        result.update(method="local_ocr", requires_review=True)
        result.setdefault("issues", []).append(
            "Local OCR output requires original-source review, including digits, signs and dates."
        )
        result.setdefault("evidence", []).append(
            dict(
                method="local_ocr",
                extraction_method=extraction_method,
                original_sha256=hashlib.sha256(data).hexdigest(),
                derivative_sha256=hashlib.sha256(working).hexdigest(),
                original_raw_pages=original_pages,
            )
        )
    return result


def export_register(payload, **kwargs):
    from .bill_register_exports import export_register as export

    return export(payload, **kwargs)


def _issue(code, message, **extra):
    return dict(code=code, message=message, **extra)


def _empty():
    return dict(
        columns=list(COLUMNS),
        column_labels={},
        rows=[],
        evidence=[],
        issues=[],
        sources=[],
        raw_pages=[],
        method="batch",
        requires_review=True,
        reviewed=False,
    )


def _shape(payload):
    if not isinstance(payload, dict):
        raise ValueError("Register payload must be an object")
    columns = payload.get("columns")
    if (
        not isinstance(columns, list)
        or not 1 <= len(columns) <= 100
        or any(not isinstance(c, str) or not c.strip() or len(c) > 200 for c in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("Use between 1 and 100 distinct nonempty column labels")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) > 50000:
        raise ValueError("Use at most 50000 register row objects")
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(key, str) for key in row):
            raise ValueError("Rows must be objects with text field names")
        for value in row.values():
            if not isinstance(value, str) or len(value) > 10000:
                raise ValueError(
                    "Register cells must be literal text up to 10000 characters"
                )
            if value.lstrip().startswith(("=", "+", "@")) or re.match(
                r"^\s*-\s*[^\d.,\s]", value
            ):
                raise ValueError(
                    "Formula expressions are not accepted in register cells"
                )
    # Editors can remove a column while retaining its old row keys in the request.
    # Current rows follow selected columns; the immutable audit retains originals.
    normalized = deepcopy(payload)
    normalized["rows"] = [
        {column: row.get(column, "") for column in columns} for row in rows
    ]
    return normalized


def _load(db, ident):
    row = db.execute(
        "SELECT * FROM suite_bill_register WHERE id=?", (ident,)
    ).fetchone()
    if row is None:
        return None
    return dict(
        id=row["id"], revision=row["revision"], payload=json.loads(row["payload"])
    )


def _save(db, payload):
    encoded = json.dumps(payload, ensure_ascii=False)
    ident = db.execute(
        "INSERT INTO suite_bill_register(revision,payload) VALUES(1,?)", (encoded,)
    ).lastrowid
    db.execute(
        "INSERT INTO suite_bill_register_audit(register_id,revision,new_payload) VALUES(?,1,?)",
        (ident, encoded),
    )
    return _load(db, ident)


def _source_path(digest):
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("Invalid source SHA-256")
    return (
        Path(current_app.config["UPLOAD_FOLDER"])
        / "suite"
        / "bill-register"
        / (digest + ".pdf")
    )


def _preserve(data, filename):
    digest = hashlib.sha256(data).hexdigest()
    path = _source_path(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("Stored source hash mismatch")
    if not path.exists():
        path.write_bytes(data)
    return dict(filename=filename, sha256=digest, source_sha256=digest)


def _append(payload, parsed, source):
    parsed = _shape(parsed)
    labels = parsed.get("column_labels", {})
    if isinstance(labels, dict):
        for key, label in labels.items():
            if key not in COLUMNS or not isinstance(label, str):
                continue
            previous = payload["column_labels"].get(key)
            if previous is None:
                payload["column_labels"][key] = label
            elif previous != label:
                payload["issues"].append(
                    _issue(
                        "column_label_conflict",
                        "Sources use different printed headers; first source label retained.",
                        column=key,
                        retained=previous,
                        other=label,
                        source_sha256=source["sha256"],
                    )
                )
        source["column_labels"] = deepcopy(labels)
    offset = len(payload["rows"])
    payload["rows"].extend(deepcopy(parsed["rows"]))
    source.update(
        row_start=offset,
        row_count=len(parsed["rows"]),
        status="parsed",
        method=parsed.get("method", "unknown"),
    )
    payload["evidence"].append(
        dict(
            source_sha256=source["sha256"],
            filename=source["filename"],
            evidence=parsed.get("evidence", []),
        )
    )
    payload["raw_pages"].append(
        dict(source_sha256=source["sha256"], pages=parsed.get("raw_pages", []))
    )
    for issue in parsed.get("issues", []):
        payload["issues"].append(
            dict(
                source_sha256=source["sha256"], filename=source["filename"], issue=issue
            )
        )


def _duplicates(payload):
    seen = {}
    for index, row in enumerate(payload["rows"]):
        key = (row.get("BillNo", "").strip(), row.get("BillDate", "").strip())
        if not key[0]:
            continue
        if key in seen:
            payload["issues"].append(
                _issue(
                    "possible_duplicate_bill",
                    "Repeated bill number and date; reconcile original sources before counting both.",
                    rows=[seen[key], index],
                    bill_no=key[0],
                )
            )
        else:
            seen[key] = index


def register_bill_register(suite):
    @suite.get("/api/bill-register/format")
    def bill_register_format():
        from .bill_register_exports import OFFICIAL_REFERENCE

        reference = deepcopy(OFFICIAL_REFERENCE)
        reference["notice"] = reference.get("verification", "")
        return jsonify(reference)

    @suite.get("/api/bill-register")
    def bill_register_list():
        with database() as db:
            records = []
            for r in db.execute(
                "SELECT * FROM suite_bill_register ORDER BY id DESC LIMIT 500"
            ):
                p = json.loads(r["payload"])
                records.append(
                    dict(
                        id=r["id"],
                        revision=r["revision"],
                        rows=len(p["rows"]),
                        sources=p["sources"],
                        requires_review=p.get("requires_review", True),
                        updated_at=r["updated_at"],
                    )
                )
        return jsonify(records)

    @suite.post("/api/bill-register")
    def bill_register_create():
        files = [f for key in request.files for f in request.files.getlist(key)]
        if not 1 <= len(files) <= 20:
            raise ValueError("Upload between 1 and 20 PDF files")
        # Preflight the batch size before persisting anything.
        entries, total = [], 0
        for f in files:
            data = f.stream.read(MAX_FILE + 1)
            total += len(data)
            entries.append((f.filename or "unnamed.pdf", data))
        if total > MAX_TOTAL:
            raise ValueError("Batch exceeds the 100 MiB limit")
        payload, seen = _empty(), set()
        for filename, data in entries:
            digest = hashlib.sha256(data).hexdigest()
            source = dict(
                filename=filename,
                sha256=digest,
                source_sha256=digest,
                row_count=0,
                status="failed",
            )
            payload["sources"].append(source)
            if digest in seen:
                source["status"] = "duplicate"
                payload["issues"].append(
                    _issue(
                        "duplicate_file",
                        "Identical PDF skipped to avoid double counting.",
                        filename=filename,
                        source_sha256=digest,
                    )
                )
                continue
            seen.add(digest)
            try:
                if len(data) > MAX_FILE:
                    raise ValueError("File exceeds the 10 MiB limit")
                if not filename.lower().endswith(
                    ".pdf"
                ) or not data.lstrip().startswith(b"%PDF-"):
                    raise ValueError("File must be a PDF")
                source.update(_preserve(data, filename))
                _append(payload, parse_bill_pdf(data), source)
            except Exception as exc:
                payload["issues"].append(
                    _issue(
                        "source_failed",
                        "Could not parse source: " + str(exc),
                        filename=filename,
                        source_sha256=digest,
                    )
                )
        _duplicates(payload)
        with database() as db:
            record = _save(db, payload)
        return jsonify(record), 201

    @suite.get("/api/bill-register/<int:ident>")
    def bill_register_get(ident):
        with database() as db:
            record = _load(db, ident)
        return (
            jsonify(record)
            if record
            else (jsonify(error="Bill register not found"), 404)
        )

    @suite.post("/api/bill-register/<int:ident>")
    def bill_register_update(ident):
        body = request.get_json() or {}
        reference = body.get("reference")
        if (
            body.get("reviewed") is not True
            or not isinstance(reference, str)
            or not reference.strip()
        ):
            raise ValueError(
                "Explicit original-source review and a reference are required"
            )
        edited = body.get("payload")
        edited = _shape(edited)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            record = _load(db, ident)
            if not record:
                return jsonify(error="Bill register not found"), 404
            if (
                type(body.get("revision")) is not int
                or body["revision"] != record["revision"]
            ):
                return jsonify(error="Register changed; reload before saving"), 409
            previous = json.dumps(record["payload"], ensure_ascii=False)
            payload = deepcopy(record["payload"])
            payload.update(
                columns=deepcopy(edited["columns"]),
                rows=deepcopy(edited["rows"]),
                reviewed=True,
                requires_review=False,
                review=dict(
                    reference=reference.strip(),
                    reviewed=True,
                    confirmed_at=datetime.now(timezone.utc).isoformat(),
                ),
            )
            # Extraction issues remain visible even after the operator reviews edits.
            revision = record["revision"] + 1
            encoded = json.dumps(payload, ensure_ascii=False)
            db.execute(
                "UPDATE suite_bill_register SET payload=?,revision=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (encoded, revision, ident),
            )
            db.execute(
                "INSERT INTO suite_bill_register_audit(register_id,revision,previous_payload,new_payload,reference) VALUES(?,?,?,?,?)",
                (ident, revision, previous, encoded, reference.strip()),
            )
            return jsonify(_load(db, ident))

    @suite.get("/api/bill-register/<int:ident>/source")
    def bill_register_source(ident):
        digest = request.args.get("source_sha256")
        path = _source_path(digest)
        with database() as db:
            record = _load(db, ident)
        if not record or not any(
            s["sha256"] == digest for s in record["payload"]["sources"]
        ):
            return jsonify(error="Source not found"), 404
        if not path.is_file():
            return jsonify(error="Original source unavailable"), 404
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Original source hash mismatch")
        from io import BytesIO

        return send_file(
            BytesIO(data), mimetype="application/pdf", download_name=digest + ".pdf"
        )

    @suite.get("/api/bill-register/<int:ident>/<kind>")
    def bill_register_export(ident, kind):
        mode, paper = request.args.get("mode", "raw"), request.args.get("paper", "A4")
        if (
            kind not in ("excel", "pdf")
            or mode not in ("raw", "official")
            or paper not in ("A4", "FS")
        ):
            raise ValueError("Choose excel/pdf, raw/official and A4/FS")
        with database() as db:
            record = _load(db, ident)
        if not record:
            return jsonify(error="Bill register not found"), 404
        payload = deepcopy(record["payload"])
        payload["draft"] = not payload.get("reviewed", False)
        payload["status"] = (
            "reviewed" if payload.get("reviewed") else "DRAFT — UNREVIEWED"
        )
        output = export_register(payload, mode=mode, format=kind, paper=paper)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"bill-register-{ident}{'-DRAFT' if payload['draft'] else ''}."
            + ("xlsx" if kind == "excel" else "pdf"),
        )

    @suite.post("/api/bill-register/from-outer")
    def bill_register_from_outer():
        body = request.get_json() or {}
        ids = body.get("import_ids")
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 20
            or any(type(i) is not int for i in ids)
        ):
            raise ValueError("Provide between 1 and 20 existing import IDs")
        payload, seen = _empty(), set()
        with database() as db:
            for ident in ids:
                r = db.execute(
                    "SELECT * FROM suite_imports WHERE id=?", (ident,)
                ).fetchone()
                if not r:
                    raise ValueError("Outer import not found: " + str(ident))
                original = json.loads(r["payload"])
                extracted = original.get("extracted")
                if original.get("file_kind") != "pdf" or not isinstance(
                    extracted, dict
                ):
                    raise ValueError(
                        "Outer import must have original PDF and existing extracted fields"
                    )
                digest = r["sha256"]
                _source_path(digest)
                if digest in seen:
                    payload["issues"].append(
                        _issue(
                            "duplicate_file",
                            "Repeated outer import skipped.",
                            import_id=ident,
                        )
                    )
                    continue
                seen.add(digest)
                path = (
                    Path(current_app.config["UPLOAD_FOLDER"])
                    / "suite"
                    / (digest + ".pdf")
                )
                if (
                    not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest
                ):
                    raise ValueError("Original outer PDF unavailable or hash mismatch")
                source = _preserve(path.read_bytes(), r["filename"])
                source.update(
                    import_id=ident,
                    original_payload=original,
                    method="outer_existing_extraction",
                    status="parsed",
                    row_start=len(payload["rows"]),
                    row_count=1,
                )
                payload["sources"].append(source)
                row = {column: "" for column in COLUMNS}
                mapping = {
                    "BillNo": ["BillNo", "Bill No", "Bill Number"],
                    "BillDate": ["BillDate", "Bill Date Parsed", "Bill Date"],
                    "Type": ["BillName", "Bill Name"],
                    "Gross": ["Gross", "Gross Amount"],
                    "Net": ["Net", "Net Amount"],
                    "IncomeTax": ["IncomeTax", "Income Tax"],
                    "Month": ["Month"],
                    "Year": ["Year"],
                    "TVNo": ["TVNo", "TV No"],
                    "TokenNo": ["TokenNo", "Token No"],
                    "TVDate": ["TVDate", "TV Date"],
                    "Status": ["Status"],
                    "GroupName": ["GroupName", "Group Name"],
                    "ECSNo": ["ECSNo", "ECS No"],
                }
                mapped = {}
                source_text = ""
                try:
                    import pymupdf

                    with pymupdf.open(
                        stream=path.read_bytes(), filetype="pdf"
                    ) as source_pdf:
                        source_text = "\n".join(page.get_text() for page in source_pdf)
                except Exception:
                    pass
                for column, candidates in mapping.items():
                    key = next(
                        (k for k in candidates if extracted.get(k) is not None), None
                    )
                    if key:
                        value = extracted[key]
                        if isinstance(value, (str, int, float)) and not isinstance(
                            value, bool
                        ):
                            if column in ("Gross", "Net"):
                                printed = re.findall(
                                    column
                                    + r"\s*(?:Amount)?\s*[:\s]+[₹\s]*([\d,]+(?:\.\d+)?)",
                                    source_text,
                                    re.I,
                                )
                                unique = set(printed)
                                if len(unique) == 1:
                                    row[column] = printed[0]
                                    mapped[column] = "original printed " + column
                                else:
                                    payload["issues"].append(
                                        _issue(
                                            "unverified_outer_amount",
                                            "Printed amount missing or ambiguous; blank retained instead of a possibly rounded outer-engine value.",
                                            import_id=ident,
                                            column=column,
                                        )
                                    )
                                continue
                            row[column] = str(value)
                            mapped[column] = key
                if not row["BillNo"]:
                    refkey = next(
                        (
                            k
                            for k in ("ReferenceNumber", "Reference Number")
                            if extracted.get(k) is not None
                        ),
                        None,
                    )
                    if refkey:
                        row["BillNo"] = "Reference Number: " + str(extracted[refkey])
                        mapped["BillNo"] = refkey
                        payload["issues"].append(
                            _issue(
                                "reference_not_bill_number",
                                "Reference Number retained with its label; confirm the actual bill number.",
                                import_id=ident,
                            )
                        )
                payload["rows"].append(row)
                payload["evidence"].append(
                    dict(
                        import_id=ident,
                        source_sha256=digest,
                        mapped_fields=mapped,
                        original_extracted=extracted,
                    )
                )
                payload["issues"].append(
                    _issue(
                        "outer_mapping_review",
                        "Converted existing outer extraction; verify field mappings and missing register fields against the PDF.",
                        import_id=ident,
                    )
                )
            _duplicates(payload)
            record = _save(db, payload)
        return jsonify(record), 201
