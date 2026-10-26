import shutil
import pytest
from ifms_suite.documents import ocr_document


def test_scan_ocr_retains_a_separate_searchable_derivative():
    import pymupdf

    if not shutil.which("tesseract"):
        pytest.skip("Local Tesseract executable not installed")
    source = pymupdf.open()
    p = source.new_page()
    p.insert_text((50, 60), "BASIC 50000.00 DA 27500.00", fontsize=20)
    image = p.get_pixmap(dpi=150).tobytes("png")
    scan = pymupdf.open()
    p = scan.new_page()
    p.insert_image(p.rect, stream=image)
    data = scan.tobytes()
    scan.close()
    source.close()
    texts, derivative = ocr_document(data)
    assert "50000" in texts[0]
    assert derivative.startswith(b"%PDF")
    with pymupdf.open(stream=data, filetype="pdf") as original:
        assert original[0].get_text() == ""


def test_scan_with_a_digital_header_still_receives_ocr(client=None):
    import pymupdf
    from ifms_suite.documents import ocr_document

    if not shutil.which("tesseract"):
        pytest.skip("Local Tesseract executable not installed")
    source = pymupdf.open()
    p = source.new_page()
    p.insert_text((50, 60), "BASIC 50000.00 DA 27500.00", fontsize=20)
    image = p.get_pixmap(dpi=150).tobytes("png")
    scan = pymupdf.open()
    p = scan.new_page()
    p.insert_image(p.rect, stream=image)
    p.insert_text((30, 20), "Digitally signed document reference for payroll review")
    data = scan.tobytes()
    scan.close()
    source.close()
    texts, _ = ocr_document(data)
    assert "50000" in texts[0]
