import json
import os
import sqlite3

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema
from ifms_engine.header_parser import HeaderParser
from ifms_engine.pdf_reader import PDFReader


PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_fixtures", "ifms_inner_sheets")
EXPECTED_FILE = os.path.join(os.path.dirname(__file__), "fixtures", "expected_bill_totals.json")


def _extract_meta(pdf_name: str):
    path = os.path.join(PDF_DIR, pdf_name)
    reader = PDFReader(path)
    words = reader.extract_words()
    meta = HeaderParser.extract_metadata(words)
    reader.close()
    return meta


def test_official_totals_extraction_representative_pdfs():
    # Required representatives:
    # TP CPF BILL -> 8.pdf
    # COMMISSIONERATE JDR -> 10.pdf
    # NEW RT 2025 -> 14.pdf
    sample_files = ["8.pdf", "10.pdf", "14.pdf"]
    with open(EXPECTED_FILE, "r", encoding="utf-8") as f:
        expected = json.load(f)

    for pdf_name in sample_files:
        meta = _extract_meta(pdf_name)
        assert meta["official_gross"] > 0, f"official_gross missing for {pdf_name}"
        assert meta["official_deduction"] > 0, f"official_deduction missing for {pdf_name}"
        assert meta["official_net"] > 0, f"official_net missing for {pdf_name}"
        assert round(meta["official_gross"]) == expected[pdf_name]["gross"]
        assert round(meta["official_deduction"]) == expected[pdf_name]["deduction"]
        assert round(meta["official_net"]) == expected[pdf_name]["net"]


def test_official_totals_aggregate_14_pdfs_if_available():
    pdfs = sorted([f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf")])
    if len(pdfs) < 14:
        return

    total_gross = 0
    total_ded = 0
    total_net = 0
    for pdf_name in pdfs[:14]:
        meta = _extract_meta(pdf_name)
        total_gross += round(meta["official_gross"])
        total_ded += round(meta["official_deduction"])
        total_net += round(meta["official_net"])

    assert total_gross == 87156799
    assert total_ded == 18425996
    assert total_net == 68730803


def test_process_file_v2_persists_official_totals_to_bills_v2(tmp_path):
    db_path = tmp_path / "official_totals_smoke.db"
    app.config["DATABASE"] = str(db_path)
    init_db()
    init_v2_schema(app.config["DATABASE"])

    pdf_name = "10.pdf"  # COMMISSIONERATE JDR
    fpath = os.path.join(PDF_DIR, pdf_name)
    process_file_v2(fpath, pdf_name, dict(app.config))

    db = sqlite3.connect(app.config["DATABASE"])
    row = db.execute(
        """
        SELECT official_gross, official_deduction, official_net, group_name, bill_no
        FROM bills_v2
        WHERE source_filename = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (pdf_name,),
    ).fetchone()
    db.close()

    assert row is not None
    assert row[0] > 0
    assert row[1] > 0
    assert row[2] > 0
    assert row[3] == "COMMISSIONERATE JDR"
    assert row[4] == "508970353"
