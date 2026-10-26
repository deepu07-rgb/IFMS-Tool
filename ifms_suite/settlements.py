"""Explicit actual-payment linkage makes subsequent rate revisions auditable."""

import json
from datetime import date
from flask import request, jsonify
from .storage import database
from .payroll import (
    identity,
    reviewed_payment,
    payment_records,
    validate_period_allocations,
)
from .calculation import money
from .payment_types import entitlement_type, payment_class


def register_settlements(suite):
    @suite.post("/api/payments/<int:id>/period_allocations")
    def review_monthly_allocations(id):
        p = request.get_json() or {}
        if p.get("reviewed") is not True or not p.get("reference"):
            raise ValueError(
                "Review monthly arrear amounts against the source and give its reference"
            )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            r = db.execute("SELECT * FROM suite_payments WHERE id=?", (id,)).fetchone()
            if not r:
                return jsonify(error="Payment not found"), 404
            q = next(
                row
                for row in payment_records(db, r["employee_code"])
                if row["id"] == id
            )
            head = identity(p.get("head"))
            if payment_class(q) != "allowance_arrear":
                raise ValueError(
                    "Monthly arrear allocations require an allowance-arrear bill"
                )
            if head in q.get("allocations_by_head", {}):
                raise ValueError(
                    "This allowance already has reviewed or saved-claim allocations"
                )
            allocations = validate_period_allocations(q, {head: p.get("rows")})
            existing = db.execute(
                "SELECT payload FROM suite_payment_allocations WHERE payment_id=?",
                (id,),
            ).fetchone()
            payload = (
                json.loads(existing["payload"])
                if existing
                else dict(period=q["entitlement_period"])
            )
            payload.setdefault("allocations_by_head", {}).update(allocations)
            payload.setdefault("allocation_references", {})[head] = p["reference"]
            db.execute(
                "INSERT INTO suite_payment_allocations(payment_id,payload) VALUES(?,?) ON CONFLICT(payment_id) DO UPDATE SET payload=excluded.payload",
                (id, json.dumps(payload)),
            )
        return jsonify(status="allocated")

    @suite.post("/api/payments/<int:id>/allocate")
    def allocate(id):
        p = request.get_json() or {}
        if p.get("reviewed") is not True or not p.get("reference"):
            raise ValueError("Confirm the sanction/source and entitlement dates")
        a, b = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
        if a > b:
            raise ValueError("Invalid entitlement period")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            r = db.execute("SELECT * FROM suite_payments WHERE id=?", (id,)).fetchone()
            if not r:
                return jsonify(error="Payment not found"), 404
            q = json.loads(r["payload"])
            if (
                q.get("entitlement_period")
                or db.execute(
                    "SELECT 1 FROM suite_payment_allocations WHERE payment_id=?", (id,)
                ).fetchone()
            ):
                raise ValueError("This payment already has an approved allocation")
            if str(q.get("bill_type", "")).lower() == "regular salary":
                raise ValueError(
                    "Regular salary belongs to its payment month, not an arrear allocation"
                )
            db.execute(
                "INSERT INTO suite_payment_allocations VALUES(?,?,CURRENT_TIMESTAMP)",
                (
                    id,
                    json.dumps(
                        dict(
                            period={"start": str(a), "end": str(b)},
                            reference=p["reference"],
                        )
                    ),
                ),
            )
        return jsonify(status="allocated")

    @suite.post("/api/claims/<int:id>/settlement")
    def record_settlement(id):
        p = request.get_json() or {}
        if p.get("reviewed") is not True or not p.get("reference"):
            raise ValueError(
                "Confirm actual settlement against the external bill / GA55 record"
            )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            claim = db.execute(
                "SELECT * FROM suite_claims WHERE id=?", (id,)
            ).fetchone()
            if not claim:
                return jsonify(error="Claim not found"), 404
            if claim["status"] != "finalized":
                raise ValueError(
                    "Only an unsettled finalized statement can be linked to actual payment"
                )
            q = json.loads(claim["payload"])
            c = json.loads(claim["calculation"])
            if p.get("payment_id"):
                candidates = payment_records(db, q["employee_code"])
                payment = next(
                    (r for r in candidates if r["id"] == int(p["payment_id"])), None
                )
                if not payment:
                    raise ValueError(
                        "Reviewed payment does not belong to this employee"
                    )
                if payment_class(payment) != "allowance_arrear" or entitlement_type(
                    payment
                ) != q.get("entitlement_type", "salary"):
                    raise ValueError(
                        "Payment category does not match this arrear entitlement"
                    )
                head = {
                    identity(k): v for k, v in payment.get("allowances", {}).items()
                }
                period = payment.get("entitlement_period") or {}
                if period != {"start": q["start"], "end": q["end"]} or money(
                    head.get(q["allowance"], "0")
                ) != money(c["total"]):
                    raise ValueError(
                        "Payment amount or allocated period differs from the finalized claim"
                    )
                payment_id = payment["id"]
            else:
                payment_id = reviewed_payment(
                    db,
                    dict(
                        employee_code=q["employee_code"],
                        bill_no=p["bill_no"],
                        pay_month=p["pay_month"],
                        bill_type="Arrear " + q["allowance"],
                        entitlement_type=q.get("entitlement_type", "salary"),
                        allowances={q["allowance"]: c["total"]},
                        deductions={},
                        entitlement_period={"start": q["start"], "end": q["end"]},
                        reviewed=True,
                        reference=p["reference"],
                    ),
                )
            if db.execute(
                "SELECT 1 FROM suite_claim_settlements WHERE payment_id=?",
                (payment_id,),
            ).fetchone():
                raise ValueError("Payment is already linked to a finalized claim")
            db.execute(
                "INSERT INTO suite_claim_settlements(claim_id,payment_id,reference) VALUES(?,?,?)",
                (id, payment_id, p["reference"]),
            )
            db.execute("UPDATE suite_claims SET status='paid' WHERE id=?", (id,))
        return jsonify(status="paid", payment_id=payment_id)
