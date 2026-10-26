from test_suite_workflow import client

def setup_history(c,code='RJ1'):
    c.post('/suite/api/employees',json=dict(employee_code=code,name='Employee'))
    c.post('/suite/api/pay_history',json=dict(employee_code=code,effective_from='2025-01-01',basic='50000',reference='Pay order',reviewed=True))
    c.post('/suite/api/rates',json=dict(allowance='DA',effective_from='2025-01-01',rate='55',reference='DA order'))
    c.post('/suite/api/payments/manual',json=dict(employee_code=code,pay_month='2025-01',bill_type='Regular Salary',bill_no='B1'+code,allowances={'DA':'26500'},deductions={},reviewed=True,reference='Original bill'))

def test_history_drives_claim_and_deductions(client):
    setup_history(client)
    r=client.post('/suite/api/claims',json=dict(employee_code='RJ1',allowance='DA',start='2025-01-01',end='2025-01-31',source='history',deductions=[dict(name='GPF',mode='percent',value='100')]))
    assert r.status_code==201
    assert r.json['calculation']['total']=='1000.00'
    assert r.json['calculation']['net_payable']=='0.00'
    assert r.json['calculation']['rows'][0]['source'].startswith('Bill B1RJ1')

def test_custom_rule_persists_and_batch_is_atomic(client):
    rule=client.post('/suite/api/rules',json=dict(name='HDA',basis='basic_da',proration='calendar',rounding='rupee',reference='Allowance order'))
    assert rule.status_code==201
    assert client.get('/suite/api/rules').json[0]['name']=='HDA'
    setup_history(client)
    r=client.post('/suite/api/batch',json=dict(employees=['RJ1','MISSING'],allowance='DA',start='2025-01-01',end='2025-01-31'))
    assert r.status_code==422
    assert client.get('/suite/api/claims').json==[]

def test_manual_payment_deduplicates_across_sources(client):
    p=dict(employee_code='rj1',pay_month='2025-01',bill_type='Regular Salary',bill_no='B1',allowances={'DA':'100'},reviewed=True,reference='Bill')
    assert client.post('/suite/api/payments/manual',json=p).status_code==201
    assert client.post('/suite/api/payments/manual',json=p).status_code==409

def test_history_preview_uses_open_transaction(client):
    setup_history(client)
    r=client.post('/suite/api/history/preview',json=dict(employee_code='RJ1',allowance='DA',start='2025-01-01',end='2025-01-31'))
    assert r.status_code==200
    assert r.json['calculation']['total']=='1000.00'
