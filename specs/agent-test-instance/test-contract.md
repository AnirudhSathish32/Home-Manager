# Test contract: agent-test-instance
Spec sha256: the bundle hash (spec.md + this file) from `gate.py hash --feature agent-test-instance --stage spec`.
It isn't copied here, because writing it into this file would change it.

## Conventions for every scenario

- **Never touch live data, even by metadata.** No test reads, lists or `stat`s `P:\Finances`, `P:\EvalCorpus` or
  the real `%LOCALAPPDATA%\HomeManager`. Every check uses one of these instead:
  - **Decoys:** `tmp_path` folders registered as protected through the instance's protected-path list (FR-04 must
    let tests extend the list). Each decoy holds a canary file `canary.txt` and a `library/inventory.sqlite3`
    placeholder.
  - **Real-path spies:** for the real protected strings (`P:\Finances\x` and the others), an in-process test replaces
    `core.paths.safe_path`, `os.lstat`, `os.scandir` and `open` with spies that **raise** on any argument under a
    real protected root, instead of passing the call through. If a guard is missing, the test fails with no
    filesystem call made.
  - **`LOCALAPPDATA` override:** every subprocess this contract starts sets `LOCALAPPDATA` (and `APPDATA`) to
    `tmp_path/fake-localappdata`, so even a bug that falls back to `default_control_dir()` lands in a decoy.
- **Instance root and port:** tests run the instance at `tmp_path/instance` on a free port, through the FR-15
  overrides, never at `tests/.tmp:8775`, so a running agent instance is never clobbered. The FR-01 defaults are
  checked by reading the command definitions only (SC-01 step 1).
- **Model doubles:**
  - The seed always uses `tests/model_server.py` (`start_model_server`) with the seed's scripted outputs.
  - "LM Studio" in the deterministic tests is a second `start_model_server` instance on a loopback port, passed
    through the FR-03 override. It records every request in `state["requests"]`.
  - The real LM Studio is used only by tests marked `@pytest.mark.lmstudio`. They are skipped by default and run by
    the developer.
- **Network double:** an in-process fixture `no_egress` patches `socket.getaddrinfo` and `socket.create_connection`
  to record every attempted host and refuse any host that isn't loopback. Subprocess tests read the instance log for
  the FR-05 refusal lines instead.
- **Clock:** the seed date is today's date, read once from `session.json` (`seed_date`). Expected dates are computed
  from that value, never from a second `date.today()` call. A test that crosses midnight between reset and assertion
  is retried once.
- **Browser:** Playwright through the existing browser-test fixtures (`tests/conftest.py:97`), Chromium with the
  `msedge` channel, headless. Each browser step collects `pageerror` events, and a step fails on any of them.
- **Test files (new):**
  - `tests/test_agent_instance.py`: lifecycle, seed, guards, verify, in subprocesses
  - `tests/test_agent_guards.py`: in-process path and network guards, with spies
  - `tests/test_agent_instance_browser.py`: marker and routes
  - `tests/test_agent_findings.py`: the findings writer, FR-16
- **Cleanup:** pytest removes `tmp_path`. Each subprocess test runs `stop` in a `finally` block and asserts the port
  is free. No file outside `tmp_path` is written.

## SC-01: first reset, start and verify
Requirement IDs: FR-01, FR-02, FR-07, FR-09, FR-15, I-1, I-2
Environment: subprocess instance at `tmp_path/instance`, free port, fake `LOCALAPPDATA`; "LM Studio" double running
Nondeterministic components: token (format: URL-safe, ≥ 32 chars); `seed_date` = today; ids (presence only)
Initial state: `tmp_path/instance` doesn't exist. `tmp_path/fake-localappdata` is empty.
Actions/checkpoints:
1. Load `tests/environment.json` -> its start, reset and verify commands default to root `tests/.tmp` and port 8775.
   Each accepts the FR-15 overrides. (Static check; nothing runs against `tests/.tmp`.)
2. Run `reset` with the overrides -> exit 0. `instance/control/profiles.json` has exactly one profile, and its
   folder resolves to `instance/library`. `instance/uploads` exists.
3. Run `start` -> within 30 s the port answers. `instance/session.json` has `base_url` (the chosen port), `link`
   (base URL + `#token=`), `seed_date` (today), `model_mode` = `lmstudio`, and `seed_counts` with a nonzero count
   for each section: accounts, transactions, documents, To check items, investment accounts, What If plans,
   household items, recurring bills.
4. Run `verify` -> exit 0. Its output names each check as passed: server, seed manifest, path guard, network guard,
   LM Studio.
Expected final state:
- Database: `instance/library/inventory.sqlite3` counts per section equal `session.json.seed_counts`.
- Filesystem: `fake-localappdata` is still empty (recursive listing = []). Nothing is written outside
  `tmp_path/instance`.
- UI: covered by SC-02.
Failure/retry/restart variants: SC-13 (broken seed), SC-17 (port in use), SC-18 (restart without reset).
Evidence: command exit codes and stdout, `session.json`, SQL count queries, recursive listing of `fake-localappdata`.
Cleanup: `stop`. The port is free.

## SC-02: an agent opens the instance and visits every route
Requirement IDs: FR-07, FR-08, FR-02
Environment: instance from SC-01's steps (shared module-scoped fixture `seeded_instance`); Playwright
Nondeterministic components: none asserted beyond presence
Initial state: seeded instance running
Actions/checkpoints:
1. Open `session.json.link` -> the Today screen loads authenticated (no token prompt), and the "Test data" marker is
   visible.
2. Visit every sidebar route (from `index.html` `.nav-link` hrefs, read at test time) at widths 390, 768 and 1440,
   in light and dark -> on each one, the marker is visible, `[aria-busy='true']` clears within 120 s, there is no
   `pageerror`, and there is no horizontal overflow.
3. On Today, Money › Transactions, Documents, To check, Investments, What If, Inventory and Taxes -> each shows at
   least one seeded row or figure, not its empty state.
Expected final state:
- Database: unchanged (row counts before = after).
- Filesystem: none.
- UI: the marker is on every route and theme. Seeded content is visible.
Failure/retry/restart variants: a reload on any route keeps the marker.
Evidence: screenshot per route/width/theme under `tmp_path/shots`; pageerror list (must be empty).
Cleanup: close the browser.

## SC-03: real protected paths are refused at every path input (in-process, spied)
Requirement IDs: FR-04, I-1
Environment: in-process app (`create_app`) in test mode on `tmp_path`, with the real-path spies and `no_egress`
Nondeterministic components: none
Initial state: a seeded or minimal test-mode library. Settings snapshot S0 (the `GET` of settings, profiles,
sources and families).
Actions/checkpoints: for each input P1–P10 (spec U1) and each root in {`P:\Finances\x`, `P:\EvalCorpus\x`,
`<real LOCALAPPDATA>\HomeManager\x`}, call the API exactly as the screen does ->
1. The response is 4xx, and its message names the folder as protected test-mode data.
2. No spy fired (if one fired, the test fails at that call, with no filesystem access).
3. For P8, refusal holds when either the source or the target is protected.
Expected final state:
- Database: settings, profiles, sources and families equal S0.
- Filesystem: no new file under `tmp_path` except the app log.
- UI: n/a (SC-14 covers screens).
Failure/retry/restart variants: the same path in mixed case, with a trailing slash, with `..` segments
(`P:\Dev\..\Finances`), and as a 8.3 short name if one resolves under a decoy -> all refused.
Evidence: response codes and messages, spy call log (empty).
Cleanup: none beyond pytest.

## SC-04: paths outside the instance root are refused
Requirement IDs: FR-04
Environment: as SC-03, with decoy D (`tmp_path/outside`, not protected, not under the instance root)
Initial state: D contains `canary.txt` with mtime M
Actions/checkpoints:
1. P6 (watched folder) with D -> 4xx, and the message says only test folders may be used.
2. P1, P2, P7 with D -> 4xx.
3. P6 with `instance/uploads` -> 201 (allowed, FR-06 folder).
Expected final state:
- Database: one new source (step 3) and nothing else.
- Filesystem: D's listing is unchanged and `canary.txt`'s mtime is still M.
Evidence: responses, D listing before and after.
Cleanup: none.

## SC-05: no outbound internet in test mode
Requirement IDs: FR-05
Environment: in-process test-mode app with `no_egress`; Playwright for the UI step
Initial state: seeded (it has a crypto investment account and a non-USD amount)
Actions/checkpoints:
1. `POST /api/prices/refresh` -> the response shows the existing "prices unavailable" result, not 5xx.
   `no_egress` recorded `api.coingecko.com` as refused, or no attempt at all.
2. Trigger the ECB rate refresh (Money › USD conversion) -> the existing offline state, not 5xx.
3. Trigger an item lookup (Inventory › identify item) -> the existing lookup-failed state.
4. Trigger a family sync (E3) to a configured `100.64.0.1` member -> refused and logged. No connection attempt is
   recorded.
5. In the browser, on Money, Investments and Inventory -> no `pageerror`.
Expected final state:
- Database: no new rows in price or rate tables.
- Log: one refusal line per attempted non-loopback host.
Failure/retry/restart variants: retrying each action gives the same result, with no crash.
Evidence: `no_egress` record, log lines, responses.
Cleanup: none.

## SC-06: an upload is read by the real LM Studio (opt-in)
Requirement IDs: FR-03, FR-06
Environment: `@pytest.mark.lmstudio`, a subprocess instance, real LM Studio at the default or overridden loopback
address. The developer runs it.
Nondeterministic components: the model output is never compared with values. Tolerances: the document state is in
{read, needs review, failed with a model message} within 300 s; fields are present or marked missing.
Initial state: seeded. LM Studio has a vision and a reasoning model available.
Actions/checkpoints:
1. Copy `instance/uploads/<grocery receipt>` into the library Inbox, open the Inbox and press Read -> the document
   leaves "waiting" within 300 s.
2. Press Record -> a receipt record exists, or the page shows needs-review. No `pageerror`.
Expected final state:
- Database: +1 document, +1 parse run, and +0 or 1 receipt.
- Log: model requests only to the loopback LM Studio address. No refused-egress line.
Evidence: screenshot, log excerpt, SQL counts.
Cleanup: `stop`.

**SC-06d (deterministic twin, always runs):** the same steps with the "LM Studio" double. The double records exactly
the vision and reasoning requests for that document, and the document reaches read.

## SC-07: LM Studio is down
Requirement IDs: FR-03, FR-09
Environment: subprocess instance, the "LM Studio" override pointing at a closed loopback port
Actions/checkpoints:
1. `verify` -> exit 0, and it prints a warning naming the LM Studio address.
2. Upload a receipt and press Read -> the existing model-unavailable state is shown, and the document isn't lost.
3. Seeded screens (SC-02 step 3 subset: Today, Documents) still render.
Expected final state: +1 document with no parse run, or a failed one. Seed counts are otherwise unchanged.
Evidence: verify output, screenshot.
Cleanup: `stop`.

## SC-08: non-loopback model addresses are refused
Requirement IDs: FR-03
Environment: in-process test-mode app with `no_egress`
Actions/checkpoints: for vision, reasoning, reviewer, decision and model computer settings, save
`http://192.168.1.50:1234/v1` and `http://example.invalid/v1` -> 4xx. The setting `GET` equals its value before.
`no_egress` recorded no attempt.
Variants: `http://127.0.0.1:1235/v1` -> accepted (loopback on another port). `http://localhost:1234/v1` -> refused,
the same as in the live app today (`models/vision.py:33` accepts only 127.0.0.1); test mode adds no new accepted
forms (I-2).
Evidence: responses, settings before and after.
Cleanup: none.

## SC-09: a finding is recorded once and seen again
Requirement IDs: FR-10, FR-16
Environment: a copy of `docs/bugs.md` at `tmp_path/bugs.md` (the real file is never written by tests), and a
`session.json` fixture with `seed_date` = 2026-10-17
Initial state: the copy's bytes B0 (the developer's text, no `## Agent findings` section)
Actions/checkpoints:
1. Record a finding (route `#/money/transactions`, symptom "category select does nothing", kind friction, severity
   medium, steps, expected/actual, and a screenshot path under `tmp_path/evidence`) -> the file ends with
   `## Agent findings` and one entry with every FR-10 field, including seed date 2026-10-17.
2. Record the same route and symptom again on another date -> still one entry, now with two "seen" dates.
3. Record a different symptom -> two entries.
Expected final state:
- Filesystem: the prefix of the file up to the section header is byte-identical to B0. Two entries. Both screenshot
  paths exist.
Variants: the section already exists -> entries are added under it and no second header appears. The file has CRLF
line endings -> the prefix is still byte-identical.
Evidence: byte diff of the prefix, the parsed entries.
Cleanup: none.

## SC-10: stop, reset and start return the instance to the seed
Requirement IDs: FR-02, FR-11
Environment: subprocess instance
Initial state: seeded and running. Seed counts C0. An agent change made through the API (one manual transaction
added, one document deleted).
Actions/checkpoints:
1. `stop` -> the port is free within 10 s, and no process from the instance (server, fake model server) is still
   alive (checked by the recorded pids).
2. `reset` -> exit 0. Every file under `instance` deletes without a sharing violation.
3. `start` -> `seed_counts` = C0, the manual transaction is absent, and the deleted document is back.
Expected final state: DB counts = C0, and the values of the named seed rows (Fresh Market groceries budget 250.00,
car loan 6000) are equal to the first seed.
Evidence: counts, pids, port checks.
Cleanup: `stop`.

## SC-11: without test mode, nothing changes (regression)
Requirement IDs: I-2
Environment: in-process app **not** in test mode, control at `tmp_path/plain` (never the real default)
Actions/checkpoints:
1. Open any route in Playwright -> there is no "Test data" marker.
2. P6 with a decoy folder under `tmp_path` that the test-mode list would treat as protected -> accepted (behavior as
   today).
3. Saving a non-loopback model address -> accepted, as today (no connection test run).
4. `https_get` isn't blocked by the app: with `no_egress` patched in, the attempt reaches the socket layer (it is
   recorded, and refused only by the test double).
Expected final state: the existing browser and path tests in `tests/` still pass, unchanged.
Evidence: screenshot, responses, `no_egress` record.
Cleanup: none.

## SC-12: a listener on 8765 triggers the shared-LM-Studio warning
Requirement IDs: FR-12
Environment: subprocess instance. A dummy TCP listener on 127.0.0.1:8765 opened by the test. If 8765 is already in
use (the live app), the test is skipped. It never connects to that port.
Actions/checkpoints: `verify` -> warning, exit 0. Close the listener, then `verify` -> no warning.
Evidence: verify output.
Cleanup: close the listener, `stop`.

## SC-13: one shared seed, and a broken seed step
Requirement IDs: FR-13, FR-02
Environment: static import check plus a subprocess `reset` with a fault-injection setting for tests
(`HM_TEST_SEED_FAIL=<step>`, part of FR-15)
Actions/checkpoints:
1. Static: `ui_shots.py`, the `reset` entry point and the browser-test household fixture import the same seed
   function (AST check of their imports). None of them defines its own household seed.
2. `reset` with `HM_TEST_SEED_FAIL=seed_investments` -> exit ≠ 0, and stderr names `seed_investments`.
3. `start` after the failed reset -> refuses to serve (exit ≠ 0, with the message "seed incomplete, run reset").
4. `reset` without the fault -> exit 0, then `start` succeeds.
Expected final state: after step 4, seed counts equal SC-01's.
Evidence: exit codes, stderr.
Cleanup: `stop`.

## SC-14: profile and restore folders in the UI
Requirement IDs: FR-04 (risk 4)
Environment: in-process test-mode app with the real-path spies; Playwright for screens
Actions/checkpoints:
1. Settings › Profiles › new profile, folder `P:\Finances\y` -> an error message on the form. The profile list is
   unchanged.
2. The same with a decoy outside the instance root -> an error.
3. Settings › Backup › restore, with the source inside `instance` and the target `P:\Finances\y` -> an error.
Expected final state: `profiles.json` is byte-identical to before. No spy fired.
Evidence: screenshots of the errors, a hash of `profiles.json`.
Cleanup: none.

## SC-15: no marker, no finding
Requirement IDs: FR-14, FR-16
Environment: a static stub page with no marker, served on a free port from `tmp_path`, and `tmp_path/bugs.md`
Actions/checkpoints: ask the findings writer to record a finding with a screenshot taken from the stub page ->
refused ("not the test instance"). The screenshot file is deleted.
Expected final state: `bugs.md` is byte-identical. `tmp_path/evidence` is empty.
Evidence: writer exit code, file hash, directory listing.
Cleanup: stop the stub server.

## SC-16: findings carry the seed date
Requirement IDs: FR-10
Covered by SC-09 step 1 (seed date 2026-10-17 from the `session.json` fixture, not today).

## SC-17: the port is already in use
Requirement IDs: FR-01 (errors)
Environment: a dummy listener on the chosen free port
Actions/checkpoints: `start` -> exit ≠ 0 within 10 s, the message names the port, and no `session.json` is written.
It doesn't fall back to another port.
Cleanup: close the listener.

## SC-18: restart without reset keeps the agent's changes
Requirement IDs: FR-01 (restart)
Environment: subprocess instance
Actions/checkpoints: add a manual transaction, `stop`, `start` -> the transaction is still there, `session.json` has
a new token, and `seed_date` is unchanged.
Cleanup: `stop`.

## SC-19: reset while the instance is running
Requirement IDs: FR-11, FR-17, I-3
Environment: subprocess instance running
Actions/checkpoints: `reset` -> refuses with "stop the instance first", exits ≠ 0, and deletes nothing. The instance
still answers `verify`.
Cleanup: `stop`.

## Traceability

| Requirement | Scenarios | Test file / command |
|---|---|---|
| FR-01 | SC-01, SC-17, SC-18 | `tests/test_agent_instance.py` |
| FR-02 | SC-01, SC-02, SC-10, SC-13 | `tests/test_agent_instance.py`, `tests/test_agent_instance_browser.py` |
| FR-03 | SC-06 (opt-in), SC-06d, SC-07, SC-08 | `tests/test_agent_instance.py`, `tests/test_agent_guards.py`; `pytest -m lmstudio` |
| FR-04 | SC-03, SC-04, SC-14 | `tests/test_agent_guards.py`, `tests/test_agent_instance_browser.py` |
| FR-05 | SC-05, SC-11 | `tests/test_agent_guards.py` |
| FR-06 | SC-01, SC-04, SC-06 | `tests/test_agent_instance.py` |
| FR-07 | SC-01, SC-02, SC-18 | `tests/test_agent_instance.py` |
| FR-08 | SC-02, SC-11 | `tests/test_agent_instance_browser.py` |
| FR-09 | SC-01, SC-07, SC-12 | `tests/test_agent_instance.py` |
| FR-10 | SC-09, SC-16 | `tests/test_agent_findings.py` |
| FR-11, FR-17 | SC-10, SC-19 | `tests/test_agent_instance.py` |
| FR-12 | SC-12 | `tests/test_agent_instance.py` |
| FR-13 | SC-13 | `tests/test_agent_instance.py` |
| FR-14 | SC-15 | `tests/test_agent_findings.py` |
| FR-15 | SC-01, SC-13 | `tests/test_agent_instance.py` |
| FR-16 | SC-09, SC-15 | `tests/test_agent_findings.py` |
| FR-18 | none (manual) | Static check that the skill names the FR-16 command and `session.json`. Following it is checked by reviewing one agent run. |
| I-1 | SC-01, SC-03, SC-14 | spies plus the fake `LOCALAPPDATA` |
| I-2 | SC-11 | `tests/test_agent_guards.py`, `tests/test_agent_instance_browser.py` |
| I-3 | SC-19 | `tests/test_agent_instance.py` |

Suggested runs:
- Targeted: `.venv/Scripts/python.exe -m pytest tests/test_agent_instance.py tests/test_agent_guards.py tests/test_agent_findings.py tests/test_agent_instance_browser.py`
- Opt-in: `-m lmstudio`

## Flags (untestable as written, or needing a decision)

- **F1 (resolved by D6, FR-16).** FR-10 and FR-14 describe what an LLM agent does. That can't be checked deterministically. These scenarios
  are testable only if findings go through a tool: a findings writer command that takes the fields, checks the
  marker on the page the screenshot came from, enforces the section, format and duplicate rule, and deletes rejected
  screenshots. The FR-18 skill must use it. Whether the agent
  actually calls it stays a manual check: review one agent run.
- **F2. FR-04 "no read of the target"** is checked with spies (in-process) and decoys (subprocess), not by watching
  real folders. Watching `P:\Finances` would itself break CLAUDE.md.
- **F3 (resolved by D7, FR-17).** Reset while running isn't defined in the spec. SC-19 expects a refusal. 
- **F4. Expected seed counts** are not fixed numbers in the spec. Tests compare the DB with the manifest, check that
  each section is nonzero, and compare two resets. The few named values in SC-10 come from the existing seed text in
  `ui_shots.py` (lines 65 and 115).
