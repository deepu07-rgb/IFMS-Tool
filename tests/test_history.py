import sqlite3,json
import pytest
from ifms_suite.history import prepare_segments

def test_rate_and_pay_changes_split_with_actual_drawn_and_settlement():
    rates=[dict(allowance='DA',effective_from='2025-01-01',rate='55',reference='OrderA'),dict(allowance='DA',effective_from='2025-02-15',rate='57',reference='OrderB')]
    pay=[dict(effective_from='2025-01-01',basic='50000'),dict(effective_from='2025-03-01',basic='51000')]
    payments=[dict(id=i,pay_month=month,bill_type='Regular Salary',bill_no=str(i),allowances={'DA':amount}) for i,(month,amount) in enumerate([('2025-01','26500'),('2025-02','26500'),('2025-03','27030')],1)]
    payments.append(dict(id=4,pay_month='2025-04',bill_type='DA',bill_no='4',allowances={'DA':'1000'},entitlement_period={'start':'2025-01-01','end':'2025-01-31'}))
    rows=prepare_segments('2025-01-01','2025-03-31','DA',rates,pay,payments,{'basis':'basic'})
    assert len(rows)==4
    assert rows[0]['prior_settlement']=='1000.00'
    assert rows[1]['end']=='2025-02-14'
    assert rows[2]['due_rate']=='57'
    assert rows[-1]['basic']=='51000'
    assert rows[-1]['drawn_amount']=='27030'

def test_missing_history_and_unallocated_arrear_are_blockers():
    args=('2025-01-01','2025-01-31','DA',[dict(allowance='DA',effective_from='2025-01-01',rate='55',reference='Order')],[dict(effective_from='2025-01-01',basic='50000')])
    with pytest.raises(ValueError,match='drawn'):prepare_segments(*args,[],{'basis':'basic'})
    p=[dict(pay_month='2025-01',bill_type='Regular Salary',bill_no='1',allowances={'DA':'26500'}),dict(pay_month='2025-04',bill_type='DA',bill_no='2',allowances={'DA':'1000'})]
    with pytest.raises(ValueError,match='Allocate'):prepare_segments(*args,p,{'basis':'basic'})

def test_leave_encashment_da_is_not_a_regular_salary_arrear_settlement():
    rates=[dict(allowance='DA',effective_from='2025-01-01',rate='55',reference='Order')]
    pay=[dict(effective_from='2025-01-01',basic='50000')]
    payments=[dict(id=1,pay_month='2025-01',bill_type='Regular Salary',bill_no='R1',allowances={'DA':'26500'}),dict(id=2,pay_month='2025-01',bill_type='Surrender Bill(15 days)',bill_no='S1',allowances={'DA':'13250'})]
    rows=prepare_segments('2025-01-01','2025-01-31','DA',rates,pay,payments,{'basis':'basic'})
    assert rows[0]['prior_settlement']=='0.00'
