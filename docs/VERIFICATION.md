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
