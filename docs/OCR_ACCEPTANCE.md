# OCR acceptance and source correction

The synthetic tests verify scoring and review behavior; they do not establish an
80% recognition result. A limited original-source development diagnostic is
recorded below, separately from the required acceptance evaluation. The requested
threshold means at least 80% exact machine field
accuracy on an independently transcribed evaluation set, with missing fields in
the denominator. Character accuracy is a separate diagnostic; it cannot substitute
for exact dates, identity strings or money digits.

## Independent evaluation

1. Freeze a source manifest (SHA-256, source page and cell/field ID), extractor
   version, OCR configuration and an immutable raw machine-output snapshot.
2. Select held-out pages representative of printed, mixed and handwritten originals.
   Include faint lines, imperfect scans, uncertain candidates and absent predictions.
   Record sample counts and keep the documents private. Do not tune on the test set.
3. Have a person transcribe truth from the original without seeing OCR, model answers,
   corrected overlays or target totals. Independently check critical digits, dates
   and identity, and resolve disagreements against the original. Mark genuinely
   illegible truth separately and report its count; do not invent values to score.
4. Use `ifms_suite.ocr_quality.score_ocr(truth, predictions)`. Truth records contain
   `field_id`, literal `text`, `category` (`digits`, `date`, `identity`, `other`) and
   `medium` (`printed`, `mixed`, `handwritten`). Predictions contain `field_id`, raw
   `text`, `origin="machine"`. User corrections must be tagged `origin="human"`;
   they are counted as excluded and never replace machine predictions. Never pass
   corrected rows as machine predictions. Keep the truth and prediction files
   separate from the application payload and repository.
5. Report overall and per-medium exact field accuracy, counts, missing fields,
   exact digits/date/identity accuracy, and each medium/category stratum. Report
   unexpected machine fields separately; they do not enlarge the expected-field
   denominator. The implementation reports character accuracy as
   `max(0, 1 - Levenshtein edits / truth characters)` plus the raw edit counts and
   character error rate. Rates for an empty denominator are `None`. Exact scoring
   does not normalize punctuation, spacing, currency, dates or case. If blank truth
   fields are evaluated, report their count separately so they cannot obscure the
   requested written-content accuracy.
6. Claim the 80% threshold only with the frozen evidence, sample sizes and actual
   rates. Publish stratum failures alongside any overall pass. Re-evaluate after
   changing extraction/OCR versions. OCR confidence is never measured accuracy.

## Review workflow

The statement grid exposes detected source cells even when no monthly semantic
row was promoted. Inputs include raw uncertain candidates and empty cells. The
original page appears beside the table; focusing a cell magnifies its source
polygon. Multiple raw line candidates stay visible beside the input for review.
Each candidate has a button to copy its literal text into the input; selection
does not save or mark it reviewed. Ordinary correction saves submit only changed
entries, so untouched blanks and suggestions do not become human-reviewed cells.
The editor only handles detected grid cells; undetected tables or missing geometry
still need separate extraction/manual handling.

Observed handwriting outside resolved table rules appears in a separate source
margin panel. An operator can copy a raw candidate or type a transcription and
save changed annotations with an explicit original-source review and reference.
These annotations share the source/grid/editor revision guard, retain their own
region IDs and `origin="human"`, and have before/after audit events. Raw margin
regions remain immutable. Margin transcriptions never create table columns or
semantic amounts; their source geometry and column assignments remain unresolved.

Saving reviewed entries stores a correction overlay and audit events separately
from immutable `statement_grids`: source SHA, grid-content/version hash, correction
revision, timestamp, review reference, and before/after cell text. Updates reject
stale source/grid/editor revisions. A new extraction preserves historical audit
records but does not apply corrections from an obsolete grid. Actual source bytes
are checked before viewing or editing. The local application has no authenticated
reviewer identity, so the audit establishes the review reference and time, not an
independently verified person's identity.

Column mapping requires explicit confirmation against original headers and cells.
Only reviewed mapped cells become reference-comparison rows. Missing values stay
missing: no balancing to a target total and no inferred handwritten digits. Cell
changes invalidate previously mapped comparison rows until mapped and reviewed
again. These rows are never entitlement evidence or proof of a pay rate/payment.

## Development diagnostic, 28 October 2026

The initial grid missed faint top rules and clipped through the first handwritten
baseline. Geometry now uses a sensitive threshold independently of OCR ink.
Extraction version 3 also retains unassigned right-margin regions when several
observed horizontal rules visibly continue beyond the last vertical rule. A page
edge bounds their source crops; it does not establish a financial column.

One previously supplied handwritten page was checked against 32 readable numeric
source entries, with blue monthly entries and red repeated totals evaluated
separately. Raw baseline OCR reproduced 27/32 exact literals (84.375%): 15/16 blue
and 12/16 red. Two of the exact readings are unassigned margin candidates. The
same source slice before right-margin recovery yielded 25/32 (78.125%). Frozen
source hashes, raw outputs, source-only literal transcriptions and per-entry
results are private and outside Git. No amount was inferred from arithmetic.

This is a development diagnostic on a known page, not a held-out evaluation or
whole-document score. Dates, employee identities, printed headings, dashes and
other handwriting were outside this numeric slice. Multiple handwriting
baselines share physical cells, so zero of these 32 entries became unambiguous
accepted cell values automatically. Correct candidates are visible and selectable
for review. The result must not be reported as 84.375% automated financial
accuracy or a guarantee that arbitrary bills meet the user's 80% target.

Margin transcriptions have their own editable annotations, explicit review,
source/grid/revision binding and audit. They never enter mapped comparison rows
or establish entitlement. Raw regions keep null text/amount and unresolved
column identity, even after an annotation is saved. Ordinary cell edits save
only changed entries; selecting a raw candidate alone does not approve it.

## New-sample check after the development diagnostic

Two further scanned statement pages did not meet the target. Exact raw monetary
readings were 5/28 on the handwritten table and 33/48 on the printed table. The printed
source has explicit zeros and two wrapped totals; missing or truncated readings
count as errors, without letter/digit substitution or concatenation to the expected
amount. Accepted cell values were 0/28 and 28/48 respectively. Source identity/date
accuracy and the separate salary-slip extraction are reported independently.
These failures show why the earlier known-page 84.375% result is not an acceptance
claim for new documents. Local grid/extraction repairs do not replace the need for
better handwriting recognition and field-level review.
