# Excel-first Arrear Maker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Let a clerk prepare the supplied due–drawn form from Excel or a verified ledger without depending on OCR.
**Architecture:** A pure worksheet calculator shares validated input with a formula workbook. Flask routes persist audited drafts and import reconciled salaries into existing suite_payments; the UI separates drawn pay, entitlement and adjustments.
**Tech Stack:** Existing Python/Flask, Decimal, SQLite, openpyxl, ReportLab, vanilla JavaScript.
**Spec:** docs/superpowers/specs/2026-10-28-excel-arrear-maker-design.md

## Global Constraints

- No new production libraries/models; offline/local processing, Windows installed-size ceiling 500,000,000 bytes, no release packaging.
- Private samples and screenshots stay outside Git.
- Missing financial values are not zero; no inferred rate or prior-payment coverage.
- Use the two existing supplied Jodhpur forms; outputs remain draft.

## Review Focus

- Partial month inclusive dates and whole-month unaffected-day rounding must agree in app and spreadsheet.
- Previous payments already included in drawn must not be entered again; explicit head/month allocation is required.
- Blank values, input formulas, external workbook links, malformed data and user text beginning '=' must not become accepted amounts or executable formulas.
- Concurrent draft edits and changed saved-ledger records must not silently overwrite or export stale figures.
- GPF/SIF already-deducted disclosure columns must not be summed again into net deductions.

### Task 1: Validated assisted calculation
**Files:** Create ifms_suite/worksheet.py; tests/test_worksheet.py.
**Interfaces:** calculate_worksheet(payload: dict) -> dict containing status, errors, bill and metadata; validate row dates/heads/references. Outputs feed both exporters/routes.
- [x] Write failing synthetic tests for HRA 4960, partial 27/31 HRA 4320, whole-month revised basic, prior credit, both deduction variants, missing values, negative difference and unsupported dates/duplicate months.
- [x] Run targeted tests; confirm failures are missing implementation.
- [x] Implement literal-input Decimal calculations with calendar proration and explicit reviews; expose cell-level provenance in result.
- [x] Run targeted tests and commit.

### Task 2: Formula workbook and structured ledger import
**Files:** Create ifms_suite/worksheet_excel.py; tests/test_worksheet_excel.py.
**Interfaces:** export_workbook(payload: dict) -> BytesIO; import_workbook(stream) -> dict; salary_template() -> BytesIO; read_salaries(stream) -> list[dict].
- [x] Write failing tests for formula cells in supplied-grid coordinates, missing-input guards, literal text, round trip and refusing formula inputs/external links.
- [x] Implement Setup/Monthly inputs/Guide plus formula-driven supplied form and a reconciled salary template.
- [x] Recalculate both presentation modes, rounding policies and deduction variants with development LibreOffice; compare with independent engine results.
- [x] Run targeted tests and commit.

### Task 3: Saved drafts, ledger reuse and HTTP contracts
**Files:** Create ifms_suite/worksheet_routes.py; modify storage.py and web.py; tests/test_worksheet_routes.py.
**Interfaces:** /api/worksheets CRUD with revision checks; /template, /preview-import, /calculate, /<id>/excel|pdf; /salary-template, /salary-preview, /salary-save; /ledger-load validates source snapshots.
- [x] Write failing route tests for persistence, stale revisions, incomplete PDF rejection, tampered statement formulas, atomic ledger duplicates/reconciliation, edited saved salary detection and save/reload/export.
- [x] Implement audited draft storage and source-link revalidation without changing OCR facts or automatic bill approval.
- [x] Run targeted tests and commit.

### Task 4: Spreadsheet-style app workflow and verification
**Files:** Create static/worksheet.js; modify templates/suite.html and static/suite.js; document usage in docs/EXCEL_ARREAR_MAKER.md.
**Interfaces:** Sidebar Excel Arrear Maker loads monthly tables, workbook import/export, saved drafts, ledger load/import, source PDF and preview errors/results.
- [x] Exercise initial missing module controls with browser before implementation; record unavailable flow.
- [x] Add dates-to-month generation, safe clipboard paste, fill-down entitlement values, explicit review-none actions, editable cells, original PDF viewing and inline errors.
- [x] Browser-test create/import/edit/reload/Excel/PDF, including keyboard entry and a partial month; retain screenshots and a blank downloadable template outside Git.
- [x] Verify two old samples as human-assisted calculations, explicitly preserving unresolved deductions/prior-payment questions.
- [x] Run full pytest suite and independent code review; address important findings with failing regression tests, update progress/verification docs and commit.

Pre-flight: Task 1 -> 2: shared payload/calculation schema; workbook uses literal payload and reproduces its arithmetic. Task 1/2 -> 3: routes recalculate imports instead of trusting workbook formula results. Task 3 -> 4: UI sends the same schema and revision token. No interface conflict identified.

Completion: native implementation at 2e8a1b3, bd5d90d, 42e5981, 06675d9 plus final review fixes. Full suite577passed14skipped; independent review completed, three Important defects reproduced and fixed, no Important deferrals. Private sample computations are human-assisted only.
