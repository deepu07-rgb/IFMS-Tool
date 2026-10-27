"""Printed order extraction must never substitute a total or issue date."""

from ifms_suite.pay_orders import extract_pay_orders


def w(text, x, y, width=0.12, **kwargs):
    return dict(
        text=text,
        box=[x, y, x + width, y + 0.012],
        confidence=0.99,
        recognizer="pdf-text",
        **kwargs
    )


def table():
    return [
        w("Increment Order", 0.05, 0.05),
        w("Issue Date", 0.6, 0.1),
        w("18.08.2031", 0.8, 0.1),
        w("Employee ID", 0.05, 0.3),
        w("Old Basic", 0.28, 0.3),
        w("Increment Date", 0.48, 0.3),
        w("Sanctioned Basic", 0.7, 0.3, 0.2),
        w("RJAB203012345678", 0.05, 0.4, 0.2),
        w("27000/-", 0.28, 0.4),
        w("01.07.2031", 0.48, 0.4),
        w("27800/-", 0.7, 0.4),
        w("Total", 0.05, 0.8),
        w("99999.00", 0.7, 0.8),
    ]


def extract(words):
    return extract_pay_orders([dict(page=7, words=words)])


def test_reads_only_sanctioned_basic_and_effective_date_with_provenance():
    row = extract(table())[0]
    assert row["complete"]
    assert row["kind"] == "increment"
    assert row["employee_code"] == "RJAB203012345678"
    assert row["effective_from"] == "2031-07-01"
    assert row["basic_amount"] == "27800.00"
    assert row["unresolved_fields"] == []
    assert row["source_pages"] == [7]
    assert row["confidence"] == 0.99
    assert any(e["text"] == "27800/-" and e["page"] == 7 for e in row["evidence"])
    assert all(e["text"] != "99999.00" for e in row["evidence"])


def test_missing_effective_heading_does_not_promote_issue_date():
    words = [word for word in table() if word["text"] != "Increment Date"]
    row = extract(words)[0]
    assert not row["complete"]
    assert row["effective_from"] == ""
    assert "effective_from" in row["unresolved_fields"]


def test_conflicting_or_low_confidence_amount_is_not_authoritative():
    for changes in ({"confidence": 0.79}, {"recognition_conflict": True}):
        words = table()
        next(word for word in words if word["text"] == "27800/-").update(changes)
        row = extract(words)[0]
        assert not row["complete"]
        assert row["basic_amount"] is None
        assert "basic_amount" in row["unresolved_fields"]
        assert any(e["text"] == "27800/-" for e in row["evidence"])


def test_two_rows_keep_each_employee_date_and_basic_separate():
    words = table() + [
        w("RJCD203112345678", 0.05, 0.5, 0.2),
        w("01.01.2032", 0.48, 0.5),
        w("34200.00", 0.7, 0.5),
    ]
    rows = extract(words)
    assert [
        (r["employee_code"], r["effective_from"], r["basic_amount"]) for r in rows
    ] == [
        ("RJAB203012345678", "2031-07-01", "27800.00"),
        ("RJCD203112345678", "2032-01-01", "34200.00"),
    ]


def test_ambiguous_row_amounts_require_review():
    words = table() + [w("28600.00", 0.7, 0.408)]
    row = extract(words)[0]
    assert row["basic_amount"] is None
    assert not row["complete"]


def test_identity_never_inherited_from_another_page():
    words = [word for word in table() if not word["text"].startswith("RJ")]
    rows = extract_pay_orders(
        [
            dict(page=1, words=[w("RJAB203012345678", 0.05, 0.1)]),
            dict(page=2, words=words),
        ]
    )
    assert rows == []


def test_unlabelled_numbers_or_basic_payroll_column_do_not_become_orders():
    assert (
        extract(
            [
                w("RJAB203012345678", 0.05, 0.4),
                w("Basic", 0.7, 0.3),
                w("27800.00", 0.7, 0.4),
                w("01.07.2031", 0.48, 0.4),
            ]
        )
        == []
    )


def test_split_heading_words_are_supported():
    words = [word for word in table() if word["text"] != "Sanctioned Basic"]
    words += [w("New", 0.7, 0.3, 0.035), w("Basic", 0.744, 0.3, 0.06)]
    assert extract(words)[0]["basic_amount"] == "27800.00"


def test_invalid_date_and_corrupt_numeric_text_are_unresolved():
    words = table()
    next(word for word in words if word["text"] == "01.07.2031")["text"] = "31.02.2031"
    next(word for word in words if word["text"] == "27800/-")["text"] = "278OO/-"
    row = extract(words)[0]
    assert not row["complete"]
    assert row["effective_from"] == ""
    assert row["basic_amount"] is None


def test_total_row_with_identity_must_not_become_an_employee_increment():
    words = table() + [
        w("Total", 0.3, 0.6),
        w("RJCD203112345678", 0.05, 0.6, 0.2),
        w("01.07.2031", 0.48, 0.6),
        w("62000.00", 0.7, 0.6),
    ]
    rows = extract(words)
    assert len(rows) == 1


def test_name_column_keeps_association_unresolved_and_extracts_old_and_new_basic():
    words = [
        word
        for word in table()
        if word["text"] not in {"Employee ID", "RJAB203012345678"}
    ]
    words += [w("Employee Name", 0.05, 0.3), w("राम लाल", 0.05, 0.4)]
    row = extract(words)[0]
    assert row["employee_name"] == "राम लाल"
    assert row["employee_code"] == ""
    assert row["old_basic"] == "27000.00"
    assert row["basic_amount"] == "27800.00"
    assert row["unresolved_fields"] == ["employee_code"]
    assert not row["complete"]


def test_labeled_narrative_distinguishes_issue_from_effective_date():
    words = [
        w("Increment Order", 0.05, 0.05),
        w("Issue Date", 0.05, 0.1),
        w("18.08.2031", 0.3, 0.1),
        w("Employee Name", 0.05, 0.2),
        w("राम लाल", 0.3, 0.2),
        w("Old Basic", 0.05, 0.3),
        w("27000/-", 0.3, 0.3),
        w("New Basic", 0.05, 0.4),
        w("27800/-", 0.3, 0.4),
        w("Effective From", 0.05, 0.5),
        w("01.07.2031", 0.3, 0.5),
    ]
    row = extract(words)[0]
    assert row["effective_from"] == "2031-07-01"
    assert row["old_basic"] == "27000.00"
    assert row["basic_amount"] == "27800.00"
    assert row["employee_name"] == "राम लाल"
    assert not row["complete"]


def test_multiline_hindi_headers_keep_name_and_dates_in_their_columns():
    words = [
        w("वेतनवृद्धि आदेश", 0.05, 0.05),
        w("कर्मचारी का नाम", 0.05, 0.3, 0.18),
        w("पुराना मूल वेतन", 0.28, 0.3, 0.16),
        w("प्रभावी दिनांक", 0.48, 0.3, 0.16),
        w("नया मूल वेतन", 0.7, 0.3, 0.2),
        w("राम लाल", 0.05, 0.4),
        w("27000/-", 0.28, 0.4),
        w("01.07.2031", 0.48, 0.4),
        w("27800/-", 0.7, 0.4),
    ]
    row = extract(words)[0]
    assert row["employee_name"] == "राम लाल"
    assert row["basic_amount"] == "27800.00"
    assert row["effective_from"] == "2031-07-01"


def test_ambiguous_narrative_employees_never_assigned_shared_values():
    words = [
        w("Increment Order", 0.05, 0.05),
        w("Employee Name", 0.05, 0.2),
        w("राम लाल", 0.3, 0.2),
        w("Employee Name", 0.05, 0.25),
        w("श्याम लाल", 0.3, 0.25),
        w("New Basic", 0.05, 0.4),
        w("27800/-", 0.3, 0.4),
        w("Effective From", 0.05, 0.5),
        w("01.07.2031", 0.3, 0.5),
    ]
    assert extract(words) == []


def test_marker_only_order_remains_source_bound_review_candidate():
    from ifms_suite import pay_orders

    extractor = getattr(pay_orders, "extract_order_candidates", None)
    assert callable(extractor)
    words = [
        w("वेतनवृद्धि आदेश", 0.05, 0.05),
        w("01.07.2031", 0.2, 0.4),
        w("27800/-", 0.7, 0.4),
    ]
    row = extractor([dict(page=8, words=words)])[0]
    assert row["effective_from"] == ""
    assert row["basic_amount"] is None
    assert row["employee_code"] == ""
    assert not row["complete"]
    assert row["evidence"] == [dict(word, page=8) for word in words]


def test_complete_orders_are_not_duplicated_as_review_candidates():
    from ifms_suite import pay_orders

    extractor = getattr(pay_orders, "extract_order_candidates", None)
    assert callable(extractor)
    assert extractor([dict(page=7, words=table())]) == []
