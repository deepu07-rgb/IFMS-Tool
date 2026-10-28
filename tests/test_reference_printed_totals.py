"""Reference totals must match independent selected heads even with matching components."""


def test_wrong_printed_total_is_not_hidden_by_matching_component_values():
    from ifms_suite.bill_comparison import compare_statement

    bill = {
        "rows": [
            {
                "month": "2031-01",
                "components": [
                    {
                        "head": "BASIC",
                        "due": "120",
                        "drawn": "100",
                        "prior_settlement": "0",
                    },
                    {"head": "DA", "due": "60", "drawn": "50", "prior_settlement": "0"},
                    {
                        "head": "OTHER",
                        "due": "25",
                        "drawn": "25",
                        "prior_settlement": "0",
                    },
                ],
            }
        ]
    }
    reference = [
        {
            "month": "2031-01",
            "due": {"Basic": "120", "DA": "60"},
            "drawn": {"Basic": "100", "DA": "50"},
            "printed_due": "180",
            "printed_drawn": "15",
            "printed_difference": "30",
            "issues": [],
        }
    ]
    result = compare_statement(bill, reference)
    assert result["status"] == "candidate_discrepancies"
    assert any(
        d["side"] == "drawn"
        and d["head"] == "Total"
        and d["source_calculation"] == "150.00"
        for d in result["discrepancies"]
    )
    reference[0]["printed_drawn"] = "150"
    assert compare_statement(bill, reference)["status"] == "candidate_matches"


def test_reference_already_drawn_includes_verified_credit_as_supplied_form_does():
    from ifms_suite.bill_comparison import compare_statement

    bill = {
        "rows": [
            {
                "month": "2031-01",
                "components": [
                    {
                        "head": "BASIC",
                        "due": "120",
                        "drawn": "100",
                        "prior_settlement": "10",
                    },
                    {"head": "DA", "due": "60", "drawn": "50", "prior_settlement": "0"},
                ],
            }
        ]
    }
    reference = [
        {
            "month": "2031-01",
            "due": {"Basic": "120", "DA": "60"},
            "drawn": {"Basic": "110", "DA": "50"},
            "printed_due": "180",
            "printed_drawn": "160",
            "printed_difference": "20",
            "issues": [],
        }
    ]
    result = compare_statement(bill, reference)
    assert result["status"] == "candidate_matches", result
