"""Synthetic financial rows; no employee fixture data is embedded here."""
import pytest

from parser import _parse_emp_block


@pytest.mark.parametrize(
    'net, net_x',
    [(123456.0, 712.6), (1234567.0, 709.2), (12345678.0, 705.9)],
)
def test_right_aligned_net_stays_separate_from_deduction(net, net_x):
    deduction = 4321
    gross = net + deduction
    words = [
        {'text': str(gross), 'x0': 424.8, 'top': 230.0},
        {'text': str(deduction), 'x0': 686.8, 'top': 230.0},
        {'text': f'{net:.2f}', 'x0': net_x, 'top': 230.0},
    ]

    employee = _parse_emp_block(1, words)

    assert employee['sum_deduction'] == deduction
    assert employee['net_total'] == net
    assert employee['gross_amount'] == gross


@pytest.mark.parametrize('summary_y', [179.6, 189.7])
def test_early_bill_summary_ends_employee_data(summary_y):
    from parser import _find_data_boundary

    words = [
        {'text': 'Gross', 'x0': 427.2, 'top': 68.1},
        {'text': 'Amount', 'x0': 425.4, 'top': 76.3},
        {'text': 'Gross', 'x0': 28.1, 'top': summary_y},
        {'text': 'Amount:', 'x0': 47.1, 'top': summary_y},
        {'text': 'Certificates:', 'x0': 28.1, 'top': 313.1},
    ]

    assert _find_data_boundary(words) == summary_y
