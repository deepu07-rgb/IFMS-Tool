"""Synthetic employee data; PDF exports must keep API filters and all rows."""
import sqlite3
import pymupdf
import pytest
from app import app, init_db
from ifms_engine.db import init_v2_schema

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setitem(app.config,'DATABASE',str(tmp_path/'pdf.db'))
    monkeypatch.setitem(app.config,'USE_V2_PARSER',True)
    init_db();init_v2_schema(app.config['DATABASE'])
    with sqlite3.connect(app.config['DATABASE']) as db:
        bill=db.execute("INSERT INTO bills_v2(source_filename) VALUES ('synthetic.pdf')").lastrowid
        for i in range(205):
            emp=db.execute('INSERT INTO employees_v2(bill_id,source_filename,sr_no,raw_name,employee_id,gross_amount,sum_deduction,net_total) VALUES (?,?,?,?,?,?,?,?)',(bill,'synthetic.pdf',i+1,f'Person {i+1}',f'TEST{i+1:03}',1000+i,100,900+i)).lastrowid
            db.execute('INSERT INTO employee_components_v2(employee_id,bill_id,component_type,raw_head,normalized_head,amount) VALUES (?,?,?,?,?,?)',(emp,bill,'allowance','ROP','rop',-25))
    return app.test_client()

def pdf_text(response):
    assert response.status_code==200
    assert response.mimetype=='application/pdf'
    with pymupdf.open(stream=response.data,filetype='pdf') as doc:
        return '\n'.join(p.get_text() for p in doc)

def test_pdf_applies_employee_amount_and_component_filters(client):
    query={'employee_id':'TEST002','gross_min':'1001','component_head':'rop','component_operator':'lt','component_value':'0'}
    api=client.get('/api/employees',query_string=query).json
    text=pdf_text(client.get('/api/export_pdf',query_string=query))
    assert api['total']==1
    assert 'TEST002' in text and 'TEST001' not in text
    for amount in ['1001.00','100.00','901.00','-25.00']:
        assert amount in text
    assert 'ROP' in text
    assert '1 employee' in text

def test_pdf_exports_every_matching_row_beyond_api_page_limit(client):
    text=pdf_text(client.get('/api/export_pdf'))
    assert '205 employees' in text
    assert all(f'TEST{i:03}' in text for i in range(1,206))
    assert '225910.00' in text
    assert '20500.00' in text
    assert '205410.00' in text

def test_pdf_empty_filter_returns_actionable_no_data(client):
    response=client.get('/api/export_pdf?employee_id=MISSING')
    assert response.status_code==404
    assert response.json['error']=='No data to export'
