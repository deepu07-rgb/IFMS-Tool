"""Payment purpose is separate from the allowance components it contains."""


def classify_bill(value):
    text = " ".join(str(value or "").lower().split())
    if "arrear" in text or text.upper() in ("DA", "HRA", "HDA", "CCA"):
        return "allowance_arrear"
    if "surrender" in text or "encashment" in text:
        return "leave_encashment"
    if "bonus" in text:
        return "bonus"
    if "regular" in text and "salary" in text:
        return "regular_salary"
    return "other"


def payment_class(payment):
    return payment.get("payment_class") or classify_bill(payment.get("bill_type"))


def entitlement_type(payment):
    if payment.get("entitlement_type"):
        return payment["entitlement_type"]
    if payment_class(payment) == "leave_encashment" or any(
        s in str(payment.get("bill_type", "")).lower()
        for s in ("surrender", "encashment")
    ):
        return "leave_encashment"
    return "salary"
