from ifms_suite.due_drawn import parse_statement_table


def test_due_drawn_arithmetic_detects_wrong_difference_without_correcting_source():
    rows = [
        [
            "Sr",
            "Month",
            "Pay Due",
            "",
            "",
            "",
            "Pay Drawn",
            "",
            "",
            "",
            "Pay Difference",
            "",
            "",
            "",
        ],
        [
            "",
            "",
            "Basic",
            "DA",
            "HRA",
            "Total",
            "Basic",
            "DA",
            "HRA",
            "Total",
            "Basic",
            "DA",
            "HRA",
            "Total",
        ],
        [
            "1",
            "Jan-2025",
            "50000",
            "27500",
            "10000",
            "87500",
            "50000",
            "26500",
            "10000",
            "86500",
            "0",
            "1000",
            "0",
            "999",
        ],
    ]
    r = parse_statement_table(rows)
    assert len(r) == 1
    assert r[0]["printed_difference"] == "999.00"
    assert r[0]["calculated_difference"] == "1000.00"
    assert any("difference" in i.lower() for i in r[0]["issues"])
    assert r[0]["month"] == "2025-01"


def test_unknown_or_incomplete_layout_is_not_guessed():
    assert parse_statement_table([["Month", "Amount"], ["Jan-2025", "1000"]]) == []


def test_period_amounts_are_not_prorated_a_second_time():
    from ifms_suite.calculation import calculate_claim

    r = calculate_claim(
        "2025-03-13",
        "2025-03-31",
        [
            dict(
                start="2025-03-13",
                end="2025-03-31",
                basis="fixed",
                due_basis="period",
                due_amount="1000",
                drawn_amount="800",
                drawn_basis="period",
            )
        ],
    )
    assert r["total"] == "200.00"


def expanded_statement():
    return [
        [
            "Month",
            "Due Pay",
            "",
            "",
            "",
            "",
            "",
            "Drawn Pay",
            "",
            "",
            "",
            "",
            "",
            "Difference",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "",
            "Basic Pay",
            "D.A.",
            "H.D.A.",
            "C.C.A.",
            "H.R.A.",
            "Gross Total",
            "HRA",
            "CCA",
            "HDA",
            "DA",
            "Basic",
            "Total",
            "Basic",
            "DA",
            "HDA",
            "CCA",
            "HRA",
            "Total",
        ],
        [
            "Feb-2025",
            50000,
            27500,
            1000,
            500,
            10000,
            89000,
            9000,
            400,
            900,
            26500,
            50000,
            86800,
            0,
            1000,
            100,
            100,
            1000,
            2200,
        ],
    ]


def test_explicit_headers_map_extra_and_reordered_heads():
    parsed = parse_statement_table(expanded_statement())
    assert len(parsed) == 1
    row = parsed[0]
    assert row["due"] == {
        "Basic": "50000.00",
        "DA": "27500.00",
        "HDA": "1000.00",
        "CCA": "500.00",
        "HRA": "10000.00",
    }
    assert row["drawn"]["Basic"] == "50000.00"
    assert row["drawn"]["HRA"] == "9000.00"
    assert row["calculated_difference"] == "2200.00"
    assert row["issues"] == []
    assert row["source_row"] == 3


def test_equal_net_does_not_hide_incorrect_printed_component_differences():
    rows = expanded_statement()
    rows[2][14:16] = [900, 200]  # Same net; DA and HDA differences are wrong.
    parsed = parse_statement_table(rows)
    assert len(parsed) == 1
    assert any(
        "DA" in issue and "difference" in issue.lower() for issue in parsed[0]["issues"]
    )
    assert any(
        "HDA" in issue and "difference" in issue.lower()
        for issue in parsed[0]["issues"]
    )


def test_missing_digits_are_retained_as_unresolved_not_balanced_from_total():
    rows = expanded_statement()
    rows[2][3] = None
    parsed = parse_statement_table(rows)
    assert len(parsed) == 1
    assert parsed[0]["due"]["HDA"] is None
    assert parsed[0]["printed_due"] == "89000.00"
    assert parsed[0]["requires_review"] is True
    assert any("HDA" in issue for issue in parsed[0]["issues"])


def test_unknown_component_header_prevents_silently_omitting_financial_columns():
    rows = expanded_statement()
    rows[1][3] = "Special allowance"
    assert parse_statement_table(rows) == []


def test_custom_component_mapping_requires_explicit_name():
    rows = expanded_statement()
    rows[1][3] = "Special allowance"
    parsed = parse_statement_table(rows, component_aliases={"Special allowance": "HDA"})
    assert parsed[0]["due"]["HDA"] == "1000.00"


def test_source_comparison_detects_wrong_both_sides_despite_equal_net():
    rows = expanded_statement()
    reference = [{"month": "2025-02", "due": {"HDA": "1200"}, "drawn": {"HDA": "1100"}}]
    parsed = parse_statement_table(rows, reference_rows=reference)
    assert parsed[0]["calculated_difference"] == "2200.00"
    assert any(
        "Due HDA" in issue and "source" in issue.lower()
        for issue in parsed[0]["issues"]
    )
    assert any(
        "Drawn HDA" in issue and "source" in issue.lower()
        for issue in parsed[0]["issues"]
    )


def test_repeated_headers_change_mapping_without_duplicate_rows():
    rows = expanded_statement()
    second = expanded_statement()
    second[0][1], second[0][7] = "Pay Due", "Pay Drawn"
    second[2][0] = "Mar-2025"
    parsed = parse_statement_table(rows + second)
    assert [row["month"] for row in parsed] == ["2025-02", "2025-03"]
    assert parsed[1]["source_row"] == 6


def test_due_and_difference_without_drawn_is_not_a_statement():
    rows = [
        ["Month", "Due", "", "Difference", ""],
        ["", "Basic", "Total", "Basic", "Total"],
        ["Jan-2025", 100, 100, 10, 10],
    ]
    assert parse_statement_table(rows) == []


def test_duplicate_component_headers_are_rejected():
    rows = expanded_statement()
    rows[1][3] = "DA"
    assert parse_statement_table(rows) == []


def test_missing_total_does_not_get_reconstructed_from_known_components():
    rows = expanded_statement()
    rows[2][6] = ""
    parsed = parse_statement_table(rows)
    assert parsed[0]["printed_due"] is None
    assert parsed[0]["calculated_difference"] is None
    assert any("Total" in issue for issue in parsed[0]["issues"])


def test_ambiguous_reference_month_is_not_chosen_by_agreement():
    reference = [
        {"month": "2025-02", "due": {"HDA": "1000"}},
        {"month": "2025-02", "due": {"HDA": "9999"}},
    ]
    parsed = parse_statement_table(expanded_statement(), reference_rows=reference)
    assert any("ambiguous" in issue for issue in parsed[0]["issues"])


def test_printed_component_error_is_not_repaired_to_match_total():
    rows = expanded_statement()
    rows[2][3] = "1200"
    parsed = parse_statement_table(rows)
    assert parsed[0]["due"]["HDA"] == "1200.00"
    assert any("components" in issue for issue in parsed[0]["issues"])


def test_partial_reference_reports_component_comparison_coverage():
    parsed = parse_statement_table(
        expanded_statement(),
        reference_rows=[
            {"month": "2025-02", "due": {"HDA": "1000"}, "drawn": {"HDA": "900"}}
        ],
    )
    assert any(
        "Due Basic" in issue and "incomplete" in issue for issue in parsed[0]["issues"]
    )
    assert any(
        "Drawn DA" in issue and "incomplete" in issue for issue in parsed[0]["issues"]
    )
