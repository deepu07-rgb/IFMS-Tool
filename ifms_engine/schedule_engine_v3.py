from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any


SOURCE_TYPE = "derived_from_employee_master"


@dataclass(frozen=True)
class ScheduleType:
    key: str
    label: str
    heads: tuple[str, ...]


SCHEDULE_TYPES: tuple[ScheduleType, ...] = (
    ScheduleType("income_tax", "Income Tax", ("income_tax", "itax")),
    ScheduleType("lic", "LIC", ("lic",)),
    ScheduleType("gpf", "GPF", ("gpf",)),
    ScheduleType("gpf_2004", "GPF 2004", ("gpf_2004",)),
    ScheduleType("ais_gpf", "AIS GPF", ("ais_gpf",)),
    ScheduleType("si_premium", "SI Premium", ("sip", "si_premium")),
    ScheduleType("si_loan", "SI Loan", ("sil", "si_loan")),
    ScheduleType("sii", "SII", ("sii",)),
    ScheduleType("rghs", "RGHS", ("rghs",)),
    ScheduleType("rop", "ROP", ("rop",)),
    ScheduleType("advance_salary", "Advance Salary", ("advance_salary",)),
    ScheduleType("ppss_jdr", "PPSS JDR", ("ppss_jdr",)),
    ScheduleType("roadways_deduction", "Roadways Deduction", ("roadways_deduction",)),
    ScheduleType("car_rent", "Car Rent", ("car_rent",)),
    ScheduleType("hfrh", "HFRH", ("hfrh",)),
    ScheduleType("eacpenf", "EACPenF", ("eacpenf",)),
    ScheduleType("giais", "GIAIS", ("giais",)),
)

SCHEDULE_BY_KEY = {item.key: item for item in SCHEDULE_TYPES}
BUILTIN_HEAD_TO_SCHEDULE = {head: item for item in SCHEDULE_TYPES for head in item.heads}
HEAD_TO_SCHEDULE = BUILTIN_HEAD_TO_SCHEDULE
VALID_SCHEDULE_KEYS = {item.key for item in SCHEDULE_TYPES} | {"other_components"}


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _page_args(args: dict[str, Any]) -> tuple[int, int]:
    page = max(1, _as_int(args.get("page"), 1))
    page_size = _as_int(args.get("page_size") or args.get("per_page"), 50)
    page_size = min(max(1, page_size), 500)
    return page, page_size


def _known_heads(db) -> set[str]:
    rows = db.execute("""
        SELECT DISTINCT normalized_head
        FROM employee_components_v2
        WHERE COALESCE(normalized_head, '') != ''
    """).fetchall()
    return {row[0] for row in rows}


def init_schedule_mapping_schema(db) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS schedule_component_mappings_v3 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component_head TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            label TEXT,
            active INTEGER DEFAULT 1,
            ignored INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_schedule_component_mappings_head ON schedule_component_mappings_v3(component_head)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_schedule_component_mappings_active ON schedule_component_mappings_v3(active, ignored)")


def custom_mapping_rows(db, include_inactive: bool = False):
    init_schedule_mapping_schema(db)
    where = "" if include_inactive else "WHERE active = 1"
    return db.execute(f"""
        SELECT id, component_head, schedule_type, label, active, ignored, created_at, updated_at, notes
        FROM schedule_component_mappings_v3
        {where}
        ORDER BY component_head, id ASC
    """).fetchall()


def ignored_heads(db) -> set[str]:
    return {
        row["component_head"] if hasattr(row, "keys") else row[0]
        for row in custom_mapping_rows(db)
        if int(_row_get(row, "ignored", 0) or 0) == 1
    }


def effective_head_to_schedule(db) -> dict[str, ScheduleType]:
    mapping = dict(BUILTIN_HEAD_TO_SCHEDULE)
    for row in custom_mapping_rows(db):
        if int(_row_get(row, "ignored", 0) or 0) == 1:
            mapping.pop(_row_get(row, "component_head", ""), None)
            continue
        key = _row_get(row, "schedule_type", "") or "other_components"
        label = _row_get(row, "label", "") or component_label(_row_get(row, "component_head", ""))
        mapping[_row_get(row, "component_head", "")] = ScheduleType(key, label if key == "other_components" else schedule_label_for_key(key), (_row_get(row, "component_head", ""),))
    return mapping


def schedule_label_for_key(key: str) -> str:
    if key == "other_components":
        return "Other Components"
    item = SCHEDULE_BY_KEY.get(key)
    return item.label if item else component_label(key)


def _heads_for_schedule(db, schedule_type: str) -> tuple[str, ...]:
    mapping = effective_head_to_schedule(db)
    ignored = ignored_heads(db)
    if not schedule_type:
        return tuple(sorted(head for head in _known_heads(db) if head not in ignored))
    if schedule_type == "other_components":
        return tuple(sorted(
            head for head, mapped in mapping.items()
            if mapped.key == "other_components" and head not in BUILTIN_HEAD_TO_SCHEDULE and head not in ignored
        ))
    item = SCHEDULE_BY_KEY.get(schedule_type)
    if not item:
        return ()
    heads = set(item.heads)
    heads.update(head for head, mapped in mapping.items() if mapped.key == schedule_type)
    return tuple(sorted(head for head in heads if head not in ignored))


def schedule_label_for_head(head: str) -> tuple[str, str]:
    item = BUILTIN_HEAD_TO_SCHEDULE.get(head)
    if item:
        return item.key, item.label
    return "other_components", "Other Components"


def schedule_label_for_head_db(db, head: str) -> tuple[str, str]:
    item = effective_head_to_schedule(db).get(head)
    if item:
        return item.key, item.label
    return "other_components", "Other Components"


def component_label(head: str) -> str:
    labels = {
        "basic_pay": "Basic Pay",
        "da": "DA",
        "hra": "HRA",
        "gpf_2004": "GPF 2004",
        "ais_gpf": "AIS GPF",
        "income_tax": "Income Tax",
        "itax": "ITax",
        "si_premium": "SI Premium",
        "sip": "SIP",
        "si_loan": "SI Loan",
        "sil": "SIL",
        "sii": "SII",
        "advance_salary": "Advance Salary",
        "ppss_jdr": "PPSS JDR",
        "roadways_deduction": "Roadways Deduction",
        "car_rent": "Car Rent",
        "hfrh": "HFRH",
        "eacpenf": "EACPenF",
        "giais": "GIAIS",
        "rop": "ROP",
        "lic": "LIC",
        "gpf": "GPF",
        "rghs": "RGHS",
    }
    if head in labels:
        return labels[head]
    return str(head or "").replace("_", " ").title()


def build_schedule_where(db, args: dict[str, Any]) -> tuple[str, list[Any], tuple[str, ...]]:
    conditions = ["c.amount IS NOT NULL", "c.amount != 0"]
    params: list[Any] = []

    show_deleted = str(args.get("show_deleted") or "").lower() in {"1", "true", "yes", "on"}
    if not show_deleted:
        conditions.append("COALESCE(e.is_deleted, 0) = 0")

    heads = _heads_for_schedule(db, str(args.get("schedule_type") or ""))
    if args.get("schedule_type") and not heads:
        conditions.append("1 = 0")
    elif heads:
        conditions.append("c.normalized_head IN (" + ",".join("?" for _ in heads) + ")")
        params.extend(heads)

    exact_filters = [
        ("group_name", "e.group_name"),
        ("month_year", "e.month_year"),
        ("source_file", "e.source_filename"),
        ("pay_scale", "e.pay_scale_raw"),
    ]
    for key, column in exact_filters:
        value = str(args.get(key) or args.get(key.replace("_name", "")) or "").strip()
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)

    designation = str(args.get("final_designation") or "").strip()
    if designation:
        conditions.append("COALESCE(e.final_designation, e.final_designation_en, e.normalized_designation, '') LIKE ?")
        params.append(f"%{designation}%")

    search = str(args.get("employee_search") or args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        conditions.append("(e.raw_name LIKE ? OR e.employee_id LIKE ? OR e.pan_raw LIKE ?)")
        params.extend([like, like, like])

    op = str(args.get("amount_operator") or "").strip().lower()
    value = args.get("amount_value")
    value2 = args.get("amount_value_2")
    if op and value not in (None, ""):
        amount = _as_float(value)
        if op in {"eq", "equals", "="}:
            conditions.append("c.amount = ?")
            params.append(amount)
        elif op in {"gt", "greater_than", ">"}:
            conditions.append("c.amount > ?")
            params.append(amount)
        elif op in {"gte", "greater_than_or_equal", ">="}:
            conditions.append("c.amount >= ?")
            params.append(amount)
        elif op in {"lt", "less_than", "<"}:
            conditions.append("c.amount < ?")
            params.append(amount)
        elif op in {"lte", "less_than_or_equal", "<="}:
            conditions.append("c.amount <= ?")
            params.append(amount)
        elif op == "between" and value2 not in (None, ""):
            lo, hi = sorted((_as_float(value), _as_float(value2)))
            conditions.append("c.amount BETWEEN ? AND ?")
            params.extend([lo, hi])

    return " AND ".join(conditions), params, heads


def _base_select(where_sql: str) -> str:
    return f"""
        SELECT
          e.id AS employee_db_id,
          e.source_filename AS source_file,
          e.bill_id,
          b.bill_no,
          e.group_name,
          e.month_year,
          e.sr_no AS employee_sr_no,
          e.raw_name AS employee_name,
          e.employee_id,
          e.pan_raw AS pan,
          e.pay_scale_raw AS pay_scale,
          COALESCE(e.final_designation, e.final_designation_en, e.normalized_designation, '') AS final_designation,
          c.normalized_head AS component_head,
          c.raw_head,
          c.amount,
          COALESCE(basic.amount, 0) AS basic_pay,
          COALESCE(c.source_page, e.page_no, 0) AS page_no,
          COALESCE(e.row_verification_status, e.employee_data_status, '') AS row_audit_status,
          COALESCE(e.employee_data_status, e.row_verification_status, '') AS employee_data_status,
          COALESCE(c.source_type, '') AS component_source_type,
          COALESCE(e.is_deleted, 0) AS is_deleted
        FROM employee_components_v2 c
        JOIN employees_v2 e ON e.id = c.employee_id
        LEFT JOIN bills_v2 b ON b.id = e.bill_id
        LEFT JOIN employee_components_v2 basic
          ON basic.employee_id = e.id AND basic.normalized_head = 'basic_pay'
        WHERE {where_sql}
    """


def row_to_schedule_entry(row: Any, db=None) -> dict[str, Any]:
    head = _row_get(row, "component_head", "")
    schedule_type, schedule_label = schedule_label_for_head_db(db, head) if db is not None else schedule_label_for_head(head)
    return {
        "source_file": _row_get(row, "source_file", "") or "",
        "bill_id": _row_get(row, "bill_id", None),
        "bill_no": _row_get(row, "bill_no", "") or "",
        "group_name": _row_get(row, "group_name", "") or "",
        "month_year": _row_get(row, "month_year", "") or "",
        "employee_db_id": _row_get(row, "employee_db_id", None),
        "employee_sr_no": _row_get(row, "employee_sr_no", 0) or 0,
        "sr_no": _row_get(row, "employee_sr_no", 0) or 0,
        "employee_name": _row_get(row, "employee_name", "") or "",
        "name": _row_get(row, "employee_name", "") or "",
        "employee_id": _row_get(row, "employee_id", "") or "",
        "pan": _row_get(row, "pan", "") or "",
        "pay_scale": _row_get(row, "pay_scale", "") or "",
        "final_designation": _row_get(row, "final_designation", "") or "",
        "designation": _row_get(row, "final_designation", "") or "",
        "component_head": head or "",
        "component_label": component_label(head),
        "raw_head": _row_get(row, "raw_head", "") or "",
        "schedule_type": schedule_type,
        "schedule_label": schedule_label,
        "amount": _row_get(row, "amount", 0) or 0,
        "total": _row_get(row, "amount", 0) or 0,
        "basic_pay": _row_get(row, "basic_pay", 0) or 0,
        "page_no": _row_get(row, "page_no", 0) or 0,
        "row_audit_status": _row_get(row, "row_audit_status", "") or "",
        "employee_data_status": _row_get(row, "employee_data_status", "") or "",
        "component_source_type": _row_get(row, "component_source_type", "") or "",
        "source_type": SOURCE_TYPE,
        "is_deleted": _row_get(row, "is_deleted", 0) or 0,
    }


def query_schedule_entries(db, args: dict[str, Any], paginate: bool = True) -> dict[str, Any]:
    where_sql, params, _heads = build_schedule_where(db, args)
    base_sql = _base_select(where_sql)
    order_sql = " ORDER BY c.normalized_head, e.group_name, e.sr_no, c.id"

    all_rows = db.execute(base_sql + order_sql, params).fetchall()
    entries = [row_to_schedule_entry(row, db) for row in all_rows]
    summary = build_summary(entries, db, args)

    page, page_size = _page_args(args)
    if paginate:
        start = (page - 1) * page_size
        paged = entries[start:start + page_size]
    else:
        paged = entries
        page_size = len(entries) or page_size

    return {
        "entries": paged,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": len(entries),
            "pages": ceil(len(entries) / page_size) if page_size else 0,
        },
        "summary": summary,
    }


def build_summary(entries: list[dict[str, Any]], db=None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    total_amount = sum(_as_float(e.get("amount")) for e in entries)
    manual_rows = sum(1 for e in entries if str(e.get("component_source_type") or "").lower() == "manual_edit")
    parsed_rows = len(entries) - manual_rows
    rows_needing_review = sum(1 for e in entries if "REVIEW" in str(e.get("employee_data_status") or e.get("row_audit_status") or "").upper())
    deleted_rows = sum(1 for e in entries if _as_int(e.get("is_deleted")) != 0)
    schedule_type = str(args.get("schedule_type") or "")
    if not schedule_type:
        schedule_type = "all"
    return {
        "schedule_type": schedule_type,
        "entry_count": len(entries),
        "count": len(entries),
        "unique_employees": len({e.get("employee_db_id") or e.get("employee_id") for e in entries}),
        "total_amount": total_amount,
        "grand_total": total_amount,
        "total_positive": sum(_as_float(e.get("amount")) for e in entries if _as_float(e.get("amount")) > 0),
        "total_negative": sum(_as_float(e.get("amount")) for e in entries if _as_float(e.get("amount")) < 0),
        "groups_count": len({e.get("group_name") for e in entries if e.get("group_name")}),
        "files_count": len({e.get("source_file") for e in entries if e.get("source_file")}),
        "source_type": SOURCE_TYPE,
        "audit": {
            "total_schedule_rows": len(entries),
            "total_amount": total_amount,
            "rows_from_parsed_data": parsed_rows,
            "rows_from_manual_edits": manual_rows,
            "rows_from_deleted_employees": deleted_rows,
            "rows_needing_review": rows_needing_review,
            "components_not_mapped_to_schedule_types": count_unmapped_component_heads(db, args) if db is not None else 0,
        },
    }


def count_unmapped_component_heads(db, args: dict[str, Any] | None = None) -> int:
    return len(unmapped_components(db, args or {}))


def list_schedule_types(db, args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    args = dict(args or {})
    result = []
    for item in SCHEDULE_TYPES:
        item_args = dict(args)
        item_args["schedule_type"] = item.key
        data = query_schedule_entries(db, item_args, paginate=False)
        result.append({
            "key": item.key,
            "label": item.label,
            "mapped_component_heads": list(item.heads),
            "entry_count": data["summary"]["entry_count"],
            "total_amount": data["summary"]["total_amount"],
        })
    other_args = dict(args)
    other_args["schedule_type"] = "other_components"
    other_heads = _heads_for_schedule(db, "other_components")
    other_data = query_schedule_entries(db, other_args, paginate=False) if other_heads else {"summary": {"entry_count": 0, "total_amount": 0}}
    result.append({
        "key": "other_components",
        "label": "Other Components",
        "mapped_component_heads": list(other_heads),
        "entry_count": other_data["summary"]["entry_count"],
        "total_amount": other_data["summary"]["total_amount"],
    })
    return result


def unmapped_components(db, args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    args = dict(args or {})
    mapped = set(effective_head_to_schedule(db))
    ignored = ignored_heads(db)
    conditions = ["c.amount IS NOT NULL", "c.amount != 0"]
    params: list[Any] = []
    if str(args.get("show_deleted") or "").lower() not in {"1", "true", "yes", "on"}:
        conditions.append("COALESCE(e.is_deleted,0) = 0")
    if mapped:
        conditions.append("c.normalized_head NOT IN (" + ",".join("?" for _ in mapped) + ")")
        params.extend(sorted(mapped))
    if ignored:
        conditions.append("c.normalized_head NOT IN (" + ",".join("?" for _ in ignored) + ")")
        params.extend(sorted(ignored))
    where_sql = " AND ".join(conditions)
    rows = db.execute(f"""
        SELECT c.normalized_head AS component_head,
               COUNT(*) AS row_count,
               COUNT(DISTINCT e.id) AS unique_employee_count,
               COALESCE(SUM(c.amount),0) AS total_amount,
               COALESCE(SUM(CASE WHEN c.amount > 0 THEN c.amount ELSE 0 END),0) AS positive_total,
               COALESCE(SUM(CASE WHEN c.amount < 0 THEN c.amount ELSE 0 END),0) AS negative_total
        FROM employee_components_v2 c
        JOIN employees_v2 e ON e.id = c.employee_id
        WHERE {where_sql}
        GROUP BY c.normalized_head
        ORDER BY c.normalized_head
    """, params).fetchall()
    result = []
    for row in rows:
        head = _row_get(row, "component_head", "")
        samples = db.execute(f"""
            SELECT DISTINCT e.raw_name
            FROM employee_components_v2 c
            JOIN employees_v2 e ON e.id = c.employee_id
            WHERE {where_sql}
              AND c.normalized_head = ?
            ORDER BY e.raw_name
            LIMIT 5
        """, params + [head]).fetchall()
        result.append({
            "component_head": head,
            "display_label": component_label(head),
            "row_count": _row_get(row, "row_count", 0) or 0,
            "unique_employee_count": _row_get(row, "unique_employee_count", 0) or 0,
            "total_amount": _row_get(row, "total_amount", 0) or 0,
            "positive_total": _row_get(row, "positive_total", 0) or 0,
            "negative_total": _row_get(row, "negative_total", 0) or 0,
            "sample_employees": [_row_get(sample, "raw_name", "") for sample in samples],
            "suggested_schedule_type": "other_components",
            "status": "unmapped",
        })
    return result


def reconciliation_rows(db, args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    args = dict(args or {})
    rows = []
    for item in SCHEDULE_TYPES + (ScheduleType("other_components", "Other Components", _heads_for_schedule(db, "other_components")),):
        item_args = dict(args)
        item_args["schedule_type"] = item.key
        data = query_schedule_entries(db, item_args, paginate=False)
        schedule_total = data["summary"]["total_amount"]
        heads = _heads_for_schedule(db, item.key)
        ledger_total = _ledger_total_for_heads(db, heads, args)
        difference = schedule_total - ledger_total
        if data["summary"]["entry_count"] == 0 and abs(ledger_total) < 0.0001:
            status = "no_data"
        elif abs(difference) < 0.0001:
            status = "matched"
        else:
            status = "mismatch"
        rows.append({
            "schedule_type": item.key,
            "label": item.label,
            "entry_count": data["summary"]["entry_count"],
            "schedule_total": schedule_total,
            "component_ledger_total": ledger_total,
            "difference": difference,
            "status": status,
            "affected_component_heads": list(heads),
        })
    return rows


def _ledger_total_for_heads(db, heads: tuple[str, ...], args: dict[str, Any]) -> float:
    if not heads:
        return 0
    conditions = ["c.amount IS NOT NULL", "c.amount != 0", "c.normalized_head IN (" + ",".join("?" for _ in heads) + ")"]
    params: list[Any] = list(heads)
    if str(args.get("show_deleted") or "").lower() not in {"1", "true", "yes", "on"}:
        conditions.append("COALESCE(e.is_deleted,0) = 0")
    for key, column in [("group_name", "e.group_name"), ("month_year", "e.month_year"), ("source_file", "e.source_filename"), ("pay_scale", "e.pay_scale_raw")]:
        value = str(args.get(key) or "").strip()
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)
    return _as_float(db.execute(f"""
        SELECT COALESCE(SUM(c.amount),0)
        FROM employee_components_v2 c
        JOIN employees_v2 e ON e.id = c.employee_id
        WHERE {' AND '.join(conditions)}
    """, params).fetchone()[0])


def mapping_payload(row: Any) -> dict[str, Any]:
    return {
        "id": _row_get(row, "id"),
        "component_head": _row_get(row, "component_head", "") or "",
        "schedule_type": _row_get(row, "schedule_type", "") or "",
        "label": _row_get(row, "label", "") or "",
        "active": bool(_row_get(row, "active", 0)),
        "ignored": bool(_row_get(row, "ignored", 0)),
        "created_at": _row_get(row, "created_at", "") or "",
        "updated_at": _row_get(row, "updated_at", "") or "",
        "notes": _row_get(row, "notes", "") or "",
    }


def list_component_mappings(db) -> dict[str, Any]:
    init_schedule_mapping_schema(db)
    builtins = [
        {
            "component_head": head,
            "schedule_type": item.key,
            "label": item.label,
            "active": True,
            "ignored": False,
            "builtin": True,
        }
        for head, item in sorted(BUILTIN_HEAD_TO_SCHEDULE.items())
    ]
    custom = [mapping_payload(row) | {"builtin": False} for row in custom_mapping_rows(db, include_inactive=True)]
    return {"built_in": builtins, "custom": custom}


def upsert_component_mapping(db, component_head: str, schedule_type: str, label: str = "", notes: str = "", active: bool = True) -> dict[str, Any]:
    init_schedule_mapping_schema(db)
    component_head = str(component_head or "").strip()
    schedule_type = str(schedule_type or "other_components").strip()
    if not component_head:
        raise ValueError("component_head is required")
    if schedule_type not in VALID_SCHEDULE_KEYS:
        raise ValueError("Invalid schedule_type")
    db.execute("""
        UPDATE schedule_component_mappings_v3
        SET active = 0, updated_at = CURRENT_TIMESTAMP
        WHERE component_head = ? AND active = 1
    """, (component_head,))
    db.execute("""
        INSERT INTO schedule_component_mappings_v3 (
            component_head, schedule_type, label, active, ignored, notes, updated_at
        ) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
    """, (component_head, schedule_type, label or component_label(component_head), 1 if active else 0, 0, notes))
    row = db.execute("SELECT * FROM schedule_component_mappings_v3 WHERE id = last_insert_rowid()").fetchone()
    return mapping_payload(row)


def deactivate_component_mapping(db, component_head: str = "", mapping_id: int | None = None) -> int:
    init_schedule_mapping_schema(db)
    if mapping_id:
        cur = db.execute("""
            UPDATE schedule_component_mappings_v3
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND active = 1
        """, (mapping_id,))
    else:
        cur = db.execute("""
            UPDATE schedule_component_mappings_v3
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE component_head = ? AND active = 1
        """, (component_head,))
    return cur.rowcount


def reactivate_component_mapping(db, mapping_id: int) -> dict[str, Any]:
    init_schedule_mapping_schema(db)
    row = db.execute("SELECT * FROM schedule_component_mappings_v3 WHERE id = ?", (mapping_id,)).fetchone()
    if not row:
        raise ValueError("mapping not found")
    component_head = _row_get(row, "component_head", "")
    db.execute("""
        UPDATE schedule_component_mappings_v3
        SET active = 0, updated_at = CURRENT_TIMESTAMP
        WHERE component_head = ? AND active = 1
    """, (component_head,))
    db.execute("""
        UPDATE schedule_component_mappings_v3
        SET active = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (mapping_id,))
    row = db.execute("SELECT * FROM schedule_component_mappings_v3 WHERE id = ?", (mapping_id,)).fetchone()
    return mapping_payload(row)


def ignore_component(db, component_head: str, notes: str = "") -> dict[str, Any]:
    init_schedule_mapping_schema(db)
    component_head = str(component_head or "").strip()
    if not component_head:
        raise ValueError("component_head is required")
    db.execute("""
        UPDATE schedule_component_mappings_v3
        SET active = 0, updated_at = CURRENT_TIMESTAMP
        WHERE component_head = ? AND active = 1
    """, (component_head,))
    db.execute("""
        INSERT INTO schedule_component_mappings_v3 (
            component_head, schedule_type, label, active, ignored, notes, updated_at
        ) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
    """, (component_head, "other_components", component_label(component_head), 1, 1, notes))
    row = db.execute("SELECT * FROM schedule_component_mappings_v3 WHERE id = last_insert_rowid()").fetchone()
    return mapping_payload(row)


def unignore_component(db, component_head: str = "", mapping_id: int | None = None) -> int:
    init_schedule_mapping_schema(db)
    if mapping_id:
        cur = db.execute("""
            UPDATE schedule_component_mappings_v3
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND ignored = 1 AND active = 1
        """, (mapping_id,))
    else:
        cur = db.execute("""
            UPDATE schedule_component_mappings_v3
            SET active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE component_head = ? AND ignored = 1 AND active = 1
        """, (component_head,))
    return cur.rowcount
