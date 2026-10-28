"""Local, user-authored salary subscription references, separate from deductions."""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import json
import math

from flask import jsonify, request

from .storage import database


SCHEMES = ("GPF", "GPF-2004", "GPF-SAB", "SI")


def initialize_slabs(db):
    """Create an empty authority library; never invent or seed subscription rates."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS suite_slabs(
            id INTEGER PRIMARY KEY, revision INTEGER NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS suite_slab_audit(
            id INTEGER PRIMARY KEY, slab_id INTEGER NOT NULL,
            revision INTEGER NOT NULL, action TEXT NOT NULL,
            previous_payload TEXT, new_payload TEXT NOT NULL,
            reason TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(slab_id, revision));
    """
    )


def _text(value, label, required=False):
    if not isinstance(value, str):
        raise ValueError(label + " must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(label + " is required")
    return value


def _date(value, label):
    value = _text(value, label, True)
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise ValueError(label + " must be a valid YYYY-MM-DD date") from None
    return value


def _decimal(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(label + " must be a finite nonnegative number")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or not math.isfinite(float(number)):
            raise ValueError()
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError(label + " must be a finite nonnegative number") from None
    return number


def _numeric(value, label):
    number = _decimal(value, label)
    # Keep input decimal strings exact while retaining the normal JSON-number schema.
    return str(number) if isinstance(value, str) else value


def _validate(body):
    if not isinstance(body, dict):
        raise ValueError("Expected a salary slab schedule object")
    result = {
        key: _text(body.get(key, ""), key, True)
        for key in ("name", "scheme", "basis", "reference", "rounding")
    }
    if result["scheme"] not in SCHEMES:
        raise ValueError("Choose GPF, GPF-2004, GPF-SAB or SI")
    if result["basis"] not in ("basic", "basic_da", "gross"):
        raise ValueError("Choose basic, basic_da or gross basis")
    if result["rounding"] not in ("rupee", "paise"):
        raise ValueError("Choose rupee or paise rounding")
    result["category"] = _text(body.get("category", ""), "category")
    result["effective_from"] = _date(body.get("effective_from"), "effective_from")
    end = body.get("effective_to")
    result["effective_to"] = (
        _date(end, "effective_to") if end not in (None, "") else None
    )
    if result["effective_to"] and result["effective_to"] < result["effective_from"]:
        raise ValueError("effective_to cannot precede effective_from")
    slabs = body.get("slabs")
    if not isinstance(slabs, list) or not slabs or len(slabs) > 1000:
        raise ValueError("Provide between 1 and 1000 slab rows")
    result["slabs"] = []
    previous_upper = None
    for index, slab in enumerate(slabs):
        if not isinstance(slab, dict):
            raise ValueError("Every slab row must be an object")
        lower = _numeric(slab.get("lower"), "lower")
        upper = None if slab.get("upper") is None else _numeric(slab["upper"], "upper")
        value = _numeric(slab.get("value"), "value")
        kind = slab.get("kind")
        if kind not in ("fixed", "percent"):
            raise ValueError("Slab kind must be fixed or percent")
        if upper is not None and Decimal(str(upper)) <= Decimal(str(lower)):
            raise ValueError("Slab upper must exceed lower")
        if index and (
            previous_upper is None or Decimal(str(lower)) < Decimal(str(previous_upper))
        ):
            raise ValueError("Slabs must be sorted and must not overlap")
        result["slabs"].append(dict(lower=lower, upper=upper, kind=kind, value=value))
        previous_upper = upper
    return result


def _record(db, row):
    if row is None:
        return None
    return dict(
        json.loads(row["payload"]),
        id=row["id"],
        revision=row["revision"],
        archived=bool(row["archived"]),
        audit_count=db.execute(
            "SELECT COUNT(*) FROM suite_slab_audit WHERE slab_id=?", (row["id"],)
        ).fetchone()[0],
    )


def _load(db, ident):
    return _record(
        db, db.execute("SELECT * FROM suite_slabs WHERE id=?", (ident,)).fetchone()
    )


def _audit(db, ident, revision, action, before, after, reason):
    db.execute(
        """INSERT INTO suite_slab_audit
        (slab_id,revision,action,previous_payload,new_payload,reason) VALUES(?,?,?,?,?,?)""",
        (
            ident,
            revision,
            action,
            json.dumps(before) if before is not None else None,
            json.dumps(after),
            reason,
        ),
    )


def suggest_slab(db, scheme, on, basic=None, da=None, gross=None, category=""):
    """Return a dated full-subscription reference; never mutate pay or deductions.

    Bounds are lower-inclusive/upper-exclusive, effective end dates inclusive.
    Category matching is exact. Equal latest effective dates are ambiguous.
    ``da`` is the salary DA amount, not a percentage rate.
    """
    if scheme not in SCHEMES:
        raise ValueError("Choose GPF, GPF-2004, GPF-SAB or SI")
    on = _date(on, "on")
    category = _text(category, "category")
    salary = {
        key: _decimal(value, key) if value not in (None, "") else None
        for key, value in dict(basic=basic, da=da, gross=gross).items()
    }
    result = dict(
        status="missing",
        amount=None,
        full_subscription_reference_only=True,
        scheme=scheme,
        on=on,
        category=category,
        schedule=None,
        slab=None,
        reference="",
        message="No applicable salary slab schedule",
    )
    candidates = []
    for row in db.execute("SELECT * FROM suite_slabs WHERE archived=0"):
        item = json.loads(row["payload"])
        if (
            item["scheme"] == scheme
            and item["category"] == category
            and item["effective_from"] <= on
            and (not item["effective_to"] or item["effective_to"] >= on)
        ):
            candidates.append((item, row))
    if not candidates:
        return result
    latest = max(item["effective_from"] for item, _ in candidates)
    candidates = [
        (item, row) for item, row in candidates if item["effective_from"] == latest
    ]
    if len(candidates) != 1:
        return dict(
            result,
            status="ambiguous",
            message="Multiple schedules share the latest effective date",
        )
    item, row = candidates[0]
    result.update(
        schedule=_record(db, row), reference=item["reference"], basis=item["basis"]
    )
    if item["basis"] == "basic_da":
        basis = (
            None
            if salary["basic"] is None or salary["da"] is None
            else salary["basic"] + salary["da"]
        )
    else:
        basis = salary[item["basis"]]
    if basis is None:
        return dict(
            result, message="Supply all salary amounts required for " + item["basis"]
        )
    result["basis_amount"] = str(basis)
    for slab in item["slabs"]:
        if basis >= Decimal(str(slab["lower"])) and (
            slab["upper"] is None or basis < Decimal(str(slab["upper"]))
        ):
            value = Decimal(str(slab["value"]))
            with localcontext() as context:
                context.prec = max(
                    50,
                    len(basis.as_tuple().digits)
                    + len(value.as_tuple().digits)
                    + max(0, basis.adjusted())
                    + max(0, value.adjusted())
                    + 10,
                )
                amount = value if slab["kind"] == "fixed" else basis * value / 100
                quantum = (
                    Decimal("1") if item["rounding"] == "rupee" else Decimal("0.01")
                )
                amount = amount.quantize(quantum, rounding=ROUND_HALF_UP)
            return dict(
                result,
                status="ok",
                amount=format(amount, ".2f"),
                slab=slab,
                message="Full subscription reference only; review separately from additional arrear deductions",
            )
    return dict(
        result, message="Salary basis falls outside the schedule's slab coverage"
    )


def _body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("Expected a salary slab object")
    return body


def _revision(body):
    revision = body.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("A current integer revision is required")
    return revision


def register_slabs(suite):
    @suite.get("/api/slabs")
    def list_slabs():
        include_archived = request.args.get("include_archived", "").lower() in (
            "true",
            "1",
            "yes",
        )
        scheme = request.args.get("scheme", "")
        query = request.args.get("q", "").strip().casefold()
        with database() as db:
            rows = []
            for row in db.execute("SELECT * FROM suite_slabs ORDER BY id DESC"):
                item = _record(db, row)
                if item["archived"] and not include_archived:
                    continue
                if scheme and item["scheme"] != scheme:
                    continue
                if (
                    query
                    and query
                    not in " ".join(
                        str(item[k])
                        for k in ("name", "scheme", "category", "reference")
                    ).casefold()
                ):
                    continue
                rows.append(item)
            return jsonify(slabs=rows)

    @suite.get("/api/slabs/suggest")
    def slab_suggestion():
        with database() as db:
            return jsonify(
                suggest_slab(
                    db,
                    request.args.get("scheme"),
                    request.args.get("on", request.args.get("date")),
                    basic=request.args.get("basic"),
                    da=request.args.get("da"),
                    gross=request.args.get("gross"),
                    category=request.args.get("category", ""),
                )
            )

    @suite.post("/api/slabs")
    def create_slab():
        body = _body()
        payload = _validate(body)
        reason = _text(body.get("reason", "Created authority schedule"), "reason", True)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            ident = db.execute(
                "INSERT INTO suite_slabs(revision,payload) VALUES(1,?)",
                (json.dumps(payload),),
            ).lastrowid
            _audit(db, ident, 1, "create", None, dict(payload, archived=False), reason)
            return jsonify(_load(db, ident)), 201

    @suite.get("/api/slabs/<int:ident>")
    def get_slab(ident):
        with database() as db:
            item = _load(db, ident)
            return (
                (jsonify(item), 200)
                if item
                else (jsonify(error="Slab schedule not found"), 404)
            )

    @suite.post("/api/slabs/<int:ident>")
    def edit_slab(ident):
        body = _body()
        revision = _revision(body)
        payload = _validate(body)
        reason = _text(body.get("reason", "Edited authority schedule"), "reason", True)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = _load(db, ident)
            if not previous:
                return jsonify(error="Slab schedule not found"), 404
            if previous["revision"] != revision:
                return (
                    jsonify(error="Slab schedule changed; reload before editing"),
                    409,
                )
            db.execute(
                "UPDATE suite_slabs SET revision=?,payload=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (revision + 1, json.dumps(payload), ident),
            )
            _audit(
                db,
                ident,
                revision + 1,
                "edit",
                previous,
                dict(payload, archived=previous["archived"]),
                reason,
            )
            return jsonify(_load(db, ident))

    @suite.post("/api/slabs/<int:ident>/archive")
    def archive_slab(ident):
        body = _body()
        revision = _revision(body)
        reason = _text(body.get("reason", ""), "reason", True)
        archived = body.get("archived")
        if not isinstance(archived, bool):
            raise ValueError("archived must be true or false")
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = _load(db, ident)
            if not previous:
                return jsonify(error="Slab schedule not found"), 404
            if previous["revision"] != revision:
                return (
                    jsonify(error="Slab schedule changed; reload before editing"),
                    409,
                )
            db.execute(
                "UPDATE suite_slabs SET revision=?,archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (revision + 1, int(archived), ident),
            )
            _audit(
                db,
                ident,
                revision + 1,
                "archive" if archived else "restore",
                previous,
                dict(previous, revision=revision + 1, archived=archived),
                reason,
            )
            return jsonify(_load(db, ident))
