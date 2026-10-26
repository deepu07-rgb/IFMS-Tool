from ifms_suite.reference import reference_rates,load_reference
from ifms_suite.history import active
from datetime import date

def test_official_freeze_and_supersession():
    rates=[r for r in reference_rates() if r['allowance']=='DA']
    assert active(rates,date(2020,7,1),'DA')['rate']=='17'
    assert active(rates,date(2021,7,1),'DA')['rate']=='31'
    assert active(rates,date(2025,1,1),'DA')['rate']=='55'
    assert all(r['source_sha256'] and r['order_date'] for r in rates)

def test_hra_effective_date_is_not_order_date():
    rates=[r for r in reference_rates() if r['allowance']=='HRA' and r['category']=='Y']
    assert active(rates,date(2024,10,31),'HRA')['rate']=='18'
    assert active(rates,date(2024,11,1),'HRA')['rate']=='20'
