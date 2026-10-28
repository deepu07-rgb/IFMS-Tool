# Approved continuation: reusable ledger and editable OCR

The user approved a ledger-based arrear maker, requested at least 80% accurate
visible OCR with editable final corrections, and restricted bill output to the
supplied due/drawn formats. Existing permission covers this implementation.
Final packaging remains paused until sample testing and the user's manual review.

## Implementation and verification

1. Reuse reviewed `suite_payments` as the employee's persistent monthly ledger;
   separate salary drawn from previous arrear credits. Admit selected original
   source bills only after explicit verification and arithmetic reconciliation.
2. Reuse monthly records across imports, including a separate sanction case.
   Check immutable source bytes, extraction version, source review snapshots,
   classifications, covered periods and amounts before calculation or approval.
   Conflicting monthly salaries and unknown prior-credit coverage block payment.
3. Expose detected source-grid cells, uncertain raw candidates and blank cells
   beside the original image and source-cell magnification. Save only changed
   entries as separate source-bound audited corrections. Never overwrite raw OCR
   or count human correction as automatic recognition.
4. Keep reviewed due/drawn cells as comparison evidence only. Invalidate stale
   comparisons after corrections or either extraction version changes.
5. Export only the two reconstructed supplied Jodhpur grids with their column
   order, totals and signature areas. Select the appropriate right-hand variant;
   reject unsupported changed heads or unresolved settlements instead of switching
   formats. Verified allocated credits count in already-drawn columns with an
   explicit disclosure; the original calculation remains unchanged.
   Revalidate saved bill dependencies before export, including finalized bills.
6. Score independent truth against machine readings: exact financial fields,
   dates, identities, text and character errors, separately for printed, mixed
   and handwritten content. Count missing written fields. An 80% target is not
   evidence of an 80% result. Old training samples are development diagnostics;
   held-out evaluation remains necessary for acceptance.

No new production dependencies, models, cloud OCR or release workflow are part
of this change. Source samples and operator screenshots remain outside Git.
The complete installed Windows size limit is still 500,000,000 bytes; no newly
bundled artifact is being produced or certified in this continuation.

## Concrete acceptance checks

- Synthetic financial regressions cover conflicts, stale evidence, bulk admission
  rollback, actual saved-ledger reuse, and exact supplied-form totals.
- Actual browser tests cover saving a verified original month, reload, preparation,
  format choice, local source viewing, corrections and matching exports.
- Run the complete repository test command after integration; record failures and
  limitations, including OCR and form readability, before any completion claim.
