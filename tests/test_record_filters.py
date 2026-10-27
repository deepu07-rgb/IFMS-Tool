import pytest


def records():
    return [
        dict(
            document="outer.pdf",
            document_type="outer",
            employee_code="",
            pay_month="2026-07",
            bill_type="Salary",
            bill_no="A",
            allowances={"BASIC": "100", "ROP": "-10"},
            deductions={"GPF": "5"},
            gross="90",
            net="85",
        ),
        dict(
            document="ga.pdf",
            document_type="ga55",
            employee_code="SYNTHETIC",
            pay_month="2026-08",
            bill_type="Regular Salary",
            bill_no="B",
            allowances={"BASIC": "200", "HRA": "40"},
            deductions={},
            gross="240",
            net=None,
        ),
    ]


def test_filters_apply_together_keep_negative_and_never_invent_missing_zero():
    from ifms_suite.record_filters import filter_records

    assert (
        len(
            filter_records(
                records(),
                {
                    "kind": "outer",
                    "amount_field": "allowance:ROP",
                    "minimum": "-11",
                    "maximum": "-9",
                },
            )
        )
        == 1
    )
    assert (
        filter_records(
            records(),
            {
                "employee": "SYNTHETIC",
                "month_from": "2026-08",
                "amount_field": "net",
                "maximum": "0",
            },
        )
        == []
    )
    assert filter_records(records(), {"search": "no such document"}) == []
    with pytest.raises(ValueError):
        filter_records(records(), {"amount_field": "gross", "minimum": "abc"})
