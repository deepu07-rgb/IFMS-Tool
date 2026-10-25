import os
import sqlite3
import pytest

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema

pytestmark = pytest.mark.v2


PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_fixtures", "ifms_inner_sheets")


def _run_v2_for_pdf(tmp_path, pdf_name: str):
    db_path = tmp_path / f"{pdf_name}.db"
    app.config["DATABASE"] = str(db_path)
    init_db()
    init_v2_schema(app.config["DATABASE"])

    fpath = os.path.join(PDF_DIR, pdf_name)
    process_file_v2(fpath, pdf_name, dict(app.config))

    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    return db


def test_ap_police_line_swap_case_is_flagged_or_consistent(tmp_path):
    db = _run_v2_for_pdf(tmp_path, "5.pdf")  # AP-Police Line
    rows = db.execute(
        """
        SELECT e.id, e.gross_amount, e.sum_deduction, e.net_total
        FROM employees_v2 e
        WHERE e.gross_amount > 0 AND e.sum_deduction > 0 AND e.net_total > 0
        """
    ).fetchall()
    assert rows, "No employee rows parsed for AP-Police Line"

    unresolved_swaps = 0
    for r in rows:
        gross = float(r["gross_amount"])
        ded = float(r["sum_deduction"])
        net = float(r["net_total"])
        # Swap signature
        if abs((gross - ded) - net) > 1 and abs((gross - net) - ded) <= 1:
            issue = db.execute(
                """
                SELECT COUNT(*) FROM validation_issues_v2
                WHERE employee_id = ? AND issue_type = 'SUSPECTED_DEDUCTION_NET_SWAP'
                """,
                (r["id"],),
            ).fetchone()[0]
            if issue == 0:
                unresolved_swaps += 1

    db.close()

    # Must not silently pass swapped rows.
    assert unresolved_swaps == 0


def test_footer_contamination_not_stored_as_employee_totals_tp_cpf_and_commissionerate(tmp_path):
    for pdf_name in ["8.pdf", "10.pdf"]:  # TP CPF BILL, COMMISSIONERATE JDR
        db = _run_v2_for_pdf(tmp_path, pdf_name)
        bill = db.execute(
            """
            SELECT id, official_gross, official_deduction, official_net
            FROM bills_v2
            WHERE source_filename = ?
            ORDER BY id DESC LIMIT 1
            """,
            (pdf_name,),
        ).fetchone()
        assert bill is not None
        assert bill["official_gross"] > 0
        assert bill["official_deduction"] > 0
        assert bill["official_net"] > 0

        # Footer contamination signature: an employee row equal to full bill summary totals.
        contaminated = db.execute(
            """
            SELECT COUNT(*) FROM employees_v2
            WHERE bill_id = ?
              AND ABS(gross_amount - ?) <= 1
              AND ABS(sum_deduction - ?) <= 1
              AND ABS(net_total - ?) <= 1
            """,
            (bill["id"], bill["official_gross"], bill["official_deduction"], bill["official_net"]),
        ).fetchone()[0]
        assert contaminated == 0, f"Detected footer-total contamination in {pdf_name}"

        # For parsed rows with all totals, arithmetic should be valid or explicitly flagged.
        bad_without_issue = db.execute(
            """
            SELECT COUNT(*) FROM employees_v2 e
            WHERE e.bill_id = ?
              AND e.gross_amount > 0 AND e.sum_deduction > 0 AND e.net_total > 0
              AND ABS((e.gross_amount - e.sum_deduction) - e.net_total) > 1
                  AND NOT EXISTS (
                    SELECT 1 FROM validation_issues_v2 v
                    WHERE v.employee_id = e.id
                      AND v.issue_type IN (
                        'SUSPECTED_DEDUCTION_NET_SWAP',
                        'PRINTED_TOTAL_MISMATCH',
                        'COMPONENT_EXTRACTION_MISMATCH'
                      )
                  )
            """,
            (bill["id"],),
        ).fetchone()[0]
        assert bad_without_issue == 0
        db.close()
