"""Reviewed histories, reusable rules and batch preparation services."""

import json
from datetime import date, timedelta
from flask import request, jsonify
from .storage import database
from .calculation import money, rounded, calculate_claim
from .history import prepare_segments
from .payment_types import classify_bill, entitlement_type


def identity(value):
    return str(value or "").strip().upper()


def reviewed_payment(db, p, import_id=0):
    if p.get("reviewed") is not True:
        raise ValueError("Confirm source review before saving a payment")
    code = identity(p.get("employee_code"))
    if (
        not code
        or not p.get("reference")
        or not p.get("bill_no")
        or not p.get("bill_type")
    ):
        raise ValueError("Employee, bill number, type and source reference required")
    p["payment_class"] = p.get("payment_class") or classify_bill(p["bill_type"])
    if p["payment_class"] not in (
        "regular_salary",
        "allowance_arrear",
        "leave_encashment",
        "bonus",
        "other",
    ):
        raise ValueError("Unknown payment category")
    p["entitlement_type"] = entitlement_type(p)
    if p["entitlement_type"] not in ("salary", "leave_encashment"):
        raise ValueError("Unknown entitlement type")
    date.fromisoformat(p["pay_month"] + "-01")
    for kind in ("allowances", "deductions"):
        values = {identity(k): money(v) for k, v in p.get(kind, {}).items()}
        if any(v != rounded(v) for v in values.values()):
            raise ValueError("Actual paid amounts may have at most two decimal places")
        p[kind] = {k: f"{v:.2f}" for k, v in values.items()}
    effects = {identity(k): v for k, v in p.get("deduction_effects", {}).items()}
    if any(not isinstance(v, bool) for v in effects.values()):
        raise ValueError("Specify whether each deduction affects net pay")
    p["deduction_effects"] = effects
    gross = sum((money(v) for v in p["allowances"].values()), money("0"))
    deduction = sum(
        (money(v) for k, v in p["deductions"].items() if effects.get(k, True)),
        money("0"),
    )
    for key, calculated in [
        ("printed_gross", gross),
        ("printed_deductions", deduction),
        ("printed_net", gross - deduction),
    ]:
        if p.get(key) not in ("", None) and money(p[key]) != calculated:
            raise ValueError(
                key.replace("_", " ")
                + " does not reconcile; review the components and informational deductions"
            )
    if not p["allowances"]:
        raise ValueError(
            "Enter at least one allowance, including an explicit zero when applicable"
        )
    if p.get("entitlement_period"):
        a, b = [
            date.fromisoformat(p["entitlement_period"][k]) for k in ("start", "end")
        ]
        if a > b:
            raise ValueError("Invalid entitlement period")
        p["entitlement_period"] = {"start": str(a), "end": str(b)}
    p["employee_code"] = code
    if p.get("allocations_by_head"):
        p["allocations_by_head"] = validate_period_allocations(
            p, p["allocations_by_head"]
        )
    for r in db.execute(
        "SELECT payload FROM suite_payments WHERE employee_code=?", (code,)
    ):
        q = json.loads(r["payload"])
        if (
            identity(q["bill_no"]) == identity(p["bill_no"])
            and q["pay_month"] == p["pay_month"]
        ):
            raise ValueError("Payment bill already saved for this employee and month")
    id = db.execute(
        "INSERT INTO suite_payments(import_id,employee_code,payload) VALUES(?,?,?)",
        (import_id, code, json.dumps(p, sort_keys=True)),
    ).lastrowid
    return id


def validate_period_allocations(payment, allocations):
    period = payment.get("entitlement_period")
    if not period or not isinstance(allocations, dict):
        raise ValueError(
            "Assign the entitlement period before reviewing monthly amounts"
        )
    result = {}
    for head, parts in allocations.items():
        head = identity(head)
        if (
            head not in payment.get("allowances", {})
            or not isinstance(parts, list)
            or not parts
            or len(parts) > 1200
        ):
            raise ValueError(
                "Choose an allowance on this bill and up to 1200 allocation rows"
            )
        normalized = []
        total = money("0")
        cursor = date.fromisoformat(period["start"])
        for part in sorted(parts, key=lambda r: r["start"]):
            a, b = date.fromisoformat(part["start"]), date.fromisoformat(part["end"])
            amount = money(part["amount"])
            if (
                a != cursor
                or a > b
                or b > date.fromisoformat(period["end"])
                or (a.year, a.month) != (b.year, b.month)
            ):
                raise ValueError(
                    "Monthly allocation rows must cover the entitlement period without gaps or overlaps"
                )
            if amount != rounded(amount):
                raise ValueError("Allocation amounts may have at most two decimals")
            normalized.append(dict(start=str(a), end=str(b), amount=f"{amount:.2f}"))
            total += amount
            cursor = b + timedelta(days=1)
        if cursor != date.fromisoformat(period["end"]) + timedelta(
            days=1
        ) or total != money(payment["allowances"][head]):
            raise ValueError(
                "Allocation dates and amounts must reconcile with the original bill"
            )
        result[head] = normalized
    return result


def payment_records(db, code):
    rows = []
    for r in db.execute(
        "SELECT * FROM suite_payments WHERE employee_code=?", (identity(code),)
    ):
        p = dict(
            json.loads(r["payload"]),
            id=r["id"],
            import_id=r["import_id"],
            employee_code=r["employee_code"],
        )
        a = db.execute(
            "SELECT payload FROM suite_payment_allocations WHERE payment_id=?",
            (r["id"],),
        ).fetchone()
        if a:
            allocation = json.loads(a["payload"])
            p["entitlement_period"] = allocation["period"]
            p["allocations_by_head"] = allocation.get("allocations_by_head", {})
        linked = db.execute(
            "SELECT c.payload,c.calculation FROM suite_claim_settlements s JOIN suite_claims c ON c.id=s.claim_id WHERE s.payment_id=?",
            (r["id"],),
        ).fetchone()
        if linked:
            claim = json.loads(linked["payload"])
            calculation = json.loads(linked["calculation"])
            p.setdefault("allocations_by_head", {})[claim["allowance"]] = [
                dict(start=row["start"], end=row["end"], amount=row["difference"])
                for row in calculation["rows"]
            ]
        rows.append(p)
    return rows


def history_segments(db, p):
    if p.get("entitlement_type", "salary") != "salary":
        raise ValueError(
            "Use reviewed statement or manual periods for leave-encashment arrears; quantity and proration need separate confirmation"
        )
    code = identity(p["employee_code"])
    allowance = identity(p["allowance"])
    rules = db.execute(
        "SELECT payload FROM suite_rules WHERE name=?", (allowance,)
    ).fetchone()
    rule = (
        json.loads(rules["payload"])
        if rules
        else {
            "name": allowance,
            "basis": "basic",
            "proration": "calendar",
            "rounding": "paise",
        }
    )
    rule = dict(rule)
    rule["category"] = p.get("category", rule.get("category", ""))
    rates = [
        json.loads(r["payload"]) for r in db.execute("SELECT payload FROM suite_rates")
    ]
    rule["da_rates"] = rates
    rule["entitlement_type"] = p.get("entitlement_type", "salary")
    rule["uniform_drawn_reviewed"] = p.get("uniform_drawn_reviewed") is True
    pay = [
        json.loads(r["payload"])
        for r in db.execute(
            "SELECT payload FROM suite_pay_history WHERE employee_code=? ORDER BY effective_from",
            (code,),
        )
    ]
    payments = payment_records(db, code)
    return prepare_segments(p["start"], p["end"], allowance, rates, pay, payments, rule)


def calculate_payload(db, p):
    profile = db.execute(
        "SELECT payload FROM suite_employees WHERE employee_code=?",
        (identity(p.get("employee_code")),),
    ).fetchone()
    if profile:
        employee = json.loads(profile["payload"])
        p["employee_name"] = employee.get("name", "")
        for key in ("designation", "office_name", "ddo_code", "group"):
            p[key] = employee.get(key, "")
    if p.get("source") == "history":
        p["segments"] = history_segments(db, p)
    else:
        validate_manual_settlements(db, p)
    deductions = list(p.get("deductions") or [])
    if p.get("allocation_policy") == "source_order":
        if p.get("source") != "history" or identity(p.get("allowance")) != "DA":
            raise ValueError(
                "Order allocation requires a DA revision from reviewed history"
            )
        scheme = p.get("scheme")
        if scheme not in ("GPF", "GPF-2004", "GPF-SAB"):
            raise ValueError("Select the applicable scheme for the claim period")
        if p["start"] < "2021-07-01" and scheme != "GPF":
            raise ValueError(
                "Verify historical pension-scheme treatment and enter the allocation manually before July 2021"
            )
        if any("GPF" in identity(d.get("name")) for d in deductions):
            raise ValueError("Do not combine automatic and manual GPF allocation")
        base = calculate_claim(p["start"], p["end"], p["segments"])
        deferred = money("0")
        for segment, row in zip(p["segments"], base["rows"]):
            if segment.get(
                "rate_verification"
            ) != "official_source_checked" or not segment.get("cash_from"):
                raise ValueError(
                    "Rate has no verified payment timing; enter the allocation manually"
                )
            if row["start"] < segment["cash_from"]:
                deferred += max(money(row["difference"]), money("0"))
        deductions.insert(0, dict(name=scheme, mode="fixed", value=str(deferred)))
    return calculate_claim(p["start"], p["end"], p["segments"], deductions)


def validate_manual_settlements(db, p):
    """IDs alone cannot authorize an overlapping revision or invented deduction."""
    from .payment_types import payment_class

    payments = {r["id"]: r for r in payment_records(db, p.get("employee_code", ""))}
    consumed = set()
    referenced = set()
    for segment in p.get("segments", []):
        ids = segment.get("settlement_ids", [])
        if not ids:
            continue
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            raise ValueError("List each linked settlement once per segment")
        expected = money("0")
        for pid in ids:
            referenced.add(pid)
            payment = payments.get(pid)
            if (
                not payment
                or payment_class(payment) != "allowance_arrear"
                or entitlement_type(payment) != p.get("entitlement_type", "salary")
            ):
                raise ValueError(
                    "Settlement employee, category or entitlement does not match"
                )
            if not db.execute(
                "SELECT 1 FROM suite_claim_settlements s JOIN suite_claims c ON c.id=s.claim_id WHERE s.payment_id=? AND c.status='paid'",
                (pid,),
            ).fetchone():
                raise ValueError(
                    "Manual revision requires an actual settlement linked to a paid claim"
                )
            parts = payment.get("allocations_by_head", {}).get(
                identity(p.get("allowance")), []
            )
            matched = False
            for index, part in enumerate(parts):
                if part["start"] <= segment["end"] and segment["start"] <= part["end"]:
                    if not (
                        segment["start"] <= part["start"]
                        and part["end"] <= segment["end"]
                    ):
                        raise ValueError(
                            "Align manual revision periods with the saved settlement slices"
                        )
                    if (pid, index) in consumed:
                        raise ValueError("Settlement slice was deducted more than once")
                    consumed.add((pid, index))
                    expected += money(part["amount"])
                    matched = True
            if not matched:
                raise ValueError(
                    "Settlement allowance or covered dates do not match this segment"
                )
        if rounded(money(segment.get("prior_settlement", "0"))) != rounded(expected):
            raise ValueError(
                "Prior settlement amount differs from linked saved allocations"
            )
    for pid in referenced:
        for index, part in enumerate(
            payments[pid]
            .get("allocations_by_head", {})
            .get(identity(p.get("allowance")), [])
        ):
            if (
                part["start"] <= p["end"]
                and p["start"] <= part["end"]
                and (pid, index) not in consumed
            ):
                raise ValueError(
                    "Deduct every saved settlement slice covered by this revision"
                )


def register_payroll(suite):
    @suite.route("/api/rules", methods=["GET", "POST"])
    def rules():
        with database() as db:
            if request.method == "GET":
                return jsonify(
                    [
                        json.loads(r["payload"])
                        for r in db.execute(
                            "SELECT payload FROM suite_rules ORDER BY name"
                        )
                    ]
                )
            p = request.get_json() or {}
            p["name"] = identity(p.get("name"))
            if not p["name"] or not p.get("reference"):
                raise ValueError("Allowance name and rule reference required")
            if p.get("basis") not in (
                "basic",
                "basic_da",
                "fixed",
                "daily",
                "components",
            ):
                raise ValueError("Unknown calculation basis")
            if p.get("proration", "calendar") not in ("calendar", "thirty"):
                raise ValueError("Unknown proration policy")
            if p.get("rounding", "paise") not in ("paise", "rupee"):
                raise ValueError("Unknown rounding policy")
            if p.get("rounding_scope", "segment") not in ("month", "segment"):
                raise ValueError("Unknown rounding scope")
            if p["basis"] == "components" and not p.get("components"):
                raise ValueError("Select pay component names")
            db.execute(
                "INSERT INTO suite_rules VALUES(?,?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
                (p["name"], json.dumps(p)),
            )
            return jsonify(p), 201

    @suite.route("/api/pay_history", methods=["GET", "POST"])
    def pay_history():
        with database() as db:
            code = identity(request.args.get("employee_code"))
            if request.method == "GET":
                return jsonify(
                    [
                        json.loads(r["payload"])
                        for r in db.execute(
                            "SELECT payload FROM suite_pay_history WHERE employee_code=? ORDER BY effective_from",
                            (code,),
                        )
                    ]
                )
            p = request.get_json() or {}
            p["employee_code"] = identity(p.get("employee_code"))
            if (
                not p["employee_code"]
                or not p.get("reference")
                or p.get("reviewed") is not True
            ):
                raise ValueError(
                    "Employee, reference and reviewed confirmation required"
                )
            p["effective_from"] = date.fromisoformat(p["effective_from"]).isoformat()
            p["basic"] = str(money(p["basic"]))
            if money(p["basic"]) < 0:
                raise ValueError("Basic cannot be negative")
            if db.execute(
                "SELECT 1 FROM suite_pay_history WHERE employee_code=? AND effective_from=?",
                (p["employee_code"], p["effective_from"]),
            ).fetchone():
                return (
                    jsonify(error="Pay event already exists; preserve dated history"),
                    409,
                )
            db.execute(
                "INSERT INTO suite_pay_history(employee_code,effective_from,payload) VALUES(?,?,?)",
                (p["employee_code"], p["effective_from"], json.dumps(p)),
            )
            return jsonify(p), 201

    @suite.post("/api/payments/manual")
    def manual_payment():
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                id = reviewed_payment(db, request.get_json() or {})
            except ValueError as e:
                if "already saved" in str(e):
                    return jsonify(error=str(e)), 409
                raise
        return jsonify(id=id), 201

    @suite.post("/api/payments/review_batch")
    def review_batch():
        p = request.get_json() or {}
        payments = p.get("payments", [])
        if p.get("reviewed") is not True or not payments or len(payments) > 500:
            raise ValueError("Confirm 1–500 reviewed payment records")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            ids = []
            for payment in payments:
                payment = dict(
                    payment,
                    employee_code=payment.get("employee_code")
                    or p.get("employee_code"),
                    reviewed=True,
                    reference=p.get("reference"),
                )
                ids.append(reviewed_payment(db, payment))
        return jsonify(saved=len(ids), ids=ids), 201

    @suite.post("/api/history/preview")
    def preview():
        p = request.get_json() or {}
        with database() as db:
            q = dict(p, source="history")
            calculation = calculate_payload(db, q)
        return jsonify(segments=q["segments"], calculation=calculation)

    @suite.post("/api/batch")
    def batch():
        p = request.get_json() or {}
        codes = p.get("employees", [])
        if not isinstance(codes, list) or not codes or len(codes) > 500:
            raise ValueError("Select 1–500 employee codes")
        if len({identity(c) for c in codes}) != len(codes):
            raise ValueError("Duplicate employees in batch")
        results = []
        errors = []
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            for code in codes:
                try:
                    q = {k: v for k, v in p.items() if k != "employees"}
                    q.update(
                        employee_code=identity(code),
                        allowance=identity(p.get("allowance")),
                        source="history",
                    )
                    q["segments"] = history_segments(db, q)
                    r = calculate_payload(db, q)
                    results.append((q, r))
                except (ValueError, KeyError) as e:
                    errors.append(dict(employee_code=identity(code), error=str(e)))
            if errors:
                return jsonify(errors=errors, saved=0), 422
            saved = []
            for q, r in results:
                id = db.execute(
                    "INSERT INTO suite_claims(payload,calculation) VALUES(?,?)",
                    (json.dumps(q), json.dumps(r)),
                ).lastrowid
                saved.append(
                    dict(id=id, employee_code=q["employee_code"], calculation=r)
                )
        return jsonify(claims=saved, saved=len(saved)), 201
