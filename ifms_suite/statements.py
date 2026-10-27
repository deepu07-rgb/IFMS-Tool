import json
from datetime import date
from calendar import monthrange
from flask import request, jsonify
from .storage import database
from .payroll import identity
from .history import active
from .calculation import money, calculate_claim


def register_statements(suite):
    @suite.post("/api/statement_claim")
    def statement_claim():
        p = request.get_json() or {}
        code = identity(p.get("employee_code"))
        head = identity(p.get("allowance"))
        if (
            not code
            or head not in ("BASIC", "DA", "HRA")
            or p.get("reviewed") is not True
        ):
            raise ValueError(
                "Select employee and Basic/DA/HRA, then confirm source review"
            )
        if p.get("method") not in ("rates", "uploaded"):
            raise ValueError(
                "Choose library recalculation or reviewed uploaded due amounts"
            )
        if head == "BASIC" and p["method"] == "rates":
            raise ValueError(
                "Basic pay must come from the approved pay fixation; use reviewed uploaded amounts"
            )
        rows = p.get("rows", [])
        if not rows or len(rows) > 1200:
            raise ValueError("Select up to 1200 reviewed monthly rows")
        segments = []
        component = "Basic" if head == "BASIC" else head
        with database() as db:
            source = db.execute(
                "SELECT * FROM suite_imports WHERE id=?", (p.get("import_id"),)
            ).fetchone()
            if not source:
                raise ValueError("Source import not found")
            original = json.loads(source["payload"])
            sheets = {
                r.get("source_sheet", "PDF") for r in original.get("statement_rows", [])
            }
            if len(sheets) > 1 and not p.get("source_sheet"):
                raise ValueError(
                    "Choose one source worksheet; workbooks may contain repeated employees or copies"
                )
            rates = [
                json.loads(r["payload"])
                for r in db.execute("SELECT payload FROM suite_rates")
            ]
            eligible_rates = [
                r
                for r in rates
                if identity(r["allowance"]) == head
                and r.get("category", "") == p.get("category", "")
            ]
            for r in rows:
                if r.get("source_sheet", "PDF") != p.get(
                    "source_sheet", r.get("source_sheet", "PDF")
                ):
                    continue
                # Review must preserve every identified source head, including heads
                # outside this single-component claim. A matching net is insufficient.
                matching_sources = [
                    source_row
                    for source_row in original.get("statement_rows", [])
                    if source_row.get("month") == r.get("month")
                    and source_row.get("source_sheet", "PDF")
                    == r.get("source_sheet", "PDF")
                ]
                for total in ("printed_due", "printed_drawn"):
                    if total in r or any(
                        total in source_row for source_row in matching_sources
                    ):
                        try:
                            money(r.get(total))
                        except ValueError:
                            raise ValueError(
                                "Resolve printed statement total "
                                + total
                                + " before creating a claim"
                            ) from None
                for side in ("due", "drawn"):
                    amounts = r.get(side, {})
                    source_heads = {
                        name
                        for source_row in matching_sources
                        for name in source_row.get(side, {})
                    }
                    missing = source_heads - amounts.keys()
                    if missing:
                        raise ValueError(
                            "Statement review omitted source components: "
                            + ", ".join(sorted(missing))
                        )
                    for name, amount in amounts.items():
                        try:
                            money(amount)
                        except ValueError:
                            raise ValueError(
                                f"Resolve {side} {name} before creating a statement claim"
                            ) from None
                first = date.fromisoformat(r["month"] + "-01")
                last = date(
                    first.year, first.month, monthrange(first.year, first.month)[1]
                )
                a = date.fromisoformat(r.get("start") or str(first))
                b = date.fromisoformat(r.get("end") or str(last))
                if a < first or b > last or a > b:
                    raise ValueError(
                        "Each statement row must stay inside its named calendar month"
                    )
                due = money(r["due"][component])
                drawn = money(r["drawn"][component])
                reference = "Reviewed uploaded due amount"
                if p["method"] == "rates":
                    rate = active(eligible_rates, a, "rate")
                    if active(eligible_rates, b, "rate") is not rate:
                        raise ValueError(
                            "Rate changes within this row; split the row at the effective date"
                        )
                    # Keep the monthly entitlement unrounded until the shared
                    # engine prorates it to the selected dates.
                    due = money(r["due"]["Basic"]) * money(rate["rate"]) / 100
                    reference = rate["reference"] + " " + rate.get("order_date", "")
                s = dict(
                    start=str(a),
                    end=str(b),
                    basis="fixed",
                    due_amount=str(due),
                    drawn_amount=str(drawn),
                    drawn_basis="monthly_amount",
                    source="Source import "
                    + str(source["id"])
                    + " / "
                    + str(r.get("source_sheet", "PDF"))
                    + " row "
                    + str(r.get("source_row", "")),
                    rule_reference=reference,
                )
                if p["method"] == "rates":
                    s["rounding"] = rate.get("rounding", "paise")
                if p.get("amounts_cover_selected_period") is True:
                    s["drawn_basis"] = "period"
                    if p["method"] == "uploaded":
                        s["due_basis"] = "period"
                segments.append(s)
            if not segments:
                raise ValueError("No rows selected in the chosen worksheet")
            start = min(s["start"] for s in segments)
            end = max(s["end"] for s in segments)
            calculation = calculate_claim(start, end, segments, p.get("deductions"))
            q = dict(
                p,
                employee_code=code,
                allowance=head,
                source="reviewed_statement",
                start=start,
                end=end,
                segments=segments,
                source_sha256=source["sha256"],
            )
            id = db.execute(
                "INSERT INTO suite_claims(payload,calculation) VALUES(?,?)",
                (json.dumps(q), json.dumps(calculation)),
            ).lastrowid
        return jsonify(id=id, calculation=calculation), 201
