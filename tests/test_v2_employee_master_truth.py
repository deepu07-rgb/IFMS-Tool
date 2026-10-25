import os

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2


def _setup_pdf1_pdf2(tmp_path):
    db_path = tmp_path / "employee_master_truth.db"
    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    for pdf_name in ("1.pdf", "2.pdf"):
        pdf_path = os.path.join("test_fixtures", "ifms_inner_sheets", pdf_name)
        assert os.path.exists(pdf_path)
        process_file_v2(pdf_path, pdf_name, dict(app.config))
    return app.test_client()


def _employee(client, source_file, sr_no):
    response = client.get("/api/employees?page=1&per_page=200")
    assert response.status_code == 200
    matches = [
        row for row in response.get_json()["employees"]
        if row["source_file"] == source_file and row["sr_no"] == sr_no
    ]
    assert len(matches) == 1
    return matches[0]


def _assert_fields(row, expected):
    for key, value in expected.items():
        assert row[key] == value, f"{row['source_file']} sr={row['sr_no']} {key}: {row[key]} != {value}"


def test_pdf1_khandafalsa_employee_master_known_rows(tmp_path):
    client = _setup_pdf1_pdf2(tmp_path)

    row1 = _employee(client, "1.pdf", 1)
    _assert_fields(row1, {
        "employee_name": "PUKHA RAJ",
        "employee_id": "RJPA200829046706",
        "pan": "BAXPR9054H",
        "pay_scale": "L8",
        "normalized_designation": "Constable",
        "basic": 35300.0,
        "da": 21180.0,
        "hra": 7060.0,
        "cca": 620.0,
        "hda": 4707.0,
        "mess_allowance": 2850.0,
        "fta": 500.0,
        "lic": 1697.0,
        "gpf_2004": 2100.0,
        "rghs": 658.0,
        "sip": 5000.0,
        "roadways_deduction": 200.0,
        "printed_gross": 72217.0,
        "printed_deduction": 9455.0,
        "printed_net": 62762.0,
    })

    row4 = _employee(client, "1.pdf", 4)
    _assert_fields(row4, {
        "employee_name": "GOVIND RAM",
        "employee_id": "RJJO198424017330",
        "pan": "AKWPR9290B",
        "pay_scale": "L11",
        "normalized_designation": "Assistant Sub-Inspector",
        "basic": 55500.0,
        "da": 33300.0,
        "hra": 11100.0,
        "income_tax": 5000.0,
        "gpf": 10000.0,
        "lic": 4494.0,
        "sip": 3000.0,
        "rghs": 875.0,
        "printed_gross": 111520.0,
        "printed_deduction": 23369.0,
        "printed_net": 88151.0,
    })


def test_pdf2_cp_pl_first_employee_master_known_rows(tmp_path):
    client = _setup_pdf1_pdf2(tmp_path)

    row3 = _employee(client, "2.pdf", 3)
    _assert_fields(row3, {
        "employee_name": "VIRENDRA VIKRAM SINGH",
        "employee_id": "RJJO198924005207",
        "pan": "ALRPB6128N",
        "pay_scale": "L11",
        "normalized_designation": "Head Constable",
        "basic": 55500.0,
        "da": 33300.0,
        "hra": 11100.0,
        "rop": -4607.0,
        "income_tax": 5000.0,
        "gpf": 7500.0,
        "sip": 3000.0,
        "roadways_deduction": 200.0,
        "printed_gross": 106163.0,
        "printed_deduction": 16375.0,
        "printed_net": 89788.0,
    })

    row4 = _employee(client, "2.pdf", 4)
    _assert_fields(row4, {
        "employee_name": "AIDAN RAM",
        "employee_id": "RJJO199224022180",
        "pan": "AJXPC7567Q",
        "pay_scale": "L11",
        "normalized_designation": "Head Constable",
        "basic": 52300.0,
        "da": 31380.0,
        "hra": 10460.0,
        "lic": 6021.0,
        "gpf": 10000.0,
        "sip": 3000.0,
        "rghs": 658.0,
        "printed_gross": 104583.0,
        "printed_deduction": 19679.0,
        "printed_net": 84904.0,
    })
