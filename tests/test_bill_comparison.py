from ifms_suite.bill_comparison import compare_statement


def test_equal_net_does_not_hide_component_discrepancies():
    result = {
        "rows": [
            {
                "month": "2026-07",
                "components": [
                    {"head": "BASIC", "due": "100", "drawn": "100"},
                    {"head": "HRA", "due": "20", "drawn": "0"},
                ],
            }
        ]
    }
    reference = [
        {
            "month": "2026-07",
            "due": {"Basic": "100", "HRA": "20", "CCA": "5"},
            "drawn": {"Basic": "100", "HRA": "0", "CCA": "5"},
            "issues": [],
        }
    ]
    compared = compare_statement(result, reference)
    assert compared["status"] == "candidate_discrepancies"
    assert len(compared["discrepancies"]) == 2
    assert compared["review_required"] is True
