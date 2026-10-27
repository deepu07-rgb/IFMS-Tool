"""Anonymized GA55 geometry: deduction amounts remain source facts."""

from ifms_suite.document_facts import facts_from_pages
from test_document_facts import w, page, header


def packet(extra=None, printed="1400.00", net="16600.00"):
    words = header() + [
        w("Deductions", 0.71, 0.2),
        w("Total Deductions", 0.86, 0.2),
        w("Net", 0.94, 0.2),
        w("October", 0.05, 0.6),
        w("2031", 0.05, 0.62),
        w("Regular", 0.12, 0.6),
        w("123456789", 0.18, 0.6),
        w("Basic", 0.31, 0.58),
        w("18000.00", 0.37, 0.58),
        w("18000.00", 0.56, 0.58),
        w(printed, 0.86, 0.58),
        w(net, 0.94, 0.58),
    ]
    return page(words + (extra or []))


def rows():
    return [
        w("GPF2004", 0.63, 0.58),
        w("1000.00", 0.69, 0.58),
        w("RGHS", 0.75, 0.58),
        w("500.00", 0.80, 0.58),
        w("SIP", 0.63, 0.61),
        w("-100.00", 0.69, 0.61),
    ]


def test_extracts_signed_deductions_from_two_lanes_with_source_evidence():
    bill = facts_from_pages([packet(rows())])["bills"][0]
    assert bill.get("deductions") == {
        "GPF2004": "1000.00",
        "RGHS": "500.00",
        "SIP": "-100.00",
    }
    assert bill["deductions_complete"] is True
    assert bill["deductions_reconciled"] is True
    assert all(q["page"] == 1 and q["box"] for q in bill["deduction_evidence"])
    assert bill["allowances_complete"] and bill["complete"]


def test_unreadable_deduction_cannot_borrow_adjacent_lane_or_printed_total():
    extra = rows()
    next(q for q in extra if q["text"] == "1000.00")["text"] = "1?00.00"
    bill = facts_from_pages([packet(extra)])["bills"][0]
    assert bill.get("deductions") == {"RGHS": "500.00", "SIP": "-100.00"}
    assert not bill["deductions_complete"]
    assert bill["allowances_complete"]
    assert not bill["complete"]


def test_recognition_conflict_and_duplicate_head_block_deduction_completeness():
    for change in ("conflict", "duplicate"):
        extra = rows()
        if change == "conflict":
            extra[1]["recognition_conflict"] = True
        else:
            extra += [w("SIP", 0.63, 0.64), w("0.00", 0.69, 0.64)]
        bill = facts_from_pages([packet(extra)])["bills"][0]
        assert bill.get("deductions_complete") is False
        assert bill["allowances_complete"]


def test_split_roadways_label_retains_printed_fragments_and_unexpected_heads():
    extra = [
        w("ROAD", 0.63, 0.58),
        w("200.00", 0.69, 0.58),
        w("WAYS", 0.63, 0.595),
        w("DEDUTI", 0.63, 0.61),
        w("ON", 0.63, 0.625),
        w("OTHER", 0.75, 0.58),
        w("1200.00", 0.80, 0.58),
    ]
    bill = facts_from_pages([packet(extra)])["bills"][0]
    assert bill.get("deductions") == {"ROADWAYS": "200.00", "OTHER": "1200.00"}
    assert {"ROAD", "WAYS", "DEDUTI", "ON"} <= {
        q["text"] for q in bill["deduction_evidence"]
    }
    assert bill["deductions_complete"]


def test_deduction_sum_mismatch_does_not_change_printed_reconciliation():
    bill = facts_from_pages([packet(rows(), printed="1500.00", net="16500.00")])[
        "bills"
    ][0]
    assert bill["net_reconciled"]
    assert bill.get("deductions_reconciled") is False
    assert not bill["deductions_complete"]
    assert bill["allowances_complete"]


def test_deduction_only_page_continuation_requires_employee_identity():
    first = packet([w("GPF", 0.63, 0.58), w("1000.00", 0.69, 0.58)])
    for employee in ("RJAB203012345678", "RJAB203098765432"):
        second = page(
            header(employee) + [w("RGHS", 0.75, 0.25), w("400.00", 0.80, 0.25)], 2
        )
        bill = facts_from_pages([first, second])["bills"][0]
        if employee == "RJAB203012345678":
            assert bill.get("deductions") == {"GPF": "1000.00", "RGHS": "400.00"}
            assert bill["deductions_complete"]
            assert bill["source_pages"] == [1, 2]
        else:
            assert bill.get("deductions") == {"GPF": "1000.00"}
            assert not bill["deductions_complete"]


def test_missing_deduction_heads_are_unknown_even_for_printed_zero():
    bill = facts_from_pages([packet(printed="0.00", net="18000.00")])["bills"][0]
    assert bill.get("deductions") == {}
    assert not bill["deductions_complete"]


def test_wrapped_rp_kalyan_nidhi_is_one_literal_head_with_all_source_words():
    extra = [
        w("RP", 0.63, 0.58),
        w("1400.00", 0.69, 0.58),
        w("KALYAN", 0.63, 0.595),
        w("NIDHI", 0.63, 0.61),
    ]
    bill = facts_from_pages([packet(extra)])["bills"][0]
    assert bill.get("deductions") == {"RP KALYAN NIDHI": "1400.00"}
    assert bill["deductions_complete"]
    assert {"RP", "KALYAN", "NIDHI"} <= {q["text"] for q in bill["deduction_evidence"]}


def test_unassigned_malformed_deduction_amount_cannot_disappear_into_matching_total():
    extra = rows() + [w("1?00.00", 0.80, 0.66)]
    facts = facts_from_pages([packet(extra)])
    bill = facts["bills"][0]
    assert bill.get("deductions_complete") is False
    assert bill["allowances_complete"]
    assert any("Unassigned deduction amount 1?00.00" in str(q) for q in facts["issues"])


def test_same_recognized_pages_surface_increment_candidates_and_keep_unsupported_blocker():
    recognized = page(
        [w("Increment Order", 0.1, 0.1), w("Effective date unreadable", 0.1, 0.3)]
    )
    facts = facts_from_pages([recognized])
    assert facts.get("order_candidates")
    assert facts.get("pay_orders") == []
    issue = next(q for q in facts["issues"] if q.get("kind") == "unsupported_page")
    assert issue["blocking"]
    assert any(
        q["text"] == "Increment Order" and q["page"] == 1 for q in issue["evidence"]
    )


def test_untrusted_printed_total_cannot_certify_deduction_completeness():
    recognized = packet(rows())
    next(q for q in recognized["words"] if q["text"] == "1400.00")["confidence"] = 0.1
    bill = facts_from_pages([recognized])["bills"][0]
    assert bill.get("deductions_complete") is False
    assert bill["allowances_complete"]
