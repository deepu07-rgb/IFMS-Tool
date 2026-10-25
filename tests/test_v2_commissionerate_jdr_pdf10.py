import os
import sqlite3

import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema


pytestmark = pytest.mark.v2


def test_v2_commissionerate_jdr_pdf10_net_totals(tmp_path):
    pdf_path = os.path.join("test_fixtures", "ifms_inner_sheets", "10.pdf")
    assert os.path.exists(pdf_path)

    db_path = tmp_path / "commissionerate_jdr_pdf10.db"
    app.config["DATABASE"] = str(db_path)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])

    process_file_v2(pdf_path, "10.pdf", dict(app.config))

    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    bill = db.execute(
        """
        SELECT group_name, parsed_gross, parsed_deduction, parsed_net,
               official_gross, official_deduction, official_net,
               verification_status
        FROM bills_v2
        WHERE source_filename = '10.pdf'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    employees = db.execute(
        """
        SELECT id, page_no, sr_no, raw_name, gross_amount, sum_deduction, net_total
        FROM employees_v2
        WHERE source_filename = '10.pdf'
        ORDER BY sr_no
        """
    ).fetchall()
    mismatch_rows = db.execute(
        """
        SELECT e.sr_no, e.raw_name, e.gross_amount, e.sum_deduction, e.net_total,
               COALESCE((
                 SELECT v.issue_type
                 FROM validation_issues_v2 v
                 WHERE v.employee_id = e.id
                   AND COALESCE(v.status, 'OPEN') != 'RESOLVED'
                 ORDER BY v.id
                 LIMIT 1
               ), '') AS issue_type
        FROM employees_v2 e
        WHERE e.source_filename = '10.pdf'
          AND ABS((e.gross_amount - e.sum_deduction) - e.net_total) > 1
        """
    ).fetchall()
    fallback_issue = db.execute(
        """
        SELECT COUNT(*)
        FROM validation_issues_v2 v
        JOIN employees_v2 e ON e.id = v.employee_id
        WHERE e.source_filename = '10.pdf'
          AND e.sr_no = 5
          AND v.issue_type = 'NET_TOTAL_COLUMN_OVERLAP_FALLBACK'
        """
    ).fetchone()[0]
    row5 = db.execute(
        """
        SELECT page_no, sr_no, raw_name, gross_amount, sum_deduction, net_total
        FROM employees_v2
        WHERE source_filename = '10.pdf' AND sr_no = 5
        """
    ).fetchone()
    db.close()

    assert bill is not None
    assert bill["group_name"] == "COMMISSIONERATE JDR"
    assert len(employees) == 5
    assert round(bill["parsed_gross"]) == 872640
    assert round(bill["parsed_deduction"]) == 226031
    assert round(bill["parsed_net"]) == 646609
    assert round(bill["official_gross"]) == 872640
    assert round(bill["official_deduction"]) == 226031
    assert round(bill["official_net"]) == 646609
    assert bill["verification_status"] == "VERIFIED"

    assert row5["page_no"] == 2
    assert row5["raw_name"] == "MANISH KUMAR CHOUDHARY"
    assert round(row5["gross_amount"]) == 114880
    assert round(row5["sum_deduction"]) == 14122
    assert round(row5["net_total"]) == 100758
    assert fallback_issue == 1

    assert not mismatch_rows, [
        {
            "sr_no": r["sr_no"],
            "name": r["raw_name"],
            "gross": r["gross_amount"],
            "deduction": r["sum_deduction"],
            "net": r["net_total"],
            "issue_type": r["issue_type"],
        }
        for r in mismatch_rows
    ]
