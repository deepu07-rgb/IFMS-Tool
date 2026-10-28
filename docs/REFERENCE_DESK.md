# Rates, salary slabs and Important Documents

These additions extend the Excel-first assisted arrear maker. No new runtime libraries or models are required. Final executable bundling remains paused for user acceptance.

## Dated rates and validation

In **Rates & Allowances**, save an allowance, calculation basis, effective date, optional expiry, category, value, order date/reference and rounding. DA/HRA are percentages of basic. Uniform allowance or another named allowance can use fixed monthly/daily amounts or the existing percentage bases.

A new named allowance gets a matching default calculation rule if none exists. Existing rules are preserved; review the separate rule form when changing a rule's basis/proration. The five-head supplied due–drawn form remains Basic/DA/HRA/HDA/CCA; other allowance calculations remain available in the existing component workflow rather than changing the supplied format.

- **New dated rate** preserves earlier effective dates. Enter a future increase only after checking the actual rate, effective date and order; no future DA increase is guessed or seeded.
- **Edit** requires an amendment reason and checks the record revision. Existing cash-date/order/source metadata omitted by an edit is preserved. The optional cash-payable date is separate from the entitlement effective date.
- **Archive** removes a rate from active selection; it retains history and can be restored. Archived bundled rates stay archived after restart. Restoring a rate cannot replace a conflicting active record silently.
- **History** shows old/new values and reasons. Manually entered/amended rates remain marked manual.

In **Excel Arrear Maker**, select the HRA category and choose **Use dated library DA / HRA rates**. The action checks row dates; it does not establish employee eligibility. The server independently checks entered rates whenever you calculate, reopen or export a saved draft.

A known mismatch highlights the field and blocks PDF. Correct it or enter a specific DA/HRA manual-exception reference. An HRA exemption needs an explicit zero rate, the exemption checkbox and a non-entitlement reference. A change inside a monthly row must be split/reviewed or represented by reviewed blended monthly amounts in manual mode.

Missing library coverage/category produces a prominent warning. It is not an independently validated rate. Explicit source-reviewed manual inputs can still be used; the app does not claim legal certification. Archived/expired/revised rates are checked again on saved bill export.

The formula workbook retains HRA category and per-row exception/exemption fields. Version1 workbooks remain importable. App exports include a **Rate checks** snapshot sheet; standalone formulas do not consult a live office library. Return edited workbooks to the app to check current rates.

## GPF and SI slabs

Use **GPF & SI Slabs** to add user-authorized GPF, GPF-2004, GPF-SAB or SI schedules. No real schedule is prefilled without its authority.

Enter scheme, optional category/group, effective dates, salary basis, reference, rounding and slab rows. Basis can be monthly basic, basic + actual DA amount, or gross salary. Each band has a lower-inclusive and upper-exclusive boundary, fixed amount or percentage value. Blank upper bound means no ceiling. A rule written with an inclusive upper amount needs the corresponding next representable boundary; verify this conversion against the order and the salary precision.

The lookup uses the latest effective schedule for the exact category. Ambiguous schedules, gaps, expiry or missing salary inputs produce explicit messages rather than zero subscriptions. Amounts are calculated with Decimal and the selected rounding rule. Schedules support audited edits and reversible archive/restore.

A suggestion is the **full subscription**, not an extra arrear deduction. Compare it with the actual amount already deducted and check any retrospective sanction. Pinning or viewing a slab never writes a deduction into a bill.

## Important Documents

Create categories such as **Travelling Allowance Rules**, **Pay Fixation Orders** or **Insurance Rules**. Add PDF/DOCX originals, typed rules or both source and explanatory text. Record title, category, order number/date, effective dates, tags and notes. Search/filter these fields and locally extracted PDF/DOCX text.

Scans without selectable text remain searchable by entered metadata/notes; the library does not claim handwriting OCR or hidden scan-text indexing. DOCX preview is extracted text, including table paragraphs; download the preserved original for Word layout. Original files are kept by SHA256. Metadata/text edits preserve original bytes and record revisions; archive/restore preserves documents.

Limits:10MiB/file, PDF500pages/100,000xref entries, DOCX1000ZIP entries/30MiB expanded content and extracted text2million characters. Unsupported active/external DOCX relationships and XML entities are rejected; nothing is fetched externally. Stored originals are covered by the complete database/source backup, including DOCX.

## Work with references beside a bill

Choose **Pin beside work** or drag a document, rate or slab card onto the workspace. Move a panel by its title bar and resize from its lower-right corner. Up to six references can stay visible together across module changes. Their IDs and geometry are restored after reload and constrained to the current screen size.

The **References · open / pin** button opens search from any module, so you can find an order without leaving the bill. Pin also works by button for keyboard/touch users; dragging is optional. Close a panel to free screen space, or refresh it after editing the original library record. Archived references are labeled. Viewing a reference does not establish its applicability or approve payment.

## Verification evidence

Development browser tests exercise typed-rule creation, PDF/DOCX upload/search, moving/resizing, navigation/reload persistence, small-screen bounds, rate save/archive/restore, wrong DA correction, sample bill calculation and PDF/Excel downloads. Synthetic schedules/rates in tests are clearly labeled and do not ship as authority. Private employee samples, generated bills and screenshots stay outside Git. See docs/VERIFICATION.md for the final test gate.
