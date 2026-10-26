from ifms_suite.documents import parse_ga55


def test_unreadable_scanned_table_cannot_look_like_zero_arrears():
    r = parse_ga55(
        [
            "Government Of Rajasthan\nGASS A\nJuly Regular S10099141\nHRA unreadable\nTotal Allowances"
        ]
    )
    assert r["extraction_status"] == "unreadable_or_unsupported"
    assert r["calculation_ready"] is False
    assert "zero" in r["notice"].lower()


from test_suite_workflow import client


def test_reviewed_july_hra_matches_reference_without_salary_deductions(client):
    r = client.post(
        "/suite/api/claims",
        json=dict(
            employee_code="SYNTHETIC",
            allowance="HRA",
            start="2026-07-01",
            end="2026-07-31",
            segments=[
                dict(
                    start="2026-07-01",
                    end="2026-07-31",
                    basic="22000",
                    due_rate="20",
                    drawn_amount="0",
                    drawn_basis="period",
                )
            ],
        ),
    )
    assert r.status_code == 201
    assert r.json["calculation"]["total"] == "4400.00"
    assert r.json["calculation"]["net_payable"] == "4400.00"
