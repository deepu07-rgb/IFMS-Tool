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

        def expected_amount(head, side):
            component = components.get(head.upper(), {})
            amount = money(component.get(side, "0.00"))
            if side == "drawn":
                amount += money(component.get("prior_settlement", "0.00"))
            return amount

        def compare_value(value, expected, side, head):
            try:
                actual = money(value)
            except ValueError:
                result["unresolved"].append(
                    dict(
                        month=month,
                        side=side,
                        head=head,
                        issue="Reference amount unreadable or invalid",
                    )
                )
                return
            result["compared_cells"] += 1
            if actual != expected:
                result["discrepancies"].append(
                    dict(
                        month=month,
                        side=side,
                        head=head,
                        reference=str(actual),
                        source_calculation=f"{expected:.2f}",
                    )
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
                expected = expected_amount(head, side)
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
                if actual != expected:
                    result["discrepancies"].append(
                        dict(
                            month=month,
                            side=side,
                            head=head,
                            reference=str(actual),
                            source_calculation=f"{expected:.2f}",
                        )
                    )
            # The supplied grid totals only its displayed heads. Full salary
            # may contain other unchanged allowances outside those columns.
            if "printed_" + side in source and source.get(side):
                selected = sum(
                    (expected_amount(h, side) for h in source[side]), money("0")
                )
                compare_value(source["printed_" + side], selected, side, "Total")
        if "printed_difference" in source and source["printed_difference"] is not None:
            if source.get("due") and {h.upper() for h in source["due"]} == {
                h.upper() for h in source.get("drawn", {})
            }:
                expected = sum(
                    (
                        expected_amount(h, "due") - expected_amount(h, "drawn")
                        for h in source["due"]
                    ),
                    money("0"),
                )
                compare_value(
                    source["printed_difference"], expected, "difference", "Total"
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
