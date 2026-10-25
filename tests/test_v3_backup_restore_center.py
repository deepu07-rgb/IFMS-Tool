import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

from app import app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema


def _setup(tmp_path):
    db_path = tmp_path / "backup_center.db"
    backup_dir = tmp_path / "backups"
    export_dir = tmp_path / "exports"
    backup_dir.mkdir()
    export_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["BACKUP_FOLDER"] = str(backup_dir)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    init_db()
    init_v2_schema(app.config["DATABASE"])
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    init_schedule_mapping_schema(db)
    bill_id = db.execute(
        "INSERT INTO bills_v2 (source_filename, group_name, month_year, bill_no) VALUES (?,?,?,?)",
        ("backup.pdf", "Backup Group", "May / 2026", "B1"),
    ).lastrowid
    db.execute(
        """
        INSERT INTO employees_v2 (
            bill_id, source_filename, sr_no, group_name, month_year, raw_name, employee_id,
            final_designation, employee_data_status, gross_amount, sum_deduction, net_total
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (bill_id, "backup.pdf", 1, "Backup Group", "May / 2026", "Backup Employee", "E1", "CONSTABLE", "VERIFIED", 1000, 100, 900),
    )
    db.execute(
        """
        INSERT INTO dictionary_mappings_v3 (
            category, raw_text, raw_text_key, final_text, final_text_en, match_type, priority, active
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        ("designation", "CONSTABLE", "CONSTABLE", "CONSTABLE", "CONSTABLE", "exact", 100, 1),
    )
    db.execute(
        """
        INSERT INTO schedule_component_mappings_v3 (
            component_head, schedule_type, label, active, ignored, notes
        ) VALUES (?,?,?,?,?,?)
        """,
        ("backup_component", "other_components", "Backup Component", 1, 0, "seed"),
    )
    db.execute(
        "INSERT INTO edit_audit_log_v3 (action_type, table_name, field_name) VALUES (?,?,?)",
        ("SEED", "tests", "backup"),
    )
    db.commit()
    db.close()
    return app.test_client(), db_path, backup_dir


def _count(db_path, table):
    db = sqlite3.connect(db_path)
    try:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        db.close()


def test_backup_restore_center_full_backup_restore_and_import_export(tmp_path):
    parser_before = Path("parser.py").read_bytes()
    client, db_path, backup_dir = _setup(tmp_path)

    create = client.post("/api/v3/backup/create")
    assert create.status_code == 200
    backup_name = create.get_json()["backup"]["file_name"]
    backup_path = backup_dir / backup_name
    assert backup_path.exists()
    with zipfile.ZipFile(backup_path) as zf:
        names = set(zf.namelist())
        assert {
            "ifms_data.db",
            "dictionary_mappings.json",
            "schedule_component_mappings.json",
            "audit_log.json",
            "app_settings.json",
            "backup_manifest.json",
        }.issubset(names)
        manifest = json.loads(zf.read("backup_manifest.json").decode("utf-8"))
    assert manifest["employee_count"] == 1
    assert manifest["dictionary_mapping_count"] == 1
    assert manifest["build_label"] == "Phase3-Full-Stable"

    listed = client.get("/api/v3/backup/list")
    assert listed.status_code == 200
    assert backup_name in {row["file_name"] for row in listed.get_json()["backups"]}

    download = client.get(f"/api/v3/backup/download/{backup_name}")
    assert download.status_code == 200
    assert zipfile.is_zipfile(io.BytesIO(download.data))

    delete = client.post("/api/v3/backup/delete", json={"file_name": backup_name})
    assert delete.status_code == 200
    assert not backup_path.exists()

    restore_backup = client.post("/api/v3/backup/create").get_json()["backup"]["file_name"]
    db = sqlite3.connect(db_path)
    db.execute("DELETE FROM employees_v2")
    db.commit()
    db.close()
    assert _count(db_path, "employees_v2") == 0

    restore = client.post("/api/v3/backup/restore", json={"file_name": restore_backup, "confirmation": True})
    assert restore.status_code == 200
    summary = restore.get_json()["restore_summary"]
    assert summary["pre_restore_backup_created"].startswith("IFMS_PreRestore_Backup_")
    assert summary["old_employee_count"] == 0
    assert summary["new_employee_count"] == 1
    assert _count(db_path, "employees_v2") == 1
    assert list(backup_dir.glob("IFMS_PreRestore_Backup_*.zip"))

    invalid_zip = io.BytesIO(b"not a zip")
    rejected = client.post(
        "/api/v3/backup/restore",
        data={"confirmation": "true", "file": (invalid_zip, "bad.zip")},
        content_type="multipart/form-data",
    )
    assert rejected.status_code == 400

    traversal = client.post("/api/v3/backup/restore", json={"file_name": "../bad.zip", "confirmation": True})
    assert traversal.status_code == 400

    dictionary_export = client.get("/api/v3/backup/export_dictionary")
    assert dictionary_export.status_code == 200
    dictionary_payload = json.loads(dictionary_export.data.decode("utf-8"))
    first_import = client.post("/api/v3/backup/import_dictionary", json={"payload": dictionary_payload})
    second_import = client.post("/api/v3/backup/import_dictionary", json={"payload": dictionary_payload})
    assert first_import.status_code == 200
    assert second_import.status_code == 200
    assert second_import.get_json()["skipped_duplicate_count"] >= 1
    assert _count(db_path, "dictionary_mappings_v3") == 1

    schedule_export = client.get("/api/v3/backup/export_schedule_mappings")
    assert schedule_export.status_code == 200
    schedule_payload = json.loads(schedule_export.data.decode("utf-8"))
    schedule_import = client.post("/api/v3/backup/import_schedule_mappings", json={"payload": schedule_payload})
    assert schedule_import.status_code == 200
    assert schedule_import.get_json()["updated_count"] >= 1
    assert _count(db_path, "schedule_component_mappings_v3") == 1

    for response in (create, listed, delete, restore, first_import, second_import, schedule_import):
        assert response.is_json
    assert Path("parser.py").read_bytes() == parser_before
