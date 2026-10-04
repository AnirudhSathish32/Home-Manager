# Plan: donated document corpus

Status: built 2026-10-03 (uncommitted, migration 057). Replaces the 2026-10-02 plan for automated local validation reports. See "What was built" at the end.

## Goal

Friends and family donate real documents with checked answers. The developer keeps them in a private corpus and runs a deterministic Python eval suite against them on their own computer, using a local model. When the model or a prompt changes, the suite re-runs on the same frozen cases and compares the results with the previous run.

The suite is the one designed in the [model comparison plan](../eval_plan.md): `evals/`, code graders, `results.jsonl`, items A1–A8, and A14 for a private real-document set. This plan adds where those private cases come from, how they are labeled, and how they are protected.

No cloud AI service or AI coding agent ever reads donated documents, answers, or raw results. A coding agent may write and change the suite code, but it tests that code only on the synthetic fixtures in Git.

## Consent

Before sending any document, each donor gets a short written consent in plain language (`docs/donation-consent.md`, to be written). It states:

- **Purpose.** The documents are used only to measure how accurately Home Manager's local models read and extract them.
- **Where they go.** They stay on the developer's computer, on an encrypted volume. They are never uploaded, shared, or shown to a cloud AI service or coding agent.
- **No training.** They are not used to train or fine-tune a model. Any future training use (Laya) needs separate consent.
- **Retention and withdrawal.** The retention period is stated. On request, the donor's cases and any results that mention their case IDs are deleted.
- **Identity.** Each donor gets a pseudonymous ID, such as `d07`, and only that ID appears in the corpus and results.
- **Other people.** Documents can name other people (a store clerk, an employer, a joint account holder). The donor removes documents they are not comfortable sharing.

## Donating from the app

The donor uses the normal app on their own computer. Donation replaces the in-app background validation runner from the earlier plan.

### Check flow

Today's review data can't serve as ground truth:

- `record_corrections` covers only receipts, bills, and income records. Statement lines have no field-level correction trail.
- Records with no issues are verified automatically (`review_source='automatic'`), so no person ever looked at them.
- **Count it** accepts a whole record. It doesn't show that each field was checked.

Corrections alone would mostly label fields that were already wrong. So donation needs an explicit check:

- The original stays beside the fields, following the `app-ux` rule "source beside the record".
- The donor marks each critical field **correct** or **fixed**. For statements, they also confirm that the row list is complete: no missing, extra, or duplicated rows.
- Auto-verified records must be checked again before they can be donated.
- Fields the donor did not check are exported as `unchecked`, never as correct.
- The model's original proposal is saved before the check, so the export can show what the model got wrong.

### Export bundle

**Donate documents** packages the selected checked documents into one zip, using the standard library's `zipfile`:

- `originals/`: the source files as imported.
- `answers.json`: a versioned schema with one entry per document. For each field it holds the value and `checked: true/false`. For statements it holds the rows and a `rows_complete` flag.
- `manifest.json`:
  - Per document: kind (receipt, statement, pay stub), source kind (phone photo, scan, native PDF), and page count.
  - Per bundle: app version, extraction version, the donor's pseudonym, and the model's pre-check proposal.

**Optional redaction.** Before export, the donor can draw boxes over SSNs and full account numbers. The boxes are burned into a redacted copy of the original, and the answers describe the redacted copy.

The donor sends the zip by hand (USB) or over a private channel. This doc recommends wrapping it in an encrypted 7-Zip with the password shared separately. The app makes no network requests for donation.

## Intake

The developer alone does this, outside any AI session:

1. Unpack the bundle into the corpus under the donor's pseudonym.
2. Check the donor's answers a second time against the originals. If the developer disagrees with an answer, they fix it or drop the case. Only cases that pass this check are admitted.
3. Randomly assign each admitted case to **dev** or **test**. Dev cases may be used to tune prompts. Test cases are frozen.
4. Record a `used_for_tuning` flag on each case. Looking at a case's failures to change a prompt counts as tuning. If that happens to a test case, it moves to dev.

## Corpus storage and the AI boundary

- **Location.** Default `P:\EvalCorpus`, outside the repo, on a BitLocker-encrypted volume.
- **Layout.** `donors/<id>/cases/<case_id>/` holds the original, `answers.json`, and `case.json` (split, strata, `used_for_tuning`). Run results go in `results/<run_id>/` inside the corpus, never in the repo.
- **Enforcement.**
  - A `CLAUDE.md` rule lists the path under private financial data.
  - Hard `deny` rules in `.claude/settings.local.json` block Read, Edit, Grep, and Glob on the path. These are deny rules, not ask rules.
  - An auto-mode soft-deny rule forbids reading the corpus through shell commands too.
  - The developer runs the suite in their own terminal, never through an AI agent.
- **Limits.** Deny rules are not a sandbox: a shell command or script could still read the path. The strongest guarantee is to keep the volume locked or unmounted during AI coding sessions.
- **What may leave the corpus.** Only `summary.json` may be shared with an AI agent, for example to get help reading failures. The suite builds it from an allowlisted schema containing counts, error categories, strata, model and configuration labels, and case IDs.
- **What `summary.json` excludes.** Documents, images, text, amounts, dates, merchant or employer names, filenames, paths, account details, document hashes, prompts, model responses, raw errors, and free-text notes.

## Eval suite

Build items A1–A8 and A14 of `eval_plan.md` first, then add:

- **Corpus loader.** It reads `P:\EvalCorpus` from a path given on the command line. It honors the split and refuses to run tuning on test cases.
- **Local-only model guard.**
  - Inference uses a loopback LM Studio server configured for evals.
  - The guard refuses the app's shared-GPU relay and any non-local endpoint, with no fallback.
  - A loopback address alone is not enough if it is a relay.
  - Models must already be installed; the suite makes no web or download requests.
- **Run manifest.** Each run records model ID, identity fingerprint, quantization, runtime, generation settings, prompt and extraction versions, and git SHA. Unknown metadata is marked unknown.
- **Switching models.** A new model means a new run on the same test split. The report compares it with the previous run case by case: cases that started passing and cases that started failing.
- **Graders.** They use deterministic comparisons only, reusing `extraction.verify`.
  - Amounts are compared exactly as Decimal; dates and names are normalized.
  - Rows are matched as a multiset, so legitimate repeated transactions are kept.
  - Unchecked fields are not scored.

### Report

- Accuracy per critical field, always with its denominator, e.g. **2 wrong totals out of 18 checked totals**. Whole-document success counts only fully checked documents.
- Row precision and recall where `rows_complete` is true. Missing, extra, and duplicated rows are counted separately.
- An error taxonomy: wrong digit or scale, wrong sign, date swap or format, field in the wrong place, missing row, extra row, truncation, schema or parse failure.
- Strata by document kind, source kind, and page count, so a weak spot such as phone-photo receipts stays visible instead of being averaged away.
- Processing failures and timing, reported separately from accuracy.
- Uncertainty for small samples. Few or no errors in a small sample does not show that errors are rare.

## Collection targets

Start with these and track gaps as donations arrive:

| Stratum | Target |
|---|---|
| Receipts, phone photos | 40, from at least 15 merchants |
| Receipts, scans or native PDFs | 15 |
| Bank and card statements | 15, from at least 6 issuers, including multi-page ones |
| Pay stubs | 15, from at least 5 employers |

Ask donors for variety, not volume: crumpled or faded receipts, long statements, unusual layouts, non-USD documents.

## Dropped from the earlier plan

- The background validation runner on each user's computer, idle scheduling, and run cancellation.
- Reports generated and sent by friends. Their summary schema and leak tests are reused here for `summary.json`.

## Implementation order

1. **Protect the path now**, before any donation arrives: the `CLAUDE.md` rule, settings deny rules, and the encrypted volume.
2. **Suite on synthetic data:** `eval_plan.md` A2–A7, with fixtures in Git.
3. **Private corpus support:** A14 loader, splits, run manifest, local-only guard, and `summary.json` with leak tests.
4. **App:**
   - A per-field checked state, with a migration that also covers statement lines.
   - The check flow.
   - **Donate documents** export and redaction.
5. **Consent text**, then the first donations.

## Acceptance checks

- The export contains only checked answers. Unchecked fields appear as `unchecked`, and auto-verified records cannot be exported until they are checked again.
- Export tests seed private values into nested outputs, model metadata, errors, and paths. None of them appears in `summary.json`.
- The suite refuses the shared-GPU relay and non-local endpoints, and a missing local model produces an explicit skipped result.
- A run that includes a test case flagged `used_for_tuning` fails.
- Grader tests cover every error category, including repeated legitimate transactions.
- With the corpus deny rules in place, an AI agent's Read and Glob calls on `P:\EvalCorpus` are refused.

## Laya later

These results can show whether Laya or a cheaper extraction route is worth trying and whether a candidate improves accuracy or latency. Training stays outside this plan and requires separate consent from each donor.

## What was built

- **Answers format** (`src/home_manager/core/answers.py`): the critical fields and row columns for each document type, value validation, and `Answers`. The app's export and the eval suite share it.
- **Donation checks** (`src/home_manager/documents/donations.py`, migration 057 `donation_checks`):
  - **Starting a check.** A check begins from the model's normalized proposal, plus the corrections the person already made (merchant, date, employer).
  - **Saving answers.** Typed answers are saved per field (correct, fixed or not checked); money is typed as text and converted exactly.
  - **Page images and redaction.** These are rendered and burned in by a bounded child (`documents/donation_worker.py`), just as the app's readers decode documents. Black boxes are drawn on the page images, so a redacted PDF becomes an image PDF.
  - **The export** is a zip under `<library>/Donations/exports`, downloaded through the app. A check never changes the ledger, review status or filing.
  - **Not donatable yet:** files split into several receipts, and documents combined from several images.
- **Donate documents page** (`app/static/donate.js`, `#/donate`): a list of documents to check and finished checks to donate. A check sits beside its original, with Correct / Fixed / Not checked per field, an editable row list with a "complete" box, and blacking out areas by dragging. Not available in a shared library.
- **Eval suite** (`evals/`, see `evals/README.md`):
  - **The corpus and intake:** `corpus.py`, `intake.py`.
  - **The local-only guard:** `guard.py`. It checks the server, refuses the relay, and blocks every non-loopback connection with a process audit hook.
  - **End-to-end runs through the real pipeline:** `run.py`, each case in a throwaway library.
  - **Deterministic graders:** `graders.py`.
  - **Reports and the allowlisted summary:** `report.py`.
  - **A synthetic corpus generator:** `synthetic.py`.
- **Consent text:** [donation-consent.md](donation-consent.md). Fill in the retention date before using it.
- **Tests:** `tests/test_donations.py`, `tests/test_evals.py`, and `tests/test_donate_browser.py` (opt-in browser).
- **eval_plan.md A4–A8, added 2026-10-03:**
  - a 40-case tagged synthetic corpus, including multi-page text PDFs;
  - `--dry-run`, and `--keep-outputs` to write a private `outputs.jsonl`;
  - per-stage model-call counts and first-try validity;
  - failure kinds and an arithmetic check;
  - a load check per candidate (`load_fail`);
  - a leaderboard, pass^N / pass@N and the score spread.

  The summary's new keys are counts and enums only, and tags appear as a stratum.
- **Sampling override (A2), added 2026-10-03:** an optional `[sampling]` section in `models.toml` sets temperature, seed and schema enforcement for every request of a run. Left out, runs use the app's own temperature of 0.1, and `--repeat` measures consistency. The settings used are in `run.json`, `report.md` and `summary.json`.
