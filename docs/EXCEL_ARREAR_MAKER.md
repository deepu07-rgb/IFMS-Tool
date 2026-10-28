# Excel Arrear Maker

Prepare an assisted due–drawn statement without waiting for OCR. Choose **Excel Arrear Maker** in the app's left sidebar. The workbook also works independently in Microsoft Excel or LibreOffice; neither program is a new app dependency.

Download the blank [formula workbook](../examples/IFMS-Formula-Due-Drawn-Template.xlsx) or [salary ledger template](../examples/IFMS-Salary-Ledger-Template.xlsx). These blank examples contain no employee data. Use the app's date-range download for a template tailored to the claim.

## Fastest app workflow

1. Enter employee, claim start/end, arrear type, rounding and the supplied form variant. Choose **Create monthly rows** or **Load employee ledger for these dates**.
2. In **Drawn pay & dates**, enter the actual full-month Basic, DA, HRA, HDA and CCA, bill details and salary reference. Paste a rectangle from Excel into the first corresponding cell. A confirmed absent head is `0`; an unknown figure stays blank.
3. In **Sanctioned changes**, enter the relevant basic/rates and the order reference. **Fill blank entitlement cells from first month** copies only into blank cells; it preserves dated changes already entered.
4. Check **Earlier payments**. Enter head/month allocations for payments not already included in drawn. After checking the source, the blank-as-zero action completes blank heads and records the review. Never repeat an arrear already included in drawn pay.
5. In **Deductions & checks**, enter only additional deductions from this arrear. Check and record the source, including an explicit none when appropriate. Ordinary salary deductions must not be charged again.
6. Choose **Check and calculate**, resolve highlighted fields, then **Save draft**. Export formula Excel or the supplied-form PDF. PDF needs complete inputs; incomplete drafts can still be saved and exported to Excel.

A local PDF can remain visible beside the tables. Imported PDFs also link to the existing editable OCR review. OCR readings do not become sanctioned entitlement or accepted money automatically.

## Formula workbook

- **Setup**: employee name/code, HRA/DA/increment/manual mode, rounding, form variant and whether an approved HDA divisor applies.
- **Monthly inputs**: blue literal input cells; the final column reports `OK`, `INCOMPLETE` or `UNUSED`. Cell comments explain the columns. Fill the relevant mode's inputs; irrelevant fields can stay blank.
- **Due drawn statement**: the supplied 27-column grid, with formulas for due, already drawn, differences, deductions, net and totals. This is the printable sheet.
- **Guide**: instructions and calculation rules.

For fewer months, clear all editable inputs in unused trailing rows. Keep formula rows/columns in place. If the first used month changes, its month/start/end entries must agree. The app can generate and download a different range in one step. Setup type changes may require completing additional inputs before checks become OK.

Open/save in a spreadsheet program to recalculate the formulas. When returning the file to the app, it reads literal inputs and independently recomputes results. It ignores statement formulas/cached totals, rejects formulas inside input cells, and refuses macro/external-link workbooks. Paste **values** into input cells when copying a formula-based source spreadsheet.

## Calculation choices

All entered drawn amounts are **full-month** actuals. Full-month due amounts are calculated as follows:

| Type | Changed heads |
| --- | --- |
| HRA | Basic × sanctioned HRA percentage / 100 |
| DA revision | Basic × sanctioned DA percentage / 100; optionally HDA |
| Basic / increment / ACP | Revised Basic, revised Basic × DA%, revised Basic × HRA%; optionally HDA |
| Explicit monthly due amounts | Five reviewed full-month due amounts entered directly |

Unchanged heads are carried on both sides. HDA is `(Basic + unrounded DA) / approved divisor` only when expressly enabled; the divisor/reference is required. A sample convention is not a substitute for the applicable sanction.

Dates include both endpoints and use the actual calendar month's length, including leap years. Select:

- `period`: prorate each due and drawn head to the affected days, rounding the two amounts separately.
- `whole_month`: retain original drawn pay for unaffected days, combine it with revised pay for affected days, then round each due head. Already-drawn salary remains the full monthly actual.

Choose nearest rupee or two decimals. Add allocated prior payments to already drawn **once**; do not prorate them again. Additional deductions are exact amounts, not prorated rates. Negative differences/net amounts remain recoveries.

The classic form subtracts GPF + SI + CM Corona + Income Tax. In the newer GPF-arrear form, only **GPF to deduct + Income Tax** affect the new deduction total; GPF/SIF already deducted are informational disclosures.

## Reusable salary ledger

The separate **Salary ledger** workbook includes employee, month, bill number, the five printed heads, `OTHER_ALLOWANCES`, total actual salary deductions, printed gross/net and source reference. Complete every column, using explicit zeros for confirmed absent amounts.

`OTHER_ALLOWANCES` holds the actual total of other heads (for example unchanged Mess/FTA and signed adjustments). Informational deductions outside the printed net must not be counted again. Component gross minus accounting deductions must equal printed net exactly.

Preview the file, check it against originals and confirm before saving. Admission is atomic: one duplicate/conflict or unreconciled record prevents partial batch saving. The records enter the existing employee payment ledger and can be reused across claims.

Linked drawn cells are read-only until **Use edited/manual pay** is selected. This detaches the source link and leaves a correction reference to complete. A changed, conflicting or stale ledger record blocks reuse/export. Partial-period salaries are rejected by this full-month-input workflow; manually establish correct monthly equivalents rather than prorating partial actuals again.

## Drafts and limits

Saved revisions retain previous and new inputs. Concurrent tab edits are rejected; edits made during a save remain unsaved and are preserved. Older calculation responses are discarded. Opening/importing another draft first saves the current meaningful draft; export refuses a stale in-flight snapshot.

This maker supports one effective segment per month, up to 120 consecutive months, and the two supplied five-head forms. Multiple changes within a month need separately reviewed monthly amounts and appropriate full-month coverage to avoid applying proration twice. It does not independently establish entitlement, earlier payment coverage or deduction authority, and it does not approve payment. PDF has the existing Latin-font limitation; use reviewed transliteration or Unicode Excel when a name/reference cannot be rendered.

Handwriting OCR reliability has not been improved or certified by this change. Final Windows bundling remains paused for user acceptance; no production dependencies or models were added.

## Dated rate checks and reference desk

The new [rate/slab/document guide](REFERENCE_DESK.md) explains current-library validation, HRA exemption/manual exception references, user-maintained GPF/SI schedules and pinned orders beside the bill. Version2 exports retain these settings and include a rate-check snapshot when downloaded from the app; earlier Version1 workbooks are still accepted. Standalone spreadsheet arithmetic is not live statutory-rate validation.
