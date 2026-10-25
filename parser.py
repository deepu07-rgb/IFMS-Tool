"""
IFMS 3.0 PDF Parser - v5 (Production)
Parses Inner Sheet, Outer Sheet, and Schedule Sheet PDFs from Rajasthan IFMS 3.0.
Handles: 1000+ employees, dependant deductions, multi-line name fragments, grand totals.

v5 fixes:
- More robust data boundary detection (won't clip last employee)
- Better Sr number detection (handles edge cases)
- Returns grand_totals for cross-validation
- Performance optimized for large PDFs (1000+ employees)
- Validates parsed data against grand totals
- Fixed x-column overlap between gross and deduction columns
"""
import pdfplumber
import re


# --------------- UTILITIES ---------------

def _pn(text):
    """Parse number from text. Returns float/int or None."""
    text = text.strip().replace(',', '')
    if re.match(r'^-?\d+\.?\d*$', text):
        try:
            return float(text) if '.' in text else int(text)
        except:
            return None
    return None


def _data_words(page, max_size=20):
    """
    Extract words, filtering watermark (large font size >= 50).
    v5: Raised threshold to 20. Watermarks are always 80+.
    If 'size' attr is missing, word is INCLUDED (safe default).
    """
    words = page.extract_words(extra_attrs=["fontname", "size"])
    result = []
    for w in words:
        sz = w.get('size')
        if sz is None:
            result.append(w)
        elif sz < max_size:
            result.append(w)
    return result


# --------------- SHEET TYPE DETECTION ---------------

def detect_sheet_type(pdf_path):
    """Detect if PDF is inner, outer, or schedule sheet."""
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return "unknown"
        text = ""
        for p in pdf.pages[:2]:
            text += (p.extract_text() or "") + "\n"
        tl = text.lower()
        if "inner sheet" in tl:
            return "inner"
        elif "outer sheet" in tl:
            return "outer"
        elif "schedule of" in tl:
            return "schedule"
        elif "GPF/PRAN" in text:
            return "inner"
        return "schedule"


# --------------- HEADER EXTRACTION ---------------

def extract_header_info(page):
    """Extract header metadata from the first page."""
    text = page.extract_text() or ""
    header = {}
    m = re.search(r'Reference\s*No[.:]*\s*(\d+)', text)
    if m: header['reference_no'] = m.group(1)
    m = re.search(r'Bill\s*No[.:]*\s*(\S+)', text)
    if m: header['bill_no'] = m.group(1)
    # Try multiple month patterns
    m = re.search(r'(?:Pay\s*Month|Month\s*of|Month\s*/?\s*Yea?\s*r?)\s*[:\s]*(\w+\s*/\s*\d{4})', text, re.I)
    if m:
        header['month_year'] = m.group(1).strip()
    else:
        # Fallback: find "January / 2026" style anywhere
        m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s*/?\s*(\d{4})', text)
        if m:
            header['month_year'] = f"{m.group(1)} / {m.group(2)}"
    m = re.search(r'GFAR[:\s]+(\S+)', text)
    if m: header['gfar'] = m.group(1)
    return header


def _extract_group_from_footer(words):
    """Find group name from footer: 'Group Name: CP PL FIRST'"""
    for w in words:
        if w.get('text', '') == 'Group' and w['top'] > 530:
            gy = w['top']
            gx = w['x0']
            # Find "Name:" right after "Group"
            nearby = [ww for ww in words if abs(ww['top'] - gy) < 3 and ww['x0'] > gx and ww['x0'] < gx + 200]
            nearby.sort(key=lambda ww: ww['x0'])
            if nearby and 'Name' in nearby[0].get('text', ''):
                # Collect group name words after "Name:" — limit x range to avoid picking up
                # "Print Date & Time: Forward" from the far right
                name_words = [ww['text'] for ww in nearby[1:] if ww['x0'] < gx + 150]
                gn = ' '.join(name_words).strip().rstrip(':')
                if gn:
                    return gn
    return ""


# ===================== INNER SHEET PARSER =====================

def parse_inner_sheet(pdf_path):
    """
    Parse Inner Sheet PDF. Returns (header, employees, grand_totals).
    grand_totals = {'gross': X, 'deduction': Y, 'net': Z} from the PDF's own summary line.
    """
    employees = []
    header = {}
    grand_totals = {}
    page_stats = []  # Track per-page parsing stats

    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return header, employees, grand_totals

        header = extract_header_info(pdf.pages[0])

        if not header.get('group_name'):
            w0 = _data_words(pdf.pages[0])
            header['group_name'] = _extract_group_from_footer(w0) or ""

        for pi, page in enumerate(pdf.pages):
            page_emps, page_totals = _parse_inner_page(page)
            page_stats.append({
                'page': pi + 1,
                'employees': len(page_emps),
                'sr_nos': [e['sr_no'] for e in page_emps]
            })
            employees.extend(page_emps)
            if page_totals:
                grand_totals = page_totals

    # POST-PARSE: Detect gaps in Sr numbers
    sr_nos = sorted(e['sr_no'] for e in employees if isinstance(e.get('sr_no'), int))
    if sr_nos:
        expected = set(range(sr_nos[0], sr_nos[-1] + 1))
        missing = sorted(expected - set(sr_nos))
        if missing:
            grand_totals['missing_sr_nos'] = missing
            grand_totals['gap_warning'] = f"Missing Sr numbers: {missing[:20]}{'...' if len(missing) > 20 else ''}"

    # VALIDATION: Cross-check parsed data against grand totals
    if grand_totals and employees:
        parsed_gross = sum(e.get('gross_amount', 0) or 0 for e in employees)
        parsed_net = sum(e.get('net_total', 0) or 0 for e in employees)
        parsed_ded = sum(e.get('sum_deduction', 0) or 0 for e in employees)

        grand_totals['parsed_gross'] = parsed_gross
        grand_totals['parsed_net'] = parsed_net
        grand_totals['parsed_deduction'] = parsed_ded
        grand_totals['parsed_count'] = len(employees)
        grand_totals['gross_match'] = abs(grand_totals.get('gross', 0) - parsed_gross) < 2.0
        grand_totals['net_match'] = abs(grand_totals.get('net', 0) - parsed_net) < 2.0
        grand_totals['page_stats'] = page_stats

    return header, employees, grand_totals


def _find_data_boundary(words):
    """
    Find the y-coordinate where employee data ends on this page.
    v5: More generous boundary detection. Uses y > 530 for footer markers.
    Fallback raised to 580.
    """
    candidates = []

    for w in words:
        t = w.get('text', '')
        y = w['top']
        x = w['x0']

        # "Gross Amount:" summary line — last page only
        if t == 'Gross' and x < 50 and y > 200:
            nearby = [ww for ww in words if abs(ww['top'] - y) < 4 and 40 < ww['x0'] < 120]
            if any('Amount' in ww.get('text', '') for ww in nearby):
                candidates.append(y)

        # "Certificates:" header — last page only
        if t.startswith('Certificates') and x < 50 and y > 200:
            candidates.append(y)

        # "Amount In Words:" line — last page
        if t == 'Amount' and x < 50 and y > 200:
            nearby = [ww for ww in words if abs(ww['top'] - y) < 4 and ww['x0'] > x]
            if any('Words' in ww.get('text', '') for ww in nearby):
                candidates.append(y)

        # Footer markers — use y > 530 (generous)
        if t == 'Note:' and y > 530:
            candidates.append(y)

        if t.startswith('Disclaimer') and y > 530:
            candidates.append(y)

        # Group Name footer
        if t == 'Group' and y > 530 and x > 350:
            candidates.append(y)

    if candidates:
        return min(candidates)

    return 580  # Safe fallback


def _parse_inner_page(page):
    """Parse a single page of Inner Sheet. Returns (employees, grand_totals_or_None)."""
    employees = []
    grand_totals = None
    words = _data_words(page)
    if not words:
        return employees, grand_totals

    # Extract grand totals if this is the last page
    grand_totals = _extract_grand_totals(words)

    # Find where employee data ends
    data_end_y = _find_data_boundary(words)

    # Find Sr. No. markers: digits at x < 40, within data area
    sr_markers = []
    for w in words:
        if w['top'] >= data_end_y:
            continue
        if w['x0'] < 40:
            txt = w['text'].strip()
            if txt.isdigit():
                n = int(txt)
                if 1 <= n <= 9999:
                    # Make sure it's in the employee data zone (below header)
                    # On page 1: header can extend to y~160, employees start ~229
                    # On other pages: header is y~43-100, employees start ~109
                    # Use 60 as safe minimum — header "Sr. No." label is at y~43-51
                    if w['top'] > 60:
                        sr_markers.append((n, w['top']))
                    else:
                        # Check if there's corresponding employee data nearby
                        nearby_data = [ww for ww in words 
                                      if abs(ww['top'] - w['top']) < 4 
                                      and 110 <= ww['x0'] < 240
                                      and ww['text'][0].isupper()]
                        if nearby_data:
                            sr_markers.append((n, w['top']))

    if not sr_markers:
        return employees, grand_totals

    sr_markers.sort(key=lambda x: x[1])

    # Remove duplicates at nearly same y (within 5px)
    unique_markers = []
    for m in sr_markers:
        if not unique_markers or abs(m[1] - unique_markers[-1][1]) > 5:
            unique_markers.append(m)
        else:
            # Keep the one with higher Sr number (more likely correct)
            if m[0] > unique_markers[-1][0]:
                unique_markers[-1] = m
    sr_markers = unique_markers

    # All data words below the page header (include everything up to data_end_y)
    data_words_list = [w for w in words if w['top'] < data_end_y]

    # Parse each employee block
    for i, (sr_no, y_start) in enumerate(sr_markers):
        if i + 1 < len(sr_markers):
            y_end = sr_markers[i + 1][1]
        else:
            y_end = data_end_y

        # v5: More generous block word collection (y_start - 3 to y_end)
        block_words = [w for w in data_words_list if y_start - 3 <= w['top'] < y_end]

        if block_words:
            emp = _parse_emp_block(sr_no, block_words)
            if emp:
                employees.append(emp)

    return employees, grand_totals


def _extract_grand_totals(words):
    """
    Extract grand totals line: 'Gross Amount: X  Deduction Amount: Y  Net Amount: Z'
    These are the PDF's own verified totals for all employees.
    """
    for w in words:
        if w.get('text', '') == 'Gross' and w['x0'] < 50:
            nearby = [ww for ww in words if abs(ww['top'] - w['top']) < 4]
            nearby.sort(key=lambda ww: ww['x0'])
            line_text = ' '.join(ww['text'] for ww in nearby)

            totals = {}
            gm = re.search(r'Gross\s+Amount[:\s]+([\d.]+)', line_text)
            if gm:
                totals['gross'] = float(gm.group(1))

            dm = re.search(r'Deduction\s+Amount[:\s]+([\d.]+)', line_text)
            if dm:
                totals['deduction'] = float(dm.group(1))

            nm = re.search(r'Net\s+Amount[:\s]+([\d.]+)', line_text)
            if nm:
                totals['net'] = float(nm.group(1))

            if totals:
                return totals
    return None


# ===================== KNOWN NAME SETS =====================

KNOWN_SINGLE_NAMES = {
    'LIC', 'GPF', 'SIP', 'SIL', 'SII', 'RGHS', 'ITax',
    'HRA', 'CCA', 'HDA', 'Basic', 'DA', 'ROP', 'CA',
    'PPSS', 'Per', 'HBA-HDFC', 'Advance',
}

ORPHAN_FRAGMENTS = {
    'DEDUTION', 'DEDUCTION', 'DEDUT', 'DEDUCTI', 'DEDUCTIO', 'ION', 'N',
    'TION', 'DUCTION', 'UCTION', 'UTION', 'ON',
}

GARBAGE_WORDS = {
    'strictly', 'certified', 'accordance', 'certificate', 'entitled', 'printed',
    'generated', 'enclosure', 'bill', 'month', 'year', 'pay', 'allowance',
    'employee', 'service', 'salary', 'verification', 'attestation', 'absence',
    'quarters', 'government', 'inspection', 'incumbents', 'respect', 'records',
    'occupation', 'rent-free', 'casual', 'leave', 'suspension', 'drawn',
    'information', 'bank', 'account', 'details', 'checked', 'verified',
    'calculation', 'income', 'tax', 'done', 'dues', 'deducted', 'examined',
    'master', 'data', 'claim', 'selection', 'dropdown', 'requirements',
    'defined', 'relevant', 'rules', 'dated', 'the', 'this', 'that', 'are',
    'has', 'been', 'for', 'from', 'with', 'and', 'not', 'any', 'all',
    'under', 'only', 'which', 'their', 'whose', 'said', 'same', 'such',
    'every', 'should', 'about', 'above', 'also', 'each', 'february',
    'january', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december', 'noted',
    'sign', 'seal', 'digital', 'ddo', 'genuineness', 'personally',
    'exclaimed', 'satisfied', 'superior', 'absent', 'duty',
}


def _parse_emp_block(sr_no, bwords):
    """Parse an employee block using precise column x-positions."""
    emp = {
        'sr_no': sr_no, 'name': '', 'designation': '', 'gpf_pran': '',
        'dob': '', 'belt_no': '', 'pan': '', 'employee_id': '',
        'st_ins_no': '', 'pay_scale': '', 'grade_pay': '',
        'bank_acc': '', 'aadhar': '',
        'allowances': {}, 'deductions': {},
        'gross_amount': 0, 'sum_deduction': 0, 'net_total': 0,
    }

    bwords.sort(key=lambda w: (w['top'], w['x0']))

    # Group into lines by y-coordinate (tolerance 3px)
    lines = []
    current_line, current_y = [], -100
    for w in bwords:
        if abs(w['top'] - current_y) > 3:
            if current_line:
                lines.append(current_line)
            current_line, current_y = [w], w['top']
        else:
            current_line.append(w)
    if current_line:
        lines.append(current_line)

    if not lines:
        return None

    # Extract name from first line (x: 110-240)
    first_line_names = [w['text'] for w in lines[0] if 110 <= w['x0'] < 240]
    emp['name'] = ' '.join(first_line_names).strip()

    # Collect words by column
    left_col_texts = []
    name_col_texts = []
    allow_c1 = {}
    allow_c2 = {}
    ded_c1 = {}
    ded_c2 = {}

    for line in lines:
        ly = round(line[0]['top'])
        for w in line:
            x = w['x0']
            t = w['text'].strip()
            if not t:
                continue

            if len(t) <= 1 and not t.isdigit():
                continue

            if t.lower() in GARBAGE_WORDS and x > 420:
                continue

            if 40 <= x < 110:
                left_col_texts.append(t)

            elif 110 <= x < 240:
                name_col_texts.append(t)

            elif 240 <= x < 325:
                d = allow_c1.setdefault(ly, {'names': [], 'val': None})
                v = _pn(t)
                if v is not None and not re.match(r'^[A-Za-z]', t):
                    d['val'] = v
                else:
                    d['names'].append(t)

            elif 325 <= x < 420:
                d = allow_c2.setdefault(ly, {'names': [], 'val': None})
                v = _pn(t)
                if v is not None and not re.match(r'^[A-Za-z]', t):
                    d['val'] = v
                else:
                    d['names'].append(t)

            elif 420 <= x < 468:
                # Gross amount column (v5: tightened to 468, was 465)
                v = _pn(t)
                if v is not None and abs(v) > 50:
                    emp['gross_amount'] = v

            elif 468 <= x < 560:
                # Deduction column 1 (v5: starts at 468, was 460)
                d = ded_c1.setdefault(ly, {'names': [], 'val': None})
                v = _pn(t)
                if v is not None and not re.match(r'^[A-Za-z]', t):
                    d['val'] = v
                else:
                    d['names'].append(t)

            elif 560 <= x < 660:
                d = ded_c2.setdefault(ly, {'names': [], 'val': None})
                v = _pn(t)
                if v is not None and not re.match(r'^[A-Za-z]', t):
                    d['val'] = v
                else:
                    d['names'].append(t)

            elif 660 <= x < 715:
                v = _pn(t)
                if v is not None:
                    emp['sum_deduction'] = v

            elif x >= 715:
                v = _pn(t)
                if v is not None and abs(v) > 10:
                    emp['net_total'] = v

    # Convert column data to dictionaries
    emp['allowances'] = _lines_to_dict(allow_c1)
    emp['allowances'].update(_lines_to_dict(allow_c2))
    emp['deductions'] = _lines_to_dict(ded_c1)
    emp['deductions'].update(_lines_to_dict(ded_c2))

    # Clean up multi-line deduction names
    _cleanup_multiline(emp['deductions'])

    # Parse identity fields
    _parse_left_col(left_col_texts, emp)
    _parse_name_col(name_col_texts, emp)

    # Populate shortcut fields from allowances
    a = emp['allowances']
    emp['basic'] = a.get('Basic', 0)
    emp['da'] = a.get('DA', 0)
    emp['hra'] = a.get('HRA', 0)
    emp['cca'] = a.get('CCA', 0)
    emp['hda'] = a.get('HDA', 0)
    emp['mess_all'] = a.get('Mess All', a.get('Mess', 0))
    emp['rop'] = a.get('ROP', 0)
    emp['ca'] = a.get('CA', 0)

    # Populate shortcut fields from deductions
    d = emp['deductions']
    emp['itax'] = _fd(d, ['ITax'])
    emp['lic'] = _fd(d, ['LIC'])
    emp['gpf'] = _fd(d, ['GPF'])
    emp['sip'] = _fd(d, ['SIP'])
    emp['sil'] = _fd(d, ['SIL'])
    emp['sii'] = _fd(d, ['SII'])
    emp['rghs'] = _fd(d, ['RGHS'])
    emp['road_ways'] = _fd(d, ['ROAD WAYS DEDUTION', 'ROAD WAYS DEDUCTION', 'ROAD WAYS', 'ROADWAYS'])
    emp['advance_salary'] = _fd(d, ['Advance Salary', 'Advance'])
    emp['hba_hdfc'] = _fd(d, ['HBA-HDFC', 'HBA HDFC'])

    # Integrity checks — fill missing totals from available data
    if emp['gross_amount'] > 0 and emp['net_total'] > 0 and emp['sum_deduction'] == 0:
        emp['sum_deduction'] = emp['gross_amount'] - emp['net_total']
    if emp['gross_amount'] == 0 and emp['net_total'] > 0 and emp['sum_deduction'] > 0:
        emp['gross_amount'] = emp['net_total'] + emp['sum_deduction']
    if emp['gross_amount'] > 0 and emp['sum_deduction'] > 0 and emp['net_total'] == 0:
        emp['net_total'] = emp['gross_amount'] - emp['sum_deduction']
    # Last resort: calculate gross from allowance sum
    if emp['gross_amount'] == 0 and emp['basic'] > 0:
        allow_sum = sum(v for v in emp['allowances'].values() if isinstance(v, (int, float)))
        if allow_sum > 0:
            emp['gross_amount'] = float(allow_sum)

    return emp


def _lines_to_dict(col_lines):
    """
    Convert {line_y: {'names': [...], 'val': N}} to {name: value} dict.
    Handles multi-line deduction names by accumulating pending name fragments.
    """
    result = {}
    pending = []

    for ly in sorted(col_lines.keys()):
        info = col_lines[ly]
        names = info['names']
        val = info['val']

        filtered_names = [n for n in names if n.upper() not in ORPHAN_FRAGMENTS]

        if filtered_names and val is not None:
            first_name = filtered_names[0] if filtered_names else ''
            if pending and first_name in KNOWN_SINGLE_NAMES and len(filtered_names) <= 2:
                full_name = ' '.join(filtered_names).strip()
                result[full_name] = val
                pending = []
            else:
                full_name = ' '.join(pending + filtered_names).strip()
                result[full_name] = val
                pending = []

        elif filtered_names and val is None:
            pending.extend(filtered_names)

        elif not filtered_names and val is not None and pending:
            result[' '.join(pending).strip()] = val
            pending = []

        elif not filtered_names and val is not None and not pending:
            pass

        elif not filtered_names and val is None:
            pass

    return result


def _cleanup_multiline(d):
    """Post-process deduction dict: remove garbage, fix multi-line names."""
    # 1. Remove garbage entries
    garbage_keys = []
    for k in d:
        kl = k.lower()
        words_in_key = set(kl.split())
        if len(words_in_key) > 0:
            garbage_ratio = len(words_in_key & GARBAGE_WORDS) / len(words_in_key)
            if garbage_ratio > 0.5:
                garbage_keys.append(k)
        if len(k) > 30:
            garbage_keys.append(k)
    for k in set(garbage_keys):
        d.pop(k, None)

    # 2. Fix keys with DEDUTION/DEDUCTION
    for k in list(d.keys()):
        ku = k.upper()
        if 'DEDUTION' in ku or 'DEDUCTION' in ku:
            val = d.pop(k)
            clean = re.sub(r'DEDUTION\s*|DEDUCTION\s*', '', k, flags=re.IGNORECASE).strip()
            if clean and clean not in ('ROAD WAYS', 'ROAD', 'WAYS'):
                d[clean] = val

    # 3. Split keys where a known deduction name is embedded
    known_deds = ['GPF', 'SIP', 'SIL', 'SII', 'LIC', 'RGHS', 'ITax', 'HBA-HDFC',
                  'Per Ded', 'PPSS', 'Advance Salary']
    for k in list(d.keys()):
        if len(k) > 15:
            ku = k.upper()
            for dn in known_deds:
                if dn.upper() in ku and dn.upper() != ku:
                    val = d.pop(k)
                    d[dn] = val
                    break

    # 4. Merge ROAD/WAYS fragments
    road_keys = [k for k in d if any(x in k.upper() for x in ['ROAD', 'WAYS'])]
    if road_keys:
        val = next((d[k] for k in road_keys if d.get(k)), None)
        for k in road_keys:
            d.pop(k, None)
        if val is not None:
            d['ROAD WAYS DEDUTION'] = val

    # 5. Merge Advance/Salary fragments
    adv_keys = [k for k in d if k in ('Advance', 'Salary', 'Advance Salary')]
    if adv_keys:
        val = None
        for k in adv_keys:
            if d.get(k):
                val = d[k]
        for k in adv_keys:
            d.pop(k, None)
        if val is not None:
            d['Advance Salary'] = val


def _fd(d, names):
    """Find deduction value by possible names."""
    for n in names:
        if n in d:
            return d[n]
    for k, v in d.items():
        for n in names:
            if n.upper() in k.upper():
                return v
    return 0


# ===================== IDENTITY FIELD PARSERS =====================

def _parse_left_col(texts, emp):
    """Parse identity fields from left column (x: 40-110)."""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if re.match(r'^\d{5,}/(0|old)', t, re.I):
            emp['gpf_pran'] = t
        elif re.match(r'^\d{2}/\d{2}/\d{4}$', t):
            emp['dob'] = t
        elif re.match(r'^[A-Z]{5}\d{4}[A-Z]$', t):
            emp['pan'] = t
        elif re.match(r'^L\d{1,2}$', t):
            emp['pay_scale'] = t
        elif re.match(r'^\d+/\d+$', t) and len(t) <= 5:
            emp['grade_pay'] = t
        elif re.match(r'^\d{6}$', t) and not emp['st_ins_no']:
            emp['st_ins_no'] = t
        elif re.match(r'^\d{1,4}$', t) and not emp['belt_no']:
            emp['belt_no'] = t


def _parse_name_col(texts, emp):
    """Parse fields from name/designation column (x: 110-240)."""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if re.match(r'^RJ[A-Z]{2}\d{9,}', t):
            emp['employee_id'] = t
        elif re.match(r'^\d{10,}$', t):
            emp['bank_acc'] = t
        elif re.match(r'^X{4,}\d*$', t):
            emp['aadhar'] = t
        elif any(kw in t.upper() for kw in ['CONSTABLE', 'INSPECTOR', 'HEAD', 'SUB', 'ASI',
                                              'NAIK', 'HAVALDAR', 'DRIVER', 'SIPAHI']):
            if not emp['designation']:
                emp['designation'] = t
            else:
                emp['designation'] += ' ' + t


# ===================== OUTER SHEET PARSER =====================

def parse_outer_sheet(pdf_path):
    """Parse Outer Sheet (summary/cover page) PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return {}, {}
        page = pdf.pages[0]
        header = extract_header_info(page)
        text = page.extract_text() or ""
        allow = {}
        for m in re.finditer(r'(Basic|DA|HRA|CCA|CA|Mess All|HDA|ROP)\s+\d+\s+([\d-]+)', text):
            allow[m.group(1)] = _pn(m.group(2)) or 0
        deduct = {}
        for m in re.finditer(r'(ITax|LIC|GPF|SIP|SIL|SII|HBA-HDFC|RGHS)\s+\d+\s+([\d-]+)', text):
            deduct[m.group(1)] = _pn(m.group(2)) or 0
        totals = {}
        g = re.search(r'Gross\s*Amount[:\s]+([\d.]+)', text)
        totals['gross_amount'] = float(g.group(1)) if g else 0
        d = re.search(r'Total\s*Deduction[:\s]+([\d.]+)', text)
        totals['total_deduction'] = float(d.group(1)) if d else 0
        n = re.search(r'Net\s*Amount[:\s\u20b9]+([\d.]+)', text)
        totals['net_amount'] = float(n.group(1)) if n else 0
        return header, {'allowances': allow, 'deductions': deduct, 'totals': totals}


# ===================== SCHEDULE SHEET PARSER =====================

# Watermark characters to strip from text (appear in IFMS PDFs)
_WATERMARK_CHARS = {'SS', 'MM', 'FF', 'II', 'JJ', 'AA', 'RR', '¥'}


def parse_schedule_sheet(pdf_path):
    """Parse Schedule Sheet PDF — word-based extraction for each schedule type.
    Returns list of schedule dicts, each with type, header, entries, and grand_total.
    """
    schedules = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            stype = _det_sched_type(text)
            if not stype:
                continue
            
            header = extract_header_info(page)
            words = _data_words(page)
            entries, grand_total = _parse_schedule_page(words, stype, text)
            
            if entries:
                schedules.append({
                    'type': stype,
                    'header': header,
                    'entries': entries,
                    'grand_total': grand_total,
                    'count': len(entries)
                })
    return schedules


def _det_sched_type(text):
    tl = text.lower()
    for kw, st in [('income tax', 'income_tax'), ('lic', 'lic'), ('gpf contribution', 'gpf'),
                    ('gpf 2004', 'gpf_2004'), ('si premium', 'si_premium'), ('rghs', 'rghs'),
                    ('rop', 'rop'), ('advance salary', 'advance_salary'), ('road', 'roadways'),
                    ('hba', 'hba')]:
        if f'schedule of {kw}' in tl:
            return st
    if 'si premium' in tl:
        return 'si_premium'
    if 'schedule of' in tl:
        m = re.search(r'schedule of\s+([^\n(]+)', tl)
        return m.group(1).strip().replace(' ', '_') if m else None
    return None


def _parse_schedule_page(words, stype, full_text):
    """Parse a single schedule page using word positions.
    Returns (entries_list, grand_total_dict).
    """
    if not words:
        return [], {}
    
    # Find Sr.No. markers
    sr_markers = []
    for w in words:
        if w['x0'] < 40 and w['text'].isdigit():
            n = int(w['text'])
            if 1 <= n <= 500:
                sr_markers.append((n, w['top']))
    
    if not sr_markers:
        return [], {}
    
    sr_markers.sort(key=lambda x: x[1])
    
    # Footer boundary
    footer_y = 600
    for w in words:
        t = w.get('text', '')
        if t.startswith('Grand') or t.startswith('Rupees') or t.startswith('Disclaimer') or t.startswith('Sign'):
            footer_y = min(footer_y, w['top'])
    
    entries = []
    for i, (sr_no, y_start) in enumerate(sr_markers):
        y_end = sr_markers[i + 1][1] if i + 1 < len(sr_markers) else footer_y
        block_words = [w for w in words if y_start - 2 <= w['top'] < y_end - 2]
        if block_words:
            entry = _parse_schedule_entry(sr_no, block_words, stype)
            if entry and entry.get('employee_id'):
                entries.append(entry)
    
    # Extract grand total from text
    grand_total = _extract_schedule_grand_total(full_text, stype)
    
    return entries, grand_total


def _parse_schedule_entry(sr_no, block_words, stype):
    """Parse one schedule entry row using column positions specific to each type."""
    entry = {
        'sr_no': sr_no,
        'employee_id': '',
        'name': '',
        'designation': '',
        'basic_pay': 0,
        'schedule_type': stype,
    }
    
    block_words.sort(key=lambda w: (w['top'], w['x0']))
    
    # Group into lines
    lines = []
    cl, cy = [], -100
    for w in block_words:
        if abs(w['top'] - cy) > 3:
            if cl:
                lines.append(cl)
            cl, cy = [w], w['top']
        else:
            cl.append(w)
    if cl:
        lines.append(cl)
    
    # Employee ID: always at x 69-155
    emp_id_words = []
    name_words = []
    
    for line in lines:
        for w in line:
            x, t = w['x0'], w['text'].strip()
            if not t or t in _WATERMARK_CHARS:
                continue
            
            # Employee ID
            if 60 <= x < 160 and re.match(r'^RJ[A-Z]{2}\d{6,}', t):
                emp_id_words.append(t)
    
    if emp_id_words:
        entry['employee_id'] = emp_id_words[0]
    
    # Type-specific column parsing
    if stype == 'income_tax':
        _parse_income_tax_entry(lines, entry)
    elif stype == 'lic':
        _parse_lic_entry(lines, entry)
    elif stype == 'gpf':
        _parse_gpf_entry(lines, entry)
    elif stype == 'si_premium':
        _parse_si_premium_entry(lines, entry)
    elif stype == 'gpf_2004':
        _parse_gpf2004_entry(lines, entry)
    else:
        _parse_generic_entry(lines, entry)
    
    return entry


def _parse_income_tax_entry(lines, entry):
    """Income Tax schedule: PAN, Basic, ITax, SIT, HEC, HIEC, Total"""
    for line in lines:
        for w in line:
            x, t = w['x0'], w['text'].strip()
            if not t or t in _WATERMARK_CHARS:
                continue
            v = _pn(t.replace(',', ''))
            
            if 155 < x < 275 and re.match(r'^[A-Z]', t) and not re.match(r'^RJ', t):
                entry.setdefault('_name_parts', []).append(t)
            elif 360 <= x < 450 and re.match(r'^[A-Z]{5}\d{4}[A-Z]$', t):
                entry['pan'] = t
            elif 445 <= x < 500 and v is not None:
                entry['basic_pay'] = v
            elif 500 <= x < 565 and v is not None:
                entry['income_tax'] = v
            elif 575 <= x < 615 and v is not None:
                entry['sit'] = v
            elif 615 <= x < 695 and v is not None:
                entry['health_edu_cess'] = v
            elif 695 <= x < 760 and v is not None:
                entry['hi_edu_cess'] = v
            elif x >= 760 and v is not None:
                entry['total'] = v
    
    entry['name'] = ' '.join(entry.pop('_name_parts', []))
    # Set defaults
    for k in ['income_tax', 'sit', 'health_edu_cess', 'hi_edu_cess', 'total', 'pan']:
        entry.setdefault(k, 0 if k != 'pan' else '')


def _parse_lic_entry(lines, entry):
    """LIC schedule: Basic, Policy No, Premium, Total"""
    for line in lines:
        for w in line:
            x, t = w['x0'], w['text'].strip()
            if not t or t in _WATERMARK_CHARS:
                continue
            v = _pn(t.replace(',', ''))
            
            if 155 < x < 317 and re.match(r'^[A-Z]', t) and not re.match(r'^RJ', t):
                entry.setdefault('_name_parts', []).append(t)
            elif 535 <= x < 590 and v is not None and v > 1000:
                entry['basic_pay'] = v
            elif 610 <= x < 670 and v is not None:
                entry['policy_no'] = t  # Keep as string
            elif 670 <= x < 760 and v is not None:
                entry['premium'] = v
            elif x >= 760 and v is not None:
                entry['total'] = v
    
    entry['name'] = ' '.join(entry.pop('_name_parts', []))
    entry.setdefault('policy_no', '')
    entry.setdefault('premium', 0)
    entry.setdefault('total', 0)


def _parse_gpf_entry(lines, entry):
    """GPF Contribution schedule: GPF No, Basic, Contribution, Loan, Total"""
    for line in lines:
        for w in line:
            x, t = w['x0'], w['text'].strip()
            if not t or t in _WATERMARK_CHARS:
                continue
            v = _pn(t.replace(',', ''))
            
            if 155 < x < 289 and re.match(r'^[A-Z]', t) and not re.match(r'^RJ', t):
                entry.setdefault('_name_parts', []).append(t)
            elif 400 <= x < 460 and v is not None and not (v > 10000):
                entry['gpf_no'] = t
            elif 500 <= x < 555 and v is not None and v > 1000:
                entry['basic_pay'] = v
            elif 555 <= x < 645 and v is not None:
                entry['gpf_contribution'] = v
            elif 675 <= x < 735 and v is not None:
                entry['gpf_loan'] = v
            elif x >= 760 and v is not None:
                entry['total'] = v
    
    entry['name'] = ' '.join(entry.pop('_name_parts', []))
    for k in ['gpf_no', 'gpf_contribution', 'gpf_loan', 'total']:
        entry.setdefault(k, '' if k == 'gpf_no' else 0)


def _parse_si_premium_entry(lines, entry):
    """SI Premium schedule: SI Policy No, Basic, SI Premium, SI Loan, SI Interest, S.Tax, Total"""
    for line in lines:
        for w in line:
            x, t = w['x0'], w['text'].strip()
            if not t or t in _WATERMARK_CHARS:
                continue
            v = _pn(t.replace(',', ''))
            
            if 155 < x < 330 and re.match(r'^[A-Z]', t) and not re.match(r'^RJ', t):
                entry.setdefault('_name_parts', []).append(t)
            elif 325 <= x < 395 and v is not None:
                entry['si_policy_no'] = t
            elif 395 <= x < 450 and v is not None and v > 1000:
                entry['basic_pay'] = v
            elif 455 <= x < 520 and v is not None:
                entry['si_premium'] = v
            elif 530 <= x < 585 and v is not None:
                entry['si_loan'] = v
            elif 595 <= x < 655 and v is not None:
                entry['si_interest'] = v
            elif 675 <= x < 740 and v is not None:
                entry['s_tax_on_si'] = v
            elif x >= 760 and v is not None:
                entry['total'] = v
    
    entry['name'] = ' '.join(entry.pop('_name_parts', []))
    for k in ['si_policy_no', 'si_premium', 'si_loan', 'si_interest', 's_tax_on_si', 'total']:
        entry.setdefault(k, '' if k == 'si_policy_no' else 0)


def _parse_gpf2004_entry(lines, entry):
    """GPF 2004 schedule: Basic, GPF 2004, Loan A/C No, Deduction Amount"""
    for line in lines:
        for w in line:
            x, t = w['x0'], w['text'].strip()
            if not t or t in _WATERMARK_CHARS:
                continue
            v = _pn(t.replace(',', ''))
            
            if 155 < x < 346 and re.match(r'^[A-Z]', t) and not re.match(r'^RJ', t):
                entry.setdefault('_name_parts', []).append(t)
            elif 500 <= x < 555 and v is not None and v > 1000:
                entry['basic_pay'] = v
            elif 585 <= x < 640 and v is not None:
                entry['gpf_2004'] = v
            elif 640 <= x < 720 and v is not None:
                entry['loan_ac_no'] = t
            elif x >= 730 and v is not None:
                entry['total'] = v
    
    entry['name'] = ' '.join(entry.pop('_name_parts', []))
    for k in ['gpf_2004', 'loan_ac_no', 'total']:
        entry.setdefault(k, '' if k == 'loan_ac_no' else 0)


def _parse_generic_entry(lines, entry):
    """Generic fallback: extract name and total from rightmost column"""
    for line in lines:
        for w in line:
            x, t = w['x0'], w['text'].strip()
            if not t or t in _WATERMARK_CHARS:
                continue
            v = _pn(t.replace(',', ''))
            if 155 < x < 400 and re.match(r'^[A-Z]', t) and not re.match(r'^RJ', t):
                entry.setdefault('_name_parts', []).append(t)
            elif x >= 760 and v is not None:
                entry['total'] = v
    entry['name'] = ' '.join(entry.pop('_name_parts', []))
    entry.setdefault('total', 0)


def _extract_schedule_grand_total(text, stype):
    """Extract Grand Total from schedule page text."""
    gt = {}
    m = re.search(r'Grand\s*Total[:\s]+([\d,]+\.?\d*)', text)
    if m:
        gt['total'] = _pn(m.group(1).replace(',', '')) or 0
    # Also get the Rupees in Words line
    rw = re.search(r'Rupees\s+in\s+Words[:\s]+(.+?)(?:\n|$)', text)
    if rw:
        gt['in_words'] = rw.group(1).strip()
    return gt


# ===================== MAIN ENTRY POINT =====================

def parse_any_pdf(pdf_path):
    """Auto-detect PDF type and parse accordingly."""
    st = detect_sheet_type(pdf_path)
    if st == 'inner':
        h, e, gt = parse_inner_sheet(pdf_path)
        return {'type': 'inner', 'header': h, 'employees': e, 'count': len(e), 'grand_totals': gt}
    elif st == 'outer':
        h, s = parse_outer_sheet(pdf_path)
        return {'type': 'outer', 'header': h, 'summary': s}
    elif st == 'schedule':
        s = parse_schedule_sheet(pdf_path)
        return {'type': 'schedule', 'schedules': s, 'count': len(s)}
    return {'type': 'unknown', 'error': 'Could not detect sheet type'}
