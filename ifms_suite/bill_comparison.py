"""Compare reference candidates with independently calculated components."""

from .calculation import money


def compare_statement(bill, reference):
    result = dict(
        status="reference_not_read",
        review_required=True,
        discrepancies=[],
        unresolved=[],
        compared_cells=0,
    )
    months = {r["month"]: r for r in bill.get("rows", [])}
    seen = set()
    for source in reference:
        month = source.get("month")
        if month not in months:
            continue
        if month in seen:
            result["unresolved"].append(
                dict(
                    month=month, issue="Repeated reference month requires source review"
                )
            )
            continue
        seen.add(month)
        components = {c["head"].upper(): c for c in months[month]["components"]}
        result["unresolved"].extend(
            dict(month=month, issue=str(i)) for i in source.get("issues", [])
        )
        for side in ("due", "drawn"):
            for head, value in source.get(side, {}).items():
                if value is None:
                    result["unresolved"].append(
                        dict(
                            month=month,
                            side=side,
                            head=head,
                            issue="Reference amount unreadable",
                        )
                    )
                    continue
                expected = components.get(head.upper(), {}).get(side, "0.00")
                try:
                    actual = money(value)
                except ValueError:
                    result["unresolved"].append(
                        dict(
                            month=month,
                            side=side,
                            head=head,
                            issue="Reference amount invalid",
                        )
                    )
                    continue
                result["compared_cells"] += 1
                if actual != money(expected):
                    result["discrepancies"].append(
                        dict(
                            month=month,
                            side=side,
                            head=head,
                            reference=str(actual),
                            source_calculation=expected,
                        )
                    )
    if result["compared_cells"]:
        result["status"] = (
            "candidate_discrepancies"
            if result["discrepancies"]
            else "candidate_matches"
        )
    if result["unresolved"]:
        result["status"] = "reference_review_required"
    return result
