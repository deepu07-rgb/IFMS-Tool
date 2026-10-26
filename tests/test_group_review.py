from test_suite_workflow import client

def test_group_conflicts_need_selection_and_approved_import_shares_master(client):
    rows=[dict(employeeCode='RJ1',employeeName='A',groupName='G1'),dict(employeeCode='RJ1',employeeName='B',groupName='G2')]
    id=client.post('/suite/api/group_import',json={'records':rows}).json['id']
    assert client.post(f'/suite/api/group_imports/{id}/review',json={'reviewed':True}).status_code==400
    r=client.post(f'/suite/api/group_imports/{id}/review',json={'reviewed':True,'selections':{'RJ1':1}})
    assert r.status_code==200
    profile=client.get('/suite/api/employees').json[0]
    assert profile['name']=='B' and profile['group']=='G2'

def test_profile_conflict_preserves_prior_until_explicit_replace(client):
    client.post('/suite/api/employees',json=dict(employee_code='RJ1',name='A'))
    id=client.post('/suite/api/group_import',json={'records':[dict(employeeCode='RJ1',employeeName='B')]}).json['id']
    assert client.post(f'/suite/api/group_imports/{id}/review',json={'reviewed':True}).status_code==409
    assert client.get('/suite/api/employees').json[0]['name']=='A'
    assert client.post(f'/suite/api/group_imports/{id}/review',json={'reviewed':True,'replace_current':True}).status_code==200

def test_identical_profiles_from_different_source_rows_are_not_conflicts(client):
    rows=[dict(employeeCode='RJ1',employeeName='A',groupName='G',__rid='1'),dict(employeeCode='RJ1',employeeName='A',groupName='G',__rid='2')]
    id=client.post('/suite/api/group_import',json={'records':rows}).json['id']
    assert client.post(f'/suite/api/group_imports/{id}/review',json={'reviewed':True}).status_code==200
