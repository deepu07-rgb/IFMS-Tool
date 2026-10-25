import os
import sqlite3

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2


EXPECTED_EMPLOYEES = {
    "PRATEEK SINGH": {
        "employee_id": "RJSK202333557710",
        "pan": "KRFPS7878A",
        "pay_scale": "L10c",
        "basic": 59500,
        "da": 35700,
        "gross_amount": 95200,
        "hfrh": 530,
        "eacpenf": 9520,
        "car_rent": 1000,
        "giais": 120,
        "rghs": 875,
        "sum_deduction": 12045,
        "net_total": 83155,
    },
    "KAMAL SHEKHAWAT": {
        "employee_id": "RJJP199817019766",
        "pan": "ADDPS7562F",
        "pay_scale": "L12c",
        "basic": 170100,
        "da": 102060,
        "gross_amount": 272160,
        "hfrh": 1514,
        "rghs": 875,
        "car_rent": 1000,
        "sip": 7000,
        "sil": 20000,
        "itax": 60000,
        "gpf": 10500,
        "sum_deduction": 100889,
        "net_total": 171271,
    },
    "SHARAT KAVIRAJ IPS": {
        "employee_id": "RJJO200425000075",
        "pan": "ADIPK4447N",
        "pay_scale": "L14c",
        "basic": 172200,
        "da": 103320,
        "gross_amount": 275520,
        "hfrh": 1533,
        "ais_gpf": 25000,
        "itax": 45000,
        "giais": 120,
        "rghs": 875,
        "car_rent": 1000,
        "sum_deduction": 73528,
        "net_total": 201992,
    },
    "SHAHEEN C": {
        "employee_id": "RJJO202024055124",
        "pan": "FCPPS0617R",
        "pay_scale": "L11c",
        "basic": 71800,
        "da": 43080,
        "gross_amount": 114880,
        "hfrh": 639,
        "giais": 120,
        "rghs": 875,
        "car_rent": 1000,
        "sil": 325,
        "eacpenf": 11488,
        "itax": 8000,
        "sip": 3000,
        "sum_deduction": 25447,
        "net_total": 89433,
    },
    "MANISH KUMAR CHOUDHARY": {
        "employee_id": "RJKO202027048204",
        "pan": "ATSPC6818M",
        "pay_scale": "L11c",
        "basic": 71800,
        "da": 43080,
        "gross_amount": 114880,
        "hfrh": 639,
        "eacpenf": 11488,
        "car_rent": 1000,
        "giais": 120,
        "rghs": 875,
        "sum_deduction": 14122,
        "net_total": 100758,
    },
}


def _amount(row, key):
    return round(float(row.get(key) or 0))


def test_v3_pdf10_employee_data_accuracy(tmp_path):
    pdf_path = os.path.join("test_fixtures", "ifms_inner_sheets", "10.pdf")
    assert os.path.exists(pdf_path)

    db_path = tmp_path / "pdf10_employee_data_accuracy.db"
    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(str(db_path))

    process_file_v2(pdf_path, "10.pdf", dict(app.config))
    client = app.test_client()
    response = client.get(
        "/api/employees",
        query_string={"source_file": "10.pdf", "page": 1, "per_page": 20, "sort": "sr_no"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 5
    assert payload["quality"]["bill_totals_matched"] is True
    assert payload["quality"]["employee_row_totals_matched"] == 5

    by_name = {row["name"]: row for row in payload["employees"]}
    assert set(EXPECTED_EMPLOYEES).issubset(by_name)
    for name, expected in EXPECTED_EMPLOYEES.items():
        row = by_name[name]
        assert row["employee_id"] == expected["employee_id"]
        assert row["pan"] == expected["pan"]
        assert row["pay_scale"] == expected["pay_scale"]
        for key, value in expected.items():
            if key in {"employee_id", "pan", "pay_scale"}:
                continue
            assert _amount(row, key) == value, f"{name} {key}"

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    bill = db.execute(
        """
        SELECT group_name, parsed_gross, parsed_deduction, parsed_net,
               official_gross, official_deduction, official_net, verification_status
        FROM bills_v2
        WHERE source_filename = '10.pdf'
        """
    ).fetchone()
    db.close()

    assert bill["group_name"] == "COMMISSIONERATE JDR"
    assert round(bill["parsed_gross"]) == 872640
    assert round(bill["parsed_deduction"]) == 226031
    assert round(bill["parsed_net"]) == 646609
    assert round(bill["official_gross"]) == 872640
    assert round(bill["official_deduction"]) == 226031
    assert round(bill["official_net"]) == 646609
    assert bill["verification_status"] == "VERIFIED"
