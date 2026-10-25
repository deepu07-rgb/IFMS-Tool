import sqlite3

from app import app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema


BAD_MOJIBAKE = (
    "\u00c3\u00b0\u00c5\u00b8",
    "\u00c3\u00a2",
    "\u00c3\u0192",
    "\ufffd",
)


def test_backup_restore_ui_and_smoke_status_are_clean(tmp_path):
    db_path = tmp_path / "backup_ui.db"
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
    init_schedule_mapping_schema(db)
    db.commit()
    db.close()

    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for label in (
        "Backup & Restore",
        "Create Full Backup",
        "Restore Full Backup",
        "Export Dictionary Only",
        "Import Dictionary Only",
        "Export Schedule Mappings Only",
        "Import Schedule Mappings Only",
    ):
        assert label in html
    for bad in BAD_MOJIBAKE:
        assert bad not in html

    smoke = client.get("/api/v3/smoke_status")
    assert smoke.status_code == 200
    assert smoke.get_json()["db_ok"] is True
