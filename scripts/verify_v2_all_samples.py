import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from app import app, init_db, process_file_v2  # noqa: E402
from ifms_engine.db import init_v2_schema  # noqa: E402


PDF_DIR = ROOT / "test_fixtures" / "ifms_inner_sheets"

EXPECTED_GLOBALS = {
    "bills": 14,
    "employees": 1118,
    "parsed_gross": 87156799,
    "parsed_deduction": 18425996,
    "parsed_net": 68730803,
    "official_gross": 87156799,
    "official_deduction": 18425996,
    "official_net": 68730803,
}

SCHEDULE_EXPECTATIONS = {
    "lic": "lic",
    "gpf": "gpf",
    "gpf_2004": "gpf_2004",
    "rop": "rop",
}


@dataclass
class VerificationReport:
    passed: bool
    db_path: str
    pdfs: List[str]
    global_summary: Dict[str, int]
    per_file: List[Dict[str, object]]
    issue_counts: Dict[str, int]
    mismatches: List[Dict[str, object]]
    schedule_errors: List[str]
    schedule_summary: Dict[str, Dict[str, object]]
    problem_rows: List[Dict[str, object]] = field(default_factory=list)

    def failure_messages(self) -> List[str]:
        messages = []
        for key, expected in EXPECTED_GLOBALS.items():
            actual = self.global_summary.get(key)
            if actual != expected:
                messages.append(f"{key}: actual={actual} expected={expected}")
        messages.extend(self.schedule_errors)
        return messages


def _pdf_sort_key(path: Path) -> int:
    match = re.match(r"^(\d+)\.pdf$", path.name, re.IGNORECASE)
    return int(match.group(1)) if match else 10**9


def list_sample_pdfs(pdf_dir: Path = PDF_DIR) -> List[Path]:
    return sorted(pdf_dir.glob("*.pdf"), key=_pdf_sort_key)


def _round(value) -> int:
    return int(round(float(value or 0)))


def _rows_to_dicts(rows) -> List[Dict[str, object]]:
    return [dict(row) for row in rows]


def _fetch_global_summary(db: sqlite3.Connection) -> Dict[str, int]:
    bill_count = db.execute("SELECT COUNT(*) FROM bills_v2").fetchone()[0]
    emp_count = db.execute("SELECT COUNT(*) FROM employees_v2").fetchone()[0]
    parsed = db.execute(
        """
        SELECT
          COALESCE(SUM(gross_amount),0) AS gross,
          COALESCE(SUM(sum_deduction),0) AS deduction,
          COALESCE(SUM(net_total),0) AS net
        FROM employees_v2
        """
    ).fetchone()
    official = db.execute(
        """
        SELECT
          COALESCE(SUM(official_gross),0) AS gross,
          COALESCE(SUM(official_deduction),0) AS deduction,
          COALESCE(SUM(official_net),0) AS net
        FROM bills_v2
        """
    ).fetchone()
    return {
        "bills": bill_count,
        "employees": emp_count,
        "parsed_gross": _round(parsed["gross"]),
        "parsed_deduction": _round(parsed["deduction"]),
        "parsed_net": _round(parsed["net"]),
        "official_gross": _round(official["gross"]),
        "official_deduction": _round(official["deduction"]),
        "official_net": _round(official["net"]),
    }


def _fetch_per_file(db: sqlite3.Connection) -> List[Dict[str, object]]:
    rows = db.execute(
        """
        SELECT
          b.source_filename,
          b.group_name,
          COUNT(e.id) AS employee_count,
          COALESCE(SUM(e.gross_amount),0) AS parsed_gross,
          COALESCE(SUM(e.sum_deduction),0) AS parsed_deduction,
          COALESCE(SUM(e.net_total),0) AS parsed_net,
          b.official_gross,
          b.official_deduction,
          b.official_net,
          b.verification_status
        FROM bills_v2 b
        LEFT JOIN employees_v2 e ON e.bill_id = b.id
        GROUP BY b.id
        ORDER BY CAST(REPLACE(b.source_filename, '.pdf', '') AS INTEGER)
        """
    ).fetchall()
    summaries = []
    for row in rows:
        parsed_gross = _round(row["parsed_gross"])
        parsed_ded = _round(row["parsed_deduction"])
        parsed_net = _round(row["parsed_net"])
        official_gross = _round(row["official_gross"])
        official_ded = _round(row["official_deduction"])
        official_net = _round(row["official_net"])
        summaries.append(
            {
                "source_file": row["source_filename"],
                "group_name": row["group_name"],
                "employee_count": row["employee_count"],
                "parsed_gross": parsed_gross,
                "parsed_deduction": parsed_ded,
                "parsed_net": parsed_net,
                "official_gross": official_gross,
                "official_deduction": official_ded,
                "official_net": official_net,
                "gross_mismatch": parsed_gross - official_gross,
                "deduction_mismatch": parsed_ded - official_ded,
                "net_mismatch": parsed_net - official_net,
                "verification_status": row["verification_status"],
            }
        )
    return summaries


def _fetch_issue_counts(db: sqlite3.Connection) -> Dict[str, int]:
    rows = db.execute(
        """
        SELECT issue_type, COUNT(*) AS count
        FROM validation_issues_v2
        WHERE COALESCE(status, 'OPEN') != 'RESOLVED'
        GROUP BY issue_type
        ORDER BY count DESC, issue_type
        """
    ).fetchall()
    return {row["issue_type"]: row["count"] for row in rows}


def _fetch_mismatches(db: sqlite3.Connection) -> List[Dict[str, object]]:
    rows = db.execute(
        """
        SELECT
          b.source_filename,
          b.group_name,
          COUNT(e.id) AS employee_count,
          COALESCE(SUM(e.gross_amount),0) AS parsed_gross,
          COALESCE(SUM(e.sum_deduction),0) AS parsed_deduction,
          COALESCE(SUM(e.net_total),0) AS parsed_net,
          b.official_gross,
          b.official_deduction,
          b.official_net,
          b.verification_status
        FROM bills_v2 b
        LEFT JOIN employees_v2 e ON e.bill_id = b.id
        GROUP BY b.id
        HAVING ROUND(COALESCE(SUM(e.gross_amount),0)) != ROUND(COALESCE(b.official_gross,0))
            OR ROUND(COALESCE(SUM(e.sum_deduction),0)) != ROUND(COALESCE(b.official_deduction,0))
            OR ROUND(COALESCE(SUM(e.net_total),0)) != ROUND(COALESCE(b.official_net,0))
        ORDER BY b.source_filename
        """
    ).fetchall()
    mismatches = []
    for row in rows:
        source_file = row["source_filename"]
        top_issues = db.execute(
            """
            SELECT issue_type, COUNT(*) AS count
            FROM validation_issues_v2 v
            JOIN bills_v2 b ON b.id = v.bill_id
            WHERE b.source_filename = ?
              AND COALESCE(v.status, 'OPEN') != 'RESOLVED'
            GROUP BY issue_type
            ORDER BY count DESC, issue_type
            LIMIT 5
            """,
            (source_file,),
        ).fetchall()
        item = dict(row)
        item["parsed_gross"] = _round(item["parsed_gross"])
        item["parsed_deduction"] = _round(item["parsed_deduction"])
        item["parsed_net"] = _round(item["parsed_net"])
        item["official_gross"] = _round(item["official_gross"])
        item["official_deduction"] = _round(item["official_deduction"])
        item["official_net"] = _round(item["official_net"])
        item["gross_mismatch"] = item["parsed_gross"] - item["official_gross"]
        item["deduction_mismatch"] = item["parsed_deduction"] - item["official_deduction"]
        item["net_mismatch"] = item["parsed_net"] - item["official_net"]
        item["top_unresolved_issues"] = {r["issue_type"]: r["count"] for r in top_issues}
        mismatches.append(item)
    return mismatches


def _fetch_problem_rows(db: sqlite3.Connection, limit: int = 20) -> List[Dict[str, object]]:
    rows = db.execute(
        """
        SELECT
          e.source_filename,
          e.group_name,
          e.page_no,
          e.sr_no,
          e.raw_name,
          e.gross_amount,
          e.sum_deduction,
          e.net_total,
          COALESCE((
            SELECT v.issue_type
            FROM validation_issues_v2 v
            WHERE v.employee_id = e.id
              AND COALESCE(v.status, 'OPEN') != 'RESOLVED'
            ORDER BY v.id
            LIMIT 1
          ), '') AS issue_type
        FROM employees_v2 e
        WHERE e.gross_amount > 0
          AND e.sum_deduction > 0
          AND e.net_total > 0
          AND ABS((e.gross_amount - e.sum_deduction) - e.net_total) > 1
        ORDER BY ABS((e.gross_amount - e.sum_deduction) - e.net_total) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return _rows_to_dicts(rows)


def _check_schedule_sanity(client) -> (Dict[str, Dict[str, object]], List[str]):
    summary = {}
    errors = []
    for schedule_type, expected_head in SCHEDULE_EXPECTATIONS.items():
        response = client.get(f"/api/schedule_entries?schedule_type={schedule_type}&page=1&per_page=5000")
        if response.status_code != 200:
            errors.append(f"{schedule_type}: endpoint returned HTTP {response.status_code}")
            continue
        payload = response.get_json() or {}
        rows = payload.get("entries", [])
        heads = sorted({row.get("normalized_head") for row in rows})
        amounts = [row.get("component_amount") for row in rows]
        unrelated = [head for head in heads if head != expected_head]
        if unrelated:
            errors.append(f"{schedule_type}: unrelated heads returned {unrelated}")
        if any(amount in (None, 0) for amount in amounts):
            errors.append(f"{schedule_type}: zero/blank component amount returned")
        if schedule_type == "rop" and rows and not any(amount < 0 for amount in amounts):
            errors.append("rop: rows exist but no negative ROP amount was returned")
        summary[schedule_type] = {
            "rows": payload.get("total", len(rows)),
            "grand_total": payload.get("summary", {}).get("grand_total", 0),
            "heads": heads,
            "negative_amounts": sum(1 for amount in amounts if amount is not None and amount < 0),
        }
    return summary, errors


def run_verification(db_path: Optional[str] = None, keep_db: bool = False, verbose: bool = True) -> VerificationReport:
    pdfs = list_sample_pdfs()
    if len(pdfs) != EXPECTED_GLOBALS["bills"]:
        raise AssertionError(f"Expected 14 sample PDFs in {PDF_DIR}, found {len(pdfs)}")

    temp_dir = None
    if db_path is None:
        temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(temp_dir.name) / "v2_all_samples_verify.db")

    export_dir = Path(db_path).parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    app.config["DATABASE"] = db_path
    app.config["EXPORT_FOLDER"] = str(export_dir)
    app.config["USE_V2_PARSER"] = True
    init_db()
    init_v2_schema(app.config["DATABASE"])

    if verbose:
        print("=== V2 ALL-SAMPLE VERIFICATION START ===")
        print(f"Using temporary DB: {db_path}")

    for pdf in pdfs:
        if verbose:
            print(f"Processing {pdf.name}")
        process_file_v2(str(pdf), pdf.name, dict(app.config))

    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    global_summary = _fetch_global_summary(db)
    per_file = _fetch_per_file(db)
    issue_counts = _fetch_issue_counts(db)
    mismatches = _fetch_mismatches(db)
    problem_rows = _fetch_problem_rows(db)
    db.close()

    schedule_summary, schedule_errors = _check_schedule_sanity(app.test_client())
    passed = not VerificationReport(
        passed=False,
        db_path=db_path,
        pdfs=[pdf.name for pdf in pdfs],
        global_summary=global_summary,
        per_file=per_file,
        issue_counts=issue_counts,
        mismatches=mismatches,
        schedule_errors=schedule_errors,
        schedule_summary=schedule_summary,
        problem_rows=problem_rows,
    ).failure_messages()

    report = VerificationReport(
        passed=passed,
        db_path=db_path,
        pdfs=[pdf.name for pdf in pdfs],
        global_summary=global_summary,
        per_file=per_file,
        issue_counts=issue_counts,
        mismatches=mismatches,
        schedule_errors=schedule_errors,
        schedule_summary=schedule_summary,
        problem_rows=problem_rows,
    )

    if verbose:
        print_report(report)

    if temp_dir is not None and keep_db:
        temp_dir.cleanup = lambda: None
    elif temp_dir is not None:
        temp_dir.cleanup()
    return report


def print_report(report: VerificationReport) -> None:
    print("\n=== OVERALL ===")
    print("PASS" if report.passed else "FAIL")

    print("\n=== PER-FILE SUMMARY ===")
    for row in report.per_file:
        print(
            f"{row['source_file']:>6} | {row['group_name']:<24} | emp={row['employee_count']:>4} | "
            f"parsed={row['parsed_gross']}/{row['parsed_deduction']}/{row['parsed_net']} | "
            f"official={row['official_gross']}/{row['official_deduction']}/{row['official_net']} | "
            f"diff={row['gross_mismatch']}/{row['deduction_mismatch']}/{row['net_mismatch']} | "
            f"status={row['verification_status']}"
        )

    print("\n=== GLOBAL SUMMARY ===")
    for key in EXPECTED_GLOBALS:
        actual = report.global_summary.get(key)
        expected = EXPECTED_GLOBALS[key]
        marker = "OK" if actual == expected else "MISMATCH"
        print(f"{key:<20} actual={actual:<12} expected={expected:<12} {marker}")

    print("\n=== VALIDATION ISSUES BY TYPE ===")
    if report.issue_counts:
        for issue_type, count in report.issue_counts.items():
            print(f"{issue_type:<35} {count}")
    else:
        print("None")

    print("\n=== DERIVED SCHEDULE SANITY ===")
    for schedule_type, data in report.schedule_summary.items():
        print(
            f"{schedule_type:<10} rows={data['rows']:<5} grand_total={data['grand_total']:<12} "
            f"heads={data['heads']} negative_amounts={data['negative_amounts']}"
        )
    if report.schedule_errors:
        print("Schedule errors:")
        for error in report.schedule_errors:
            print(f"- {error}")

    if report.mismatches:
        print("\n=== MISMATCH TABLE ===")
        for row in report.mismatches:
            print(
                f"{row['source_filename']} | {row['group_name']} | emp={row['employee_count']} | "
                f"parsed={row['parsed_gross']}/{row['parsed_deduction']}/{row['parsed_net']} | "
                f"official={row['official_gross']}/{row['official_deduction']}/{row['official_net']} | "
                f"diff={row['gross_mismatch']}/{row['deduction_mismatch']}/{row['net_mismatch']} | "
                f"status={row['verification_status']} | issues={row['top_unresolved_issues']}"
            )

    if report.problem_rows:
        print("\n=== SAMPLE PROBLEMATIC ROWS ===")
        for row in report.problem_rows:
            print(
                f"{row['source_filename']} page={row['page_no']} group={row['group_name']} "
                f"sr={row['sr_no']} name={row['raw_name']} "
                f"gross={row['gross_amount']} deduction={row['sum_deduction']} "
                f"net={row['net_total']} issue={row['issue_type']}"
            )

    failures = report.failure_messages()
    if failures:
        print("\n=== FAILURES ===")
        for failure in failures:
            print(f"- {failure}")


def main() -> int:
    report = run_verification(verbose=True)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
