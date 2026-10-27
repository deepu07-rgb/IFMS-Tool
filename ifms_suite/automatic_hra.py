"""Source-derived HRA drafts. Never supplies missing OCR digits from arithmetic."""

import json
from calendar import monthrange
from datetime import date
from decimal import Decimal
from pathlib import Path
from .calculation import calculate_claim, money
from .payment_types import classify_bill, payment_class, entitlement_type
from .increments import period_rate


def _heads(bill):
    return {str(k).upper(): money(v) for k, v in bill.get("allowances", {}).items()}


def reconcile_hra(facts, rates=None):
    if rates is None:
        rates = json.loads(
            (Path(__file__).parent / "data/rajasthan_rates.json").read_text()
        )
    blockers = []
    drafts = []
    fatal = [
        i
        for i in facts.get("issues", [])
        if (
            i.get("blocking") is True
            and i.get("scope", "document") == "document"
            and not i.get("employee_code")
        )
        or str(i.get("issue", "")).startswith(
            ("Printed page recognition unresolved", "No printed recognizer available")
        )
    ]
    if fatal:
        return dict(
            drafts=[],
            blockers=[
                "Source page recognition is incomplete; review or retry the affected pages."
            ],
        )
    if any(not b.get("employee_code") for b in facts.get("bills", [])):
        return dict(
            drafts=[],
            blockers=["A salary/credit record has unresolved employee identity."],
        )
    # Surface matched unresolved sanctions before falling back to an ID-mismatch message.
    bill_codes = {b.get("employee_code") for b in facts.get("bills", [])}
    unresolved = [
        i
        for i in facts.get("issues", [])
        if i.get("kind") == "order_unresolved"
        and i.get("blocking") is True
        and i.get("employee_code") in bill_codes
    ]
    if unresolved:
        return dict(
            drafts=[],
            blockers=[
                str(i["employee_code"])
                + ": HRA sanction needs review: "
                + ", ".join(i.get("unresolved_fields", ["source row"]))
                for i in unresolved
            ],
        )
    orders = [o for o in facts.get("orders", []) if o.get("allowance") == "HRA"]
    if not orders:
        return dict(
            drafts=[],
            blockers=["No reliable employee-specific HRA sanction row was extracted."],
        )
    if any(
        b.get("identity_reliable") is False or b.get("period_reliable") is False
        for b in facts.get("bills", [])
    ):
        return dict(
            drafts=[],
            blockers=["A bill employee identity or pay month remains uncertain."],
        )
    codes = {o.get("employee_code") for o in orders} & {
        b.get("employee_code") for b in facts.get("bills", [])
    }
    if not codes:
        return dict(
            drafts=[],
            blockers=[
                "No exact employee ID match between salary records and HRA sanction rows."
            ],
        )
    for code in sorted(codes, key=str):
        try:
            if any(
                i.get("employee_code") == code
                and (
                    (
                        i.get("blocking") is True
                        and i.get("scope", "employee") in ("employee", "bill")
                    )
                    or i.get("issue") == "Employee order date/rate unresolved"
                )
                for i in facts.get("issues", [])
            ):
                raise ValueError("A matching employee sanction row is unresolved")
            selected = [o for o in orders if o.get("employee_code") == code]
            if not code or len(selected) != 1:
                raise ValueError(
                    "Missing identity or multiple HRA effective dates need review"
                )
            order = selected[0]
            effective = date.fromisoformat(order["effective_from"])
            rate = money(order["rate"])
            if not 0 < rate <= 100:
                raise ValueError("Invalid HRA percentage")
            bills = [
                b for b in facts.get("bills", []) if b.get("employee_code") == code
            ]
            if not bills:
                raise ValueError("No GA55 bills match the sanction employee ID")
            if any(not b.get("pay_month") for b in bills):
                raise ValueError(
                    "Unresolved bill month prevents prior-credit and claim-period checks"
                )
            salaries = [
                b
                for b in bills
                if payment_class(b) == "regular_salary"
                and b["pay_month"] >= effective.strftime("%Y-%m")
            ]
            if not salaries:
                raise ValueError(
                    "No regular salary was extracted for the sanction period"
                )
            if len({b.get("bill_no") for b in salaries}) != len(salaries) or any(
                not b.get("bill_no") for b in salaries
            ):
                raise ValueError("Missing or repeated salary bill identifier")
            last = max(b["pay_month"] for b in salaries)
            stop = date.fromisoformat(last + "-01")
            stop = stop.replace(day=monthrange(stop.year, stop.month)[1])
            matched = []
            for category in {
                r.get("category", "")
                for r in rates
                if r.get("allowance", "").upper() == "HRA"
            }:
                try:
                    row = period_rate(
                        [
                            r
                            for r in rates
                            if r.get("allowance", "").upper() == "HRA"
                            and r.get("category", "") == category
                        ],
                        effective,
                        stop,
                        "HRA",
                    )
                    if money(row["rate"]) == rate:
                        matched.append(row)
                except ValueError:
                    pass
            if not matched:
                raise ValueError(
                    "Sanction rate conflicts with or crosses the dated HRA library; split/review the period"
                )
            from .payroll import validate_period_allocations

            policies = {r.get("rounding", "paise") for r in matched}
            if len(policies) != 1:
                raise ValueError("Matching HRA library entries disagree on rounding")
            rounding = policies.pop()
            credits = []
            seen_credits = set()
            for bill in bills:
                if payment_class(bill) in (
                    "regular_salary",
                    "leave_encashment",
                    "bonus",
                ):
                    continue
                amount = _heads(bill).get("HRA", Decimal(0))
                if entitlement_type(bill) != "salary":
                    continue
                if not amount:
                    known = bill.get("reviewed") is True or (
                        bill.get("complete") is True
                        and bill.get("printed_gross") is not None
                        and bool(_heads(bill))
                        and sum(_heads(bill).values()) == money(bill["printed_gross"])
                    )
                    if not known:
                        raise ValueError(
                            "Incomplete prior bill cannot establish absent HRA as zero"
                        )
                    continue
                if bill.get("reviewed") is not True:
                    if (
                        bill.get("complete") is not True
                        or bill.get("printed_gross") is None
                        or sum(_heads(bill).values()) != money(bill["printed_gross"])
                    ):
                        raise ValueError(
                            "Prior HRA amount is incomplete or unreconciled"
                        )
                if (
                    bill.get("printed_deductions") is not None
                    and bill.get("printed_net") is not None
                ):
                    if bill.get("printed_gross") is None or money(
                        bill["printed_gross"]
                    ) - money(bill["printed_deductions"]) != money(bill["printed_net"]):
                        raise ValueError(
                            "Prior HRA gross/deductions/net contradict each other"
                        )
                key = str(bill.get("bill_no") or "")
                if not key or key in seen_credits:
                    raise ValueError("Missing or duplicate prior HRA bill identifier")
                seen_credits.add(key)
                if amount < 0:
                    raise ValueError("Signed HRA corrections require source review")
                period = bill.get("entitlement_period")
                if not period:
                    raise ValueError("Prior HRA credit has no confirmed covered period")
                if period["end"] < str(effective) or period["start"] > str(stop):
                    continue
                normal = dict(
                    bill, allowances={k: str(v) for k, v in _heads(bill).items()}
                )
                parts = validate_period_allocations(
                    normal, bill.get("allocations_by_head", {})
                ).get("HRA", [])
                if not parts or sum(money(p["amount"]) for p in parts) != amount:
                    raise ValueError(
                        "Prior HRA credit needs complete monthly allocations"
                    )
                if any(money(part["amount"]) < 0 for part in parts):
                    raise ValueError(
                        "Signed prior-credit allocations require source review"
                    )
                credits.extend(parts)
            segments = []
            cursor = effective.replace(day=1)
            while cursor <= stop:
                month = cursor.strftime("%Y-%m")
                rows = [b for b in salaries if b["pay_month"] == month]
                if len(rows) != 1:
                    raise ValueError("Missing or duplicate regular salary for " + month)
                bill = rows[0]
                heads = _heads(bill)
                if (
                    not bill.get("complete")
                    or not heads
                    or "BASIC" not in heads
                    or heads.get("BASIC", Decimal(0)) <= 0
                    or bill.get("printed_gross") is None
                    or sum(heads.values()) != money(bill["printed_gross"])
                ):
                    raise ValueError(
                        "Incomplete/unreconciled allowance record for " + month
                    )
                if (
                    bill.get("printed_deductions") is not None
                    and bill.get("printed_net") is not None
                ):
                    deduction = money(bill["printed_deductions"])
                    if money(bill["printed_gross"]) - deduction != money(
                        bill["printed_net"]
                    ):
                        raise ValueError(
                            "Printed gross/deductions/net contradict each other for "
                            + month
                        )
                    if (
                        bill.get("deductions") is not None
                        and sum(
                            money(v)
                            for k, v in bill["deductions"].items()
                            if bill.get("deduction_effects", {}).get(k, True)
                        )
                        != deduction
                    ):
                        raise ValueError(
                            "Recognized deductions do not reconcile for " + month
                        )
                a = max(cursor, effective)
                b = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
                drawn = heads.get("HRA", Decimal(0))
                if a.day != 1 and drawn:
                    raise ValueError(
                        "Partial-month drawn HRA requires an explicit period allocation"
                    )
                prior = Decimal(0)
                for part in credits:
                    if part["start"] <= str(b) and str(a) <= part["end"]:
                        if not (str(a) <= part["start"] <= part["end"] <= str(b)):
                            raise ValueError(
                                "Align prior HRA credit allocation with eligible dates"
                            )
                        prior += money(part["amount"])
                segments.append(
                    dict(
                        start=str(a),
                        end=str(b),
                        basic=str(heads["BASIC"]),
                        due_rate=str(rate),
                        drawn_amount=str(drawn),
                        drawn_basis="monthly_amount",
                        rounding=rounding,
                        prior_settlement=str(prior),
                        source="GA55 bill "
                        + str(bill.get("bill_no", ""))
                        + " pages "
                        + str(bill.get("source_pages", [])),
                        rule_reference="Attached employee HRA sanction pages "
                        + str(order.get("source_pages", [])),
                    )
                )
                cursor = (
                    b.replace(day=1).replace(year=b.year + 1, month=1)
                    if b.month == 12
                    else b.replace(day=1, month=b.month + 1)
                )
            calculation = calculate_claim(str(effective), str(stop), segments)
            payload = dict(
                employee_code=code,
                allowance="HRA",
                start=str(effective),
                end=str(stop),
                source="automatic_hra",
                machine_generated=True,
                entitlement_type="salary",
                segments=segments,
                rule_reference="Matched employee-specific attached HRA sanction",
                drawn_reference="Machine-extracted reconciled GA55 allowance records",
                machine_evidence=dict(
                    order=order, bills=salaries, rate_matches=matched
                ),
                deductions_review_required=True,
            )
            drafts.append(dict(payload=payload, calculation=calculation))
        except (ValueError, KeyError, TypeError) as exc:
            blockers.append(str(code or "Unknown employee") + ": " + str(exc))
    return dict(drafts=drafts, blockers=blockers)


def register_automatic_hra(suite):
    @suite.post("/api/imports/<int:id>/automatic_hra")
    def automatic_hra(id):
        import hashlib
        from flask import current_app, request, jsonify
        from .storage import database
        from .document_facts import extract_document_facts, FACTS_VERSION
        from .payroll import payment_records

        with database() as db:
            source = db.execute(
                "SELECT * FROM suite_imports WHERE id=?", (id,)
            ).fetchone()
            if not source:
                return jsonify(error="Import not found"), 404
            original = json.loads(source["payload"])
        if original.get("file_kind") != "pdf":
            raise ValueError("Select a PDF containing GA55 and HRA sanction pages")
        path = (
            Path(current_app.config["UPLOAD_FOLDER"])
            / "suite"
            / (source["sha256"] + ".pdf")
        )
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("Original source changed; reimport it")
        from .source_evidence import source_facts

        facts = source_facts(
            data,
            source["sha256"],
            original,
            refresh=(request.get_json() or {}).get("refresh") is True,
        )
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = json.loads(
                db.execute(
                    "SELECT payload FROM suite_imports WHERE id=?", (id,)
                ).fetchone()["payload"]
            )
            current_source = db.execute(
                "SELECT status,payload FROM suite_imports WHERE id=?", (id,)
            ).fetchone()
            if (
                current_source["payload"] != source["payload"]
                or current_source["status"] != source["status"]
            ):
                raise ValueError("Import changed during extraction; reload it")
            for key in (
                "bill_field_reviews",
                "superseded_bill_field_reviews",
                "order_reviews",
                "reference_page_reviews",
                "source_bill_reviews",
                "superseded_case_reviews",
            ):
                if key in original:
                    latest[key] = original[key]
            latest.update(machine_facts=facts, machine_facts_version=FACTS_VERSION)
            db.execute(
                "UPDATE suite_imports SET payload=? WHERE id=?",
                (json.dumps(latest), id),
            )
            from .evidence_routes import reviewed_facts

            evidence = (
                reviewed_facts(latest, source["sha256"])
                if latest.get("bill_field_reviews")
                else facts
            )
            result = workspace_reconciliation(
                db, evidence, latest.get("machine_fact_reviews", [])
            )
            claims = []
            for draft in result["drafts"]:
                p = draft["payload"]
                p.update(
                    source_import=id,
                    source_sha256=source["sha256"],
                    machine_facts_version=FACTS_VERSION,
                )
                fingerprint = hashlib.sha256(
                    json.dumps(draft, sort_keys=True).encode()
                ).hexdigest()
                existing = next(
                    (
                        row
                        for row in db.execute("SELECT * FROM suite_claims")
                        if json.loads(row["payload"]).get("automatic_fingerprint")
                        == fingerprint
                    ),
                    None,
                )
                if existing:
                    claim_id = existing["id"]
                else:
                    p["automatic_fingerprint"] = fingerprint
                    claim_id = db.execute(
                        "INSERT INTO suite_claims(payload,calculation) VALUES(?,?)",
                        (json.dumps(p), json.dumps(draft["calculation"])),
                    ).lastrowid
                claims.append(
                    dict(
                        id=claim_id,
                        calculation=draft["calculation"],
                        employee_code=p["employee_code"],
                        human_assisted=p["machine_evidence"]["order"].get(
                            "human_reviewed"
                        )
                        is True,
                    )
                )
            return jsonify(
                review_requests=result.get("review_requests", []),
                claims=claims,
                blockers=result["blockers"],
                facts=facts,
                notice="Machine-generated draft. Verify source facts, eligibility and deductions before final approval.",
            )

    @suite.post("/api/imports/<int:id>/fact_review")
    def confirm_fact(id):
        import hashlib
        from datetime import datetime, timezone
        from flask import request, jsonify, current_app
        from .storage import database
        from .fact_review import apply_rate_reviews

        review = request.get_json() or {}
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM suite_imports WHERE id=?", (id,)).fetchone()
            if not row:
                return jsonify(error="Import not found"), 404
            original = json.loads(row["payload"])
            path = (
                Path(current_app.config["UPLOAD_FOLDER"])
                / "suite"
                / (row["sha256"] + ".pdf")
            )
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
            ):
                raise ValueError("Original source changed; reimport it")
            facts = original.get("machine_facts", {})
            apply_rate_reviews(facts, [review])
            record = dict(
                review,
                source_sha256=row["sha256"],
                recorded_at=datetime.now(timezone.utc).isoformat(),
            )
            old = original.get("machine_fact_reviews", [])
            original["machine_fact_reviews"] = [
                r for r in old if r.get("request_id") != review["request_id"]
            ] + [record]
            original.setdefault("machine_fact_review_audit", []).append(record)
            db.execute(
                "UPDATE suite_imports SET payload=? WHERE id=?",
                (json.dumps(original), id),
            )
        return automatic_hra(id)

    @suite.get("/api/imports/<int:id>/fact_review/<request_id>/image")
    def fact_review_image(id, request_id):
        import io
        import pymupdf
        from flask import jsonify, current_app, send_file
        from .storage import database
        from .fact_review import rate_review_requests

        with database() as db:
            row = db.execute("SELECT * FROM suite_imports WHERE id=?", (id,)).fetchone()
            if not row:
                return jsonify(error="Import not found"), 404
            original = json.loads(row["payload"])
        matches = [
            r
            for r in rate_review_requests(original.get("machine_facts", {}))
            if r["request_id"] == request_id
        ]
        if len(matches) != 1:
            return jsonify(error="Review field not found"), 404
        item = matches[0]
        boxes = [e["box"] for e in item["evidence"] if e.get("box")]
        if not boxes:
            raise ValueError("No source region available")
        path = (
            Path(current_app.config["UPLOAD_FOLDER"])
            / "suite"
            / (row["sha256"] + ".pdf")
        )
        import hashlib

        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
        ):
            raise ValueError("Original source changed; reimport it")
        with pymupdf.open(path) as doc:
            if not 1 <= item["page"] <= len(doc):
                raise ValueError("Source page unavailable")
            page = doc[item["page"] - 1]
            rect = page.rect
            y1 = max(0, min(b[1] for b in boxes) - 0.025)
            y2 = min(1, max(b[3] for b in boxes) + 0.025)
            clip = pymupdf.Rect(0, y1 * rect.height, rect.width, y2 * rect.height)
            content = page.get_pixmap(dpi=180, clip=clip).tobytes("png")
        return send_file(io.BytesIO(content), mimetype="image/png")


def workspace_reconciliation(db, facts, reviews=None):
    from .payroll import payment_records

    facts = json.loads(json.dumps(facts))
    from .fact_review import apply_rate_reviews, rate_review_requests

    requests = {r["request_id"]: r for r in rate_review_requests(facts)}
    active = [
        r
        for r in (reviews or [])
        if r.get("request_id") in requests
        and r.get("facts_version") == requests[r["request_id"]]["facts_version"]
    ]
    if active:
        facts = apply_rate_reviews(facts, active)
    for code in {
        o.get("employee_code")
        for o in facts.get("orders", [])
        if o.get("employee_code")
    }:
        saved = payment_records(db, code)
        for payment in saved:
            if payment_class(payment) in (
                "regular_salary",
                "bonus",
                "leave_encashment",
            ):
                continue
            matches = [
                b
                for b in facts.get("bills", [])
                if b.get("employee_code") == code
                and b.get("bill_no") == payment.get("bill_no")
            ]
            if matches:
                for bill in matches:
                    for key in ("entitlement_period", "allocations_by_head"):
                        if payment.get(key):
                            bill[key] = payment[key]
            else:
                facts.setdefault("bills", []).append(payment)
    rates = [
        json.loads(r["payload"]) for r in db.execute("SELECT payload FROM suite_rates")
    ]
    result = reconcile_hra(
        facts,
        (
            rates
            if any(r.get("allowance", "").upper() == "HRA" for r in rates)
            else None
        ),
    )
    result["review_requests"] = rate_review_requests(facts)
    return result


def validate_automatic_draft(db, payload, calculation, review):
    import hashlib
    from flask import current_app
    from .document_facts import FACTS_VERSION

    if (
        payload.get("entitlement_type") != "salary"
        or payload.get("machine_generated") is not True
    ):
        raise ValueError("Machine draft type changed; rebuild from the original import")
    if review.get("machine_facts_reviewed") is not True:
        raise ValueError(
            "Check machine-extracted employee, dates, source amounts, eligibility and deductions before final approval"
        )
    source = db.execute(
        "SELECT * FROM suite_imports WHERE id=?", (payload.get("source_import"),)
    ).fetchone()
    if not source or source["sha256"] != payload.get("source_sha256"):
        raise ValueError("Machine draft source is missing or changed; rebuild it")
    original = json.loads(source["payload"])
    path = (
        Path(current_app.config["UPLOAD_FOLDER"])
        / "suite"
        / (source["sha256"] + ".pdf")
    )
    if (
        not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]
    ):
        raise ValueError("Original PDF changed; reimport before approval")
    if (
        original.get("machine_facts_version") != FACTS_VERSION
        or payload.get("machine_facts_version") != FACTS_VERSION
    ):
        raise ValueError("Extraction version changed; rebuild the machine draft")
    from .evidence_routes import reviewed_facts

    evidence = (
        reviewed_facts(original, source["sha256"])
        if original.get("bill_field_reviews")
        else original.get("machine_facts", {})
    )
    fresh = workspace_reconciliation(
        db, evidence, original.get("machine_fact_reviews", [])
    )
    target = [
        d
        for d in fresh["drafts"]
        if all(
            d["payload"].get(k) == payload.get(k)
            for k in ("employee_code", "start", "end", "allowance")
        )
    ]
    if (
        len(target) != 1
        or target[0]["calculation"] != calculation
        or target[0]["payload"]["segments"] != payload.get("segments")
        or target[0]["payload"]["machine_evidence"] != payload.get("machine_evidence")
    ):
        raise ValueError(
            "Source facts, library or prior credits changed; rebuild and review the machine draft"
        )
