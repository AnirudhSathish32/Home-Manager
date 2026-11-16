# Receipt layout eval: measure how images should be read before changing it
Feature: receipt-layout-eval

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: nothing. This adds an eval task and eval-only reading formats. The reading it measures is the built behavior in
`docs/documents.md` "Images (vision transcription)" (specs/dining-receipt-indent FR-15 – FR-21) and the eval design in
`docs/evals.md`. The change to how the app reads images is a later spec, written from this eval's results.

## Decisions already made (user, 2026-11-15; not to be re-asked)
- **D1 Measure first.** Before any change to how images are read, build a realistic receipt eval and compare candidate
  reading formats on the user's own vision model. The reading spec follows the numbers.
- **D2 Positions are data.** Text positions reported by the vision model may be kept and used to build layout and to
  highlight lines. They are always marked as the model's report, never shown or used as measurements. In this feature
  they are used only by the eval-only `spans` format and the eval's diagnostics.
- **D3 No interim fix.** The app keeps reading images with today's format (`receipt-vision-v7-indent`) until the reading
  spec lands. Real receipts keep splitting rows until then.
- **D4 Indent stays data beside the text** (carried from specs/dining-receipt-indent D3): never leading spaces in a
  line's stored text.

## Goal / users / scope / non-goals
**Goal.** Numbers that say which way of reading an image keeps each printed row whole, each indent right and each money
amount exact, on the vision model the user actually runs. Synthetic receipts are measured in Git; the user runs the
same comparison end to end on the private corpus in their own terminal.

**Users.** The developer running evals locally, now and whenever the vision model changes.

**Scope.**
1. A synthetic receipt layout generator: receipts drawn the way real ones print (prices at the right edge, indented side
   lines, centered headings, handwritten tip), in several print styles and photo conditions, with exact answers.
2. A `receipt_layout` task that grades row integrity, money, indent, cells and positions.
3. Four reading formats in the app's reading code, selectable only by the evals: today's, its predecessor as a control,
   and two candidates.
4. A deterministic row builder for the positioned-text candidate.
5. A `--formats` option on both eval runners, a format comparison in the report, and the format label in the shareable
   summary.

**Non-goals.** Changing how the app reads (the reading spec decides); the Text view's "as printed" mode; finding tables
from positions; reading long receipts in strips; zoomed re-reads of rows that fail arithmetic; highlighting lines on the
image; choosing a vision model; any judge model; letting a format be chosen in Settings or on any page.

## Existing behavior (verified paths, assumptions, unknowns)
Verified:
- **Today's reading.** `src/home_manager/models/vision.py`: `VISION_VERSION = "receipt-vision-v7-indent"`. The answer is
  `{lines: [{text, indent}], tables}` (`LINE_ITEM`), parsed by `parse_lines`; an invalid answer gets one text-only rescue
  call; `LINE_RULES` (commit e873c68) asks to keep an item and its price on one line. `transcribe_preview` turns the
  lines into `TextLine{id, text, block_ids, indent}`; scanned PDF pages use the same `transcribe`
  (`documents/pdf_reader.py:89-97`).
- **The previous reading.** `receipt-vision-v6-tables` asked for `{full_text, tables}` (`git show
  3128497^:src/home_manager/models/vision.py`, lines 20 and 131).
- **Observed on the user's real receipts (2026-11-15).** v7 splits printed rows: "Bottled Water" / "$3.95", "Bill:" /
  "$52.76", and once a price after the side line below its item. The `LINE_RULES` sentence didn't change that. v6 kept
  rows (a tab between item and price) but gave no indents.
- **Eval-only overrides.** `Sampling` (`models/vision.py:44`) carries temperature, seed and `schema_enforced` for evals,
  left out of every dump when unset, so saved settings and run options (reuse keys) stay byte-for-byte unchanged.
- **The synthetic corpus can't show a split row.** `evals/synthetic.py` `receipt()` prints each item as one string
  ("COFFEE 4.50") and `draw()` (line 390) writes every line flush left in Arial or Pillow's default font. Nothing is
  right-aligned, indented or centered.
- **The transcription task** (`evals/tasks/transcription.py`) grades CER, WER, key lines and reported table cells, drawing
  each case at run time.
- **The runners.** The task suite (`evals/tasks/runner.py`) and the documents suite (`evals/run.py`) call the app's real
  code. Per-candidate variants already exist for schema enforcement (`schema_variants`, `<name>@no-schema`, configured
  through `candidate_sampling` into `VisionConfig`, `evals/run.py:357`). Variants are reported, never ranked.
- **Telemetry.** The model client records completion tokens when the server reports them (`model_client.py:177`).
- **The shareable summary** is built from an allowlist and refused otherwise (`evals/report.py` `summary`,
  `check_summary`).
- **The breakfast fixture** is already in Git with an invented address but the real receipt's order number, 179580
  (`tests/dining_receipt_fixtures.py:37`).
- **The text-PDF engine** builds rows, words and cells from positions, and `amounts_of_rows` keeps amounts printed at the
  right with the rows on their left (`documents/pdf_layout.py`). This is the approach the `spans` format follows for
  images.

Assumptions:
- The user's vision model is a Qwen2.5-VL-class model served by LM Studio (`evals/models.toml` baseline:
  `qwen2.5-vl-7b-instruct`). Such models were trained on "text spotting" output: a JSON list of text pieces with boxes.
  That habit is the likely reason a JSON list of lines splits rows. This is a hypothesis the eval tests, not a fact.

Unknowns (the eval answers them):
- Whether the model reports usable boxes on long, dense, tilted receipts, and whether it reads digits as well when it
  also reports positions.
- How much longer the answers get, and how often long receipts hit the 8,192-token answer limit.

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | **Layout generator.** A receipt is defined as printed rows. Each row has cells (text, and where it sits: left, center or right), an indent of 0, 1 or 2, and a handwritten flag per cell. Drawing places left cells at the margin plus one indent step per level, right cells against the right margin, and centered cells in the middle. | A two-cell row draws its amount ending at the right margin; an indent-1 row starts one step right of an indent-0 row; a centered row's middle is the receipt's middle (checked on the drawn boxes). |
| FR-02 | **Layout families**, each a case tag: `grocery` (quantity and savings lines indented with their own prices, a tax letter after prices), `dining` (built from the breakfast fixture rows: unpriced side lines at indent 1, Bill, Tip and Total with the tip and total handwritten, a suggested-tip block), `fuel` (label and value pairs), `terminal` (a card-terminal block: label at the left, value at the right), `itemized` (a table with a Qty / Item / Price / Total header), `long` (at least 80 rows), `ereceipt` (proportional font, no thermal look), `return` (RETURN rows). | Each family has at least two cases; each case's tags include its family. |
| FR-03 | **Print styles.** A thermal monospace font, a proportional font, and a handwriting font for handwritten cells. The fonts are files in the repository under a permissive licence, so drawing is identical on every computer. | Drawing one case twice, on any computer, gives identical PNG bytes; the licence files sit beside the fonts. |
| FR-04 | **Photo conditions**, each a case tag, applied after drawing with fixed seeds: `clean`, `faded` (grey print and specks, as today's faded look), `tilted` (2–3°), `angled` (a perspective warp like a phone photo), `blurred`, `small_text` (a long receipt photographed whole, so its text is downscaled) and `background` (the receipt on a darker margin). Every cell's box is transformed with the image. | After `tilted` and `angled`, each recorded box still encloses its drawn text (checked in a test by the ink inside each box). |
| FR-05 | **Answers per case:** the rows in printed order with their cells, indent, alignment and handwritten flags; each money amount; each cell's box in the final image. Case ids are stable (`make_case`). | The same generator inputs give the same case ids and answers. |
| FR-06 | **No real personal data.** Merchants, addresses, card and terminal numbers are invented. The `dining` family reuses the items and layout of the fixture already in Git, with its order number replaced (the fixture's `179580` is the real receipt's). Every invented card, terminal, reference and order number starts with `0000`, so it can't be mistaken for a real one. | A test checks that every long number (6 digits or more) in every case starts with `0000`. |
| FR-07 | **Reading formats.** The app's reading code offers four formats, selectable only by the evals: `v7-lines` (today's, the default), `v6-text` (the v6 prompt and answer shape, restored word for word from `3128497^`), `layout-text` and `spans`. Each format has its own prompt version label, recorded with every eval result. The same format applies to every vision call in a run: images, scanned PDF pages and combined images. | A run with each format sends that format's prompt and schema; results carry the label. |
| FR-08 | **`layout-text`.** The answer is `{full_text, tables}`. The prompt asks for one printed row per line, a tab between pieces of text printed apart on the same row, and one leading tab per indent step. It contains no receipt-specific rules. Parsing: leading tabs give the indent (more than two counts as 2); tabs inside the line split cells; the stored text is the cells joined by single spaces; tables are validated as today. | "\tNo Allergies" gives indent 1 and text "No Allergies"; "Coffee\t$14.95" gives cells ["Coffee", "$14.95"] and text "Coffee $14.95". |
| FR-09 | **`spans`.** The answer is a list of text pieces. Each piece has its text, its box (left, top, right, bottom) in the image as the model sees it, and whether it is handwritten. The prompt asks only what is printed and where: no layout judgments, no receipt rules, no tables. | The request's schema and prompt contain no indent, row or table instructions. |
| FR-10 | **Row building for `spans`, in code.** Pieces that sit on the same printed row form one row, even when the receipt is tilted. Within a row, pieces run left to right, and pieces closer than a small gap join into one cell. Rows run top to bottom. Indent comes from groups of the rows' left edges: the leftmost group is 0, then 1 and 2 (deeper is 2); centered rows and rows printed only at the right are 0. Each row is marked left, center or right aligned. A row's text is its cells joined by single spaces. Only relative positions are used. | On exact drawn boxes, every family builds the expected rows and indents, including `tilted`; the same pieces with each axis scaled differently (pixels or a 0–1000 scale) build identical rows. |
| FR-11 | **Unusable positions.** A piece whose box isn't four numbers with right > left and bottom > top keeps its place after the previous piece, as a row of its own with unknown indent, and the reading notes it. When fewer than half the pieces have usable boxes, rows follow the model's order with unknown indents. | One zero-width box: that piece is its own row, indent unknown, one note; most boxes invalid: rows in answer order, all indents unknown. |
| FR-12 | **Failures, as today, per format.** An invalid answer gets one rescue call in that format's own shape. A blank answer fails with "Model response was blank." A truncated answer is the failure kind `truncated`. | Each case is shown with the fake model server for every format. |
| FR-13 | **Grading: row integrity.** The case's rows are aligned in order to the reading's lines, tolerant of misread characters. The grader counts rows read whole (on one line of their own), split rows (on two lines or more), merged rows (sharing a line with another row), missing rows, extra lines, and rows out of order. A misread character inside a row never counts as a split. Tabs, " \| " and runs of spaces count as one space when matching. | A v7-shaped answer with "$3.95" on its own line counts exactly one split row; two rows on one line count one merged row; a misread "48.85" inside its row counts the row as whole. |
| FR-14 | **Grading: money.** For each printed amount: read exactly anywhere in the reading (Decimal value and sign), and read on its own row's line. Wrong digits are counted apart from missing amounts. | A split row's amount counts as read but not on its row; "48.85" for "49.85" counts one wrong amount. |
| FR-15 | **Grading: indent.** For rows read whole: indent right, wrong or unknown, reported separately for indented rows and edge rows. A format that reports no indent shows "not reported". | A side line read at indent 0 counts one wrong indented row; `v6-text` shows "not reported". |
| FR-16 | **Grading: cells, alignment and handwriting**, for the formats that report them: rows whose cell boundaries match; rows whose alignment is right (`spans`); precision and recall of handwritten flags (`spans`). | A perfect `spans` answer scores all three perfect; one missed handwritten flag lowers recall only. |
| FR-17 | **Diagnostics for positions** (`spans`, reported, never part of passing): the share of pieces with usable boxes; and, after fitting one scale per axis between reported and drawn boxes, the median overlap (intersection over union) of matched pieces. | Exact boxes scaled per axis report overlap 1.0; shifted boxes report less. |
| FR-18 | **Other measures**, as the transcription task does: character error rate, output characters, output tokens when the server reports them, seconds, first-try and final validity, and truncation. | Each appears per case in `results.jsonl`. |
| FR-19 | **A case passes** when no row is split, merged or missing, every amount is read exactly on its own row, and, for formats that report indent, every indent is right. | SC-01 passes; SC-02 to SC-05 each fail on the named count only. |
| FR-20 | **Report.** A "Reading formats" section compares formats per family and per photo condition, with denominators ("3 split rows of 412 rows"), and follows the existing small-sample rule. | The section lists every format run, with counts that add up to the case totals. |
| FR-21 | **`--formats`.** `python -m evals.tasks` and `python -m evals.run` accept `--formats <comma list>` and run each candidate once per listed format, as `<candidate>@<format>`. A dry run prints the cases and model calls per format. A format comparison names no model winner, like the `@no-schema` variants. An unknown format name is refused before any model call. | Dry run with two formats lists both and makes no requests; `--formats nope` exits with the list of known formats. |
| FR-22 | **Summary.** The documents suite records the format with each result, in `run.json` and in `summary.json` as an allowlisted configuration label. Nothing else new enters the summary. | `check_summary` passes with formats; the existing leak tests, with private values seeded into the new fields, still find none in the summary. |
| FR-23 | **Docs.** `docs/evals.md` describes the task, the formats, the measures and how to run them; `evals/README.md` gives the commands; `docs/open-work.md` records the reading change pending these results. | The docs name the task and the four formats, and cite this spec. |

## Invariants, privacy, security and data retention
- **The app reads exactly as today** unless an eval selects a format. With no selection, every vision request, stored
  result, run option (reuse key) and settings file is byte-for-byte what today's code writes. No page or Setting offers a
  format. (Like `Sampling`, the selection is left out of every dump when unset.)
- **Nothing leaves this computer.** The guard's rules are unchanged: loopback LM Studio only, never the family GPU relay.
- **The private corpus is never read by an agent.** The suite is written and tested on synthetic fixtures only. The user
  runs `--formats` on the corpus in their own terminal. Only the allowlisted `summary.json` may be shown to an agent.
- **No real personal data in Git** (FR-06). The user's own receipts go into the private corpus as cases, never into Git.
- **Fonts** are committed with their licence files; no font is downloaded at run time.

## Errors, recovery, duplicates, restart behavior
- A case that fails (invalid answer after the rescue, timeout, truncation, connection) is recorded with its failure kind
  and the run moves on, as today. One format failing doesn't stop the others.
- Each run writes a new run folder; repeating a run never overwrites an earlier one. `--repeat` works with `--formats`.
- Interrupting a run leaves the cases already written; nothing in any library changes (cases run in throwaway libraries).

## Nondeterministic outputs and how they are verified
- **Live model answers** are never specified or asserted. In tests, a fake model server returns fixed answers per format:
  perfect, split row, merged row, misread amount, wrong indent, invalid box, blank, truncated. Each must give exactly
  the expected counts.
- **Drawing is deterministic:** fixed seeds and committed fonts, checked by drawing a case twice and comparing bytes.
- **Timing and token counts** are recorded, never asserted.

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-07 – FR-19 | Fake server returns the exact rows of a `dining/clean` case in each format | Run `receipt_layout` for that case with `--formats v6-text,v7-lines,layout-text,spans` | Every count perfect. Each case passes; `v6-text` indent shows "not reported". |
| SC-02 | FR-13, FR-14, FR-19 | Fake `v7-lines` answer puts "$3.95" on its own line | Run the case | 1 split row; amount read, not on its row; case fails. |
| SC-03 | FR-13, FR-19 | Fake answer prints two rows on one line | Run the case | 1 merged row; case fails. |
| SC-04 | FR-13, FR-14 | Fake answer reads "48.85" for "49.85" inside its row | Run the case | Row whole; 1 wrong amount; CER above 0; case fails. |
| SC-05 | FR-15 | Fake answer gives a side line indent 0 | Run the case | 1 wrong indented row; case fails. |
| SC-06 | FR-10 | Exact drawn boxes of a `tilted` case as a `spans` answer | Build rows | Rows and indents equal the case's answers. |
| SC-07 | FR-10, FR-17 | The SC-06 pieces scaled to a 0–1000 frame, x and y differently | Build rows; run diagnostics | Same rows as SC-06; overlap 1.0 after the per-axis fit. |
| SC-08 | FR-11 | A `spans` answer with one zero-width box; another with most boxes invalid | Build rows | First: that piece its own row, indent unknown, one note. Second: answer order, all indents unknown. |
| SC-09 | FR-08 | A `layout-text` answer with leading tabs (one, two, three) and inner tabs | Parse | Indents 1, 2, 2; cells split at tabs; text joined by single spaces. |
| SC-10 | Invariant | Today's app, no eval selection | Read an image, a scanned PDF and a combined image | Requests, `result.json`, run options and settings byte-identical to captures taken from today's code before the change. |
| SC-11 | FR-21 | Task suite config with one candidate | `--formats v7-lines,spans --dry-run`; then a run; then `--formats nope` | Dry run lists both, no requests. Run results named `<candidate>@v7-lines` and `<candidate>@spans`, no winner. Unknown name refused before any request. |
| SC-12 | FR-21, FR-22 | Synthetic documents corpus, fake server | `python -m evals.run --formats v7-lines,spans` | Each variant runs end to end; `run.json` and `summary.json` carry the format; `check_summary` passes; seeded private values absent from the summary. |
| SC-13 | FR-03, FR-04, FR-05 | Any case | Draw it twice; draw a `tilted` and an `angled` case | Identical PNG bytes; every recorded box encloses its drawn text. |
| SC-14 | FR-12 | Fake server: invalid first `spans` answer, then a valid one; separately a blank answer | Run each | One rescue call in the `spans` shape, then success; blank fails with "Model response was blank." |
| SC-15 | Invariant | Config pointing at a non-loopback server | Any run with `--formats` | Refused as without `--formats`. |

## Out of scope / product decisions requiring approval
Open decisions, each with a recommended default (reply "defaults ok" to take them all):
- **OD-1 Which formats.** Default: all four. `v6-text` is the control that kept rows on your receipts; `v7-lines` is
  today's; `layout-text` and `spans` are the candidates.
- **OD-2 Where the candidates live.** Default: in the app's reading code, off unless an eval selects them. The eval
  design says "call the real code", so the winner later ships as measured.
- **OD-3 Key names in the `spans` answer.** Default: the names grounding-trained models already use (`bbox_2d`,
  `text_content`), keeping the model in its trained format. The row builder doesn't care about names.
- **OD-4 Tables from positions.** Default: not in this feature. `spans` asks for no tables, its table measures show "not
  produced", and the report keeps pay stubs and statements apart from receipts. The reading spec adds tables if `spans`
  wins.
- **OD-5 Fonts.** Default: commit a monospace and a handwriting font with permissive licences under `evals/fonts/`.
- **OD-6 What decides.** Default: the corpus run's money accuracy and review counts for receipts first, the synthetic
  layout measures second, as the explanation. No automatic winner; the choice is recorded in the reading spec.

Risk candidates (domain risk pass). Each becomes an FR or SC only if you accept it:
- **R1 Run time.** Four formats take four times the GPU time. Default: `--formats` takes an explicit list, the dry run
  shows the count, and `--case` and `--tasks` narrow a run as today.
- **R2 Synthetic bias.** Drawn receipts are cleaner than photos, which may favor `spans`. Default: covered by OD-6.
- **R3 Tuning on the test split.** Iterating on the new prompts while looking at corpus failures counts as tuning.
  Default: iterate on synthetic cases and the dev split only, then one test-split run per format at the end, as the
  corpus rules already require.
- **R4 Long answers.** `spans` answers are several times longer, so long receipts may hit the 8,192-token limit. Default:
  keep the same limit for every format and report truncation separately. Strips for long receipts belong to the reading
  spec.
- **R5 Other box conventions.** A model may answer `[x, y, width, height]` or swap axes. Default: the prompt defines the
  order, FR-11 treats impossible boxes as unusable, and FR-17 shows the usable share, so a model with another convention
  is visible in the report.
