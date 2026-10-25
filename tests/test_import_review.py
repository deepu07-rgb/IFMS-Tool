import io
from test_suite_workflow import client

def test_ga55_import_is_duplicate_safe_and_review_required(client):
    import pymupdf
    d=pymupdf.open();p=d.new_page();p.insert_text((30,40),'March\n2025\nRegular Salary\n123456789\nBasic\n50000.00\nDA\n26500.00\n76,500.00\nGPF\n1000.00\n1,000.00\n75,500.00');data=d.tobytes();d.close()
    a=client.post('/suite/api/imports',data={'kind':'ga55','file':(io.BytesIO(data),'ga.pdf')})
    assert a.status_code==201
    assert a.json['payload']['ga55']['payments'][0]['allowances']['Basic']=='50000.00'
    b=client.post('/suite/api/imports',data={'kind':'ga55','file':(io.BytesIO(data),'same.pdf')})
    assert b.json['duplicate'] is True
    assert client.post(f"/suite/api/imports/{a.json['id']}/review",json={'employee_code':'RJ1','payments':[]}).status_code==400

def test_group_snapshot_retains_raw_and_conflicts(client):
    r=client.post('/suite/api/group_import',json={'records':[{'employeeCode':'RJ1','employeeName':'A'},{'employeeCode':'RJ1','employeeName':'B'}]})
    assert r.status_code==201
    assert r.json['conflicts']==1
    assert client.get('/suite/api/employees').json==[]

def test_reviewed_import_cannot_be_reprocessed(client):
    import pymupdf
    d=pymupdf.open();p=d.new_page();p.insert_text((30,40),'March\n2025\nRegular Salary\n123456789\nBasic\n50000.00');data=d.tobytes();d.close()
    id=client.post('/suite/api/imports',data={'kind':'ga55','file':(io.BytesIO(data),'ga.pdf')}).json['id']
    payment=dict(bill_no='123456789',pay_month='2025-03',bill_type='Regular Salary',allowances={'Basic':'50000.00'},deductions={})
    assert client.post(f'/suite/api/imports/{id}/review',json=dict(reviewed=True,employee_code='RJ1',payments=[payment])).status_code==200
    assert client.post(f'/suite/api/imports/{id}/ocr',json={}).status_code==400
    assert len(client.get('/suite/api/payments?employee_code=RJ1').json)==1
