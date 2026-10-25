from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


VALID_STATUSES = {
    "ACTIVE",
    "INACTIVE",
    "NEW",
    "NEEDS_REVIEW",
    "DUPLICATE_REVIEW",
    "IDENTITY_CONFLICT",
    "ARCHIVED",
}

MONTH_ORDER = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}


def _row_get(row: Any, key: str, default: Any = "") -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def _clean_id(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _period_parts(month_year: str) -> tuple[str, str]:
    text = str(month_year or "").strip()
    compact = text.replace(" ", "")
    if "/" in compact:
        month, year = compact.split("/", 1)
        return month.strip(), year.strip()
    parts = text.split()
    if len(parts) >= 2:
        return parts[0].strip(), parts[-1].strip()
    return text, ""


def _period_sort_key(month_year: str) -> tuple[int, int]:
    month, year = _period_parts(month_year)
    try:
        y = int(re.sub(r"\D", "", year) or 0)
    except ValueError:
        y = 0
    return y, MONTH_ORDER.get(_norm(month), 0)


def _valid_employee_id(value: Any) -> bool:
    text = _clean_id(value)
    return bool(text and len(text) >= 4 and text not in {"0", "00", "000", "NA", "N/A", "NONE"})


def _valid_pan(value: Any) -> bool:
    return bool(re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", _clean_id(value)))


def _valid_gpf(value: Any) -> bool:
    text = _clean_id(value)
    return bool(text and len(text) >= 3 and text not in {"0", "NA", "N/A", "NONE"})


def _valid_bank(value: Any) -> bool:
    text = re.sub(r"\D", "", str(value or ""))
    return bool(len(text) >= 6 and set(text) != {"0"})


def _master_key(row: dict[str, Any]) -> tuple[str, float, str]:
    employee_id = _clean_id(row.get("employee_id"))
    pan = _clean_id(row.get("pan"))
    gpf = _clean_id(row.get("gpf_pran"))
    bank = re.sub(r"\D", "", str(row.get("bank_account") or ""))
    if _valid_employee_id(employee_id):
        return f"EMPID:{employee_id}", 1.0, "ACTIVE"
    if _valid_pan(pan):
        return f"PAN:{pan}", 0.9, "ACTIVE"
    if _valid_gpf(gpf):
        return f"GPF:{gpf}", 0.75, "ACTIVE"
    if _valid_bank(bank):
        return f"BANK:{bank}", 0.65, "ACTIVE"
    fallback = "|".join([_norm(row.get("employee_name")), _norm(row.get("pay_scale")), _norm(row.get("designation"))])
    return f"LOWCONF:{fallback}", 0.35, "NEEDS_REVIEW"


def init_master_register_schema(db) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS master_employees_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_employee_key TEXT UNIQUE,
        employee_id TEXT,
        employee_name TEXT,
        pan TEXT,
        gpf_pran TEXT,
        bank_account TEXT,
        aadhaar_masked TEXT,
        belt_no TEXT,
        current_designation TEXT,
        current_pay_scale TEXT,
        current_group TEXT,
        current_source_file TEXT,
        first_seen_month TEXT,
        first_seen_year TEXT,
        last_seen_month TEXT,
        last_seen_year TEXT,
        last_seen_source_file TEXT,
        status TEXT DEFAULT 'ACTIVE',
        confidence REAL DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS master_employee_history_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_employee_id INTEGER,
        source_employee_row_id INTEGER UNIQUE,
        source_file TEXT,
        bill_no TEXT,
        group_name TEXT,
        month_year TEXT,
        employee_name TEXT,
        employee_id TEXT,
        pan TEXT,
        gpf_pran TEXT,
        bank_account TEXT,
        designation TEXT,
        pay_scale TEXT,
        basic REAL DEFAULT 0,
        gross REAL DEFAULT 0,
        deduction REAL DEFAULT 0,
        net REAL DEFAULT 0,
        change_flags TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS master_employee_issues_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        master_employee_id INTEGER,
        source_employee_row_id INTEGER,
        issue_type TEXT,
        severity TEXT,
        message TEXT,
        old_value TEXT,
        new_value TEXT,
        source_file TEXT,
        status TEXT DEFAULT 'OPEN',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        resolved_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_master_status ON master_employees_v3(status);
    CREATE INDEX IF NOT EXISTS idx_master_empid ON master_employees_v3(employee_id);
    CREATE INDEX IF NOT EXISTS idx_master_pan ON master_employees_v3(pan);
    CREATE INDEX IF NOT EXISTS idx_master_history_master ON master_employee_history_v3(master_employee_id);
    CREATE INDEX IF NOT EXISTS idx_master_issues_status ON master_employee_issues_v3(status, issue_type);
    """)


def _source_rows(db) -> list[dict[str, Any]]:
    rows = db.execute("""
        SELECT
            e.id AS source_employee_row_id,
            e.source_filename AS source_file,
            b.bill_no AS bill_no,
            e.group_name,
            e.month_year,
            COALESCE(NULLIF(e.raw_name,''), e.normalized_name, '') AS employee_name,
            e.employee_id,
            e.pan_raw AS pan,
            e.gpf_pran_raw AS gpf_pran,
            e.bank_acc AS bank_account,
            e.aadhar_raw AS aadhaar_masked,
            e.belt_no,
            COALESCE(NULLIF(e.final_designation_en,''), NULLIF(e.final_designation,''), NULLIF(e.normalized_designation,''), e.raw_designation_en, e.raw_designation, '') AS designation,
            e.pay_scale_raw AS pay_scale,
            COALESCE((SELECT SUM(c.amount) FROM employee_components_v2 c WHERE c.employee_id = e.id AND c.normalized_head = 'basic_pay'), 0) AS basic,
            e.gross_amount AS gross,
            e.sum_deduction AS deduction,
            e.net_total AS net
        FROM employees_v2 e
        LEFT JOIN bills_v2 b ON b.id = e.bill_id
        WHERE COALESCE(e.is_deleted,0) = 0
        ORDER BY e.id
    """).fetchall()
    data = [dict(row) for row in rows]
    data.sort(key=lambda row: (_period_sort_key(row.get("month_year", "")), row.get("source_employee_row_id") or 0))
    return data


def _insert_issue(db, master_id: int | None, row: dict[str, Any] | None, issue_type: str, severity: str, message: str, old_value: Any = "", new_value: Any = "") -> None:
    source_id = row.get("source_employee_row_id") if row else None
    source_file = row.get("source_file") if row else ""
    exists = db.execute("""
        SELECT id FROM master_employee_issues_v3
        WHERE COALESCE(master_employee_id,0) = COALESCE(?,0)
          AND COALESCE(source_employee_row_id,0) = COALESCE(?,0)
          AND issue_type = ?
          AND message = ?
          AND status = 'OPEN'
        LIMIT 1
    """, (master_id, source_id, issue_type, message)).fetchone()
    if exists:
        return
    db.execute("""
        INSERT INTO master_employee_issues_v3 (
            master_employee_id, source_employee_row_id, issue_type, severity, message,
            old_value, new_value, source_file, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
    """, (master_id, source_id, issue_type, severity, message, str(old_value or ""), str(new_value or ""), source_file or ""))


def _create_master(db, key: str, row: dict[str, Any], confidence: float, status: str) -> int:
    month, year = _period_parts(row.get("month_year", ""))
    cur = db.execute("""
        INSERT INTO master_employees_v3 (
            master_employee_key, employee_id, employee_name, pan, gpf_pran, bank_account,
            aadhaar_masked, belt_no, current_designation, current_pay_scale, current_group,
            current_source_file, first_seen_month, first_seen_year, last_seen_month,
            last_seen_year, last_seen_source_file, status, confidence, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        key, _clean_id(row.get("employee_id")), row.get("employee_name", ""), _clean_id(row.get("pan")),
        _clean_id(row.get("gpf_pran")), row.get("bank_account", ""), row.get("aadhaar_masked", ""),
        row.get("belt_no", ""), row.get("designation", ""), row.get("pay_scale", ""),
        row.get("group_name", ""), row.get("source_file", ""), month, year, month, year,
        row.get("source_file", ""), status, confidence, "Low-confidence fallback key" if status == "NEEDS_REVIEW" else "",
    ))
    return int(cur.lastrowid)


def _change_flags(master: Any | None, row: dict[str, Any], previous_history: Any | None) -> list[str]:
    flags: list[str] = []
    if master:
        checks = [
            ("employee_name", "EMPLOYEE_NAME_CHANGED", master["employee_name"], row.get("employee_name")),
            ("employee_id", "EMPLOYEE_ID_CHANGED", master["employee_id"], _clean_id(row.get("employee_id"))),
            ("pan", "PAN_CHANGED", master["pan"], _clean_id(row.get("pan"))),
            ("bank_account", "BANK_ACCOUNT_CHANGED", master["bank_account"], row.get("bank_account")),
            ("gpf_pran", "GPF_PRAN_CHANGED", master["gpf_pran"], _clean_id(row.get("gpf_pran"))),
            ("belt_no", "BELT_NO_CHANGED", master["belt_no"], row.get("belt_no")),
            ("current_designation", "DESIGNATION_CHANGED", master["current_designation"], row.get("designation")),
            ("current_pay_scale", "PAY_SCALE_CHANGED", master["current_pay_scale"], row.get("pay_scale")),
            ("current_group", "GROUP_CHANGED", master["current_group"], row.get("group_name")),
        ]
        for _field, flag, old, new in checks:
            if _norm(old) != _norm(new):
                flags.append(flag)
    if previous_history:
        basic_diff = _as_float(row.get("basic")) - _as_float(previous_history["basic"])
        gross_diff = _as_float(row.get("gross")) - _as_float(previous_history["gross"])
        net_diff = _as_float(row.get("net")) - _as_float(previous_history["net"])
        if abs(basic_diff) >= 0.01:
            flags.append("BASIC_PAY_CHANGED")
        if abs(gross_diff) >= 1000:
            flags.append("GROSS_CHANGED")
        if abs(net_diff) >= 1000:
            flags.append("NET_CHANGED")
    return flags


def _record_change_issues(db, master_id: int, master: Any | None, row: dict[str, Any], flags: list[str]) -> None:
    if not master:
        return
    if "EMPLOYEE_ID_CHANGED" in flags or "PAN_CHANGED" in flags:
        _insert_issue(db, master_id, row, "IDENTITY_CONFLICT", "CRITICAL", "Employee ID or PAN changed for existing master employee.", master["employee_id"] or master["pan"], row.get("employee_id") or row.get("pan"))
        db.execute("UPDATE master_employees_v3 SET status = 'IDENTITY_CONFLICT', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (master_id,))
    if "DESIGNATION_CHANGED" in flags:
        _insert_issue(db, master_id, row, "DESIGNATION_CHANGED", "MEDIUM", "Designation changed from previous master value.", master["current_designation"], row.get("designation"))
    if "PAY_SCALE_CHANGED" in flags:
        _insert_issue(db, master_id, row, "PAY_SCALE_CHANGED", "MEDIUM", "Pay scale changed from previous master value.", master["current_pay_scale"], row.get("pay_scale"))
    if "GROUP_CHANGED" in flags:
        _insert_issue(db, master_id, row, "GROUP_CHANGED", "INFO", "Employee moved group.", master["current_group"], row.get("group_name"))


def _insert_history(db, master_id: int, row: dict[str, Any], flags: list[str]) -> None:
    db.execute("""
        INSERT OR IGNORE INTO master_employee_history_v3 (
            master_employee_id, source_employee_row_id, source_file, bill_no, group_name,
            month_year, employee_name, employee_id, pan, gpf_pran, bank_account,
            designation, pay_scale, basic, gross, deduction, net, change_flags
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        master_id, row.get("source_employee_row_id"), row.get("source_file", ""), row.get("bill_no", ""),
        row.get("group_name", ""), row.get("month_year", ""), row.get("employee_name", ""),
        _clean_id(row.get("employee_id")), _clean_id(row.get("pan")), _clean_id(row.get("gpf_pran")),
        row.get("bank_account", ""), row.get("designation", ""), row.get("pay_scale", ""),
        _as_float(row.get("basic")), _as_float(row.get("gross")), _as_float(row.get("deduction")),
        _as_float(row.get("net")), json.dumps(flags, ensure_ascii=False),
    ))


def _update_master_current(db, master_id: int, row: dict[str, Any], status: str | None = None) -> None:
    month, year = _period_parts(row.get("month_year", ""))
    sql_status = ", status = COALESCE(?, status)" if status else ""
    params: list[Any] = [
        _clean_id(row.get("employee_id")), row.get("employee_name", ""), _clean_id(row.get("pan")),
        _clean_id(row.get("gpf_pran")), row.get("bank_account", ""), row.get("aadhaar_masked", ""),
        row.get("belt_no", ""), row.get("designation", ""), row.get("pay_scale", ""),
        row.get("group_name", ""), row.get("source_file", ""), month, year, row.get("source_file", ""),
    ]
    if status:
        params.append(status)
    params.append(master_id)
    db.execute(f"""
        UPDATE master_employees_v3
        SET employee_id = ?, employee_name = ?, pan = ?, gpf_pran = ?, bank_account = ?,
            aadhaar_masked = ?, belt_no = ?, current_designation = ?, current_pay_scale = ?,
            current_group = ?, current_source_file = ?, last_seen_month = ?, last_seen_year = ?,
            last_seen_source_file = ?, updated_at = CURRENT_TIMESTAMP{sql_status}
        WHERE id = ?
    """, params)


def _detect_cross_identity_issues(db, master_id: int, row: dict[str, Any]) -> None:
    employee_id = _clean_id(row.get("employee_id"))
    pan = _clean_id(row.get("pan"))
    bank = row.get("bank_account", "")
    if _valid_employee_id(employee_id) and _valid_pan(pan):
        same_id = db.execute("""
            SELECT id, pan FROM master_employees_v3
            WHERE employee_id = ? AND id <> ? AND COALESCE(pan,'') <> '' AND pan <> ?
            LIMIT 1
        """, (employee_id, master_id, pan)).fetchone()
        if same_id:
            _insert_issue(db, master_id, row, "IDENTITY_CONFLICT", "CRITICAL", "Same employee ID appears with different PAN.", same_id["pan"], pan)
            db.execute("UPDATE master_employees_v3 SET status = 'IDENTITY_CONFLICT' WHERE id IN (?, ?)", (master_id, same_id["id"]))
    if _valid_pan(pan):
        same_pan = db.execute("""
            SELECT id, employee_id, employee_name FROM master_employees_v3
            WHERE pan = ? AND id <> ?
              AND (COALESCE(employee_id,'') <> COALESCE(?, '') OR UPPER(COALESCE(employee_name,'')) <> UPPER(COALESCE(?, '')))
            LIMIT 1
        """, (pan, master_id, employee_id, row.get("employee_name", ""))).fetchone()
        if same_pan:
            _insert_issue(db, master_id, row, "IDENTITY_CONFLICT", "CRITICAL", "Same PAN appears with different employee ID or name.", same_pan["employee_id"] or same_pan["employee_name"], employee_id or row.get("employee_name", ""))
            db.execute("UPDATE master_employees_v3 SET status = 'IDENTITY_CONFLICT' WHERE id IN (?, ?)", (master_id, same_pan["id"]))
    if _valid_bank(bank):
        bank_digits = re.sub(r"\D", "", str(bank or ""))
        same_bank = db.execute("""
            SELECT id, employee_id, employee_name FROM master_employees_v3
            WHERE REPLACE(REPLACE(REPLACE(COALESCE(bank_account,''), ' ', ''), '-', ''), '/', '') = ?
              AND id <> ?
              AND (COALESCE(employee_id,'') <> COALESCE(?, '') OR UPPER(COALESCE(employee_name,'')) <> UPPER(COALESCE(?, '')))
            LIMIT 1
        """, (bank_digits, master_id, employee_id, row.get("employee_name", ""))).fetchone()
        if same_bank:
            _insert_issue(db, master_id, row, "DUPLICATE_REVIEW", "HIGH", "Same bank account appears for different employees.", same_bank["employee_id"] or same_bank["employee_name"], employee_id or row.get("employee_name", ""))
            db.execute("UPDATE master_employees_v3 SET status = 'DUPLICATE_REVIEW' WHERE id = ? AND status NOT IN ('IDENTITY_CONFLICT','ARCHIVED')", (master_id,))


def _process_row(db, row: dict[str, Any]) -> int:
    key, confidence, default_status = _master_key(row)
    master = db.execute("SELECT * FROM master_employees_v3 WHERE master_employee_key = ?", (key,)).fetchone()
    if master:
        master_id = int(master["id"])
    else:
        master_id = _create_master(db, key, row, confidence, default_status)
        master = None
        if default_status == "NEEDS_REVIEW":
            _insert_issue(db, master_id, row, "LOW_CONFIDENCE_KEY", "LOW", "Low-confidence fallback key used. Human review required.", "", key)

    previous_history = db.execute("""
        SELECT * FROM master_employee_history_v3
        WHERE master_employee_id = ?
        ORDER BY id DESC LIMIT 1
    """, (master_id,)).fetchone()
    flags = _change_flags(master, row, previous_history)
    _record_change_issues(db, master_id, master, row, flags)
    _insert_history(db, master_id, row, flags)
    current = db.execute("SELECT status FROM master_employees_v3 WHERE id = ?", (master_id,)).fetchone()
    if current and current["status"] not in {"IDENTITY_CONFLICT", "DUPLICATE_REVIEW", "NEEDS_REVIEW", "ARCHIVED"}:
        _update_master_current(db, master_id, row, "ACTIVE")
    else:
        _update_master_current(db, master_id, row)
    _detect_cross_identity_issues(db, master_id, row)
    return master_id


def _apply_lifecycle_statuses(db, rows: list[dict[str, Any]]) -> None:
    latest_period = max((_period_sort_key(row.get("month_year", "")) for row in rows), default=(0, 0))
    masters = db.execute("SELECT * FROM master_employees_v3 WHERE status <> 'ARCHIVED'").fetchall()
    for master in masters:
        master_period = _period_sort_key(f"{master['last_seen_month']}/{master['last_seen_year']}")
        if master["status"] in {"IDENTITY_CONFLICT", "DUPLICATE_REVIEW", "NEEDS_REVIEW"}:
            continue
        first_period = _period_sort_key(f"{master['first_seen_month']}/{master['first_seen_year']}")
        if master_period < latest_period:
            db.execute("UPDATE master_employees_v3 SET status = 'INACTIVE', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (master["id"],))
        elif first_period == latest_period:
            db.execute("UPDATE master_employees_v3 SET status = 'NEW', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (master["id"],))
        else:
            db.execute("UPDATE master_employees_v3 SET status = 'ACTIVE', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (master["id"],))


def build_master_register(db) -> dict[str, Any]:
    init_master_register_schema(db)
    db.execute("DELETE FROM master_employee_issues_v3")
    db.execute("DELETE FROM master_employee_history_v3")
    db.execute("DELETE FROM master_employees_v3")
    rows = _source_rows(db)
    for row in rows:
        _process_row(db, row)
    _apply_lifecycle_statuses(db, rows)
    return summary(db)


def update_master_register(db) -> dict[str, Any]:
    init_master_register_schema(db)
    rows = _source_rows(db)
    for row in rows:
        _process_row(db, row)
    _apply_lifecycle_statuses(db, rows)
    return summary(db)


def summary(db) -> dict[str, Any]:
    init_master_register_schema(db)
    counts = {status.lower() + "_count": 0 for status in VALID_STATUSES}
    for row in db.execute("SELECT status, COUNT(*) AS c FROM master_employees_v3 GROUP BY status").fetchall():
        counts[f"{str(row['status'] or '').lower()}_count"] = row["c"]
    return {
        "total_master_employees": db.execute("SELECT COUNT(*) AS c FROM master_employees_v3").fetchone()["c"],
        "active_count": counts.get("active_count", 0),
        "inactive_count": counts.get("inactive_count", 0),
        "new_count": counts.get("new_count", 0),
        "needs_review_count": counts.get("needs_review_count", 0),
        "identity_conflict_count": counts.get("identity_conflict_count", 0),
        "duplicate_review_count": counts.get("duplicate_review_count", 0),
        "archived_count": counts.get("archived_count", 0),
        "history_row_count": db.execute("SELECT COUNT(*) AS c FROM master_employee_history_v3").fetchone()["c"],
        "unresolved_issue_count": db.execute("SELECT COUNT(*) AS c FROM master_employee_issues_v3 WHERE status = 'OPEN'").fetchone()["c"],
    }


def employees(db, args: dict[str, Any]) -> list[dict[str, Any]]:
    init_master_register_schema(db)
    conditions = ["1=1"]
    params: list[Any] = []
    search = str(args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        conditions.append("(employee_name LIKE ? OR employee_id LIKE ? OR pan LIKE ? OR gpf_pran LIKE ?)")
        params.extend([like, like, like, like])
    for arg_name, column in (("designation", "current_designation"), ("group", "current_group"), ("status", "status")):
        value = str(args.get(arg_name) or "").strip()
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)
    try:
        limit = min(max(int(args.get("limit") or 500), 1), 2000)
    except (TypeError, ValueError):
        limit = 500
    sql = f"""
        SELECT m.*,
               (SELECT COUNT(*) FROM master_employee_issues_v3 i WHERE i.master_employee_id = m.id AND i.status = 'OPEN') AS open_issue_count,
               (SELECT h.source_employee_row_id FROM master_employee_history_v3 h WHERE h.master_employee_id = m.id ORDER BY h.id DESC LIMIT 1) AS latest_source_employee_row_id
        FROM master_employees_v3 m
        WHERE {' AND '.join(conditions)}
        ORDER BY m.status DESC, m.employee_name
        LIMIT ?
    """
    params.append(limit)
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def employee_detail(db, master_id: int) -> dict[str, Any] | None:
    init_master_register_schema(db)
    row = db.execute("""
        SELECT m.*,
               (SELECT COUNT(*) FROM master_employee_issues_v3 i WHERE i.master_employee_id = m.id AND i.status = 'OPEN') AS open_issue_count
        FROM master_employees_v3 m
        WHERE m.id = ?
    """, (master_id,)).fetchone()
    return dict(row) if row else None


def history(db, master_id: int) -> list[dict[str, Any]]:
    init_master_register_schema(db)
    return [dict(row) for row in db.execute("""
        SELECT * FROM master_employee_history_v3
        WHERE master_employee_id = ?
        ORDER BY id DESC
    """, (master_id,)).fetchall()]


def issues(db, args: dict[str, Any]) -> list[dict[str, Any]]:
    init_master_register_schema(db)
    conditions = ["1=1"]
    params: list[Any] = []
    for arg_name, column in (("status", "i.status"), ("issue_type", "i.issue_type"), ("severity", "i.severity")):
        value = str(args.get(arg_name) or "").strip()
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)
    search = str(args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        conditions.append("(m.employee_name LIKE ? OR m.employee_id LIKE ? OR m.pan LIKE ? OR i.message LIKE ?)")
        params.extend([like, like, like, like])
    return [dict(row) for row in db.execute(f"""
        SELECT i.*, m.employee_name, m.employee_id, m.pan
        FROM master_employee_issues_v3 i
        LEFT JOIN master_employees_v3 m ON m.id = i.master_employee_id
        WHERE {' AND '.join(conditions)}
        ORDER BY CASE i.severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 WHEN 'LOW' THEN 4 ELSE 5 END,
                 i.id DESC
        LIMIT 1000
    """, params).fetchall()]


def resolve_issue(db, issue_id: int) -> int:
    cur = db.execute("""
        UPDATE master_employee_issues_v3
        SET status = 'RESOLVED', resolved_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (issue_id,))
    return cur.rowcount


def archive_employee(db, master_id: int) -> int:
    cur = db.execute("""
        UPDATE master_employees_v3
        SET status = 'ARCHIVED', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (master_id,))
    return cur.rowcount


def options(db) -> dict[str, Any]:
    init_master_register_schema(db)
    return {
        "statuses": sorted(VALID_STATUSES),
        "designations": [row["current_designation"] for row in db.execute("SELECT DISTINCT current_designation FROM master_employees_v3 WHERE COALESCE(current_designation,'') <> '' ORDER BY current_designation").fetchall()],
        "groups": [row["current_group"] for row in db.execute("SELECT DISTINCT current_group FROM master_employees_v3 WHERE COALESCE(current_group,'') <> '' ORDER BY current_group").fetchall()],
        "issue_types": [row["issue_type"] for row in db.execute("SELECT DISTINCT issue_type FROM master_employee_issues_v3 WHERE COALESCE(issue_type,'') <> '' ORDER BY issue_type").fetchall()],
    }


def export_workbook(db, export_dir: Path, metadata: dict[str, Any]) -> Path:
    init_master_register_schema(db)
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = export_dir / f"Master_Employee_Register_{timestamp}.xlsx"
    master_rows = employees(db, {"limit": 200000})
    issue_rows = issues(db, {})
    history_rows = [dict(row) for row in db.execute("SELECT * FROM master_employee_history_v3 ORDER BY master_employee_id, id").fetchall()]
    summary_rows = [{"Metric": key, "Value": value} for key, value in summary(db).items()]
    metadata_rows = [
        {"Field": "Application", "Value": metadata.get("app_name", "IFMS Report Analyzer")},
        {"Field": "Designed and Developed by", "Value": "Neeraj Purohit"},
        {"Field": "Role", "Value": "Senior Assistant, Rajasthan Police"},
        {"Field": "Email", "Value": metadata.get("developer_email", "rjjo200924001769@rajasthan.in")},
        {"Field": "Export Timestamp", "Value": datetime.now().isoformat(timespec="seconds")},
        {"Field": "App Build Label", "Value": metadata.get("build_label", "")},
        {"Field": "Disclaimer", "Value": metadata.get("disclaimer", "")},
    ]
    sheets = {
        "Export Metadata": pd.DataFrame(metadata_rows),
        "Master Summary": pd.DataFrame(summary_rows),
        "Master Register": pd.DataFrame(master_rows),
        "Active Employees": pd.DataFrame([r for r in master_rows if r.get("status") == "ACTIVE"]),
        "Inactive Employees": pd.DataFrame([r for r in master_rows if r.get("status") == "INACTIVE"]),
        "New Employees": pd.DataFrame([r for r in master_rows if r.get("status") == "NEW"]),
        "Needs Review": pd.DataFrame([r for r in master_rows if r.get("status") == "NEEDS_REVIEW"]),
        "Identity Conflicts": pd.DataFrame([r for r in issue_rows if r.get("issue_type") == "IDENTITY_CONFLICT"]),
        "Duplicate Review": pd.DataFrame([r for r in issue_rows if r.get("issue_type") == "DUPLICATE_REVIEW"]),
        "Employee History": pd.DataFrame(history_rows),
        "Master Issues": pd.DataFrame(issue_rows),
        "Data Quality Notes": pd.DataFrame([
            {"Note": "Master register is a separate intelligence layer and does not modify employees_v2."},
            {"Note": "Low-confidence fallback records require human review before merge decisions."},
            {"Note": "Human review is compulsory before using this data for official work."},
        ]),
    }
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe_name = name[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)
            ws = writer.book[safe_name]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 45)
    return path
