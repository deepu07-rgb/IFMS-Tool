# Bill Register

Use the Bill Register sidebar to upload 1–20 PDFs (10 MiB each, 100 MiB per batch). Digital IFMS Bill Details Summary tables are extracted first; scanned or mixed pages use the existing local English OCR runtime. Originals, per-cell source-page evidence, initial extraction and review revisions are retained. Missing or uncertain layouts and duplicate bills are flagged; OCR is not guaranteed error-free.

Source/custom mode preserves literal fields and identifiers, including leading zeros and wrapped identifiers. Edit visible entries, add/remove/reorder columns, enter a source-review reference and save. The initial extraction remains in the immutable audit. Screen search and 50-row pagination do not filter downloads: exports contain all saved rows and selected columns. Check page continuations against the source viewer. Identical PDF files are skipped with notices; matching bill numbers in different files are flagged rather than discarded.

Previously imported Outer sheets can be selected in the same module. Direct recognized Outer PDFs also use the existing Outer extraction with original printed amount checks. Missing register fields stay blank; a reference number remains labeled as such rather than being asserted as a treasury or bill number. No missing pay-month, payee, expenditure head or treasury detail is inferred from unrelated fields.

Download editable Excel or PDF in A4 landscape or explicitly defined FS/foolscap 13 × 8.5 inches landscape. Wide PDFs may use repeated column bands/pages for legibility. Source labels are preserved when observed; custom columns use their entered labels. Unreviewed outputs show draft status. Excel text is literal, not executable formulas.

## Official GF&AR status

The prescribed Rajasthan GF&AR bill-register form could not be authenticated: 13 attempts against official Finance, Treasury, department sites and search sources returned network proxy HTTP 403. No form number or government column set was invented. Official mode explains the missing verification and blocks export. Source/custom exports work now. A verified official source or office-prescribed blank form is needed to implement and validate that mapping; a customized source sheet is not certified GF&AR output.

No new runtime dependencies, models or release package. Complete source backups include these original PDFs. Financial extraction and official-format authenticity are separate checks; neither is established simply by a successful upload.
