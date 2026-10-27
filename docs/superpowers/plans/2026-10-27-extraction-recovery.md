# Extraction Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Generate traceable HRA draft calculations from complete printed GA55 and sanction-order facts without operator number repair.
**Architecture:** A document-fact extraction layer preserves word boxes and source pages, joins continued bills, and matches an employee-specific dated order. The existing Decimal calculator generates drafts only when required evidence reconciles; recognition uncertainty remains blocked.
**Tech Stack:** Existing Python/Flask/PyMuPDF/Pillow/NumPy/Tesseract; evaluate optional compact ONNX printed OCR, no generative model.
**Spec:** docs/superpowers/specs/2026-10-27-extraction-recovery.md (user approved recovery design).

## Global Constraints
- Full Windows installation strictly below500000000bytes, models included.
- No employee PDFs or private expected values committed or packaged.
- No guessing missing monetary values or manufacturing digits from expected totals.
- Machine draft is distinct from human approval; uncertain facts block automatic calculation.

## Review Focus
- Continuation rows cannot be joined to another employee/bill.
- Order issue date must not replace employee-specific effective date.
- Missing HRA is zero only in a complete reconciled bill.
- Repeated statement totals must not become duplicate entitlements.
- Prior arrear coverage and already-paid salary must prevent duplicate claims.

### Task1: Document facts and complete bills
Files: new ifms_suite/document_facts.py, tests/test_document_facts.py.
Interface: extract_document_facts(pdf_bytes)->dict with bills, orders, evidence and issues.
- [x] Write failing tests for word geometry, signed monetary heads, employee identity and continuation isolation.
- [x] Implement recognition adapter and geometry-based bill/order extraction.
- [x] Run tests and actual frozen private samples; retain unresolved evidence.
- [x] Commit independently verified extraction change.

### Task2: Automatic HRA draft orchestration
Files: new ifms_suite/automatic_hra.py; web.py, templates/suite.html, static/suite.js; tests/test_automatic_hra.py.
Interface: reconcile_hra(facts,rates)->dict with draft calculations or explicit blockers; POST /api/imports/<id>/automatic_hra saves machine-draft snapshots and exposes existing PDF/Excel exports.
- [x] Write failing tests for partial eligibility, exact ID match, prior HRA credits, unresolved rows, and no duplicate draft creation.
- [x] Implement deterministic source matching and calendar calculations, UI action and source evidence.
- [x] Run private hands-off test without edited figures; compare independently afterward.
- [x] Commit only verified behavior and report remaining limitations.

### Task3: Regression, review and size gate
- [x] Run active/full tests and actual UI/API acceptance; disclose inherited failures.
- [x] Fresh independent review and fix blockers.
- [x] Measure/build frozen package including any added libraries/models; do not claim Windows size without a successful gate.
- [ ] Push source and preserve private frozen test evidence.

## Acceptance result
The strict private PDF run remains blocked by one uncertain HRA percentage. No figures, dates or review approvals were entered. This is a successful uncertainty safeguard, not an unattended bill accuracy pass. Windows packaging is independently gated by CI after push.
