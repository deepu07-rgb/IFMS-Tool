from ifms_suite.document_facts import facts_from_pages


def w(text, x, y, width=0.05):
    return {"text": text, "box": [x, y, x + width, y + 0.01], "confidence": 1}


def page(words, number=1):
    return {"page": number, "words": words}


def header(employee="RJAB203012345678"):
    return [
        w("GA55A", 0.45, 0.05),
        w("Employee ID", 0.5, 0.1),
        w(employee, 0.65, 0.1),
        w("Allowances", 0.4, 0.2),
        w("Gross", 0.56, 0.2),
        w("Pay Month", 0.05, 0.2),
        w("Bill No.", 0.18, 0.2),
    ]


def test_signed_heads_and_continuation_reconcile_only_with_identity_evidence():
    first = page(
        header()
        + [
            w("October", 0.05, 0.8),
            w("2031", 0.05, 0.815),
            w("Regular", 0.12, 0.8),
            w("123456789", 0.18, 0.8),
            w("Basic", 0.31, 0.78),
            w("18000.00", 0.37, 0.78),
            w("ROP", 0.31, 0.81),
            w("-200.00", 0.37, 0.81),
            w("18100.00", 0.56, 0.78),
        ]
    )
    second = page(header() + [w("HDA", 0.31, 0.25), w("300.00", 0.37, 0.25)], 2)
    bill = facts_from_pages([first, second])["bills"][0]
    assert bill["complete"]
    assert bill["allowances"] == {
        "Basic": "18000.00",
        "ROP": "-200.00",
        "HDA": "300.00",
    }
    assert bill["source_pages"] == [1, 2]
    assert bill["employee_code"] == "RJAB203012345678"
    assert bill["pay_month"] == "2031-10"


def test_different_employee_continuation_is_not_attached():
    a = page(
        header()
        + [
            w("October", 0.05, 0.8),
            w("2031", 0.05, 0.815),
            w("123456789", 0.18, 0.8),
            w("Basic", 0.31, 0.78),
            w("18000.00", 0.37, 0.78),
            w("18300.00", 0.56, 0.78),
        ]
    )
    b = page(
        header("RJAB203098765432") + [w("HDA", 0.31, 0.25), w("300.00", 0.37, 0.25)], 2
    )
    result = facts_from_pages([a, b])
    assert not result["bills"][0]["complete"]
    assert result["bills"][0]["source_pages"] == [1]


def test_order_uses_employee_row_date_and_rate_not_issue_date():
    result = facts_from_pages(
        [
            page(
                [
                    w("09/12/2031", 0.7, 0.05),
                    w("HOUSE", 0.8, 0.2),
                    w("RENT", 0.8, 0.22),
                    w("RJAB203012345678", 0.35, 0.4),
                    w("07.11.2031", 0.8, 0.405),
                    w("18%", 0.9, 0.407),
                ]
            )
        ]
    )
    assert result["orders"][0]["effective_from"] == "2031-11-07"
    assert result["orders"][0]["rate"] == "18"
    assert result["orders"][0]["employee_code"] == "RJAB203012345678"


def test_shifted_continuation_gross_does_not_absorb_new_bills_or_annual_totals():
    first = page(
        header()
        + [
            w("October", 0.05, 0.8),
            w("2031", 0.05, 0.815),
            w("Regular", 0.12, 0.8),
            w("123456789", 0.18, 0.8),
            w("Basic", 0.31, 0.78),
            w("18000.00", 0.37, 0.78),
            w("18300.00", 0.56, 0.78),
            w("2031-32", 0.8, 0.08),
            w("GroupName:Demo", 0.55, 0.96),
        ]
    )
    second = page(
        [
            w("GA55A", 0.45, 0.05),
            w("2031-32", 0.8, 0.08),
            w("GroupName:Demo", 0.55, 0.96),
            w("HDA", 0.31, 0.15),
            w("300.00", 0.37, 0.15),
            w("18300.00", 0.556, 0.23),
            w("Basic", 0.31, 0.25),
            w("18000.00", 0.37, 0.25),
            w("HDA", 0.43, 0.27),
            w("300.00", 0.49, 0.27),
            w("November", 0.05, 0.28),
            w("2031", 0.05, 0.295),
            w("Regular", 0.12, 0.28),
            w("987654321", 0.18, 0.28),
            w("Total Allowances", 0.1, 0.5),
            w("Basic", 0.31, 0.6),
            w("999999.00", 0.37, 0.6),
        ],
        2,
    )
    result = facts_from_pages([first, second])
    assert len(result["bills"]) == 2
    assert all(b["complete"] for b in result["bills"])
    assert result["bills"][0]["source_pages"] == [1, 2]
    assert result["bills"][1]["employee_code"] == "RJAB203012345678"
    assert any(
        e["text"] == "RJAB203012345678" and e["page"] == 1
        for e in result["bills"][1]["evidence"]
    )
    assert result["bills"][1]["allowances"] == {"Basic": "18000.00", "HDA": "300.00"}


def test_bill_number_column_is_distinct_from_type_even_when_header_is_offset():
    words = header() + [
        w("October", 0.05, 0.6),
        w("2031", 0.05, 0.62),
        w("Regular", 0.115, 0.6),
        w("987654321", 0.172, 0.6),
        w("Basic", 0.31, 0.58),
        w("18000.00", 0.37, 0.58),
        w("18000.00", 0.56, 0.58),
    ]
    bill = facts_from_pages([page(words)])["bills"][0]
    assert bill["bill_no"] == "987654321"
    assert bill["bill_type"] == "Regular Salary"
    assert bill["complete"]


def test_unknown_month_bill_is_retained_as_a_blocker():
    words = header() + [
        w("Oct?ber", 0.05, 0.6),
        w("2031", 0.05, 0.62),
        w("Regular", 0.115, 0.6),
        w("987654321", 0.172, 0.6),
        w("Basic", 0.31, 0.58),
        w("18000.00", 0.37, 0.58),
        w("18000.00", 0.56, 0.58),
    ]
    result = facts_from_pages([page(words)])
    assert len(result["bills"]) == 1
    assert result["bills"][0]["pay_month"] == ""
    assert not result["bills"][0]["complete"]


def test_sloped_order_rows_do_not_take_adjacent_employee_rate():
    result = facts_from_pages(
        [
            page(
                [
                    w("HOUSE", 0.8, 0.2),
                    w("RENT", 0.8, 0.22),
                    w("RJAB203012345678", 0.35, 0.4),
                    w("RJAB203012345679", 0.35, 0.42),
                    w("07.11.2031", 0.8, 0.408),
                    w("08.11.2031", 0.8, 0.428),
                    w("10%", 0.9, 0.410),
                    w("18%", 0.9, 0.430),
                ]
            )
        ]
    )
    assert [
        (o["employee_code"], o["effective_from"], o["rate"]) for o in result["orders"]
    ] == [
        ("RJAB203012345678", "2031-11-07", "10"),
        ("RJAB203012345679", "2031-11-08", "18"),
    ]


def test_extract_document_facts_reads_pdf_bytes_and_keeps_page_evidence():
    import pymupdf
    from ifms_suite import document_facts

    pdf = pymupdf.open()
    p = pdf.new_page(width=1000, height=1000)
    for text, x, y in [
        ("GA55A", 450, 50),
        ("RJAB203012345678", 650, 100),
        ("Allowances", 400, 200),
        ("Gross", 560, 200),
        ("October", 50, 600),
        ("2031", 50, 620),
        ("Regular", 115, 600),
        ("987654321", 172, 600),
        ("Basic", 310, 580),
        ("18000.00", 370, 580),
        ("18000.00", 560, 580),
    ]:
        p.insert_text((x, y), text, fontsize=10)
    result = document_facts.extract_document_facts(pdf.tobytes())
    assert result["bills"][0]["complete"]
    assert all(e["page"] == 1 for e in result["bills"][0]["evidence"])


def test_unreadable_amount_cannot_borrow_money_from_adjacent_allowance_lane():
    words = header() + [
        w("October", 0.05, 0.6),
        w("2031", 0.05, 0.62),
        w("Regular", 0.115, 0.6),
        w("987654321", 0.172, 0.6),
        w("DA", 0.43, 0.575),
        w("10000.00", 0.49, 0.575),
        w("Basic", 0.31, 0.58),
        w("18000:00", 0.37, 0.58),
        w("20000.00", 0.56, 0.57),
    ]
    result = facts_from_pages([page(words)])
    bill = result["bills"][0]
    assert "Basic" not in bill["allowances"]
    assert not bill["complete"]


def test_bill_type_can_begin_above_its_printed_gross():
    words = header() + [
        w("October", 0.05, 0.64),
        w("2031", 0.05, 0.66),
        w("Surrender", 0.115, 0.6),
        w("Bill", 0.115, 0.64),
        w("987654321", 0.172, 0.64),
        w("Basic", 0.31, 0.64),
        w("18000.00", 0.37, 0.64),
        w("18000.00", 0.56, 0.62),
    ]
    result = facts_from_pages([page(words)])
    assert "Surrender" in result["bills"][0]["bill_type"]


def test_allowance_geometry_excludes_gross_box_overlapping_column_edge():
    words = header() + [
        w("October", 0.05, 0.6),
        w("2031", 0.05, 0.62),
        w("Regular", 0.115, 0.6),
        w("987654321", 0.172, 0.6),
        w("Basic", 0.31, 0.58),
        w("18000.00", 0.37, 0.58),
        w("18000.00", 0.549, 0.57),
    ]
    result = facts_from_pages([page(words)])
    assert result["bills"][0]["complete"]


def test_tesseract_word_adapter_does_not_require_external_tsv_config():
    import pytest
    import pymupdf
    from PIL import Image
    from ifms_suite.documents import ocr_runtime
    from ifms_suite.document_facts import _tesseract_words

    try:
        executable, env, _ = ocr_runtime()
    except ValueError:
        pytest.skip("Local Tesseract unavailable")
    with pymupdf.open() as pdf:
        p = pdf.new_page(width=300, height=70)
        p.insert_text((15, 45), "12345.00", fontsize=32)
        pix = p.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        assert (
            "".join(w["text"] for w in _tesseract_words(img, executable, env, 7))
            == "12345.00"
        )


def test_missing_printed_models_returns_explicit_issues_instead_of_crashing(
    monkeypatch,
):
    import io
    import sys
    from types import SimpleNamespace
    import pymupdf
    from PIL import Image
    from ifms_suite import document_facts, documents

    def missing_models(**kwargs):
        raise OSError("Model file unavailable")

    def missing_tesseract():
        raise ValueError("Tesseract unavailable")

    monkeypatch.setitem(
        sys.modules, "rapidocr_onnxruntime", SimpleNamespace(RapidOCR=missing_models)
    )
    monkeypatch.setattr(documents, "ocr_runtime", missing_tesseract)
    encoded = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(encoded, "PNG")
    with pymupdf.open() as pdf:
        p = pdf.new_page(width=100, height=100)
        p.insert_image(p.rect, stream=encoded.getvalue())
        result = document_facts.extract_document_facts(pdf.tobytes())
    assert result["bills"] == []
    assert any("recognizer unavailable" in i["issue"] for i in result["issues"])


def test_conflicting_header_identities_cannot_inherit_previous_employee():
    first = page(
        header()
        + [
            w("October", 0.05, 0.8),
            w("2031", 0.05, 0.815),
            w("123456789", 0.18, 0.8),
            w("Basic", 0.31, 0.78),
            w("18000.00", 0.37, 0.78),
            w("18300.00", 0.56, 0.78),
            w("2031-32", 0.8, 0.08),
            w("GroupName:Demo", 0.55, 0.96),
        ]
    )
    second = page(
        header()
        + [
            w("RJAB203098765432", 0.65, 0.12),
            w("2031-32", 0.8, 0.08),
            w("GroupName:Demo", 0.55, 0.96),
            w("HDA", 0.31, 0.25),
            w("300.00", 0.37, 0.25),
        ],
        2,
    )
    result = facts_from_pages([first, second])
    assert result["bills"][0]["source_pages"] == [1]
    assert not result["bills"][0]["complete"]
