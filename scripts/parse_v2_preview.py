import sys
import os
import json

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Add parent dir to path so we can import ifms_engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ifms_engine.pdf_reader import PDFReader
from ifms_engine.header_parser import HeaderParser
from ifms_engine.employee_block_detector import EmployeeBlockDetector
from ifms_engine.employee_parser import EmployeeParser
from ifms_engine.validator import EngineValidator

def parse_preview(pdf_path):
    print(f"--- Parsing {pdf_path} ---")
    
    reader = PDFReader(pdf_path)
    words = reader.extract_words()
    
    # Header metadata
    meta = HeaderParser.extract_metadata(words)
    print("Bill Metadata:", json.dumps(meta, indent=2))
    
    # Employee blocks
    blocks = EmployeeBlockDetector.detect_blocks(words)
    print(f"Employee Count: {len(blocks)}")
    
    print("\n--- First 5 Employee Parsed Results ---")
    for i, block in enumerate(blocks[:5]):
        emp = EmployeeParser.parse_employee(block)
        EngineValidator.validate_employee(emp)
        print(f"Employee {i+1}:")
        print(f"  Name: {emp.raw_name}")
        print(f"  Designation: {emp.raw_designation} -> {emp.normalized_designation}")
        print(f"  GPF/PRAN: {emp.gpf_pran_raw}")
        print(f"  DOB: {emp.dob}")
        print(f"  PAN: {emp.pan_raw}")
        print(f"  Bank: {emp.bank_acc}")
        print(f"  Gross: {emp.gross_amount}")
        print(f"  Deduction: {emp.sum_deduction}")
        print(f"  Net: {emp.net_total}")
        allowances = [c for c in emp.components if c.component_type == 'allowance']
        deductions = [c for c in emp.components if c.component_type == 'deduction']
        print(f"  Allowances: {len(allowances)} -> {[(c.raw_head, c.normalized_head, c.amount) for c in allowances]}")
        print(f"  Deductions: {len(deductions)} -> {[(c.raw_head, c.normalized_head, c.amount) for c in deductions]}")
        print(f"  Issues: {len(emp.issues)}")
        for issue in emp.issues:
            print(f"    - [{issue.severity}] {issue.issue_type}: {issue.message}")
        print("-" * 20)

    reader.close()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python parse_v2_preview.py <path_to_pdf>")
        sys.exit(1)
        
    parse_preview(sys.argv[1])
