from ifms_suite.document_facts import facts_from_pages


def w(text, x, y, width=0.12):
    return dict(
        text=text,
        box=[
            x,
            y,
            x + (min(width, 0.07) if text.replace(".", "").isdigit() else width),
            y + 0.01,
        ],
        confidence=0.99,
    )


def slip():
    return [
        w("Pay Slip", 0.45, 0.08),
        w("EMP ID", 0.05, 0.21),
        w("RJAB203012345678", 0.21, 0.21),
        w("Month:October/2031", 0.76, 0.11),
        w("Bill No., Date", 0.53, 0.14),
        w(":123456789,30-10-2031", 0.69, 0.14),
        w("Earnings (Rs.)", 0.12, 0.45),
        w("Accounting", 0.45, 0.47),
        w("Non Accounting", 0.76, 0.47),
        w("Name", 0.06, 0.49),
        w("Name", 0.41, 0.49),
        w("Name", 0.69, 0.49),
        w("Basic Pay(100)", 0.06, 0.51),
        w("12000.00", 0.28, 0.51),
        w("RGHS(297)", 0.41, 0.51),
        w("300.00", 0.60, 0.51),
        w("Cooperative(301)", 0.69, 0.51),
        w("90.00", 0.89, 0.51),
        w("Gross Pay:12000.00", 0.05, 0.64),
        w("Total Deductions:300.00", 0.36, 0.64),
        w("Net Pay:11700.00", 0.65, 0.64),
    ]


def test_salary_slip_retains_components_and_nonaccounting_effects():
    facts = facts_from_pages([dict(page=1, words=slip())])
    assert facts["page_classifications"][0]["kind"] == "salary_slip"
    bill = facts["bills"][0]
    assert bill["complete"]
    assert bill["allowances"] == {"Basic": "12000.00"}
    assert bill["deductions"] == {"RGHS": "300.00", "Cooperative": "90.00"}
    assert bill["deduction_effects"] == {"RGHS": True, "Cooperative": False}
    assert bill["deductions_reconciled"]


def test_salary_slip_missing_amount_is_retained_as_blocked_bill():
    words = [q for q in slip() if q["text"] != "12000.00"]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert not bill["complete"]
    assert not bill["allowances_complete"]
    assert bill["printed_gross"] == "12000.00"


def test_small_lower_page_ga55_uses_printed_header_position():
    words = [
        w("GA55A", 0.45, 0.28),
        w("Employee ID", 0.50, 0.32),
        w("RJAB203012345678", 0.65, 0.32),
        w("Allowances", 0.4, 0.38),
        w("Gross", 0.56, 0.38),
        w("October", 0.05, 0.43, 0.05),
        w("2031", 0.05, 0.445, 0.05),
        w("Regular", 0.12, 0.43, 0.05),
        w("123456789", 0.20, 0.43, 0.06),
        w("Basic", 0.31, 0.43, 0.05),
        w("12000.00", 0.38, 0.43, 0.07),
        w("12000.00", 0.56, 0.43, 0.07),
    ]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert bill["identity_reliable"]
    assert bill["complete"]


def test_overlapping_independent_identity_readings_are_one_source_field():
    words = slip() + [w(":RJAB203012345678", 0.205, 0.21, 0.16)]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert bill["identity_reliable"]


def test_deduction_label_at_column_edge_does_not_become_an_earning():
    words = slip()
    words += [w("Special Fund(222)", 0.405, 0.54, 0.13), w("50.00", 0.60, 0.54)]
    words = [
        (
            dict(q, text="Total Deductions:350.00")
            if q["text"] == "Total Deductions:300.00"
            else (
                dict(q, text="Net Pay:11650.00")
                if q["text"] == "Net Pay:11700.00"
                else q
            )
        )
        for q in words
    ]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert bill["complete"]
    assert bill["deductions"]["Special Fund"] == "50.00"


def test_compact_ga55_is_recognized_from_enlarged_source_block_with_page_boxes():
    import pymupdf
    from ifms_suite.document_facts import _recognize_page

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=1000)
    calls = []

    def recognize(encoded):
        from PIL import Image
        from io import BytesIO

        im = Image.open(BytesIO(encoded))
        calls.append(im.size)
        if len(calls) == 1:
            y = 0.30 * im.height
            return [
                ([[250, y], [330, y], [330, y + 20], [250, y + 20]], "GA55A", 0.99),
                (
                    [
                        [100, 0.6 * im.height],
                        [200, 0.6 * im.height],
                        [200, 0.62 * im.height],
                        [100, 0.62 * im.height],
                    ],
                    "footer",
                    0.99,
                ),
            ], None
        return [([[10, 10], [90, 10], [90, 30], [10, 30]], "Allowances", 0.99)], None

    words = _recognize_page(page, recognize, None)
    assert len(calls) == 2
    assert calls[1][0] > calls[0][0]
    assert words[0]["text"] == "Allowances"
    assert 0.25 < words[0]["box"][1] < 0.35
    assert words[0]["source_block_box"]


def test_ga55_missing_structural_header_preserves_blocked_source_bill():
    words = [
        w("GA55A", 0.45, 0.28),
        w("October", 0.05, 0.43, 0.05),
        w("123456789", 0.2, 0.43, 0.06),
        w("UnreadableGross", 0.56, 0.38),
    ]
    facts = facts_from_pages([dict(page=1, words=words)])
    bill = facts["bills"][0]
    assert not bill["complete"]
    assert bill["bill_no"] == "123456789"
    assert bill["printed_gross"] is None
    assert bill["raw_fields"]


def test_printed_component_code_identifies_head_and_retains_literal_label():
    words = [
        dict(q, text="Uncertain label(104)") if q["text"] == "Basic Pay(100)" else q
        for q in slip()
    ]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert bill["allowances"] == {"DA": "12000.00"}
    assert any(q["text"] == "Uncertain label(104)" for q in bill["evidence"])


def test_salary_slip_identity_disagreement_and_low_confidence_remain_blocked():
    words = slip() + [w(":RJAC203012345678", 0.205, 0.21, 0.16)]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert not bill["complete"]
    assert not bill["identity_reliable"]
    words = [dict(q, confidence=0.3) if q["text"] == "12000.00" else q for q in slip()]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert not bill["complete"]
    assert bill["allowances"]["Basic"] == "12000.00"


def test_salary_slip_totals_cannot_supply_missing_component_amount():
    words = [
        dict(q, text="Gross Pay:13000.00") if q["text"] == "Gross Pay:12000.00" else q
        for q in slip()
    ]
    bill = facts_from_pages([dict(page=1, words=words)])["bills"][0]
    assert not bill["complete"]
    assert bill["allowances"]["Basic"] == "12000.00"
    assert bill["printed_gross"] == "13000.00"
