# Legacy Inner Sheet total failures

Investigated 27 October 2026 using `/workspace/ifms-dev/bin/python`, the original `parser.py`, and the existing private/local fixture PDFs. No personal source rows or new sample files are included here. The expected JSON values were not changed.

## Reproduced defects

Baseline command: `python -m pytest tests/test_expected_totals.py -q --tb=short`.
Result before changes: **13 failed, 1 passed**. Employee count and gross matched in every case; each failing case first failed its deduction assertion. Net assertions occurred later and were therefore masked by that failure.

Two independent geometry errors caused the failures:

1. **Deduction/net column divider.** The source table divider is at x=705.53. The legacy parser instead assigned every numeric word with 660 <= x < 715 to the sum-deduction column. Right-aligned six-digit net amounts start around x=712.6, so a net amount overwrote the employee's actual deduction. Its missing net was then synthesized from gross minus the corrupted deduction. This could produce a self-consistent arithmetic identity with wrong financial values. Correcting the divider alone resolved 11 of the 13 failing fixture tests.
2. **Early final-page summary.** PDFs 8 and 10 place the bill summary at y=179.6 and y=189.7. `_find_data_boundary` recognized the left-margin Gross Amount summary only below y=200. Consequently it extended the last employee block through the bill summary and assigned the bill-wide net amount to that employee's deduction field. The summary's left-margin position and adjacent Amount label already distinguish it from the Gross column heading; the y restriction was unnecessary.

## Repair and evidence

`parser.py` now uses the printed deduction/net divider and recognizes the left-margin Gross Amount summary at any page height. No arithmetic values are selected to force reconciliation, and no expected totals were changed. Other parser modules and suite modules were not modified for this repair.

`tests/test_legacy_inner_columns.py` contains synthetic rows for six-, seven-, and eight-digit net amounts plus early-summary boundary cases. All five cases were observed failing on their respective original behavior before each minimal fix. The tests contain no employee data.

Every expected gross/deduction/net triple was separately checked against the source PDF's own printed bill summary. Those 14 summaries agree with the existing expected JSON. The regression tests additionally compare parsed employee sums and counts against those independent expectations.

## Scope limits

This repairs the two demonstrated legacy layout assumptions. It does not establish support for arbitrary column layouts, scanned PDFs, handwritten statements, every employee identity/component field, or zero/small net values. The legacy parser still infers some missing totals; agreement of aggregate totals alone is not proof that every extracted component is correct. Broader source-evidence and review work remains necessary under the approved proposal.

## Verification

After both fixes: `python -m pytest tests/test_expected_totals.py tests/test_legacy_inner_columns.py -q --tb=short` → **19 passed in 18.28s**. A separate source-summary/parsed-row reconciliation pass succeeded for **14/14 PDFs**. Full repository verification is coordinated by the parent implementation task; this targeted result does not assert a complete-suite pass.
