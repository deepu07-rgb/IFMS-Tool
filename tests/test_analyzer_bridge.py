from test_suite_workflow import client
from ifms_engine.db import init_v2_schema
from ifms_suite.storage import database

def test_inner_components_become_review_candidates(client):
    init_v2_schema(client.application.config['DATABASE'])
    with client.application.app_context(),database() as db:
        bid=db.execute("INSERT INTO bills_v2(bill_no,month_year,source_filename) VALUES('B1','January / 2025','inner.pdf')").lastrowid
        eid=db.execute("INSERT INTO employees_v2(bill_id,employee_id,raw_name,month_year,gross_amount,sum_deduction,net_total) VALUES(?,'RJ1','Employee','January / 2025',76500,1000,75500)",(bid,)).lastrowid
        db.executemany('INSERT INTO employee_components_v2(employee_id,bill_id,component_type,raw_head,normalized_head,amount) VALUES(?,?,?,?,?,?)',[(eid,bid,'allowance','Basic','basic_pay',50000),(eid,bid,'allowance','DA','da',26500),(eid,bid,'deduction','GPF','gpf',1000)])
    r=client.get('/suite/api/analyzer_candidates?employee_code=RJ1')
    assert r.status_code==200
    assert r.json[0]['allowances']['Basic']=='50000.00'
    assert r.json[0]['requires_review'] is True
    assert r.json[0]['pay_month']=='2025-01'

def test_inner_profiles_can_be_reviewed_into_shared_employee_library(client):
    init_v2_schema(client.application.config['DATABASE'])
    with client.application.app_context(),database() as db:
        bid=db.execute("INSERT INTO bills_v2(bill_no,month_year) VALUES('B2','January / 2025')").lastrowid
        db.execute("INSERT INTO employees_v2(bill_id,employee_id,raw_name,group_name) VALUES(?,'RJ2','Employee Two','Group')",(bid,))
    r=client.post('/suite/api/group_import/analyzer',json={})
    assert r.status_code==201
    assert client.post(f"/suite/api/group_imports/{r.json['id']}/review",json={'reviewed':True}).status_code==200
    assert client.get('/suite/api/employees').json[0]['name']=='Employee Two'
