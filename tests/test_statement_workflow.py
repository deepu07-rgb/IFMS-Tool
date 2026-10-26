import io
from openpyxl import Workbook
from test_suite_workflow import client

def test_excel_statement_can_be_checked_and_recalculated_with_rate_library(client):
    w=Workbook();s=w.active;s.title='Arrear'
    s.append(['Sr','Month','Pay Due','','','','Pay Drawn','','','','Pay Difference','','',''])
    s.append(['','','Basic','DA','HRA','Total','Basic','DA','HRA','Total','Basic','DA','HRA','Total'])
    s.append([1,'Jan-2025',50000,27000,10000,87000,50000,26500,10000,86500,0,500,0,500])
    b=io.BytesIO();w.save(b);b.seek(0)
    r=client.post('/suite/api/imports',data={'kind':'due_drawn','file':(b,'statement.xlsx')})
    assert r.status_code==201
    assert len(r.json['payload']['statement_rows'])==1
    id=r.json['id'];client.post('/suite/api/rates',json=dict(allowance='DA',effective_from='2025-01-01',rate='55',reference='Order'))
    q=client.post('/suite/api/statement_claim',json=dict(import_id=id,employee_code='RJ1',allowance='DA',source_sheet='Arrear',method='rates',reviewed=True,rows=r.json['payload']['statement_rows']))
    assert q.status_code==201
    assert q.json['calculation']['total']=='1000.00'
    assert q.json['calculation']['rows'][0]['due']=='27500.00'
