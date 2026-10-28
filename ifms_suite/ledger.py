"""Monthly views over reviewed payments; the ledger has no separate financial store."""

from copy import deepcopy

from .payroll import identity, payment_records, reviewed_payment
from .payment_types import payment_class


def ledger_payments(db, code, strict=True):
    """Recheck original hashes and source reviews before reusing saved evidence."""
    from .bill_routes import _load, _hash, case_facts

    records = payment_records(db, code)
    sources = {}
    for record in records:
        record["ledger_status"] = "reviewed"
        provenance = record.get("ledger_source")
        if not provenance:
            continue  # Existing manual histories already require explicit review.
        try:
            ident = provenance["source_import"]
            if ident not in sources:
                row, payload = _load(db, ident)
                sources[ident] = (row, case_facts(payload, row["sha256"]))
            row, facts = sources[ident]
            index = provenance["bill_index"]
            if (
                row["sha256"] != provenance["source_sha256"]
                or facts["facts_version"] != provenance["facts_version"]
                or _hash(facts["bills"][index]) != provenance["bill_snapshot"]
            ):
                raise ValueError("Source review or extraction changed")
        except (ValueError, OSError, KeyError, IndexError, TypeError) as error:
            message = (
                "Saved ledger source is stale or changed; repeat original review: "
                + str(error)
            )
            record["ledger_status"] = "stale"
            record["ledger_issue"] = message
            if strict:
                raise ValueError(message) from error
    return records


def employee_ledger(db, code):
    code = identity(code)
    if not code:
        raise ValueError("Employee code required")
    records = ledger_payments(db, code, strict=False)
    months = {}
    for record in records:
        month = months.setdefault(
            record["pay_month"],
            dict(
                pay_month=record["pay_month"],
                regular_salary=[],
                prior_credits=[],
                issues=[],
                status="reviewed",
            ),
        )
        kind = (
            "regular_salary"
            if payment_class(record) == "regular_salary"
            else "prior_credits"
        )
        month[kind].append(record)
        if record["ledger_status"] == "stale":
            month["status"] = "stale"
            month["issues"].append(record["ledger_issue"])
    for month in months.values():
        if len(month["regular_salary"]) > 1:
            if month["status"] != "stale":
                month["status"] = "conflict"
            month["issues"].append(
                "Multiple regular salary bills for this month; resolve original evidence before preparation"
            )
    return dict(
        employee_code=code,
        months=[months[m] for m in sorted(months)],
        payment_count=len(records),
    )


def save_source_payments(db, import_id, indexes, reference=None):
    """Atomically admit selected verified source bills through payment validation."""
    from .bill_routes import _load, _save, _hash, case_facts
    from .source_bill_review import bill_review_requests, apply_bill_reviews

    if (
        not isinstance(indexes, list)
        or not indexes
        or len(indexes) > 500
        or any(type(i) is not int or i < 0 for i in indexes)
        or len(indexes) != len(set(indexes))
    ):
        raise ValueError("Select 1–500 distinct source bill indexes")
    row, payload = _load(db, import_id)
    facts = case_facts(payload, row["sha256"])
    for index in indexes:
        if index >= len(facts.get("bills", [])):
            raise ValueError("Unknown source bill index")
        bill = facts["bills"][index]
        if not bill.get("human_reviewed"):
            if not bill.get("complete") or not str(reference or "").strip():
                raise ValueError(
                    "Complete original source bill review before saving to ledger"
                )
            req = next(
                (r for r in bill_review_requests(facts) if r["bill_index"] == index),
                None,
            )
            if not req:
                raise ValueError("Source review unavailable")
            review = dict(
                request_id=req["request_id"],
                reviewed=True,
                reference=reference.strip(),
                record=deepcopy(bill),
            )
            facts = apply_bill_reviews(facts, [review])
            payload.setdefault("source_bill_reviews", []).append(review)
    # A savepoint protects callers that catch a validation error within their transaction.
    db.execute("SAVEPOINT ledger_save")
    try:
        ids = []
        for index in indexes:
            bill = deepcopy(facts["bills"][index])
            if not bill.get("complete") or not bill.get("source_bill_review"):
                raise ValueError(
                    "Complete original source bill review before saving to ledger"
                )
            existing = payment_records(db, bill["employee_code"])
            for saved in existing:
                if saved["pay_month"] == bill["pay_month"]:
                    if identity(saved["bill_no"]) == identity(bill["bill_no"]):
                        raise ValueError(
                            "Payment bill already saved for this employee and month"
                        )
                    if payment_class(saved) == payment_class(bill) == "regular_salary":
                        raise ValueError(
                            "A regular salary bill already exists for this month; resolve conflicting source bills"
                        )
            bill["ledger_source"] = dict(
                source_import=import_id,
                source_sha256=row["sha256"],
                facts_version=facts["facts_version"],
                bill_index=index,
                source_pages=bill.get("source_pages", []),
                bill_snapshot=_hash(bill),
            )
            bill.update(
                reviewed=True, reference=bill["source_bill_review"]["reference"]
            )
            ids.append(reviewed_payment(db, bill, import_id))
        _save(db, row, payload)
        db.execute("RELEASE ledger_save")
    except Exception:
        db.execute("ROLLBACK TO ledger_save")
        db.execute("RELEASE ledger_save")
        raise
    return ids
