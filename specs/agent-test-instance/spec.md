# Agent test instance: a synthetic Home Manager for Playwright agents
Feature: agent-test-instance

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: no earlier spec. The baseline is the harness config `tests/environment.json` (untracked), the synthetic seed in
`.claude/skills/ui-redesign/scripts/ui_shots.py` and the fake model server `tests/model_server.py`, cited below.

## Goal / users / scope / non-goals

**Goal.** AI agents drive Home Manager through Playwright the way a person would. They look for workflow friction
and broken features, and they only ever see synthetic data. One command starts a long-running app with a full
synthetic household. Agents explore it, and they report what they find. Nothing they do can reach the live library or
the donated corpus.

**Users.**
1. The developer, who starts, resets and stops the instance and triages findings.
2. Agent sessions (Claude Code with the `playwright-cli` skill, or Playwright scripts) that browse the instance and
   write findings.

**In scope.**
- A dedicated, resettable test instance: its own settings folder and library under `tests/.tmp`, on its own port.
- Seeding it with the full synthetic household that `ui_shots.py` builds today.
- Pointing the instance's vision and reasoning models at the developer's local LM Studio after seeding (decision D1).
- A set of synthetic documents that agents can drop into the Inbox or upload.
- Guards that work while the app runs as the test instance: it refuses protected paths and makes no outbound
  internet calls.
- Writing agent findings into `docs/bugs.md` in a fixed format (decision D4).

**Non-goals.**
- Any change to how the live app (default settings folder, port 8765) behaves.
- Fixing the friction or bugs that agents find. Each fix is its own spec or `debug-issue`.
- CI, scheduled agent runs, or multi-agent orchestration.
- An "empty library" first-run preset (D2: the full household only).
- Replacing the pytest browser tests. They keep their own temporary instances.

## Existing behavior (verified paths, assumptions, unknowns)

**Verified**
- `src/home_manager/__main__.py:28` accepts `--control-dir`. Without it, the app uses `default_control_dir()`
  (`app/manager.py:84`), which on Windows is `%LOCALAPPDATA%\HomeManager`, the live settings and the pointer to the
  live library.
- `__main__.py:36-37` generates a fresh random session token on every start and prints the `#token=` link to
  stdout only.
- `core/paths.py:62-63` already lets a library sit inside the checkout only under `tests/.tmp`, for this harness.
- `tests/environment.json`:
  - It starts `python -m home_manager --control-dir tests/.tmp/control --port 8775` and logs to
    `tests/.tmp/server.log`.
  - `reset` creates an **empty** `test` profile whose library is `tests/.tmp/library`.
  - It lists `P:\Finances`, `P:\EvalCorpus` and `%LOCALAPPDATA%\HomeManager` as protected.
  - It sets `models.mode = deterministic_fixture` and `live_inference_opt_in = false`. This spec changes the model
    setting (D1).
- `tests/.tmp/` is gitignored (`.gitignore:13`).
- `ui_shots.py` `seed()` (lines 40-86) builds a full household on a temporary, in-process server. It covers:
  - accounts, a month of spending, budgets, statements, a car and its loan, recurring bills and subscriptions, rules
  - this year's taxes, investments of every kind, two What If plans
  - read and recorded documents and To check items (`tests/seed_documents.py`), household items, processing
    failures, and settings (a reviewer and a Donate check)

  The seeded documents get their fields from the fake model server's scripted outputs (`tests/model_server.py`,
  `seed_documents._read_and_record`). Seeded dates are relative to `date.today()`. The temporary folder is deleted on
  exit, so nothing persists.
- `.playwright/cli.config.json` uses Chromium through the `msedge` channel.
- The app has outbound internet callers:
  - `finance/fx.py:31` (ECB rates)
  - `finance/prices.py:28` (CoinGecko)
  - `models/web_lookup.py:24-25` (Brave Search, Open Food Facts)
- The LM Studio default is `http://127.0.0.1:1234/v1` (`models/vision.py:65`). `models/residency.py` loads and
  unloads models through LM Studio's API before each request.
- `docs/bugs.md` is free-form prose that the developer writes, with no structure.
- `evals/synthetic.py` generates a 44-case synthetic document corpus (`docs/evals.md`).

**Assumptions**
- A1. The seed helpers in `tests/` can run against a long-running instance's manager as well as an in-process one.
  The plan must confirm this.
- A2. LM Studio runs on the same machine and serves the same models the developer uses for real documents.

**Resolved from the code while designing tests (2026-10-17)**
- U1. Path inputs. Each one goes through `core/paths.py` `local_absolute` / `validate_managed` / `separate_folder`.
  The plan must recheck this list against the code.

  | Ref | Screen / action | API | Manager |
  |---|---|---|---|
  | P1 | Settings › Library folder | `PUT /api/settings` | `configure` (`manager.py:356`) |
  | P2 | Settings › Profiles › new profile | `POST /api/profiles` | `create_profile` (`:430`) |
  | P3 | Settings › Profiles › new family | family create | `create_family` (`:503`) |
  | P4 | Family › invite a member | `POST /api/families/{id}/members/{mid}/invites` | `invite_member` (`:581`) |
  | P5 | Join a family | `POST /api/family-membership` | `join_family` (`:605`) |
  | P6 | Processing › watched folder | `POST /api/sources` | `add_source` (`:1264`) |
  | P7 | Settings › Backup › back up | `POST /api/backups` | `start_backup` (`:2167`) |
  | P8 | Settings › Backup › restore (source and target) | `POST /api/restores` | `start_restore` (`:2180`) |
  | P9 | Settings › Sharing › export | share export | `start_share_export` (`:2241`) |
  | P10 | Open a shared copy | `POST /api/sessions` | `start_session` (`:2278`) |
  | P11 | Startup / profile switch | none (reads `profiles.json`) | `migrate_settings` (`:376`), `open_library` (`:403`, `:411`) |

- U2. Outbound callers.
  - E1: `models/web_lookup.py` `https_get`, used by `finance/fx.py` (ECB), `finance/prices.py` (CoinGecko), and
    Brave / Open Food Facts lookups.
  - E2: `models/model_client.py` to each configured model address: vision, reasoning, reviewer, decision, and
    model computer (`PUT /api/model-computer`).
  - E3: `app/family_client.py` to a family computer over Tailscale.
  - `models/gpu_host.py` is a separate subcommand, and the test instance never starts it.

## Functional requirements

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | One `start` command brings up the test instance at `http://127.0.0.1:8775`. Its settings folder is `tests/.tmp/control` and its library is `tests/.tmp/library`. | After `start`, `verify` passes. `tests/.tmp/control/profiles.json` names only `tests/.tmp/library`. No file under `%LOCALAPPDATA%\HomeManager` changes. |
| FR-02 | `reset` rebuilds the instance from scratch with the full synthetic household (the `ui_shots.py` seed, every section). The seeded documents are read and recorded with the fake model server, so the seed is the same on every run. | After `reset` then `start`, every top-level screen shows seeded content. Seed counts (accounts, documents, To check items, investments, plans, items) match the manifest written by FR-07. Two resets on the same date give the same counts and values. |
| FR-03 | After seeding, the instance's vision and reasoning models point at the local LM Studio (default `http://127.0.0.1:1234/v1`, overridable). In test mode, a non-loopback address is refused for every model setting (E2: vision, reasoning, reviewer, decision, model computer). | Settings › Models shows the LM Studio address. Trying to save a non-loopback address in any model setting shows an error, and the setting does not change. |
| FR-04 | In test mode, the app refuses any path inside `P:\Finances`, `P:\EvalCorpus`, `%LOCALAPPDATA%\HomeManager` or the live library recorded there, wherever the UI or API accepts a path (U1). It refuses before it opens, lists or reads anything. It also refuses paths outside `tests/.tmp` and the synthetic upload folder (FR-06). | For each path input, submitting a protected path shows a clear refusal. The response is a 4xx. The log shows no read of the target. |
| FR-05 | In test mode, no outbound internet call is made through E1 or E3 (U2). Exchange rates, crypto prices and item lookups each show the app's existing offline or unavailable state instead of crashing. Loopback calls to LM Studio are allowed. | With the network guard on, opening Money/USD conversion, Investments (crypto) and an item lookup shows the offline state with no page error. Any attempted call to a non-loopback host is refused and logged. |
| FR-06 | A gitignored folder `tests/.tmp/uploads` holds synthetic documents for agents to add: receipts of each kind, a pay stub, a bank statement PDF, a bill, a refund and a non-receipt (offer letter). They come from `evals/synthetic.py` and the seed's drawn receipts. | After `reset`, the folder contains at least one file of each listed kind. No file comes from outside the repo's generators. |
| FR-07 | `start` writes `tests/.tmp/session.json` with the base URL, the session token link, the seed date, the seed counts and the model mode, so an agent can open the app without reading stdout. | The file exists after `start`, and opening its link in Playwright lands on the authenticated Today screen. |
| FR-08 | Every page of the test instance shows a persistent "Test data" marker, so neither the developer nor an agent can mistake it for the live app. Agents confirm the marker before acting. | The marker is visible on every route at 390/768/1440 widths in light and dark. The live app (no test mode) never shows it. |
| FR-09 | `verify` checks four things: the server answers, the seed manifest matches the database, the path and network guards are active, and LM Studio is reachable. LM Studio being unreachable is a warning, not a failure. | `verify` exits 0 on a healthy instance. It exits non-zero, naming the failed check, when the seed is missing or a guard is off. With LM Studio down it prints a warning and exits 0. |
| FR-10 | Agents append findings to a dedicated `## Agent findings` section at the end of `docs/bugs.md`. Each finding gives: date; seed date (from `session.json`); agent/session; route; steps; expected vs. actual; kind (bug, friction or console error); severity; and evidence (a screenshot path under `tests/.tmp/evidence`). Before adding a finding, the agent checks whether the same route and symptom are already listed. If so, it adds a "seen again" date and does not add a duplicate. Agents never edit text above that section. | After an agent run, the developer's text above the section is unchanged byte for byte (diff). New entries follow the format. Running the same scenario twice gives one entry with two dates. |
| FR-11 | `stop` ends the app server and any helper processes (fake model server). No process keeps the port or `tests/.tmp` files locked. | After `stop`, port 8775 is free and `reset` can delete `tests/.tmp` without a "file in use" error. |
| FR-12 | Risk 1: `verify` and `start` warn when something is listening on port 8765 (the live app may be sharing LM Studio). The test instance's docs say not to run agent uploads while the live app is scanning. | With a listener on 8765, `verify` prints the shared-LM-Studio warning and still exits 0. With 8765 free, there is no warning. |
| FR-13 | Risk 2: the synthetic household seed lives in one shared module. `ui_shots.py`, the browser tests that seed a household, and this instance's `reset` all call it, so none of them seeds its own copy. | `ui_shots.py` and `reset` import the same seed entry point. A deliberately broken seed step makes `reset` fail by naming that step, and the FR-02 manifest check catches count drift. |
| FR-14 | Risk 5: before every screenshot and every finding, the agent checks that the FR-08 "Test data" marker is visible. A screenshot without the marker is deleted and no finding is recorded from it. | An agent pointed at a page without the marker (the live app, or a stub page) records no finding and leaves no screenshot in `tests/.tmp/evidence`. |
| FR-15 | For tests, `start`, `reset`, `verify` and `stop` accept an override for the instance root, the port and the LM Studio address. They also accept a test-only seed fault setting and extra protected paths. The defaults stay `tests/.tmp`, 8775 and `http://127.0.0.1:1234/v1`. | The commands run against a `tmp_path` root on a free port without touching `tests/.tmp`. With no overrides, they use the defaults. |
| FR-16 | One findings command is the only way agents record findings (D6). It takes the FR-10 fields and a screenshot and checks the FR-14 marker on the page the screenshot came from. It writes only under `## Agent findings` in its target file (default `docs/bugs.md`), and it enforces the format and the duplicate rule. If it refuses a finding, it deletes the screenshot and leaves the file unchanged. | SC-09 and SC-15 pass against a copy of `bugs.md`. Its text above the section stays byte-identical. |
| FR-17 | `reset` refuses while the instance is running and deletes nothing (D7). | SC-19. |
| FR-18 | A tracked project skill in `.claude/skills/` describes the agent workflow: read `session.json`, confirm the marker, explore, and record findings only through FR-16 (D9). | The skill exists, names the FR-16 command, and has agents use only `session.json.base_url`. Whether an agent follows it is checked by reviewing one run (manual). |

## Invariants, privacy, security and data retention
- **I-1.** The test instance never reads, lists, writes or opens anything under `P:\Finances`, `P:\EvalCorpus` or
  `%LOCALAPPDATA%\HomeManager` (CLAUDE.md). The guards in FR-04 and FR-05 enforce this in the app. Agent instructions
  alone are not enough.
- **I-2.** Test mode is opt-in, and only the test instance's start command turns it on. The live app's behavior
  does not change when test mode is off.
- **I-3.** `reset` deletes only `tests/.tmp`. It resolves that path and checks it is inside the checkout before
  deleting (as `environment.json` already does).
- **I-4.** Data leaving the machine: none. LM Studio is on loopback. The synthetic documents, screenshots and logs
  stay in `tests/.tmp` (gitignored). Findings in `docs/bugs.md` describe synthetic data only.
- **I-5.** Agents use only the test base URL from `session.json`. They never open `127.0.0.1:8765` (the live app).
- **I-6.** The session token is random per start. It lives only in `tests/.tmp/session.json` and `server.log` and is
  never committed.

## Errors, recovery, duplicates, restart behavior
- **Seeding fails** (A1 drift, a helper error): `reset` exits non-zero with the failing seed step, and `start`
  refuses to serve a half-seeded library. The developer runs `reset` again after fixing the cause.
- **Port 8775 already in use:** `start` fails with a clear message and does not pick another port silently.
- **LM Studio is down or has no model loaded:** the instance still starts, and seeded data is unaffected. New
  uploads fail with the app's existing model-unavailable state. Agents should report that state as a finding only if
  the UI handles it badly.
- **Restart without reset:** `start` reuses the existing library and everything agents changed. Only `reset` returns
  the instance to the seed.
- **The server crashes mid-run:** `verify` fails. The agent records a crash finding with the `server.log` tail, and
  the developer resets.
- **Duplicate findings:** handled by FR-10's check for the same route and symptom.

## Nondeterministic outputs and how they are verified
- **Seed values:** deterministic. The fake model server supplies fixed outputs, and dates are relative to the seed
  date in `session.json`. Seed checks compare counts and named values against the manifest.
- **LM Studio readings of uploads:** never checked against exact values. Checks look only at the state: the
  document reaches read, needs-review or failed within a timeout, the page has no `pageerror`, and fields are present
  or explicitly marked missing.
- **Session token, timestamps and generated ids:** checked for presence and format only.
- **Agent findings:** checked for format and placement (FR-10), never for content.

## Scenarios (expand into test-contract.md with design-tests for stateful features)
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-01, FR-02, FR-07, FR-09, FR-15 | No instance root. `LOCALAPPDATA` points at an empty decoy folder (the real one is never listed). | `reset`, `start`, `verify` | `verify` exits 0. `session.json` has the URL, token, seed date and counts. The DB counts match the manifest. The decoy `LOCALAPPDATA` is still empty. |
| SC-02 | FR-07, FR-08 | Instance running | Playwright opens the `session.json` link and visits every sidebar route | Each route renders seeded content with the "Test data" marker. No `pageerror`. |
| SC-03 | FR-04 | Instance running | In Settings, set the library folder, a watched folder and a restore source to `P:\Finances\x` (one per path input from U1) | Each is refused with a message and a 4xx. Settings don't change. The log shows no read of the target. |
| SC-04 | FR-04 | Instance running | Set a watched folder to a folder outside `tests/.tmp`, e.g. `C:\Temp\x` | Refused, the same as SC-03. |
| SC-05 | FR-05 | Instance running, network guard on | Open USD conversion, crypto prices and an item lookup | The offline or unavailable state shows. No page error. The log shows the refused outbound host. |
| SC-06 | FR-03, FR-06 | Instance running, LM Studio up | Drop `tests/.tmp/uploads/<grocery receipt>` into the Inbox and press Read, then Record | The document reaches read or needs-review within the timeout. LM Studio's request log shows the request. No other host is contacted. |
| SC-07 | FR-03, FR-09 | Instance running, LM Studio stopped | `verify`, then upload a receipt | `verify` warns and exits 0. The document shows the existing model-unavailable state. Seeded screens are unaffected. |
| SC-08 | FR-03 | Instance running | Set the model address to a non-loopback URL | Refused, and the setting doesn't change. |
| SC-09 | FR-10 | `docs/bugs.md` with the developer's text | The agent records a finding, then records the same route and symptom again | One new entry in `## Agent findings` with two dates and a screenshot under `tests/.tmp/evidence`. The text above the section is unchanged byte for byte. |
| SC-10 | FR-02, FR-11 | Instance running with agent changes | `stop`, `reset`, `start` | Port freed, `tests/.tmp` recreated, and the agent's changes are gone. The seed counts match the manifest again. |
| SC-11 | I-2 | Live app started normally (no test mode) | Open any route | No "Test data" marker. Path and network behavior are unchanged from today (regression). |
| SC-12 | FR-12 | Instance running. A dummy listener on 127.0.0.1:8765 (not the live app) | `verify` | Prints the shared-LM-Studio warning and exits 0. After the listener stops, `verify` gives no warning. |
| SC-13 | FR-13, FR-02 | Clean checkout | Run `ui_shots.py --routes home` and `reset`. Then make one seed step raise and run `reset` again | Both runs seed through the same module. The broken run exits non-zero naming the step, and `start` refuses to serve the half-seeded library. |
| SC-14 | FR-04 (risk 4) | Instance running | Add a profile, and restore into a profile, with a folder at `P:\Finances\y` and another at `C:\Temp\y` | Both are refused. `profiles.json` is unchanged. |
| SC-15 | FR-14, FR-10 | A stub page without the marker, served on a spare port | An agent is pointed at it and asked to record a finding | No finding is added to `docs/bugs.md` and no screenshot is left in `tests/.tmp/evidence`. |
| SC-16 | FR-10 (risk 3) | Instance seeded on a known date | The agent records a finding | The entry contains the seed date from `session.json`. |
| SC-17 | FR-01 | The chosen port is already taken | `start` | Fails, naming the port. No `session.json` is written, and it doesn't fall back to another port. |
| SC-18 | FR-01 | Seeded, with an agent change | `stop`, `start` (no reset) | The change is kept. There is a new token, and the seed date is unchanged. |
| SC-19 | FR-11, FR-17, I-3 | Instance running | `reset` | Refused ("stop the instance first"). Nothing is deleted, and the instance still verifies. (Decision F3.) |

This feature is stateful, so I recommend running `design-tests` to expand these scenarios into `test-contract.md`
before approval.

## Out of scope / product decisions requiring approval

**Decisions recorded (2026-10-17, from intake)**
- **D1. Models: real LM Studio.** Uploads during agent runs go to the local LM Studio. The seed still uses the fake
  model server so seeded state is repeatable. (The developer chose this over the recommended fake-by-default.)
- **D2. Seed: full household** (the `ui_shots.py` seed). No empty first-run preset.
- **D3. Guards:** refuse protected paths and outbound internet in test mode, enforced in the app.
- **D4. Findings go straight into `docs/bugs.md`.** (The developer chose this over a separate run report.) FR-10
  confines agents to their own section.

**Domain risk candidates.** All five defaults were accepted on 2026-10-17 (D5). They are built into FR-10 (seed
date), FR-04/U1 (profile folders), FR-12, FR-13 and FR-14, and into SC-12 to SC-16.
1. **The test instance shares LM Studio with the live app.** `models/residency.py` unloads and loads models before
   each request. An agent run could evict a model that a live scan on port 8765 is using, or the other way round, so
   the live scan slows down or fails.
   *Default:* document "don't run both at once". `verify` warns if something is listening on 8765. No code lock.
2. **The seed is tied to test helpers.** `ui_shots.py` imports private helpers from `tests/` (`test_reconcile_tools`,
   `test_extraction`, `test_receipts`). A test refactor can silently break the instance.
   *Default:* move the seed into one shared module that `ui_shots.py`, the browser tests and this instance all call.
   FR-02's manifest check catches drift.
3. **Findings depend on the date.** The seed is relative to `date.today()`. On the 1st of a month, "this month" has
   almost no spending, and agents may report false "empty screen" friction.
   *Default:* findings record the seed date (from `session.json`). No clock freezing, because that would touch app
   code everywhere.
4. **Agents can take destructive actions in the UI.** Agents may delete documents, restore backups or change
   profiles. Inside the instance that is fine, because `reset` restores it. But a "restore" or "add profile" action
   could create a second profile whose folder lies outside `tests/.tmp`.
   *Default:* FR-04 covers profile folders too. Accepting this candidate adds it to U1 explicitly.
5. **Findings or screenshots could hold live data.** If an agent opens the live app by mistake (port 8765),
   screenshots and `bugs.md` would contain real financial data.
   *Default:* agents must check the FR-08 marker before every screenshot. A screenshot without the marker is
   discarded and not recorded.

**Decisions recorded (2026-10-17, after design-tests; all defaults accepted)**
- **D6 (F1).** Agents record findings only through the findings command, FR-16.
- **D7 (F3).** `reset` refuses while the instance is running, FR-17.
- **D8 (P1).** The seed stays relative to today. There is no `--seed-date`, and findings record the seed date.
- **D9 (P2).** The agent workflow is a tracked project skill, FR-18.
