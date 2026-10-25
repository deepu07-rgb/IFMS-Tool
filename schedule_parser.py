"""
IFMS 3.0 Schedule Sheet Parser - v7 (Complete Rewrite)
Parses ALL 10 schedule types from Rajasthan IFMS 3.0 Schedule PDFs.
Key: Dynamic column detection from header row.
"""
import pdfplumber
import re
from collections import OrderedDict


def _pn(text):
    if not text: return None
    text = str(text).strip().replace(',', '').replace(' ', '')
    if re.match(r'^-?\d+\.?\d*$', text):
        try: return float(text)
        except: return None
    return None

def _data_words(page, max_font_size=20):
    try: words = page.extract_words(extra_attrs=["fontname", "size"])
    except: words = page.extract_words()
    return [w for w in words if w.get('size') is None or w.get('size') < max_font_size]

_WM = {'SS','MM','FF','II','JJ','AA','RR','¥','RAJFMS','RA','JF','MS','3.0'}
def _is_wm(t): return t.strip() in _WM

# ===================== SCHEDULE TYPE DETECTION =====================
_TYPE_KW = [
    ('schedule of income tax', 'income_tax'), ('income tax (budget', 'income_tax'),
    ('income tax(budget', 'income_tax'),
    ('gpf 2004', 'gpf_2004'),
    ('gpf  contribution', 'gpf_contribution'), ('gpf contribution', 'gpf_contribution'),
    ('si premium', 'si_premium'),
    ('schedule of rop', 'rop'),
    ('advance salary', 'advance_salary'),
    ('cooperative account (ppss', 'ppss_jdr'), ('cooperative account(ppss', 'ppss_jdr'),
    ('cooperative account (road', 'cooperative_roadways'),
    ('road ways dedut', 'cooperative_roadways'), ('roadways', 'cooperative_roadways'),
    ('schedule of rghs', 'rghs'),
    ('schedule of lic', 'lic'), ('lic (budget', 'lic'),
]

def detect_schedule_type(text):
    tl = text.lower()
    for kw, st in _TYPE_KW:
        if kw in tl: return st
    m = re.search(r'schedule\s+of\s+([^\n(]+)', tl)
    if m: return m.group(1).strip().replace(' ', '_')[:30]
    return None

# ===================== EXPECTED COLUMN ORDER PER TYPE =====================
TYPE_COLS = {
    'gpf_contribution': ['sr_no','employee_id','name','designation','gpf_no',
                         'basic_pay','gpf_contribution','gpf_loan','total'],
    'income_tax': ['sr_no','employee_id','name','designation','pan',
                   'basic_pay','income_tax','sit','health_edu_cess','hi_edu_cess','total'],
    'lic': ['sr_no','employee_id','name','designation','basic_pay',
            'policy_no','premium','total'],
    'si_premium': ['sr_no','employee_id','name','si_policy_no','basic_pay',
                   'si_premium','si_loan','si_interest','s_tax_on_si','total'],
    'gpf_2004': ['sr_no','employee_id','name','designation','basic_pay',
                 'gpf_2004','loan_ac_no','total'],
    'rop': ['sr_no','name','employee_id','designation','gpf_no',
            'basic_pay','reason','total'],
    'advance_salary': ['sr_no','employee_id','name','bank_ac_no',
                       'designation','nominee_name','total'],
    'ppss_jdr': ['sr_no','employee_id','name','coop_ser_no','bank_ac_no',
                 'designation','gpf_no','total'],
    'cooperative_roadways': ['sr_no','employee_id','name','coop_ser_no','bank_ac_no',
                             'designation','gpf_no','total'],
    'rghs': ['sr_no','employee_id','name','designation','basic_pay','rghs','total'],
}

FLOAT_COLS = {'basic_pay','gpf_contribution','gpf_loan','income_tax','sit',
              'health_edu_cess','hi_edu_cess','premium','si_premium','si_loan',
              'si_interest','s_tax_on_si','gpf_2004','rghs','total'}
INT_COLS = {'sr_no'}

# ===================== HEADER ROW -> COLUMN BOUNDARIES =====================
def _find_columns(words, stype):
    """Find header row, group words into column headers, map to expected columns."""
    # Find "Sr." or "Sr" header word - search the entire page, not just top 130px
    # Prefer the topmost one that's in the left margin
    candidates = []
    for w in words:
        t = w.get('text','').strip()
        if t in ('Sr.','Sr') and w['x0'] < 55:
            candidates.append(w)
    if not candidates: return [], 0
    # Pick the topmost candidate
    sr_w = min(candidates, key=lambda w: w['top'])

    hy = sr_w['top']
    # Also check if there's a "No." word next to "Sr." (within ~20px y, to the right)
    hw = sorted([w for w in words if abs(w['top']-hy) < 8 and w.get('text','').strip()
                 and not _is_wm(w.get('text','').strip())],
                key=lambda w: w['x0'])

    # Group nearby header words into column groups using x1 (right edge)
    groups = []
    cg = None
    for w in hw:
        t = w['text'].strip()
        if not t: continue
        if cg is None:
            cg = {'x': w['x0'], 'x1': w.get('x1', w['x0']+30), 'texts': [t]}
        elif w['x0'] - cg['x1'] < 10:  # Gap < 10px = same column header
            cg['texts'].append(t)
            cg['x1'] = w.get('x1', w['x0']+30)
        else:
            groups.append(cg)
            cg = {'x': w['x0'], 'x1': w.get('x1', w['x0']+30), 'texts': [t]}
    if cg: groups.append(cg)

    expected = TYPE_COLS.get(stype, [])
    if not expected or not groups: return [], hy

    # Map groups to expected columns by position order
    # Use MIDPOINT between groups as boundaries (handles right-aligned numbers)
    columns = []
    n = min(len(groups), len(expected))
    for i in range(n):
        if i == 0:
            x_start = 0
        else:
            x_start = (groups[i-1]['x1'] + groups[i]['x']) / 2
        if i + 1 < len(groups):
            x_end = (groups[i]['x1'] + groups[i+1]['x']) / 2
        else:
            x_end = 900
        columns.append((expected[i], x_start, x_end))

    return columns, hy + 12

# ===================== HEADER METADATA =====================
def extract_schedule_header(page):
    text = page.extract_text() or ""
    h = {}
    m = re.search(r'Month\s*/?\s*Year\s*[:/]?\s*(\w+\s*/?\s*\d{4})', text, re.I)
    if m: h['month_year'] = m.group(1).strip()
    else:
        m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s*/?\s*(\d{4})', text)
        if m: h['month_year'] = f"{m.group(1)}/{m.group(2)}"
    m = re.search(r'Bill\s*No\.?\s*&?\s*Date\s*[:/]?\s*(\S+)', text)
    if m: h['bill_no'] = m.group(1).strip()
    m = re.search(r'DDO\s*Code\s*[:/]?\s*(\d+)', text)
    if m: h['ddo_code'] = m.group(1).strip()
    m = re.search(r'Office\s*Name\s*[:/]?\s*(.+?)(?:\n|DDO|$)', text)
    if m: h['office_name'] = m.group(1).strip()
    m = re.search(r'Service\s*Head\s*[:/]?\s*([\d-]+)', text)
    if m: h['service_head'] = m.group(1).strip()
    return h

# ===================== FOOTER / SR MARKERS =====================
def _footer_y(words):
    fy = 750
    for w in words:
        t = w.get('text','').strip(); y = w['top']
        if y < 100: continue
        if t.startswith('Grand') or t.startswith('Rupees') or t.startswith('Disclaimer'):
            fy = min(fy, y)
        elif t in ('DHANNA',) or t.startswith('Signer'): fy = min(fy, y)
        elif t == 'Print' and y > 200:
            if any('Date' in ww.get('text','') for ww in words if abs(ww['top']-y)<4 and ww['x0']>w['x0']):
                fy = min(fy, y)
    return fy

def _sr_markers(words, start_y, end_y):
    ms = []
    for w in words:
        if w['top'] < start_y or w['top'] >= end_y: continue
        if w['x0'] > 45: continue
        t = w['text'].strip()
        if t.isdigit():
            n = int(t)
            if 1 <= n <= 9999: ms.append((n, w['top']))
    ms.sort(key=lambda x: x[1])
    uniq = []
    for m in ms:
        if not uniq or abs(m[1]-uniq[-1][1]) > 5: uniq.append(m)
        elif m[0] > uniq[-1][0]: uniq[-1] = m
    return uniq

# ===================== ENTRY EXTRACTION =====================
def _extract_entry(bwords, columns, stype):
    entry = {'schedule_type': stype}
    for cn in TYPE_COLS.get(stype, []):
        entry[cn] = 0.0 if cn in FLOAT_COLS else (0 if cn in INT_COLS else '')

    cw = {cn: [] for cn, _, _ in columns}
    for w in bwords:
        x = w['x0']; t = w.get('text','').strip()
        if not t or _is_wm(t): continue
        for cn, xs, xe in columns:
            if xs <= x < xe:
                cw[cn].append(w); break

    for cn, _, _ in columns:
        wl = cw.get(cn, [])
        if not wl: continue
        wl.sort(key=lambda w: (w['top'], w['x0']))
        texts = [w['text'].strip() for w in wl if w['text'].strip() and not _is_wm(w['text'].strip())]
        if not texts: continue

        if cn in FLOAT_COLS:
            best = None
            for t in texts:
                v = _pn(t)
                if v is not None:
                    if best is None or abs(v) > abs(best): best = v
            if best is not None: entry[cn] = best
        elif cn in INT_COLS:
            for t in texts:
                if t.isdigit(): entry[cn] = int(t); break
        elif cn == 'employee_id':
            for t in texts:
                if re.match(r'^RJ[A-Z]{2}\d{6,}', t): entry[cn] = t; break
            if not entry.get(cn): entry[cn] = texts[0]
        elif cn == 'name':
            parts = [t for t in texts if not re.match(r'^[\u0900-\u097F]', t)
                     and not re.match(r'^\(?\d{10,}\)?$', t) and not re.match(r'^RJ[A-Z]{2}\d', t)
                     and not re.match(r'^\(?\d{1,5}\)?$', t)
                     and not re.match(r'^\(\d', t)]
            entry[cn] = ' '.join(parts).strip()
        elif cn == 'pan':
            for t in texts:
                if re.match(r'^[A-Z]{5}\d{4}[A-Z]$', t): entry[cn] = t; break
        else:
            entry[cn] = ' '.join(texts).strip()
    return entry

def _extract_grand_total(words, fy):
    gt = {}
    for w in words:
        if w['top'] < fy - 5: continue
        t = w.get('text','').strip()
        if t == 'Grand' or t.startswith('Grand'):
            sl = sorted([ww for ww in words if abs(ww['top']-w['top'])<5], key=lambda ww: ww['x0'], reverse=True)
            for s in sl:
                v = _pn(s['text'])
                if v is not None: gt['total'] = v; break
        if t.startswith('Rupees'):
            sl = sorted([ww for ww in words if abs(ww['top']-w['top'])<5], key=lambda ww: ww['x0'])
            iw = ' '.join(ww['text'] for ww in sl)
            m = re.search(r'(?:Words?\s*[:/]?\s*)(.+?)(?:Only|$)', iw, re.I)
            if m: gt['in_words'] = m.group(1).strip()
    return gt

# ===================== PARSE PAGE =====================
def _parse_page(page, stype, prev_cols=None):
    words = _data_words(page)
    if not words: return [], {}, prev_cols

    columns, start_y = _find_columns(words, stype)
    is_continuation = False
    if not columns and prev_cols:
        columns = prev_cols
        is_continuation = True
        # For continuation pages: find the first potential sr_no marker to set start_y
        # Don't use a hardcoded value — scan for the first digit at the left margin
        first_data_y = None
        for w in sorted(words, key=lambda w: w['top']):
            t = w.get('text','').strip()
            if w['x0'] < 55 and t.isdigit() and 1 <= int(t) <= 9999:
                first_data_y = w['top']
                break
        start_y = max(0, first_data_y - 5) if first_data_y else 0
    if not columns: return [], {}, prev_cols

    fy = _footer_y(words)
    srs = _sr_markers(words, start_y, fy)
    if not srs: return [], {}, columns

    dw = [w for w in words if start_y - 5 <= w['top'] < fy]
    entries = []
    for i, (sr, ys) in enumerate(srs):
        ye = srs[i+1][1]-1 if i+1 < len(srs) else fy
        bw = [w for w in dw if ys-3 <= w['top'] < ye]
        if bw:
            e = _extract_entry(bw, columns, stype)
            e['sr_no'] = sr
            if e.get('employee_id') or e.get('name'): entries.append(e)
    gt = _extract_grand_total(words, fy)
    return entries, gt, columns

# ===================== MAIN =====================
def _is_schedule_header_page(text):
    """Check if the page has an actual schedule title header (not just a keyword in data)."""
    tl = text.lower()
    # Must have "Schedule of" or "Schedule Of" as an actual header
    if re.search(r'schedule\s+of\s+\w', tl):
        return True
    # Or "Contribution (Budget" pattern
    if re.search(r'contribution\s*\(budget', tl):
        return True
    return False

def parse_schedule_pdf(pdf_path):
    schedules = []
    try:
        pdf_obj = pdfplumber.open(pdf_path)
    except Exception as e:
        return [{'error': f'Cannot open PDF: {str(e)}'}]
    with pdf_obj as pdf:
        if not pdf.pages: return schedules
        ct = None    # current schedule type
        ch = {}      # current header
        ce = []      # current entries
        cgt = {}     # current grand total
        pc = None    # previous columns
        last_sr = 0  # track last sr_no for continuation validation
        
        for page in pdf.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            
            # Skip blank/near-blank pages (watermark-only, etc.)
            # Count non-watermark meaningful text
            clean = re.sub(r'\b(RAJFMS|SS|MM|FF|II|JJ|AA|RR|3\.0)\b', '', text)
            if len(clean.strip()) < 30:
                continue
            
            pt = detect_schedule_type(text)
            
            if pt and pt != ct:
                # Verify this is actually a new schedule header page, not just
                # a keyword appearing in data (e.g. employee working at "roadways")
                if _is_schedule_header_page(text):
                    # Save previous schedule if any
                    if ct and ce:
                        schedules.append({'type':ct,'header':ch,'entries':ce,
                                         'grand_total':cgt,'count':len(ce)})
                    ct = pt
                    ch = extract_schedule_header(page)
                    ce = []
                    cgt = {}
                    pc = None
                    last_sr = 0
                elif ct:
                    # Keyword in data but not an actual header — treat as continuation
                    pt = ct
                else:
                    # No current type and not a header page — skip
                    continue
            elif not pt:
                if ct:
                    # No schedule keyword found — continuation page
                    pt = ct
                else:
                    continue
            
            try:
                entries, gt, cols = _parse_page(page, pt, pc)
            except Exception:
                continue
            if cols: pc = cols
            
            # Validate continuation: check sr_no continuity
            if entries:
                first_sr = entries[0].get('sr_no', 0)
                # If sr_nos jump backwards significantly, might be a new schedule
                # that wasn't detected (safety check)
                if ce and first_sr > 0 and last_sr > 0 and first_sr < last_sr - 5:
                    # This looks like a restart — might be a new schedule of same type
                    # Save current and start fresh
                    if ce:
                        schedules.append({'type':ct,'header':ch,'entries':ce,
                                         'grand_total':cgt,'count':len(ce)})
                        ch = extract_schedule_header(page)
                        ce = []
                        cgt = {}
                
                ce.extend(entries)
                last_sr = entries[-1].get('sr_no', last_sr)
            
            if gt: cgt = gt
        
        # Save final schedule
        if ct and ce:
            schedules.append({'type':ct,'header':ch,'entries':ce,
                             'grand_total':cgt,'count':len(ce)})
    return schedules

def get_all_employee_ids(schedules):
    ids = set()
    for s in schedules:
        for e in s.get('entries', []):
            eid = e.get('employee_id', '').strip()
            if eid: ids.add(eid)
    return ids

SCHEDULE_TYPE_NAMES = {
    'gpf_contribution':'GPF Contribution','income_tax':'Income Tax','lic':'LIC',
    'si_premium':'SI Premium','gpf_2004':'GPF 2004','rop':'Schedule of ROP',
    'advance_salary':'Advance Salary','ppss_jdr':'Coop (PPSS JDR)',
    'cooperative_roadways':'Coop Roadways','rghs':'RGHS',
}
def get_schedule_type_name(st): return SCHEDULE_TYPE_NAMES.get(st, st.replace('_',' ').title())
