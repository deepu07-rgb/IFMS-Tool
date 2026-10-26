from test_suite_workflow import client

def test_cross_origin_state_changes_are_rejected(client):
    r=client.post('/suite/api/employees',json={'employee_code':'RJ1','name':'A'},headers={'Origin':'https://unrelated.example'})
    assert r.status_code==403
    assert client.get('/suite/api/employees').json==[]

def test_invalid_payload_returns_an_actionable_error(client):
    r=client.post('/suite/api/claims',json={'employee_code':'RJ1','allowance':'DA'})
    assert r.status_code==400
    assert 'start' in r.json['error']

def test_ocr_status_reports_installed_languages(client):
    r=client.get('/suite/api/ocr_status')
    assert r.status_code==200
    assert isinstance(r.json['available'],bool)
    if r.json['available']:assert 'eng' in r.json['languages']

def test_get_with_json_acceptance_header_needs_no_body(client):
    r=client.get('/suite/api/claims',headers={'Content-Type':'application/json'})
    assert r.status_code==200
