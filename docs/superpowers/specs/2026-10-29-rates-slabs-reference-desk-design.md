# Dated rates, salary slabs and a persistent reference desk

The user authorizes implementation and manual-style testing with previously supplied samples. Extend the existing Excel-first assisted maker, keeping final bundling paused. No new production dependencies/models; offline/local processing; installed Windows ceiling remains500,000,000 bytes. No assumed future DA increase or invented GPF/SI schedule.

## Shared behavior

Use the existing suite_rates and audit trail for DA/HRA/custom allowances, including Uniform allowance. Expose calculation basis, effective/order/end dates, category, edit, archive and restore. Archive removes a rate from active calculations but preserves its record/audit; archived bundled rates must not reappear on restart. Reject malformed/negative rates. Keep earlier dates when a new future date is added.

Add worksheet warnings and dated comparisons. A known conflicting DA/HRA entry blocks PDF until corrected or a specific manual-exception reason is recorded. Missing library coverage/category produces a visible warning, never a false validation pass. Check the entire selected date range; a rate change inside a row requires explicit reviewed manual/blended amounts. HRA exemption needs its own reference when a zero rate intentionally differs. Recheck saved worksheets on reload/export after library edits. Default compatibility: existing explicit manually reviewed inputs still calculate if no matching library rate exists, with a warning. The library is local office reference data, not automatic legal certification.

Add user-authored GPF/GPF-2004/GPF-SAB/SI salary slabs with effective dates, categories, basis (basic/basic+DA/gross), fixed or percentage values, lower-inclusive/upper-exclusive bounds, reference and rounding. Validate finite numbers, nonoverlap, dates, revision conflicts and archive/restore. Suggestions select the latest effective applicable schedule, reject ambiguity/gaps and clearly identify full subscription suggestions, not additional arrear deductions. No real schedule is seeded without authority.

## Important Documents and reference panels

Create user categories such as Travelling Allowance Rules. Store original PDF/DOCX or typed rules, title, category, order number/date, effective dates, tags, notes and searchable local text. PDF selectable text and DOCX paragraphs/tables are searchable; scans without text remain metadata-searchable with an explicit limitation. Upload only PDF/DOCX (10MB/file), bounded local ZIP/XML parsing, no external content retrieval. Preserve originals by SHA256 under UPLOAD_FOLDER/suite/library so existing full upload backups include them. Archive/restore rather than erase evidence, and audit edits/revisions.

Users can search/filter, read/download, edit metadata/text, archive/restore and pin documents or slab tables. Floating panels persist across module navigation, are draggable/resizable and clamped to screen bounds; keyboard pin controls and a global reference search avoid mandatory dragging or tab switching. Multiple panels (up to6) may remain visible together. Persist only IDs/geometry in browser storage. PDF displays original; DOCX displays safe extracted text and offers original download, not pixel-identical Word layout.

## Alternatives and verification

Do not duplicate the rate store or embed rules into screenshots. Reuse rates; separate salary slab authority from deduction arithmetic; local file/text storage plus floating views meets the task without a heavy document editor. Extend existing Excel schema backward-compatibly for category/exception metadata. Standalone Excel arithmetic remains formula-driven; live-library validation happens in app and is identified in the export notes.

Prove known bill arithmetic using reviewed source data, wrong DA warning/block/correction, future DA save and dated selection, override audit, archive/restart/restore, slab boundaries and no double deduction, category/upload/search/edit/pin/navigation/mobile sizing. Exercise actual browser and PDF/Excel, retain private sample bills/screenshots outside Git, run full tests and independent review. Report usability observations honestly; do not claim a measured clerical time reduction or improved OCR accuracy without evidence.
