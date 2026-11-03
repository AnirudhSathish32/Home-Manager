# Test suite simplification
Feature: test-suite-simplification

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

## Goal / users / scope / non-goals
- **Goal.** Cut redundant work, maintenance burden and runtime in `tests/` while every distinct regression the suite
  can detect today stays detectable. No target count or percentage.
- **User.** The developer, running `pytest -q` (default) and `pytest -q --browser` (full).
- **Scope.** Test code and test infrastructure only: `tests/*.py`, `tests/conftest.py`, `tests/model_server.py`, and
  `docs/development.md` "Tests" where it describes them.
- **Non-goals.** Any change under `src/`, `evals/` or `scripts/`. New test frameworks or plugins (no xdist). Fixing
  the Linux-only failures (OD-3). Removing the old statement reader or its tests (OD-2). Removing or thinning
  end-to-end/browser tests (user, 2026-11-03: "keep end-to-end tests").

## Existing behavior (verified paths, assumptions, unknowns)
Baseline: one run on 2026-11-03 on this Linux machine (8 cores, Python 3.13.12, pytest 9.1.1, Edge headless), with
`pytest -q --browser -p no:cacheprovider --durations=0 --junitxml=…`. Branch `reorganize-packages` plus the user's
uncommitted changes in `docs/documents.md`, `documents/extraction.py` and `tests/test_layout_consumers.py`.
- **Counts.** 2,451 collected, 1 deselected (`lmstudio`), 2,450 run: **2,379 passed, 68 failed, 23 errors,
  3 skipped**. Wall time **2,413 s (40 min 13 s)**. 1,623 `def test_` definitions in 156 files; parametrization
  makes up the rest.
- **Time split** (`--durations=0` lines ≥ 5 ms): call 1,799 s, setup 334 s, teardown 272 s. The `*_browser.py`
  files and `test_ui_parity.py` take 825 s.
- **Baseline failures are platform failures, not regressions.** The repo is developed on Windows
  (`docs/development.md` "Tests" uses `.venv\Scripts`), and failing tests use Windows-only APIs or line endings:
  `socket.SO_EXCLUSIVEADDRUSE` (28), `subprocess.CREATE_NEW_CONSOLE`, `netstat`, and a `\r\n` expectation in
  `test_agent_findings.py`. Tax-engine `KeyError`s (`test_engine_worksheets` 18, `test_tax_engines` 8) look
  environment-related (Engine 2 extras). Not verified per test; the failing IDs are kept in the baseline junit.
- **Not measured.** Windows runtime, the default (non-browser) run on its own, run-to-run variance, line/branch
  coverage. `.coverage` from 2026-10-22 is stale.

What the survey found (method in parentheses):
- **No copy-paste duplicates.** No two test bodies are identical. Only three pairs share an AST shape once literals are
  normalised (AST hash of every `test_*` body): `test_health.py:113/135`, `test_pdf_layout.py:223/230`,
  `test_table_engine.py:1358/1506`. Each pair's names state a different rule, so they are not redundant.
- **Little mocking or private coupling.** Mock or patch calls in 7 files (at most 10 per file), no
  `assert_called*` or `call_args`, and 4 calls to private functions (`_joint_accounts`, `_headers`, `_coverage`,
  `_apply_correction`).
- **Tests are traced to approved specs.** Names carry SC/FR IDs (for example `test_bill_kinds.py`,
  `test_table_engine.py`). Removing one breaks a contract mapping such as `specs/account-import-pdf/test-contract.md`'s
  FR→command table.
- **Fixed waits are deliberate.** Most `time.sleep` calls sit in polling loops. The fixed ones are
  `test_agent_instance.py:551` (2 s, proves no second capture happens) and `test_gpu_host.py:124,233` (0.1 s, sets
  queue order).
- **Browser launch is cheap.** A headless Edge launch plus a page takes about 0.45 s, measured here. 77 launch sites
  cost at most about 35 s.
- **Teardown has a fixed wait** (measured). `tests/model_server.py` `stop()` calls `server.shutdown()` on a
  `serve_forever` thread with the default 0.5 s poll interval, so each stop takes **0.45 s** (5 of 5 trials). About
  440 teardowns cluster at 0.4–0.5 s. The same pattern is in `test_gpu_host.py:41` (relay, two servers),
  `test_http_server.py:31` and `test_agent_findings.py:214`.
- **Server start is copied around.** The same "bind a free port, start uvicorn in a thread, poll `server.started`"
  helper exists in 12 files: `seed_documents.py`, `test_browser.py` (×4), `test_donate_browser.py`,
  `test_family_browser.py`, `test_employers.py`, `test_share.py`, `test_review_v2_browser.py`,
  `test_shell_browser.py`, `test_document_search_browser.py`, `test_receipt_counting.py`, `test_taxes_v2_browser.py`
  and `test_ui_parity.py`.
- **Slowest tests.** `test_pdf_imports.py::test_sc19_the_picker_endpoint_lists_a_csv_and_all_250_table_pdfs…` (97 s)
  and `test_pdf_imports_browser.py::test_sc19_the_import_picker…` (88 s) each read 250 PDFs, as
  `specs/account-import-pdf` SC-19 / FR-25 requires (OD-1).
- **The old reader is still live code.** `finance/statement_rows.py` and `pdf_import.analyze_legacy` are kept until
  the corpus eval (`docs/open-work.md` "Remove the old statement path"). `evals/run.py:31` and
  `scripts/statement_diagnose.py:31` import them. Their tests (`test_statement_rebuild.py`, 70 cases, 45 s) are not
  obsolete.

## Ranked simplification opportunities
| # | Opportunity | Kind | Expected effect | Confidence |
|---|---|---|---|---|
| 1 | Stop test HTTP servers promptly: a short `poll_interval` on `serve_forever` in `model_server.py`, the gpu_host relay, `test_http_server.py` and `test_agent_findings.py`. | runtime | **Estimated** ~0.4 s × ~440 teardowns ≈ 150–180 s (~7 % of the full run). No test definition or assertion changes. | High |
| 2 | One shared helper in `tests/conftest.py` for "uvicorn app on a free loopback port", replacing the 12 copies. | maintenance | Fewer lines; one place to fix start-up waits. No runtime change expected. | High |
| 3 | Move fixtures that tests import from other test modules (`env`/`no_network`/`opened` from `test_pdf_imports`, `pdf_store`/`make_pdf` from `test_pdf`, `make_receipt` from `test_receipts`, …) into `conftest.py` or a `*_fixtures.py` module. | maintenance | Removes test-to-test coupling. Wide churn, no runtime change. | Medium (OD-4) |
| 4 | The 250-PDF SC-19 API test duplicates the browser test's scale setup. | runtime | Up to ~95 s if reduced. Changes an approved contract scenario. | Low: retained by default (OD-1) |
| 5 | Old-reader tests. | removal | ~45 s and 70 cases once the reader is removed. | Blocked by open-work D4 (OD-2) |

Not opportunities, with the evidence above: duplicate removal (none found), mock reduction (none worth it),
fixed-sleep removal (deliberate), and sharing one browser across tests (≤ 35 s, and it adds cross-test state).

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | A baseline of counts, pass/fail/error IDs, wall time and per-phase durations is captured before any change. | Done (above). The junit file is kept in the session scratchpad for comparison. |
| FR-02 | Test HTTP servers stop without the 0.5 s poll wait, and serve exactly what they served before. | A `start_model_server()` + `stop()` pair takes < 0.1 s in 5 of 5 trials. Every file using `local_model`, `relay` or the other changed servers has the same pass/fail set as the baseline. |
| FR-03 | One shared loopback-server helper replaces the duplicated uvicorn start code. Each test still starts its own server, on its own port and data folder. | No `uvicorn.Server(` outside the helper (plus any copy that can't use it, with the reason in the helper's docstring). The changed browser files have the same pass/fail set as the baseline. |
| FR-04 | A test is removed or merged only with a written note of the distinct regression it could catch and the test that still catches it. | Each removal or merge is listed in the final summary with that mapping. A merge keeps every original assertion. No case runs that wasn't run before. |
| FR-05 | Nothing under `src/`, `evals/` or `scripts/` changes. No `skip`, `skipif`, `xfail` or marker is added. No expected value changes. No end-to-end/browser test is removed. | `git diff --stat` touches only `tests/`, `docs/development.md` and this spec. The browser and parity test counts equal the baseline's. |
| FR-06 | No fixture added or changed is shared mutable state across tests. Server, browser, store and folder stay per test, as now, unless already module-scoped. | No new `scope="module"` or `"session"` fixture holds a store, server, page or mutable dict. |
| FR-07 | Final validation: the same full command as the baseline, on the same machine. | Identical failing and erroring IDs (the platform set), no new failures. The executed-case count differs from 2,450 only by FR-04 removals. Wall time and teardown total are reported as measured, beside the baseline. |
| FR-08 | A closing summary covers: tests removed, consolidated, rewritten or optimised; why each removal added no distinct protection; before/after counts (definitions vs executed cases) and runtime (measured vs estimated); validation results; remaining uncertainty; and expensive tests kept for unique behavior. | Delivered in chat at the end. No new plan document. `docs/development.md` "Tests" updated only if a described helper or practice changes. |

## Invariants, privacy, security and data retention
- No access to `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus` (CLAUDE.md). All tests stay on
  synthetic data in temporary folders. No network beyond loopback.
- The family-hub `no_tailnet` autouse guard and the C-net guard in `test_pdf_imports.py` keep applying to every
  test that has them today.
- Financial assertions (minor units, rounding, dates, reconciliation, ledger health via `assert_ledger_healthy`)
  are kept verbatim wherever a test is touched.

## Errors, recovery, duplicates, restart behavior
- A shorter shutdown poll must not cause connection resets or half-written replies. `docs/development.md` "Windows
  loopback resets" says a reset is a bug. If a changed file shows a reset or a new flake in 3 consecutive runs of that
  file, the change to that server is reverted and reported.
- Each batch is one commit-sized change: revert it whole if its affected files don't match the baseline.

## Nondeterministic outputs and how they are verified
- Runtime is noisy. Before/after times come from the same command and machine, and are reported as single measured
  runs, not as a guaranteed improvement. Per-teardown time (FR-02) is measured directly, 5 trials.

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-02 | Baseline: `stop()` takes 0.45 s. | Start and stop the synthetic model server 5 times. | Each stop < 0.1 s. The server answers its first request exactly as before (existing `local_model` tests pass). |
| SC-02 | FR-02, FR-07 | Baseline pass/fail sets for `test_gpu_host`, `test_http_server`, `test_agent_findings`, and every `local_model` user. | Run those files. | Same pass/fail IDs. Teardown total drops (measured). No `ConnectionResetError` in the output. |
| SC-03 | FR-03, FR-05 | 12 files have their own uvicorn start. | Run the 12 files with `--browser`. | Same pass/fail IDs as the baseline. Same number of browser cases. |
| SC-04 | FR-05, FR-06 | — | `git diff --stat`; grep for added skip/xfail/scope markers. | Only `tests/`, `docs/development.md` and the spec changed. No added markers or shared mutable fixtures. |
| SC-05 | FR-07, FR-08 | All batches done. | One full `pytest -q --browser` run with junit. | 2,450 executed (minus documented FR-04 removals). Failing/erroring IDs identical to the baseline's 91. Wall and phase times reported beside the baseline. |

## Out of scope / product decisions requiring approval
Open decisions (recommended default first; reply "defaults ok" to take them all):
- **OD-1 The 250-PDF SC-19 tests (185 s together).** *Default: keep both unchanged.* The browser test is the
  contract's FR-25 check and an end-to-end test. The API test is the only FR-25 scale check in the default
  (non-browser) run. Reducing it would change an approved scenario, which needs an amendment to
  `account-import-pdf`.
- **OD-2 Old-reader tests.** *Default: keep* until `docs/open-work.md` "Remove the old statement path" is done. They
  protect code still used by the evals and the FR-24 fallback.
- **OD-3 Linux platform failures (91).** *Default: out of scope, and add one line to `docs/open-work.md`* noting that
  these tests assume Windows, without fixing them here. Fixing them would mean changing tests' platform behavior, which
  is a separate change.
- **OD-4 Opportunity 3 (cross-module fixture imports).** *Default: not in this change.* It's wide churn with no
  regression or runtime gain, and conflicts are likely with your uncommitted `tests/test_layout_consumers.py`.
- **OD-5 The three same-shape pairs.** *Default: leave as separate tests.* Their names state different rules, and
  parametrizing them would make a failure harder to read.

Domain risk candidates (accept to turn into FR/SC; otherwise recorded as rejected):
- **R1 Teardown race.** A test that relied on the 0.5 s slack, for example a background thread still writing into
  `tmp_path`, could turn flaky. *Default: accept, as the 3-run check in "Errors, recovery".*
- **R2 Port reuse.** A helper that frees ports faster could hand a port that is still in TIME_WAIT to the next test.
  *Default: accept. The helper keeps binding port 0 per test, as the copies do now.*
- **R3 Measurement noise.** One run each side can mislead. *Default: accept. Report single runs labelled "measured,
  n=1", plus the direct per-stop measurement for FR-02.*
