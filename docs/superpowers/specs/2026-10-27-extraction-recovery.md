# Extraction recovery proposal — 27 October 2026

Status: proposed architecture, not implemented. The tested app remains source4ba1a11. No sample-derived values or corrections were supplied to its test run.

## What this test established

The complete four-page PDF was sent unchanged through each existing import/OCR route in separate empty databases, using the UI default English+Hindi. No pages were split, payment figures entered, employee selected, review approved, or claim constructed by the operator. The actual Flask routes returned9 GA55 candidates,0 structured due-drawn rows,0 employees and0 claims. All9 candidate employee IDs are blank;5 payment months are blank. Only1 allowance subtotal reconciles to its printed gross; that is the surrender bill, not the target July salary bill. HTTP200 means processing completed, not financial correctness.

This is a failure of unattended bill preparation. The earlier sample results established calculation correctness with reviewed inputs; they did not establish automatic extraction correctness.

## Concrete causes

1. The fixed-column fallback deliberately emits blank identities and always sets calculation_ready=false. Successful OCR cannot become a machine-generated draft under the current orchestration.
2. Page-relative crops and month anchors do not establish table cells or complete bill records. July's HDA continues onto the next page; the July candidate retains only page2 and loses that continuation. Its DA is14830 rather than source14880, and basic is missing.
3. Sanction-order rows are not parsed into structured employee-specific effective dates/rates. The maker cannot automatically use this employee's5July effective date from the3August order.
4. The statement parser expects a limited digital table with particular labels/three allowance heads. This form has different labels/four heads and handwritten numbers, plus a detail and repeated total row. Raw OCR text is not a usable statement record.
5. Header patches and correct Decimal arithmetic cannot supply these missing document facts. More manually corrected sample totals would mask the same failure.

## Reference check, isolated from the app

Independent visual audit reads July basic24800, HRA20%, effective5July2026, through31July2026. MonthlyHRA4960 x27 inclusive days/31 =4320; JulyGA55 has no HRA in its fully reconstructed allowance record; AugustHRA4960 is already drawn. The handwritten statement also shows4320. This is an auditor's reference, never an app-generated result in this test.

## Approaches considered

| Approach | Advantage | Limit |
|---|---|---|
| Rebuild layout extraction/orchestration around existing Tesseract | Smallest dependency change; Hindi support retained | Existing scans still show monetary recognition errors; preprocessing alone must earn an accuracy pass |
| Same document/fact pipeline with compact independent ONNX printed-text recognition | Independent recognition candidates for critical typed cells, while retaining Tesseract for Hindi | Adds models/runtime and requires actual benchmark and frozen-build size verification; does not establish handwriting accuracy |

Recommendation: rebuild the document/fact pipeline, evaluate both recognition approaches on the same frozen benchmark, and keep the smallest one that passes. Do not add another page-header special case as the primary remedy. A second OCR engine without correct table segmentation and orchestration will not solve the task.

## Proposed workflow

1. Classify individual pages/regions as GA55, sanction order or reference statement; preserve originals and page/box provenance. Correct rotation/perspective before OCR. Recognition does not execute document instructions.
2. Locate the table grid and cells using image/geometry evidence, not a single fixed page coordinate. Remove ruling lines within recognition crops. Process typed money with an English/numeric recognizer and Hindi order prose separately.
3. Build complete bill records across page boundaries. Carry an open employee/bill into a continuation only with matching layout/identity evidence. Preserve negative heads, informational deductions and annual summaries separately. Do not count statement TOTAL rows as a second entitlement.
4. Extract a fact record for employee ID, bill/month, basic, allowances, actual paid credits and effective dates. Join the matching employee to the sanction-order row. Distinguish order issue date, entitlement start, salary month and payment date. Here the relevant order row is5July, not3August.
5. Reconcile every bill's recognized heads to printed gross and net where available. Missing/ambiguous cells remain unresolved. Totals may reject recognition or rank explicit candidates; they must not manufacture digits or force the handwritten answer. An absent allowance becomes zero only when the entire allowance record is demonstrably complete and reconciled, with that reasoning retained.
6. Reconcile prior arrears and their covered dates. Unknown coverage blocks payable approval. Read the pay/rate/eligibility facts from the sources and saved verified library, then call the existing deterministic calendar/rounding engine.
7. Generate a machine-validated draft with PDF/Excel and cell-level provenance when all required facts pass. Keep machine validation distinct from human approval. Ask for a correction only at an unresolved field, not for retyping the entire bill. Do not label an unresolved job a successful automatic run.
8. Compare independently against the supplied due-drawn; it is a reference/check, not the input that teaches the app what answer to produce. Handwriting recognition is a separate capability to benchmark, not a prerequisite for deriving a bill from complete printed source records.

## Size feasibility evidence

Read-only PyPI wheel inspection (no installation or product integration) found rapidocr-onnxruntime1.4.4 uncompressed16275503bytes including models and WindowsCPython3.12 onnxruntime1.31.0 uncompressed43615005bytes. Combined59890508bytes excludes other dependencies and build effects. The full RapidOCR wrapper declares OpenCV, Shapely and other dependencies; these cannot be ignored in a package-size claim. A lean direct-model implementation would also need to account for its actual preprocessing/postprocessing code. No accuracy inference was run and no final installed-size compliance is claimed from wheel inspection.

Sources: https://pypi.org/pypi/rapidocr-onnxruntime/json and https://pypi.org/pypi/onnxruntime/json. Metadata and model/component sizes are retained beside this proposal. The actual Windows portable directory, including all libraries/models/fonts, must remain strictly below500000000bytes and pass the executable smoke gate before distribution.

## Acceptance before requesting more samples

- Freeze the existing private samples and independently verified reference facts as a regression corpus; do not ship employee documents in the package.
- Run every case with no manual number/date repairs, record approvals separately, and count missing/wrong fields rather than only candidate rows.
- For this case, automatically establish the matching employee,5July entitlement,24800 basic,20%HRA,27/31 days,July drawnHRA0 from a complete reconciled bill, and draft4320. The operator must not supply those facts during the run.
- Require correct treatment of July's continuation, unchanged August payment, negative ROP and the repeated statement total.
- Other supplied cases must retain prior-credit, pay-fixation, dated-rate, partial-month and GPF safeguards. Unconfirmed prior coverage is a blocked case, not a fabricated automatic success.
- Label these already-seen samples regression tests. Genuine generalization requires a later unseen sample; no claim of held-out accuracy from a file already inspected.
- Preserve the existing Decimal calculation/export behavior and measure the complete Windows installation below500MB. Do not call this finished based on unit-test counts or a manually reconstructed bill.
