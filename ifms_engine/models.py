from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class ComponentParseResult:
    component_type: str  # 'allowance' or 'deduction'
    raw_head: str
    normalized_head: str = ""
    amount: float = 0.0
    source_page: int = 1
    source_y: float = 0.0

@dataclass
class EmployeeParseResult:
    sr_no: Optional[int] = None
    raw_name: str = ""
    raw_designation: str = ""
    normalized_designation: str = ""
    employee_id: str = ""
    gpf_pran_raw: str = ""
    dob: str = ""
    belt_no: str = ""
    pan_raw: str = ""
    pan_status: str = ""
    pay_scale_raw: str = ""
    grade_pay: str = ""
    bank_acc: str = ""
    aadhar_raw: str = ""
    st_ins_no: str = ""
    gross_amount: float = 0.0
    sum_deduction: float = 0.0
    net_total: float = 0.0
    components: List[ComponentParseResult] = field(default_factory=list)
    issues: List['ValidationIssue'] = field(default_factory=list)
    raw_text_block: str = ""
    page_no: int = 1

@dataclass
class ValidationIssue:
    issue_type: str
    severity: str
    message: str
    raw_value: str = ""
    employee_id: Optional[str] = None
    suggested_value: str = ""

@dataclass
class BillParseResult:
    source_filename: str = ""
    group_name: str = ""
    month_year: str = ""
    bill_no: str = ""
    reference_no: str = ""
    budget_head_full: str = ""
    page_count: int = 0
    official_gross: float = 0.0
    official_deduction: float = 0.0
    official_net: float = 0.0
    employees: List[EmployeeParseResult] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)
