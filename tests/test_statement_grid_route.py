import io
import pymupdf
from test_suite_workflow import client


def test_grid_endpoint_validates_original_page_without_reading_outside_source(client):
    doc = pymupdf.open()
    doc.new_page()
    ident = client.post(
        "/suite/api/imports",
        data={
            "kind": "due_drawn",
            "file": (io.BytesIO(doc.tobytes()), "statement.pdf"),
        },
    ).json["id"]
    r = client.post(f"/suite/api/imports/{ident}/statement_grid", json={"page": 999})
    assert r.status_code == 400
    assert "page" in r.json["error"].lower()
