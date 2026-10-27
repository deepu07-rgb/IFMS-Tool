# Preparing a consolidated arrear bill

Final software bundling remains paused pending additional sample checks and the user's manual acceptance. This workflow runs from source in the existing local suite.

1. Import the original case PDF under GA55/OCR. Select **Prepare complete bill** on that import. The case uses the shared source extraction once and retains its original PDF and source references.
2. Review outstanding order decisions against the linked original page. A name-only or unreadable employee row needs an explicit association to an imported employee. Confirm the entitlement date, sanctioned revised basic or allowance percentage, expiry if applicable, HRA eligibility and any HDA fraction with its governing reference. The order issue date is separate. These confirmations are labelled human assistance.
3. Resolve only incomplete GA55 bills needed for the claim. Records are prefilled. Correct unclear values, missing heads and printed totals against the source. Salary deductions are distinct from additional arrear deductions. For an actual partial payment, record its covered dates and the monthly basic separately. For a previous arrear payment, enter its covered entitlement dates and the actual monthly/head allocations; its payment month is insufficient evidence of coverage.
4. Select the employee, arrear kind, inclusive dates, relevant HRA category, and applicable proration/rounding rule. If additional arrear deductions apply, enter their supported adjustment and reference; confirm zero explicitly when appropriate. Prepare the consolidated statement. Every month retains due, actual drawn, prior credit and difference for every relevant head, including unchanged signed recoveries. Months already paid at revised pay contribute zero additional arrear.
5. Export the whole statement as PDF or Excel. Saved bills appear under Reports. Source/rate/history changes invalidate approval of old calculations. Final approval requires source, prior-payment and additional-deduction review. Overlapping finalized bills/claims are rejected.

If entitlement or previous-payment coverage is unknown, the app retains verified rows as a blocked provisional draft and withholds net payable. Resolve the missing evidence and prepare a fresh bill; do not enter a guessed date or amount to clear a blocker.

## Existing due–drawn statements

The source-backed calculation does not use a handwritten total as its target. It derives entitlement from the order, rates and actual drawn records independently.

A comparison page can be classified explicitly as a reference statement after source review. Orders or payment evidence must not be classified away. The case's **Read individual table cells** tool uses printed grid rules and preserves cell/text-line candidates with original-image provenance. Faint column headings can be mapped after explicit review. It cannot infer missing amounts, repair digits to balance a total, or treat a repeated subtotal as another month's entitlement.

Handwritten candidates can be wrong despite high confidence. Uncertain or multi-line cells remain unresolved. Available semantic reference rows are compared by component, so equal errors on both sides do not disappear behind a matching net. When no trustworthy monthly reference rows are available, comparison remains visibly incomplete and final approval requires a source comparison review. No unattended handwriting accuracy claim is made.

## Current capability boundary

The consolidated source workflow handles HRA, DA and sanctioned revised-basic arrears across months, with an explicitly supported HDA dependency when configured. It uses sanctioned pay values; it does not decide legal eligibility, unresolved suspension/court cases or unprovided promotion/MACP fixation values. The existing custom allowance/history maker remains available for other configured allowances. Unknown financial evidence remains a review dependency.

The installed-size/Windows distribution check belongs to the later authorized bundling phase. No dependency or recognition model was added by these workflow repairs.
