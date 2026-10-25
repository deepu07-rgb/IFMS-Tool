# Unified IFMS Implementation Plan
> For agentic workers: use superpowers:executing-plans task by task.
**Goal:** combine existing analyzers with auditable arrear preparation.
**Architecture:** retain inner Flask APIs, add a suite blueprint using the same database and dedicated history tables, migrate outer parser and group operations into the shared workflow.
**Tech Stack:** Flask, SQLite, Decimal, PyMuPDF, openpyxl, ReportLab, local Tesseract.
**Spec:** ../specs/2026-10-26-unified-ifms-design.md
## Global Constraints
Windows first; installed footprint below 500 MB; offline operation; no fabricated official rates; source originals retained; user approval already covers implementation. Use this existing isolated cloud checkout.
## Review Focus
Negative adjustments; missing drawn values; ambiguous identity; duplicate settlements; February and mid-month effective changes.
### Task 1: extraction baseline
Files: outer_engine/parser.py; tests/test_suite.py; retained app.py and ifms_engine.
- [ ] Write regression for signed money, ROP and non-1xx/2xx deduction heads; run RED.
- [ ] Correct signed extraction and gross reconciliation; run GREEN.
### Task 2: deterministic engine
Files: ifms_suite/calculation.py; tests/test_arrears.py.
Interface: calculate_claim(start,end,segments) -> rows/totals; segments have inclusive start/end, basic, due_rate, drawn_rate, prior_settlement and proration.
- [ ] Tests: three months; 19/31 partial month; leap year; rate boundary; missing drawn; overlap; signed recovery; settlement.
- [ ] Run RED, implement Decimal arithmetic and validated segments, run GREEN.
### Task 3: integrated persistent workspace
Files: ifms_suite/web.py, storage.py, templates/suite.html, static/suite.js; app.py.
Interfaces: /suite/api/employees, rates, claims, imports; shared app.config DATABASE; source records separate from reviewed records.
- [ ] Test real Flask/SQLite workflows for conflicting identity, rate intervals, persisted claims, finalization blockers and duplicate imports.
- [ ] Implement sidebar and source review; retain original UI under /analyzer and group tool under /groups.
- [ ] Run workflow tests and actual HTTP readiness.
### Task 4: documents and export
Files: ifms_suite/documents.py, exports.py; tests/test_documents.py.
- [ ] Tests for GA55 continuation/type handling, source links, import review, PDF/XLSX numerical parity and backup inclusion.
- [ ] Implement text-first PDF extraction, local OCR fallback, structured review; export reviewed snapshots.
- [ ] Validate supplied PDFs and workbook cases. No auto-confirmation of uncertain OCR.
### Task 5: reproducibility and packaging
Files: start_tool.bat, README.md, packaging/; tests.
- [ ] Windows launcher, dependency locking and size budget; official rate research with sources.
- [ ] Run retained suite; diagnose failures, review branch and document exact limitations.
