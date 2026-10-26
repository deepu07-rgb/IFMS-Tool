import json

"""Read-only bridge from the existing analyzer to shared payment review."""

import calendar
from decimal import Decimal
from pathlib import Path
from flask import request, jsonify, current_app, send_file
from .storage import database

HEADS = {
    "basic_pay": "Basic",
    "da": "DA",
    "hra": "HRA",
    "cca": "CCA",
    "hda": "HDA",
    "mess_all": "Mess All",
    "mess_allowance": "Mess All",
    "fta": "FTA",
    "rop": "ROP",
    "gpf": "GPF",
    "gpf_2004": "GPF-2004",
    "sip": "SIP",
    "rghs": "RGHS",
    "lic": "LIC",
    "roadways_deduction": "Roadways",
}


def register_analyzer_bridge(suite):
    @suite.post("/api/group_import/analyzer")
    def analyzer_profiles():
        records = []
        with database() as db:
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='employees_v2'"
            ).fetchone():
                raise ValueError("Import inner sheets first")
            for r in db.execute(
                "SELECT e.*,b.office_id,b.ddo_code,b.source_filename AS bill_source FROM employees_v2 e JOIN bills_v2 b ON b.id=e.bill_id WHERE COALESCE(e.is_deleted,0)=0 ORDER BY e.id"
            ):
                records.append(
                    dict(
                        employeeCode=r["employee_id"],
                        employeeName=r["raw_name"] or r["normalized_name"],
                        groupName=r["group_name"] or "",
                        designation=r["final_designation_en"]
                        or r["raw_designation"]
                        or "",
                        ddoCode=r["ddo_code"] or "",
                        source_employee_row_id=r["id"],
                        source_file=r["source_filename"] or r["bill_source"],
                    )
                )
            if not records:
                raise ValueError("No extracted employee rows are available")
            id = db.execute(
                "INSERT INTO suite_group_imports(payload) VALUES(?)",
                (json.dumps({"records": records, "source": "Inner Sheet Analyzer"}),),
            ).lastrowid
        return jsonify(id=id, rows=len(records)), 201

    @suite.get("/api/analyzer_candidates")
    def candidates():
        code = request.args.get("employee_code", "").strip().upper()
        if not code:
            raise ValueError("Select one employee code")
        result = []
        with database() as db:
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='employees_v2'"
            ).fetchone():
                return jsonify([])
            for r in db.execute(
                "SELECT e.*,b.bill_no,b.month_year AS bill_month FROM employees_v2 e JOIN bills_v2 b ON b.id=e.bill_id WHERE UPPER(e.employee_id)=? AND COALESCE(e.is_deleted,0)=0 ORDER BY e.id LIMIT 500",
                (code,),
            ):
                period = (
                    str(r["month_year"] or r["bill_month"] or "")
                    .replace("/", " ")
                    .split()
                )
                if len(period) != 2:
                    continue
                try:
                    month = list(calendar.month_name).index(period[0].title())
                    year = int(period[1])
                except (ValueError, TypeError):
                    continue
                p = dict(
                    employee_code=code,
                    employee_name=r["raw_name"],
                    bill_no=r["bill_no"],
                    pay_month=f"{year:04d}-{month:02d}",
                    bill_type="Regular Salary",
                    allowances={},
                    deductions={},
                    deduction_effects={},
                    requires_review=True,
                    source_employee_row_id=r["id"],
                    source_file=r["source_filename"],
                    source_page=r["page_no"],
                    printed_gross=str(r["gross_amount"]),
                    printed_deductions=str(r["sum_deduction"]),
                    printed_net=str(r["net_total"]),
                    issues=[
                        "Confirm bill type and component totals against the original inner sheet"
                    ],
                )
                for c in db.execute(
                    "SELECT * FROM employee_components_v2 WHERE employee_id=?",
                    (r["id"],),
                ):
                    head = HEADS.get(c["normalized_head"], c["raw_head"])
                    dest = (
                        p["allowances"]
                        if c["component_type"] == "allowance"
                        else p["deductions"]
                    )
                    if head in dest:
                        p["issues"].append(
                            "Repeated component " + str(head) + "; check the source"
                        )
                    dest[head] = (
                        f"{Decimal(str(c['amount']))+Decimal(dest.get(head,'0')):.2f}"
                    )
                    if c["component_type"] == "deduction":
                        p["deduction_effects"][head] = bool(c["included_in_total"])
                result.append(p)
        return jsonify(result)

    @suite.get("/api/analyzer_source/<int:id>")
    def source(id):
        with database() as db:
            r = db.execute(
                "SELECT source_filename FROM employees_v2 WHERE id=?", (id,)
            ).fetchone()
        if not r:
            return jsonify(error="Source not found"), 404
        root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        path = (root / r["source_filename"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return jsonify(error="Original source file unavailable"), 404
        return send_file(path, mimetype="application/pdf")
