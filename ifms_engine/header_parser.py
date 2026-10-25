import re
from typing import List, Dict, Any


class HeaderParser:
    @staticmethod
    def _to_amount(token: str):
        token = (token or "").replace(",", "").strip()
        if not token:
            return None
        if re.match(r"^-?\d+(?:\.\d+)?$", token):
            try:
                return float(token)
            except ValueError:
                return None
        return None

    @staticmethod
    def _group_lines(words: List[Dict[str, Any]], y_tol: float = 3.0) -> List[str]:
        if not words:
            return []
        sw = sorted(words, key=lambda w: (w.get("page_no", 0), w.get("y0", 0), w.get("x0", 0)))
        lines = []
        current = [sw[0]]
        current_page = sw[0].get("page_no", 0)
        current_y = sw[0].get("y0", 0)
        for w in sw[1:]:
            wp = w.get("page_no", 0)
            wy = w.get("y0", 0)
            if wp != current_page or abs(wy - current_y) > y_tol:
                lines.append(" ".join(x.get("text", "") for x in sorted(current, key=lambda z: z.get("x0", 0))).strip())
                current = [w]
                current_page = wp
                current_y = wy
            else:
                current.append(w)
        if current:
            lines.append(" ".join(x.get("text", "") for x in sorted(current, key=lambda z: z.get("x0", 0))).strip())
        return [ln for ln in lines if ln]

    @staticmethod
    def _extract_value(pattern: str, text: str, flags: int = re.I):
        m = re.search(pattern, text, flags)
        if not m:
            return "", ""
        if m.lastindex:
            return m.group(1).strip(), m.group(0).strip()
        return m.group(0).strip(), m.group(0).strip()

    @staticmethod
    def extract_metadata(words: List[Dict[str, Any]]) -> Dict[str, Any]:
        meta = {
            "group_name": "",
            "reference_no": "",
            "month_year": "",
            "office_id": "",
            "ddo_name": "",
            "ddo_code": "",
            "bill_no": "",
            "bill_date": "",
            "demand_no": "",
            "object_head": "",
            "budget_head": "",
            "budget_head_full": "",
            "sf_amount": 0.0,
            "ca_amount": 0.0,
            "na_amount": 0.0,
            "tan_no": "",
            "print_date_time": "",
            "page_count": 0,
            "official_gross": 0.0,
            "official_deduction": 0.0,
            "official_net": 0.0,
            "raw_matches": {},
        }
        if not words:
            return meta

        pages = [w.get("page_no", 0) for w in words if w.get("page_no")]
        if pages:
            meta["page_count"] = max(pages)

        p1 = [w for w in words if w.get("page_no") == 1]
        p1_text = " ".join(w.get("text", "") for w in sorted(p1, key=lambda w: (w.get("y0", 0), w.get("x0", 0))))
        p1_lines = HeaderParser._group_lines(p1)
        p1_full = "\n".join(p1_lines)

        for key, pat in [
            ("reference_no", r"Reference\s*No[:\s]*([A-Za-z0-9/-]+)"),
            ("month_year", r"Month/Year[:\s]*([A-Za-z]+\s*/\s*\d{4})"),
            ("office_id", r"Office\s*ID[:\s]*([A-Za-z0-9/-]+)"),
            ("ddo_code", r"DDO\s*Code[:\s]*([A-Za-z0-9/-]+)"),
            ("bill_no", r"Bill\s*No[:\s]*([A-Za-z0-9/-]+)"),
            ("bill_date", r"Bill\s*Date[:\s]*([0-3]?\d/[01]?\d/\d{4})"),
            ("demand_no", r"Demand\s*No[:\s]*([A-Za-z0-9/-]+)"),
            ("object_head", r"Object\s*Head[:\s]*([A-Za-z0-9/-]+)"),
            ("budget_head", r"Budget\s*Head[:\s]*([0-9\-./A-Za-z]+(?:/SF/Voted|/Voted|/Charged)?)"),
            ("tan_no", r"TAN\s*No[:\s]*([A-Za-z0-9]+)"),
        ]:
            val, raw = HeaderParser._extract_value(pat, p1_full)
            if val:
                meta[key] = val
                meta["raw_matches"][key] = raw

        if meta["budget_head"]:
            meta["budget_head_full"] = meta["budget_head"]

        for key, pat in [
            ("sf_amount", r"SF[:\s]*([0-9]+(?:\.[0-9]+)?)"),
            ("ca_amount", r"CA[:\s]*([0-9]+(?:\.[0-9]+)?)"),
            ("na_amount", r"NA[:\s]*([0-9]+(?:\.[0-9]+)?)"),
        ]:
            val, raw = HeaderParser._extract_value(pat, p1_full)
            if val:
                try:
                    meta[key] = float(val)
                except ValueError:
                    meta[key] = 0.0
                meta["raw_matches"][key] = raw

        ddo_value = ""
        for i, line in enumerate(p1_lines):
            if re.search(r"Name\s+of\s+DDO[:\s]*", line, re.I):
                trailing = re.sub(r".*Name\s+of\s+DDO[:\s]*", "", line, flags=re.I).strip()
                if trailing and not re.search(r"\bDDO\s*Code\b", trailing, re.I):
                    ddo_value = trailing
                elif i + 1 < len(p1_lines):
                    nxt = p1_lines[i + 1]
                    if not re.search(r"^\s*(Bill|Budget|Demand|Object|Reference|Month/Year)\b", nxt, re.I):
                        ddo_value = nxt.strip()
                if ddo_value:
                    break
        if ddo_value:
            meta["ddo_name"] = ddo_value
            meta["raw_matches"]["ddo_name"] = ddo_value
        elif meta["ddo_code"]:
            # Fallback: value row often contains DDO name to the left of DDO code.
            code_word = None
            for w in p1:
                if w.get("text", "").strip() == meta["ddo_code"]:
                    code_word = w
                    break
            if code_word:
                same_row = [
                    w.get("text", "").strip()
                    for w in p1
                    if abs(w.get("y0", 0) - code_word.get("y0", 0)) < 2.5
                    and 80 <= w.get("x0", 0) < code_word.get("x0", 0)
                ]
                same_row = [t for t in same_row if t and t.lower() not in {"name", "of", "ddo:"}]
                if same_row:
                    ddo_value = " ".join(same_row).strip()
                    ddo_value = re.sub(r"\bDDO\s*Code:?\s*$", "", ddo_value, flags=re.I).strip()
                    meta["ddo_name"] = ddo_value
                    meta["raw_matches"]["ddo_name"] = ddo_value

        footer_words = [w for w in p1 if w.get("y0", 0) > 540]
        footer_text = "\n".join(HeaderParser._group_lines(footer_words))

        gval, graw = HeaderParser._extract_value(r"Group\s*Name[:\s]*([^\n]+)", footer_text)
        if gval:
            gval = re.split(r"\b(?:Print|Forward)\s+Date\b", gval, flags=re.I)[0].strip(" -")
            meta["group_name"] = gval
            meta["raw_matches"]["group_name"] = graw

        pt_val, pt_raw = HeaderParser._extract_value(
            r"Print\s*Date\s*&\s*Time[:\s]*([0-3]?\d/[01]?\d/\d{4}\s+[0-2]?\d:[0-5]\d\s*(?:AM|PM)?)",
            footer_text,
        )
        if pt_val:
            meta["print_date_time"] = pt_val
            meta["raw_matches"]["print_date_time"] = pt_raw

        if meta["page_count"] == 0:
            pc_val, pc_raw = HeaderParser._extract_value(r"Page\s+\d+\s+of\s+(\d+)", p1_text)
            if pc_val:
                try:
                    meta["page_count"] = int(pc_val)
                    meta["raw_matches"]["page_count"] = pc_raw
                except ValueError:
                    pass

        # Bill-level official totals from final summary area.
        # Guard against employee-row contamination by requiring a single line that contains:
        # Gross Amount + Deduction Amount + Net Amount labels together.
        all_lines = HeaderParser._group_lines(words)
        summary_line = ""
        for ln in reversed(all_lines):
            low = ln.lower()
            if "gross" in low and "deduction" in low and "net" in low and "amount" in low:
                summary_line = ln
                break
        if summary_line:
            gm = re.search(r"Gross\s+Amount[:\s]+([0-9,]+(?:\.[0-9]+)?)", summary_line, re.I)
            dm = re.search(r"Deduction\s+Amount[:\s]+([0-9,]+(?:\.[0-9]+)?)", summary_line, re.I)
            nm = re.search(r"Net\s+Amount[:\s]+([0-9,]+(?:\.[0-9]+)?)", summary_line, re.I)
            if gm:
                v = HeaderParser._to_amount(gm.group(1))
                if v is not None:
                    meta["official_gross"] = v
                    meta["raw_matches"]["official_gross"] = gm.group(0).strip()
            if dm:
                v = HeaderParser._to_amount(dm.group(1))
                if v is not None:
                    meta["official_deduction"] = v
                    meta["raw_matches"]["official_deduction"] = dm.group(0).strip()
            if nm:
                v = HeaderParser._to_amount(nm.group(1))
                if v is not None:
                    meta["official_net"] = v
                    meta["raw_matches"]["official_net"] = nm.group(0).strip()
            if gm or dm or nm:
                meta["raw_matches"]["official_totals_line"] = summary_line

        return meta
