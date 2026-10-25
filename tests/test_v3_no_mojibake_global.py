from pathlib import Path

from app import app, format_currency


FORBIDDEN_SEQUENCES = (
    "\u00c3\u00b0\u00c5\u00b8",
    "\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00b9",
    "\u00c3\u00a0\u00e2\u20ac\u0161\u00c2\u00b9",
    "\u00c3\u00a2\u00c5\u201c",
    "\u00c3\u00a2\u00e2\u201a\u00ac",
    "\u00c3\u0192",
    "\u00c3\u201a",
    "\u00c3\u00af\u00c2\u00b8",
    "\u00c3\u00a2\u00c5\u00a1",
    "\u00c3\u0192\u00c2\u00a2",
    "\u00c3\u0192\u00c2\u00b0",
    "\ufffd",
)

SERVED_SOURCE_FILES = (
    Path("templates/index.html"),
    Path("app.py"),
)

NAV_LABELS = (
    "Upload PDFs",
    "Dashboard",
    "Employee Data",
    "Schedules",
    "Group Summary",
    "Exception Center",
    "Dictionary",
)


def _assert_no_mojibake(text):
    for bad in FORBIDDEN_SEQUENCES:
        assert bad not in text


def test_user_facing_source_files_do_not_contain_forbidden_mojibake():
    for path in SERVED_SOURCE_FILES:
        _assert_no_mojibake(path.read_text(encoding="utf-8"))


def test_served_html_version_and_labels_are_clean():
    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html; charset=utf-8" in response.content_type

    html = response.get_data(as_text=True)
    _assert_no_mojibake(html)
    for label in NAV_LABELS:
        assert label in html
    assert "Build: Phase3-Full-Stable" in html
    assert "Clear All Data</button>" in html
    assert "Refresh</button>" in html
    assert "PDF Verified" in html
    assert "Rs. " in html


def test_api_version_reports_phase3_full_stable():
    response = app.test_client().get("/api/version")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["app_name"] == "IFMS Report Analyzer"
    assert payload["build_label"] == "Phase3-Full-Stable"
    assert payload["python_file_path"].endswith("app.py")
    assert payload["template_mtime"]
    assert payload["port"] == "5000"


def test_stats_endpoint_and_currency_helper_are_ascii_safe():
    response = app.test_client().get("/api/stats")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    _assert_no_mojibake(text)
    assert "\u20b9" not in text

    assert format_currency(123456) == "Rs. 1,23,456"
    assert "\u20b9" not in format_currency(123456)
