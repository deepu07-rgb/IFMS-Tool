import re
from typing import List, Dict, Any
from ifms_engine.models import EmployeeParseResult, ComponentParseResult, ValidationIssue
from ifms_engine.layout_detector import LayoutDetector

from ifms_engine.dictionary import DictionaryManager

class EmployeeParser:
    DESIGNATION_SUFFIXES = [
        "ASSISTANT SUB-INSPECTOR",
        "HEAD CONSTABLE",
        "SUB-INSPECTOR",
        "CONSTABLE",
        "INSPECTOR",
    ]
    SUMMARY_FOOTER_PATTERNS = [
        "GROSS AMOUNT",
        "DEDUCTION AMOUNT",
        "NET AMOUNT",
        "AMOUNT IN WORDS",
        "CERTIFICATES",
        "CERTIFIED THAT",
        "ENCLOSURE",
        "SIGN",
        "PRINT DATE",
        "FORWARD DATE",
        "GROUP NAME",
        "DISCLAIMER",
        "NOTE:",
    ]

    @staticmethod
    def _parse_num(text: str):
        clean = (text or "").replace(",", "").strip()
        if re.match(r"^-?\d+(?:\.\d+)?$", clean):
            try:
                return float(clean)
            except ValueError:
                return None
        return None

    @staticmethod
    def _line_buckets(words: List[Dict[str, Any]], y_tol: float = 3.0):
        lines = []
        for w in sorted(words, key=lambda z: (z['y0'], z['x0'])):
            placed = False
            for ln in lines:
                if abs(ln['y'] - w['y0']) <= y_tol:
                    ln['words'].append(w)
                    placed = True
                    break
            if not placed:
                lines.append({'y': w['y0'], 'words': [w]})
        return lines

    @staticmethod
    def _is_summary_footer_text(text: str) -> bool:
        upper = " ".join((text or "").upper().replace(".", " ").split())
        return any(pattern in upper for pattern in EmployeeParser.SUMMARY_FOOTER_PATTERNS)

    @staticmethod
    def _filter_component_words(words: List[Dict[str, Any]], emp: EmployeeParseResult, comp_type: str):
        kept = []
        for ln in EmployeeParser._line_buckets(words):
            line_words = sorted(ln['words'], key=lambda z: z['x0'])
            line_text = " ".join(w.get('text', '') for w in line_words)
            if EmployeeParser._is_summary_footer_text(line_text):
                emp.issues.append(ValidationIssue(
                    issue_type='SUMMARY_CONTAMINATION_DETECTED',
                    severity='LOW',
                    message=f'Summary/footer text was excluded from {comp_type} component extraction.',
                    raw_value=line_text,
                    employee_id=emp.employee_id,
                    suggested_value='Ignored summary/footer line'
                ))
                continue
            kept.extend(line_words)
        return kept

    @staticmethod
    def _extract_printed_total(col_words: List[Dict[str, Any]], anchor_y: float, banned_ys: List[float]) -> float:
        if not col_words:
            return 0.0
        candidates = []
        for w in col_words:
            if any(abs(w['y0'] - by) <= 3.0 for by in banned_ys):
                continue
            val = EmployeeParser._parse_num(w.get('text', ''))
            if val is not None:
                candidates.append((val, w['y0'], w['x0']))
        if not candidates:
            return 0.0

        # Prefer values near the employee's main row to avoid footer/final-summary contamination.
        near = [c for c in candidates if anchor_y - 4 <= c[1] <= anchor_y + 40]
        pool = near if near else candidates
        pool.sort(key=lambda c: (abs(c[1] - anchor_y), c[1], c[2]))
        return pool[0][0]

    @staticmethod
    def _find_row_total_token(block: List[Dict[str, Any]], anchor_y: float, expected_value: float):
        candidates = []
        for w in block:
            if not (640 <= w['x0'] < 900):
                continue
            if abs(w['y0'] - anchor_y) > 8:
                continue
            val = EmployeeParser._parse_num(w.get('text', ''))
            if val is None:
                continue
            if abs(round(val, 2) - round(expected_value, 2)) <= 1:
                candidates.append((w['x0'], w['y0'], val))
        if not candidates:
            return None
        # Prefer the right-most matching token on the employee's own total row.
        candidates.sort(key=lambda c: (-c[0], abs(c[1] - anchor_y)))
        return candidates[0]

    @staticmethod
    def parse_components(words: List[Dict[str, Any]], comp_type: str) -> List[ComponentParseResult]:
        components = []
        # Group words by line (Y coordinate, with some tolerance)
        lines = {}
        for w in words:
            # Round Y to nearest 5 to group into lines roughly
            y_bucket = round(w['y0'] / 5) * 5
            if y_bucket not in lines:
                lines[y_bucket] = []
            lines[y_bucket].append(w)
            
        for y, line_words in sorted(lines.items()):
            # Sort by X to read left to right
            line_words.sort(key=lambda w: w['x0'])
            line_text = " ".join(w.get('text', '') for w in line_words)
            if EmployeeParser._is_summary_footer_text(line_text):
                continue
            
            # Simple state machine to find [String] -> [Number]
            current_head_words = []
            for w in line_words:
                text = w['text']
                # Clean up commas in numbers
                clean_num = text.replace(',', '')
                # Check if it's a number
                is_num = False
                amount = 0.0
                try:
                    amount = float(clean_num)
                    is_num = True
                except ValueError:
                    is_num = False
                    
                if is_num:
                    # Handle compound head like "GPF 2004" where 2004 is part of head,
                    # not the deduction amount.
                    if current_head_words and clean_num in ("2004", "2004.0"):
                        prev = " ".join(current_head_words).upper()
                        if "GPF" in prev:
                            current_head_words.append("2004")
                            continue
                    if current_head_words:
                        raw_head = " ".join(current_head_words)
                        components.append(ComponentParseResult(
                            component_type=comp_type,
                            raw_head=raw_head,
                            normalized_head=DictionaryManager.normalize_head(raw_head),
                            amount=amount,
                            source_page=w['page_no'],
                            source_y=w['y0']
                        ))
                        current_head_words = [] # Reset for next component on same line
                else:
                    if text not in ['-', '0']:
                        current_head_words.append(text)
                        
        return components

    @staticmethod
    def parse_employee(block: List[Dict[str, Any]]) -> EmployeeParseResult:
        emp = EmployeeParseResult()
        
        if not block:
            return emp
            
        emp.page_no = block[0]['page_no']
        
        # Sort words primarily by Y, then X for reading order
        block.sort(key=lambda w: (w['y0'], w['x0']))
        
        raw_text = []
        name_words = []
        identity_words = []
        gross_words = []
        deduction_total_words = []
        net_words = []
        allowance_words = []
        deduction_words = []
        sr_y = None
        
        for w in block:
            x = w['x0']
            y = w['y0']
            text = w['text']
            raw_text.append(text)
            
            if LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_SR_NO) and text.isdigit():
                emp.sr_no = int(text)
                if sr_y is None:
                    sr_y = y
            
            elif LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_IDENTITY):
                identity_words.append(text)
                
            elif LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_NAME_DESIG):
                name_words.append(text)
                
            elif LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_GROSS):
                gross_words.append(w)
                
            elif LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_SUM_DEDUCTION):
                deduction_total_words.append(w)
                
            elif LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_NET):
                net_words.append(w)
                
            elif LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_ALLOWANCE):
                allowance_words.append(w)
                
            elif LayoutDetector.is_in_zone(x, y, LayoutDetector.COL_DEDUCTION):
                deduction_words.append(w)

        emp.raw_text_block = " ".join(raw_text)
        if sr_y is None:
            sr_y = min(w['y0'] for w in block)
        
        # 1. Parse name/designation from the name column without letting lower
        # identity rows pollute the employee name.
        name_col_words = [
            w for w in block
            if LayoutDetector.is_in_zone(w['x0'], w['y0'], LayoutDetector.COL_NAME_DESIG)
        ]
        first_name_line = [
            w['text'] for w in name_col_words
            if abs(w['y0'] - sr_y) <= 5 and not re.match(r'^RJ[A-Z]{2}\d{6,}', w['text'])
        ]
        emp.raw_name = " ".join(first_name_line).strip()

        designation_words = [
            w['text'] for w in name_col_words
            if sr_y + 5 < w['y0'] < sr_y + 28
            and not re.match(r'^RJ[A-Z]{2}\d{6,}', w['text'])
            and w['text'].lower() != 'null'
            and not re.match(r'^\d{8,}$', w['text'])
        ]
        emp.raw_designation = " ".join(designation_words).strip()

        upper_name = emp.raw_name.upper()
        for suffix in EmployeeParser.DESIGNATION_SUFFIXES:
            if upper_name.endswith(" " + suffix):
                emp.raw_name = emp.raw_name[: -len(suffix)].strip()
                if not emp.raw_designation:
                    emp.raw_designation = suffix
                break

        emp.normalized_designation = DictionaryManager.normalize_designation(emp.raw_designation)

        # 2. Parse Identity Col
        id_str = " ".join(identity_words)
        date_match = re.search(r'\d{2}/\d{2}/\d{4}', id_str)
        if date_match:
            emp.dob = date_match.group(0)
            
        for text in identity_words:
            if re.match(r'[A-Z]{5}\d{4}[A-Z]{1}', text):
                emp.pan_raw = text
            elif 'GPF' in text or 'PRAN' in text or '/' in text and not re.match(r'\d{2}/\d{2}/\d{4}', text):
                if not emp.gpf_pran_raw:
                    emp.gpf_pran_raw = text
            elif text.isdigit() and len(text) > 8:
                emp.bank_acc = text
        for text in raw_text:
            if re.match(r'^RJ[A-Z]{2}\d{6,}', text):
                emp.employee_id = text
                break
        for text in raw_text:
            if re.match(r'^L\d{1,2}[A-Za-z]?(?:-FIXED)?$', text, re.IGNORECASE):
                emp.pay_scale_raw = text
                break
        for text in raw_text:
            if re.match(r'^[A-Z]{5}\d{4}[A-Z]$', text):
                emp.pan_raw = text
                break
            if not emp.pan_raw and re.match(r'^[A-Z0-9]{10}$', text) and any(ch.isalpha() for ch in text) and any(ch.isdigit() for ch in text):
                # Preserve odd PAN-like PDF tokens for review; do not normalize/fix.
                emp.pan_raw = text
        for text in raw_text:
            if not emp.aadhar_raw and re.match(r'^X{4,}\d{4}$', text, re.IGNORECASE):
                emp.aadhar_raw = text
            if not emp.bank_acc and text.isdigit() and 10 <= len(text) <= 18:
                emp.bank_acc = text
                
        # 3. Parse printed totals (row-anchored, footer-safe).
        lines = EmployeeParser._line_buckets(block)
        banned_ys = []
        for ln in lines:
            txt = " ".join(w.get('text', '') for w in sorted(ln['words'], key=lambda z: z['x0'])).lower()
            if (
                ("gross" in txt and "amount" in txt)
                or ("deduction" in txt and "amount" in txt)
                or ("net" in txt and "amount" in txt)
                or "group name" in txt
                or "disclaimer" in txt
            ):
                banned_ys.append(ln['y'])

        emp.gross_amount = EmployeeParser._extract_printed_total(gross_words, sr_y, banned_ys)
        emp.sum_deduction = EmployeeParser._extract_printed_total(deduction_total_words, sr_y, banned_ys)
        emp.net_total = EmployeeParser._extract_printed_total(net_words, sr_y, banned_ys)

        # Fallback for shifted print alignment: derive printed G/D/N from row-right numeric triplet.
        if emp.gross_amount > 0 and (emp.net_total <= 0 or emp.sum_deduction <= 0):
            row_nums = []
            for w in block:
                if not (420 <= w['x0'] < 900):
                    continue
                if abs(w['y0'] - sr_y) > 8:
                    continue
                v = EmployeeParser._parse_num(w.get('text', ''))
                if v is None:
                    continue
                row_nums.append((w['x0'], v))
            row_nums.sort(key=lambda x: x[0])
            # Typical row has gross, deduction, net in left-to-right order.
            if len(row_nums) >= 3:
                g2, d2, n2 = row_nums[-3][1], row_nums[-2][1], row_nums[-1][1]
                if emp.gross_amount <= 0:
                    emp.gross_amount = g2
                if emp.sum_deduction <= 0:
                    emp.sum_deduction = d2
                if emp.net_total <= 0:
                    emp.net_total = n2

        # Some officer-style rows print the net just left of the nominal net
        # column. If the extracted net is inconsistent, recover the printed
        # row token that exactly matches gross-deduction instead of using
        # footer/date text from later in the block.
        if emp.gross_amount > 0 and emp.sum_deduction > 0:
            expected_net = emp.gross_amount - emp.sum_deduction
            if expected_net > 0 and abs(round(emp.net_total, 2) - round(expected_net, 2)) > 1:
                row_net_token = EmployeeParser._find_row_total_token(block, sr_y, expected_net)
                if row_net_token is not None:
                    old_net = emp.net_total
                    emp.net_total = row_net_token[2]
                    emp.issues.append(ValidationIssue(
                        issue_type='NET_TOTAL_COLUMN_OVERLAP_FALLBACK',
                        severity='LOW',
                        message='Printed net was recovered from the employee row because it overlapped the deduction/net column boundary.',
                        raw_value=f'old_net={old_net},row_token={row_net_token[2]},x={row_net_token[0]},y={row_net_token[1]}',
                        employee_id=emp.employee_id,
                        suggested_value='Verify row net token if layout changes'
                    ))

        # 3b. Explicitly flag suspected deduction/net swap; do not auto-correct values.
        if emp.gross_amount > 0 and emp.sum_deduction > 0 and emp.net_total > 0:
            lhs1 = round(emp.gross_amount - emp.sum_deduction, 2)
            rhs1 = round(emp.net_total, 2)
            lhs2 = round(emp.gross_amount - emp.net_total, 2)
            rhs2 = round(emp.sum_deduction, 2)
            if abs(lhs1 - rhs1) > 1:
                emp.issues.append(ValidationIssue(
                    issue_type='PRINTED_TOTAL_MISMATCH',
                    severity='HIGH',
                    message='Printed totals are internally inconsistent (gross - deduction != net).',
                    raw_value=f'gross={emp.gross_amount},deduction={emp.sum_deduction},net={emp.net_total}',
                    employee_id=emp.employee_id,
                    suggested_value='Verify printed gross/deduction/net from PDF row'
                ))
            if abs(lhs1 - rhs1) > 1 and abs(lhs2 - rhs2) <= 1:
                emp.issues.append(ValidationIssue(
                    issue_type='SUSPECTED_DEDUCTION_NET_SWAP',
                    severity='HIGH',
                    message='Printed deduction and net totals appear swapped for this employee row.',
                    raw_value=f'gross={emp.gross_amount},deduction={emp.sum_deduction},net={emp.net_total}',
                    employee_id=emp.employee_id,
                    suggested_value='Verify printed row totals manually'
                ))
        
        # 4. Parse Components
        allowance_words = EmployeeParser._filter_component_words(allowance_words, emp, 'allowance')
        deduction_words = EmployeeParser._filter_component_words(deduction_words, emp, 'deduction')
        allowances = EmployeeParser.parse_components(allowance_words, 'allowance')
        deductions = EmployeeParser.parse_components(deduction_words, 'deduction')
        emp.components = allowances + deductions
        known_heads = {
            'basic_pay', 'da', 'hra', 'cca', 'hda', 'mess_allowance', 'fta',
            'lic', 'gpf', 'gpf_2004', 'rghs', 'sip', 'sil', 'income_tax',
            'roadways_deduction', 'advance_salary', 'ppss_jdr', 'rop',
            'car_rent', 'hfrh', 'eacpenf', 'giais', 'ais_gpf', 'sii',
            'per_ded_1', 'per_ded_2', 'kma_allowance', 'mta', 'special_pay',
            'wash_allowance'
        }
        for comp in emp.components:
            if comp.normalized_head not in known_heads:
                emp.issues.append(ValidationIssue(
                    issue_type='UNKNOWN_COMPONENT_HEAD',
                    severity='MEDIUM',
                    message=f'Unknown component head: {comp.raw_head}',
                    raw_value=comp.raw_head,
                    employee_id=emp.employee_id,
                    suggested_value=comp.normalized_head
                ))
        
        return emp
