# Preparing an arrear statement

## Reuse records instead of entering them again

Use **Employee & Groups → Import extracted inner-sheet employee profiles** after extracting inner sheets, or open **Group Management** and save an imported spreadsheet snapshot to the shared workspace. Review different records for the same employee code before choosing the current profile. Old profile values stay in the audit history. Enter dated pay events for increments, promotion/fixation or changed eligibility with the relevant order reference.

## Approve drawn history

In **GA 55 / OCR**, upload GA55 or load a selected employee's extracted inner-sheet candidates. Check the original beside the editable records. Confirm each payment's employee code, payment month and bill number. Categorize regular salary, allowance arrear, leave encashment or bonus separately. Do not classify surrender/encashment DA as an ordinary salary DA arrear. Confirm any zero allowance explicitly. Mark informational deductions that do not affect net pay, and reconcile printed gross, deductions and net before approving the batch.

Previous allowance-arrear bills need the actual entitlement dates, which can differ from the payment month. Use the employee history inspector to allocate a reviewed bill once. The app blocks ambiguous regular salaries or relevant unallocated prior arrears rather than assuming they are zero.

## Calculate due minus drawn

In **Arrear / Due–Drawn**, choose the employee, allowance and dates. January 1 through March 31 includes all three months. March 13 through March 31 includes 19 days. Calendar proration uses the actual month's days; choose a 30-day rule only when the governing allowance requires it.

History mode uses dated basic pay, effective allowance rates and actual reviewed drawn components. For HRA, select the correct location category. Save custom allowance rules in the library before preparing HDA/CCA or other allowances. Basic-plus-DA and selected-component bases are available. Rules do not establish service eligibility.

Manual mode supports multiple dated periods, explicit due/drawn rates or amounts, deductions and earlier settlements. If a supplied figure already covers a partial period, choose the period-amount basis to avoid prorating it twice. Whole-rupee rounding may apply per month or per segment; select the rule supported by the relevant order.

For an uploaded due–drawn workbook/PDF, select the worksheet and relevant rows, review arithmetic flags and correct source values. DA/HRA due amounts can be recalculated from the dated library; drawn figures remain source values. Split rows if a rate changes inside the row. For leave encashment use a reviewed statement or manual periods with confirmed quantity and basis.

## Review, export and settle

A calculation saves a draft. **Reports & Backup** requires review confirmation and source/rate references before finalization. The app blocks overlapping finalized claims of the same allowance and entitlement scope. PDF and Excel both use the saved snapshot. Export a batch pack for several employees.

After actual payment/credit, record the full settlement or link an exact reviewed arrear bill. This records evidence of payment; it does not initiate payment. A later history-based revision deducts the linked settlement and can produce only the remaining difference. Drafts whose history changed must be recalculated before finalization.

## Preserve documents and backups

Original PDFs download unchanged, including their original layout. Structured Excel exports are editable review copies. A PDF generated from an uploaded workbook is a review report, not a replica of the workbook's print settings or a signed original.

Download complete backups periodically. To restore, preview a trusted backup, type RESTORE, stage it and close/restart the launcher. The launcher first saves a pre-restore backup. Documents and salary records stay on the local machine; the app does not call an external AI/OCR service.

## Dated allocations and revised leave statements

A settled combined January/February claim retains its original monthly amounts. A January-only revision deducts January's amount, rather than a share based on the combined number of days. For an imported aggregate arrear, first assign its entitlement dates, then open the employee history inspector and enter the original monthly amounts under **Review monthly arrear amounts**. Their sum must match the bill; each saved allowance allocation is immutable.

For partial-month history, confirm the uniform-calendar-day allocation option only after checking that it represents the actual drawn and previous-payment distribution. If basic pay or the drawn allowance changed during that month, enter the actual drawn period amount in manual mode instead. A whole month's average cannot establish the second half's actual payment.

For a paid leave-encashment revision, use approved manual quantities and dates. Enter the earlier linked payment numbers shown as `#...` in the history inspector in the **Linked prior payment IDs** field, and enter their exact saved prior amount. The server verifies employee, allowance, entitlement, dates and amount before allowing finalization. Match the saved settlement slices; arbitrary IDs or omitted amounts are rejected.

The explicit **30-day service month** convention counts 30 service units per full month: day 31 adds none; February's final day completes the month. Thus splitting a full month cannot reduce or increase its entitlement. Use calendar days or approved actual period amounts if the governing order uses another convention. Daily allowances always count actual days.
