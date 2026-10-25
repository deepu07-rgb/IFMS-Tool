import re
import unicodedata


_LONG_NUMBER_RE = re.compile(r"\b\d{7,}\b")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+")
_MOJIBAKE_TOKEN_RE = re.compile(r"\S*(?:à|¤|¥|�)\S*")
_EMPTY_BRACKETS_RE = re.compile(r"\(\s*\)|\[\s*\]|\{\s*\}")


def _strip_empty_brackets(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _EMPTY_BRACKETS_RE.sub(" ", text)
    return text


def extract_english_designation(raw_designation_full) -> str:
    """Return the audit-safe English designation text used for matching/display."""
    text = unicodedata.normalize("NFKC", str(raw_designation_full or ""))
    text = text.replace("–", "-").replace("—", "-")
    text = _LONG_NUMBER_RE.sub(" ", text)
    text = _DEVANAGARI_RE.sub(" ", text)
    text = re.sub(r"[-/]\s*(?=\S*(?:à|¤|¥|�))", " ", text)
    text = _MOJIBAKE_TOKEN_RE.sub(" ", text)
    text = re.sub(r"[^A-Za-z0-9,\-/&().\s]", " ", text)
    text = re.sub(r"\s*[-/]\s*(?=\s*[)\]}])", " ", text)
    text = re.sub(r"[-/,\s]+(?=[)\]}])", "", text)
    text = re.sub(r"[(]\s*[-,/&.]+\s*[)]", " ", text)
    previous = None
    while previous != text:
        previous = text
        text = _EMPTY_BRACKETS_RE.sub(" ", text)
        text = re.sub(r"\s*[-/]\s*(?=\s*[)\]}])", "", text)
        text = re.sub(r"[-/,\s]+(?=[)\]}])", "", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+", " ", text).strip(" -/,")
    previous = None
    while previous != text:
        previous = text
        text = _EMPTY_BRACKETS_RE.sub(" ", text).strip(" -/,")
    text = re.sub(r"\s+", " ", text).strip()
    duplicate = re.fullmatch(r"(.+?)\s*\(\s*\1\s*\)", text, flags=re.I)
    if duplicate:
        text = duplicate.group(1).strip()
    duplicate_prefix = re.fullmatch(r"(.+?)\s*\(\s*\1[-\s]*\)", text, flags=re.I)
    if duplicate_prefix:
        text = duplicate_prefix.group(1).strip()
    return text


def extract_hindi_designation(raw_designation_full) -> str:
    """Return Hindi/Devanagari display text only; never use this for matching."""
    text = unicodedata.normalize("NFKC", str(raw_designation_full or ""))
    text = text.replace("–", "-").replace("—", "-")
    text = _LONG_NUMBER_RE.sub(" ", text)
    devanagari = re.findall(r"[\u0900-\u097F]+(?:\s+[\u0900-\u097F]+)*", text)
    mojibake_tokens = [
        token.strip("()[]{}-/, ")
        for token in _MOJIBAKE_TOKEN_RE.findall(text)
        if token.strip("()[]{}-/, ")
    ]
    cleaned = " ".join(devanagari + mojibake_tokens)
    cleaned = _LONG_NUMBER_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[(){}\[\],;:/\\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_designation_parts(raw_designation_full) -> dict:
    """Split raw PDF designation into audit, English match, Hindi display, and combined display values."""
    raw_full = str(raw_designation_full or "")
    raw_en = extract_english_designation(raw_full)
    raw_hi = extract_hindi_designation(raw_full)
    combined = raw_en
    if raw_en and raw_hi:
        combined = f"{raw_en} / {raw_hi}"
    elif raw_hi:
        combined = raw_hi
    return {
        "raw_designation_full": raw_full,
        "raw_designation_en": raw_en,
        "raw_designation_hi": raw_hi,
        "raw_designation_key": clean_designation_key(raw_en),
        "raw_designation_display_combined": combined,
    }


def clean_designation_key(text) -> str:
    english = extract_english_designation(text).upper()
    english = re.sub(r"[^A-Z0-9]+", " ", english)
    return " ".join(english.split())


class DictionaryManager:
    DESIGNATION_CANONICAL = {
        "CONSTABLE": "Constable",
        "HEAD CONSTABLE": "Head Constable",
        "ASSISTANT SUB-INSPECTOR": "Assistant Sub-Inspector",
        "SUB-INSPECTOR": "Sub-Inspector",
        "INSPECTOR": "Inspector",
        "CLASS IV": "Class IV",
        "UNMAPPED": "Unmapped",
    }
    DEFAULT_DESIGNATIONS = {
        "हैड कांसटेबल": "HEAD CONSTABLE",
        "हैड कानसटेबल": "HEAD CONSTABLE",
        "कानसटेबल": "CONSTABLE",
        "कांसटेबल": "CONSTABLE",
        "सहायक": "ASSISTANT SUB-INSPECTOR",
        "निरीक्षक": "INSPECTOR",
        "चतुर्थ": "CLASS IV",
        "उप": "SUB-INSPECTOR"
    }
    
    DEFAULT_COMPONENTS = {
        "Basic": "basic_pay",
        "DA": "da",
        "HRA": "hra",
        "CCA": "cca",
        "HDA": "hda",
        "Mess All": "mess_allowance",
        "Mess": "mess_allowance",
        "Wash Allo.": "fta",
        "FTA": "fta",
        "LIC": "lic",
        "GPF": "gpf",
        "GPF 2004": "gpf_2004",
        "RGHS": "rghs",
        "SIP": "sip",
        "SIL": "sil",
        "ITax": "income_tax",
        "Income Tax": "income_tax",
        "ROAD WAYS": "roadways_deduction",
        "ROAD": "roadways_deduction",
        "PPSS JDR": "ppss_jdr",
        "Advance Salary": "advance_salary",
        "Advance": "advance_salary",
        "Car Rent": "car_rent",
        "HFRH": "hfrh",
        "EACPenF": "eacpenf",
        "GIAIS": "giais",
        "AIS GPF": "ais_gpf",
        "SII": "sii",
        "Per Ded 1": "per_ded_1",
        "Per Ded 2": "per_ded_2",
        "KMA Allowance": "kma_allowance",
        "MTA": "mta",
        "Special Pay": "special_pay",
        "Wash Allowance": "wash_allowance",
        "ROP": "rop",
    }

    UNSAFE_DESIGNATION_PHRASES = [
        "IPS",
        "RPS",
        "JUNIOR SCALE",
        "SENIOR SCALE",
        "SENIOR TIME SCALE",
        "SELECTION SCALE",
        "SUPER TIME SCALE",
        "INSPECTOR GENERAL OF POLICE",
        "DEPUTY POLICE COMMISSIONER",
        "ASSISTANT COMMISSIONER OF POLICE",
    ]

    SYSTEM_DESIGNATION_PATTERNS = [
        (re.compile(r"\bASSISTANT\s+SUB[-\s]?INSPECTOR\b|\bASI\b", re.I), "Assistant Sub-Inspector"),
        (re.compile(r"\bHEAD\s+CONSTABLE\b|\bHC\b", re.I), "Head Constable"),
        (re.compile(r"\bSUB[-\s]?INSPECTOR\b|\bSI\b", re.I), "Sub-Inspector"),
        (re.compile(r"\bCONSTABLE\b|\bFC\b|\bPC\b", re.I), "Constable"),
        (re.compile(r"\bINSPECTOR\b", re.I), "Inspector"),
        (re.compile(r"\bPEON\b|\bCLASS\s+IV\b", re.I), "Class IV"),
    ]

    @staticmethod
    def _clean_designation(raw_desig: str) -> str:
        return extract_english_designation(raw_desig)

    @staticmethod
    def is_unsafe_designation(raw_desig: str) -> bool:
        key = clean_designation_key(raw_desig)
        return any(clean_designation_key(phrase) in key for phrase in DictionaryManager.UNSAFE_DESIGNATION_PHRASES)

    @staticmethod
    def resolve_system_designation(raw_desig: str):
        clean = DictionaryManager._clean_designation(raw_desig)
        if DictionaryManager.is_unsafe_designation(raw_desig):
            return None
        if clean:
            key = clean_designation_key(clean)
            for pattern, final_en in DictionaryManager.SYSTEM_DESIGNATION_PATTERNS:
                match = pattern.search(clean)
                if not match:
                    continue
                if final_en == "Inspector" and "INSPECTOR GENERAL OF POLICE" in key:
                    continue
                if final_en == "Sub-Inspector" and "DEPUTY POLICE COMMISSIONER" in key:
                    continue
                if final_en == "Assistant Sub-Inspector" and "ASSISTANT COMMISSIONER OF POLICE" in key:
                    continue
                return {
                    "final_en": final_en,
                    "final_hi": "",
                    "source": "system_high_confidence",
                    "confidence": 0.92,
                    "needs_review": False,
                }
        legacy_raw = " ".join(str(raw_desig or "").split())
        for hindi, english in DictionaryManager.DEFAULT_DESIGNATIONS.items():
            if hindi in legacy_raw:
                canonical = DictionaryManager.DESIGNATION_CANONICAL.get(english.upper(), english.title())
                return {
                    "final_en": canonical,
                    "final_hi": "",
                    "source": "system_high_confidence",
                    "confidence": 0.92,
                    "needs_review": False,
                }
        return None

    @staticmethod
    def normalize_designation(raw_desig: str) -> str:
        resolved = DictionaryManager.resolve_system_designation(raw_desig)
        return resolved["final_en"] if resolved else DictionaryManager.DESIGNATION_CANONICAL["UNMAPPED"]

    @staticmethod
    def normalize_head(raw_head: str) -> str:
        clean = (raw_head or "").strip()
        compact = " ".join(clean.replace(".", " ").replace("/", " ").split())
        upper = compact.upper()
        # Direct lookup
        if clean in DictionaryManager.DEFAULT_COMPONENTS:
            return DictionaryManager.DEFAULT_COMPONENTS[clean]
        if compact in DictionaryManager.DEFAULT_COMPONENTS:
            return DictionaryManager.DEFAULT_COMPONENTS[compact]

        # Common broken labels
        if upper.startswith("BASIC"):
            return "basic_pay"
        if upper == "DA":
            return "da"
        if upper.startswith("HRA"):
            return "hra"
        if upper.startswith("CCA"):
            return "cca"
        if upper.startswith("HDA"):
            return "hda"
        if "MESS" in upper or "KMAA" in upper or "KMAALL" in upper:
            return "mess_allowance"
        if "WASH" in upper or "FTA" in upper:
            return "fta"
        if upper.startswith("LIC"):
            return "lic"
        if "GPF 2004" in upper:
            return "gpf_2004"
        if upper.startswith("GPF"):
            return "gpf"
        if upper.startswith("RGHS"):
            return "rghs"
        if upper.startswith("SIP"):
            return "sip"
        if upper.startswith("SIL"):
            return "sil"
        if "ITAX" in upper or "INCOME TAX" in upper:
            return "income_tax"
        if upper == "ROAD" or ("ROAD" in upper and ("DEDUT" in upper or "DEDUCT" in upper or "WAYS" in upper)):
            return "roadways_deduction"
        if "PPSS" in upper:
            return "ppss_jdr"
        if "ADVANCE" in upper:
            return "advance_salary"
        if "CAR" in upper and "RENT" in upper:
            return "car_rent"
        if upper.startswith("HFRH"):
            return "hfrh"
        if "EACPENF" in upper:
            return "eacpenf"
        if "GIAIS" in upper:
            return "giais"
        if "AIS" in upper and "GPF" in upper:
            return "ais_gpf"
        if upper.startswith("SII"):
            return "sii"
        if "PER" in upper and "DED" in upper and "1" in upper:
            return "per_ded_1"
        if "PER" in upper and "DED" in upper and "2" in upper:
            return "per_ded_2"
        if "KMA" in upper:
            return "kma_allowance"
        if upper.startswith("MTA"):
            return "mta"
        if "SPECIAL" in upper and "PAY" in upper:
            return "special_pay"
        if "ROP" in upper.replace("-", " ").split():
            return "rop"

        return compact.lower().replace(" ", "_")
