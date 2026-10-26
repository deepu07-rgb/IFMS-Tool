# IFMS Workspace

A local, offline workspace combining the existing Inner Sheet Analyzer, Outer Sheet Analyzer and Group Management tool with reviewed GA55 extraction and deterministic arrear preparation. The left sidebar provides access to each module. Original supplied tools and archives are retained.

## Start

A verified Windows package is available from [successful build #3](https://github.com/deepu07-rgb/IFMS-Tool/actions/runs/40271821514#artifacts), at source commit `a61ad43`. The approximately153 MB compressed artifact passed the installed-size limit and real packaged OCR checks. The Windows portable package is produced by the **Windows portable package** GitHub Actions workflow on `feat/unified-ifms`. Download its `IFMSWorkspace-Windows` artifact, unzip the package and run `IFMSWorkspace.exe`. The package includes Python, libraries, English/Hindi OCR models and the OCR executable; Python installation is unnecessary. The build rejects an installed package of 500,000,000 bytes or more. Check the accompanying `size-report.json` and successful packaged smoke-test step before distributing a build.

For source development, Python 3.12 is recommended. Run `start_workspace.bat` on Windows or `./start_tool.sh` on Linux/macOS. The first source setup downloads pinned dependencies. Source OCR requires a local Tesseract executable. The original `start_tool.bat` still opens the compatibility analyzer. `IFMS_OPEN_BROWSER=0` suppresses browser launch; `IFMS_PORT` changes the port; `IFMS_DATA_DIR` selects the data directory. The server binds only to loopback.

Portable Windows data is stored under `%LOCALAPPDATA%\IFMSWorkspace`, separate from the executable. Source runs use the repository directory by default. Only one launcher may use a data directory at a time. Close the console to stop the application. Keep regular backups using **Reports & Backup**.

## Workflow

1. Import employee spreadsheets through Group Management, or stage profiles already extracted by the Inner Sheet Analyzer. Review identity conflicts explicitly. Save dated basic-pay events and their order references.
2. Import inner/outer sheets or GA55 PDFs. Digital text is read first; scanned pages can use local English/Hindi OCR. Review each employee, bill category, component, informational deduction and printed total before approving payment history. Original files remain available.
3. Select DA, HRA or a saved custom allowance such as HDA/CCA. History mode splits months at dated pay/rate changes and uses reviewed actual drawn payments. Missing months, ambiguous bills and unallocated previous arrears block calculation. Manual periods and reviewed uploaded statements are also supported.
4. Review inclusive dates, partial months, calendar/30-day proration, rounding, deductions and any cash/GPF allocation. Finalize using rate/source references. Later record an actual full settlement so a future rate revision can deduct it once.
5. Export saved due–drawn snapshots as PDF/Excel, or download a batch pack with individual statements and a consolidated workbook. Download original PDF forms unchanged; workbook PDF exports are clearly labelled review reports. Complete backups include the shared database and original PDF/XLSX documents; restoration is queued until an exclusive restart and creates a pre-restore backup.

See [the user guide](docs/USER_GUIDE.md), [verification record](docs/VERIFICATION.md) and [implementation ledger](docs/PROGRESS.md).

## Calculation and rate coverage

Supported bases are percentage of basic, basic plus DA, selected pay components, fixed monthly and daily allowances. Dates are inclusive; calculations use Decimal with explicit paise/whole-rupee and segment/month rounding. Actual paid period amounts are never prorated twice. Due and drawn remain separate, including negative adjustments and prior settlements.

The bundled Rajasthan DA history covers January 2017–January 2026, and HRA changes cover October 2017, July 2021 and November 2024. Public Finance Department orders, order dates, cash dates and checksums are retained under `reference_orders/`. The DA freeze and superseding 2021 order are represented. Future or locally applicable rates can be entered with a reason and audit history; manual entries are labelled accordingly. Order-backed deferred DA allocation requires an explicit applicable pension scheme.

## Limits that require human judgment

OCR cannot guarantee accurate handwriting, digits or document layouts. All candidates require source review. Uploaded due–drawn recognition supports the supplied Basic/DA/HRA table structure; unknown layouts use manual entry. Excel imports read cached values and do not execute workbook formulas. MACP eligibility, service entitlement and leave-encashment quantities need an approved source or manual periods; the app does not decide them. Generated reports do not inherit source signatures or submit bills to IFMS.

The retained V1 parser has thirteen known deduction-total regression failures on the original private fixtures. Its source remains unchanged; the active V2 engine and new workspace are tested separately. See the verification record before relying on a build.

## Development checks

Install `requirements.lock`, restore private `test_fixtures/` from the supplied Inner Analyzer archive, then run `python -m pytest`. The Windows workflow records the inherited V1 failures separately and gates all other tests. Optional browser acceptance: start an empty development data directory on port 5059, then run `python scripts/verify_suite_browser.py` with Playwright and Chromium installed. Browser tools and tests are excluded from the portable runtime. Build instructions are in `packaging/build.py`; `packaging/smoke.py` runs the actual packaged executable, exercises calculations/exports and performs raster OCR.
