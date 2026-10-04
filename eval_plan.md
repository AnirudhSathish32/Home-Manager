# LLM eval plan: comparing local LM Studio models for Home Manager

Written 2026-09-30. Status 2026-10-03: A1–A17 are all done (see each row in section 5).

- **Documents suite:** `python -m evals.run` reads whole documents end to end. It took the shape of the donated-corpus work
  ([private-reliability-testing.md](docs/private-reliability-testing.md)).
- **Task suite:** `python -m evals.tasks` covers every other model task.

Still open: hand labels to calibrate a judge.

**Terms.**
- **Code-based eval:** a deterministic grader that checks the output in code. No LLM is involved.
- **Prompt-based eval:** an LLM judge scores the output against a rubric.

Anything that can be checked in code is a code-based eval.

**Choosing the best model.** Models are ranked on three things: output quality and accuracy,
reliable structured output, and consistency across runs. Speed matters only when a model is too
slow to use.

## 1. Current state summary

Home Manager has 13 LLM tasks, and all of them go through one transport, `request_completion`
(`src/home_manager/models/model_client.py:193`). Every task asks for strict `json_schema` output and
validates the reply with a Pydantic model. Many tasks then run strong deterministic checks: citations
must be exact quotes, amounts must be supported by the cited lines, and enum values must be allowed.
Those checks are effectively code-based graders already, but they run only inside the app.

The tests use the synthetic `local_model` server (`tests/conftest.py:48-140`), so they check the
plumbing and never measure model quality. There is no eval runner, dataset, golden output, results
store or leaderboard. `docs/milestones.md:80-107` describes an eval design that was never built,
and `docs/milestones.md:11` says accuracy has "only been tested on synthetic data".

The biggest risk to a fair comparison is that nothing measures accuracy against expected answers.
Today a model is "good" if it doesn't crash. The parameters behind any result are also locked:
temperature is hard-wired to 0.1 and no seed is sent (`model_client.py:206`). And the only way to
switch models is to edit the `vision.json` and `reasoning.json` files in the private control
directory.

## 2. LLM call site inventory

All paths are under `src/home_manager/`.

Every task:
- sends `temperature=0.1` and `stream=True` (forced at `models/model_client.py:206`);
- asks for strict `response_format: json_schema` output built from a Pydantic model;
- sends text only, except transcription (#1), which sends base64 PNG images.

| # | Call site | Task | Output type | Current validation | Has eval coverage? |
|---|---|---|---|---|---|
| 1 | `models/vision.py:94` `transcribe`; also each low-text PDF page via `documents/pdf_reader.py:49` | Transcribe a document image or PDF page into text (vision) | JSON `{full_text}`; 8192 max_tokens | `VisionText` (non-blank, ≤1M characters); flags `[unreadable]` markers (:138). No retry. | No (fake server only) |
| 2 | `documents/extraction.py:993` `extract` → `ask` :544 (classify step) | Pick the document kind | JSON `Classification` (enum); 1024 max_tokens | Pydantic. 2 attempts with a correction turn (:555-572). The decision model gives a second, advisory opinion (`ExtractionService.assess`). | No |
| 3 | `documents/extraction.py:1009` (header step) | Read header fields for each kind: receipt, statement, paystub, investment, 1099 | JSON `HEADER_MODELS[kind]`; 2048 max_tokens | Pydantic; `verify` :488-532 (exact citations, `amount_supported` :435, `name_supported` :481); drops a field only if it is in `DROPPABLE` (:88) | No |
| 4 | `documents/extraction.py:1055` (row step, run per chunk) | Read line items, transactions, pay lines, trades and tax boxes | JSON `ROWS[kind]`; 8192 max_tokens | Same as #3. Amount or row problems always fail the extraction. | No (one hand-typed regression test of real-model quirks, `tests/test_extraction.py:211`) |
| 5 | `documents/extraction.py:1061` `identify` | Find the receipt's seller and location | JSON `ReceiptIdentity`; 1024 max_tokens | `name_supported`, `SELLER_SHAPE` :351, `ONLINE_EVIDENCE` :353. A failure is ignored. | No |
| 6 | `documents/extraction.py:1082` `describe_purchase`; also `finance/item_categories.py:53` | Write a purchase description; pick the category, recurrence and per-item categories | JSON `PurchaseDescription`; 3072 max_tokens | `clean_description` :182; the item-category list is used only if its length matches the items. No retry. | No |
| 7 | `documents/extraction.py:1100` `rewards` | Find rewards and offers | JSON `Rewards`; 2048 max_tokens | Drops any amount or link not found in its quote | No |
| 8 | `documents/extraction.py:1118` `payment_terms` | Read contract payment terms | JSON `PaymentTerms`; 2048 max_tokens | `term_records` :1130. A chunk that fails is skipped. | No |
| 9 | `documents/reasoning.py:99` `interpret` | Financial interpretation of a document | JSON `Interpretation`; 8192 max_tokens | `validate_interpretation` :213-242 (exact quotes, every line accounted for). 2 attempts. | No |
| 10 | `documents/reviewer.py:53` `review` | Second-opinion review | JSON `Review` (verdict + findings); 4096 max_tokens | Exact-quote citations; a verdict that contradicts its findings is rejected. No retry. | No |
| 11 | `finance/recurring_scan.py:96` `ask` | Decide whether statement payees are recurring bills | JSON `PayeeAnswers` (Literal enums); 64 tokens per payee + 256 | Pydantic. Out-of-range IDs are dropped; a failed batch is retried next run (:104). | No |
| 12 | `finance/assistant.py:161` `answer`, `:185` `step` | Assistant chat: tool-calling loop simulated through JSON | JSON `Step` (action, tool, `arguments_json`), up to 6 tool calls; 1500 max_tokens | Pydantic and tool-argument models; `checked` :207 flags money figures not in tool results; `sources` :216 | No |
| 13 | `finance/checkin.py:128` `read` | Turn free-text household check-ins into structured data | JSON `Reading`; 5000 max_tokens | `stage` :141 (unknown lots, duplicates, future or unparseable dates) | No |
| 14 | `household/resolver.py:159`, `household/warranty.py:377`, `household/tax_tables.py:332`, `household/tax_figures.py:270` | Web-search agent loops: item names, warranties, tax tables, tax figures | JSON step loop; 1200–2500 max_tokens; at most 8–24 calls | `propose_*` checks (quote must be on the page, numbers must appear in the quotes, brackets ascending) | No (web lookups faked with `FakeWeb`) |

The decision model (`models/decisions.py`, which replaced the in-process Laya on 2026-10-03) answers typed questions with
probabilities: in LM Studio through `/v1/responses` log-probabilities, or on a `/v1/systemone` server. It has its own per-task
eval, `decisions` (`python -m evals.tasks --tasks decisions`), which also reports calibration and a fitted temperature.
Candidates name it with `decision` (plus `decision_provider` and `decision_url` for a non-LM Studio server). See
[decision models](docs/decision-models.md).

**How the model is chosen today.**
- Each role (vision, reasoning, reviewer) has its own JSON file in the control directory
  (`app/manager.py:61-62`, default folder `%LOCALAPPDATA%\HomeManager` at :75).
- The user sets them in the Settings UI (`app/static/index.html:723-740`, `app/api.py:589-619`).
- No environment variable selects the model.
- Every task except transcription and review uses the reasoning model (`app/manager.py:865-1370`).
- Swapping a model is easy in the UI, but impossible from code without editing private files.

**How the app connects.**
- It streams OpenAI-compatible SSE using `http.client`, with no SDK (`models/model_client.py:229`).
- Before every request, `models/residency.py:72` `ensure_loaded` unloads every other model and
  loads the one this request needs, using LM Studio's native `/api/v1/models/load|unload`.
- The app has no `lms` CLI integration.

**Generation params.**
- Temperature is fixed at 0.1.
- `max_tokens` varies by task.
- Strict `json_schema` output is always on.
- The app never sends `top_p`, `seed` or `stop`.

## 3. Gap analysis

### Model swapping
| Item | Status | Evidence |
|---|---|---|
| Single config point to switch models | Partial | Each role has a config object (`VisionConfig` `models/vision.py:39`, `ReasoningConfig` `documents/reasoning.py:23`), and a harness can build those objects in code. In production the model ID lives in private JSON files (`app/manager.py:61-62`), so swapping needs the UI. |
| Run the suite against a list of models in one command | Missing | Not found. I searched for eval, bench and runner scripts; `scripts/` holds only `db_checks.py`. |
| Model identity recorded with results | Partial | `model_identity` (`models/model_client.py:127`) fingerprints the model. `telemetry` (:162) and the `model_runs` table (`library/migrations/010_model_runs.sql:12`) record the model ID, tokens and timings. Prompt versions are stored too (`EXTRACTION_VERSION`, `documents/extraction.py:40`). Not recorded: quantization, context length and the full generation params. |

### Datasets
| Item | Status | Evidence |
|---|---|---|
| Eval dataset for each task | Missing | Tests use inline byte strings (`tests/test_reextraction.py:17`). The project has no `tests/fixtures` or `tests/data`. |
| Golden outputs | Missing | Not found. |
| Edge-case coverage | Missing | Unit tests cover some malformed model output, but no input datasets exist. |
| Versioned and separate from code | Missing | Required by `docs/milestones.md:82` but never built. |

### Code-based evals
| Item | Status | Evidence |
|---|---|---|
| JSON and schema validation for every structured task | Partial (strong in the app) | Every task uses strict `json_schema` plus Pydantic. A `ValidationError` either fails the run or is swallowed (`finance/recurring_scan.py:104`, `identify`), and none of this is counted per model. |
| Task-specific deterministic checks | Partial | `verify`, `validate_interpretation`, `stage`, `checked` and `propose_*` check faithfulness to the source. Nothing compares output with a golden answer: whether the total or category is actually correct is never measured. |
| Failure categories | Partial | The transport classifies errors as `http_N`, timeout, invalid_stream or connection (`models/model_client.py:254-270`). `server_error` (:66-83) recognizes "structured output rejected", "no vision", out of memory and context limit. Parse, schema and wrong-value failures are not separated, and the correction-turn retry (`documents/extraction.py:555-572`) hides first-attempt failures. |

### Prompt-based evals
| Item | Status | Evidence |
|---|---|---|
| Rubrics, deliberately chosen judge, judge calibration, structured judge output | Missing | No judge code found anywhere. |

### Consistency measurement
| Item | Status | Evidence |
|---|---|---|
| Each case run N times | Missing | `docs/milestones.md:105` asks for at least 3 repeat runs, but this is not built. |
| "Passes sometimes" vs "passes reliably" metrics | Missing | Not found. |
| Fixed seed and temperature, documented | Partial | Temperature is fixed at 0.1 but hard-coded with no override, and no seed is sent (`models/model_client.py:206`). No decision on which temperature to evaluate at was found. |

### Fairness of comparison
| Item | Status | Evidence |
|---|---|---|
| Identical prompts, params and datasets | Partial (by construction) | Prompts are Python constants (e.g. `documents/extraction.py:323-385`) shared by all models, and params are forced in one place. A runner that calls the real task functions gets identical prompts for free. |
| Prompts not tuned to one model | Unknown | Prompts use a single system message plus a user message, with no model-specific template handling; LM Studio applies each model's chat template. The prompts may have been iterated against one model (`tests/test_extraction.py:211`, "real model quirks"). |
| Handling of load failures and timeouts | Partial | `server_error` recognizes out-of-memory, context-limit and no-vision errors. `ensure_loaded` waits up to 900 s to load a model (`models/residency.py:102`), and the stream idle timeout is 900 s (`models/model_stream.py`). Not handled: recording these as scored failures, or a per-case time budget. |

### Results and decision-making
| Item | Status | Evidence |
|---|---|---|
| Comparable results store, summary leaderboard, decision rule, regression tracking | Missing | The `model_runs` telemetry records speed and status only. |

### LM Studio specifics
| Item | Status | Evidence |
|---|---|---|
| Targets models through the `model` field or the `lms` CLI | Present | `model` comes from config (`models/model_client.py:206`), and `/v1/models` lists the models. The `lms` CLI isn't needed because the native load API already does this work. |
| One model at a time on the GPU | Present, unconfirmed | `ensure_loaded` unloads the others, then loads, under a process lock (`models/residency.py:27`, :72-102). `core/jobs.py:13` uses one inference worker, and `models/gpu_host.py:130` `Scheduler` runs one request at a time. The API shape is not yet confirmed against the installed LM Studio (`docs/shared-gpu-plan.md:6-9`). |
| Structured output, with and without enforced schemas | Present for enforced schemas, Missing without them | Strict schemas are always on, and nothing can turn enforcement off to test it. |

## 4. Proposed eval architecture

### Principle
- **Call the real code.** The runner calls the app's real task functions, such as
  `extraction.ask`/`extract`, `describe_purchase`, `interpret`, `recurring_scan.ask` and
  `assistant.answer`. It never copies the prompts, so the eval measures exactly what production runs
  and identical prompts across models come for free.
- **Reuse the app's validators.** They become graders, and new graders compare outputs with golden
  answers.
- **No new dependencies.** Everything is plain Python plus the existing Pydantic.
- **Why not a framework.** promptfoo, inspect-ai or DeepEval would add a second prompt and config
  layer that drifts away from the real call path. They would also bring Node or many dependencies,
  and they assume concurrent HTTP calls, which the one-model-at-a-time GPU rules out. A runner of
  about 300 lines is simpler and easier to trust.

### Folder layout
```
evals/
  README.md
  models.toml              # candidate models + sampling + judge (opt-in)
  datasets/<task>/v1/      # cases.jsonl + source files (synthetic, in git)
  graders/code/            # deterministic graders, one module per task family
  graders/judge/           # rubric prompts + calibration labels
  runners/run.py           # python -m evals.runners.run --models a,b --tasks extraction --n 5
  runners/judge.py         # python -m evals.runners.judge --run <run_id> --judge <model_id>
  runners/report.py        # leaderboard + diff vs previous run
  results/<run_id>/        # gitignored; results.jsonl, run.json, judge/<model>.jsonl, report.md
```
- Private real-document datasets stay outside git, at a path you choose (see the open questions).
- Each run gets a throwaway library database and documents folder from `tempfile`, as
  `docs/milestones.md:82` requires. A run never touches the live library.

### Config format (`evals/models.toml`)
```toml
[server]
base_url = "http://127.0.0.1:1234/v1"

[sampling]
temperature = 0.1     # production value
seed = 1234
n_runs = 5
schema_enforced = true

[[candidate]]
id = "<lm studio model key>"
roles = ["reasoning"]

[[candidate]]
id = "<another model key>"
roles = ["reasoning", "vision"]

[judge]
enabled = false       # opt-in; --judge <model_id> on the CLI chooses the judge for a run
```

### Data flow
1. Read a dataset case.
2. Build the role config objects (`ReasoningConfig`, `VisionConfig`) from `models.toml`.
3. Load the candidate with `ensure_loaded`, so only one model is on the GPU at a time.
4. Run the real task function N times. A recording hook on `request_completion` captures every
   attempt's raw output.
5. Run the code graders.
6. Write one line to `results.jsonl` for each case and each run.
7. Only if `--judge <model>` was given: after every candidate has finished, load that judge once and
   score the cases that need judging. Saved runs can be judged later with `runners/judge.py`.
8. `report.py` builds the leaderboard and the diff against the previous run.

### Graders for each call site
Code always comes first. A judge is used only for what code cannot check.

| Task | Code-based graders | Prompt-based (judge, opt-in) | Why |
|---|---|---|---|
| 1 Transcription | JSON and schema valid; character and word error rate against golden text; must-have tokens (total, date, merchant) present; no `[unreadable]` on legible pages | none | Synthetic images come with ground-truth text, so error rate is deterministic |
| 2 Classify | Exact match to the golden kind; confusion matrix | none | Enum |
| 3–4 Header and rows | Schema; `verify` passes; each field matches its golden value (amounts exact as Decimal, dates normalized, names compared ignoring case and spacing); row precision, recall and count; rows sum to the total | none | Every field has a definable correct answer |
| 5 Identify | Seller and location match after normalizing; online flag exact | none | Definable |
| 6 Describe purchase | Category and recurrence exact; per-item category accuracy; `clean_description` and `DESCRIPTION_SHAPE` pass; length limit | Description is useful and specific (1–4) | Description quality is subjective |
| 7 Rewards | Amounts and links match as a set; no amount outside its quote | none | Definable |
| 8 Payment terms | Amount, frequency and currency match; no duplicate terms | none | Definable |
| 9 Interpretation | `validate_interpretation` passes; facts match the golden facts (Decimal) | Reasoning is correct and complete for facts with no golden value (1–4) | Partly subjective |
| 10 Reviewer | Verdict matches the labeled verdict; recall of deliberately planted errors; citations exact | Findings are relevant and non-trivial (1–4) | Planted errors make most of this deterministic |
| 11 Payee scan | Frequency and category exact for each payee; F1 on recurring yes/no | none | Enums |
| 12 Assistant | Step schema; correct tool choice (required and allowed tools); arguments match after normalizing; no forbidden tools; at most 6 calls; `unverified_figures` empty; final numbers match answers computed from the synthetic library | Answer is helpful, direct and correctly hedged; abstains when it should (1–4) | Follows `docs/milestones.md:84-96` |
| 13 Check-in | `stage` accepts; lots, quantities and dates match golden exactly | none | Definable |
| 14 Web agents | Run against pages recorded with `FakeWeb`; proposal matches golden values (months, brackets, figures); call count within budget | none | Recorded pages make it deterministic |

### Judge: opt-in, with the judge chosen by you each time
- **Off by default.** A normal run uses code graders only. Rubric-only dimensions show as
  "not judged" in the report.
- **You choose the judge on every run.** Pass `--judge <model_id>` to `run.py`, or run the standalone
  `python -m evals.runners.judge --run <run_id> --judge <model_id>`. There is no fixed judge in code.
- **Judging is decoupled from candidate runs.** Every run saves its raw outputs, so a finished run
  can be judged, or judged again, by any model later without re-running the candidates.
- **Scores are filed by judge model.** They go in `results/<run_id>/judge/<judge_model>.jsonl`, so
  scores from different judges are never mixed.
- **Self-preference guard.** The runner refuses a judge that is also a candidate in the same run.
  `--allow-self-judge` overrides this, and the report then marks those scores.
- **Structured output.** The judge replies with strict `json_schema` `{score: 1-4, reason, cited_span}`,
  and a code grader parses and validates that reply. A malformed judge reply counts as a judge
  failure, never as a score.
- **Rubrics.** Each rubric file (`graders/judge/<rubric>.md`) defines all four score levels, with one
  example per level.
- **Calibration** is stored separately for each judge model and rubric pair.
  - `--calibrate` scores about 30 cases you have labeled by hand.
  - The bar is agreement within one point on at least 85% of the cases, and Cohen's kappa of at
    least 0.6.
  - In the report, an uncalibrated judge's scores are labeled "uncalibrated" and are left out of the
    decision rule.

### Results schema
Each line of `results.jsonl` is one case for one model on one run:

| Field | Contents |
|---|---|
| `run_id`, `git_sha` | Which eval run, and which code version |
| `dataset_version`, `prompt_version` | Dataset version, and the app's prompt version (e.g. `EXTRACTION_VERSION`) |
| `task`, `case_id`, `case_tags` | Which case; tags such as edge, long or adversarial |
| `model_id`, `model_identity` | The model ID, and its fingerprint from `model_client.model_identity` |
| `quant`, `context_length` | Quantization and context length, from LM Studio |
| `params` | temperature, seed, max_tokens, schema_enforced |
| `run_index` | Which of the N runs this is |
| `attempts` | Raw output and finish_reason of each correction-turn attempt |
| `status` | One of: `ok`, `parse_fail`, `schema_fail`, `validator_fail`, `wrong_value`, `timeout`, `load_fail`, `server_error:<category>` |
| `first_try_valid` | Whether the first attempt was valid before any correction turn |
| `grader_scores` | `{name: value}` for each code grader |
| `latency_s`, `tokens` | Speed and token counts |

- `run.json` holds a full snapshot of the config plus the LM Studio version.
- Judge scores are stored in `judge/<judge_model>.jsonl`, keyed by `run_id`, `case_id`, `model_id`
  and `run_index`.

### Comparison report and decision rule
**`report.md` contents:**
- **Leaderboard,** one row per model:
  - structured reliability: first-attempt schema-valid rate and final valid rate;
  - accuracy: golden-match score for each task, plus a weighted mean;
  - consistency: pass^N (the share of cases that pass in all N runs), pass@N (pass in at least one
    run), and the mean per-case score standard deviation.
- **Per-task breakdown.**
- **Failure categories:** counts for each model.
- **Judge scores,** if any. Each is labeled with its judge model and calibration status.
- **Regression diff:** the cases that went from pass to fail, or fail to pass, since the previous
  run.

**Decision rule:**
1. **Gate.** A model is eligible only if:
   - the final schema-valid rate is at least 99%;
   - it makes zero `wrong_value` errors on money amounts in the critical set;
   - no task has pass^N below X. X is an open question.
2. **Rank** eligible models by weighted accuracy.
3. **Tie-break** (scores within 2 points): use pass^N, then the calibrated judge score.
4. **Usability floor.** Exclude a model whose p95 latency is above Y, a limit you set.

## 5. Action items

| ID | Title | Priority | What to build | Files | Effort | Depends on | Done when |
|---|---|---|---|---|---|---|---|
| A1 | Confirm the LM Studio load API | P0 | Run `residency.ensure_loaded` by hand against the installed LM Studio with two models, and record the real `/api/v1/models` and load/unload response shapes | `docs/shared-gpu-plan.md` (update) | S | – | Two models swap in turn with no out-of-memory error, and the doc's shapes match the real ones. **Done 2026-10-03:** shapes matched with no code change; replies recorded in `docs/shared-gpu-plan.md` |
| A2 | Sampling override | P0 | Optional `temperature`, `seed` and `schema_enforced` on the role configs, defaulting to today's behaviour; `request_completion` uses them instead of forcing 0.1 | `models/model_client.py`, `models/vision.py`, `documents/reasoning.py`, `tests/test_reasoning.py` | S | – | Existing tests pass; a new test shows seed and temperature in the request payload. **Done 2026-10-03:** `Sampling` in `models/vision.py` (base of `VisionConfig`/`ReasoningConfig`), unset fields left out of dumps so saved settings and reuse keys are unchanged; `model_client.apply_sampling`; `schema_enforced=false` moves the schema into the system prompt; evals read `[sampling]` from `models.toml`; `tests/test_sampling.py` |
| A3 | Raw-output recording hook | P0 | Optional callback on the work object that records each attempt's raw text, finish_reason and timings without changing behaviour | `models/model_client.py`, `core/` work object, a test | S | – | A `local_model` test sees both attempts of a correction-turn retry. **Done 2026-10-03:** `model_client.recording(callback)`, a process-wide context manager rather than a work-object field, because the Manager creates its own work objects that an eval cannot reach. Not yet used by `evals/run.py` |
| A4 | Eval skeleton and config | P0 | The `evals/` layout, `models.toml` loader, throwaway library setup, results writer (schema above), `.gitignore` entry for `evals/results/` | `evals/**`, `.gitignore` | M | A2, A3 | `python -m evals.runners.run --dry-run` against the `local_model` fake writes valid result lines. **Done 2026-10-03, in a flat layout** (`evals/run.py`, `python -m evals.run`): `--dry-run` checks server, models and cases and stops; result lines carry tags, per-stage attempt counts, `first_try_valid` and a failure kind; `--keep-outputs` writes raw answers to a private `outputs.jsonl`. Results live under the corpus (`.runtime/` for the synthetic one, ignored by Git) |
| A5 | Extraction dataset v1 | P0 | About 40 synthetic transcriptions (receipts, statements, paystubs), each with golden kind, header and rows. Edge cases: empty, 300-line, ambiguous kind, prompt-injection text, non-USD | `evals/datasets/extraction/v1/` | M | – | Every case validates against a case schema, and the golden values pass the app's own `verify`. **Done 2026-10-03:** `evals/synthetic.py` makes 40 cases from a fixed seed (22 receipts, 6 bank and 5 card statements, 7 pay stubs; 6 text-layer PDFs up to 7 pages), tagged long, multi_page, non_usd, injection, ambiguous_kind, no_items, duplicates, date_format, faded, ytd. Not `verify` itself (it needs the model's cited output); instead a test checks every golden amount is printed and the answers add up the way the app checks |
| A6 | Extraction code graders | P0 | Failure categories, field match (Decimal amounts, normalized dates and names), row precision and recall, sum check, first-try-valid | `evals/graders/code/extraction.py`, `tests/test_eval_graders.py` | M | A4, A5 | Grader unit tests cover every failure category. **Done 2026-10-03** in `evals/graders.py`: field and row grading (built earlier), `failure_kind` (parse, schema, validator, truncated, context, memory, load, timeout, connection, HTTP, stream), `arithmetic` (the model's own sums), `score`; tests in `tests/test_evals.py` |
| A7 | Multi-model run and minimal report | P0 | Loop over candidates (unload, load, wait until ready); record load failures and timeouts as scored results; Markdown leaderboard | `evals/runners/run.py`, `evals/runners/report.py` | M | A1, A4, A6 | One command produces an extraction leaderboard for 3 models. **Done 2026-10-03:** each candidate's models are loaded before its cases, and a load failure is one `load_fail` per case; `report.md` opens with a leaderboard table. No winner is picked (A13) |
| A8 | Consistency metrics | P1 | N runs per case (default 5); pass^N, pass@N, score standard deviation | `evals/runners/report.py` | S | A7 | The leaderboard shows pass^N next to pass@N. **Done 2026-10-03:** `--repeat` (default 1, not 5), pass^N and pass@N, and the score spread (mean per-case standard deviation) in the report and summary |
| A9 | Datasets for the remaining tasks | P1 | Transcription images with ground-truth text (synthetic receipts drawn with PIL); describe, payee scan, check-in, payment terms, rewards and interpretation sets; reviewer cases with planted errors | `evals/datasets/*/v1/` | L | A5 | Every task that has golden outputs has at least 20 cases. **Done 2026-10-03:** `evals/tasks/` (transcription 34, identify 20, describe 24, rewards 24, payment_terms 22, interpretation 22, reviewer 21, payees 20, checkin 22), generated in code from fixed data and seeds, each with a `VERSION`; transcription reuses the synthetic corpus images |
| A10 | Graders for the remaining tasks | P1 | Graders from the table above, reusing `verify`, `validate_interpretation`, `stage` and `propose_*` | `evals/graders/code/*.py` | M | A9 | Every non-judge row of the grader table has a graded run. **Done 2026-10-03** except row 14 (A16): each task module's `grade`; the app's own checks (`validate_interpretation`, `review`, `CheckinService.stage`, `identify`) run inside the real calls. Runner `python -m evals.tasks` |
| A11 | Assistant eval | P1 | A script that seeds a synthetic library; cases with required, allowed and forbidden tools and an answer computed from the library | `evals/datasets/assistant/v1/`, `evals/graders/code/assistant.py` | L | A4 | 25 cases graded on tool, argument and figure checks. **Done 2026-10-03:** `evals/tasks/library.py` seeds three months of bank and card lines; `evals/tasks/assistant.py` has 25 questions whose figures come from calling the tools directly, including a prompt injection and three to decline. Tool arguments are not compared, only tool choice and results (document-search questions are not covered yet) |
| A12 | Opt-in judge and calibration | P1 | Rubrics for describe, interpretation, reviewer and assistant. `--judge <model>` on `run.py`; standalone `runners/judge.py --run <id> --judge <model>` to judge or re-judge saved outputs. Scores filed by judge model; self-judge guard; parsed JSON verdicts; calibration for each judge and rubric pair against 30 hand labels | `evals/graders/judge/**`, `evals/runners/judge.py` | M | A7 | A run without `--judge` makes no judge calls; the same run judged by two models produces two separate score sets; the report shows each judge's calibration status. **Done 2026-10-03:** `evals/judge.py`, `evals/rubrics/`; `--export-labels` makes the hand-label file. No hand labels exist yet, so no judge is calibrated |
| A13 | Decision rule and regression diff | P1 | Code the gate, ranking and tie-break; compare with the previous `run_id` on the same `prompt_version` | `evals/runners/report.py`, `evals/README.md` | S | A8 | The report names a winner, or says no model passes the gate; the diff lists the cases that changed. **Done 2026-10-03:** `evals/decision.py`, `[decision]` in `models.toml` (defaults from the open questions below), in both reports; regression diffs in both |
| A14 | Private real-document set | P1 | Loader for a dataset outside git, at a path you choose, curated and labeled by you; results store case IDs only | `evals/datasets/README.md`, loader in `run.py` | S | A6 | Runs against a path you supply, and no document text is written to the results |
| A15 | Schema-off variant | P2 | Run tasks with `schema_enforced=false` (the prompt describes the schema instead) to measure how well each model keeps to JSON without enforcement | `evals/runners/run.py` | S | A2 | The report shows reliability with and without enforced schemas. **Done 2026-10-03:** `--compare-schema` on `evals.run` and `evals.tasks` adds a `<name>@no-schema` variant per candidate (schema in the system prompt, `model_client.apply_sampling`); both reports get a "Schema enforcement" table; variants are never ranked |
| A16 | Web agent replays | P2 | Recorded pages with `FakeWeb` for the resolver, warranty and tax agents | `evals/datasets/web/` | M | A10 | All four agents are graded offline. **Done 2026-10-03:** `evals/tasks/web.py` (a replay `WebLookup`: recorded synthetic results and pages, no network, no pacing) and task modules `item_lookup` (12), `warranty` (12), `tax_table` (10), `tax_figures` (6), each running the real agent loop in a throwaway library with traps and should-decline cases |
| A17 | Model metadata capture | P2 | Read quantization and context length from LM Studio `/api/v0/models` into `run.json` | `evals/runners/run.py` | S | A4 | Every result row has quantization and context length |

## 6. Recommended build order

1. **First comparison: A1, then A2 and A3, then A4, A5 and A6, then A7.** This is the smallest
   end-to-end slice: one task (extraction: classify, header and rows), code graders only, and
   2–3 reasoning models. It produces the first leaderboard.
2. **Consistency: A8.** Run each case 5 times to tell "passes sometimes" apart from
   "passes reliably".
3. **Breadth: A9 and A10.** Start with transcription, since the vision model is a separate choice,
   then payee scan, check-in and the other tasks.
4. **Decisions: A13 and A14.** Add the decision rule, the regression diff and real documents.
5. **Judge: A12, then A11.** Add the opt-in judge, then the assistant eval.
6. **Optional: A15, A16 and A17.**

## 7. Open questions

1. Which candidate models and quantizations? Should vision and reasoning be compared separately?
   Today they are separate roles.
2. Should judge scores ever count toward picking the winner, or stay advisory? Proposed: they count
   only as a tie-break, and only from a calibrated judge.
3. What failure rates are acceptable? Proposed: schema-valid ≥ 99%, pass^5 ≥ 90%, and zero money
   errors on critical cases.
4. Evaluate at the production temperature of 0.1 with a fixed seed (recommended)? And should there
   also be a temperature 0 reference run?
5. Will production always use enforced schemas, including through the family GPU relay? If yes, A15
   stays P2.
6. Will you build a labeled set of real documents, stored outside git and curated by you? Synthetic
   data can't show how models do on real documents (`docs/milestones.md:11`, :23-25).
7. How should tasks be weighted in the weighted accuracy (extraction vs assistant vs the others)?
8. Is there a latency limit that makes a model unusable?
