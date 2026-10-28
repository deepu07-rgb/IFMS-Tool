import hashlib, json, sqlite3
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request, render_template, send_file
from .storage import database, initialize
from .calculation import calculate_claim
from . import exports

suite = Blueprint(
    "suite",
    __name__,
    template_folder="templates",
    static_folder="static",
    url_prefix="/suite",
)


@suite.errorhandler(ValueError)
def bad_input(error):
    return jsonify(error=str(error)), 400


@suite.before_request
def validate_local_request():
    from urllib.parse import urlsplit

    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin:
            actual = urlsplit(origin)
            expected = urlsplit(request.host_url)
            if (actual.scheme, actual.netloc.lower()) != (
                expected.scheme,
                expected.netloc.lower(),
            ):
                return (
                    jsonify(
                        error="Open IFMS directly before changing workspace records"
                    ),
                    403,
                )
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(error="Cross-site workspace changes are not allowed"), 403
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and request.is_json
        and not isinstance(request.get_json(), dict)
    ):
        raise ValueError("Expected a JSON object")


@suite.errorhandler(KeyError)
def missing_input(error):
    return jsonify(error="Required field missing: " + str(error)), 400


@suite.get("/api/ocr_status")
def ocr_status():
    from .documents import ocr_runtime

    try:
        executable, env, languages = ocr_runtime()
        return jsonify(available=True, languages=sorted(languages))
    except (ValueError, OSError):
        return jsonify(available=False, languages=[])


@suite.get("/api/reference/<filename>")
def reference_order(filename):
    root = Path(__file__).resolve().parent.parent / "reference_orders"
    path = (root / filename).resolve()
    if (
        path.parent != root.resolve()
        or path.suffix.lower() != ".pdf"
        or not path.is_file()
    ):
        return jsonify(error="Reference order not found"), 404
    return send_file(path, mimetype="application/pdf", download_name=filename)


@suite.get("/")
def home():
    return render_template("suite.html")


@suite.route("/api/employees", methods=["GET", "POST"])
def employees():
    with database() as db:
        if request.method == "GET":
            return jsonify(
                [
                    json.loads(r["payload"])
                    for r in db.execute(
                        "SELECT payload FROM suite_employees ORDER BY name"
                    )
                ]
            )
        p = request.get_json() or {}
        code = str(p.get("employee_code", "")).strip().upper()
        if not code or not p.get("name"):
            raise ValueError("Employee code and name required")
        p["employee_code"] = code
        existing = db.execute(
            "SELECT payload FROM suite_employees WHERE employee_code=?", (code,)
        ).fetchone()
        if existing:
            if json.loads(existing["payload"]) == p:
                return jsonify(p)
            return (
                jsonify(
                    error="Conflicting employee record. Resolve identity before replacing history.",
                    existing=json.loads(existing["payload"]),
                ),
                409,
            )
        db.execute(
            "INSERT INTO suite_employees VALUES(?,?,?)",
            (code, p["name"], json.dumps(p)),
        )
        return jsonify(p), 201


@suite.route("/api/rates", methods=["GET", "POST"])
def rates():
    from .rate_library import save_rate

    with database() as db:
        if request.method == "GET":
            return jsonify(
                [
                    dict(
                        json.loads(r["payload"]),
                        id=r["id"],
                        revision=json.loads(r["payload"]).get("revision", 1),
                    )
                    for r in db.execute("SELECT * FROM suite_rates")
                ]
            )
        db.execute("BEGIN IMMEDIATE")
        saved, error = save_rate(db, request.get_json() or {})
        if error:
            return (
                jsonify(
                    error="Rate already exists. Provide an override reason to replace it; previous version is retained."
                ),
                409,
            )
        return jsonify(saved), 201


@suite.route("/api/claims", methods=["GET", "POST"])
def claims():
    with database() as db:
        if request.method == "GET":
            return jsonify(
                [
                    dict(
                        id=r["id"],
                        status=r["status"],
                        payload=json.loads(r["payload"]),
                        calculation=json.loads(r["calculation"]),
                    )
                    for r in db.execute("SELECT * FROM suite_claims ORDER BY id DESC")
                ]
            )
        p = request.get_json() or {}
        if p.get("source") == "automatic_hra":
            raise ValueError("Machine drafts must be created from their source import")
        if not p.get("employee_code") or not p.get("allowance"):
            raise ValueError("Employee and allowance required")
        from datetime import date

        if p.get("entitlement_type", "salary") not in ("salary", "leave_encashment"):
            raise ValueError("Unknown entitlement type")
        p["employee_code"] = str(p["employee_code"]).strip().upper()
        p["allowance"] = str(p["allowance"]).strip().upper()
        p["start"] = date.fromisoformat(p["start"]).isoformat()
        p["end"] = date.fromisoformat(p["end"]).isoformat()
        from .payroll import calculate_payload

        try:
            r = calculate_payload(db, p)
        except KeyError as e:
            raise ValueError("Missing claim input: " + str(e)) from None
        id = db.execute(
            "INSERT INTO suite_claims(payload,calculation) VALUES(?,?)",
            (json.dumps(p), json.dumps(r)),
        ).lastrowid
        return jsonify(id=id, calculation=r), 201


@suite.post("/api/claims/<int:id>/finalize")
def finalize(id):
    p = request.get_json() or {}
    if (
        p.get("reviewed") is not True
        or not p.get("rule_reference")
        or not p.get("drawn_reference")
    ):
        raise ValueError(
            "Confirm reviewed inputs and provide rate/order and drawn-payment references"
        )
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM suite_claims WHERE id=?", (id,)).fetchone()
        if not row:
            return jsonify(error="Claim not found"), 404
        if row["status"] == "finalized":
            return jsonify(status="finalized")
        payload = json.loads(row["payload"])
        from .payroll import guard_prior_arrears

        if payload.get("source") == "automatic_hra":
            from .automatic_hra import validate_automatic_draft

            validate_automatic_draft(db, payload, json.loads(row["calculation"]), p)
        else:
            guard_prior_arrears(db, payload)
        if payload.get("source") == "history":
            from .payroll import calculate_payload

            fresh_payload = json.loads(row["payload"])
            fresh = calculate_payload(db, fresh_payload)
            if fresh != json.loads(row["calculation"]):
                raise ValueError(
                    "Reviewed history or rates changed. Prepare a fresh draft and review its calculation."
                )
        elif payload.get("source") != "automatic_hra":
            from .payroll import validate_manual_settlements

            validate_manual_settlements(db, payload)
        if payload.get("source") == "reviewed_increment":
            from datetime import date

            if not payload.get("increment_effective_from") or date.fromisoformat(
                payload["increment_effective_from"]
            ) > date.fromisoformat(payload["start"]):
                raise ValueError(
                    "Recheck the increment and confirm its approved effective date before finalization"
                )
            from .increments import guard_prior_increment

            guard_prior_increment(
                db,
                payload["employee_code"],
                payload["start"],
                payload["end"],
                payload.get("increment_heads", [payload["allowance"]]),
            )
            from .increments import period_rate
            from datetime import date

            current_rates = [
                json.loads(r["payload"])
                for r in db.execute("SELECT payload FROM suite_rates")
            ]
            for head, saved in payload.get("rate_snapshot", {}).items():
                current = period_rate(
                    [
                        r
                        for r in current_rates
                        if r["allowance"].upper() == head
                        and r.get("category", "") == saved.get("category", "")
                    ],
                    date.fromisoformat(payload["start"]),
                    date.fromisoformat(payload["end"]),
                    head + " rate",
                )
                if current != saved:
                    raise ValueError(
                        "Library rates changed; recheck the increment before finalizing"
                    )
        for other in db.execute(
            "SELECT * FROM suite_claims WHERE status IN ('finalized','paid')"
        ):
            q = json.loads(other["payload"])
            overlap = (
                str(q["employee_code"]).strip().upper() == payload["employee_code"]
                and str(q["allowance"]).strip().upper() == payload["allowance"]
                and q.get("entitlement_type", "salary")
                == payload.get("entitlement_type", "salary")
                and q["start"] <= payload["end"]
                and payload["start"] <= q["end"]
            )
            if not overlap:
                continue
            settlement = db.execute(
                "SELECT payment_id FROM suite_claim_settlements WHERE claim_id=?",
                (other["id"],),
            ).fetchone()
            applied = {
                pid
                for segment in payload.get("segments", [])
                for pid in segment.get("settlement_ids", [])
            }
            if (
                other["status"] == "paid"
                and settlement
                and settlement["payment_id"] in applied
            ):
                continue
            raise ValueError(
                "Overlapping finalized claim: link and deduct its actual saved settlement before preparing a revision"
            )
        db.execute(
            "UPDATE suite_claims SET status='finalized',review=? WHERE id=?",
            (json.dumps(p), id),
        )
    return jsonify(status="finalized")


@suite.get("/api/claims/<int:id>/<kind>")
def export_claim(id, kind):
    with database() as db:
        r = db.execute("SELECT * FROM suite_claims WHERE id=?", (id,)).fetchone()
    if not r:
        return jsonify(error="Claim not found"), 404
    p, c = json.loads(r["payload"]), json.loads(r["calculation"])
    review = json.loads(r["review"] or "{}")
    p.update(
        {k: review[k] for k in ("rule_reference", "drawn_reference") if k in review}
    )
    p["status"] = r["status"]
    if kind == "excel":
        b = exports.excel(p, c)
        ext = "xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif kind == "pdf":
        b = exports.pdf(p, c)
        ext = "pdf"
        mime = "application/pdf"
    else:
        return jsonify(error="Unknown export format"), 404
    return send_file(
        b,
        as_attachment=True,
        download_name=f'claim-{id}-{r["status"]}.{ext}',
        mimetype=mime,
    )


@suite.route("/api/imports", methods=["GET", "POST"])
def imports():
    with database() as db:
        if request.method == "GET":
            return jsonify(
                [
                    dict(
                        id=r["id"],
                        filename=r["filename"],
                        status=r["status"],
                        payload=json.loads(r["payload"]),
                    )
                    for r in db.execute("SELECT * FROM suite_imports ORDER BY id DESC")
                ]
            )
        f = request.files.get("file")
        if not f:
            raise ValueError("Select a PDF")
        data = f.read(50 * 1024 * 1024 + 1)
        if len(data) > 50 * 1024 * 1024:
            raise ValueError("PDF exceeds 50 MB")
        is_pdf = data.startswith(b"%PDF")
        is_xlsx = data.startswith(b"PK") and f.filename.lower().endswith(".xlsx")
        if not is_pdf and not is_xlsx:
            raise ValueError("Expected PDF or XLSX file")
        kind = request.form.get("kind", "ga55")
        if is_xlsx and kind != "due_drawn":
            raise ValueError(
                "Excel input currently supports due–drawn statements; use the group analyzer for employee spreadsheets"
            )
        digest = hashlib.sha256(data).hexdigest()
        existing = db.execute(
            "SELECT id FROM suite_imports WHERE sha256=?", (digest,)
        ).fetchone()
        if existing:
            return jsonify(id=existing["id"], duplicate=True)
        suffix = ".pdf" if is_pdf else ".xlsx"
        folder = Path(current_app.config["UPLOAD_FOLDER"]) / "suite"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (digest + suffix)
        path.write_bytes(data)
        if is_pdf:
            import pymupdf

            try:
                with pymupdf.open(stream=data, filetype="pdf") as doc:
                    pages = [p.get_text() for p in doc]
                    from .documents import page_needs_ocr

                    scan_pages = [p.number + 1 for p in doc if page_needs_ocr(p)]
            except Exception:
                raise ValueError(
                    "PDF could not be read; check encryption or file integrity"
                ) from None
            payload = dict(
                kind=kind, pages=pages, requires_review=True, file_kind="pdf"
            )
            if kind == "outer":
                from outer_engine.parser import extract_pdf_data

                payload["extracted"] = extract_pdf_data(str(path), f.filename)
            if kind == "ga55":
                from .documents import parse_ga55

                payload["ga55"] = parse_ga55(pages)
            if kind == "due_drawn":
                from .due_drawn import parse_pdf_tables

                payload["statement_rows"] = parse_pdf_tables(data)
            payload["scan_pages"] = scan_pages
            if payload["scan_pages"]:
                payload["notice"] = (
                    "Scanned pages require OCR and review; no amounts inferred."
                )
        else:
            from .due_drawn import parse_workbook

            payload = dict(
                parse_workbook(data), kind=kind, file_kind="xlsx", scan_pages=[]
            )
        id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            (digest, Path(f.filename).name, json.dumps(payload)),
        ).lastrowid
        return jsonify(id=id, payload=payload), 201


@suite.post("/api/group_import")
def group_import():
    p = request.get_json() or {}
    records = p.get("records", [])
    if not isinstance(records, list) or len(records) > 100000:
        raise ValueError("Invalid group records")
    groups = {}
    for row in records:
        code = str(row.get("employeeCode") or row.get("employee_code") or "").strip()
        if code:
            groups.setdefault(code, []).append(row)
    conflicts = sum(
        len({json.dumps(r, sort_keys=True) for r in rows}) > 1
        for rows in groups.values()
    )
    with database() as db:
        id = db.execute(
            "INSERT INTO suite_group_imports(payload) VALUES(?)", (json.dumps(p),)
        ).lastrowid
    return (
        jsonify(
            id=id,
            rows=len(records),
            identified=len(groups),
            conflicts=conflicts,
            status="needs_review",
        ),
        201,
    )


@suite.get("/api/imports/<int:id>/source")
def source_pdf(id):
    with database() as db:
        row = db.execute("SELECT * FROM suite_imports WHERE id=?", (id,)).fetchone()
    if not row:
        return jsonify(error="Import not found"), 404
    file_kind = json.loads(row["payload"]).get("file_kind", "pdf")
    path = (
        Path(current_app.config["UPLOAD_FOLDER"])
        / "suite"
        / (row["sha256"] + "." + file_kind)
    )
    return send_file(
        path, download_name=row["filename"], as_attachment=file_kind != "pdf"
    )


@suite.post("/api/imports/<int:id>/ocr")
def ocr_import(id):
    from .documents import ocr_document, parse_ga55

    with database() as db:
        row = db.execute("SELECT * FROM suite_imports WHERE id=?", (id,)).fetchone()
        if not row:
            return jsonify(error="Import not found"), 404
        if row["status"] == "reviewed":
            raise ValueError(
                "Reviewed imports are immutable; OCR cannot replace approved evidence"
            )
        path = (
            Path(current_app.config["UPLOAD_FOLDER"])
            / "suite"
            / (row["sha256"] + ".pdf")
        )
        payload = json.loads(row["payload"])
        data = path.read_bytes()
        if payload["kind"] == "ga55":
            from .source_evidence import source_facts, payment_candidates

            facts = source_facts(
                data,
                row["sha256"],
                payload,
                refresh=(request.get_json() or {}).get("refresh") is True,
            )
            if payload.get("bill_field_reviews"):
                from .evidence_routes import reviewed_facts

                facts = reviewed_facts(payload, row["sha256"])
            payload["ga55"] = payment_candidates(facts)
        else:
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Original source changed; reimport it")
            pages, derivative = ocr_document(
                data, (request.get_json() or {}).get("language", "eng")
            )
            path.with_suffix(".ocr.pdf").write_bytes(derivative)
            payload["pages"] = pages
            if payload["kind"] == "due_drawn":
                from .due_drawn import parse_pdf_tables

                payload["statement_rows"] = parse_pdf_tables(derivative)
        payload["ocr_used"] = True
        payload["notice"] = payload.get("ga55", {}).get(
            "notice",
            "OCR output requires source review, including digits, signs and dates.",
        )
        updated = db.execute(
            "UPDATE suite_imports SET payload=?,status='needs_review' WHERE id=? AND status=? AND payload=?",
            (json.dumps(payload), id, row["status"], row["payload"]),
        )
        if updated.rowcount != 1:
            raise ValueError("Import changed during OCR; reload it")
    return jsonify(payload)


@suite.post("/api/imports/<int:id>/review")
def review_import(id):
    from .calculation import money
    from datetime import date

    p = request.get_json() or {}
    payments = p.get("payments", [])
    if (
        p.get("reviewed") is not True
        or not payments
        or (
            not p.get("employee_code")
            and any(not r.get("employee_code") for r in payments)
        )
    ):
        raise ValueError(
            "Employee identity, reviewed payments and explicit source confirmation are required"
        )
    for payment in payments:
        if (
            not payment.get("bill_no")
            or not payment.get("pay_month")
            or not payment.get("bill_type")
        ):
            raise ValueError("Payment requires bill number, month and type")
        date.fromisoformat(payment["pay_month"] + "-01")
        for amounts in [payment.get("allowances", {}), payment.get("deductions", {})]:
            for v in amounts.values():
                money(v)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT status,payload FROM suite_imports WHERE id=?", (id,)
        ).fetchone()
        if not row:
            return jsonify(error="Import not found"), 404
        if row["status"] == "reviewed":
            raise ValueError(
                "Import already reviewed; preserve existing payment history"
            )
        from .payroll import reviewed_payment

        column_ocr = json.loads(row["payload"]).get("ga55", {}).get("layout") in (
            "GA55 A column OCR",
            "Shared geometric source evidence",
        )
        if column_ocr and any(
            any(
                payment.get(k) in (None, "")
                for k in ("printed_gross", "printed_deductions", "printed_net")
            )
            for payment in payments
        ):
            raise ValueError(
                "Column OCR requires source-checked printed gross, deductions and net before payment approval"
            )
        for payment in payments:
            payment = dict(
                payment,
                employee_code=payment.get("employee_code") or p.get("employee_code"),
                reviewed=True,
                reference="Reviewed source import " + str(id),
            )
            reviewed_payment(db, payment, id)
        db.execute("UPDATE suite_imports SET status='reviewed' WHERE id=?", (id,))
    return jsonify(status="reviewed", payments=len(payments))


@suite.get("/api/payments")
def payments():
    from .payroll import payment_records

    with database() as db:
        rows = payment_records(db, request.args.get("employee_code", ""))
    return jsonify(rows)


from .analyzer_bridge import register_analyzer_bridge

register_analyzer_bridge(suite)

from .document_exports import register_document_exports

register_document_exports(suite)

from .increments import register_increments

register_increments(suite)

from .statements import register_statements

register_statements(suite)

from .batch_exports import register_batch_exports

register_batch_exports(suite)

from .backups import register_backups

register_backups(suite)

from .settlements import register_settlements

register_settlements(suite)

from .groups import register_groups

register_groups(suite)

from .payroll import register_payroll

register_payroll(suite)


from .automatic_hra import register_automatic_hra

register_automatic_hra(suite)


def register_suite(app):
    with app.app_context():
        initialize()
        if not app.config.get("TESTING"):
            from .reference import load_reference

            with database() as db:
                load_reference(db)
    app.register_blueprint(suite)


from .evidence_routes import register_evidence_routes

register_evidence_routes(suite)

from .bill_routes import register_bill_routes

register_bill_routes(suite)

from .statement_grid_routes import register_statement_grid_routes

register_statement_grid_routes(suite)

from .document_records import register_document_records

register_document_records(suite)

from .ledger_routes import register_ledger

register_ledger(suite)

from .worksheet_routes import register_worksheets

register_worksheets(suite)

from .rate_library import register_rate_library

register_rate_library(suite)

from .slab_library import register_slabs
from .document_library import register_document_library

register_slabs(suite)
register_document_library(suite)
