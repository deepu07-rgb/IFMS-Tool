"""Field-by-field source review, retaining original recognition and audit."""

import json
from pathlib import Path
from datetime import datetime, timezone
from flask import current_app, request, jsonify
from .storage import database
from .source_evidence import source_facts, payment_candidates
from .evidence_review import evidence_requests, apply_evidence_reviews


def reviewed_facts(payload, digest):
    raw = payload["machine_facts"]
    return apply_evidence_reviews(
        raw,
        payload.get("bill_field_reviews", []),
        digest,
        payload["machine_facts_version"],
    )


def register_evidence_routes(suite):
    @suite.route("/api/imports/<int:id>/evidence", methods=["GET", "POST"])
    def evidence(id):
        with database() as db:
            row = db.execute("SELECT * FROM suite_imports WHERE id=?", (id,)).fetchone()
            if not row:
                return jsonify(error="Import not found"), 404
            if row["status"] == "reviewed":
                raise ValueError("Reviewed imports are immutable")
            payload = json.loads(row["payload"])
            if payload.get("file_kind") != "pdf":
                raise ValueError("Source evidence review requires a PDF")
            path = (
                Path(current_app.config["UPLOAD_FOLDER"])
                / "suite"
                / (row["sha256"] + ".pdf")
            )
            source_facts(path.read_bytes(), row["sha256"], payload)
            facts = reviewed_facts(payload, row["sha256"])
            if request.method == "POST":
                review = request.get_json() or {}
                # Validate against current remaining requests, then reapply the complete
                # audit set against immutable raw recognition for subsequent reads.
                apply_evidence_reviews(
                    facts, [review], row["sha256"], payload["machine_facts_version"]
                )
                # IDs for the original snapshot remain stable across field confirmations.
                original_requests = evidence_requests(
                    payload["machine_facts"],
                    row["sha256"],
                    payload["machine_facts_version"],
                )
                current_request = next(
                    q
                    for q in evidence_requests(
                        facts, row["sha256"], payload["machine_facts_version"]
                    )
                    if q["request_id"] == review["request_id"]
                )
                match = next(
                    r
                    for r in original_requests
                    if r["bill_index"] == current_request["bill_index"]
                    and r["field"] == review["field"]
                )
                stored = dict(review, request_id=match["request_id"])
                payload.setdefault("bill_field_reviews", []).append(stored)
                payload.setdefault("bill_field_review_audit", []).append(
                    dict(stored, confirmed_at=datetime.now(timezone.utc).isoformat())
                )
                facts = reviewed_facts(payload, row["sha256"])
            payload["ga55"] = payment_candidates(facts)
            updated = db.execute(
                "UPDATE suite_imports SET payload=?,status=? WHERE id=? AND status=? AND payload=?",
                (
                    json.dumps(payload),
                    "needs_review",
                    id,
                    row["status"],
                    row["payload"],
                ),
            )
            if updated.rowcount != 1:
                raise ValueError(
                    "Import changed during extraction or review; reload it"
                )
            return jsonify(
                facts=facts,
                requests=evidence_requests(
                    facts, row["sha256"], payload["machine_facts_version"]
                ),
                ga55=payload["ga55"],
            )
