import io
from test_suite_workflow import client

def test_ga55_review_enforces_cross_import_bill_identity(client):
    import pymupdf
    def upload(text):
        d=pymupdf.open();page=d.new_page();page.insert_text((30,40),text);data=d.tobytes();d.close()
        return client.post('/suite/api/imports',data={'kind':'ga55','file':(io.BytesIO(data),'ga.pdf')}).json['id']
    first=upload('First version');second=upload('Different scan of same payment')
    p=dict(reviewed=True,employee_code='rj1',payments=[dict(bill_no='B1',pay_month='2025-01',bill_type='Regular Salary',allowances={'DA':'100'})])
    assert client.post(f'/suite/api/imports/{first}/review',json=p).status_code==200
    assert client.post(f'/suite/api/imports/{second}/review',json=p).status_code==400
    assert len(client.get('/suite/api/payments?employee_code=RJ1').json)==1

def test_reviewed_payment_reconciles_informational_deductions_explicitly(client):
    p=dict(employee_code='RJ1',pay_month='2025-01',bill_type='Regular Salary',bill_no='B2',reviewed=True,reference='Source',allowances={'Basic':'50000'},deductions={'GPF':'1000','Advance Salary':'2000'},printed_gross='50000',printed_deductions='1000',printed_net='49000')
    assert client.post('/suite/api/payments/manual',json=p).status_code==400
    p['deduction_effects']={'Advance Salary':False,'GPF':True}
    assert client.post('/suite/api/payments/manual',json=p).status_code==201

def test_manual_review_batch_rolls_back_if_any_bill_is_duplicate(client):
    base=dict(employee_code='RJ1',pay_month='2025-01',bill_type='Regular Salary',bill_no='B1',allowances={'DA':'100'},reviewed=True,reference='Bill')
    client.post('/suite/api/payments/manual',json=base)
    new=dict(base,bill_no='B2')
    r=client.post('/suite/api/payments/review_batch',json=dict(employee_code='RJ1',reference='Bills',reviewed=True,payments=[new,base]))
    assert r.status_code==400
    assert len(client.get('/suite/api/payments?employee_code=RJ1').json)==1
