import io
from openpyxl import Workbook
from test_suite_workflow import client


def test_excel_statement_can_be_checked_and_recalculated_with_rate_library(client):
    w = Workbook()
    s = w.active
    s.title = "Arrear"
    s.append(
        [
            "Sr",
            "Month",
            "Pay Due",
            "",
            "",
            "",
            "Pay Drawn",
            "",
            "",
            "",
            "Pay Difference",
            "",
            "",
            "",
        ]
    )
    s.append(
        [
            "",
            "",
            "Basic",
            "DA",
            "HRA",
            "Total",
            "Basic",
            "DA",
            "HRA",
            "Total",
            "Basic",
            "DA",
            "HRA",
            "Total",
        ]
    )
    s.append(
        [
            1,
            "Jan-2025",
            50000,
            27000,
            10000,
            87000,
            50000,
            26500,
            10000,
            86500,
            0,
            500,
            0,
            500,
        ]
    )
    b = io.BytesIO()
    w.save(b)
    b.seek(0)
    r = client.post(
        "/suite/api/imports", data={"kind": "due_drawn", "file": (b, "statement.xlsx")}
    )
    assert r.status_code == 201
    assert len(r.json["payload"]["statement_rows"]) == 1
    id = r.json["id"]
    client.post(
        "/suite/api/rates",
        json=dict(
            allowance="DA", effective_from="2025-01-01", rate="55", reference="Order"
        ),
    )
    q = client.post(
        "/suite/api/statement_claim",
        json=dict(
            import_id=id,
            employee_code="RJ1",
            allowance="DA",
            source_sheet="Arrear",
            method="rates",
            reviewed=True,
            rows=r.json["payload"]["statement_rows"],
        ),
    )
    assert q.status_code == 201
    assert q.json["calculation"]["total"] == "1000.00"
    assert q.json["calculation"]["rows"][0]["due"] == "27500.00"


def test_statement_claim_rejects_unrepresented_source_heads(client):
    import json
    from ifms_suite.storage import database

    original = {
        "month": "2025-01",
        "source_row": 3,
        "source_sheet": "Arrear",
        "due": {"Basic": "50000", "DA": "27000", "HRA": "10000", "HDA": "1000"},
        "drawn": {"Basic": "50000", "DA": "26500", "HRA": "10000", "HDA": "900"},
    }
    with client.application.app_context(), database() as db:
        source_id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            (
                "extra-head-source",
                "synthetic.xlsx",
                json.dumps({"statement_rows": [original]}),
            ),
        ).lastrowid
    reviewed = dict(
        original,
        due={"Basic": "50000", "DA": "27000", "HRA": "10000"},
        drawn={"Basic": "50000", "DA": "26500", "HRA": "10000"},
    )
    response = client.post(
        "/suite/api/statement_claim",
        json=dict(
            import_id=source_id,
            employee_code="SYNTHETIC",
            allowance="DA",
            method="uploaded",
            reviewed=True,
            source_sheet="Arrear",
            rows=[reviewed],
        ),
    )
    assert response.status_code == 400
    assert "HDA" in response.json["error"]


def test_statement_claim_rejects_unresolved_unselected_component(client):
    import json
    from ifms_suite.storage import database

    row = {
        "month": "2025-01",
        "due": {"Basic": "50000", "DA": "27000", "HRA": None},
        "drawn": {"Basic": "50000", "DA": "26500", "HRA": "10000"},
    }
    with client.application.app_context(), database() as db:
        source_id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            (
                "missing-head-source",
                "synthetic.xlsx",
                json.dumps({"statement_rows": [row]}),
            ),
        ).lastrowid
    response = client.post(
        "/suite/api/statement_claim",
        json=dict(
            import_id=source_id,
            employee_code="SYNTHETIC",
            allowance="DA",
            method="uploaded",
            reviewed=True,
            rows=[row],
        ),
    )
    assert response.status_code == 400
    assert "HRA" in response.json["error"]


def test_statement_claim_rejects_unresolved_printed_total(client):
    import json
    from ifms_suite.storage import database

    row = {
        "month": "2025-01",
        "due": {"Basic": "50000", "DA": "27000", "HRA": "10000"},
        "drawn": {"Basic": "50000", "DA": "26500", "HRA": "10000"},
        "printed_due": None,
        "printed_drawn": "86500",
    }
    with client.application.app_context(), database() as db:
        source_id = db.execute(
            "INSERT INTO suite_imports(sha256,filename,payload) VALUES(?,?,?)",
            (
                "missing-total-source",
                "synthetic.xlsx",
                json.dumps({"statement_rows": [row]}),
            ),
        ).lastrowid
    response = client.post(
        "/suite/api/statement_claim",
        json=dict(
            import_id=source_id,
            employee_code="SYNTHETIC",
            allowance="DA",
            method="uploaded",
            reviewed=True,
            rows=[row],
        ),
    )
    assert response.status_code == 400
    assert "total" in response.json["error"].lower()
