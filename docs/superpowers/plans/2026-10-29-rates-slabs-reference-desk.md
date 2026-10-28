# Rates, Slabs and Reference Desk Implementation Plan

> **For agentic workers:** Use focused parallel independent tasks and TDD; integrate and review the whole change.

**Goal:** Check assisted bill rates, maintain dated rates/slabs and keep searchable orders visible while preparing a bill.
**Architecture:** Reuse suite_rates; add separate audited slab and document repositories. Server worksheet validation consults current rates. Vanilla JS exposes editable libraries and floating reference windows without new runtime libraries.
**Tech Stack:** Existing Flask, SQLite, Decimal, PyMuPDF, stdlib DOCX ZIP/XML, openpyxl and vanilla JavaScript.
**Spec:** docs/superpowers/specs/2026-10-29-rates-slabs-reference-desk-design.md

## Global Constraints
- Offline/local; no new production dependencies/models; installed Windows ceiling500,000,000 bytes; final bundling paused.
- No invented future DA rate or GPF/SI schedules. Private source PDFs, generated bills and screenshots stay outside Git.
- Preserve supplied statement grid, source/raw OCR and deduction semantics.

## Review Focus
- Dated rate changes inside a row, exemptions, expired rates and stale exports must not silently pass.
- Archived seeded rates must not return after restart; restore/conflicting revisions must preserve history.
- Salary slab amounts are full-subscription references, never automatically extra arrear deductions.
- Uploaded DOCX/PDF content is untrusted data; bounded extraction, escaping and original hashes apply.
- Floating panels must survive navigation and stay reachable after a small-screen resize without losing bill entries.

### Task 1: Important-document repository
Files: new ifms_suite/document_library.py and tests/test_document_library.py. Interfaces initialize_library(db), register_document_library(suite); /api/library/categories and /api/library/documents list/create/get/update/archive/content. Metadata and contracts in spec; return id/revision/archive state, safe extracted_text and SHA-backed original. TDD category, PDF/DOCX/typed search, edit conflict, archive/restore, unsafe upload and source integrity. Owner independent; shared storage/web wiring by coordinator.
- [x] Observe failing tests, implement, verify targeted tests.

### Task 2: Effective salary slab repository
Files: new ifms_suite/slab_library.py and tests/test_slab_library.py. Interfaces initialize_slabs(db), register_slabs(suite), suggest_slab(db,scheme,on,basic=None,da=None,gross=None,category=''). /api/slabs GET/POST, /<id> POST revision edit, /<id>/archive POST revision/reason/archived, /suggest GET. Schema: name,scheme,basis,category,effective_from,effective_to,reference,rounding,slabs[{lower,upper,kind:'fixed'|'percent',value}]. Return full_subscription_reference_only=true. TDD boundaries, dates, overlap, stale edits and archive.
- [x] Observe failing tests, implement, verify targeted tests.

### Task 3: Rates and worksheet validation
Files: new ifms_suite/rate_library.py; existing web.py/reference.py/storage.py/worksheet_routes.py/worksheet.py/worksheet_excel.py; tests/test_rate_library.py and worksheet tests. Preserve existing rate POST contract; add archive/restore and audited edit. worksheet_rate_checks(db,payload)->{errors,warnings,checks}; row errors match existing highlighting. Add backward-compatible category and per-row exemption/override fields; do not trust Excel cached outputs.
- [x] Reproduce wrong DA acceptance, add failing date/override/archive tests.
- [x] Implement validation, source-aware messages, dated suggestions and current-data export rechecks.
- [x] Run targeted tests and schema round trips.

### Task 4: Libraries and reference-window UI
Files: new static/reference_desk.js, templates/reference_desk.html, static/reference_desk.css; modify suite.html/suite.js/worksheet.js. Rates editable/reversible; slab form and independent calculator; searchable document categories/upload/text/edit. Drag or click to pin, move/resize/persist up to6 panels and quick-search from any module. Integrate suggestions/warnings into Excel maker.
- [x] Actual browser absence/incorrect-rate baseline, then implement.
- [x] Verify create/save/edit/remove/restore, document search/pin, navigational persistence, resize and preserved bill inputs.

### Task 5: Sample bill and completion evidence
- [x] Use earlier source-reviewed full bill and partial case, explicitly separate human assistance and authority assumptions.
- [x] Generate supplied-format PDF/Excel, test incorrect DA plus corrected/new effective rate and GPF/SI slab references without adding deductions twice.
- [x] Run full suite, independent review, fix Important regressions with RED->GREEN, save screenshots/report and docs, push existing feature branch without bundling.

Pre-flight: document and slab repositories share only coordinator storage/web registration; separate owned files. Rates/worksheet contracts feed UI; changing rate library must be checked at every worksheet read/export. No unresolved interface conflict.

Completion evidence:665passed14skipped; private full-app browser/sample/exports report retained outside Git. Independent review Important findings fixed with RED->GREEN tests; no deferrals. Source cases remain explicitly human-assisted and conditional; bundling paused.
