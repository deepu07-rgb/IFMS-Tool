import re

from app import BUILD_LABEL, app


BAD_SEQUENCES = (
    "\u00c3\u00b0\u00c5\u00b8",
    "\u00c3\u00a2\u00e2\u20ac\u0161\u00c2\u00b9",
    "\u00c3\u00a0\u00e2\u20ac\u0161\u00c2\u00b9",
    "\u00c3\u00a2\u00c5\u201c",
    "\u00c3\u00a2\u00e2\u201a\u00ac",
    "\u00c3\u0192",
    "\u00c3\u201a",
    "\ufffd",
)


def _clean(text):
    for bad in BAD_SEQUENCES:
        assert bad not in text


def test_ui_polish_footer_version_and_actions():
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    _clean(html)

    assert "Designed and Developed by Neeraj Purohit, Senior Assistant, Rajasthan Police" in html
    footer = re.search(r"<footer class=\"app-footer\">(?P<footer>.*?)</footer>", html, re.S).group("footer")
    assert f"Build: {BUILD_LABEL}" not in footer
    assert "Version</button>" in html
    assert "Build: {{ build_label }}" not in html
    assert f"Build: {BUILD_LABEL}" in html

    version = client.get("/api/version")
    assert version.status_code == 200
    assert version.get_json()["build_label"] == BUILD_LABEL

    assert 'class="action-cell"' in html
    assert 'onclick="showEmployeeEditModal(${e.id})">Edit</button>' in html
    assert 'onclick="showSourceModal(${e.id})">View Source</button>' in html
    assert "Delete Row</button>" in html


def test_numeric_employee_cells_do_not_have_hover_titles():
    html = app.test_client().get("/").get_data(as_text=True)
    numeric_columns = (
        "basic",
        "da",
        "hra",
        "gross",
        "itax",
        "gpf",
        "gpf_2004",
        "lic",
        "sip",
        "sil",
        "rghs",
        "rop",
        "roadways",
        "deduction",
        "net",
    )
    for col in numeric_columns:
        pattern = rf'<td data-col="{re.escape(col)}"[^>]*title='
        assert not re.search(pattern, html)

    assert 'data-col="designation" title=' in html
    assert 'data-col="issues" title=' in html
