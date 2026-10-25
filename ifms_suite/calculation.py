"""Deterministic inclusive-date percentage allowance calculations.

No implicit rate schedule or service entitlement is inferred. Values must be supplied
for every day. Raw decimal amounts are prorated, then rounded per monthly segment.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal('0.01')

def money(value):
    try:
        result = Decimal(str(value).replace(',', ''))
        if not result.is_finite():
            raise ValueError('Money and rates must be finite')
        return result
    except (InvalidOperation, TypeError):
        raise ValueError('Missing or invalid monetary value') from None

def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)

def calculate_claim(start, end, segments):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end:
        raise ValueError('Start date must precede end date')
    if (end-start).days > 36600:
        raise ValueError('Claim period exceeds 100 years')
    prepared=[]
    for s in segments:
        a,b=date.fromisoformat(s['start']),date.fromisoformat(s['end'])
        if a>b:raise ValueError('Invalid segment dates')
        for key in ('basic','due_rate','drawn_rate'):
            if key not in s or s[key] in ('',None):raise ValueError('Missing '+key)
        if s.get('proration','calendar') != 'calendar':
            raise ValueError('Only explicitly selected calendar proration is currently supported')
        prepared.append((a,b,s))
    rows=[];cursor=start; total=Decimal(0)
    while cursor<=end:
        matches=[(a,b,s) for a,b,s in prepared if a<=cursor<=b]
        if len(matches)!=1:raise ValueError('Missing or overlapping segment at '+str(cursor))
        a,b,s=matches[0]
        last=min(end,b,date(cursor.year,cursor.month,monthrange(cursor.year,cursor.month)[1]))
        # A second interval starting within this one must not go unnoticed.
        if any(cursor<x<=last for x,y,t in prepared if t is not s):
            raise ValueError('Overlapping segments')
        days=(last-cursor).days+1; denominator=monthrange(cursor.year,cursor.month)[1]
        factor=Decimal(days)/Decimal(denominator);basic=money(s['basic'])
        due=rounded(basic*money(s['due_rate'])/100*factor)
        drawn=rounded(basic*money(s['drawn_rate'])/100*factor)
        # A segment-level prior settlement is applied once, at its first selected row.
        prior=rounded(money(s.get('prior_settlement','0'))) if cursor==max(start,a) else Decimal(0)
        difference=rounded(due-drawn-prior);total+=difference
        rows.append(dict(start=str(cursor),end=str(last),days=days,denominator=denominator,
                         basic=str(basic),due_rate=str(s['due_rate']),drawn_rate=str(s['drawn_rate']),
                         due=f'{due:.2f}',drawn=f'{drawn:.2f}',prior_settlement=f'{prior:.2f}',difference=f'{difference:.2f}'))
        cursor=last+timedelta(days=1)
    return dict(rows=rows,total=f'{total:.2f}',rounding='HALF_UP, 2 decimals per segment; due and drawn separately',proration='calendar')
