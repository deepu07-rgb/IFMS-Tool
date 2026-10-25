from pathlib import Path

from app import app


BAD_SEQUENCES = (
    "\u00c3\u00b0\u00c5\u00b8",  # mojibake fragment for emoji prefix
    "\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00b9",  # mojibake rupee
    "\u00c3\u00a2\u00c5\u201c",  # mojibake check/cross prefix
    "\u00c3\u00a2\u00e2\u201a\u00ac",  # mojibake punctuation prefix
    "\u00c3\u0192",
    "\u00c3\u201a",
    "\u00c3",
    "\u00c2",
    "\u00e2",
)

TAB_LABELS = (
    "Upload PDFs",
    "Dashboard",
    "Employee Data",
    "Schedules",
    "Group Summary",
    "Exception Center",
    "Dictionary",
)


def _assert_clean(text):
    for bad in BAD_SEQUENCES:
        assert bad not in text


def test_template_ui_encoding_cleanliness():
    html = Path("templates/index.html").read_text(encoding="utf-8")

    assert "<head>\n<meta charset=\"UTF-8\">" in html
    _assert_clean(html)
    for label in TAB_LABELS:
        assert f">{label}</div>" in html
    assert "Clear All Data</button>" in html
    assert "const money = n => 'Rs. ' + fmt(n);" in html
    assert "Export Filtered Employee Data" in html
    assert "Add Filter Condition" in html
    assert "No matching records found." in html


def test_rendered_html_encoding_cleanliness():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html; charset=utf-8")

    html = response.get_data(as_text=True)
    _assert_clean(html)
    for label in TAB_LABELS:
        assert f">{label}</div>" in html
    assert "Clear All Data</button>" in html
    assert "Rs. " in html
