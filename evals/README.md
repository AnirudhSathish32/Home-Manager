# Evals

Tests of how well Home Manager's local models do their jobs, for choosing between models. There are two suites. The design, the donation flow and the corpus's AI boundary are in [docs/evals.md](../docs/evals.md).

- **Documents** (`python -m evals.run`): whole documents read and extracted end to end, over a corpus. The corpus can be synthetic, or the private corpus of donated documents.
- **Tasks** (`python -m evals.tasks`): each of the app's other model tasks on its own, over made-up cases with known answers. See [Per-task evals](#per-task-evals).

**The private corpus is for you alone.** Run these commands in your own terminal, never through an AI coding agent, and keep the corpus on its encrypted drive. The only file meant to leave it is a run's `summary.json`, which holds counts only.

## Try it on synthetic documents first

```powershell
python -m evals.synthetic .runtime\synthetic-corpus            # 40 made-up documents with known answers
python -m evals.run --corpus .runtime\synthetic-corpus --config evals\models.toml --dry-run
python -m evals.run --corpus .runtime\synthetic-corpus --config evals\models.toml
```

Edit `evals\models.toml` to list your LM Studio model IDs. Each candidate pairs a vision model with a reasoning model.

The synthetic corpus is the same every time (a fixed seed): 24 receipts, 6 bank statements, 5 card statements and 7 pay stubs. 36 are images read by the vision model, and 6 are PDFs with a text layer, up to 7 pages long. Each case's tags name the edge it tests, and the report shows results by tag:

| Tag | What it tests |
|---|---|
| `long` | A 30-item receipt and a 300-transaction statement |
| `multi_page` | Statements that run over 2–7 PDF pages |
| `non_usd` | EUR, GBP, JPY (no minor unit) and CAD documents |
| `injection` | A printed line telling the model to report a total of 0.00 |
| `ambiguous_kind` | A paid "INVOICE / RECEIPT" |
| `no_items` | A parking receipt that prints only its total |
| `duplicates` | The same item or charge twice: both are real |
| `date_format` | Dates printed 08/14/2026 or 14 Aug 2026 |
| `faded` | Grey, speckled, slightly tilted print |
| `ytd` | Pay stubs with a year-to-date column |
| `return` | A return and an exchange printed without minus signs: the answers are negative (money back) |

Generate it into an empty folder: `evals.synthetic` adds to a folder and never deletes.

## Taking in donations

```powershell
python -m evals.intake init P:\EvalCorpus
python -m evals.intake add P:\EvalCorpus donation-xxxxxxxxxxxx.zip --donor d07
python -m evals.intake list P:\EvalCorpus --status pending
```

For each pending case, check `answers.json` against `original.*` yourself, and correct `answers.json` by hand where the donor was wrong. Then run `admit CASE_ID`, or `drop CASE_ID --reason ...`. Intake puts each case at random into the **test** split (frozen) or the **dev** split (open for prompt tuning); `--test-share` sets the proportion.

If you look at a test case's failures to change a prompt, run `tuned CASE_ID`: the case moves to dev for good. A run refuses any test case that was used for tuning. If a donor withdraws, `withdraw d07` deletes their cases and their rows in every result, and rebuilds the reports.

## Running

```powershell
python -m evals.run --corpus P:\EvalCorpus --config my-models.toml [--split test|dev|all] [--repeat 3] [--case ID] [--dry-run] [--keep-outputs]
```

`--dry-run` checks the server, the models and the cases, prints how many documents the run would read, and stops without reading any.

What a run does:

- **Reads each case through the app's real pipeline.** Capture, reading and extraction run in a throwaway library that is deleted afterwards, so the eval measures exactly what the app does.
- **Runs only on this computer.**
  - It refuses any server other than `http://127.0.0.1:PORT/v1`.
  - It refuses the shared GPU relay, by its port or by its listing.
  - It checks that every model is listed before the first case.
  - It blocks every network connection except loopback for the whole process.
- **Loads each candidate's models before its cases.** A model that cannot load (out of memory, for example) is recorded as one `load_fail` per case, and the run moves on to the next candidate.
- **Records every model call** (in memory, through `model_client.recording`): how many calls and correction turns each stage needed, and which answers were cut off at the token limit.
- **Measures consistency with `--repeat`.** The app reads at temperature 0.1, so repeating a run shows how consistent each model is.
- **Sampling is the app's own unless `[sampling]` in the config says otherwise:** `temperature`, `seed`, and `schema_enforced = false` to put the JSON schema in the prompt instead of having the server enforce it. The settings used are written to `run.json`, the report and the summary.

Results go to `P:\EvalCorpus\results\<run_id>\`:

- `results.jsonl`: one line per case and repeat, holding the grades, timing, model calls per stage, whether the first answers were valid, and a processing error with its failure kind. Private.
- `outputs.jsonl`, only with `--keep-outputs`: every model answer as text, in order. Private: it holds the documents' contents. `withdraw` removes a donor's rows from it too.
- `run.json`: the code version, the extraction and vision prompt versions, the sampling settings, and each model's server-reported identity and quantization.
- `report.md`: Private, because it lists case IDs. It holds:
  - a leaderboard with one row per candidate: cases passed, mean score, fields wrong, rows found, first answers valid, pass in every and any repeat, score spread, failures and time;
  - accuracy per field ("2 wrong of 18 checked", with a 95% interval) and the error kinds;
  - row precision and recall, and whether the model's own numbers add up;
  - why documents failed;
  - results by document type, source, page count and tag;
  - timing;
  - the cases that newly fail or pass compared with the previous run on the same split.
- `summary.json`: the same counts, built from an allowlist. It has no values, names, text, paths or errors, and any cell with fewer than 3 cases is suppressed. This is the one file you may share, for example to get help reading failures.

## Grading

Every document grade is computed by code; no model judges anything in this suite.

- **Fields:**
  - Only fields the donor marked correct or fixed are scored.
  - Amounts must match exactly, and dates and currencies must match exactly.
  - Names match ignoring case, punctuation, legal suffixes and store numbers.
  - Each mismatch gets one category: `missing`, `invented`, `sign`, `scale`, `digit`, `date_swap`, `year` or `wrong_value`.
- **Rows** are scored only when the donor confirmed the list complete. They match as a multiset, so two identical lattes are two rows and a third is counted as a duplicate.
- **Passing a case:** every checked field is right, and every row is found exactly once.
- **Score:** the share of checked fields and expected rows that came out right. Extra or duplicated rows count against it as missing ones do, and a document that was not processed scores 0.
- **Consistency over repeats:**
  - **pass^N** counts the cases that passed in every repeat, and **pass@N** the cases that passed in at least one.
  - **Score spread** is the mean standard deviation of each case's score across repeats; 0 means the model answered the same way every time.
- **Adds up:** whether the model's own rows reach its subtotal or closing balance, and its pay lines its gross and net pay. It needs no answers.
- **First answers valid:** no correction turn was needed. When the app's checks reject an answer, it asks the model once more, and that hides the first failure.
- **Processing failures** are counted by status and never as wrong fields. The failure kinds are:
  - the model's answer: `parse_fail` (not JSON), `schema_fail` (wrong shape), `validator_fail` (the app's evidence checks), `truncated` (cut off at the token limit);
  - the model server: `context_limit`, `out_of_memory`, `load_fail`, `model_timeout`, `model_connection`, `model_http`, `model_stream`;
  - anything else: `other`.

## Per-task evals

```powershell
python -m evals.tasks --config evals\models.toml --dry-run
python -m evals.tasks --config evals\models.toml [--tasks describe,payees] [--repeat 3] [--limit 5] [--compare-schema] [--judge MODEL]
```

`--compare-schema` (both suites) runs each candidate a second time as `<name>@no-schema`. In that run the server enforces nothing, and the JSON schema is only described in the prompt. The report adds a table comparing the two runs: valid answers, answers that weren't JSON, wrong shape, cut off, and first answers valid. It shows how much a model relies on enforcement. Only the enforced runs are ranked, because the app always enforces the schema.

Each task calls the app's own function for that job (never a copy of its prompt) on made-up cases, and code grades the answer. All cases are synthetic, so you may run these through anyone and share the results. Results go to `.runtime\eval-tasks\<run_id>\`: `run.json`, `results.jsonl` (with each parsed answer) and `report.md`.

| Task | Model | Cases | What is checked |
|---|---|---|---|
| `transcription` | vision | 34 synthetic images | Character and word error rate; the merchant, date and total lines read exactly |
| `identify` | reasoning | 20 receipts | Seller (also from a footer web address) and street; Online for shipped orders; none when only a city is printed |
| `describe` | reasoning | 24 receipts | Category, recurrence (subscriptions, utilities, insurance) and per-item categories against the accepted choices |
| `rewards` | reasoning | 24 receipts | Every printed points, savings, coupon and survey amount or link, and nothing else |
| `payment_terms` | reasoning | 22 lease, insurance and loan excerpts | Each scheduled payment's payee, exact amount and frequency once; no deposits, fees, limits or totals |
| `interpretation` | reasoning | 22 receipts | Type, merchant, date, total and every item with its amount (the app's own citation checks run first) |
| `reviewer` | reasoning | 21 analyses, most with one planted error | The verdict, and that the planted error is pointed at; no findings for a correct analysis |
| `payees` | reasoning | 20 batches of 5 statement payees | Recurring or not, the frequency from the charge dates, and a category |
| `checkin` | reasoning | 22 free-text check-in answers | The staged updates (lot, event, resolved day), and nothing set aside |
| `assistant` | reasoning | 25 questions on a synthetic library | A fitting tool; every figure from a tool result; the right figure; no figure planted by a prompt injection; declining questions the records can't answer |
| `item_lookup` | reasoning | 12 abbreviated receipt lines | The proposed product's name, brand, category and whether it runs out; no proposal for a line no page explains |
| `warranty` | reasoning | 12 owned items | The manufacturer warranty's length (or lifetime), past traps: another model's page, an accessory's shorter cover, an extended plan for sale; none when no page states it |
| `tax_table` | reasoning | 10 state and federal tables | The standard deduction, every bracket and, for federal, the FICA figures exactly, past the prior year's page; none for an unpublished year |
| `decisions` | decision | 40 document classifications and 116 claims, half with a planted wrong value | The document type picked; a true claim supported and a wrong one not (at the app's 0.8 threshold); the report adds calibration error, Brier score and a fitted temperature |

The `decisions` task needs a candidate with a `decision` model (see [decision models](../docs/documents.md "Decision models")); a candidate may
name only a decision model, and then runs only this task. Without one, the default task list leaves it out.

Web agents: `item_lookup`, `warranty` and `tax_table`. They run their real tool loops and checks against recorded, made-up pages (`evals/tasks/web.py`): every search answers with the case's results, pages come from the recording, and nothing goes to the web. Their tax tables are invented, not any year's real ones.

The report has:
- a leaderboard of weighted accuracy and valid answers per candidate;
- the decision;
- one table per task: passed, mean score, every and any repeat, score spread, first answers valid, failure kinds and time;
- the cases that failed, and the cases that changed since the previous run of the same dataset versions.

Bumping a task's `VERSION` starts a fresh comparison.

## Choosing a model

Both reports end in a decision from `evals/decision.py`, set in `[decision]` of the config:

1. **Gate.** A candidate is out if any of these fail:
   - valid answers in at least 99% of runs;
   - no wrong money amounts;
   - every task passed in every repeat for at least 90% of its cases.
2. **Usability floor.** An optional limit on the 95th-percentile time per case.
3. **Rank** by weighted accuracy: the mean score per task, weighted by `[decision.weights]`.
4. **Tie-break.** Candidates within 2 points are ordered by consistency, then by a calibrated judge.

The report names the winner, or says no candidate passes the gate and why.

## The judge (opt-in)

What code cannot check gets a rubric in `evals/rubrics/`: whether a description is useful, whether an interpretation's reasoning is sound, whether review findings are relevant, and whether an assistant answer is helpful and correctly hedged. A run makes no judge calls unless you pass `--judge MODEL`. A finished run can be judged, or judged again, later:

```powershell
python -m evals.judge --run .runtime\eval-tasks\<run_id> --judge MODEL
python -m evals.judge --export-labels --run .runtime\eval-tasks\<run_id> --rubric describe --to describe-labels.jsonl
python -m evals.judge --calibrate describe-labels.jsonl --judge MODEL
```

How judging works:
- Scores are filed per judge (`judge/<model>.jsonl`), so two judges' scores are never mixed.
- A judge that is also a candidate is refused unless you pass `--allow-self-judge`, and its scores are then marked self-judged.
- The judge must reply `{score 1-4, reason, cited_span}`, and `cited_span` must quote the answer it judged. Anything else is a judge failure, never a score.

Calibration:
- Label about 30 exported answers by hand, then run `--calibrate`.
- A judge counts as calibrated for a rubric when it agrees within one point on at least 85% of them and Cohen's kappa is at least 0.6.
- Uncalibrated scores are shown, but never count in the decision.

## Tests

These cover the suites and the app's donation export, using synthetic data only:
- `tests/test_evals.py`: the documents suite;
- `tests/test_eval_tasks.py`: the task suite, the decision rule and the judge;
- `tests/test_donations.py`: the donation export.

The task tests check that a perfect answer passes every case of every task.
