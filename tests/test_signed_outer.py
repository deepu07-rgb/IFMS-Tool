from outer_engine.parser import clean_money, extract_pdf_data
from pathlib import Path

def test_negative_money_keeps_sign():
    assert clean_money('-2,756.00') == -2756

def test_negative_rop_and_full_component_sum(tmp_path):
    import fitz
    p=tmp_path/'outer.pdf'; d=fitz.open(); page=d.new_page()
    page.insert_text((30,40),'Reference No: 123456789\nBill Date: 01/01/2025\nSalary Arrear\nBasic 100 10000\nROP 123 -500\nGPF 215 9500\nGross Amount: 9500\nTotal Deduction: 9500\nNet Amount: 0')
    d.save(p); d.close()
    r=extract_pdf_data(str(p))
    assert r['Allowances']['ROP'] == -500
    assert r['Confidence_Score'] != '❌'

def test_zero_net_still_requires_arithmetic_reconciliation(tmp_path):
    import pymupdf
    p=tmp_path/'bad-zero.pdf';d=pymupdf.open();page=d.new_page()
    page.insert_text((30,40),'Reference No: 123456789\nBill Date: 01/01/2025\nSalary Arrear\nBasic 100 10000\nGPF 215 1000\nGross Amount: 10000\nTotal Deduction: 1000\nNet Amount: 0')
    d.save(p);d.close();r=extract_pdf_data(str(p))
    assert any('Net calculation mismatch' in reason for reason in r['Confidence_Reasons'])
