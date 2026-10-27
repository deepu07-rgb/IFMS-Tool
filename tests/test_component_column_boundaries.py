import pytest
from ifms_engine.employee_parser import EmployeeParser

def word(text,x,y=295,width=20):
    return dict(text=text,x0=x,x1=x+width,y0=y,y1=y+8,page_no=1)

@pytest.mark.parametrize('head,normalized', [('SIP','sip'),('GPF','gpf')])
def test_orphan_multiline_label_does_not_prefix_next_column_component(head,normalized):
    # A left-column Advance Salary continuation shares a baseline with right SIP.
    words=[word('Advance',469,286,25),word('8691',519,286,14),
           word('Salary',469,295,18),word(head,571,295,10),word('3000',612,295,14)]
    components=EmployeeParser.parse_components(words,'deduction')
    assert [(c.normalized_head,c.amount) for c in components]==[('advance_salary',8691),(normalized,3000)]
    assert components[-1].raw_head==head
    assert components[-1].source_y==295

def test_legitimate_advance_salary_label_and_signed_amount_are_retained():
    words=[word('Advance',30,width=25),word('Salary',58,width=18),word('-125',110,width=20)]
    components=EmployeeParser.parse_components(words,'deduction')
    assert len(components)==1
    assert components[0].raw_head=='Advance Salary'
    assert components[0].normalized_head=='advance_salary'
    assert components[0].amount==-125
