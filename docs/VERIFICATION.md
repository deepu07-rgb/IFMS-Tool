# Build verification

Source/browser checks on 26 October 2026:

- Active engine/workspace regression: `python -m pytest --ignore=tests/test_expected_totals.py -q` — 133 passed, 14 skipped, including the mixed scanned-page/digital-header OCR regression.
- Real Chromium acceptance passed employee/pay-history entry, reviewed drawn history, history-based DA/GPF claim, finalization, Excel export, actual settlement, digital GA55 identity and printed totals, uploaded workbook recalculation, fixed custom allowance and complete backup.
- Browser acceptance blocked external HTTP/HTTPS requests; no external requests or JavaScript errors occurred. Chromium's built-in PDF-viewer resources are local and allowed.
- Original supplied source regression fixtures are restored from the Inner archive for tests and are never included in the portable package.
- Thirteen retained V1 expected-deduction failures are isolated in `tests/test_expected_totals.py`; V2 and workspace have their own required gate. The inherited `parser.py` is byte-identical to the original archive (SHA256 `09b1c2b39ebd7ef98b24ce585568bc7e2dad65bb84a6fe8747bf4c1d16c35e4d`).

Packaging uses PyInstaller onedir. `packaging/build.py` totals all installed files including runtime, libraries, models, fonts and manifest, refuses 500,000,000 bytes or more, and rejects private databases, uploads, backups and original archives. `packaging/smoke.py` launches the actual executable in an empty data directory, checks HTTP/database/calculation/PDF/XLSX and performs English+Hindi raster OCR.

The Windows workflow is the release gate; a Linux size measurement does not establish the Windows footprint. Download artifacts only from a successful **Windows portable package** run and inspect `size-report.json`. See the ledger for the current build result. There is no automatic release, merge or IFMS submission.

Known functional boundaries: handwritten/unknown-layout OCR needs review; MACP/service eligibility is not inferred; arbitrary workbook formulas are not executed; generated reports do not replicate signatures or every source print setting. Original PDF and XLSX downloads preserve the source bytes.

Independent financial review found five issues and each was reproduced before correction. Added regressions cover February/leap-February/31-day slicing, paid January/February allocation conservation, explicit partial drawn review, unreadable employee identity, and validated leave-encashment revisions. Updated active suite: **143 passed, 14 skipped**. The full browser acceptance passed again after these fixes. The rebuilt Linux executable, including fonts/models/libraries, is **316,217,155 bytes**; real packaged English+Hindi OCR and PDF/Excel smoke checks passed. Linux uses a system OCR binary, so this is not Windows installed-size evidence.

Windows CI exposed a host-specific MIME problem in the retained employee Excel export: XLSX was served as `application/octet-stream` on a clean Windows image. A regression now simulates missing file associations, and retained audit/schedule/employee Excel responses declare their MIME type explicitly. The updated Linux active gate passes **144 tests, 14 skipped**; the complete run before that extra regression was **144 passed, 14 skipped, 13 inherited V1 failures**. Windows rerun #3 is the remaining platform gate.


## Windows result

The mandatory Windows build succeeded at source commit `a61ad43`:
https://github.com/deepu07-rgb/IFMS-Tool/actions/runs/40271821514

Download **IFMSWorkspace-Windows** under Artifacts (GitHub sign-in required). The artifact is approximately **153 MB compressed**, and contains `IFMSWorkspace-win32.zip` and `size-report.json`. Extract the inner ZIP, then run `IFMSWorkspace/IFMSWorkspace.exe`. The mandatory installed-size check includes Python, dependencies, bundled OCR executable/DLLs, English/Hindi models, PDF font/config and manifest; it rejects 500,000,000 bytes or more. Its successful result establishes the Windows size gate, rather than using compressed archive size as a proxy. The exact installed byte count is in the supplied report.

The same job ran the actual Windows executable in a fresh data directory and passed calculation, PDF/Excel, database and real English+Hindi raster OCR checks. All active regressions passed. The run also displays an expected error annotation from the deliberately separate, non-blocking inherited V1 test step; this is not a new workspace regression. No automatic merge or release was performed.

GitHub artifact digest: `sha256:42e14625ae2097bc961134c98ce075e35bd64d5bc5f3ef5378e1bc68026c82c3`.

Final Linux package: 316,217,299 bytes with system Tesseract; actual packaged smoke passed. Additional Chromium checks passed reviewed monthly allocation entry, mobile/desktop viewport containment, paid leave revision from ₹1,000 to ₹1,200 with ₹200 remaining, and offline loading of the retained inner/group interfaces.


## Increment and scanned-table iteration — 26 October 2026

Source `3dc5987` passed Windows build #7:
https://github.com/deepu07-rgb/IFMS-Tool/actions/runs/40368154281#artifacts

The mandatory Windows gates passed the active suite (including local Tesseract tests with its PATH configured), installed footprint strictly below 500,000,000 bytes, and actual frozen HTTP/calculation/increment/PDF/Excel/database/OCR smoke checks. Artifact **IFMSWorkspace-Windows** is 153 MB compressed; exact installed bytes are included in its size-report.json. Artifact digest: `sha256:7952f0c41382c373d09cd0f7ff44804a2d13d53a6c2dbe252ffab10aaf9e916a`.

Final Linux active gate: **162 passed, 14 skipped**. Full suite: **163 passed, 14 skipped, 13 inherited inactive V1 expected-total failures**. Latest Linux frozen package: 316,241,031 bytes; actual packaged smoke includes the reviewed increment result3093 and passed.

Independent review found two Important full-period rate-validation gaps. Both were reproduced and fixed; regressions cover bounded interior overrides and midmonth rates introduced after drafting. Additional tests cover approved increment-effective dates, export basis metadata, prior arrear blocking, absent drawn heads, configured-rate overrides and zero difference for already-updated August salary. Browser validation exercised the actual form, saved component drafts and PDF/Excel pack.

An anonymized source-reviewed July increment gives Basic1600+DA960+HRA320+HDA213=3093, agreeing with the handwritten reference. The app uses dated DA60%, Y-category HRA20% and the explicitly confirmed exact HDA fraction(Basic+DA)/12. The separate HDA policy order was not supplied; this is source-reconciled input, not a newly certified official rule.

OCR is still review-only. In the private increment scan, standard OCR parsed0 payment rows; column fallback now identifies9 candidate bills. A manually aligned audit of46 positive allowance cells found20 exact,5 incorrect and21 missing. Handwritten due-drawn parsing still yields0 usable rows. This establishes an extraction improvement and a correct reviewed-input calculation, **not an unattended OCR accuracy pass**. A secondary numeric-only experiment did not resolve all discrepancies and was not deployed.

Private comparison reports, OCR audit and employee documents are retained outside the repository. No customer scan was included in the application package or committed with this iteration.

## Partial-month pay-fixation sample — 26 October 2026

Source-reviewed financial comparison passed through the real claims API and PDF/Excel exports: January splits28 old-basic days and3 revised-basic days, with monthly whole-rupee rounding. Previously credited DA/HDA3060 is allocated explicitly to January-April; the remaining gross is30096 rather than33156. Gross agrees with the handwritten reference. The user confirmed retrospective GPF subscription3000 for February-May, making additional subscription3600 plus residual DA-revision GPF235, total3835 and cash26261. The handwritten subscription2850 would give3235 and26861 respectively; its net must change under the confirmed subscription. HDA remains an explicitly reviewed source-payroll fraction, not a newly certified policy order.

Actual upload/OCR endpoints now identify24 GA55 candidates instead of1 malformed first-pass row. Handwritten due-drawn extraction remains0 rows. A manually source-region-aligned audit of20 core Basic/DA/HRA/HDA cells across January-May finds8 exact,3 wrong,9 missing. Some dates also remain unreadable. **This is not an unattended OCR accuracy pass.** Source-reviewed inputs are still necessary.

Corrections: tolerate damaged GA55 form headers using multiple header signals; run column fallback when nonempty first-pass rows fail gross reconciliation; preserve reconciled first-pass pages and uncovered rows; retain first-pass output with a notice above the40-page column limit. Automatic DA-order GPF allocation now requires unchanged source-reviewed drawn basic; missing basic or pay fixation routes to separately reviewed allocation.

Final full suite:170 passed,14 skipped,13 inherited V1 failures in `tests/test_expected_totals.py` (fixtures1.pdf through13.pdf). Real Chromium acceptance passed history/DA/GPF, payment review, digital GA55, workbook recalculation, custom allowance, exports, settlement and complete backup, with no external requests or JavaScript errors. Independent review identified2 fallback regressions; both reproduced and fixed, with helper and route regressions for mixed-page coverage and41-page documents. No Important findings remain deferred. Private comparisons, source PDFs and employee records stay outside the repository. The prior Windows artifact predates these fixes; a fresh successful workflow is required before distributing the updated executable.
