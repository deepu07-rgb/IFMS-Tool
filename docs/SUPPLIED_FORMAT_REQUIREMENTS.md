# Supplied due/drawn statement requirements

The required output is the user's supplied wide, monochrome printed grid. A generic component listing or consolidated audit report is not a substitute. The clean form must never use scanned employee handwriting, signatures, amounts, or stamps as its background.

## Source comparison

Both inspected first-page samples share an office heading, employee name and ID, followed by these columns:

1. Month and year; bill number and date; treasury voucher number and date.
2. PAY TO BE DRAWN: Basic Pay, DA, HRA, HDA, CCA, Total.
3. PAY ALREADY DRAWN: the same six columns.
4. PAY DIFFERENCE DRAWN: the same six columns.
5. Four deduction/credit columns, total deduction, and net amount.

The totals row uses these same columns. Blank ruled space remains below it for accounts, forwarding, and drawing/disbursing signatures. Do not reproduce actual signatures or imply that a clean signature block is signed.

The samples differ in the right-hand columns. Explicit supported template IDs are:

| ID | Right-hand columns before total deduction and net |
| --- | --- |
| `jodhpur_classic` | GPF, SI, CM Corona, I Tax |
| `jodhpur_gpf_arrear` | GPF arrear to be deducted, GPF arrear already deducted, SIF arrear already deducted, I Tax |

**Source readability limit:** the newer sample's tiny deduction headings contain faint further wording/year text. The second template captures the legible meanings and column positions; its wording is not certified as a letter-for-letter transcription. The original scan is skewed and photographed, so clean output is a vector grid reconstruction, not a pixel-exact facsimile. A clearer blank master is needed to certify the faint wording and absolute print dimensions. Do not claim exact original-format acceptance without that visual comparison.

## Export contract

`ifms_suite.supplied_form` exposes `export_supplied_pdf(bill, metadata)` and `export_supplied_excel(bill, metadata)`, returning a `BytesIO` positioned at zero. Set `metadata['supplied_template_id']` explicitly to one supported ID. The route/UI must catch validation errors and show the blocking reason; it must never silently fall back to another bill layout.

Metadata accepts `employee_name`, `employee_code`, and optional `supplied_form_rows` keyed by `YYYY-MM`. Each month may carry `bill_no`, `bill_date`, `tv_no`, `tv_date`, `deductions`, and `total_deductions`. Source bill/treasury details are carried automatically from unambiguous row/evidence fields where available. Missing details stay blank; conflicting evidence is not guessed. Reviewed metadata may override them.

Classic deduction keys are `GPF`, `SI`, `CM_CORONA`, `I_TAX`. Newer keys are `GPF_TO_DEDUCT`, `GPF_ALREADY_DEDUCTED`, `SIF_ALREADY_DEDUCTED`, `I_TAX`. Newer GPF credit columns are informational and must not be summed automatically as current deductions. The reviewed monthly `total_deductions` must reconcile with the engine's aggregate deduction total. Nonzero deductions need explicit monthly mapping or an unambiguous engine-calculated aggregate adjustment. Exact normalized names GPF, SI, I Tax, Income Tax, and their adjustment forms are supported in the classic form; CM Corona is also supported. The newer form supports current GPF adjustment in its first GPF column and income tax, while SI adjustments have no matching current-deduction column and block output. When an engine deduction is aggregate-only, monthly deduction and net cells remain blank and only the final TOTAL row contains the adjustment and net. No monthly allocation is invented. Source salary deductions are not automatically deducted again from arrears.

Only printed salary heads are included in the due/drawn totals. Unchanged unprinted heads can be omitted because they do not affect arrears; an unprinted head with a change blocks output. Verified, explicitly allocated prior arrear settlements on printed heads are included in PAY ALREADY DRAWN together with the actual salary drawn. Each original component must satisfy due minus actual drawn minus prior settlement equals remaining difference. Negative or unresolved credits block output. Credits on unprinted heads also block output even if the remaining difference is zero; they cannot be omitted. The engine data is never modified. If an aggregate prior-settlement total is present, it must reconcile with the per-head allocations.

Whenever prior settlements are included, both outputs disclose outside the grid: "Pay already drawn includes verified prior arrear settlements". Available bill numbers, pay months, references and document IDs from `bill.evidence` entries with `kind=prior_credit` are included below that disclosure. A displayed drawn total therefore includes prior settlement amounts; difference and net remain the engine amounts. Missing allocation is never invented. Unresolved amounts, non-ready bills, unknown templates, inconsistent monthly differences, or aggregate net/deduction discrepancies block output. Draft or finalized review status prints below the grid, never as a substitute heading.

PDF uses a clean landscape A3 vector grid and repeats the supplied form for continuation pages, with at most eight months per page to preserve signature space. Continuation pages show a displayed-month SUBTOTAL; the final page shows the whole-bill TOTAL. Excel is one editable sheet with matching merged headings, numeric amounts, print area and landscape settings. Excel strings are literal, including strings beginning with `=`. Signature areas remain blank apart from role labels.

PDF currently uses the built-in Latin font. Names or references containing unsupported characters block PDF output rather than being replaced with boxes. The editable Excel form preserves Unicode text. A portable, correctly shaped Devanagari font is required before Hindi PDF output can be claimed supported.

## Acceptance and privacy

Use synthetic employees and amounts in committed tests. Keep real source scans and rendered private comparisons outside the repository. Verify merged salary group order, right-hand variant, selected-head arithmetic, populated source references, editable Excel values, and printable signature space. OCR field coverage and editable review controls belong to the ingestion/review workflow; generating this form alone does not establish the required 80% measured OCR coverage.

Partial claim spans print their start and end dates inside the existing month/year cell, preserving the supplied column layout.
