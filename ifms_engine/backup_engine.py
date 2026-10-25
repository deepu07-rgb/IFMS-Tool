from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


BACKUP_DISCLAIMER = (
    "This backup is created for local office productivity use. Human review of "
    "restored data is compulsory before official use."
)


def ensure_backup_folder(app_root: str | os.PathLike[str]) -> Path:
    folder = Path(app_root) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder.resolve()


def safe_named_file(folder: Path, file_name: str, suffix: str) -> Path:
    raw = str(file_name or "").strip()
    if not raw:
        raise ValueError("file_name is required")
    if raw != Path(raw).name or os.path.isabs(raw) or ".." in Path(raw).parts:
        raise ValueError("Invalid file name")
    if not raw.lower().endswith(suffix.lower()):
        raise ValueError(f"File must end with {suffix}")
    path = (folder / raw).resolve()
    if folder.resolve() not in path.parents:
        raise ValueError("Invalid file path")
    return path


def table_exists(db: sqlite3.Connection, table_name: str) -> bool:
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def count_rows(db: sqlite3.Connection, table_name: str, where_sql: str = "1=1") -> int:
    if not table_exists(db, table_name):
        return 0
    return int(db.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {where_sql}").fetchone()[0] or 0)


def table_rows(db: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    if not table_exists(db, table_name):
        return []
    return [dict(row) for row in db.execute(f"SELECT * FROM {table_name} ORDER BY id").fetchall()]


def database_counts(db_path: str | os.PathLike[str]) -> dict[str, int]:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        return {
            "bill_count": count_rows(db, "bills_v2"),
            "employee_count": count_rows(db, "employees_v2"),
            "dictionary_mapping_count": count_rows(db, "dictionary_mappings_v3"),
            "schedule_mapping_count": count_rows(db, "schedule_component_mappings_v3"),
            "audit_log_count": count_rows(db, "edit_audit_log_v3"),
            "deleted_row_count": count_rows(db, "employees_v2", "COALESCE(is_deleted,0) != 0"),
            "unresolved_issue_count": count_rows(db, "validation_issues_v2", "COALESCE(status,'OPEN') != 'RESOLVED'"),
        }
    finally:
        db.close()


def _snapshot_database(db_path: str | os.PathLike[str], target_path: Path) -> None:
    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(target_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()


def _write_json(zf: zipfile.ZipFile, name: str, payload: Any) -> None:
    zf.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def create_full_backup(
    db_path: str | os.PathLike[str],
    backup_folder: str | os.PathLike[str],
    app_name: str,
    build_label: str,
    prefix: str = "IFMS_Backup",
) -> dict[str, Any]:
    folder = Path(backup_folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{prefix}_{timestamp}.zip"
    zip_path = safe_named_file(folder, file_name, ".zip")

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        counts = {
            "bill_count": count_rows(db, "bills_v2"),
            "employee_count": count_rows(db, "employees_v2"),
            "dictionary_mapping_count": count_rows(db, "dictionary_mappings_v3"),
            "schedule_mapping_count": count_rows(db, "schedule_component_mappings_v3"),
            "audit_log_count": count_rows(db, "edit_audit_log_v3"),
            "deleted_row_count": count_rows(db, "employees_v2", "COALESCE(is_deleted,0) != 0"),
            "unresolved_issue_count": count_rows(db, "validation_issues_v2", "COALESCE(status,'OPEN') != 'RESOLVED'"),
        }
        dictionary_rows = table_rows(db, "dictionary_mappings_v3")
        schedule_rows = table_rows(db, "schedule_component_mappings_v3")
        audit_rows = table_rows(db, "edit_audit_log_v3")
    finally:
        db.close()

    with tempfile.TemporaryDirectory() as tmp:
        snapshot_path = Path(tmp) / "ifms_data.db"
        _snapshot_database(db_path, snapshot_path)
        manifest = {
            "app_name": app_name,
            "build_label": build_label,
            "backup_created_at": datetime.now().isoformat(timespec="seconds"),
            "database_file_name": "ifms_data.db",
            "database_size_bytes": snapshot_path.stat().st_size,
            **counts,
            "created_by": "Neeraj Purohit",
            "disclaimer": BACKUP_DISCLAIMER,
        }
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot_path, "ifms_data.db")
            _write_json(zf, "dictionary_mappings.json", {"metadata": manifest, "dictionary_mappings": dictionary_rows})
            _write_json(zf, "schedule_component_mappings.json", {"metadata": manifest, "schedule_component_mappings": schedule_rows})
            _write_json(zf, "audit_log.json", {"metadata": manifest, "edit_audit_log_v3": audit_rows})
            _write_json(zf, "app_settings.json", {"app_name": app_name, "build_label": build_label, "database": "ifms_data.db"})
            _write_json(zf, "backup_manifest.json", manifest)

    return {"file_name": file_name, "path": str(zip_path), "manifest": manifest, "size_bytes": zip_path.stat().st_size}


def read_manifest(zip_path: str | os.PathLike[str]) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        if "backup_manifest.json" not in zf.namelist():
            return {}
        return json.loads(zf.read("backup_manifest.json").decode("utf-8"))


def list_backups(backup_folder: str | os.PathLike[str]) -> list[dict[str, Any]]:
    folder = Path(backup_folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        manifest = {}
        try:
            manifest = read_manifest(path)
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
            manifest = {}
        created_at = manifest.get("backup_created_at") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        rows.append({
            "file_name": path.name,
            "created_at": created_at,
            "size_bytes": path.stat().st_size,
            "build_label": manifest.get("build_label", ""),
            "employee_count": manifest.get("employee_count", 0),
            "dictionary_mapping_count": manifest.get("dictionary_mapping_count", 0),
            "schedule_mapping_count": manifest.get("schedule_mapping_count", 0),
            "download_url": f"/api/v3/backup/download/{path.name}",
        })
    return rows


def validate_backup_zip(zip_path: str | os.PathLike[str], temp_folder: Path) -> Path:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            if "backup_manifest.json" not in names or "ifms_data.db" not in names:
                raise ValueError("Backup ZIP must contain backup_manifest.json and ifms_data.db")
            for info in zf.infolist():
                name = Path(info.filename)
                if info.filename.startswith("/") or ".." in name.parts or len(name.parts) > 1:
                    if info.filename != "ifms_data.db" and info.filename != "backup_manifest.json":
                        raise ValueError("Backup ZIP contains unsafe paths")
            db_target = temp_folder / "ifms_data.db"
            with zf.open("ifms_data.db") as source, db_target.open("wb") as dest:
                shutil.copyfileobj(source, dest)
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid backup ZIP") from exc
    db = sqlite3.connect(db_target)
    try:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValueError("Backup database integrity check failed")
    finally:
        db.close()
    return db_target


def restore_full_backup(
    current_db_path: str | os.PathLike[str],
    backup_zip_path: str | os.PathLike[str],
    backup_folder: str | os.PathLike[str],
    app_name: str,
    build_label: str,
) -> dict[str, Any]:
    old_counts = database_counts(current_db_path)
    pre = create_full_backup(current_db_path, backup_folder, app_name, build_label, prefix="IFMS_PreRestore_Backup")
    with tempfile.TemporaryDirectory() as tmp:
        staged_db = validate_backup_zip(backup_zip_path, Path(tmp))
        new_counts = database_counts(staged_db)
        shutil.copy2(staged_db, current_db_path)
    return {
        "restored_from": Path(backup_zip_path).name,
        "pre_restore_backup_created": pre["file_name"],
        "restored_at": datetime.now().isoformat(timespec="seconds"),
        "old_employee_count": old_counts["employee_count"],
        "new_employee_count": new_counts["employee_count"],
        "old_dictionary_count": old_counts["dictionary_mapping_count"],
        "new_dictionary_count": new_counts["dictionary_mapping_count"],
        "old_schedule_mapping_count": old_counts["schedule_mapping_count"],
        "new_schedule_mapping_count": new_counts["schedule_mapping_count"],
    }


def export_dictionary_payload(db: sqlite3.Connection, build_label: str) -> dict[str, Any]:
    return {
        "metadata": {"build_label": build_label, "exported_at": datetime.now().isoformat(timespec="seconds")},
        "dictionary_mappings": table_rows(db, "dictionary_mappings_v3"),
    }


def import_dictionary_payload(db: sqlite3.Connection, payload: dict[str, Any], replace: bool = False) -> dict[str, int]:
    rows = payload.get("dictionary_mappings") if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, list):
        rows = payload
    rows = rows or []
    if replace:
        db.execute("DELETE FROM dictionary_mappings_v3")
    imported = skipped = updated = 0
    for row in rows:
        category = row.get("category") or row.get("dictionary_type") or "designation"
        raw_text = row.get("raw_text") or row.get("raw_value") or ""
        raw_text_key = row.get("raw_text_key") or row.get("raw_designation_key") or ""
        final_text = row.get("final_text") or row.get("final_text_en") or row.get("normalized_value") or ""
        match_type = row.get("match_type") or "exact"
        active = int(row.get("active", 1) or 0)
        existing = db.execute("""
            SELECT id FROM dictionary_mappings_v3
            WHERE category=? AND COALESCE(raw_text_key,'')=? AND COALESCE(final_text,'')=?
              AND COALESCE(match_type,'exact')=? AND COALESCE(active,1)=?
        """, (category, raw_text_key, final_text, match_type, active)).fetchone()
        if existing:
            skipped += 1
            continue
        db.execute("""
            INSERT INTO dictionary_mappings_v3 (
                category, raw_text, raw_text_key, final_text, final_text_en, final_text_hi,
                match_type, priority, active, created_by, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            category, raw_text, raw_text_key, final_text, row.get("final_text_en") or final_text,
            row.get("final_text_hi") or "", match_type, int(row.get("priority", 100) or 0),
            active, row.get("created_by") or "backup_import", row.get("notes") or "",
        ))
        imported += 1
    return {"imported_count": imported, "skipped_duplicate_count": skipped, "updated_count": updated}


def export_schedule_mapping_payload(db: sqlite3.Connection, build_label: str) -> dict[str, Any]:
    return {
        "metadata": {"build_label": build_label, "exported_at": datetime.now().isoformat(timespec="seconds")},
        "schedule_component_mappings": table_rows(db, "schedule_component_mappings_v3"),
    }


def import_schedule_mapping_payload(db: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, int]:
    rows = payload.get("schedule_component_mappings") if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, list):
        rows = payload
    rows = rows or []
    imported = skipped = updated = 0
    for row in rows:
        component_head = str(row.get("component_head") or "").strip()
        schedule_type = str(row.get("schedule_type") or "other_components").strip()
        if not component_head:
            skipped += 1
            continue
        existing = db.execute("""
            SELECT id FROM schedule_component_mappings_v3
            WHERE component_head=? AND schedule_type=?
            ORDER BY id DESC LIMIT 1
        """, (component_head, schedule_type)).fetchone()
        values = (
            row.get("label") or component_head.replace("_", " ").title(),
            int(row.get("active", 1) or 0),
            int(row.get("ignored", 0) or 0),
            row.get("notes") or "",
        )
        if existing:
            db.execute("""
                UPDATE schedule_component_mappings_v3
                SET label=?, active=?, ignored=?, notes=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (*values, existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]))
            updated += 1
        else:
            db.execute("""
                INSERT INTO schedule_component_mappings_v3 (
                    component_head, schedule_type, label, active, ignored, notes, updated_at
                ) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """, (component_head, schedule_type, *values))
            imported += 1
    return {"imported_count": imported, "skipped_duplicate_count": skipped, "updated_count": updated}
