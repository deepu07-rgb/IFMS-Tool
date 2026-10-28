# Excel-first assisted due–drawn maker

The user approved the four-part assisted workflow and specifically requested an easy Excel sheet with prebuilt formulas. This approval authorizes implementation now; final bundling remains paused.

## Design

Build on the existing Flask app, Decimal arithmetic, SQLite employee payment ledger, openpyxl and supplied Jodhpur forms. Add an Excel Arrear Maker sidebar module. A person can enter monthly figures directly, paste spreadsheet rows, load verified ledger months, or upload the provided workbook. OCR remains optional editable transcription beside an original PDF; it is never a prerequisite or entitlement authority.

Keep drawn pay, sanctioned changes, allocated previous payments and additional deductions separate. Support HRA, DA, basic-pay revision and explicit monthly due amounts. Require references for salary, entitlement, prior-payment review (including none) and deduction review (including none). Never infer a rate or the absence of earlier payment. Calendar-day inclusive proration and rupee/paise rounding are explicit. One effective segment per calendar month; unsupported multiple segments must be combined into reviewed monthly amounts. Allow either claim-period presentation or whole-month presentation with the unaffected days retained. Preserve signed recovery differences.

Provide a macro-free workbook with Setup, Monthly inputs, Due drawn statement and Guide. Blue input cells, validated dates/rates, visible missing-field checks and prebuilt formulas update the user's supplied 27-column grid. The statement formulas and server calculator must agree, including partial dates, prior credits and extra deductions. References and review status remain visible in the workbook. Missing values remain blank, not zero. The app recalculates from literal input values when a workbook returns; imported formulas/cached statement totals are never trusted. User text must remain literal Excel text.

Provide a separate structured salary-ledger Excel template and preview/import workflow. It includes all selected salary heads, other allowances, total deductions and printed gross/net, requiring reconciliation and explicit review before atomic admission into the existing payment ledger. Duplicate regular salaries block admission. Saved ledger links are revalidated before worksheet reuse/export. A worksheet's corrections are saved as revisions with previous values; no change overwrites raw OCR.

Save incomplete worksheet drafts, render field-level errors, and permit formula-workbook download while incomplete. PDF export requires complete referenced/reviewed inputs and uses the existing supplied-form renderer. Both supplied right-hand deduction variants are supported; already-deducted GPF/SIF columns in the newer variant are disclosures, not additional deductions. All outputs remain drafts for office verification/signature, not an automatic payment approval.

## Alternatives and constraints

An OCR-led extension would retain the existing extraction bottleneck. A standalone spreadsheet alone would lose reusable ledger records and correction history. Integrate the spreadsheet and app instead. No new production libraries/models; offline/local processing, Windows installed-size ceiling 500,000,000 bytes, no release packaging. Private samples and screenshots stay outside Git. Do not claim improved handwriting accuracy or statutory rate certification.

## Acceptance

Synthetic tests independently verify full/partial months, two deduction layouts, credits, missing/invalid inputs, negative differences, formula-injection defense, workbook round trip, duplicate/atomic ledger admission, saved revisions and stale ledger links. Exercise the real browser workflow and recalculate exported spreadsheets with the available development LibreOffice, which is not a runtime dependency. Recheck two private sample computations using explicitly human-entered facts, reporting this as assisted calculation, not OCR success. Run the full repository suite and retain a downloadable blank formula template and screenshots for review.
