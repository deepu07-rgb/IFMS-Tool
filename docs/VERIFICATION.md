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
