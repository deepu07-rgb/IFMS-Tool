"""Explicit verified-source admission and reusable employee monthly ledger."""

from flask import request, jsonify
from .storage import database
from .ledger import employee_ledger, save_source_payments


def register_ledger(suite):
    @suite.get("/api/ledger/employees")
    def ledger_employees():
        with database() as db:
            return jsonify(
                [
                    dict(row)
                    for row in db.execute(
                        "SELECT DISTINCT p.employee_code, COALESCE(e.name, '') AS name "
                        "FROM suite_payments p LEFT JOIN suite_employees e "
                        "ON e.employee_code=p.employee_code ORDER BY p.employee_code"
                    )
                ]
            )

    @suite.get("/api/ledger")
    def ledger():
        with database() as db:
            return jsonify(employee_ledger(db, request.args.get("employee_code")))

    @suite.post("/api/imports/<int:id>/ledger")
    def save_ledger(id):
        payload = request.get_json() or {}
        if payload.get("reviewed") is not True:
            raise ValueError(
                "Confirm original source verification before saving ledger records"
            )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            ids = save_source_payments(
                db, id, payload.get("bill_indexes"), payload.get("reference")
            )
        return jsonify(saved=len(ids), ids=ids), 201
