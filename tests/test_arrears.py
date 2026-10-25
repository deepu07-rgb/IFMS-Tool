from decimal import Decimal
import pytest
from ifms_suite.calculation import calculate_claim

def segment(start='2025-01-01',end='2025-03-31',**kw):
    return dict(start=start,end=end,basic='50000',due_rate='55',drawn_rate='53',**kw)

def test_full_three_months():
    r=calculate_claim('2025-01-01','2025-03-31',[segment()])
    assert len(r['rows'])==3
    assert r['total']=='3000.00'

def test_partial_inclusive():
    r=calculate_claim('2025-03-13','2025-03-31',[segment()])
    assert r['rows'][0]['days']==19
    assert r['total']=='612.90'

def test_leap_february_and_rounding():
    r=calculate_claim('2024-02-29','2024-02-29',[segment('2024-02-01','2024-02-29')])
    assert r['rows'][0]['denominator']==29
    assert r['total']=='34.49'

def test_rate_change_and_prior_settlement():
    a=segment(end='2025-01-15'); b=segment('2025-01-16','2025-01-31',prior_settlement='100')
    b['due_rate']='57'
    r=calculate_claim('2025-01-01','2025-01-31',[a,b])
    assert r['total']=='1416.13'

@pytest.mark.parametrize('segments',[[dict(start='2025-01-01',end='2025-01-31',basic='50000',due_rate='55')],[],[segment(),segment()]])
def test_reject_missing_drawn_gaps_and_overlap(segments):
    with pytest.raises(ValueError):calculate_claim('2025-01-01','2025-01-31',segments)

def test_signed_recovery():
    s=segment();s['due_rate']='50'
    assert calculate_claim('2025-01-01','2025-01-31',[s])['total']=='-1500.00'

def test_settlement_rounding_matches_displayed_arithmetic():
    s=segment(prior_settlement='100.015')
    r=calculate_claim('2025-01-01','2025-01-31',[s]);row=r['rows'][0]
    assert row['prior_settlement']=='100.02'
    assert row['difference']=='899.98'
