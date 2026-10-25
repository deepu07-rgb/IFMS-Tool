import json
import subprocess
from pathlib import Path

from app import app


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_api_version_phase3_full_stable():
    with app.test_client() as client:
        response = client.get("/api/version")
    assert response.status_code == 200
    data = response.get_json()
    assert data["app_name"] == "IFMS Report Analyzer"
    assert data["build_label"] == "Phase3-Full-Stable"
    for key in ("started_at", "python_file_path", "template_mtime", "port"):
        assert key in data


def test_health_check_release_payload_and_integrity():
    with app.test_client() as client:
        response = client.get("/api/v3/health_check")
    assert response.status_code == 200
    data = response.get_json()
    assert data["build_label"] == "Phase3-Full-Stable"
    assert data["database_ok"] is True
    assert data["database_integrity"]["ok"] is True
    assert data["overall_status"] in {"HEALTHY", "HEALTHY_WITH_WARNINGS", "NEEDS_REVIEW", "CRITICAL"}
    for key in (
        "employee_count",
        "bill_count",
        "dictionary_count",
        "schedule_type_count",
        "official_schedule_upload_count",
        "monthly_comparison_run_count",
        "master_employee_count",
        "unresolved_issue_count",
        "backup_count",
        "export_file_count",
        "stale_job_count",
        "warning_count",
        "critical_count",
    ):
        assert key in data
    assert data["folder_sizes"]["exports"]["total_size_bytes"] >= 0
    assert data["folder_sizes"]["backups"]["total_size_bytes"] >= 0
    assert data["folder_sizes"]["uploads"]["total_size_bytes"] >= 0
    assert data["required_tables_ok"]["bills_v2"] is True
    assert data["required_tables_ok"]["employees_v2"] is True
    assert data["required_tables_ok"]["employee_components_v2"] is True


def test_ui_action_inventory_includes_major_modules():
    with app.test_client() as client:
        response = client.get("/api/v3/ui_action_inventory")
    assert response.status_code == 200
    sections = response.get_json()["sections"]
    names = {section["section"] for section in sections}
    assert {
        "Upload PDFs",
        "Employee Data",
        "Dictionary",
        "Schedules",
        "Official Schedule Comparison",
        "Monthly Comparison",
        "Master Register",
        "Backup & Restore",
        "Export Center",
    }.issubset(names)
    flattened = [action for section in sections for action in section["actions"]]
    assert all({"action_name", "endpoint", "method", "exists", "notes"}.issubset(action) for action in flattened)
    assert any(action["action_name"] == "master register export" and action["exists"] for action in flattened)


def test_html_release_diagnostics_help_and_no_mojibake():
    with app.test_client() as client:
        html = client.get("/").get_data(as_text=True)
    for label in (
        "Upload PDFs",
        "Dashboard",
        "Employee Data",
        "Schedules",
        "Official Schedule Comparison",
        "Monthly Comparison",
        "Master Register",
        "Backup & Restore",
        "Export Center",
        "System Diagnostics",
        "Help",
        "Help / User Guide",
    ):
        assert label in html
    for bad in ("\u00c3\u00a2", "\u00c3\u0192", "\ufffd"):
        assert bad not in html


def test_release_notes_startup_scripts_smoke_script_and_parser_unchanged():
    release_notes = REPO_ROOT / "docs" / "RELEASE_NOTES_PHASE3.md"
    assert release_notes.exists()
    assert "Phase3-Full-Stable" in release_notes.read_text(encoding="utf-8")

    for script_name in ("start_tool.bat", "start_tool.sh"):
        text = (REPO_ROOT / script_name).read_text(encoding="utf-8")
        assert "Phase3-Full-Stable" in text
        assert "/api/v3/health_check" in text
        assert "/api/version" in text

    smoke_text = (REPO_ROOT / "scripts" / "ui_smoke_check.py").read_text(encoding="utf-8")
    assert "/api/v3/health_check" in smoke_text
    assert "/api/v3/ui_action_inventory" in smoke_text
    assert "test-client fallback mode" in smoke_text

    result = subprocess.run(
        ["git", "diff", "--", "parser.py"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == ""
