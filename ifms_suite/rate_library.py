"""Dated office rates and current-library checks for assisted worksheets."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
from flask import request, jsonify

from .calculation import money
from .storage import database


def initialize_rates(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS suite_rate_archives(id INTEGER PRIMARY KEY,payload TEXT NOT NULL,reason TEXT NOT NULL,archived_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )


def rate_key(p):
    return (
        p["allowance"].strip().upper(),
        p.get("category", "").strip().upper(),
        p["effective_from"],
    )


def next_rate_id(db):
    return db.execute(
        "SELECT MAX(n)+1 FROM (SELECT COALESCE(MAX(id),0) n FROM suite_rates UNION ALL SELECT COALESCE(MAX(id),0) FROM suite_rate_archives UNION ALL SELECT COALESCE(MAX(rate_id),0) FROM suite_rate_audit)"
    ).fetchone()[0]


def _normalize(body):
    if not isinstance(body, dict):
        raise ValueError("Expected a rate object")
    p = {
        k: body[k]
        for k in (
            "allowance",
            "effective_from",
            "effective_to",
            "rate",
            "reference",
            "category",
            "basis",
            "order_date",
            "notes",
            "override_reason",
            "rounding",
            "rounding_scope",
            "cash_from",
            "source_url",
            "source_file",
            "source_sha256",
        )
        if k in body
    }
    for key in ("allowance", "effective_from", "reference"):
        if not isinstance(p.get(key), str) or not p[key].strip() or len(p[key]) > 500:
            raise ValueError("Required text: " + key)
    p["allowance"] = p["allowance"].strip().upper()
    category = p.get("category", "")
    if not isinstance(category, str) or len(category) > 80:
        raise ValueError("Invalid rate category")
    p["category"] = category.strip().upper()
    for key in ("effective_from", "effective_to", "order_date", "cash_from"):
        if p.get(key):
            try:
                p[key] = date.fromisoformat(p[key]).isoformat()
            except (ValueError, TypeError):
                raise ValueError("Invalid " + key) from None
    if p.get("effective_to") and p["effective_to"] < p["effective_from"]:
        raise ValueError("Rate expiry precedes effective date")
    amount = money(p.get("rate"))
    if amount < 0 or amount > 100000000:
        raise ValueError("Rate must be nonnegative and no greater than 100,000,000")
    p["rate"] = format(amount, "f")
    p["basis"] = p.get("basis") or "basic"
    if p["basis"] not in ("basic", "basic_da", "fixed", "daily", "components"):
        raise ValueError("Unknown rate basis")
    if p["allowance"] in ("DA", "HRA") and (p["basis"] != "basic" or amount > 1000):
        raise ValueError("DA/HRA must be a percentage of basic, between 0 and 1000")
    for key in (
        "notes",
        "override_reason",
        "rounding",
        "rounding_scope",
        "cash_from",
        "source_url",
        "source_file",
        "source_sha256",
    ):
        if key in p and (not isinstance(p[key], str) or len(p[key]) > 2000):
            raise ValueError("Invalid " + key)
    if p.get("rounding") not in (None, "", "rupee", "paise"):
        raise ValueError("Unknown rate rounding")
    if p.get("rounding_scope") not in (None, "", "month", "segment"):
        raise ValueError("Unknown rate rounding scope")
    p["verification"] = "manual"
    return p


def save_rate(db, body, ident=None):
    p = _normalize(body)
    existing = None
    for row in db.execute("SELECT * FROM suite_rates"):
        q = json.loads(row["payload"])
        if (ident is not None and row["id"] == ident) or (
            ident is None and rate_key(q) == rate_key(p)
        ):
            existing = row
        elif ident is not None and rate_key(q) == rate_key(p):
            raise ValueError(
                "Another rate already uses this allowance/category/effective date"
            )
    if ident is not None and not existing:
        raise ValueError("Active rate not found")
    if existing:
        old = json.loads(existing["payload"])
        p = _normalize(dict(old, **body))
        revision = old.get("revision", 1)
        if ident is not None and (
            type(body.get("revision")) is not int or body["revision"] != revision
        ):
            return None, "conflict"
        if not str(p.get("override_reason", "")).strip():
            return None, "reason"
        p["revision"] = revision + 1
        ident = existing["id"]
        db.execute(
            "UPDATE suite_rates SET payload=? WHERE id=?", (json.dumps(p), ident)
        )
    else:
        ident = next_rate_id(db)
        p["revision"] = 1
        db.execute(
            "INSERT INTO suite_rates(id,payload) VALUES(?,?)", (ident, json.dumps(p))
        )
    if not db.execute(
        "SELECT 1 FROM suite_rules WHERE name=?", (p["allowance"],)
    ).fetchone():
        rule = dict(
            name=p["allowance"],
            basis=p["basis"],
            proration="calendar",
            rounding=p.get("rounding") or "paise",
            rounding_scope="month",
            reference=p["reference"],
        )
        db.execute(
            "INSERT INTO suite_rules VALUES(?,?)", (p["allowance"], json.dumps(rule))
        )
    db.execute(
        "INSERT INTO suite_rate_audit(rate_id,previous_payload,new_payload,reason) VALUES(?,?,?,?)",
        (
            ident,
            existing["payload"] if existing else None,
            json.dumps(p),
            p.get("override_reason") or "Created manual rate",
        ),
    )
    return dict(p, id=ident), None


def register_rate_library(suite):
    @suite.post("/api/rates/<int:ident>")
    def edit_rate(ident):
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            saved, error = save_rate(db, request.get_json() or {}, ident)
        if error:
            return (
                jsonify(
                    error=(
                        "Rate changed in another tab; reload before editing"
                        if error == "conflict"
                        else "Provide an amendment reason"
                    )
                ),
                409,
            )
        return jsonify(saved)

    @suite.get("/api/rates/archived")
    def archived_rates():
        with database() as db:
            return jsonify(
                [
                    dict(
                        json.loads(r["payload"]),
                        id=r["id"],
                        archived=True,
                        archive_reason=r["reason"],
                    )
                    for r in db.execute(
                        "SELECT * FROM suite_rate_archives ORDER BY id DESC"
                    )
                ]
            )

    @suite.post("/api/rates/<int:ident>/archive")
    def archive_rate(ident):
        p = request.get_json() or {}
        archived = p.get("archived")
        if (
            not isinstance(archived, bool)
            or not isinstance(p.get("reason"), str)
            or not p["reason"].strip()
            or len(p["reason"]) > 1000
        ):
            raise ValueError("Choose archive/restore and give a reason")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            table = "suite_rates" if archived else "suite_rate_archives"
            old = db.execute(
                f"SELECT payload FROM {table} WHERE id=?", (ident,)
            ).fetchone()
            if not old:
                raise ValueError("Rate not found in selected state")
            value = json.loads(old["payload"])
            if type(p.get("revision")) is not int or p["revision"] != value.get(
                "revision", 1
            ):
                return jsonify(error="Rate changed; reload before archive/restore"), 409
            if not archived and any(
                rate_key(json.loads(r["payload"])) == rate_key(value)
                for r in db.execute("SELECT payload FROM suite_rates")
            ):
                raise ValueError(
                    "An active rate uses this effective date; resolve it before restoring"
                )
            value["revision"] = value.get("revision", 1) + 1
            encoded = json.dumps(value)
            if archived:
                db.execute(
                    "INSERT INTO suite_rate_archives(id,payload,reason) VALUES(?,?,?)",
                    (ident, encoded, p["reason"]),
                )
            else:
                db.execute(
                    "INSERT INTO suite_rates(id,payload) VALUES(?,?)", (ident, encoded)
                )
            db.execute(f"DELETE FROM {table} WHERE id=?", (ident,))
            db.execute(
                "INSERT INTO suite_rate_audit(rate_id,previous_payload,new_payload,reason) VALUES(?,?,?,?)",
                (
                    ident,
                    old["payload"],
                    json.dumps(dict(value, archived=archived)),
                    p["reason"],
                ),
            )
        return jsonify(dict(value, id=ident, archived=archived))

    @suite.get("/api/rates/<int:ident>/audit")
    def rate_audit(ident):
        with database() as db:
            return jsonify(
                [
                    dict(
                        id=r["id"],
                        reason=r["reason"],
                        created_at=r["created_at"],
                        previous=(
                            json.loads(r["previous_payload"])
                            if r["previous_payload"]
                            else None
                        ),
                        current=json.loads(r["new_payload"]),
                    )
                    for r in db.execute(
                        "SELECT * FROM suite_rate_audit WHERE rate_id=? ORDER BY id",
                        (ident,),
                    )
                ]
            )


def worksheet_rate_checks(db, payload):
    errors, warnings, checks = [], [], []
    rates = [
        dict(json.loads(r["payload"]), id=r["id"])
        for r in db.execute("SELECT * FROM suite_rates")
    ]
    for i, row in enumerate(payload.get("rows", [])):
        if not isinstance(row, dict):
            continue
        try:
            start, end = date.fromisoformat(row["start"]), date.fromisoformat(
                row["end"]
            )
            if start > end:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        kind = payload.get("kind")
        if kind == "manual":
            warnings.append(
                dict(
                    row=i,
                    field="order_reference",
                    message="Explicit monthly due amounts: no DA/HRA percentage is independently validated. Check the blended amounts and order.",
                )
            )
            continue
        heads = (
            ["HRA"]
            if kind == "hra"
            else (
                ["DA"] if kind == "da" else ["DA", "HRA"] if kind == "increment" else []
            )
        )
        for head in heads:
            field = head.lower() + "_rate"
            override = row.get(head.lower() + "_override_reason", "")
            try:
                entered = money(row.get(field))
            except ValueError:
                continue
            category = (
                payload.get("hra_category", "").strip().upper()
                if head == "HRA" and isinstance(payload.get("hra_category", ""), str)
                else ""
            )
            if head == "HRA" and row.get("hra_exempt") is True:
                if (
                    entered != 0
                    or not isinstance(row.get("hra_exemption_reference"), str)
                    or not row["hra_exemption_reference"].strip()
                ):
                    errors.append(
                        dict(
                            row=i,
                            field="hra_exemption_reference",
                            message="HRA exemption needs a zero rate and a specific non-entitlement reference",
                        )
                    )
                else:
                    checks.append(
                        dict(
                            row=i,
                            head=head,
                            status="exempt",
                            reference=row["hra_exemption_reference"],
                        )
                    )
                continue
            options = [
                r
                for r in rates
                if r.get("allowance", "").upper() == head
                and r.get("category", "").upper() == category
            ]
            cuts = {start}
            for r in options:
                for key in ("effective_from", "effective_to"):
                    if r.get(key):
                        d = date.fromisoformat(r[key])
                        if key == "effective_to":
                            if d == date.max:
                                continue
                            d += timedelta(days=1)
                        if start < d <= end:
                            cuts.add(d)
            selected = []
            missing = False
            ambiguous = False
            for day in sorted(cuts):
                eligible = [
                    r
                    for r in options
                    if r["effective_from"] <= str(day)
                    and (not r.get("effective_to") or str(day) <= r["effective_to"])
                ]
                if not eligible:
                    missing = True
                    continue
                latest = max(r["effective_from"] for r in eligible)
                active = [r for r in eligible if r["effective_from"] == latest]
                if len(active) != 1:
                    ambiguous = True
                    continue
                selected.append(active[0])
            if missing or not selected:
                warnings.append(
                    dict(
                        row=i,
                        field=field,
                        message=f"No complete dated {head} library coverage for {start} through {end}"
                        + (
                            " — select the correct HRA category"
                            if head == "HRA" and not category
                            else ""
                        )
                        + ". Entered rate requires source verification.",
                    )
                )
            if ambiguous:
                errors.append(
                    dict(
                        row=i,
                        field=field,
                        message=f"Ambiguous dated {head} library entries; resolve conflicting rules",
                    )
                )
                continue
            values = {money(r["rate"]) for r in selected}
            bad_basis = any(r.get("basis", "basic") != "basic" for r in selected)
            issue = None
            if len(values) > 1:
                issue = f"{head} changes within this row. Split/review the effective periods or enter reviewed blended monthly amounts in manual mode."
            elif values and (entered not in values or bad_basis):
                expected = format(next(iter(values)), "f")
                issue = f"Entered {head} {entered}% does not match the dated library {expected}% for {start} through {end}. Check the effective date and sanction."
            if issue:
                if (
                    isinstance(override, str)
                    and override.strip()
                    and len(override) <= 1000
                ):
                    warnings.append(
                        dict(
                            row=i,
                            field=field,
                            message=issue + " Manual exception recorded: " + override,
                        )
                    )
                    status = "exception"
                else:
                    errors.append(
                        dict(
                            row=i,
                            field=field,
                            message=issue
                            + " Correct the rate or record a specific manual exception reference.",
                        )
                    )
                    status = "mismatch"
            else:
                status = "unverified" if missing or not selected else "matched"
            checks.append(
                dict(
                    row=i,
                    head=head,
                    status=status,
                    entered_rate=str(entered),
                    category=category,
                    sources=[
                        {
                            k: r.get(k)
                            for k in (
                                "id",
                                "rate",
                                "effective_from",
                                "effective_to",
                                "order_date",
                                "reference",
                                "verification",
                                "basis",
                            )
                        }
                        for r in selected
                    ],
                )
            )
    return dict(errors=errors, warnings=warnings, checks=checks)
