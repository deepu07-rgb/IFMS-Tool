import re
import pdfplumber
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

PAY_ID_MAPPING = {
    "100": "Basic", "104": "DA", "107": "HRA", "108": "CCA",
    "117": "Mess All", "119": "HDA", "120": "NPA", "122": "Wash All",
    "124": "Hard All", "126": "SP Pay", "202": "ITax", "205": "HFRH",
    "207": "HRA Ded", "208": "Car Rent", "210": "LIC", "215": "GPF",
    "217": "SIP", "218": "SIL", "222": "GIAIS", "237": "AIS GPF",
    "263": "EACPenF", "281": "GI CC", "294": "GPF 2004", "297": "RGHS"
}

def clean_money(v):
    """Convert Indian number format or currency string to integer."""
    if not v:
        return 0
    try:
        # Remove commas
        cleaned = str(v).replace(',', '')
        # Extract the first matching number pattern
        match = re.search(r'[+-]?\d+(?:\.\d+)?', cleaned)
        if match:
            return int(Decimal(match.group(0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return 0
    except:
        return 0

def clean_watermarks(text):
    """
    Remove RAJ IFMS 3.0 watermarks without corrupting real data.
    The watermark appears as 'RAJ IFMS 3.0' diagonally but pdfplumber may scatter
    its individual letters into the data lines. We only remove the full phrase
    and truly isolated single-char occurrences surrounded by whitespace.
    We do NOT strip single letters that are inside or adjacent to words/numbers
    because that would corrupt 'HDA', 'HRA', 'DA', 'NPA' etc.
    """
    # Remove the full watermark text phrase
    text = re.compile(r'RAJ\s*IFMS\s*3\.0', re.I).sub('', text)
    # Remove isolated watermark letters ONLY when surrounded by spaces or at line boundaries
    # Use word boundary approach: match only chars that appear as completely standalone tokens
    # e.g. " R " or " A " but NOT "HRA" or "DA"
    text = re.sub(r'(?<!\w)([RAJIFMS])(?!\w)', '', text)
    return text

def parse_date(date_str):
    """Normalize various date formats to YYYY-MM-DD for sorting."""
    if not date_str:
        return None
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None

def extract_pdf_data(pdf_path, filename="", custom_mappings=None):
    """
    Extracts all metadata, allowances, and deductions from an IFMS 3.0 PDF.
    Dynamically identifies all items and verifies calculation accuracy.
    """
    if custom_mappings is None:
        custom_mappings = {}

    data = {
        "Reference Number": "",
        "Group Name": "",
        "Bill Name": "",
        "Bill Date": "",
        "Bill Date Parsed": "",
        "Gross Amount": 0,
        "Net Amount": 0,
        "Stated_Total_Deduction": 0,
        "Allowances": {},
        "Deductions": {},
        "Confidence_Score": "✅",
        "Confidence_Reasons": [],
        "Unknown_Pay_IDs": []
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                data["Confidence_Score"] = "❌"
                data["Confidence_Reasons"].append("PDF has 0 pages.")
                return data

            # Extract text from the first page (outer sheet is always on page 1)
            text = pdf.pages[0].extract_text() or ""
            if not text.strip():
                data["Confidence_Score"] = "❌"
                data["Confidence_Reasons"].append("No text could be extracted from PDF.")
                return data

            # Clean watermark interference
            cleaned_text = clean_watermarks(text)

            # === REFERENCE NUMBER ===
            ref_match = re.search(r'Reference\s*No\s*[:\s]+(\d{9})', cleaned_text, re.I)
            if ref_match:
                data["Reference Number"] = ref_match.group(1)
            else:
                bill_match = re.search(r'Bill\s*No\s*[:\s]+(\d{9})', cleaned_text, re.I)
                if bill_match:
                    data["Reference Number"] = bill_match.group(1)
                else:
                    data["Confidence_Reasons"].append("Reference/Bill Number not found.")
                    data["Confidence_Score"] = "⚠️"

            # === BILL DATE ===
            date_match = re.search(r'Bill\s*Date\s*[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', cleaned_text, re.I)
            if date_match:
                data["Bill Date"] = date_match.group(1)
                data["Bill Date Parsed"] = parse_date(data["Bill Date"])
            else:
                data["Confidence_Reasons"].append("Bill Date not found.")
                data["Confidence_Score"] = "⚠️"

            # === BILL TYPE / NAME ===
            if "Inner Sheet" in cleaned_text:
                data["Bill Name"] = "Salary Bill (Inner)"
            elif "Salary Arrear" in cleaned_text:
                data["Bill Name"] = "Salary Arrear"
            elif "Regular" in cleaned_text and "Salary Bill" in cleaned_text:
                data["Bill Name"] = "Salary Bill (Regular)"
            elif "Surrender Bill" in cleaned_text:
                data["Bill Name"] = "Surrender Bill"
            elif "Salary Bill" in cleaned_text:
                data["Bill Name"] = "Salary Bill"
            else:
                data["Bill Name"] = "Other"

            # === GROUP NAME ===
            group_patterns = [
                r'Group\s*Name\s*[:\s]+([A-Za-z0-9/\-\s\.]+?)(?=\s*(?:Print|Forward)\s*Date)',
                r'Group\s*Name\s*[:\s]+([A-Za-z0-9/\-\s\.]+?)(?=\s*Print)',
                r'Group\s*Name\s*[:\s]+([^\n]+)',
            ]
            for p in group_patterns:
                g_match = re.search(p, cleaned_text, re.I)
                if g_match:
                    gname = g_match.group(1).strip()
                    # Clean trailing print/forward timestamp leftovers
                    gname = re.sub(r'\s*Print.*$', '', gname, flags=re.I).strip()
                    gname = re.sub(r'\s*Forward.*$', '', gname, flags=re.I).strip()
                    if gname and len(gname) > 1:
                        data["Group Name"] = gname
                        break

            # === GROSS AMOUNT ===
            gross_match = re.search(r'Gross\s*Amount\s*[:\s]+([\d,]+(?:\.\d+)?)', cleaned_text, re.I)
            if gross_match:
                data["Gross Amount"] = clean_money(gross_match.group(1))
            else:
                # Fallback for some layouts
                gross_match = re.search(r'Gross\s+([\d,]+(?:\.\d+)?)', cleaned_text, re.I)
                if gross_match:
                    data["Gross Amount"] = clean_money(gross_match.group(1))

            # === NET AMOUNT ===
            net_found = False
            for p in [r'Net\s*Amount\s*[:\s]+[₹\s]*([\d,]+(?:\.\d+)?)',
                      r'Please\s*[Oo]rder\s*to\s*pay\s*[₹Rs\.\s]*([\d,]+(?:\.\d+)?)',
                      r'Pay\s*Rs\.\s*[₹\s]*([\d,]+(?:\.\d+)?)']:
                n_match = re.search(p, cleaned_text, re.I)
                if n_match:
                    data["Net Amount"] = clean_money(n_match.group(1))
                    net_found = True
                    break
            
            if not net_found:
                data["Confidence_Reasons"].append("Net Amount/Pay order not found.")
                data["Confidence_Score"] = "⚠️"

            # === STATED TOTAL DEDUCTION ===
            ded_match = re.search(r'Total\s*Deduction\s*[:\s]+([\d,]+(?:\.\d+)?)', cleaned_text, re.I)
            if ded_match:
                data["Stated_Total_Deduction"] = clean_money(ded_match.group(1))

            # === DYNAMIC ALLOWANCES & DEDUCTIONS EXTRACTION ===
            # - Group 1: Allowance or Deduction Name
            # - Group 2: Pay ID (allows attached optional [A-Z] watermark char)
            # - Group 3: Amount (allows attached optional [A-Z] watermark char)
            item_regex = re.compile(
                r'([A-Za-z][A-Za-z0-9\s\/\-\(\)\.\+\&]*?)\s+([A-Z]?(?:[1-4]\d{2})[A-Z]?)\s+([A-Z]?[+-]?[\d,]+(?:\.\d+)?[A-Z]?)'
            )

            lines = cleaned_text.split('\n')
            for line in lines:
                # Skip header/footer metadata lines to prevent false matches
                if any(x in line for x in ["Reference No", "TAN No", "DDO Code", "Office ID", "Budget Head", "Disclaimer"]):
                    continue
                
                matches = item_regex.findall(line)
                for match in matches:
                    raw_name = match[0].strip()
                    pay_id_raw = match[1].strip()
                    amount_raw = match[2].strip()

                    # Extract pure digits for pay_id to strip any attached watermark letters
                    pay_id_match = re.search(r'([1-4]\d{2})', pay_id_raw)
                    if not pay_id_match:
                        continue
                    pay_id = pay_id_match.group(1)

                    amount = clean_money(amount_raw)

                    # Use standard name if Pay ID is known, else check custom mappings, else fallback
                    name = PAY_ID_MAPPING.get(pay_id)
                    if not name:
                        name = custom_mappings.get(pay_id)
                    
                    if not name:
                        name = re.sub(r'\s+[A-Z]\s*$', '', raw_name).strip()
                        # Track it so UI can prompt user
                        data["Unknown_Pay_IDs"].append({"pay_id": pay_id, "raw_name": name})

                    if pay_id.startswith('1'):
                        data["Allowances"][name] = amount
                    else:
                        data["Deductions"][name] = amount

            # === ARITHMETIC RECONCILIATION & CONFIDENCE SCORING ===
            sum_allowances = sum(data["Allowances"].values())
            sum_deductions = sum(data["Deductions"].values())

            # Verification 1: Stated Gross vs Sum(Allowances)
            # Sometimes allowances aren't fully listed or there are minor OCR issues
            if data["Gross Amount"] > 0 and abs(data["Gross Amount"] - sum_allowances) > 5:
                # If sum of allowances matches gross, we are good. If not, check if we missed some allowances
                # but let's not make it critical unless gross amount is 0
                data["Confidence_Reasons"].append("Allowance sum does not match printed gross.")
                data["Confidence_Score"] = "⚠️"

            # Verification 2: Stated Deductions vs Sum(Deductions)
            if abs(data["Stated_Total_Deduction"] - sum_deductions) > 5:
                data["Confidence_Reasons"].append(
                    f"Deduction Sum mismatch: Individual sum is ₹{sum_deductions}, stated total is ₹{data['Stated_Total_Deduction']}."
                )
                data["Confidence_Score"] = "⚠️"

            # Verification 3: Gross - Deductions == Net
            calculated_net = data["Gross Amount"] - sum_deductions
            if data["Gross Amount"] > 0 and net_found and abs(calculated_net - data["Net Amount"]) > 5:
                data["Confidence_Reasons"].append(
                    f"Net calculation mismatch: Gross (₹{data['Gross Amount']}) - Deductions (₹{sum_deductions}) = ₹{calculated_net}, but Net is ₹{data['Net Amount']}."
                )
                data["Confidence_Score"] = "❌"

            # Verification 4: Absolute checks for core values
            if data["Gross Amount"] == 0 or not net_found:
                data["Confidence_Score"] = "❌"
                data["Confidence_Reasons"].append("Gross is zero or net amount is missing.")

            # === ANOMALY DETECTION ===
            # Anomaly 1: Total deductions are suspiciously high (>90% of Gross)
            if data["Gross Amount"] > 0 and sum_deductions > 0:
                ded_pct = (sum_deductions / data["Gross Amount"]) * 100
                if ded_pct > 90 and "Arrear" not in data["Bill Name"]:
                    data["Confidence_Score"] = "❌"
                    data["Confidence_Reasons"].append(
                        f"ANOMALY: Total Deductions (₹{sum_deductions}) are {ded_pct:.1f}% of Gross Amount — unusually high."
                    )

            # Anomaly 2: Net Amount is negative
            if data["Net Amount"] < 0:
                data["Confidence_Score"] = "❌"
                data["Confidence_Reasons"].append(
                    f"ANOMALY: Net Amount is negative (₹{data['Net Amount']}). This is invalid."
                )

            # Anomaly 3: A single deduction head is disproportionately large (>80% of all deductions)
            if sum_deductions > 0:
                for ded_name, ded_val in data["Deductions"].items():
                    if ded_val > 0 and (ded_val / sum_deductions) > 0.80:
                        if data["Confidence_Score"] == "✅":
                            data["Confidence_Score"] = "⚠️"
                        data["Confidence_Reasons"].append(
                            f"ANOMALY: '{ded_name}' (₹{ded_val}) is {(ded_val/sum_deductions)*100:.1f}% of total deductions — please verify."
                        )

    except Exception as e:
        data["Confidence_Score"] = "❌"
        data["Confidence_Reasons"].append(f"Parser error: {str(e)}")

    return data
