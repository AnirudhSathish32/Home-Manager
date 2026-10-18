# Agent test instance: implementation plan
Spec: specs/agent-test-instance/spec.md (+ test-contract.md)
Spec sha256: b2834186f1660324f9d1dea1e61814598ef5ebcbe397aee2cef77c8efbdf5e76

<!-- Approval lives in approvals/<slug>.json, bound to this file's hash. No Status line.
     Execution progress goes in plans/<slug>/progress.yaml, never in this file. -->

## Verified repository integration points

| What | Where | Why it matters |
|---|---|---|
| App factory | `app/api.py:580` `create_app(control, token, port, limits)`; it builds `Manager(control or default_control_dir(), limits)` at `:588` | The harness passes an explicit control dir and token, so `default_control_dir()` (`manager.py:84`, reads `LOCALAPPDATA`) is never reached. |
| Auth and CSP | `api.py:597-635`: Host must be `127.0.0.1:{port}`, Bearer token on `/api/`, strict CSP | The marker must be a same-origin element with no inline script or style. Agents authenticate with the `#token=` link. |
| Settings the shell loads | `api.py:675` `GET /api/settings` → `Manager.settings()` (`manager.py:321`); `static/app.js:152` `loadSettings()` | The marker flag and guard status are added to this payload. No new endpoint. |
| Every path input | `core/paths.py:33` `local_absolute`, called by `validate_managed` (`:54`) and `separate_folder` (`:75`), and directly at `manager.py:605` and `:2278`. Callers: `manager.py:356, 376, 403, 411, 430, 503, 581, 605, 1264, 2167, 2180-2181, 2241, 2278` | All of P1–P11 (spec U1) pass through `local_absolute`, so **one guard there covers every path input**. `safe_path` `lstat`s each part of the path, so the guard must run **before** it. Family folders are opened before validation (`manager.py:401, :498`, `family_hub.py:88`), but only from `profiles.json` entries that were validated when created. |
| Checkout overlap | `separate_folder` (`paths.py:75-83`) refuses any folder overlapping the checkout (`reserved_paths`). Only `validate_managed` exempts `tests/.tmp` (`:62-63`). The seed's watched folder goes through it (`tests/seed_processing.py:39` → `manager.add_source` → `manager.py:1264`) | On the default root `tests/.tmp` (inside the checkout), the `processing` seed step, SC-04 step 3 (watching `uploads`) and backups into the root would all be refused. The sandbox root needs the same exemption here (A1). |
| Model addresses | `models/vision.py:25` `endpoint_url` (127.0.0.1 or a tailnet host). `VisionConfig.local_only` (`:70`) falls back to `tailnet=True` for a tailnet host (`:77-78`) and is reused by `ReasoningConfig`, `ReviewerConfig` (`documents/reviewer.py:15`) and `DecisionConfig` (`models/decisions.py:69-73`). `ModelComputer.gpu_host_url` (`vision.py:104`) uses `tailnet=True` | Every model address is already loopback-or-tailnet, and LAN or public hosts are refused today. Besides that, `configure_model` (`manager.py:1182-1185`, `is_remote` at `model_client.py:54`) already refuses any host but `127.0.0.1` for vision, reasoning, reviewer and decision, tailnet included. So the only setting that accepts a tailnet address today is the model computer (`PUT /api/model-computer`, `ModelComputer.tailnet_only`, `vision.py:102`), plus saved run options read back through `VisionConfig`. Test mode only has to refuse the tailnet branch, in one function. Tests show the change on the model computer with a tailnet address (`100.64.0.1`, `*.ts.net`). |
| Outbound callers | E1 `models/web_lookup.py:50` `https_get` (fx via `manager.rate_fetch`, prices via `manager.price_fetch` at `manager.py:121-122`, `WebLookup` for items, warranty and tax tables); E2 `models/model_client.py:96` `_connection`; E3 `app/family_client.py:52` | All three end in `socket.getaddrinfo` / `socket.connect`. A process-wide audit hook catches all of them and any future caller. They already catch `OSError` / `gaierror` (`web_lookup.py:42,74`, `model_client.py:155,384,407`, `family_client.py:72,82,187`), so a refusal shows each feature's existing offline state. |
| Family hub listener | `app/family_hub.py:108` binds `tailnet_address()` (imported by name from `models/http_server.py:39`, so it must be wrapped in `family_hub`); `tests/conftest.py:113` already stubs it to `None` for tests | In test mode `tailnet_address` returns `None`, so the hub stays off ("Tailscale isn't running"). |
| Household seed | `.claude/skills/ui-redesign/scripts/ui_shots.py:40-154` (`seed`, `seed_today`, `seed_money`, `seed_settings`). It calls `tests/seed_documents.py`, `seed_items.py`, `seed_processing.py`, `seed_wealth.py`, `seed_taxes.py`, `conftest.inbox_scan`, and `test_reconcile_tools.add/receipt` | This moves into one shared module (FR-13). No browser test seeds the *whole* household today; they seed sections (see Risks R2). |
| Fake models | `tests/model_server.py:18` `start_model_server()` | The seed's models, and the "LM Studio" double in deterministic tests. |
| Synthetic uploads | `evals/synthetic.py:198` `documents()`, `:262` `draw`, `:280` `write_pdf` | Receipts (grocery, cafe/diner, fuel-type), statements (png/pdf), card statements, paystubs, return receipts (`:241`) and bills (`:244`). There is **no offer letter**, so the harness draws one with `draw()`. Note: case `:210` is a deliberate prompt-injection receipt. It is included as an upload so agents also see how the app handles it. |
| Harness config | `tests/environment.json` (untracked); `.gitignore:13` ignores `tests/.tmp/` | The commands are rewritten to call the new harness script. |
| Pytest config | `pyproject.toml:42-45` (`addopts = "-ra"`, no markers registered, no marker filter); `browser-test` extra = `playwright==1.63.0` | Register the `lmstudio` marker **and deselect it by default**: `addopts = "-ra -m \"not lmstudio\""`. A later `-m lmstudio` on the command line replaces it (pytest keeps the last `-m`), which is the contract's opt-in. |
| Log files | `core/logs.py:15,35` `configure(control)` writes the app loggers to `<control>/logs/home-manager.log` | The sandbox's refusal lines land there, not in `server.log` (stdout/stderr only). Tests grep this file. |
| Gate tool | `gate.py` resolves files from the cwd. Use `--root "P:\Dev Environment\Projects\Home Manager"` | Check commands below pass `--root`. |

## Architecture, contracts, data flow and decisions

**A1. `core/sandbox.py` (new): process-wide test mode, off by default.**
- `activate(root, allowed=(...), protected=(...))`, `deactivate()` (for in-process tests), `active()`, `status()`
  → `{"paths": bool, "egress": bool}`.
- `status()` **probes** each guard instead of reporting a stored flag, so `verify` can't pass on a guard that isn't
  working:
  - `paths` is true only if `check_path(<first protected root>\probe)` raises `PathError`. The check is lexical, so the
    probe touches nothing.
  - `egress` is true only if the audit hook is installed and `socket.getaddrinfo("egress-probe.invalid", 443)` raises
    the sandbox's `gaierror` with the sandbox's own message. The hook fires on the audit event before any lookup, so
    nothing leaves the machine. The probe skips the refusal log line, so `verify` doesn't fill the log.
  - While inactive, `status()` returns `{"paths": false, "egress": false}` without probing.
- Nothing in `home_manager` reads `HM_TEST_*` environment variables. Only `scripts/test_instance.py` calls
  `activate`. That is how I-2 holds: the live launcher (`__main__.py`) never activates test mode.
- **Path check** `check_path(value) -> None`, called first thing in `local_absolute`:
  - Normalizes lexically only (`os.path.normcase(os.path.abspath(...))`), with no filesystem call.
  - Under a protected root: `PathError("Test instance: <root> holds real data and is off limits.")`.
  - Not under an allowed root (`<root>` and `<root>/uploads`): `PathError("Test instance: only folders inside
    <root> can be used.")`.
  - The live library (FR-04) is covered by the allowlist. The harness never reads the live settings to find it.
  - Mixed case, trailing separators and `..` are normalized lexically. 8.3 short names and links aren't under the
    allowed root lexically, so they are refused without being touched. `safe_path` then still rejects links inside
    the allowed root.
  - The protected list is the three spec roots plus extras passed by the harness (tests' decoys). `%LOCALAPPDATA%`
    is expanded from the environment at activation.
- **Checkout exemption:** `separate_folder` skips the checkout overlap for a path under the sandbox root while
  `sandbox.active()`. That matches what `validate_managed` already allows for `tests/.tmp`. The overlap checks against
  the control folder, the open library and the `others` list still apply. With the sandbox inactive, nothing changes.
- **Egress hook:** `sys.addaudithook` is installed once, at the first `activate`, and is a no-op while inactive.
  - On `socket.getaddrinfo` for a host that isn't loopback (`localhost`, `127.0.0.0/8`, `::1`), it raises
    `socket.gaierror`. Host `None` and `""` (passive lookups for a bind, no network) are let through, the same as
    the `no_egress` double.
  - On `socket.connect` to a non-loopback address, it raises `ConnectionRefusedError`.
  - Each refusal logs `log.warning("test instance: refused outbound host=%s", host)` once per host per activation.
    `activate()` clears the set of hosts already logged, so in-process tests that each activate the sandbox see their
    own log lines regardless of test order.
  - Binds aren't touched.
  - **Scope: this process only.** Audit hooks don't reach child processes. The app's children are the OpenTax Node
    runner (`finance/engines/opentax.py:195-199`, telemetry turned off through `OPENTAX_TELEMETRY=0` / `DO_NOT_TRACK=1`
    at `:190`), the Tax-Calculator runner (`taxcalc.py:214`), the PDF reader (`receipt_service.py:229`) and
    `tailscale ip` (`http_server.py:49`, not called in test mode; see "Hub"). None of them makes network calls today.
    `docs/development.md` "Agent test instance" says so, and a new child that needs the network must be checked
    separately. "Catches any future caller" (D-P2) means callers inside the server process.
  - **Scope: TCP and name lookups.** The hook handles `socket.getaddrinfo` and `socket.connect`. It doesn't handle
    `socket.sendto` (UDP without a connect), and nothing in the app calls that today. A future UDP caller would need
    the hook to handle `socket.sendto` too.
- **Model addresses:** `endpoint_url(..., tailnet=True)` raises `ValueError("Test instance: only
  http://127.0.0.1:PORT/v1 model servers.")` while `sandbox.active()`. In practice this changes only the model
  computer (`family_gpu`) and saved run options read back through `VisionConfig`. Vision, reasoning, reviewer and
  decision already refuse tailnet addresses in both modes (`configure_model`, `manager.py:1183`).
- **Hub:** the check is inline at the call site, `family_hub.py:108`, keeping the existing loopback branch:
  `address = "127.0.0.1" if self.loopback else (None if sandbox.active() else tailnet_address())`. Nothing is wrapped or patched at `activate()`, so pytest's monkeypatch of `tailnet_address`
  (`conftest.py:108-113`) can't undo or hide it.

**A2. `Manager.settings()`** gains `"test_instance": sandbox.status() if sandbox.active() else None`.

**A3. Marker (FR-08).**
- `index.html` has no shell header: the shell is `aside.sidebar` (`index.html:50`). Under 820 px it is a top bar whose
  contents sit in the collapsed `#sidebar-sheet` (`:53-54`), and the collapsed desktop sidebar hides `.nav-label`
  text. So the hidden `#test-instance-marker` element ("Test data", with an `aria-label`) is a **direct child of
  `aside.sidebar`, right after `.brand` and outside `#sidebar-sheet`**. Its text is not a `.nav-label`, and in the
  collapsed sidebar it keeps a short visible label ("Test"), so it is visible at 390/768/1440 and in both sidebar
  states without opening anything. SL-04's browser test checks all three widths and the collapsed sidebar.
- `app.js loadSettings()` toggles `body.test-instance` and unhides the marker when `settings.test_instance`.
- Style lives in the app stylesheet using design tokens (CLAUDE.md: load `ui-ux-pro-max` first, CSP-safe, no
  framework).
- Selector contract for agents and tests: `#test-instance-marker` visible.

**A4. `tests/seed_household.py` (new, FR-13).**
- It holds `seed(manager, root, model, fail_step=None)` plus `seed_today`, `seed_money` and `seed_settings`, moved
  from `ui_shots.py` with one change: `seed` no longer calls `manager.configure(...)` (`ui_shots.py:43`). It seeds the
  library the caller already opened, and raises if none is open. Otherwise `configure` would move the open `test`
  profile's folder to `<root>/managed` (`manager.py:361-362`), which breaks FR-01. `ui_shots.py` calls
  `manager.configure(str(root / "managed"))` itself before `seed`, so its behavior is unchanged.
- Folders the seed creates (the watched `scanner` folder) go under the `root` it is given.
- `seed` runs named steps in order: `seed_ledger`, `seed_today`, `seed_money`, `seed_taxes`, `seed_investments`,
  `seed_plans`, `seed_documents`, `seed_review_items`, `seed_items`, `seed_processing`, `seed_settings`. These are
  the names SC-13 uses (`HM_TEST_SEED_FAIL=seed_investments`). It raises `SeedStepFailed(step)` around each one.
- `fail_step` raises inside the named step (SC-13). An unknown step name raises before anything is seeded.
- It returns `(ids, manifest)`. The manifest has a count per section and named values (groceries budget `250.00`,
  car loan `6000`).
- The manifest also records `taxes_seeded`, the return value of `seed_tax_year` (`tests/seed_taxes.py:22`). That's
  false when Engine 1 doesn't cover this year (`opentax.YEARS`, now `{2025, 2026}`). Tests that expect seeded taxes
  read this flag and skip with `seed_taxes.this_year_covered`'s reason instead of failing as if the page were broken.
- `ui_shots.py` imports `seed` from it and keeps no seed of its own.

**A5. `scripts/test_instance.py` (new): the harness CLI.**

Subcommands: `reset`, `start`, `serve` (internal), `stop`, `verify`, `finding`. They are configured by flags or
environment, with defaults in brackets:

| Setting | Flag | Environment | Default |
|---|---|---|---|
| Instance root | `--root` | `HM_TEST_ROOT` | `tests/.tmp` |
| Port | `--port` | `HM_TEST_PORT` | `8775` |
| LM Studio address | `--lmstudio` | `HM_TEST_LMSTUDIO` | `http://127.0.0.1:1234/v1` |
| Vision model ID (`reset` only) | `--vision-model` | `HM_TEST_VISION_MODEL` | the one kept from the previous instance, else empty |
| Reasoning model ID (`reset` only) | `--reasoning-model` | `HM_TEST_REASONING_MODEL` | the one kept from the previous instance, else empty |
| Seed step to break (tests only) | none | `HM_TEST_SEED_FAIL` | none |
| Make `serve` exit before uvicorn starts (tests only) | none | `HM_TEST_SERVE_FAIL` | none |
| Extra protected paths | none | `HM_TEST_PROTECTED` (`os.pathsep`-separated) | none |

**Root check (I-1).** Before any filesystem call, `reset`, `start`, `serve`, `stop`, `verify` and `finding` refuse
(exit 2, "Test instance root overlaps protected data: <root>") a root that overlaps a protected root in either
direction: inside it, equal to it, or containing it. The protected roots are the three spec roots plus
`HM_TEST_PROTECTED`. The check is the same lexical one as `sandbox.check_path` (shared helper in `core/sandbox.py`),
so a mistyped `--root P:\Finances\agent` never creates, deletes or writes anything there.

**Sentinel check.** After the root check, and before any filesystem write or delete, `start`, `serve`, `stop`,
`verify` and `finding` refuse (exit 2, "not a test instance folder: <root>") a root that doesn't hold the sentinel
`<root>/.hm-test-instance`. The one exception is a root that resolves exactly to `<checkout>/tests/.tmp`, the same
exception `reset` makes (I-3). Only `reset` creates the sentinel. So a mistyped `--root C:\Users\<me>\proj` never
loses `evidence/<file>` to a refused `finding`, or `session.json`, `server.pid` or `stop.request` to `stop`.

Instance layout:
- `<root>/.hm-test-instance` is a sentinel. `reset` deletes a root only if (a) it is absent, (b) it holds the
  sentinel, or (c) it resolves exactly to `<checkout>/tests/.tmp` (I-3's check, which also covers the folder the old
  `environment.json` reset created without a sentinel). Otherwise it refuses.
- `<root>/control/`, `<root>/library/`, `<root>/uploads/` and `<root>/evidence/`.
- `<root>/seed.json` holds the manifest and seed date.
- `<root>/.seed-incomplete` exists while seeding.
- `<root>/server.pid` is JSON `{"pid", "created"}`. `created` is the process creation time from
  `GetProcessTimes` (through `ctypes`; no new dependency). **`serve` writes it itself** (`os.getpid()` and its own
  creation time), after uvicorn has started and before `session.json`. `start` never records `Popen().pid`, because
  `.venv/Scripts/python.exe` is the venv redirector and that pid is the launcher's, not the server's.
- `<root>/server.log` and `<root>/session.json`.

**Process identity.** A pid file names "our server" only if a process with that pid exists **and** its creation
time equals `created`. A pid that doesn't match is treated as stale: the file is removed, and nothing is signalled.
`reset`, `start` and `stop` all use this one check.

`reset`:
0. Runs the root check above.
1. Refuses if `server.pid` names our live server (by the identity check) or the port is bound (FR-17, SC-19). The
   two refusals have different messages: "stop the instance first" for our server, and "port <port> is in use by
   another program; stop it or pass --port" when the port is bound but `server.pid` names no live server of ours.
2. Checks the root against the deletion rule above (I-3). Before deleting, it reads the model IDs from the old
   `<root>/control` vision and reasoning settings files, if they are there, so a reset keeps the developer's model
   choice. It deletes everything in the root except `evidence/`, which is kept so that screenshots cited in
   `docs/bugs.md` stay valid. Then it writes the sentinel.
3. Writes `.seed-incomplete` and activates the sandbox. It builds the Manager with
   `ScanLimits(stability_seconds=0)`, as `ui_shots.py:176` does, so seeded captures don't wait 1 s each
   (`scanner.py:22,113`). It creates a profile named "Test" with its library at `<root>/library` through
   `create_profile("Test", ...)` and opens it with `switch_profile(id)` (`manager.py:419-441`). `configure` isn't
   used, because with no active profile it would name the profile "My profile" (`manager.py:363-364`).
4. Starts an in-process server on an ephemeral port with `start_model_server()` and runs `seed_household.seed` on the
   open library.
5. Waits for the inference queue to drain (`busy("inference")` false, up to 120 s), because `configure_model`
   refuses while model work runs (`manager.py:1187`). The seed reads synchronously today
   (`seed_documents.py:31-32`), so this wait is a guard against future changes. Then it points every model setting
   the seed touched at the LM Studio address. It never contacts LM Studio, so seeded
   settings don't depend on what LM Studio has loaded.
   - Vision and reasoning: `configure_vision` / `configure_reasoning` with the address and the model IDs. The IDs
     come from `--vision-model` / `--reasoning-model`, else the ones kept in step 2, else they stay empty.
   - Reviewer: the seed sets a chat reviewer on the fake model server's temporary port (`ui_shots.py:91`), which is
     gone once `reset` ends. `configure_reviewer` keeps `provider="chat"` (so Settings › Independent checks still
     shows a seeded reviewer) and points it at the LM Studio address with the reasoning model ID. If that ID is empty,
     the reviewer is set to `provider="off"`.
   - Decision: the seed never sets it (default `provider="off"`), so nothing changes.
   - The model IDs go into `seed.json` and `session.json` (`models`), and `verify` warns when the vision or reasoning
     ID is empty ("uploads won't be read until you pick models in Settings › Models").
6. Waits for the Manager's queues to drain (`busy()` false, up to 120 s; for example, the text-index backfill that
   `open_library` can queue, `manager.py:1150`). Then it calls `manager.close()` (`manager.py:2316`), which releases
   the `DirectoryLock` and closes the DB. Only then does it compute the manifest, from a fresh read-only connection, so
   `seed.json` and the template describe a settled library. A queue still busy after 120 s is a seed failure
   (`seed step failed: settle`).
7. Writes the uploads (A6) and `seed.json`, then removes `.seed-incomplete`.

On `SeedStepFailed` it exits 1, prints `seed step failed: <step>` to stderr and keeps `.seed-incomplete`.

`start`:
1. Refuses if `.seed-incomplete` exists or `seed.json` is missing ("seed incomplete, run reset").
2. Refuses if the port can't be bound: a bind test with `SO_EXCLUSIVEADDRUSE`, never a connection (SC-17).
3. Prints the shared-LM-Studio warning if 127.0.0.1:8765 isn't bindable (FR-12, the same check as `verify`). A
   warning only, so `start` goes on.
4. Spawns `serve` detached (`CREATE_NEW_PROCESS_GROUP`, output to `server.log`) and waits up to 30 s for both
   `server.pid` and `session.json`.
5. If the spawned process exits early, or 30 s pass without both files, `start` fails:
   - It prints "server did not start" and the last 20 lines of `server.log`.
   - If `server.pid` was written, it ends that process through the identity check and the `stop` path. Otherwise it
     terminates the spawned process tree (`taskkill /T /F /PID <Popen pid>`; that pid is only the launcher's, but `/T`
     includes its child).
   - It removes any `session.json` and `server.pid`, and exits 1.

`serve`:
1. Activates the sandbox and configures logs into `<root>/control` (app log: `<root>/control/logs/home-manager.log`).
2. Generates a token and builds `create_app(control, token, port)`.
3. Once uvicorn has started, writes `server.pid` (its own pid and creation time), then `session.json` (`base_url`,
   `link`, `seed_date`, `seed_counts`, `model_mode: "lmstudio"`, `lmstudio`, `models`).
4. Watches for `<root>/stop.request` once a second (a thread). When it appears, it sets uvicorn's
   `server.should_exit`, so shutdown is clean and doesn't depend on which console `stop` runs from.

`stop`:
- Only if the identity check passes: writes `<root>/stop.request`, waits up to 10 s for the process to exit, then
  terminates that pid. `CTRL_BREAK_EVENT` isn't used: it only reaches a process group on the caller's own console,
  and `stop` often runs from a different shell than `start`.
- Removes `server.pid`, `session.json` and `stop.request`, and confirms the port is bindable. SC-10's "port free
  within 10 s" is measured from when `stop` returns.

`verify` prints one line per check and exits 1 if any required check fails:
- The server answers `GET /` (required).
- Seed (required). `seed.json` exists, there is no `.seed-incomplete`, and the DB opens read-only (`mode=ro`)
  with every manifest table present. With `--fresh`, each manifest count must also equal the DB count. Tests and the
  check right after `reset` use `--fresh`. Agents run `verify` without it, because their own changes (SC-18) move the
  counts. *This is how the plan reads FR-09's "the seed manifest matches the database" (decision D-P3).*
- `settings.test_instance` is present and both guards are true (required). The values come from the probing
  `status()` (A1). A server started without the sandbox, such as the plain launcher on this control folder, reports
  `test_instance: null` and fails with "guards: test mode is off".
- The seed check fails with "seed: incomplete, run reset" when `.seed-incomplete` exists or `seed.json` is missing.
- LM Studio `GET {lmstudio}/models` within 3 s (a warning if it fails).
- Vision and reasoning model IDs are set (a warning if either is empty).
- Port 8765 is bindable (a warning if it isn't: the shared-LM-Studio note, FR-12).

`finding` is covered in A7.

**A6. Uploads (FR-06).**
- `reset` writes one document per kind from `evals.synthetic.documents()`:
  - grocery receipt, dining receipt, fuel receipt (parking/fuel case)
  - bank statement PNG and PDF, card statement
  - pay stub, bill
  - return/refund receipt, and the prompt-injection receipt
- It adds `offer-letter.png`, drawn with `draw()` from fixed lines.
- File names say the kind (`grocery-receipt.png`, …). `uploads/README.txt` lists them.

**A7. The findings command (FR-10, FR-14, FR-16).**

```
python scripts/test_instance.py finding --url PAGE_URL --route R --symptom S --kind bug|friction|console-error
    --severity low|medium|high --steps S --expected E --actual A --screenshot PATH --agent NAME
    [--target docs/bugs.md] [--root R]
```

`--agent` is required, because FR-10 lists agent/session among every finding's fields. An empty value is refused
(exit 2).

`--url` is the full address of the page the screenshot was taken on (Playwright's `page.url`). The finding date is
today. Tests can set it with `HM_TEST_FINDING_DATE` (ISO date), which lets SC-09 step 2 record "another date". This
setting sits beside the other test-only `HM_TEST_*` settings in A5.

**Screenshot rule on refusal (FR-16).** Whenever the command refuses a finding, for any reason (any check below or
the lock timeout), it deletes the screenshot **if** it resolves inside `<root>/evidence`. A screenshot outside
`evidence/` is never touched. The command never deletes or writes anything outside `<root>/evidence` and the target.
A root without the sentinel is refused before this rule applies (A5 "Sentinel check"), so nothing is deleted there.

Steps:
1. Resolve `--screenshot`. If it isn't inside `<root>/evidence`, refuse with exit 2 and **don't touch the file**.
2. Read `<root>/session.json`. If it is missing, or its `base_url` isn't exactly `http://127.0.0.1:<port>`, refuse
   (exit 2). `finding` runs outside the sandbox, so this keeps the token from being sent anywhere but loopback.
3. Require `--target` to resolve to the repo's `docs/bugs.md` or a path inside `<root>`. Otherwise refuse with exit
   2. Tests pass `tmp_path/bugs.md` with `--root tmp_path`.
4. Require the origin of `--url` (scheme, host and port) to equal `session.json.base_url`. A page on 8765 (the live
   app) or on a stub port fails this check.
5. Call `GET {base_url}/api/settings` with the token and require `test_instance` to be truthy. The live app fails
   this.
6. If check 2, 3, 4 or 5 fails: delete the screenshot (it is inside `evidence/`, by check 1), leave the target
   unchanged, and exit 2. Checks 4 and 5 are the deterministic part of FR-14. An agent that reports a URL it wasn't on isn't
   caught. The skill's marker check before each screenshot covers that case (FR-18, manual).
7. Otherwise, write the entry while holding `<target>.lock`, created with `O_CREAT|O_EXCL`. If the lock is still
   held after 10 s, refuse with exit 3 and delete the screenshot (the rule above). The file is replaced through `write_atomic` (`paths.py:86`), so a second agent
   never sees half an entry.
   - The lock only coordinates `finding` runs. The developer may save the file in an editor at the same time, so
     just before the replace, the command re-reads the target and compares its bytes with the first read. If they
     differ, it refuses with exit 3 ("docs/bugs.md changed while recording; run again"), deletes the screenshot and
     leaves the developer's version in place.
   - `docs/bugs.md.lock` and `docs/bugs.md.pending` (the `write_atomic` temp file) are added to `.gitignore`, so a
     crashed run never leaves them to be committed.
   - Keep the target's newline style.
   - Append `## Agent findings` if it is missing.
   - The key is sha256 of (normalized route, then lower-cased symptom with whitespace collapsed). It is stored as
     `<!-- finding:KEY -->`.
   - **Section bounds.** The section runs from its `## Agent findings` header to the next line starting `## `, or to
     the end of the file. New entries go at the end of the section, before any later `## ` heading the developer
     added. Text after the section is kept byte for byte, like text before it. A `## ` line inside an entry's fields
     is written as `\## ` so it can't end the section.
   - **Entries and keys.** Keys are matched **only inside the section**. A `<!-- finding:KEY -->` the developer
     copied into their own text above or after the section is ignored, so a "Seen again" write can't land outside it.
     An entry runs from its marker to the next `<!-- finding:` marker or the section's end. A "Seen again" line goes
     at the end of its entry. In field text, `<!--` is written as `&lt;!--`, so a field can't forge a marker or open
     a comment that hides later entries.
   - If the key exists, append `- Seen again: DATE (seed DATE) — evidence: <screenshot path>` under that entry. Each
     sighting cites its own screenshot, so SC-09's "both screenshot paths exist" also means both are cited.
   - **The same key on the same date** is a no-op that exits 0 and prints "already recorded today". It keeps the new
     screenshot, because the finding wasn't refused, and prints its path. FR-10's "two dates" therefore means two
     different dates. SC-09 step 2 uses `HM_TEST_FINDING_DATE` for that, and the skill (A8) tells agents a repeat on
     the same day adds nothing.
   - Otherwise append the entry with every FR-10 field, including the seed date from `session.json` and the URL.
   - The bytes before the section header are never rewritten. The command writes only after the header, and the
     test compares that prefix byte for byte.
   - **No trailing newline.** The real `docs/bugs.md` ends without a newline (CRLF file, last line "screen. "). When
     the section is added, the command writes the target's own newline and then `## Agent findings`. That line break
     is part of the header block, so the content before it is B0 exactly. SC-09's oracle is `new_bytes.startswith(B0)`,
     then exactly one target newline, then `## Agent findings`. SL-05 adds this as a SC-09 variant (B0 with CRLF and no
     trailing newline), next to the contract's CRLF and existing-section variants.

**A8. Agent skill (FR-18):** `.claude/skills/agent-testing/SKILL.md`. The skill tells agents to:
1. Run `verify` and then read `session.json`.
2. Use only `base_url` (never 8765).
3. Open `link` with `playwright-cli`, using `.playwright/cli.config.json`.
4. Check that `#test-instance-marker` is visible before each screenshot.
5. Save screenshots under `<root>/evidence`.
6. Record findings only with the `finding` command, passing `--url` as the page's current URL. Before recording,
   read `## Agent findings` and reuse the exact route and symptom text of a matching entry, so that duplicates
   collapse into "seen again" (the key is exact after normalization). A repeat on the same day adds nothing.
7. Use the files in `uploads/`.
8. Never type paths outside the root.

**Decision D-P1. The test instance is a separate entry point (`scripts/test_instance.py serve`), not a
`--test-instance` flag on `python -m home_manager`.** That keeps the live launcher unchanged (I-2). It also means a
typo in a live launch can never turn guards on or off. *Rejected alternative:* a CLI flag, which needs live-launcher
changes and lets test code paths be reached from the live entry point.

**Decision D-P2. Egress is blocked with an audit hook, not a wrapper at each of E1–E3.** The hook catches future
callers, and the existing `OSError` handling already gives the right UI. *Rejected alternative:* guards at each
call site. That needs three edits and misses new callers.

**Decision D-P3 (accepted 2026-10-17). `verify` checks that the seed is complete, and checks exact counts only with `--fresh`.** FR-09
says `verify` checks that "the seed manifest matches the database". Exact count equality would fail for every agent
session after the first change, even though restarting without a reset is supported (spec "Restart without reset",
SC-18). Exact equality still runs in tests and right after `reset`, so FR-02 drift is still caught. *Rejected
alternative:* always exact. That makes `verify`, step 1 of the agent workflow, fail after any agent edit.

**Decision D-P4 (accepted 2026-10-17). `finding` checks the page origin, and the agent takes the screenshot.** This
is how the plan reads FR-16's "checks the FR-14 marker on the page the screenshot came from": the page's origin must
be `base_url`, and that server must report `test_instance`. The marker is shown exactly when `test_instance` is set
(A3). The command doesn't inspect the image (R8). *Rejected alternative:* the
command takes the screenshot itself. A fresh page load loses the UI state that the finding shows, such as an open
modal or a filled form.

**Decision D-P5 (accepted 2026-10-17). `finding` deletes the screenshot on every refusal, but only inside
`<root>/evidence`.** FR-16 says a refused finding deletes its screenshot. A screenshot path outside `evidence/` is
left untouched, so a mistaken or hostile `--screenshot` can never delete a file elsewhere on disk. A root without the
sentinel is refused first (A5 "Sentinel check"), so a mistaken `--root` can't widen what "inside `evidence/`" means.

## Error handling, idempotency and recovery

| Situation | Behavior |
|---|---|
| A seed step fails | exit 1, the step is named on stderr, `.seed-incomplete` stays, `start` refuses. Re-running `reset` is idempotent: sentinel check, delete, reseed. |
| `reset` while running | refused with exit 1 ("stop the instance first"). Nothing is deleted. |
| The root overlaps a protected root (mistyped `--root` or `HM_TEST_ROOT`) | every subcommand refuses (exit 2) before any filesystem call. Nothing is created, deleted or written. |
| The root has no sentinel but has content | `reset` refuses to delete it ("not a test instance folder"). This protects a mistyped `--root`. The one exception is `<checkout>/tests/.tmp` itself (I-3). |
| `start`, `serve`, `stop`, `verify` or `finding` on a root without the sentinel | refused (exit 2, "not a test instance folder") before any write or delete, with the same `tests/.tmp` exception. Nothing in the folder is touched. |
| `server.pid` names a dead process or one with a different creation time | Stale: the file is removed and nothing is signalled. `reset` and `start` go ahead. |
| Port busy | `start` exits 1 and names the port. No `session.json`, no fallback port. |
| `start` while already running | the same as port busy. |
| `stop` when not running | exit 0, says "not running". Stale pid and session files are removed. |
| The server crashes | `verify` fails "server". `session.json` may be stale, so `start` deletes a stale `session.json` before spawning. |
| LM Studio is down | `verify` warns. Uploads show the app's existing model-unavailable state. Nothing else changes. |
| No model IDs picked yet (first reset with no `--vision-model` / `--reasoning-model`) | `verify` warns. Uploads show the app's existing "choose a model" state (`receipt_service.py:56`). The developer picks models in Settings › Models, and later resets keep them (reset step 2). |
| Something is listening on 8765 | `start` and `verify` print the shared-LM-Studio warning and carry on (FR-12). |
| `finding` is given a screenshot outside `evidence/` | refused (exit 2). That file is not touched, and the target is unchanged. |
| `finding` has a `session.json` whose `base_url` isn't `http://127.0.0.1:<port>`, or an empty `--agent` | refused (exit 2) before any request. The screenshot (inside `evidence/`) is deleted, and the target is unchanged. |
| The developer saves `docs/bugs.md` while `finding` is writing | `finding` sees the change before replacing, refuses (exit 3) and deletes its screenshot. The developer's edit is kept. |
| `finding` has no `session.json`, a target outside the allowed paths, a page origin that isn't `base_url`, or an instance not in test mode | refused (exit 2). The screenshot (inside `evidence/`) is deleted, and the target is unchanged. |
| Two `finding` runs at once | the second waits for `<target>.lock` for up to 10 s, then refuses (exit 3) and deletes its screenshot. It never writes half an entry. A lock left by a crashed run is reported by name so the developer can delete it. |
| `finding` duplicate | a "seen again" line citing the new screenshot, no new entry. Re-running with the same date is a no-op that exits 0 (idempotent) and keeps the screenshot. |
| The developer added text after `## Agent findings` | entries go at the end of the section, before the next `## ` heading. The developer's text after it stays byte for byte. |
| `reset` while another program holds the port | refused with exit 1, naming the port and saying it isn't this instance. Nothing is deleted. |
| `serve` crashes or hangs during `start` | `start` exits 1 within 30 s, prints the `server.log` tail, ends the spawned process tree, and leaves no `session.json` or `server.pid`. |
| `reset` | keeps `<root>/evidence/`, so findings in `docs/bugs.md` keep valid screenshot paths. |
| The server doesn't exit within 10 s of `stop.request` | terminated. The SQLite WAL is recovered on the next open. The OS releases `DirectoryLock` on process death (`paths.py:137`). |

## Privacy/security and migration impact

- **No schema or migration change.** No new persisted app settings. The test-mode flag is process memory only.
- **The live app is unchanged.** `sandbox` is inactive unless `scripts/test_instance.py` activates it. The added
  checks are a no-op `if` in `local_absolute` and `endpoint_url`, a `None` key in settings, and a hidden element.
  SC-11 plus the existing test suite cover this.
- **Live data is never touched.** Guards are lexical and run before any filesystem call. Tests use decoys, raising
  spies and a fake `LOCALAPPDATA` (contract conventions). The harness never reads `%LOCALAPPDATA%\HomeManager`.
- **Network.** Only loopback in test mode. LM Studio is loopback. No data leaves the machine.
- **Tokens.** The token is random per `serve` and lives only in `<root>/session.json` (gitignored when the root is
  `tests/.tmp`).
- **Audit hooks can't be removed.** In-process tests install the hook once per pytest session. It is inert while
  `sandbox` is inactive and only blocks non-loopback hosts, which tests don't contact anyway.
- **This is gated work** (integration guards, persisted test data). Implementation waits for plan approval.

## Vertical slices

| ID | FR/SC covered | Dependencies | Files/changes | Verification command / evidence |
|---|---|---|---|---|
| SL-01 Guards | FR-03 (refusals), FR-04, FR-05; SC-03, SC-04, SC-05, SC-08, SC-11 (steps 2–4), SC-14 (API part) | none | New `src/home_manager/core/sandbox.py`. `core/paths.py` (`local_absolute` calls `sandbox.check_path`; `separate_folder` checkout exemption under the sandbox root). `models/vision.py` (`endpoint_url` tailnet refusal). `app/family_hub.py` (inline `sandbox.active()` check where the hub reads `tailnet_address()`, `:108`). New `tests/test_agent_guards.py`: fixtures `sandboxed`, `real_path_spies`, `no_egress` (never calls the real socket functions for a non-loopback host; see the test environment section, with `test_no_egress_never_calls_real_socket`), decoys; SC-08: for vision, reasoning, reviewer and decision, `http://192.168.1.50:1234/v1`, `http://example.invalid/v1`, `http://100.64.0.1:1234/v1` and `http://localhost:1234/v1` are refused in both modes (as today, `manager.py:1183`); for the model computer (`PUT /api/model-computer`, `family_gpu` with a token), `http://100.64.0.1:1234/v1` and `http://gpu.example.ts.net:1234/v1` are refused only in test mode; `test_hook_allows_passive_bind_lookup` (with the sandbox active, `socket.getaddrinfo(None, 0, flags=AI_PASSIVE)` and `getaddrinfo("", 0)` succeed, and `getaddrinfo("example.invalid", 443)` raises `gaierror`); `test_watch_folder_in_root_inside_checkout` (monkeypatches `paths.reserved_paths` so the checkout is `tmp_path/checkout` and the sandbox root is `tmp_path/checkout/tests/.tmp`: `add_source` for `<root>/uploads` succeeds, and with the sandbox off it is refused, as today); SC-05 step 4 setup: no API path can link a `100.64.0.1` member in test mode (`invite_member` needs `tailnet_address()`, `manager.py:582-584`), so the test creates a family with `FamilyFolder.create` inside `<root>` (hex `family_id`, `family_sync.py:332`), adds a member with `family.add_member(name, "remote")` (hex `member_id`, `:355-365`) and a token with `family.new_token(member_id)` (`:469`), which `read_invite` requires (`:147-148`), then closes the `FamilyFolder` (it holds a `DirectoryLock`). It writes an invite with `family_sync.write_invite(family.data, member, ..., hub="100.64.0.1:<port>", token)` (`family_sync.py:122-123`; a bare `host:port`, because `hub_address` parses it with `ip_address`, `family_client.py:31-41`, and a URL would be refused as `HubError` before any socket call) into `<root>`, and joins it through `join_family` (the invite path is inside the root, so `local_absolute` allows it). `join_family` starts the sync itself (`manager.py:612`). The test waits on `manager.future.result()`, then asserts both halves of the contract's "refused and logged; no connection attempt is recorded" (`test-contract.md:132-133`): the `100.64.0.1` lookup is recorded at the `getaddrinfo` stage with `refused_by="sandbox"`, no connect-stage record exists for it, and the refusal is logged (`caplog` in-process). Asserting only "no connection" isn't enough, because that also passes when the invite is malformed; `test_hub_stays_off_in_test_mode` registers a family folder (otherwise `start()` returns early with "No family folder", `family_hub.py:105-107`), monkeypatches `family_hub.tailnet_address` with a spy returning `"100.64.0.1"` (overriding the autouse `no_tailnet`, `conftest.py:108-113`), activates the sandbox, and asserts the hub doesn't listen, its status reason is "Tailscale isn't running…", and the spy was never called; **SC-05 steps 1–3 setup**, because the household seed has no crypto and no non-USD amount (every `seed_wealth.py` account is USD), crypto prices are off by default (`ledger.py:284`), and Brave search stops before any request without a key (`web_lookup.py:145`), so without this setup each step could pass with no attempt at all: the fixture sets `fetch_crypto_prices=True` and `fetch_exchange_rates=True` through `configure_household`, and adds a crypto investment account (kind `crypto`, which is market-valued, `036_investments.sql:31`) holding units > 0 of `BTC`, a symbol in `prices.COINGECKO_IDS`, so `CryptoPrices.wanted` returns a pair (`prices.py:108-129`). No foreign-currency transaction is needed: `POST /api/rates/refresh` fetches whenever rates are on (`fx.py:134-138`). Steps: (1) `POST /api/prices/refresh`; (2) `POST /api/rates/refresh`; (3) item identification on a receipt line whose `product_code` is a GTIN with a valid check digit (`4006381333931`), because `valid_gtin` checks it (`household/items.py:67-74`), with no reasoning model set, so the resolver doesn't go on to model calls (`resolver.py:155-157`); the test waits on `manager.future`, and since a failed barcode lookup is swallowed (`resolver.py:143-146`), the oracle is that the run ends `succeeded` with `method` None, the line has no new proposal, `world.openfoodfacts.org` is recorded with `refused_by="sandbox"`, and the refusal is logged. The test is **stricter than the contract's "or no attempt at all"**: steps 1 and 2 must record their host (`api.coingecko.com`, the ECB host) with `refused_by="sandbox"` and return the existing unavailable result, a 400 from the `ValueError` handler (`api.py:644-646`), not 5xx; each refused host is logged; a precondition assertion fails the test if the setup leaves `CryptoPrices(...).wanted()` empty. **End state:** the row counts of `price_quotes`, `fx_rate_sets` and `fx_rates` are the same before and after. **Retry variant:** each of steps 1–3 is run a second time, with the same response, no 5xx and no new rows. **Step 5** is `test_sc05_offline_screens` in `tests/test_agent_instance_browser.py` (SL-04, `browser_test`). It runs the same setup on an in-process sandboxed app with `no_egress` and opens Money (USD conversion), Investments (the crypto account) and Inventory (the identified line). Each shows its existing unavailable state, with no `pageerror`. **SC-03 inputs**: P1–P10 from spec U1 plus P12, the member folder in `POST /api/families/{profile_id}/members/{member_id}/local` (`api.py:714-716`, `LocalMemberInput.folder`, `api.py:142-145` → `set_up_local_member` → `create_profile`, `manager.py:568`), which the spec's list leaves out but the same `local_absolute` guard covers. For every input, SC-03 asserts the sandbox's own refusal text ("Test instance: … holds real data and is off limits."), not just a 4xx, so a wrong route (404/405) or a validation error fails the test | `.venv/Scripts/python.exe -m pytest tests/test_agent_guards.py tests/test_capture.py tests/test_gpu_host.py tests/test_residency.py tests/test_family_hub.py` (existing path, model-address and hub tests unchanged and passing) |
| SL-02 Shared seed | FR-13; SC-13 step 1 | none | New `tests/seed_household.py` (moved code, steps, `fail_step`, manifest; `seed` seeds the open library and doesn't call `configure`). `ui_shots.py` imports it, calls `configure(root/"managed")` before `seed`, and its seed functions are deleted | AST test in `tests/test_agent_instance.py::test_one_household_seed`. Run `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes home,review --widths 1440 --themes light`: same routes render, no page errors |
| SL-03 Harness lifecycle | FR-01, FR-02, FR-06, FR-07, FR-09, FR-11, FR-12, FR-15, FR-17, FR-03 (pointing at LM Studio); SC-01, SC-06d, SC-07, SC-10, SC-12, SC-13 (2–4), SC-17, SC-18, SC-19, SC-06 (opt-in) | SL-01, SL-02 | New `scripts/test_instance.py`. `tests/environment.json` (commands call the script; `models.mode = "lmstudio"`, `live_inference_opt_in = true`). `pyproject.toml` (register the `lmstudio` marker and add `-m "not lmstudio"` to `addopts`, so the default run skips it). New `tests/test_agent_instance.py`, including `test_reset_refuses_root_without_sentinel`, `test_root_overlapping_protected_refused` (with a decoy in `HM_TEST_PROTECTED`, `reset`, `start` and `stop` with `--root <decoy>/agent`, `--root <decoy>` and `--root <decoy's parent>` each exit 2, and the decoy's recursive listing and the canary's mtime are unchanged), `test_reset_keeps_evidence`, `test_commands_refuse_root_without_sentinel` (a `tmp_path` folder with no sentinel holding a decoy `evidence/x.png`, `session.json`, `server.pid` and `stop.request`: `start`, `stop`, `verify` and `finding` (with `--screenshot <folder>/evidence/x.png` and no valid session) each exit 2 with "not a test instance folder", and every decoy's bytes and mtime are unchanged), `test_stop_from_another_console` (`stop` launched with `CREATE_NEW_CONSOLE` shuts the server down through `stop.request` well before the 10 s fallback, and the port is free when `stop` returns), `test_stale_pid_is_not_signalled` (the pid file names the test's own live helper process with a wrong `created`: `stop` leaves that process alive and removes the file), `test_pid_is_the_server` (after `start`, the pid in `server.pid` is the process that owns the listening port, checked with `GetExtendedTcpTable` through `ctypes`, not the venv launcher's pid; SC-10's "no process alive" uses this pid), `test_lmstudio_deselected_by_default` (`pytest --collect-only -q tests/test_agent_instance.py` in a subprocess doesn't list SC-06, and `-m lmstudio` does), `test_verify_after_agent_change` (exit 0 without `--fresh`, exit 1 naming the seed check with `--fresh`), `test_restored_instance_is_independent` (the template-restore fixture), `test_reset_models` (with `--vision-model` / `--reasoning-model` the vision, reasoning and reviewer settings name the LM Studio address and those IDs; a second `reset` without the flags keeps them; with no IDs at all the reviewer is `off`, `verify` warns, and no setting names the fake model server's port), `test_profile_library_is_root_library` (SC-01 step 2: `profiles.json` has one profile at `<root>/library`, not `<root>/managed`), `test_start_warns_on_8765` (SC-12's dummy listener: `start` prints the warning and still serves), `test_verify_fails_without_guards` (FR-09's "a guard is off": with the instance stopped, the test starts the plain launcher `python -m home_manager --control-dir <root>/control --port <port>`, with the fake `LOCALAPPDATA`, reads the `#token=` link from its stdout, and writes `session.json` itself; `verify` exits 1 and names the guard check; the test ends the launcher in `finally`), `test_status_probes_guards` (in-process: with `check_path` monkeypatched to return without raising, `status()["paths"]` is false; with the audit hook made a no-op, `status()["egress"]` is false and `no_egress` records the probe host with `refused_by="double"`, so the probe never resolves for real), `test_verify_incomplete_seed` (with `.seed-incomplete` present, `verify` exits 1 with "seed: incomplete, run reset"), `test_reset_refuses_foreign_port` (a dummy listener on the port with no `server.pid`: `reset` exits 1 with the "in use by another program" message and deletes nothing), `test_start_reports_failed_serve` (`HM_TEST_SERVE_FAIL=1`, a test-only setting read only by `serve`, makes `serve` exit before uvicorn starts: `start` exits 1 within 30 s, prints the log tail, leaves no `session.json` or `server.pid`, and the port is free), and `test_reset_settles_before_manifest` (after `reset`, no `-wal` content is pending and the Manager's lock file isn't held; two resets on the same date give equal manifests) | `.venv/Scripts/python.exe -m pytest --browser tests/test_agent_instance.py` (`--browser` because SC-06d and SC-07 step 2 drive the UI; those tests carry `browser_test`. SC-14's screens are in SL-04). The slice report gives pass and skip counts. Opt-in: `-m lmstudio`. Manual, required before the slice is done: `python scripts/test_instance.py reset`, `start`, `verify --fresh` on the **default** root `tests/.tmp`. This is the only run inside the checkout, and it catches checkout-overlap errors that the `tmp_path` tests can't. |
| SL-04 Marker | FR-08, FR-03 (Settings › Models shows the LM Studio address); SC-02, SC-11 step 1, SC-14 (screens) | SL-01, SL-03 | `app/manager.py` (`settings()` key). `static/index.html`, `static/app.js` and the app stylesheet (marker). New `tests/test_agent_instance_browser.py` (every test carries the per-module `browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", ...)` alias, as in `test_accounts_v2_browser.py:13`; `--browser` sets that variable, `conftest.py:11-18`), including `test_marker_visible_everywhere` (`#test-instance-marker` is visible at 390, 768 and 1440 without opening `#nav-toggle`, and at 1024, where the sidebar is the 64 px rail that hides `.brand-name` and `.nav-label`, `style.css:1268-1276`) `test_models_show_lmstudio_address` (Settings › Models shows the `--lmstudio` address given to `reset`), and SC-02 step 3's seeded-content check, where Taxes is checked only when `seed.json` has `taxes_seeded` true and is otherwise skipped with the `this_year_covered` reason (A4), and `test_sc05_offline_screens` (SC-05 step 5, with SL-01's SC-05 setup on an in-process sandboxed app with `no_egress`: Money's USD conversion, the Investments crypto account and the Inventory line each show their existing unavailable state, with no `pageerror`). Load `ui-ux-pro-max` first | `.venv/Scripts/python.exe -m pytest --browser tests/test_agent_instance_browser.py tests/test_settings_browser.py`. The slice report gives the pass and skip counts; a run where these tests are skipped is not evidence. Screenshots at 390/768/1024/1440, light and dark |
| SL-05 Findings command | FR-10, FR-14, FR-16; SC-09, SC-15, SC-16 | SL-03 (`session.json`, `settings.test_instance`) | `scripts/test_instance.py` (`finding`). `.gitignore` (`docs/bugs.md.lock`, `docs/bugs.md.pending`). New `tests/test_agent_findings.py`, always against `tmp_path/bugs.md` (the real `docs/bugs.md` is never written). The tests call the CLI in-process through `test_instance.main(argv)` (so `no_egress`, `monkeypatch.setenv("HM_TEST_FINDING_DATE", ...)` and `caplog` apply), and `test_finding_cli_smoke` runs it once as a subprocess to check exit codes and argument parsing. Its server is a module-scoped `test_server` fixture built on `tmp_path_factory` (a module fixture can't use `tmp_path`): an in-process `create_app(<module dir>/"control", token, port)` on a uvicorn thread (a free port), with the sandbox activated over the module directory and deactivated on teardown. A function-scoped `finding_root` fixture makes the per-test root as a subfolder of that module directory (so it is inside the sandbox's allowed root), creates `evidence/` and the sentinel `.hm-test-instance` there and writes its `session.json` (`base_url`, `link`, `seed_date` = 2026-10-17) pointing at the module server. Each test passes that folder as `--root` and `<root>/bugs.md` as `--target`. No seeded instance is needed. It covers: SC-09 with `HM_TEST_FINDING_DATE` for step 2; SC-15 with `--url` on the stub's port; `test_screenshot_outside_evidence_untouched` (a decoy file outside `evidence/` is refused, and its bytes and mtime are unchanged); `test_target_outside_allowed_refused` (a screenshot inside `evidence/` is deleted); `test_refusal_deletes_screenshot` (no `session.json`, a bad target and a lock timeout each delete a screenshot inside `evidence/`); `test_no_trailing_newline_prefix` (B0 is CRLF with no final newline, like the real `docs/bugs.md`: the new file starts with B0, then one CRLF, then `## Agent findings`); `test_concurrent_findings` (two writers at once give two complete entries, or one entry plus exit 3); `test_developer_edit_kept` (the target is changed between the command's read and its replace, through a test hook: exit 3, the changed bytes stay, the screenshot is deleted); `test_non_loopback_base_url_refused` (`session.json.base_url` = `http://192.0.2.1:8775`: exit 2 and `no_egress` records no attempt); `test_agent_required` (no `--agent` or an empty one: exit 2); `test_seen_again_cites_screenshot` (the "Seen again" line names the second screenshot, and both files exist); `test_same_date_repeat_noop` (the same key on the same date: exit 0, bytes unchanged, screenshot kept); `test_text_after_section_kept` (B0 + section + one entry + a developer `## Notes` section after it: a new entry lands before `## Notes`, and the bytes from `## Notes` to the end are unchanged); `test_heading_in_field_escaped` (a `--actual` value with a `## ` line doesn't end the section); `test_marker_outside_section_ignored` (B0 contains a copied `<!-- finding:KEY -->` above the section: recording that key adds a new entry inside the section, and the B0 prefix stays byte-identical); `test_seen_again_lands_in_its_entry` (with two entries, a repeat of the first puts its line before the second entry's marker); `test_comment_in_field_escaped` (a `--steps` value containing `<!-- finding:abc -->` is written escaped, and the parsed entries are unchanged in number) | `.venv/Scripts/python.exe -m pytest tests/test_agent_findings.py` |
| SL-06 Skill and docs | FR-18; I-5 (instructions) | SL-03, SL-05 | New `.claude/skills/agent-testing/SKILL.md`. `docs/development.md` new section "Agent test instance". `docs/README.md` index line. (`tests/.tmp/` is already ignored; SL-05 adds the `bugs.md` lock and temp files.) | `tests/test_agent_findings.py::test_skill_names_finding_command` (static). Manual: one agent session following the skill, reviewed by the developer (FR-18 acceptance) |

Order: SL-01 and SL-02 (in parallel) → SL-03 → SL-04 and SL-05 → SL-06.

## Requirements & scenarios coverage matrix

| ID | Slice | Test |
|---|---|---|
| FR-01 | SL-03 | SC-01, SC-17, SC-18 |
| FR-02 | SL-02, SL-03 | SC-01, SC-10, SC-13; SC-02 (SL-04) |
| FR-03 | SL-01 (refusal), SL-03 (pointing), SL-04 (UI) | SC-08 (with tailnet cases); SC-06d, SC-07; SC-06 opt-in; `test_reset_models`; `test_models_show_lmstudio_address` |
| FR-04 | SL-01 | SC-03, SC-04, SC-14 |
| FR-05 | SL-01, SL-04 (step 5) | SC-05 (with the crypto, rates and barcode setup, end-state row counts and retries; stricter than the contract), `test_sc05_offline_screens`, SC-11, `verify`'s egress probe |
| FR-06 | SL-03 | SC-01 step 2 (one per kind), SC-04 step 3, SC-06 |
| FR-07 | SL-03 | SC-01, SC-18; SC-02 |
| FR-08 | SL-04 | SC-02, SC-11 |
| FR-09 | SL-03 | SC-01 (`verify --fresh`), SC-07, SC-12, `test_verify_after_agent_change` (D-P3), `test_verify_fails_without_guards`, `test_status_probes_guards`, `test_verify_incomplete_seed` |
| FR-10 | SL-05 | SC-09, SC-16, `test_seen_again_cites_screenshot`, `test_same_date_repeat_noop`, `test_text_after_section_kept` |
| FR-11 | SL-03 | SC-10 |
| FR-12 | SL-03 | SC-12, `test_start_warns_on_8765` |
| FR-13 | SL-02, SL-03 | SC-13 |
| FR-14 | SL-05 (deterministic part: page origin and test mode), SL-06 (agent part, manual) | SC-15 (stub on another port, by `--url`) |
| FR-15 | SL-03 | SC-01 step 1, SC-13 |
| FR-16 | SL-05 | SC-09, SC-15, `test_refusal_deletes_screenshot` |
| FR-17 | SL-03 | SC-19 |
| FR-18 | SL-06 | static check plus one reviewed agent run |
| I-1 | SL-01, SL-03, SL-05 | SC-01 (fake `LOCALAPPDATA` empty), SC-03, SC-14, `test_root_overlapping_protected_refused`, `test_screenshot_outside_evidence_untouched`, `test_target_outside_allowed_refused` |
| I-2 | SL-01, SL-04 | SC-11 plus the existing suites in the SL-01 and SL-04 commands |
| I-3 | SL-03 | SC-19, `test_reset_refuses_root_without_sentinel`, `test_stale_pid_is_not_signalled` |
| I-4 / I-6 | SL-03 | SC-05 (no non-loopback host), SC-18 (new token per start) |
| I-5 | SL-06 | skill text (manual review) |

## Test environments, data, stubs for nondeterministic components, final-state oracle

- **Unit and integration (in-process):** `tests/test_agent_guards.py` uses `create_app(tmp_path/"control", token,
  port)` with `sandbox.activate(tmp_path/"instance", protected=[decoys])` and `deactivate` in teardown.
  - Real-path spies raise on any argument under `P:\Finances`, `P:\EvalCorpus` or the real `LOCALAPPDATA` (read
    from `os.environ` **as a string only**).
  - `no_egress` is independent of the sandbox. It patches `socket.getaddrinfo`, `socket.create_connection` and
    `socket.socket.connect`. **It never calls the real function for a non-loopback host**, so no DNS lookup or
    connection leaves the machine even when the guard under test is broken or off:
    - Loopback hosts (`localhost`, `127.0.0.0/8`, `::1`, and `None`/`""` for binds) go to the real function.
    - For any other host, the spy records it, then raises the same audit event the real function would
      (`sys.audit("socket.getaddrinfo", host, port, family, type, proto)` or
      `sys.audit("socket.connect", sock, address)`). If the sandbox is active, its hook raises there, and the spy
      records `refused_by="sandbox"` and lets that exception through. If nothing raised, the spy records
      `refused_by="double"` and raises the same type the sandbox would: `socket.gaierror` for `getaddrinfo` and
      `ConnectionRefusedError` for a connect. That matters because `web_lookup.public_address` (`:40-43`) catches
      only `gaierror` and is called outside `https_get`'s `try` (`:56`). Another type would escape as a raw `OSError`
      in the sandbox-off case and fail the test for a reason the live app never hits.
    - SC-05 asserts that every recorded non-loopback attempt has `refused_by="sandbox"` and that the
      `test instance: refused outbound host=` log line is present.
    - SC-11 step 4 asserts the reverse: with the sandbox off, the attempt is recorded with `refused_by="double"`.
    - A self-test of the double (`test_no_egress_never_calls_real_socket`) replaces the saved real functions with
      ones that raise, then runs a non-loopback lookup and connect with the sandbox off and on, and asserts the real
      functions were never reached.
    - Subprocess tests can't patch the server process, so they rely on the sandbox hook and grep the app log
      `<root>/control/logs/home-manager.log` (not `server.log`, which holds only stdout/stderr).
      On the seeded household they have **no** non-loopback trigger. The startup refresh does nothing: crypto prices
      are off by default (`ledger.py:284`, `manager.py:1675`), and rates need non-USD money (`manager.py:1683`), but
      the seed is all USD. `tailnet_address` isn't called in test mode (A1 "Hub"). So subprocess tests can only
      assert that the log has **no** refusal line and no non-loopback model request (SC-06, SC-06d). The contract's
      "subprocess tests read the instance log for the FR-05 refusal lines" (`test-contract.md:28-29`) is met that
      way. FR-05 itself is proven in-process (SC-05, SL-01) and in the running instance by `verify`'s egress probe
      (A1 `status()`).
  - SC-11 step 3 saves a tailnet address (`http://100.64.0.1:1234/v1`) as the **model computer** (`PUT
    /api/model-computer`, `family_gpu`, with a token), the only model setting the live app accepts it for today.
    Vision, reasoning, reviewer and decision refuse it in live mode too (`manager.py:1183`), and LAN and public
    addresses are refused everywhere (`vision.py:33`).
- **Subprocess (harness):** `tests/test_agent_instance.py` runs `scripts/test_instance.py` with
  `HM_TEST_ROOT=tmp_path/instance`, a free port, and `LOCALAPPDATA`/`APPDATA` set to `tmp_path/fake-localappdata`.
  - It never uses `tests/.tmp` or port 8775.
  - Seeded state can't be copied to a new folder. `profiles.json` stores the library folder as an absolute path
    (`profiles.py:82`), and so does the seeded watched folder (`seed_processing.py:39`, read at `manager.py:268`). A
    copy's server would try to open the original library, and the sandbox would refuse it.
  - So a module-scoped fixture runs `reset` once into `tmp_path_factory/template/instance` with the instance stopped,
    and keeps that tree as the template. The function-scoped `seeded_instance` fixture then:
    1. stops any instance at the fixed test root `tmp_path_factory/run/instance` and checks the port is free;
    2. deletes that root and copies the template's files into it, then rewrites the absolute paths that name the
       template root to the run root **by parsing values, not bytes**:
       - **Every** copied `.json` file is loaded with `json`, each string value naming the template root is rebased
         with `Path.relative_to(template)`, and the file is written back with `json.dump`. That covers `profiles.json`
         and `seed.json`, and also `control/settings.json`, which `switch_profile` → `open_library(persist=True)`
         writes with the library's absolute path (`manager.py:1126`), plus anything else under `control/profiles/`.
       - **Rebase rule** (JSON and DB): a value is rebased only if it equals the template root or starts with the
         root followed by a separator (`\` or `/`, in the matching form), so `<template>-old\…` is never touched.
       - The tree is copied with `shutil.copytree` (`copy2`), so file mtimes are kept.
       - The library DB is rewritten **generically**, not table by table, because absolute paths live in more places
         than `sources.path`. The Inbox key is stored as `path_key(...)` (`os.path.normcase`, lowercase on Windows,
         `paths.py:50`) in `occurrences`, `jobs`, `receipt_batches` and `capture_intents` (`source_root`, the same four
         tables `backup.py:217-221` rewrites on restore), and in `sources.path_key`. For every ordinary table in
         `sqlite_master` (virtual tables and FTS shadow tables skipped) and every column, rows where
         `typeof(col) = 'text'` and the value matches the rebase rule for the template root in its raw, `normcase`,
         or forward-slash form are rebased onto the run root in the same form. Selecting by value rather than by
         declared type also covers STRICT `ANY` columns. That covers the four
         `source_root` tables and `sources.path`/`path_key`, and any column added later.
       - The template's logs (`control/logs/`, `server.log`) are not copied.
       Afterwards it searches every copied text file and every TEXT value in the DB for the template root in raw,
       `normcase`, JSON-escaped (`\\`) and forward-slash forms, case-insensitively, and fails on any hit. It also
       checks that each profile folder and each `sources.path`, resolved, is under the run root;
    3. returns the run root.
    Tests run one after another (no xdist), so one fixed run root is safe. Tests that only read (SC-02, SC-12) share
    one restore per module.
  - `test_restored_instance_is_independent` checks the fixture itself: after a restore, `start` + `verify --fresh`
    pass, `profiles.json` and every `sources.path` sit under the run root, and a change made in one test is gone in
    the next. It also drops one synthetic receipt into the restored `Library/Inbox` and checks that exactly one new
    document appears and the seeded Inbox documents are not captured again (the `source_root` keys match the run
    root's Inbox).
  - SC-01, SC-13 and the two-reset equality check (FR-02) always run a real `reset`, never the template.
- **Browser:** Playwright with Chromium on `msedge`, headless, against `seeded_instance`. The `pageerror` list must
  be empty.
- **Models:**
  - The seed always uses `start_model_server()` with scripted outputs.
  - "LM Studio" in deterministic tests is a second `start_model_server()`, passed with `--lmstudio`, and
    `--vision-model synthetic-vision --reasoning-model synthetic-reasoning` (IDs the double serves). Without model
    IDs, `receipt_service.py:56` won't read the upload, so SC-06d needs them. Its `state["requests"]` is the oracle
    for SC-06d.
  - The double returns `state["output"]` for every request unless `state["outputs"]` is scripted
    (`tests/model_server.py:96`). So SC-06d scripts `outputs` for the grocery upload: the vision reply from that
    document's known lines, then the reasoning reply. It follows `seed_documents._read_and_record`
    (`seed_documents.py:26-33`). Without that, the reasoning step would get a vision-shaped reply.
  - Real LM Studio is used only under `@pytest.mark.lmstudio`. Those tests check states (read, needs-review, or
    failed with a message) within 300 s, never values.
- **Clock:** expected dates come from `seed.json.seed_date`. Two-reset equality runs within one test, and the test
  is retried once if the date changes between resets.
- **Final-state oracle, independent of the code under test:**
  - Raw `sqlite3` read-only counts on `<root>/library/inventory.sqlite3`, compared with `seed.json`.
  - File listings and hashes (`profiles.json`, decoys, `fake-localappdata`, the prefix of `bugs.md`).
  - Port bind checks.
  - Process liveness from the pids.

  The table names the manifest counts must be confirmed in SL-02 from `library/storage.py` / migrations. The test
  queries them directly and doesn't reuse the manifest code.

## Risks, unresolved decisions, alternatives

- **R1 (resolved).** The re-approved contract (SC-08) expects `http://localhost:1234/v1` to stay refused, as in the
  live app today. SL-01 tests it as an ordinary case.
- **R2 (accepted 2026-10-17): FR-13's "browser tests that seed a household".** No existing
  browser test seeds the whole household. They seed sections (`seed_documents`, `seed_items`, …), and those keep
  their own helpers. The shared module is used by `ui_shots.py`, `reset` and the new SC-02 browser fixture. The SC-13
  AST check covers those three.
- **R7: checkout overlap.** The default root sits inside the checkout, and `tmp_path` tests can't see that. It is
  covered by the `separate_folder` exemption (A1), an in-process test with a monkeypatched checkout (SL-01), and the
  required manual run of `reset` on the default root (SL-03).
- **R8 (accepted 2026-10-17, with D-P4): finding provenance.** `finding` checks the page's origin, not the image. An agent that passes a URL it
  wasn't on isn't caught by code (D-P4). The skill's marker check before each screenshot and the reviewed agent run
  (FR-18) cover that.
- **R3: the seed still imports private test helpers** (`test_reconcile_tools.add/receipt`, `test_extraction`,
  `test_receipts`). A refactor there breaks `reset`. The manifest and step errors make the breakage loud (FR-13).
  Moving those helpers out is left out of scope.
- **R4: the SC-01 seed time.** The full seed (taxes engine, documents through the fake model) may take tens of
  seconds. The module-scoped fixture and a copied root keep the suite usable. If a single reset takes over 120 s,
  `start`'s 30 s wait is unaffected, since seeding is in `reset`.
- **R5: shared LM Studio** (risk 1) stays a warning only (FR-12). No lock is added.
- **R6: stopping the server.** `stop` asks through `<root>/stop.request`, which works from any console (a
  `CTRL_BREAK_EVENT` only reaches the caller's own console). A fallback terminate after 10 s is accepted, because
  SQLite WAL makes it safe.
- **New dependencies:** none. Playwright (the `browser-test` extra) and Pillow (already used by
  `evals/synthetic.py` and the tests' drawn receipts) are already in use.
- **Rejected alternatives:** a `--test-instance` flag on the live launcher (D-P1); per-call-site egress guards
  (D-P2); a fixed `--seed-date` (spec D8); a separate findings report (spec D4).

- **Spec wording notes (for the next time the spec is opened; the plan already follows the code):**
  - S-1: SC-11 step 3 says a "non-loopback model address" is accepted today. Only a tailnet model-computer address
    is (`vision.py:33`, `manager.py:1182-1185`). The plan tests exactly that.
  - S-2: SC-09's "prefix up to the section header is byte-identical to B0". The plan reads the line break it inserts
    before the header as part of the header (A7, "No trailing newline"), so B0 is still byte-identical. This is
    decision **D-P6 (accepted 2026-10-17)**: the oracle is `new_bytes.startswith(B0)`
    followed by one target newline and the header. *Rejected alternative:* reopen the spec to reword SC-09 first.
    The real `docs/bugs.md` has no trailing newline, so the literal reading can't be met by any writer.
  - S-3: SC-05's initial state ("seeded (it has a crypto investment account and a non-USD amount)") is false for the
    household seed: every seeded account is USD and none is crypto. The contract also accepts "or no attempt at all".
    The plan adds the missing state in SC-05's own setup and asserts a sandbox refusal for every step (SL-01). That
    is stricter than the contract, not a change to it.
  - S-4: FR-10's "running the same scenario twice gives one entry with two dates" holds for two different dates. A
    repeat on the same date is a no-op (A7). SC-09 already uses another date.
  - S-5: spec U1 leaves out the family member folder (`LocalMemberInput.folder`). The plan tests it as P12 under
    SC-03. It goes through the same `local_absolute` guard.
  - S-6: FR-02 says "investments of every kind", but the seed has no crypto account. The plan doesn't add one to the
    shared seed, which would change `ui_shots.py` output and FR-13's single seed. SC-05 sets it up itself.
- **Pytest `-m`:** a command-line `-m` replaces the default `-m "not lmstudio"`, so any other marker expression
  (e.g. `-m "not slow"`) brings the lmstudio tests back. No other markers exist today; `docs/development.md` notes it.

Recommended next steps:
1. Run `review-plan` in a fresh context (revised 2026-10-17 for review findings M1–M3, m1–m4, then for the third
   review: root overlap with protected roots, model-address scope, seed step names, the findings test server,
   required `--agent`, concurrent developer edits, loopback-only `base_url`, passive lookups, and stop by request file;
   then for the fourth review: default `lmstudio` deselection, `serve` writes its own pid, `gaierror` in `no_egress`,
   the no-trailing-newline prefix, SC-05 step 4 setup, marker placement, value-based template rewrite, the "Test"
   profile, the app log path, scripted SC-06d outputs; then for the fifth review: generic DB path rewrite
   including lowercase `source_root` keys, the invite's hub format, `--browser` in commands, the inline hub check,
   in-process `finding` tests; then for the sixth review: rebase every copied JSON file incl. `control/settings.json`,
   separator-bounded rebase rule, family member/token setup, hub test preconditions, the `finding_root` fixture;
   then for the seventh review: SC-05 crypto/rates/barcode setup with strict sandbox-refusal assertions, probing
   guard status with a guards-off `verify` test, `taxes_seeded` in the manifest, the `start` failure path, `reset`
   settling before the manifest, cited screenshots on "seen again", the P12 member folder, child-process scope of
   the egress hook, the same-date no-op, the `reset` message for a port held by another program, and section bounds;
   then for the eighth review (PASS WITH MINORS): the P12 route and refusal-text assertions, a valid-GTIN barcode
   step with the swallowed-failure oracle, SC-05 step 5 / end state / retries, keys matched only inside the section
   with `<!--` escaped, refusal logging reset on each activation, the subprocess egress wording, the SL-03 SC-14
   note, the EUR setup dropped, the inference drain before repointing models, and UDP scope; then for round 10 in
   reviews.md (PASS WITH MINORS): m1, every subcommand but `reset` requires the sentinel before any write or delete).
2. D-P3, D-P4/R8, D-P5, D-P6 and R2 were accepted on 2026-10-17. No plan decisions are open.
3. Approve in your own terminal:
   `gate.py approve --feature agent-test-instance --stage plan --by "<name>" --root "P:\Dev Environment\Projects\Home Manager"`
