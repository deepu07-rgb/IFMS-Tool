"""Consolidated export uses the same immutable snapshots as individual exports."""

import io, json, zipfile
from decimal import Decimal
from flask import request, jsonify, send_file
from openpyxl import Workbook
from .storage import database
from . import exports


def register_batch_exports(suite):
    @suite.get("/api/batch_export")
    def batch_export():
        try:
            ids = [int(v) for v in request.args.get("ids", "").split(",")]
        except ValueError:
            raise ValueError("Select saved statement numbers") from None
        if not ids or len(ids) > 500 or len(ids) != len(set(ids)):
            raise ValueError("Select up to 500 distinct statements")
        with database() as db:
            rows = [
                db.execute("SELECT * FROM suite_claims WHERE id=?", (id,)).fetchone()
                for id in ids
            ]
        if any(r is None for r in rows):
            return jsonify(error="Statement not found"), 404
        result = io.BytesIO()
        w = Workbook()
        s = w.active
        s.title = "Consolidated"
        s.append(
            [
                "Statement",
                "Employee",
                "Allowance",
                "From",
                "Through",
                "Gross arrear",
                "Deductions",
                "Cash payable",
                "Status",
            ]
        )
        totals = [Decimal(0), Decimal(0), Decimal(0)]
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for r in rows:
                p = json.loads(r["payload"])
                c = json.loads(r["calculation"])
                review = json.loads(r["review"] or "{}")
                p.update(
                    {
                        k: review[k]
                        for k in ("rule_reference", "drawn_reference")
                        if k in review
                    }
                )
                p["status"] = r["status"]
                amounts = [
                    Decimal(c["total"]),
                    Decimal(c.get("total_deductions", "0")),
                    Decimal(c.get("net_payable", c["total"])),
                ]
                s.append(
                    [
                        r["id"],
                        p["employee_code"],
                        p["allowance"],
                        p["start"],
                        p["end"],
                        *[float(v) for v in amounts],
                        r["status"],
                    ]
                )
                for cell in s[s.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
                totals = [a + b for a, b in zip(totals, amounts)]
                prefix = f"Statement-{r['id']}-{r['status']}"
                z.writestr(prefix + ".xlsx", exports.excel(p, c).getvalue())
                z.writestr(prefix + ".pdf", exports.pdf(p, c).getvalue())
            s.append(["TOTAL", "", "", "", "", *[float(v) for v in totals]])
            s.freeze_panes = "C2"
            s.page_setup.orientation = "landscape"
            s.page_setup.paperSize = s.PAPERSIZE_A4
            b = io.BytesIO()
            w.save(b)
            z.writestr("Consolidated.xlsx", b.getvalue())
        result.seek(0)
        return send_file(
            result,
            mimetype="application/zip",
            as_attachment=True,
            download_name="IFMS-Arrear-Pack.zip",
        )
