"""Independent generated PDFs: no private source documents in the test suite."""

import importlib

import pymupdf

COLUMNS = [
    "SrNo",
    "BillNo",
    "BillDate",
    "Type",
    "Month",
    "Year",
    "Gross",
    "Net",
    "IncomeTax",
    "TVNo",
    "TokenNo",
    "TVDate",
    "Status",
    "GroupName",
    "ECSNo",
]
HEADERS = [
    "Sr. No.",
    "Bill NO.",
    "Bill DATE",
    "Bill Type",
    "Bill MONTH",
    "Bill YEAR",
    "Gross Amount",
    "Net Amount",
    "Income Tax",
    "TV No.",
    "Token No",
    "TV Date",
    "Bill Status",
    "Group Name",
    "ECS NO",
]
VALUES = [
    "1",
    "0000123",
    "01/09/2026",
    "Salary Arrear",
    "September",
    "2026",
    "1,234.50",
    "1,200.00",
    "34.50",
    "0008",
    "0009",
    "02/09/2026",
    "Voucher Generated",
    "OFFICE STAFF",
    "EPV000123\n456789\n012345",
]


def make_pdf(pages, merged=False):
    doc = pymupdf.open()
    headers = HEADERS.copy()
    if merged:
        headers[1:3] = ["Bill NO.\nBill DATE"]
    count = len(headers)
    for bands in pages:
        page = doc.new_page(width=1600, height=500)
        for i, header in enumerate(headers):
            page.insert_text((22 + i * 102, 55), header, fontsize=7)
        for y in [40, 75] + [75 + 45 * (i + 1) for i in range(len(bands))]:
            page.draw_line((20, y), (20 + count * 102, y))
        for j, original in enumerate(bands):
            row = list(original)
            if merged:
                row[1:3] = [row[1] + "\n" + row[2]]
            for i, value in enumerate(row):
                if value:
                    page.insert_text((22 + i * 102, 88 + j * 45), value, fontsize=7)
    data = doc.tobytes()
    doc.close()
    return data


def parse(data):
    # An explicit assertion gives a meaningful first red test for the new module.
    import importlib.util

    assert importlib.util.find_spec(
        "ifms_suite.bill_register_parser"
    ), "bill register parser is not implemented"
    return importlib.import_module("ifms_suite.bill_register_parser").parse_bill_pdf(
        data
    )


def test_preserves_source_strings_and_all_fifteen_columns():
    result = parse(make_pdf([[VALUES]]))
    assert result["columns"] == COLUMNS
    assert result["rows"] == [
        dict(
            zip(
                COLUMNS,
                [
                    v.replace("\n", "") if k == "ECSNo" else v
                    for k, v in zip(COLUMNS, VALUES)
                ],
            )
        )
    ]
    assert result["evidence"][0]["source_pages"] == [1]
    assert result["raw_pages"] and result["method"] == "digital_geometry"
    assert not result["requires_review"]


def test_combined_bill_number_date_column_is_split_by_geometry():
    result = parse(make_pdf([[VALUES]], merged=True))
    assert result["rows"][0]["BillNo"] == "0000123"
    assert result["rows"][0]["BillDate"] == "01/09/2026"


def test_page_top_ecs_fragment_is_preserved_with_both_source_pages():
    first = VALUES.copy()
    first[-1] = "EPV000123\n456789"
    continuation = [""] * 15
    continuation[-1] = "012345"
    second = VALUES.copy()
    second[0] = "2"
    result = parse(make_pdf([[first], [continuation, second]], merged=True))
    assert len(result["rows"]) == 2
    assert result["rows"][0]["ECSNo"] == "EPV000123456789012345"
    assert result["evidence"][0]["source_pages"] == [1, 2]
    assert any(
        f["text"] == "012345" and f["page"] == 2
        for f in result["evidence"][0]["fragments"]
    )
    assert result["issues"] and result["requires_review"]


def test_unrelated_orphan_is_retained_as_issue_without_joining():
    first = VALUES.copy()
    orphan = [""] * 15
    orphan[6] = "98765"
    result = parse(make_pdf([[first], [orphan, VALUES]], merged=True))
    assert result["rows"][0]["Gross"] == "1,234.50"
    assert result["rows"][0]["ECSNo"] == "EPV000123456789012345"
    assert result["issues"] and result["requires_review"]
    assert "98765" in result["raw_pages"][1]


def test_unknown_layout_preserves_raw_text_without_inventing_rows():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Unrecognised bill source 001234")
    result = parse(doc.tobytes())
    assert not result["rows"]
    assert "001234" in result["raw_pages"][0]
    assert result["issues"] and result["requires_review"]


def test_invalid_pdf_returns_reviewable_issue():
    result = parse(b"not a PDF")
    assert result["issues"] and result["requires_review"]
    assert not result["rows"]


def test_uncertain_numeric_identifier_is_retained_and_flagged_without_guessing():
    row = VALUES.copy()
    row[1] = "00O0123"
    result = parse(make_pdf([[row]]))
    assert result["rows"][0]["BillNo"] == "00O0123"
    assert result["requires_review"]
    assert any("BillNo" in issue for issue in result["issues"])


def test_image_rules_with_digital_ocr_layer_extracts_rows_without_vector_drawings():
    source = pymupdf.open(stream=make_pdf([[VALUES]], merged=True), filetype="pdf")
    derivative = pymupdf.open()
    for original in source:
        page = derivative.new_page(
            width=original.rect.width, height=original.rect.height
        )
        page.insert_image(page.rect, stream=original.get_pixmap(dpi=144).tobytes("png"))
        for word in original.get_text("words"):
            page.insert_text((word[0], word[3] - 2), word[4], fontsize=7, render_mode=3)
        assert not page.get_drawings()
    result = parse(derivative.tobytes())
    assert len(result["rows"]) == 1
    assert result["rows"][0]["BillNo"] == "0000123"
    assert result["rows"][0]["Gross"] == "1,234.50"
    assert result["rows"][0]["ECSNo"] == "EPV000123456789012345"
    assert result["requires_review"]
    assert any("image" in issue.lower() for issue in result["issues"])


def test_invalid_observed_date_remains_unchanged_and_is_flagged():
    row = VALUES.copy()
    row[2] = "46/09/2026"
    result = parse(make_pdf([[row]], merged=True))
    assert result["rows"][0]["BillDate"] == "46/09/2026"
    assert result["requires_review"]
    assert any(
        "BillDate" in issue and "date" in issue.lower() for issue in result["issues"]
    )
