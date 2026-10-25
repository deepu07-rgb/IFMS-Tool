import os
import sqlite3
import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema

pytestmark = pytest.mark.v2


def test_v2_khandafalsa_pdf1_pipeline(tmp_path):
    pdf_path = os.path.join("test_fixtures", "ifms_inner_sheets", "1.pdf")
    assert os.path.exists(pdf_path)

    db_path = tmp_path / "khandafalsa_pdf1.db"
    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])

    process_file_v2(pdf_path, "1.pdf", dict(app.config))

    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    bill = db.execute(
        """
        SELECT group_name, parsed_gross, parsed_deduction, parsed_net,
               official_gross, official_deduction, official_net
        FROM bills_v2
        WHERE source_filename = '1.pdf'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    count = db.execute(
        "SELECT COUNT(*) FROM employees_v2 WHERE source_filename = '1.pdf'"
    ).fetchone()[0]
    db.close()

    assert bill is not None
    assert bill["group_name"] == "Khandafalsa"
    assert count == 36
    assert round(bill["parsed_gross"]) == 2707921
    assert round(bill["parsed_deduction"]) == 572559
    assert round(bill["parsed_net"]) == 2135362
    assert round(bill["official_gross"]) == 2707921
    assert round(bill["official_deduction"]) == 572559
    assert round(bill["official_net"]) == 2135362
