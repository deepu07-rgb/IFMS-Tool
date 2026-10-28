"""Structured salary admission and revalidated worksheet links to the existing ledger."""

from calendar import monthrange
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from decimal import Decimal

from .calculation import money, rounded
from .ledger import ledger_payments
from .payroll import reviewed_payment, payment_records, identity
from .payment_types import payment_class
from .supplied_form import HEADS
from .worksheet import _date


def month_rows(start, end):
    start, end = _date(start), _date(end)
    if start > end:
        raise ValueError("End date must follow start date")
    rows, cursor = [], start
    while cursor <= end:
        last = min(
            end,
            date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]),
        )
        rows.append(
            dict(
                month=str(cursor)[:7],
                start=str(cursor),
                end=str(last),
                presentation="period",
            )
        )
        if len(rows) > 120:
            raise ValueError("Use at most 120 months")
        if last == end:
            break
        cursor = last + timedelta(days=1)
    return rows


def snapshot(record):
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_full_month_salary(record):
    """This worksheet accepts monthly actuals, not amounts for a paid subperiod."""
    month = record.get("pay_month", "")
    first = _date(month + "-01")
    last = date(first.year, first.month, monthrange(first.year, first.month)[1])
    for key in ("covered_dates", "entitlement_period"):
        coverage = record.get(key)
        if coverage is not None and coverage != {"start": str(first), "end": str(last)}:
            raise ValueError(
                "This salary covers part of a month; enter explicitly reviewed full-month amounts manually instead of reusing partial actuals"
            )
    monthly_basic = record.get("monthly_basic")
    if monthly_basic is not None and money(monthly_basic) != money(
        record.get("allowances", {}).get("BASIC")
    ):
        raise ValueError(
            "Actual basic differs from the recorded monthly basic; confirm full-month amounts manually before using this salary"
        )


def load_ledger_rows(db, code, start, end):
    code = identity(code)
    if not code:
        raise ValueError("Employee code required")
    salaries = {}
    for record in ledger_payments(db, code):
        if payment_class(record) == "regular_salary":
            salaries.setdefault(record["pay_month"], []).append(record)
    rows = month_rows(start, end)
    for row in rows:
        records = salaries.get(row["month"], [])
        if len(records) > 1:
            raise ValueError("Conflicting regular salaries for " + row["month"])
        if not records:
            continue
        record = records[0]
        require_full_month_salary(record)
        for head in HEADS:
            if head in record["allowances"]:
                row["drawn_" + head] = record["allowances"][head]
        row.update(
            salary_reference=record["reference"],
            bill_no=record["bill_no"],
            ledger_payment_id=record["id"],
            ledger_snapshot=snapshot(record),
        )
        for key in ("bill_date", "tv_no", "tv_date"):
            if record.get(key):
                row[key] = record[key]
        # Previous arrear records are deliberately not inferred absent or allocated.
    return rows


def linked_errors(db, payload):
    errors, by_code = [], {}
    for index, row in enumerate(
        payload.get("rows", []) if isinstance(payload.get("rows"), list) else []
    ):
        if not isinstance(row, dict) or not (
            row.get("ledger_payment_id") or row.get("ledger_snapshot")
        ):
            continue
        try:
            code = identity(payload.get("employee_code"))
            if code not in by_code:
                by_code[code] = ledger_payments(db, code, strict=False)
            record = next(
                (p for p in by_code[code] if p["id"] == row.get("ledger_payment_id")),
                None,
            )
            if (
                not record
                or record.get("ledger_status") != "reviewed"
                or snapshot(record) != row.get("ledger_snapshot")
            ):
                raise ValueError(
                    "Saved salary source changed or is missing; reload the ledger"
                )
            require_full_month_salary(record)
            if payment_class(record) != "regular_salary" or record[
                "pay_month"
            ] != row.get("month"):
                raise ValueError("Saved salary does not match the stated month")
            if (
                sum(
                    p["pay_month"] == row.get("month")
                    and payment_class(p) == "regular_salary"
                    for p in by_code[code]
                )
                != 1
            ):
                raise ValueError(
                    "Multiple regular salary records conflict for this month"
                )
            for head in HEADS:
                if head not in record["allowances"] or money(
                    row.get("drawn_" + head)
                ) != money(record["allowances"][head]):
                    raise ValueError(
                        "Drawn amounts differ from the linked ledger; reload or explicitly use manually reviewed values"
                    )
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(dict(row=index, field="ledger_snapshot", message=str(exc)))
    return errors


def validate_salary(record):
    if not isinstance(record, dict):
        raise ValueError("Expected a salary record")
    result = deepcopy(record)
    for key in ("employee_code", "employee_name", "bill_no", "reference", "pay_month"):
        if (
            not isinstance(result.get(key), str)
            or not result[key].strip()
            or len(result[key]) > 500
        ):
            raise ValueError("Enter " + key + " for each salary record")
    result["employee_code"] = identity(result["employee_code"])
    month = result["pay_month"]
    if len(month) != 7 or str(_date(month + "-01"))[:7] != month:
        raise ValueError("Salary month must be YYYY-MM")
    if not isinstance(result.get("allowances"), dict) or not isinstance(
        result.get("deductions"), dict
    ):
        raise ValueError(
            "Salary allowances and deductions must be named component objects"
        )
    require_full_month_salary(result)
    if set(result.get("allowances", {})) != set((*HEADS, "OTHER_ALLOWANCES")) or set(
        result.get("deductions", {})
    ) != {"TOTAL_DEDUCTIONS"}:
        raise ValueError(
            "Enter the five printed heads, OTHER_ALLOWANCES and TOTAL_DEDUCTIONS; use explicit zero for confirmed absent values"
        )
    for key in (*HEADS, "OTHER_ALLOWANCES"):
        value = money(result["allowances"][key])
        if (
            value != rounded(value)
            or abs(value) > 100000000
            or (key != "OTHER_ALLOWANCES" and value < 0)
        ):
            raise ValueError("Invalid salary allowance " + key)
    deduction = money(result["deductions"]["TOTAL_DEDUCTIONS"])
    if deduction < 0 or deduction != rounded(deduction) or deduction > 100000000:
        raise ValueError("Invalid salary deductions")
    gross = sum((money(v) for v in result["allowances"].values()), Decimal(0))
    for key, expected in (
        ("printed_gross", gross),
        ("printed_deductions", deduction),
        ("printed_net", gross - deduction),
    ):
        if money(result.get(key)) != expected:
            raise ValueError(key.replace("_", " ") + " does not reconcile")
    # Aggregate entries are explicit actual totals, not invented deduction heads.
    result.update(
        bill_type="Regular Salary (structured Excel)",
        payment_class="regular_salary",
        entitlement_type="salary",
        deduction_effects={"TOTAL_DEDUCTIONS": True},
        reviewed=True,
    )
    result.pop("ledger_source", None)
    return result


def save_salaries(db, records):
    if not isinstance(records, list) or not 1 <= len(records) <= 1200:
        raise ValueError("Select 1–1200 structured salary records")
    normalized = [validate_salary(r) for r in records]
    db.execute("SAVEPOINT structured_salaries")
    try:
        ids = []
        for record in normalized:
            if any(
                p["pay_month"] == record["pay_month"]
                and payment_class(p) == "regular_salary"
                for p in payment_records(db, record["employee_code"])
            ):
                raise ValueError(
                    "Regular salary already saved for this employee/month; resolve the duplicate before import"
                )
            employee = db.execute(
                "SELECT name FROM suite_employees WHERE employee_code=?",
                (record["employee_code"],),
            ).fetchone()
            if (
                employee
                and employee["name"].strip().casefold()
                != record["employee_name"].strip().casefold()
            ):
                raise ValueError(
                    "Employee name conflicts with the saved employee master"
                )
            if not employee:
                db.execute(
                    "INSERT INTO suite_employees VALUES(?,?,?)",
                    (
                        record["employee_code"],
                        record["employee_name"],
                        json.dumps(
                            dict(
                                employee_code=record["employee_code"],
                                name=record["employee_name"],
                            )
                        ),
                    ),
                )
            ids.append(reviewed_payment(db, record))
        db.execute("RELEASE structured_salaries")
        return ids
    except Exception:
        db.execute("ROLLBACK TO structured_salaries")
        db.execute("RELEASE structured_salaries")
        raise
