"""Shared immutable-source extraction and review-compatible payment records."""

from copy import deepcopy
import hashlib
from .payment_types import classify_bill, entitlement_type


def source_facts(data, digest, payload, refresh=False):
    from importlib import import_module

    document_facts = import_module("ifms_suite.document_facts")

    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Original source changed; reimport it")
    # Statement-grid and document-facts engines have independent versions. Even
    # cached facts must discard comparisons from an obsolete source/grid before
    # case_facts can consume them, without waiting for the editor to reopen.
    from .statement_grid import GRID_EXTRACTION_VERSION

    stale_pages = {
        str(page)
        for page, grid in payload.get("statement_grids", {}).items()
        if grid.get("extraction_version") != GRID_EXTRACTION_VERSION
        or grid.get("source_sha256") != digest
    }
    if stale_pages:
        old_rows = {
            page: deepcopy(rows)
            for page, rows in payload.get("statement_reference_rows", {}).items()
            if str(page) in stale_pages
        }
        old_mappings = [
            deepcopy(review)
            for review in payload.get("statement_column_reviews", [])
            if str(review.get("page")) in stale_pages
        ]
        if old_rows or old_mappings:
            payload.setdefault("superseded_case_reviews", []).append(
                dict(
                    facts_version=payload.get("machine_facts_version"),
                    reason="statement_grid_changed",
                    pages=sorted(stale_pages),
                    reviews=dict(
                        statement_reference_rows=old_rows,
                        statement_column_reviews=old_mappings,
                    ),
                )
            )
            for page in old_rows:
                payload["statement_reference_rows"].pop(page)
            payload["statement_column_reviews"] = [
                review
                for review in payload.get("statement_column_reviews", [])
                if str(review.get("page")) not in stale_pages
            ]
    if (
        refresh
        or payload.get("machine_facts") is None
        or payload.get("machine_facts_version") != document_facts.FACTS_VERSION
    ):
        fresh = deepcopy(document_facts.extract_document_facts(data))
        fresh.setdefault("facts_version", document_facts.FACTS_VERSION)
        changed = (
            fresh != payload.get("machine_facts")
            or payload.get("machine_facts_version") != document_facts.FACTS_VERSION
        )
        if changed:
            if payload.get("bill_field_reviews"):
                payload.setdefault("superseded_bill_field_reviews", []).append(
                    {
                        "facts_version": payload.get("machine_facts_version"),
                        "reviews": deepcopy(payload["bill_field_reviews"]),
                    }
                )
                payload["bill_field_reviews"] = []
            archive = {
                key: deepcopy(payload[key])
                for key in (
                    "order_reviews",
                    "reference_page_reviews",
                    "source_bill_reviews",
                    "statement_reference_rows",
                    "statement_column_reviews",
                )
                if payload.get(key)
            }
            if archive:
                payload.setdefault("superseded_case_reviews", []).append(
                    dict(
                        facts_version=payload.get("machine_facts_version"),
                        reviews=archive,
                    )
                )
                for key in archive:
                    payload[key] = {} if key == "statement_reference_rows" else []
        payload["machine_facts"] = fresh
        payload["machine_facts_version"] = document_facts.FACTS_VERSION
    return deepcopy(payload["machine_facts"])


def payment_candidates(facts):
    records = []
    for bill in facts.get("bills", []):
        row = deepcopy(bill)
        row.setdefault("deductions", {})
        row.setdefault("allowances", {})
        row.setdefault("entitlement_period", None)
        row.setdefault("bill_type", "")
        row["payment_class"] = classify_bill(row["bill_type"])
        row["entitlement_type"] = entitlement_type(row)
        row["issues"] = [
            str(i.get("issue", i)) if isinstance(i, dict) else str(i)
            for i in row.get("issues", [])
        ]
        if not row.get("complete"):
            row["issues"].append(
                "Source bill remains incomplete; check highlighted evidence"
            )
        if not row["deductions"]:
            row["issues"].append(
                "Deduction heads have not been extracted; verify against printed deductions and net"
            )
        row["issues"].append(
            "Confirm source identity, dates, signs and component values before approving history"
        )
        row["raw_text"] = ""
        records.append(row)
    return dict(
        payments=records,
        extraction_status=(
            "candidates_require_review" if records else "unreadable_or_unsupported"
        ),
        calculation_ready=False,
        requires_review=True,
        layout="Shared geometric source evidence",
        notice="Source-backed candidates; resolve missing fields and deductions before approval.",
        issues=deepcopy(facts.get("issues", [])),
    )
