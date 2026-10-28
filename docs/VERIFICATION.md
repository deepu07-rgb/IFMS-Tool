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

## Mixed typed/handwritten statement — 26 October 2026

The actual app OCR endpoints initially returned0 GA55 candidates and0 structured statement rows. Damaged numeric55A form recognition now also requires financial-year and government/employee/GPF header evidence; rerunning the actual upload/OCR route finds27 GA55 candidates. The mixed handwritten/typed statement remains unsupported with0 usable structured rows. A manually source-region-aligned audit of26 positive Basic/DA/HRA cells for the claim months finds10 exact,1 wrong and15 missing. This is not an automatic OCR accuracy pass.

Source-reviewed statement/API comparison agrees with corrected monthly figures: Basic37800, DA22552, HRA2653, gross63005, additionalGPF256, conditionalcash62749. The review explicitly includes priorDA7416 (1854 each January-April) and HRA24720 (June6180/July18540), keeps HRA limited to the21June effective date, uses DA58% then60%, and separates effective pay dates from order issue dates. Whole-rupee HRA rounding was explicitly configured for source comparison. The employee's20000 subscription is unchanged; the previous sample's3000 subscription is not reused.

**The result remains conditional:** the user does not yet know the covered period of the prior82388 salary-arrear payment. The app preserves this as unallocated and blocks all3 component finalizations. A payment month is not evidence of non-overlap; other relevant unallocated prior credits also need covered dates. Comparisons and exported component packs are drafts, not approved payment bills.

A financial regression reproduced a partial statement/library HRA result13000 instead of213 for June21-30. Library due now stays monthly until shared-engine proration and rounding; actual period amounts are not prorated twice. Fresh review found2 further issues: library rounding changed actual drawn paise, and assigning overlapping prior dates alone bypassed credit handling. Both reproduced RED and fixed GREEN: monthly actual amounts retain paise and non-history overlap requires settlement IDs validated against saved paid allocations. History finalization still recalculates reviewed inputs. No Important review findings remain deferred.

Final active gate174 passed14 skipped; full suite175 passed14 skipped and13 inherited V1 expected-total failures in `tests/test_expected_totals.py`, fixtures1.pdf-13.pdf. Actual Chromium lifecycle passed payment review, historyDA/GPF, finalization, Excel/PDF, settlement, digitalGA55, workbook recalculation, custom allowance and full backup, with no external requests or JavaScript errors. Actual current-code statement API/export rerun gives63005/256/62749 and rejects all3 finalizations. No new runtime library or employee document was added to the repository/package. The previous portable artifact predates these source changes; a fresh successful Windows build is required for updated distribution.


## Extraction recovery — 27 October 2026

Added offline geometric printed OCR, bill continuation matching, identity/date confidence gates, recognizer disagreement detection, and gross/deduction/net reconciliation. HRA drafts use matched employee sanctions, dated rates, calendar days, complete salary records and validated prior credits. Unresolved financial evidence blocks generation.

The private strict sample recovered 9 bill records (8 complete), including all three relevant regular salary months. Its HRA sanction rate remains uncertain: the app creates no draft and requests one field review against the original row. No manual figures or approvals were entered. Earlier prototype outputs are superseded and are not evidence of an unattended pass.

A narrow rate confirmation flow preserves raw OCR, source hash, review reference and audit timestamp. Human-assisted drafts are labelled in the UI and exports. Synthetic endpoint tests cover review validation, unchanged evidence, source crop, audit and stale review rejection. Reconciliation also rejects unresolved positive prior HRA credits and bill-scoped blockers.

The full run before the final credit guard reported 257 passed, 14 skipped and 13 inherited failures in test_expected_totals.py. A fresh active regression run and final portable package verification are recorded in the completion update. Linux measurement does not establish the Windows installed size; CI must enforce the complete Windows budget.

Final active regression: 257 passed, 14 skipped (legacy expected_totals excluded). Focused recovery tests: 83 passed. Strict browser: zero claims, one blank review field, no numeric/date inputs, approvals, external requests or JavaScript errors. Linux portable payload: 454,854,338 bytes with neural models; system Tesseract, not complete Windows measurement.

Source pushed as `9842c36` on `feat/unified-ifms`. Reviewer reproduced the prior-credit defect, then confirmed its regression test and fix. Final frozen smoke passed. Windows build: https://github.com/deepu07-rgb/IFMS-Tool/actions/runs/40485278959 (completion pending at documentation time).

## Additional July increment samples — 27 October 2026

Fresh private workspaces tested two complete scanned PDFs through GA55 OCR, due-drawn OCR and the available source-driven workflow. No figures, dates or approvals were injected in the unassisted tests. Both remained blocked, with zero automatic claims and zero recognized statement rows. The separate reviewed-input increment checker matched independently checked source arithmetic after adding explicit no-HRA eligibility support. These results are not automatic OCR approvals.

Final extraction recovered seven records/five complete in one sample and nine records/three complete in the other. Missing monetary components, continuation identity and unsupported financial order pages remain blocking. No missing digits were reconstructed from expected totals. The private comparison report includes month/component arithmetic, deduction caveats, original failure, and before/after evidence.

Commands: `python -m pytest` — 262 passed, 14 skipped, 13 inherited `tests/test_expected_totals.py` failures; recovery/increment focused suite — 95 passed; `node --check ifms_suite/static/suite.js` and `git diff --check` passed. Independent code review found no important issues. No software build was run.

## Fiscal, money and continuation regressions — 27 October 2026

Fresh application API runs on two additional private PDFs used no numeric/date corrections or review approvals. Their original and final outputs, raw OCR, source-derived evidence, separate reviewed calculations and report are saved outside Git. The recorded final OCR replay exactly reproduced each API's bill and issue arrays. A previous saved-evidence case still returns nine records/eight complete, zero drafts and one rate-review request.

Regression tests were observed failing before the fixes for invalid fiscal periods, letter-containing money tokens, new-month continuation identity and silently omitted rows. Independent review then reproduced a cross-employee risk with split profile labels; both identity-inheritance and allowance-carry regressions now pass after the broader conservative header guard.

Final focused run: 100 passed. Full suite: 267 passed, 14 skipped, 13 inherited failures in `tests/test_expected_totals.py` (fixtures 1–13). The source image crops recovered invalid readings without expected-total arithmetic or digit replacement. Reviewed calculations also verified an unchanged signed recovery and a source/component discrepancy hidden by a matching net total. App PDF/Excel endpoints succeeded for the reviewed drafts. `git diff --check` passed. No software build was performed, and push-triggered packaging remains disabled.

## Workload-reduction implementation checkpoint — 27 October 2026

Approved repairs are in progress. Final full regression: `python -m pytest -q` → **346 passed, 14 skipped**, no failures (67.05 seconds). Focused financial/extraction/export check before the final missing-total regression:82 passed; final review/source/HRA check:50 passed. JavaScript syntax and `git diff --check` passed. Original legacy expected totals are unchanged and now pass after two source-backed geometry fixes. Updated obsolete tests that assumed the replaced column-OCR route or a clean parser working-tree diff.

Independent review found concurrent-import overwrite, absent deduction/net approval, and stranded reviews after extractor refresh. All reproduced with failing tests and fixed; active reviews are source/snapshot-bound, stale reviews archived, absent net totals cannot establish payment completeness, and conditional writes reject concurrent changes. Field-only review and dynamic statement columns are implemented; browser/operator workload acceptance remains outstanding.

An intermediate private replay of Kana/Nand/Nimba used six fresh databases with original PDFs and no corrected figures or approvals: source bills9/8/8, extractor-complete8/4/8, automatic claims0/0/0, handwritten statement rows0/0/0. Shared source facts matched between GA55 and HRA. Code changed during that development replay, so it is not frozen-version acceptance. It establishes no achieved workload reduction or production readiness. Private evidence remains outside Git.

Remaining work includes usable handling of the actual narrative/name-only orders, automatic multi-month combined preparation, deduction-head extraction, broader handwritten statement recognition and independent source comparison integration, full corpus/browser/time checks, and holdouts. The new explicit printed increment-table parser is unit-tested but not yet wired into complete automatic bill preparation. No bundle was built and packaging is still gated to later user-authorized manual dispatch.

## Consolidated bill workflow — 28 October 2026 (client date)

Final full regression: **433 passed, 14 skipped** (`python -m pytest -q`,67.61 seconds). JavaScript syntax and diff whitespace checks passed. No dependency/model installation or packaging was performed.

Connected the source case, order and bill review, monthly combined engine, saved draft list, PDF/Excel, additional deduction review and final approval. Independent review's six important financial/workflow issues were reproduced RED and fixed GREEN: unknown prior amounts, dependent HDA credits, duplicate reviewed order, partial monthly-basic basis, discarded coverage/allocations and overwritten HRA ineligibility. Tests also cover sequential decisions, stale source/rates/history, source substitution, overlapping approval, original evidence preservation and provisional blocked rows.

Actual Chromium synthetic-source workflow passed preparation across two months, all-head display, zero additional-deduction review, saved bill finalization and final PDF retrieval; no page errors. The finalized PDF contains the distinct finalized-after-review label. This is a browser integration check with synthetic source recognition, not an actual scanned-source accuracy pass.

A fresh private original scanned source was processed through real recognition in a new database. Unassisted preparation blocked on unreadable sanction evidence. After a comparison-page classification and an order review using entitlement terms already confirmed by the user, the app prepared the independently checked HRA gross with no monthly pay figures entered. PDF/Excel exports succeeded. Hashes of every suite Python module and browser JS were unchanged throughout that run. Additional deduction approval remains distinct from this gross calculation. This case demonstrates useful assisted orchestration, not unattended OCR success or the proposed 70% operator-time/80% routine-automation targets.

Reference-cell experiment: actual ruled handwritten source yields 26 columns, 17 physical rows,86 raw text-line candidates,13 high-confidence numeric candidates and zero trustworthy semantic monthly rows. Some high-confidence digits are wrong or truncated. The new integrated cell-reader always requires review, retains source polygons/hash/page and unknown headers, and cannot feed candidates into entitlement. Explicit mapping can label columns; malformed numeric tokens remain unresolved. Available reference candidates are compared by head rather than final difference alone, and any supplied reference requires source comparison review before approval. Universal handwritten extraction remains unsupported.

Private source PDFs, OCR outputs, employee details, exports and browser artefacts are outside Git under /workspace/review/complete-bill-2026-10-28. No new Windows size/runtime verification is claimed. User's bundling pause remains in force.

## Original-file module walkthrough — 28 October 2026

Tested two prior arrear PDFs through the full live app in an isolated workspace, recording unassisted and assisted runs separately. Both unassisted preparations remained blocked on order recognition. One HRA case produced the independently checked draft after two source reviews with no monthly pay typing. One increment case produced both independently checked monthly differences after three reviews, but correctly withheld net payable for unknown prior-credit coverage. All exported component values and consolidated totals matched API results. Handwritten reference comparison remained unread; it was not recorded as an automatic pass.

Original Inner Sheet: 60/60 employee gross/deduction/net values matched independent original-PDF parsing. Component checks exposed a shared-baseline column artefact that attached an orphan Salary token to SIP/GPF. A generic geometry fix was reproduced RED then GREEN; legitimate adjacent Advance Salary and signed amounts remain supported. Four stored test classifications were refreshed only by matching fresh source geometry/amounts, with backup and audit; no employee IDs, bill IDs or monetary values were changed. All tested SIP/GPF values now match fresh source parsing. Other source warnings remain visible.

Nine nonempty Inner filter combinations passed actual filtered PDF and Excel checks, including employee, search, gross/deduction/net ranges, basic, SIP and GPF. Empty selection returns404. The new filtered PDF uses the existing employee filter builder, includes all matched rows and component details, and passed a205-row multipage regression. It is a generated data report, separate from the original PDF.

Original Outer Sheet extraction and every exported component matched, including signed ROP. Original PDF download is byte-identical. Added shared Outer/GA55 search, employee, month and named-component amount filters, matching on-screen/export query results, Excel AutoFilter and filtered PDF review reports. Browser checked a negative-ROP Outer range and combined GA55 employee/month/HRA range; each returned one row and both downloads matched source amounts. Missing amounts are never coerced to zero.

Actual Chromium walkthrough captured18 real screenshots with no page errors. Embedded Inner->Schedules navigation initially failed on same-document hash changes; observed browser failure, fixed the hash-change handler and verified the full navigation. Sidebar titles/highlights and loaded/prepared status messages were corrected. Screenshot PDF and ZIP verified structurally (19PDF pages including18images, ZIP integrity passes). They and all source/employee evidence are private outside Git.

Final full suite on current sources: **442 passed,14 skipped** (59.77 seconds). JavaScript syntax and diff checks passed. No final software bundle was built. These checks establish the stated source/export/filter behaviours, not universal OCR accuracy or unattended payroll readiness.

## Ledger and editable OCR continuation — 28 October 2026

Frozen-source complete regression: **513 passed, 14 skipped**, zero failures,
59.12 seconds (`python -m pytest -q`, development environment). Both suite and
ledger JavaScript syntax checks and `git diff --check` passed. Independent review
of ledger/source conflicts, stale comparisons, source-margin correction isolation
and supplied-form prior-credit accounting reported no remaining important issues.

Tests cover actual reviewed storage reuse in a separate sanction import,
source-byte/version/review binding, classification/amount/coverage conflicts,
atomic bulk admission, optimistic correction updates, immutable raw OCR, missing
fields, source-only margin annotation isolation, supplied form columns/partial
dates, aggregate GPF adjustment and prior-credit conservation. Original-source
browser checks saved and reloaded a verified month, reused it for a matching HRA
draft, downloaded the supplied PDF/Excel, saved exactly one source cell correction,
and separately saved an unassigned margin annotation without changing financial
or raw machine rows. Browser checks reported no JavaScript errors. A genuine
unknown prior-payment covered period still blocks the other sample's net.

A browser-discovered hidden nested margin section was fixed and replayed
successfully. One intermediate full test process overlapped active renderer edits
and had three mixed-version failures; the final frozen run above supersedes that
non-frozen process. No failing checks are being treated as successful validation.

The original-source numeric diagnostic is **27/32 exact raw suggestions** on one
known handwritten page, including two unassigned margin readings. It has **zero
unambiguous automatic accepted fields** for this slice because blue and red ink
share physical cells. It does not establish whole-document, holdout, employee
identity/date accuracy or unattended financial accuracy. See OCR_ACCEPTANCE.md.

Bill exports use the supplied grid variants. The faint newer header wording is
not certified letter-for-letter, and the Latin PDF font does not support Hindi
names; Excel preserves Unicode. No new runtime dependency, model, cloud OCR,
Windows package, installed-size certification, deployment or final bundling was
performed. The user's further sample/manual acceptance gates remain in force.

## Two new original-source tests — 28 October 2026

Final code regression: **531 passed, 14 skipped**, zero failures, 71.50 seconds. Before
finalization, focused failing-then-passing regressions reproduced short-table and
crossing-crease detection, salary-slip parsing, source-crop reading conflicts,
non-accounting deduction effects, and printed-total comparison gaps. Both suite
and ledger JavaScript syntax checks and git diff checks passed. Independent
read-only review confirmed original/crop disagreements now remain visible and
reported no remaining important bounded-fix findings.

Actual original PDFs were processed through HTTP import, shared source OCR,
statement-grid OCR and source-case preparation in a fresh local workspace. Initial
results had zero usable salary bills for either source and no detected printed
reference table. After repairs, one July salary slip is complete with 12/12 checked
monetary fields matching independent source truth; August remains blocked for an
identity disagreement. The small degraded GA55 yields only unresolved raw source
candidates. A detected table or arithmetic equality is not counted as OCR success.

Scoped due/drawn benchmarks: handwritten raw 5/28 exact (17.86%), accepted 0/28;
printed raw 33/48 exact (68.75%), accepted 28/48. Printed wrapped totals lose a digit
and are incorrect despite high OCR confidence. Missing readings stay in the
denominator; human corrections, headings and blank grid cells do not inflate
accuracy. Original-source replay confirmed raw grid cells match benchmarked cells.
A separate reference diagnostic transcribed one month and mapped checked headings
but made zero monetary corrections; it exposed incomplete fields. Engine-only
reviewed entitlement verification, with original source blockers retained, computed
the expected HRA gross and flagged the printed-total OCR mismatch against verified
selected heads. This is not automatic complete-bill acceptance.

Both final unassisted bill-route attempts remain blocked with no payable export.
Actual browser source/grid checks showed the incorrect readings beside their
original crops, with no JavaScript errors. Payroll documents, screenshots,
per-field truth and reports remain private outside Git. Final bundling is paused;
no installed-size or production-readiness claim is made.

## Excel-first assisted workflow — 28 October 2026

- Full repository suite: **577 passed, 14 skipped**, 81.12 seconds; log `/tmp/ifms-excel-final-suite.log`.
- `tests/test_worksheet.py`: independent known arithmetic including partial dates, whole-month unaffected pay, prior credits, both supplied deduction layouts, negative recovery and missing/invalid values.
- `tests/test_worksheet_excel.py`: editable formula coordinates, literal text protection, safe round trip ignoring altered statement totals, formula-input rejection, structured salary template, header validation; actual LibreOffice recalculation for unused trailing rows.
- `tests/test_worksheet_routes.py`: saved revisions/audit, conflict protection, incomplete PDF block, independent workbook recomputation, full salary reconciliation, atomic duplicate rejection, linked source revalidation and rejection of partial-month actuals as full-month amounts. Malformed records cannot poison saved work.
- Actual LibreOffice matrix: 32 workbooks, 768 financial cells matching the Decimal calculator, two rounding policies, two presentation modes, four claim types and both form variants. Formula arithmetic is unchanged by the separately tested unused-row guard.
- Real full-app Chromium flow: salary workbook preview/confirmation/save; load linked employee month; HRA result4960; save/reload; formula Excel and supplied PDF downloads; workbook reimport; explicit detachment/paste; July5–31 result4320; unknown field visibly blocked. No JavaScript errors. Development script `scripts/verify_worksheet_browser.py` separately reproduces and verifies delayed save/calculation race handling.
- Human-assisted repeat of two old samples: gross4960 and2774 match prior independent audit. These tests start with human-entered source facts. They do not establish OCR accuracy, governing entitlement/HDA authority, absence of other payments or final cash approval.
- Blank formula/salary workbooks contain no employee data. All source cases, reports and screenshots remain outside Git in `/workspace/review/excel-arrear-maker-2026-10-28`.
- No new runtime packages/models and no release package produced. Installed Windows footprint has not been remeasured; final bundling remains paused for user acceptance.
