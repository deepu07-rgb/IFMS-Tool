import json
import os

from ifms_engine.header_parser import HeaderParser
from ifms_engine.pdf_reader import PDFReader


PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_fixtures", "ifms_inner_sheets")


def _parse_pdf_header(pdf_name: str):
    path = os.path.join(PDF_DIR, pdf_name)
    reader = PDFReader(path)
    words = reader.extract_words()
    meta = HeaderParser.extract_metadata(words)
    reader.close()
    return meta


def test_v2_header_parser_key_samples():
    sample_expectations = {
        "14.pdf": {  # NEW RT 2025
            "group_name": "NEW RT 2025",
            "bill_no": "509110635",
        },
        "10.pdf": {  # COMMISSIONERATE JDR
            "group_name": "COMMISSIONERATE JDR",
            "bill_no": "508970353",
        },
        "6.pdf": {  # Wireless-I
            "group_name": "Wireless-I",
            "budget_head": "2055-00-114-01-00/SF/Voted",
        },
        "9.pdf": {  # OFFICE STAFF
            "group_name": "OFFICE STAFF",
        },
    }

    for pdf_name, expected in sample_expectations.items():
        meta = _parse_pdf_header(pdf_name)
        print(f"\n[{pdf_name}] HEADER:")
        print(json.dumps(meta, indent=2, ensure_ascii=False))

        assert meta["group_name"], f"group_name missing for {pdf_name}"
        assert meta["reference_no"], f"reference_no missing for {pdf_name}"
        assert meta["month_year"], f"month_year missing for {pdf_name}"
        assert meta["bill_no"], f"bill_no missing for {pdf_name}"
        assert meta["bill_date"], f"bill_date missing for {pdf_name}"
        assert meta["office_id"], f"office_id missing for {pdf_name}"
        assert meta["ddo_code"], f"ddo_code missing for {pdf_name}"
        assert meta["page_count"] > 0, f"page_count missing for {pdf_name}"
        assert meta["print_date_time"], f"print_date_time missing for {pdf_name}"

        for k, v in expected.items():
            assert meta.get(k) == v, f"{k} mismatch for {pdf_name}: {meta.get(k)} != {v}"

        # TODO: parser/header accuracy hardening for wider office/DDO variations will be added later.
