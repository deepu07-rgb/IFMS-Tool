"""Enlargement must preserve conflicting original financial readings."""


def test_enlarged_source_block_keeps_original_reliable_numeric_candidate():
    import pymupdf
    from PIL import Image
    from io import BytesIO
    from ifms_suite.document_facts import _recognize_page

    document = pymupdf.open()
    page = document.new_page(width=600, height=1000)
    count = 0

    def recognizer(encoded, **options):
        nonlocal count
        count += 1
        image = Image.open(BytesIO(encoded))
        width, height = image.size
        if count == 1:
            return [
                (
                    [
                        [width * 0.44, height * 0.30],
                        [width * 0.55, height * 0.30],
                        [width * 0.55, height * 0.32],
                        [width * 0.44, height * 0.32],
                    ],
                    "GA55A",
                    0.99,
                ),
                (
                    [
                        [width * 0.40, height * 0.40],
                        [width * 0.47, height * 0.40],
                        [width * 0.47, height * 0.42],
                        [width * 0.40, height * 0.42],
                    ],
                    "100.00",
                    0.99,
                ),
            ], None
        if count == 2:
            # Full source y .40-.42 maps into crop y .125-.145 / .17.
            return [
                (
                    [
                        [width * 0.40, height * (0.125 / 0.17)],
                        [width * 0.47, height * (0.125 / 0.17)],
                        [width * 0.47, height * (0.145 / 0.17)],
                        [width * 0.40, height * (0.145 / 0.17)],
                    ],
                    "200.00",
                    0.99,
                )
            ], None
        return [], None

    words = _recognize_page(page, recognizer, None)
    financial = [w for w in words if w["text"] in ("100.00", "200.00")]
    candidates = [
        c.get("text") for w in financial for c in w.get("recognition_candidates", [])
    ]
    assert "100.00" in candidates
    assert "200.00" in candidates
    assert any(w.get("recognition_conflict") for w in financial)
