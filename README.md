# IFMS Workspace — development build

Combines the retained Inner Sheet Analyzer with an initial shared workspace for employee records, outer-sheet imports, GA55 candidate extraction and due–drawn calculations. Original uploaded tools remain in the repository as reference archives.

**This is an implementation in progress, not an approved payroll release.** See [progress](docs/PROGRESS.md) and the approved design/plan under `docs/superpowers/`.

## Start

Python 3.12 recommended. Windows: run `start_workspace.bat`. Linux/macOS with Python installed: `./start_tool.sh`. Initial setup downloads pinned dependencies; later starts reuse the local virtual environment. The browser opens the workspace. `IFMS_OPEN_BROWSER=0` suppresses opening a browser; `IFMS_PORT` selects the port. The launcher binds to loopback only.

The existing `start_tool.bat` remains the original analyzer launcher; use `start_workspace.bat` for the combined workspace. The compatibility analyzer and all original V2/V3 APIs are retained. The group HTML currently remains a compatibility tool; shared group reconciliation and its UI are under development. Its current spreadsheet library still requires separate offline bundling.

## Current verified scope

- Signed outer-sheet components and valid zero-cash arrear handling.
- Percentage-of-basic calculations with explicit due/drawn rates and calendar-day proration, inclusive dates, pay/rate segments and one explicit prior settlement per segment.
- HALF_UP rounding at two decimals, separately for due/drawn. Other prescribed government rounding and proration policies are pending verification.
- Saved claim snapshots and export from those same snapshots, with draft/final labels, review references and duplicate finalization checks.
- Digital GA55 candidate extraction, retained original PDF and source text, review APIs and local Tesseract OCR adapter. OCR and handwriting output always require review.
- Shared SQLite tables coexist with retained analyzer tables. Source PDFs live in `uploads/suite/`.

## Not complete

Automatic application of verified Rajasthan rates; custom allowance formula/eligibility engine; complete employee pay timeline and group migration; guided GA55 review UI; drawn-payment/settlement allocation; deductions and cash/GPF allocation; batch claims; official-form PDF/Excel fidelity; measured Windows installer below 500 MB. No official IFMS submission or digital signing is performed.

## Checks

Install development dependencies then run `python -m pytest`. Private regression PDFs are in the original Inner archive under `test_fixtures/`; they are deliberately excluded from extracted source commits. See `docs/PROGRESS.md` for inherited V1 test failures. New suite regression files are `test_signed_outer.py`, `test_arrears.py`, `test_suite_workflow.py`, `test_import_review.py`, and `test_ga55.py`.

Do not use this development build to authorize payments. Review extracted figures and rules against source documents.
