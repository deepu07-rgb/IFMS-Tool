"""Independent synthetic truth, deliberately wrong digits and missing output."""

import pytest


def test_exact_fields_and_character_accuracy_keep_missing_fields_in_denominator():
    from ifms_suite.ocr_quality import score_ocr

    truth = [
        dict(field_id="a", text="1234", category="digits", medium="handwritten"),
        dict(field_id="b", text="2026-07", category="date", medium="printed"),
        dict(field_id="c", text="RJ01", category="identity", medium="mixed"),
    ]
    predictions = [
        dict(field_id="a", text="1235", origin="machine", confidence=0.999),
        dict(field_id="b", text="2026-07", origin="machine"),
        dict(field_id="c", text="RJ01", origin="human"),
    ]
    result = score_ocr(truth, predictions)
    assert result["overall"]["fields_expected"] == 3
    assert result["overall"]["fields_exact"] == 1
    assert result["overall"]["field_accuracy"] == pytest.approx(1 / 3)
    assert result["overall"]["missing_fields"] == 1
    assert result["overall"]["character_accuracy"] == pytest.approx(10 / 15)
    assert result["overall"]["character_edits"] == 5
    assert result["ignored_human_predictions"] == 1
    assert result["by_medium"]["handwritten"]["field_accuracy"] == 0
    assert result["by_category"]["date"]["field_accuracy"] == 1
    assert result["by_medium"]["mixed"]["missing_fields"] == 1
    assert (
        result["by_medium_and_category"]["handwritten"]["digits"]["field_accuracy"] == 0
    )


def test_no_normalization_of_critical_digits_dates_or_identity():
    from ifms_suite.ocr_quality import score_ocr

    truth = [
        dict(field_id="n", text="1,234", category="digits", medium="printed"),
        dict(field_id="d", text="01/07/2026", category="date", medium="printed"),
        dict(field_id="i", text="RJ01", category="identity", medium="printed"),
    ]
    predictions = [
        dict(field_id="n", text="1234", origin="machine"),
        dict(field_id="d", text="2026-07-01", origin="machine"),
        dict(field_id="i", text="rj01", origin="machine"),
        dict(field_id="extra", text="999", origin="machine"),
    ]
    result = score_ocr(truth, predictions)
    assert result["overall"]["field_accuracy"] == 0
    assert result["unexpected_machine_fields"] == ["extra"]
    assert result["overall"]["missing_fields"] == 0


def test_machine_prediction_not_replaced_by_human_correction():
    from ifms_suite.ocr_quality import score_ocr

    truth = [dict(field_id="a", text="100", category="digits", medium="handwritten")]
    result = score_ocr(
        truth,
        [
            dict(field_id="a", text="1O0", origin="machine"),
            dict(field_id="a", text="100", origin="human"),
        ],
    )
    assert result["overall"]["field_accuracy"] == 0
    assert result["overall"]["character_accuracy"] == pytest.approx(2 / 3)
    with pytest.raises(ValueError):
        score_ocr(truth, [dict(field_id="a", text="100")])
    with pytest.raises(ValueError):
        score_ocr(truth, [dict(field_id="a", text="100", origin="machine")] * 2)
