import os
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app import app, init_db, process_file_v2
from ifms_engine.db import init_v2_schema
from ifms_engine.employee_block_detector import EmployeeBlockDetector
from ifms_engine.employee_parser import EmployeeParser
from ifms_engine.pdf_reader import PDFReader


def _numeric_tokens(block):
    tokens = []
    for w in sorted(block, key=lambda z: (z["y0"], z["x0"])):
        val = EmployeeParser._parse_num(w.get("text", ""))
        if val is not None and 400 <= w["x0"] < 900:
            tokens.append((round(w["x0"], 1), round(w["y0"], 1), w["text"]))
    return tokens


def _line_preview(block):
    lines = defaultdict(list)
    for w in block:
        y = round(w["y0"] / 3) * 3
        lines[y].append(w)
    return [
        " ".join(x["text"] for x in sorted(words, key=lambda z: z["x0"]))
        for _, words in sorted(lines.items())
    ]


def debug_pdf(pdf_path):
    print(f"Debug parsing: {pdf_path}")
    reader = PDFReader(str(pdf_path))
    words = reader.extract_words()
    blocks = EmployeeBlockDetector.detect_blocks(words)
    print(f"Total blocks detected: {len(blocks)}")

    page_sr = defaultdict(list)
    parsed = []
    for block in blocks:
        emp = EmployeeParser.parse_employee(list(block))
        page_sr[emp.page_no].append(emp.sr_no)
        parsed.append((emp, block))

    for page in sorted(page_sr):
        srs = [sr for sr in page_sr[page] if sr is not None]
        print(f"Page {page}: blocks={len(srs)} sr={srs}")

    print("\nEmployee row diagnostics:")
    for emp, block in parsed:
        expected_net = emp.gross_amount - emp.sum_deduction
        diff = emp.net_total - expected_net
        preview = (emp.raw_text_block or "")[:240].replace("\n", " ")
        print(
            f"\npage={emp.page_no} sr={emp.sr_no} name={emp.raw_name} "
            f"gross={emp.gross_amount} deduction={emp.sum_deduction} "
            f"net={emp.net_total} gross-ded={expected_net} diff={diff}"
        )
        print(f"right_tokens={_numeric_tokens(block)}")
        print(f"raw_preview={preview}")
        if abs(diff) > 1:
            print("line_preview:")
            for line in _line_preview(block):
                print(f"  {line}")
        if emp.issues:
            print("issues=" + ", ".join(issue.issue_type for issue in emp.issues))
    reader.close()


def run_pipeline(pdf_path):
    temp_dir = tempfile.TemporaryDirectory()
    db_path = str(Path(temp_dir.name) / "debug_v2_one_pdf.db")
    app.config["DATABASE"] = db_path
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])
    process_file_v2(str(pdf_path), Path(pdf_path).name, dict(app.config))

    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    bill = db.execute(
        """
        SELECT group_name, parsed_gross, parsed_deduction, parsed_net,
               official_gross, official_deduction, official_net, verification_status
        FROM bills_v2 ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    count = db.execute("SELECT COUNT(*) FROM employees_v2").fetchone()[0]
    issues = db.execute(
        """
        SELECT issue_type, COUNT(*) AS count
        FROM validation_issues_v2
        GROUP BY issue_type
        ORDER BY count DESC, issue_type
        """
    ).fetchall()
    print("\nPipeline DB summary:")
    print(f"group={bill['group_name']} employees={count}")
    print(f"parsed gross/ded/net={bill['parsed_gross']}/{bill['parsed_deduction']}/{bill['parsed_net']}")
    print(f"official gross/ded/net={bill['official_gross']}/{bill['official_deduction']}/{bill['official_net']}")
    print(f"verification_status={bill['verification_status']}")
    print("issues=" + ", ".join(f"{r['issue_type']}:{r['count']}" for r in issues))
    db.close()
    temp_dir.cleanup()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else os.path.join("test_fixtures", "ifms_inner_sheets", "1.pdf")
    pdf_path = Path(arg)
    if not pdf_path.exists():
        print(f"Missing: {pdf_path}")
        return 1
    debug_pdf(pdf_path)
    run_pipeline(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
