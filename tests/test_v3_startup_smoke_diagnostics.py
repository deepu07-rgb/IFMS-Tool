import sqlite3

from app import BUILD_LABEL, app, init_db
from ifms_engine.db import init_v2_schema
from ifms_engine.schedule_engine_v3 import init_schedule_mapping_schema
from scripts import ui_smoke_check


BAD_MOJIBAKE = (
    "\u00c3\u00b0\u00c5\u00b8",
    "\u00c3\u00a2",
    "\u00c3\u0192",
    "\ufffd",
)


def _setup(tmp_path):
    db_path = tmp_path / "startup_smoke.db"
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    app.config["DATABASE"] = str(db_path)
    app.config["EXPORT_FOLDER"] = str(export_dir)
    init_db()
    init_v2_schema(app.config["DATABASE"])
    db = sqlite3.connect(app.config["DATABASE"])
    init_schedule_mapping_schema(db)
    db.commit()
    db.close()
    return app.test_client()


def _assert_clean(text):
    for bad in BAD_MOJIBAKE:
        assert bad not in text


def test_startup_smoke_diagnostics_endpoints_and_script(tmp_path, capsys):
    client = _setup(tmp_path)

    version = client.get("/api/version")
    assert version.status_code == 200
    version_payload = version.get_json()
    assert version_payload["app_name"] == "IFMS Report Analyzer"
    assert version_payload["build_label"] == BUILD_LABEL
    assert version_payload["started_at"]
    assert version_payload["python_file_path"].endswith("app.py")
    assert version_payload["template_mtime"]
    assert version_payload["port"] == "5000"

    smoke = client.get("/api/v3/smoke_status")
    assert smoke.status_code == 200
    smoke_payload = smoke.get_json()
    assert smoke_payload["version_ok"] is True
    assert smoke_payload["db_ok"] is True
    assert smoke_payload["schedule_types_count"] >= 18

    inventory = client.get("/api/v3/ui_action_inventory")
    assert inventory.status_code == 200
    sections = {section["section"]: section["actions"] for section in inventory.get_json()["sections"]}
    assert {"Employee Data", "Dictionary", "Schedules"}.issubset(sections)
    for actions in sections.values():
        assert all(action["endpoint_exists"] for action in actions)

    html_response = client.get("/")
    assert html_response.status_code == 200
    html = html_response.get_data(as_text=True)
    _assert_clean(html)
    assert "Version</button>" in html
    assert "System Diagnostics" in html
    assert "Refresh Diagnostics" in html
    assert "Copy Diagnostics" in html

    assert client.get("/api/v3/schedules/types").status_code == 200
    assert client.get("/api/v3/schedules/reconciliation").status_code == 200
    assert client.get("/api/v3/dictionary").status_code == 200
    assert client.get("/api/employees").status_code == 200

    assert ui_smoke_check.main(["--test-client"]) == 0
    output = capsys.readouterr().out
    assert "PASS" in output
