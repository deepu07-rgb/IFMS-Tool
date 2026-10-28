"""Excel-first draft preparation, independent of PDF extraction and OCR gating."""

from datetime import date
import json
import math
from flask import request, jsonify, send_file

from .storage import database
from .worksheet import calculate_worksheet, COLUMNS, HEADS, TEMPLATES
from .worksheet_excel import (
    export_workbook,
    import_workbook,
    salary_template,
    read_salaries,
)
from .worksheet_ledger import (
    month_rows,
    load_ledger_rows,
    linked_errors,
    save_salaries,
    validate_salary,
)
from .supplied_form import export_supplied_pdf


def _validate_shape(payload):
    """Incomplete scalar inputs are drafts; invalid containers are not records."""
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("Expected a worksheet object with a monthly rows list")
    if len(payload["rows"]) > 120 or any(
        not isinstance(row, dict) for row in payload["rows"]
    ):
        raise ValueError("Use up to 120 monthly row objects")
    for key in ("employee_code", "employee_name", "kind", "rounding", "template_id"):
        if payload.get(key) is not None and not isinstance(payload[key], str):
            raise ValueError("Worksheet " + key + " must be text")
    if "include_hda" in payload and not isinstance(payload["include_hda"], bool):
        raise ValueError("Include HDA must be true or false")
    for row in payload["rows"]:
        for value in row.values():
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    "Monthly inputs must be literal text, numbers or check values"
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Monthly inputs must be finite numbers")


def _result(db, payload):
    _validate_shape(payload)
    result = calculate_worksheet(payload)
    errors = linked_errors(db, payload)
    if errors:
        result["errors"].extend(errors)
        result.update(status="incomplete")
        result["bill"].update(status="blocked", blockers=result["errors"], totals=None)
    return result


def _load(db, ident):
    row = db.execute("SELECT * FROM suite_worksheets WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("Worksheet not found")
    payload = json.loads(row["payload"])
    return dict(
        id=row["id"],
        revision=row["revision"],
        payload=payload,
        result=_result(db, payload),
        audit_count=db.execute(
            "SELECT COUNT(*) FROM suite_worksheet_audit WHERE worksheet_id=?", (ident,)
        ).fetchone()[0],
    )


def _file():
    file = request.files.get("file")
    if not file or not str(file.filename).lower().endswith(".xlsx"):
        raise ValueError("Choose a macro-free .xlsx file")
    return file


def register_worksheets(suite):
    @suite.get("/api/worksheets/schema")
    def worksheet_schema():
        return jsonify(
            columns=[dict(key=k, label=l, group=g) for k, l, g in COLUMNS],
            templates=TEMPLATES,
            heads=HEADS,
        )

    @suite.get("/api/worksheets/template")
    def worksheet_template():
        today = date.today()
        start = request.args.get("start", today.replace(day=1).isoformat())
        end = request.args.get("end", start)
        payload = dict(
            employee_code="",
            employee_name="",
            kind="hra",
            rounding="rupee",
            template_id="jodhpur_classic",
            include_hda=False,
            rows=month_rows(start, end),
        )
        return send_file(
            export_workbook(payload),
            download_name="IFMS-Formula-Due-Drawn-Template.xlsx",
            as_attachment=True,
        )

    @suite.get("/api/worksheets/salary-template")
    def worksheet_salary_template():
        return send_file(
            salary_template(),
            download_name="IFMS-Salary-Ledger-Template.xlsx",
            as_attachment=True,
        )

    @suite.post("/api/worksheets/preview-import")
    def worksheet_preview():
        payload = import_workbook(_file().stream)
        with database() as db:
            return jsonify(payload=payload, result=_result(db, payload))

    @suite.post("/api/worksheets/salary-preview")
    def worksheet_salary_preview():
        rows = read_salaries(_file().stream)
        errors = []
        for i, record in enumerate(rows):
            try:
                validate_salary(record)
            except ValueError as exc:
                errors.append(dict(row=i, message=str(exc)))
        return jsonify(records=rows, errors=errors)

    @suite.post("/api/worksheets/salary-save")
    def worksheet_salary_save():
        body = request.get_json() or {}
        if body.get("reviewed") is not True:
            raise ValueError(
                "Confirm the original salary records before saving to the ledger"
            )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            ids = save_salaries(db, body.get("records"))
        return jsonify(saved=len(ids), ids=ids), 201

    @suite.get("/api/worksheets/ledger-load")
    def worksheet_ledger_load():
        with database() as db:
            rows = load_ledger_rows(
                db,
                request.args.get("employee_code"),
                request.args.get("start"),
                request.args.get("end"),
            )
        return jsonify(rows=rows)

    @suite.post("/api/worksheets/months")
    def worksheet_months():
        p = request.get_json() or {}
        return jsonify(rows=month_rows(p.get("start"), p.get("end")))

    @suite.post("/api/worksheets/calculate")
    def worksheet_calculate():
        with database() as db:
            return jsonify(_result(db, request.get_json() or {}))

    @suite.get("/api/worksheets")
    def worksheet_list():
        with database() as db:
            results = []
            for row in db.execute(
                "SELECT id,revision,payload,updated_at FROM suite_worksheets ORDER BY id DESC LIMIT 500"
            ):
                payload = json.loads(row["payload"])
                results.append(
                    dict(
                        id=row["id"],
                        revision=row["revision"],
                        employee_code=payload.get("employee_code", ""),
                        employee_name=payload.get("employee_name", ""),
                        kind=payload.get("kind", ""),
                        months=len(payload.get("rows", [])),
                        updated_at=row["updated_at"],
                    )
                )
        return jsonify(results)

    @suite.post("/api/worksheets")
    def worksheet_create():
        body = request.get_json() or {}
        payload = body.get("payload")
        with database() as db:
            _result(
                db, payload
            )  # Incomplete literal inputs can be saved, malformed objects cannot.
            ident = db.execute(
                "INSERT INTO suite_worksheets(payload,revision) VALUES(?,1)",
                (json.dumps(payload, sort_keys=True),),
            ).lastrowid
            db.execute(
                "INSERT INTO suite_worksheet_audit(worksheet_id,revision,previous_payload,new_payload) VALUES(?,1,NULL,?)",
                (ident, json.dumps(payload, sort_keys=True)),
            )
            result = _load(db, ident)
        return jsonify(result), 201

    @suite.get("/api/worksheets/<int:ident>")
    def worksheet_get(ident):
        with database() as db:
            return jsonify(_load(db, ident))

    @suite.post("/api/worksheets/<int:ident>")
    def worksheet_update(ident):
        body = request.get_json() or {}
        payload = body.get("payload")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT payload,revision FROM suite_worksheets WHERE id=?", (ident,)
            ).fetchone()
            if not old:
                raise ValueError("Worksheet not found")
            if (
                type(body.get("revision")) is not int
                or body["revision"] != old["revision"]
            ):
                return (
                    jsonify(
                        error="This worksheet changed in another tab. Reload before saving your edits."
                    ),
                    409,
                )
            _result(db, payload)
            revision = old["revision"] + 1
            encoded = json.dumps(payload, sort_keys=True)
            db.execute(
                "UPDATE suite_worksheets SET payload=?,revision=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (encoded, revision, ident),
            )
            db.execute(
                "INSERT INTO suite_worksheet_audit(worksheet_id,revision,previous_payload,new_payload) VALUES(?,?,?,?)",
                (ident, revision, old["payload"], encoded),
            )
            return jsonify(_load(db, ident))

    @suite.get("/api/worksheets/<int:ident>/excel")
    def worksheet_excel(ident):
        with database() as db:
            record = _load(db, ident)
            if linked_errors(db, record["payload"]):
                raise ValueError(
                    "Saved ledger source is stale or edited; reload it before export"
                )
        return send_file(
            export_workbook(record["payload"]),
            download_name=f"IFMS-Due-Drawn-{ident}.xlsx",
            as_attachment=True,
        )

    @suite.get("/api/worksheets/<int:ident>/pdf")
    def worksheet_pdf(ident):
        with database() as db:
            record = _load(db, ident)
        result = record["result"]
        if result["status"] != "ready":
            raise ValueError(
                "Worksheet is incomplete; resolve highlighted fields before PDF export"
            )
        return send_file(
            export_supplied_pdf(result["bill"], result["metadata"]),
            download_name=f"IFMS-Due-Drawn-{ident}.pdf",
            as_attachment=True,
        )
