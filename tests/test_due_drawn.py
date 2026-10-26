from ifms_suite.due_drawn import parse_statement_table

def test_due_drawn_arithmetic_detects_wrong_difference_without_correcting_source():
    rows=[['Sr','Month','Pay Due','','','','Pay Drawn','','','','Pay Difference','','',''],['','','Basic','DA','HRA','Total','Basic','DA','HRA','Total','Basic','DA','HRA','Total'],['1','Jan-2025','50000','27500','10000','87500','50000','26500','10000','86500','0','1000','0','999']]
    r=parse_statement_table(rows)
    assert len(r)==1
    assert r[0]['printed_difference']=='999.00'
    assert r[0]['calculated_difference']=='1000.00'
    assert any('difference' in i.lower() for i in r[0]['issues'])
    assert r[0]['month']=='2025-01'

def test_unknown_or_incomplete_layout_is_not_guessed():
    assert parse_statement_table([['Month','Amount'],['Jan-2025','1000']])==[]

def test_period_amounts_are_not_prorated_a_second_time():
    from ifms_suite.calculation import calculate_claim
    r=calculate_claim('2025-03-13','2025-03-31',[dict(start='2025-03-13',end='2025-03-31',basis='fixed',due_basis='period',due_amount='1000',drawn_amount='800',drawn_basis='period')])
    assert r['total']=='200.00'
