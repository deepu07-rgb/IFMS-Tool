from typing import List
from ifms_engine.models import EmployeeParseResult, ValidationIssue
from ifms_engine.dictionary import DictionaryManager

class EngineValidator:
    @staticmethod
    def validate_employee(emp: EmployeeParseResult):
        calc_gross = sum(c.amount for c in emp.components if c.component_type == 'allowance')
        calc_deduction = sum(
            c.amount for c in emp.components
            if c.component_type == 'deduction' and c.normalized_head != 'roadways_deduction'
        )
        calc_net = calc_gross - calc_deduction
        
        issues = []
        
        # Component extraction may be incomplete; report as a component-class issue
        # rather than flooding row-level printed-total mismatch categories.
        mismatch_bits = []
        if round(calc_gross) != round(emp.gross_amount) and emp.gross_amount > 0:
            mismatch_bits.append(f'gross(calc={calc_gross},printed={emp.gross_amount})')
        if round(calc_deduction) != round(emp.sum_deduction) and emp.sum_deduction > 0:
            mismatch_bits.append(f'deduction(calc={calc_deduction},printed={emp.sum_deduction})')
        if round(calc_net) != round(emp.net_total) and emp.net_total > 0:
            mismatch_bits.append(f'net(calc={calc_net},printed={emp.net_total})')
        if mismatch_bits:
            issues.append(ValidationIssue(
                issue_type='COMPONENT_EXTRACTION_MISMATCH',
                severity='MEDIUM',
                message='Component-derived totals do not align with printed row totals.',
                raw_value="; ".join(mismatch_bits),
                employee_id=emp.employee_id,
                suggested_value='Review component head extraction for this row'
            ))
            
        if emp.raw_designation and emp.normalized_designation == emp.raw_designation.upper():
            # Basic check for unmapped: if normalized is just uppercase raw, might be unmapped.
            # But actual check according to prompt: "If designation is unmapped (DictionaryManager doesn't know it), add ValidationIssue"
            # Since DictionaryManager returns clean.upper() as fallback, we can check if clean.upper() is not in a known list, or just check this fallback logic.
            # Better: if DictionaryManager.normalize_designation didn't map it to a predefined, it's unmapped.
            # Let's say if it doesn't match values in DEFAULT_DESIGNATIONS.values().
            known_desigs = {"Head Constable", "Constable", "Assistant Sub-Inspector", "Sub-Inspector", "Inspector", "Class IV"}
            if emp.normalized_designation not in known_desigs:
                issues.append(ValidationIssue(
                    issue_type='UNMAPPED_DESIGNATION',
                    severity='MEDIUM',
                    message=f'Designation {emp.raw_designation} is not mapped in dictionary',
                    raw_value=emp.raw_designation,
                    employee_id=emp.employee_id
                ))
        elif emp.normalized_designation == "Unmapped":
            issues.append(ValidationIssue(
                issue_type='UNMAPPED_DESIGNATION',
                severity='MEDIUM',
                message=f'Designation {emp.raw_designation} is not mapped in dictionary',
                raw_value=emp.raw_designation,
                employee_id=emp.employee_id
            ))
                
        emp.issues.extend(issues)
