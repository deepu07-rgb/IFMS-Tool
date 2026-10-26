import io,zipfile
from openpyxl import load_workbook
from test_suite_workflow import client

def test_batch_pack_contains_individual_files_and_matching_summary(client):
    p=dict(employee_code='RJ1',allowance='DA',start='2025-01-01',end='2025-01-31',segments=[dict(start='2025-01-01',end='2025-01-31',basic='50000',due_rate='55',drawn_rate='53')])
    ids=[]
    for code in ['RJ1','RJ2']:
        p['employee_code']=code;ids.append(client.post('/suite/api/claims',json=p).json['id'])
    r=client.get('/suite/api/batch_export?ids='+','.join(map(str,ids)))
    assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.data)) as z:
        assert len([n for n in z.namelist() if n.endswith('.pdf')])==2
        w=load_workbook(io.BytesIO(z.read('Consolidated.xlsx')))
        assert w.active['F4'].value==2000
        assert w.active['H4'].value==2000
