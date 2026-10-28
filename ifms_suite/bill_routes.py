"""Source-backed whole-bill workflow; client requests cannot replace payroll facts."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone
from flask import current_app, request, jsonify, send_file
from .storage import database
from .source_evidence import source_facts
from .evidence_routes import reviewed_facts


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def case_facts(payload, digest):
    from .order_review import apply_order_reviews

    facts = (
        reviewed_facts(payload, digest)
        if payload.get("bill_field_reviews")
        else deepcopy(payload["machine_facts"])
    )
    facts.setdefault("facts_version", payload["machine_facts_version"])
    facts["source_sha256"] = digest
    from .source_bill_review import apply_bill_reviews

    facts = apply_bill_reviews(facts, payload.get("source_bill_reviews", []))
    facts = apply_order_reviews(facts, payload.get("order_reviews", []))
    for decision in payload.get("reference_page_reviews", []):
        if decision.get("snapshot") != _hash(payload["machine_facts"]):
            raise ValueError("Source extraction changed; repeat page classification")
        facts["issues"] = [
            i
            for i in facts.get("issues", [])
            if not (
                i.get("kind") == "unsupported_page"
                and i.get("page") == decision["page"]
            )
        ]
    facts["reference_statement_pages"] = [
        r["page"] for r in payload.get("reference_page_reviews", [])
    ]
    facts["reference_statement_rows"] = [
        r for rows in payload.get("statement_reference_rows", {}).values() for r in rows
    ]
    return facts


def _load(db, ident):
    row = db.execute("SELECT * FROM suite_imports WHERE id=?", (ident,)).fetchone()
    if not row:
        raise ValueError("Source import not found")
    payload = json.loads(row["payload"])
    if payload.get("file_kind") != "pdf":
        raise ValueError("Complete source bill requires a PDF")
    path = (
        Path(current_app.config["UPLOAD_FOLDER"]) / "suite" / (row["sha256"] + ".pdf")
    )
    source_facts(path.read_bytes(), row["sha256"], payload)
    return row, payload


def _save(db, row, payload):
    updated = db.execute(
        "UPDATE suite_imports SET payload=? WHERE id=? AND payload=? AND status=?",
        (json.dumps(payload), row["id"], row["payload"], row["status"]),
    )
    if updated.rowcount != 1:
        raise ValueError("Source changed during preparation; reload the case")


def _rates(db):
    rows = [
        json.loads(r["payload"]) for r in db.execute("SELECT payload FROM suite_rates")
    ]
    return rows or json.loads(
        (Path(__file__).parent / "data/rajasthan_rates.json").read_text()
    )


def _history_facts(db, facts, code):
    from .ledger import ledger_payments
    from .calculation import money
    from .payment_types import payment_class, entitlement_type

    result = deepcopy(facts)
    for payment in ledger_payments(db, code):
        matches = [
            b
            for b in result.get("bills", [])
            if b.get("employee_code") == code
            and b.get("bill_no") == payment.get("bill_no")
            and b.get("pay_month") == payment.get("pay_month")
        ]
        if matches:
            b = matches[0]
            normalize = lambda values: {
                str(k).upper(): money(v) for k, v in values.items()
            }
            if (
                (
                    payment_class(b) != payment_class(payment)
                    or entitlement_type(b) != entitlement_type(payment)
                )
                or any(
                    b.get(field) not in (None, "")
                    and payment.get(field) not in (None, "")
                    and money(b[field]) != money(payment[field])
                    for field in ("printed_gross", "printed_deductions", "printed_net")
                )
                or any(
                    normalize(b.get(field, {})) != normalize(payment.get(field, {}))
                    for field in ("allowances", "deductions")
                )
                or any(
                    field in b
                    and field in payment
                    and b[field] is not None
                    and payment[field] is not None
                    and b[field] != payment[field]
                    for field in (
                        "deduction_effects",
                        "covered_dates",
                        "entitlement_period",
                        "allocations_by_head",
                    )
                )
                or (
                    b.get("monthly_basic") not in (None, "")
                    and payment.get("monthly_basic") not in (None, "")
                    and money(b["monthly_basic"]) != money(payment["monthly_basic"])
                )
            ):
                result.setdefault("issues", []).append(
                    dict(
                        kind="history_conflict",
                        employee_code=code,
                        blocking=True,
                        issue="Saved history conflicts with source bill "
                        + str(payment.get("bill_no")),
                    )
                )
            else:
                for field in (
                    "entitlement_period",
                    "allocations_by_head",
                    "covered_dates",
                    "monthly_basic",
                ):
                    if payment.get(field):
                        b[field] = payment[field]
        else:
            # Preserve reviewed drawn salaries and all known prior credits.
            result.setdefault("bills", []).append(
                dict(
                    payment,
                    complete=payment.get("reviewed") is True,
                    evidence=deepcopy(payment.get("evidence", []))
                    + [
                        dict(
                            reference=payment.get(
                                "reference", "Saved reviewed history"
                            ),
                            payment_id=payment.get("id"),
                        )
                    ],
                )
            )
    return result


def _prepare(facts, selection, rates):
    from .bill_engine import prepare_bill

    kind = selection.get("kind")
    orders = (
        facts.get("pay_orders", [])
        if kind == "increment"
        else [
            o
            for o in facts.get("orders", [])
            if str(o.get("allowance", "")).lower() == kind
        ]
    )
    orders = [
        o for o in orders if o.get("employee_code") == selection.get("employee_code")
    ]
    if len(orders) != 1:
        return dict(
            status="blocked",
            rows=[],
            totals={},
            blockers=[
                {
                    "code": "order",
                    "message": "Select a case with one verified matching employee order; review missing or competing sanctions.",
                }
            ],
        )
    order = orders[0]
    p = dict(selection)
    p.update(
        effective_from=order["effective_from"],
        pay_order_reference=order.get("reference")
        or order.get("review_reference")
        or "Original order pages " + str(order.get("source_pages", [])),
        reviewed=order.get("human_reviewed") is True,
        complete=order.get("complete", True),
        evidence=order.get("evidence")
        or [{"source_pages": order.get("source_pages", [])}],
    )
    for k in ("effective_to", "rate", "hda_rule", "hra_eligible"):
        if k in order:
            p[k] = order[k]
    p["hra_eligibility_reference"] = (
        order.get("hra_reference") or p["pay_order_reference"]
    )
    if kind == "hra":
        p.setdefault("hra_eligible", True)
    if kind == "increment":
        p["new_basic"] = order["basic_amount"]
    bills = [
        b
        for b in facts.get("bills", [])
        if b.get("employee_code") == selection.get("employee_code")
        and b.get("allowances")
    ]
    if bills:
        first = next(
            (b for b in bills if b.get("pay_month") == selection.get("start", "")[:7]),
            bills[0],
        )
        basic = next(
            (v for k, v in first["allowances"].items() if k.upper() == "BASIC"), None
        )
        if first.get("covered_dates"):
            basic = first.get("monthly_basic")
        if basic is not None:
            p["old_basic"] = basic
        if kind != "increment":
            p["new_basic"] = basic
    result = prepare_bill(facts, p, rates)
    if facts.get("reference_statement_pages") or facts.get("reference_statement_rows"):
        from .bill_comparison import compare_statement

        result["reference_comparison"] = compare_statement(
            result, facts.get("reference_statement_rows", [])
        )
    result["deductions_confirmed"] = selection.get("deductions_reviewed") is True
    if (
        p.get("reviewed") is True
        or facts.get("source_bill_reviews")
        or any(b.get("human_reviewed") for b in facts.get("bills", []))
        or selection.get("deductions_reviewed") is True
    ):
        result["mode"] = "human_assisted"
    return result


def register_bill_routes(suite):
    @suite.route("/api/imports/<int:id>/case_review", methods=["GET", "POST"])
    def case_review(id):
        from .order_review import order_review_requests, apply_order_reviews
        from .source_bill_review import bill_review_requests, apply_bill_reviews

        with database() as db:
            row, payload = _load(db, id)
            facts = case_facts(payload, row["sha256"])
            if request.method == "POST":
                if row["status"] == "reviewed":
                    raise ValueError("Reviewed imports are immutable")
                decision = request.get_json() or {}
                if decision.get("type") == "source_bill":
                    review = {k: v for k, v in decision.items() if k != "type"}
                    apply_bill_reviews(facts, [review])
                    payload.setdefault("source_bill_reviews", []).append(review)
                elif decision.get("type") == "reference_page":
                    page = decision.get("page")
                    if (
                        decision.get("reviewed") is not True
                        or not str(decision.get("reference", "")).strip()
                    ):
                        raise ValueError("Explicit original-page review required")
                    if not any(
                        i.get("kind") == "unsupported_page" and i.get("page") == page
                        for i in facts.get("issues", [])
                    ):
                        raise ValueError("Unknown unresolved source page")
                    payload.setdefault("reference_page_reviews", []).append(
                        dict(
                            page=page,
                            reference=decision["reference"],
                            snapshot=_hash(payload["machine_facts"]),
                            confirmed_at=datetime.now(timezone.utc).isoformat(),
                        )
                    )
                else:
                    apply_order_reviews(facts, [decision])
                    payload.setdefault("order_reviews", []).append(decision)
                facts = case_facts(payload, row["sha256"])
            _save(db, row, payload)
            return jsonify(
                facts=facts,
                requests=order_review_requests(facts),
                bill_requests=bill_review_requests(facts),
                unsupported_pages=[
                    i.get("page")
                    for i in facts.get("issues", [])
                    if i.get("kind") == "unsupported_page"
                ],
            )

    @suite.post("/api/imports/<int:id>/bill_prepare")
    def bill_prepare(id):
        selection = request.get_json() or {}
        allowed = {
            "kind",
            "employee_code",
            "start",
            "end",
            "category",
            "proration",
            "rounding",
            "rounding_scope",
            "extra_deductions",
            "deductions_reviewed",
            "deduction_reference",
        }
        if selection.get("extra_deductions") and (
            selection.get("deductions_reviewed") is not True
            or not str(selection.get("deduction_reference", "")).strip()
        ):
            raise ValueError(
                "Extra arrear deductions need explicit source review and reference"
            )
        if set(selection) - allowed:
            raise ValueError(
                "Payroll source fields must come from source evidence and saved order reviews"
            )
        with database() as db:
            row, payload = _load(db, id)
            facts = _history_facts(
                db, case_facts(payload, row["sha256"]), selection.get("employee_code")
            )
            rates = _rates(db)
            result = _prepare(facts, selection, rates)
            _save(db, row, payload)
            if result["status"] == "ready" or result.get("rows"):
                saved = dict(
                    selection=selection,
                    source_sha256=row["sha256"],
                    facts_hash=_hash(facts),
                    rates_hash=_hash(rates),
                    source_import=id,
                )
                fingerprint = _hash([saved, result])
                db.execute(
                    "INSERT OR IGNORE INTO suite_bills(import_id,fingerprint,payload,result,status) VALUES(?,?,?,?,?)",
                    (
                        id,
                        fingerprint,
                        json.dumps(saved),
                        json.dumps(result),
                        "draft" if result["status"] == "ready" else "blocked",
                    ),
                )
                result["bill_id"] = db.execute(
                    "SELECT id FROM suite_bills WHERE fingerprint=?", (fingerprint,)
                ).fetchone()["id"]
            return jsonify(result)

    @suite.get("/api/bills")
    def bills():
        with database() as db:
            return jsonify(
                [
                    dict(
                        id=r["id"],
                        status=r["status"],
                        payload=json.loads(r["payload"]),
                        result=json.loads(r["result"]),
                    )
                    for r in db.execute("SELECT * FROM suite_bills ORDER BY id DESC")
                ]
            )

    @suite.post("/api/bills/<int:id>/finalize")
    def finalize_bill(id):
        review = request.get_json() or {}
        if (
            review.get("reviewed") is not True
            or review.get("deductions_reviewed") is not True
            or not str(review.get("reference", "")).strip()
        ):
            raise ValueError(
                "Confirm original sources, prior credits and additional arrear deductions with a reference"
            )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            bill = db.execute("SELECT * FROM suite_bills WHERE id=?", (id,)).fetchone()
            if not bill:
                return jsonify(error="Bill not found"), 404
            payload = json.loads(bill["payload"])
            saved = json.loads(bill["result"])
            row, current = _load(db, payload["source_import"])
            facts = _history_facts(
                db,
                case_facts(current, row["sha256"]),
                payload["selection"].get("employee_code"),
            )
            rates = _rates(db)
            if (
                row["sha256"] != payload["source_sha256"]
                or _hash(facts) != payload["facts_hash"]
                or _hash(rates) != payload["rates_hash"]
            ):
                raise ValueError(
                    "Source evidence or rates changed; prepare a fresh bill"
                )
            fresh = _prepare(facts, payload["selection"], rates)
            if fresh != saved or fresh.get("status") != "ready":
                raise ValueError("Calculation changed; prepare a fresh bill")
            if (
                saved.get("reference_comparison", {}).get("review_required")
                and review.get("comparison_reviewed") is not True
            ):
                raise ValueError(
                    "Reference statement comparison requires source review, including unreadable cells"
                )
            selection = payload["selection"]
            for other in db.execute(
                "SELECT * FROM suite_bills WHERE status='finalized' AND id<>?", (id,)
            ):
                previous = json.loads(other["payload"])["selection"]
                if (
                    previous["employee_code"] == selection["employee_code"]
                    and previous["start"] <= selection["end"]
                    and selection["start"] <= previous["end"]
                ):
                    raise ValueError(
                        "Overlapping finalized bill exists; reconcile the previous settlement first"
                    )
            for other in db.execute(
                "SELECT payload FROM suite_claims WHERE status='finalized'"
            ):
                previous = json.loads(other["payload"])
                if (
                    previous.get("employee_code") == selection["employee_code"]
                    and previous["start"] <= selection["end"]
                    and selection["start"] <= previous["end"]
                ):
                    raise ValueError(
                        "Overlapping finalized component claim exists; reconcile it first"
                    )
            db.execute(
                "UPDATE suite_bills SET status='finalized',review=? WHERE id=?",
                (
                    json.dumps(
                        dict(
                            review, confirmed_at=datetime.now(timezone.utc).isoformat()
                        )
                    ),
                    id,
                ),
            )
            return jsonify(id=id, status="finalized")

    @suite.get("/api/bills/<int:id>/<kind>")
    def export(id, kind):
        from .supplied_form import export_supplied_pdf, export_supplied_excel

        if kind not in ("pdf", "excel"):
            raise ValueError("Choose PDF or Excel")
        with database() as db:
            row = db.execute("SELECT * FROM suite_bills WHERE id=?", (id,)).fetchone()
            if not row:
                return jsonify(error="Bill not found"), 404
            payload = json.loads(row["payload"])
            result = json.loads(row["result"])
            if result.get("status") != "ready" or result.get("blockers"):
                raise ValueError("Supplied form requires a ready bill")
            try:
                original, current = _load(db, payload["source_import"])
                facts = _history_facts(
                    db,
                    case_facts(current, original["sha256"]),
                    payload["selection"]["employee_code"],
                )
                rates = _rates(db)
                if (
                    original["sha256"] != payload["source_sha256"]
                    or _hash(facts) != payload["facts_hash"]
                    or _hash(rates) != payload["rates_hash"]
                    or _prepare(facts, payload["selection"], rates) != result
                ):
                    raise ValueError(
                        "Source evidence, ledger or rates changed; prepare a fresh bill"
                    )
            except OSError as error:
                raise ValueError(
                    "Original source unavailable; restore the evidence before exporting"
                ) from error
            metadata = dict(
                payload["selection"],
                source_sha256=payload["source_sha256"],
                status=row["status"],
                bill_id=id,
                supplied_template_id=request.args.get("template", "jodhpur_classic"),
            )
            employee = db.execute(
                "SELECT name FROM suite_employees WHERE employee_code=?",
                (payload["selection"]["employee_code"],),
            ).fetchone()
            if employee:
                metadata["employee_name"] = employee["name"]
            if row["review"]:
                metadata["approval_review"] = json.loads(row["review"])
            output = (export_supplied_pdf if kind == "pdf" else export_supplied_excel)(
                result, metadata
            )
            return send_file(
                output,
                download_name=f"due-drawn-{id}." + ("pdf" if kind == "pdf" else "xlsx"),
                as_attachment=True,
            )
