"""Exact independent-truth OCR scoring; confidence and human edits are not accuracy.

Truth records: field_id, text, category (digits/date/identity/other), medium
(printed/mixed/handwritten). Predictions: field_id, text, origin (machine/human).
Do not derive truth from predictions, reviewed overlays, target totals or model output.
"""

_MEDIUMS = ("printed", "mixed", "handwritten")
_CATEGORIES = ("digits", "date", "identity", "other")


def _distance(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        following = [i]
        for j, b in enumerate(right, 1):
            following.append(min(following[-1] + 1, row[j] + 1, row[j - 1] + (a != b)))
        row = following
    return row[-1]


def _metrics(truth, predictions):
    exact = missing = edits = characters = 0
    for field in truth:
        expected = field["text"]
        observed = predictions.get(field["field_id"])
        absent = observed is None or (observed == "" and expected != "")
        missing += absent
        exact += not absent and expected == observed
        characters += len(expected)
        edits += _distance(expected, observed or "")
    count = len(truth)
    return dict(
        fields_expected=count,
        fields_exact=exact,
        missing_fields=missing,
        field_accuracy=exact / count if count else None,
        reference_characters=characters,
        character_edits=edits,
        character_error_rate=edits / characters if characters else None,
        character_accuracy=max(0, 1 - edits / characters) if characters else None,
    )


def score_ocr(truth, predictions):
    """Score literal raw machine text, with explicit missing/excluded counts.

    Exact means Unicode text equality, without whitespace, punctuation, currency,
    date or identity normalization. Character accuracy is max(0, 1 - CER).
    Empty strata return None for rates rather than claiming 100% accuracy.
    """
    truth = list(truth)
    identifiers = set()
    for field in truth:
        if (
            not isinstance(field, dict)
            or not isinstance(field.get("field_id"), str)
            or not field["field_id"]
            or field["field_id"] in identifiers
            or not isinstance(field.get("text"), str)
            or field.get("medium") not in _MEDIUMS
            or field.get("category") not in _CATEGORIES
        ):
            raise ValueError(
                "Truth requires unique field IDs, literal text, medium and category"
            )
        identifiers.add(field["field_id"])
    machine, ignored = {}, 0
    for field in predictions:
        if not isinstance(field, dict) or field.get("origin") not in (
            "human",
            "machine",
        ):
            raise ValueError("Prediction origin must explicitly be machine or human")
        if field["origin"] == "human":
            ignored += 1
            continue
        identifier, value = field.get("field_id"), field.get("text")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in machine
            or (value is not None and not isinstance(value, str))
        ):
            raise ValueError(
                "Machine predictions require unique field IDs and literal text"
            )
        machine[identifier] = value
    return dict(
        overall=_metrics(truth, machine),
        by_medium={
            medium: _metrics([t for t in truth if t["medium"] == medium], machine)
            for medium in _MEDIUMS
        },
        by_category={
            category: _metrics([t for t in truth if t["category"] == category], machine)
            for category in _CATEGORIES
        },
        by_medium_and_category={
            medium: {
                category: _metrics(
                    [
                        t
                        for t in truth
                        if t["medium"] == medium and t["category"] == category
                    ],
                    machine,
                )
                for category in _CATEGORIES
            }
            for medium in _MEDIUMS
        },
        ignored_human_predictions=ignored,
        unexpected_machine_fields=sorted(set(machine) - identifiers),
        method="exact_literal_fields_and_levenshtein_characters",
    )
