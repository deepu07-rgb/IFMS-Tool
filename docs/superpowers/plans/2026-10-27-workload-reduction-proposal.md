# IFMS reliability and workload reduction — approval proposal

Status: approved by the user; implementation in progress. Final packaging remains paused until additional sample tests and user manual acceptance.
Evidence reviewed: source commit fa266f6, current import/OCR/calculation/review code, and saved private sample reports dated 27 October 2026. This review did not rerun OCR or tests. Earlier extraction-recovery work is a foundation, not evidence that the whole workflow succeeds.

## Intended outcome

Upload a case containing GA55, orders and an optional existing due–drawn. The app identifies the employee and relevant periods, prepares a source-backed month-wise statement, asks only about unresolved facts, checks an existing statement independently, and produces consistent PDF/Excel outputs. Measure the operator's work from upload through checked export, including corrections and final review.

## Confirmed causes

- `web.py` uses `parse_ga55` and the column OCR fallback for ordinary GA55 import, while `automatic_hra.py` uses `document_facts.py`. A successful fix in one path does not necessarily reach the other.
- `due_drawn.py` recognizes exact Pay Due/Pay Drawn headings separated by four columns, with Basic/DA/HRA plus total. Different headings, HDA/CCA columns and handwritten layouts are not generally represented.
- Source-driven orchestration handles HRA orders. `increments.py` requires reviewed inputs and one full calendar month; it is not an automatic increment-order reader. The shared history/calendar engine already provides useful foundations and should be reused.
- `fact_review.py` supports a narrow HRA-rate correction. Dates, amounts, employee associations, deductions and missing table cells do not have an equivalent unified targeted review flow.
- Document-level blockers can prevent all useful output, while ordinary review screens require substantial manual reconstruction. Unresolved relevant evidence must continue to block payment approval, but the app should preserve verified work and explain the exact dependency.
- Saved four recent sample runs produced no automatic claims or usable handwritten statement rows. Separate reviewed calculations worked. One handwritten statement had an incorrect component on both sides despite a correct difference.
- Last recorded full suite: 267 passed, 14 skipped, 13 inherited expected-total failures. These counts are historical, not a new verification run. Broad daily-use claims require diagnosis of the inherited failures too.

## Approach and tradeoffs

Recommended: consolidate the current app around one source-evidence pipeline, retain the deterministic calculator and working analyzer modules, then add targeted review and broader order/statement support. This repairs the main discontinuities without discarding established calculations and exports.

Continuing isolated OCR patches is cheaper per fix but leaves inconsistent routes and missing orchestration. A large generative document model would introduce new accuracy, installation-size and potentially connectivity problems; it is not the proposed default. Compact offline OCR alternatives may be benchmarked, but must earn their place through measured gains and total installed size. No promise of universal handwriting recognition.

## Ordered work packages

### 1. Establish a reproducible baseline

- Freeze existing originals and independently reviewed reference facts in private storage. Record known missing entitlement/credit evidence separately from software defects.
- Capture the complete current user-facing workflow in a fresh database: extracted fields, missing/wrong fields, claims, blockers, manual edits, time and exports.
- Keep reference answers outside the app's inputs. Classify cases by printed/mixed/handwritten material and arrear type. All existing samples are development regressions, not unseen validation.
- Diagnose the 13 inherited total failures against source evidence. Correct wrong code or demonstrably wrong expectations with an explanation; do not hide failing routes.

Deliverable: repeatable benchmark and explicit supported/unsupported case list.

### 2. Unify extraction and case evidence

- Give ordinary GA55 import, source-driven arrears and statement checking the same facts and source references. Migrate with compatibility tests, preserving originals and reviewed history.
- Classify pages and regions into GA55, employee-specific orders, existing statements, summaries and attachments. Record each nonblank page as processed or requiring classification; no silently omitted financial pages.
- Represent employee, bill ID, pay month, covered dates, component amounts, deductions, signs and totals with source page/cell, original OCR, reliability and review status. Separate missing, uncertain, zero and not applicable.
- Improve rotation/table/cell recognition and continuation joining. Re-read difficult crops with existing local engines before adding dependencies. Never choose a financial value solely because it makes the totals agree.
- Reuse cached extraction by source hash and extractor version; rerun affected pages rather than every document. Avoid duplicate import/payments.

Primary areas: `document_facts.py`, `documents.py`, `ga55_table_ocr.py`, `web.py`, storage adapters and extraction tests.
Deliverable: consistent source records regardless of the entry screen, including complete relevant allowances and deductions.

### 3. Turn orders and history into a unified monthly calculation

- Extract employee-specific old/new basic, effective start/end, issue date, allowance eligibility and sanction terms from supported Hindi/English order layouts. Unreadable or legally ambiguous clauses require focused review.
- Start with HRA sanctions/continuations and ordinary increments; then DA revisions and configured custom allowances. Promotion/MACP/fixation uses sanctioned pay values first; unsupported fixation decisions remain explicitly assisted.
- Use the shared calendar/history engine to split at month boundaries and changes in pay, DA/HRA rates, eligibility and sanction expiry. Support inclusive partial months with the applicable explicit proration rule; do not treat calendar-day proration as universal government policy.
- Keep actual drawn amounts separate from recalculated entitlement. Apply the verified rounding rule at the correct component/period level. Handle signed recoveries, unchanged heads and separate gross/additional deductions/net.
- Store prior arrears by covered period, employee and head. Unknown potentially overlapping coverage blocks payable approval. HRA continuation dates are not proof that every sanctioned month is unpaid.
- Preserve the dated rate library, official/manual provenance and override reasons. Custom HDA/CCA rules require basis, effective dates, eligibility, rounding and reference; a name alone is insufficient. Validate HDA rules against governing evidence, not only matching samples.

Primary areas: new structured order adapter and orchestration, `automatic_hra.py`, `history.py`, `increments.py`, `calculation.py`, existing rules/rates/settlement modules.
Deliverable: one multi-month case statement with all relevant heads, backed by order and payment evidence.

### 4. Independently read and check supplied statements

- Replace the fixed three-head assumption with detected column groups and configurable component mappings. Recognize common due/drawn heading variants, multiple header rows, printed or handwritten cells, totals and repeated annotations.
- Treat the supplied due–drawn as a comparison document. Generate entitlement from orders, rules and actual paid records independently; a handwritten answer does not authorize pay or supply a target for OCR correction.
- Compare employee, period, every component, due/drawn totals, prior payments, deductions and net. Show discrepancies even when the final difference matches.
- If a reference statement cannot be read, retain the independently prepared source-backed draft and mark comparison incomplete. Unknown pages that could contain financial authority or payments remain unresolved until classified; do not simply ignore them.

Primary areas: `due_drawn.py`, statement workflow and export comparison views.
Deliverable: exact-cell discrepancy report and honest comparison coverage, not a net-only pass.

### 5. Make manual review small and reusable

- One case workflow: Upload → Review exceptions → Check statement → Export. Show source crop next to each unresolved value, why it matters and the affected calculation.
- Extend focused review to dates, employee/bill links, amounts, eligibility and credit allocations. Preserve original recognition, correction, reviewer reference and version. Recalculate affected months and invalidate stale approvals.
- Ask for each fact once, save/resume work, reuse verified employee history and valid rules. Never transfer a correction or entitlement to a different employee automatically.
- Scope issues to their proven dependencies. Unrelated employee cases can proceed only when relevance is established; ambiguous identity or unknown financial content cannot be bypassed. Show verified subtotals as provisional while approval remains blocked.
- Present a unified bill; avoid requiring the clerk to prepare and assemble separate component claims. Keep existing Inner/Outer/Group modules accessible and share reviewed data through explicit adapters.
- Sidebar proposal: Work queue; Employees & groups; Inner sheet; Outer sheet; GA55; Arrear maker; Rates & allowance rules; Reports & backup. Reuse existing modules rather than duplicating them.

Primary areas: `fact_review.py`, `web.py`, `static/suite.js`, `templates/suite.html`, history/claims storage, existing export modules.
Deliverable: a clerk corrects a few exceptions rather than transcribing the full bill.

### 6. Verify usefulness, then decide on release

- Run automated calculation and extraction regressions during implementation. After repairs, rerun every original sample through the actual UI/API in a fresh workspace with no assistant-supplied answers.
- Record unassisted results first; separately run the assisted workflow and count every field correction, confirmation and missing external fact. Test PDF/Excel values, complete head coverage and approved layout references.
- Then request 2–3 unseen varied cases for holdout testing. Freeze the version before testing; after a holdout drives a fix, it becomes a regression case and fresh holdouts are needed.
- Pilot with the clerk on representative daily work. Compare total active operator time against the same manual tasks, including review and correcting exports. Record OCR waiting time and typical-PC performance separately.
- Only after the user accepts the accuracy and workload results, resume Windows packaging. Measure all required runtime files, OCR binaries/models/fonts and bundled dependencies below 500,000,000 bytes; a compressed ZIP or Linux-only size is insufficient. Preserve offline operation and local documents.

## Proposed acceptance gates

These are proposed targets, not achieved results or guarantees:

1. Zero silently accepted wrong critical identities, dates, amounts or overlapping credits in the tested corpus. Every included financial row/component must match independently verified evidence under documented rules; a matching net alone fails this gate.
2. Fully determined cases reconcile exactly; cases with genuinely missing evidence report the correct blocker and provisional scope. Do not force unknown cases to a final payable amount.
3. Report automatic success as cases completed without corrections divided by all tested cases, with supported cases also broken out by type. Provisional target: at least 80% of supported routine cases need no numeric/date correction; report raw counts for small sets and do not generalize them to all bills.
4. Target at least 70% median reduction in active clerk time over the agreed manual baseline, with per-case results so difficult cases cannot disappear in an average. Target no more than three field corrections for a typical supported case; count confirmations separately.
5. Mandatory financial regressions pass; inherited failures are resolved or affected legacy functionality is visibly unavailable pending repair. Every skipped test is accounted for against the claimed support scope.
6. PDF/Excel agree with saved calculations and the selected office layout; no personal samples are shipped. Complete Windows size, offline and startup gates pass only during the later authorized packaging phase.

## Scope decision requested

Approve the consolidation-and-targeted-review approach and the ordered repair work above. Implementation should proceed in these testable work packages, with progress reported as working capabilities and measured reductions in manual intervention. Final packaging and daily-use readiness remain separate decisions after retesting. No product code or dependencies were changed while preparing this proposal.
