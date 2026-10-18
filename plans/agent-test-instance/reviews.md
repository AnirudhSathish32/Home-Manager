# Plan reviews: agent-test-instance

Every `review-plan` round on `plans/agent-test-instance/plan.md`, oldest first, copied verbatim from the session
transcripts. Rounds are numbered by time. The reports' own titles ("third review round", "round 7") and the
plan's "Recommended next steps" count differently, because some rounds didn't know about others.

| Round | When (UTC) | Source | Verdict |
|---|---|---|---|
| 1 | 2026-10-18 02:33 | separate review session | REVISE |
| 2 | 2026-10-18 02:43 | separate review session | REVISE |
| 3 | 2026-10-18 02:55 | separate review session | REVISE |
| 4 | 2026-10-18 03:06 | separate review session | REVISE |
| 5 | 2026-10-18 03:21 | subagent review | REVISE |
| 6 | 2026-10-18 03:29 | subagent review | REVISE |
| 7 | 2026-10-18 03:33 | subagent review | REVISE (narrow) |
| 8 | 2026-10-18 03:41 | review in this session | REVISE |
| 9 | after 03:41 (time not recorded) | fresh-context subagent review | PASS WITH MINORS |

## Round 1

**Verdict: REVISE.** The plan was written against an older version of the spec, and it has three defects I confirmed in the code or plan text. Each has a small fix. Everything else maps cleanly.

### Gate
- `gate.py check --stage spec` → **APPROVED** b2834186f166 (2026-10-17 22:28).
- `gate.py hash` → `b2834186…5e76`. The plan records `67b2b77b…d6e8` (`plan.md:3`). **They don't match.**

### Findings

**BLOCKER 1: the plan is bound to an outdated spec.** Besides the hash, R1 (`plan.md:290-298`) still says SC-08 expects `localhost` to be *accepted* and leaves that case pending. The approved contract (`test-contract.md:179-181`) already expects it to stay refused, so option (a) was applied.
*Fix:* update the hash, delete R1, and make the `localhost` case a normal test in SL-01.

**BLOCKER 2: on the default root, `reset` fails at the `processing` seed step.** This is verified in the code:
- `seed_processing` calls `manager.add_source(root/"scanner")` (`tests/seed_processing.py:39`).
- That goes through `separate_folder` (`manager.py:1264`), which refuses any folder overlapping the checkout (`paths.py:75-83`).
- `tests/.tmp` is inside the checkout. Only `validate_managed` has the `tests/.tmp` exemption (`paths.py:62-63`).

The same check would also refuse SC-04 step 3 (watching `uploads`) and backups into the root. All the plan's subprocess tests use a `tmp_path` root outside the checkout, so they would pass while the real instance breaks.
*Fix:* while the sandbox is active, `separate_folder` exempts paths under the sandbox root. Add one test whose root is a unique folder under `tests/.tmp`.

**BLOCKER 3: `finding` can delete any file on the machine.** The error table (`plan.md:197`) says a screenshot outside `evidence/` is refused *and deleted*. So `--screenshot P:\Finances\…`, or a mistyped path, deletes that file, which breaks I-1.
*Fix:* delete only when the resolved path is inside `<root>/evidence`. Otherwise refuse and leave the file alone.

**MAJOR 1: FR-14 doesn't hold for the risk it targets.** A7 step 3 (`plan.md:152`) checks that the instance named in `session.json` is in test mode. It never checks which page the screenshot came from. The risk-5 case is a test instance running while the agent screenshots the live app on 8765. That screenshot passes. SC-15 only passes because the test points `session.json` at the stub.
*Fix:* `finding` takes `--url` and takes the screenshot itself with Playwright. It requires the URL's origin to equal `base_url` and `#test-instance-marker` to be visible.

**MAJOR 2: `stop` can kill an unrelated process.** `server.pid` can be stale after a crash or reboot. `stop` then sends CTRL_BREAK and TerminateProcess to whatever process now has that pid (`plan.md:120,194,199`). `reset`'s "pid is live" check (`:97`) has the same problem and will refuse spuriously.
*Fix:* store the pid with the process creation time, or check the command line, before signalling.

**MAJOR 3: `verify` fails as soon as an agent changes anything.** `verify` requires manifest counts to equal DB counts (`plan.md:125`). The skill tells agents to run `verify` first (A8.1). After any added transaction or deleted document, every later session fails `verify`, even though restarting without a reset is supported (SC-18). → **HUMAN DECISION** on what FR-09 "matches" means. I recommend: `verify` checks that `seed.json` exists, there is no `.seed-incomplete`, and the DB opens. Exact count equality goes behind a `--fresh` flag used only by tests and right after `reset`.

**MAJOR 4: SC-08 passes without the new code.** `192.168.1.50` and `example.invalid` are already refused today (`vision.py:33`). The only path test mode actually closes is a Tailscale address (`vision.py:77-78`, also used by `decisions.py:71`), and nothing tests it.
*Fix:* add `http://100.64.0.1:1234/v1` and a `*.ts.net` name to SC-08's cases. SC-11 step 3 ("accepted, as today") is only true for a Tailscale address, so the plan should say SC-11 step 3 uses one.

**MINOR**
- `--target` accepts any path, so an agent can append text to any file. Allow only `docs/bugs.md` or a path under `--root`.
- `finding` writes without a lock, so two agent sessions writing at once can corrupt `bugs.md`. Add a lock file and write atomically (`write_atomic` already exists).
- SC-09 step 2 ("on another date") needs a date override that the plan doesn't define.
- Your current `tests/.tmp` has content but no sentinel, so the first `reset` refuses. Give the default root a one-time exemption using the spec's I-3 "inside the checkout" check.
- `reset` deletes `evidence/`, which leaves `bugs.md` entries pointing at missing screenshots. Keep `evidence/` across resets, or say in the plan that it is lost.
- `reset` asks LM Studio for model names (`plan.md:101-102`). That makes the settings depend on what LM Studio has loaded, and the plan doesn't say what happens if LM Studio is down at reset.
- FR-03's "Settings › Models shows the LM Studio address" isn't asserted in any test.
- `no_egress` as the plan defines it ("wraps the audit-hook refusals", `:263`) would record nothing when test mode is off, so SC-11 step 4 can't be checked. Define it as a socket-level spy that records the host and then calls the real function, as the contract specifies.

**INFO (verified)**
- Every user-typed path does go through `local_absolute` (`manager.py:356, 376, 403, 411, 430, 503, 581, 605, 1264, 2167, 2180-81, 2241, 2278`). Family folders are opened before validation (`:401, :498`), but they only ever come from already-validated inputs.
- All three outbound callers use `http.client`, which ignores proxy settings, and each catches `OSError`, so the audit-hook approach holds.
- The app's child processes (the two tax engines and the receipt-image helper) are outside the hook. They make no network calls today.
- The stub the plan cites is at `conftest.py:113`, not `:109`.
- R2's narrower reading of FR-13 is reasonable but differs from the spec text. Note it in the spec, or accept it when approving.

### Coverage
Every requirement (FR-01–18, I-1–6) and scenario (SC-01–19) maps to a slice. The gaps are the tests under MAJOR 4, the date override under MINOR, and FR-14's agent-side check, which stays manual by design.

**Next:** revise the plan for BLOCKERs 1–3 and MAJORs 1, 2 and 4, decide MAJOR 3, then run `review-plan` again before `gate.py approve --stage plan`.

## Round 2

### Plan review: agent-test-instance

**Verdict: REVISE.** The plan maps every FR and SC to a slice and is well grounded in the code. Three problems in the test design and the seed would make planned tests fail or leak network traffic. Each has a small fix.

**Gate:** the spec is approved (`b2834186f166`, 2026-10-17 22:38). The hash in the plan matches what `gate.py hash` computes now.

### Verified against the code
- **One path guard covers every input.** Every path input P1–P11 goes through `local_absolute`. The callers are at `manager.py:356, 376, 403, 411, 430, 503, 581, 605, 1264, 2167, 2180-2181, 2241, 2278`. Putting the check before `safe_path` (`paths.py:37`) is the right spot.
- **Checkout exemption is needed.** `separate_folder` refuses any folder overlapping the checkout (`paths.py:80-82`). Without the plan's exemption, the seed's watched folder would be refused on the default root.
- **Existing error handling gives the offline states.** The outbound callers already catch `gaierror` / `OSError` (`web_lookup.py:42,74`, `family_client.py:72,82,187`).
- **Hub wrap is right.** `family_hub` imports `tailnet_address` by name (`family_hub.py:37`), so wrapping it there works.
- **Coverage is complete.** Every FR-01–18 and SC-01–19 has a slice and a test. FR-18 is manual by design.

### MAJOR

**M1. The copied seed root used by the test fixture points at the original root.**
- `profiles.json` stores the library folder as an absolute path (`profiles.py:82`, `str(folder)`). The seeded watched folder is also stored absolute (`seed_processing.py:39`, read back at `manager.py:268`).
- **Failure:** `seeded_instance` "copies the seeded root for each test." Each copy's `serve` then tries to open the original library. The sandbox refuses it because it is outside the copy's root, so the server doesn't start.
- **Fix:** keep one template and copy it back to the same root path before each mutating test. Or run a real `reset` in the tests that change data (SC-10, SC-18, SC-19, SC-07, SC-06d).

**M2. Empty model names break SC-06d and every agent upload after a reset.**
- `reset` step 5 leaves the model names empty. But `receipt_service.py:56` won't read a non-PDF document without a vision model.
- **Failure:** SC-06d expects the double to record vision and reasoning requests and the document to reach read. Instead the read is refused. Every `reset` also wipes the developer's model choice, so agent sessions start with failing uploads and report false findings.
- **Fix:** add `--vision-model` / `--reasoning-model` options (or `HM_TEST_*` settings) that `reset` writes. SC-06d passes the double's model names.

**M3. The `no_egress` test double can let real traffic out.**
- The plan's spies call the real `socket.getaddrinfo` / `create_connection` first, and only refuse afterwards.
- **Failure:** if the sandbox hook is broken (the case these tests exist to catch), `create_connection` completes a real TCP connection to, for example, CoinGecko. SC-11 step 4, with the sandbox off on purpose, always makes a real DNS lookup. This contradicts the contract's convention ("refuse any host that isn't loopback") and the plan's own "nothing reaches the network."
- **Fix:** for a non-loopback host, the spy calls `sys.audit("socket.getaddrinfo", …)` or `sys.audit("socket.connect", …)` itself. If the sandbox is on, its hook raises there. The spy records whether that happened, then refuses without calling the real function.

### MINOR

- **m1. The seed would move the library.** `ui_shots.py:43` calls `manager.configure(str(root/"managed"))`. After `reset` creates the `test` profile, that call moves the profile's folder to `<root>/managed` (`manager.py:361-362`). That breaks FR-01 / SC-01 step 2, which want `<root>/library`. Fix: let `seed` take the library path, or skip `configure` when a library is already open.
- **m2. The reviewer points at a dead port.** `seed_settings` (`ui_shots.py:91`) points the reviewer at the fake model server's temporary port, which is gone after `reset`. Step 5 repoints only vision and reasoning. Fix: repoint or clear the reviewer, and state what happens to the decision setting.
- **m3. FR-12 says `start` warns too.** The plan only warns from `verify` when something listens on 8765. Add the warning to `start` and a check in SC-12.
- **m4. FR-16 says any refusal deletes the screenshot.** The plan deletes it only when the page check fails. For no `session.json`, a bad target or a lock timeout, the screenshot stays. Never touching files outside `evidence/` is right. Fix: delete a screenshot inside `evidence/` on every refusal, or list this as a deviation to approve.
- **m5. FR-16's marker check is replaced.** The plan checks the page origin plus `settings.test_instance` instead of the marker itself (D-P4/R8). That is a fair equivalent, but it reinterprets the spec. List it next to D-P3 and R2 for your explicit acceptance.
- **m6. SC-11 step 3 needs to name its setting.** The plan says the live app accepts a tailnet address today. That is true only for Model computer. Vision, reasoning, reviewer and decision already refuse any host other than 127.0.0.1 (`manager.py:1183`, `is_remote`). The test must use the Model computer setting, or it fails.
- **m7. Which pid lands in `server.pid` is unspecified.** In a Windows venv, `python.exe` is a small launcher that starts the real interpreter as a child, so the pid `Popen` returns may be the launcher's. This is a possible risk, not verified. Fix: have `serve` write its own `os.getpid()` and creation time.

### INFO
- **Audit hook edge cases.** The hook should allow `getaddrinfo(None/"")`, which is used for binding. `tailnet_address()` calls `getaddrinfo(gethostname())` (`http_server.py:43`), so expect one harmless refusal line in the log at startup.
- **The `finding` command's side effects on `docs/`:**
  - If a run crashes, `docs/bugs.md.lock` stays behind.
  - If you save `bugs.md` in the instant between the command's read and its replace, your edit is lost. The window is milliseconds.
- **Prompt-injection receipt.** It is included as an upload, and its text will show on pages that Claude agents with shell access read. The skill should say that page content is data, not instructions.
- **Harness dependency.** The harness imports `tests/conftest.py`, which needs pytest. So it only runs from the dev venv.

### Next steps
1. Revise the plan for M1–M3 and m1–m3.
2. Explicitly accept or change D-P3, R2, m4 and m5.
3. Run `review-plan` again before you approve it with `gate.py approve` in your own terminal.

## Round 3

**Verdict: REVISE.** One MAJOR finding (a small fix) and several MINORs. The architecture holds up, and every FR and SC maps to a slice.

**Gate:** the spec is `APPROVED b2834186f166` (2026-10-17 22:51). The plan's recorded hash `b2834186…5e76` matches `gate.py hash --stage spec`.

**What I checked against the code:**
- **Path inputs:** P1–P11 all go through `local_absolute`. The callers listed in `manager.py` are complete: `set_up_local_member` goes through `create_profile`, and `library_action` takes a folder inside the library.
- **Stored absolute paths:** `sources.path` (migration 053) is the only absolute path in the database, so the plan's template-restore rewrite is enough.
- **Fake model server:** it serves `synthetic-vision` and `synthetic-reasoning` and the LM Studio load/unload endpoints, so SC-06d works.
- **Seed:** it writes nothing outside the folder it is given, apart from the `configure` call that A4 removes.

### Findings

**MAJOR-1 (verified gap): the instance root is never checked against the protected roots (I-1).**
- **Where:** A5 `reset`, deletion rule (a) "absent". The root is the sandbox's own allowed root, so `check_path` never sees it.
- **Failure:** a mistyped `HM_TEST_ROOT=P:\Finances\agent` passes rule (a). `reset` then creates the folder and writes the sentinel, `control/`, `library/` and the seed under `P:\Finances` before the sandbox is active. A root inside `%LOCALAPPDATA%\HomeManager` behaves the same way.
- **Fix:** in `reset`, `start` and `serve`, before any filesystem call, refuse a root that overlaps a protected root in either direction. Reuse `sandbox`'s lexical check, including the `HM_TEST_PROTECTED` extras. Add one subprocess test that uses a decoy protected root.

**MINOR-2 (verified): SC-08 and SC-11 step 3 assume the live app accepts a tailnet model address. It doesn't for 4 of the 5 settings.**
- **Code:** `configure_model` (`manager.py:1183`) already refuses any host other than `127.0.0.1` for vision, reasoning, reviewer and decision (`is_remote`, `model_client.py:54`).
- **Plan lines affected:** line 297 ("both refused only in test mode") and line 358 ("which the live app accepts today") are only true for the model computer (`ModelComputer.tailnet_only`, `vision.py:102`).
- **Failure:** the planned SC-11 step 3 test and the test-mode-only tailnet assertions in SC-08 fail for vision, reasoning, reviewer and decision.
- **Fix:** scope "tailnet accepted live, refused in test mode" to `PUT /api/model-computer`. For the other four, assert refusal in both modes.

**MINOR-3 (verified): the seed step names don't match the contract.**
- SC-13 uses `HM_TEST_SEED_FAIL=seed_investments` and expects stderr to name `seed_investments`.
- A4 names the steps `investments` and so on.
- **Fix:** name the steps `seed_<x>` in A4, or state that the plan accepts the contract's spelling.

**MINOR-4: SC-09 needs a running server, and the plan doesn't say which one.**
- `finding` check 5 calls `GET {base_url}/api/settings`. SC-09's environment is only "a `session.json` fixture", and SL-05 doesn't name a server fixture.
- **Fix:** name one, for example an in-process `create_app` with the sandbox active on a uvicorn thread.

**MINOR-5: the agent/session field is optional, but FR-10 requires it.**
- A7 makes `--agent` optional, and FR-10 lists agent/session among the required fields of every finding.
- **Fix:** make `--agent` required, or define its default value.

**MINOR-6: `finding` can overwrite the developer's own edits to `docs/bugs.md`.**
- The lock only coordinates `finding` runs with each other. `write_atomic` replaces the whole file from a read taken earlier.
- **Failure:** if the developer saves `bugs.md` in the IDE while triaging and agents are running, that edit is lost.
- **Fix:** re-read the file and compare it with the first read just before `os.replace`; if it changed, refuse with exit 3.
- Also, a crash leaves `docs/bugs.md.lock` and `docs/bugs.md.pending` in the repo. Add both to `.gitignore`.

**MINOR-7 (security hardening): `finding` sends the bearer token to whatever `session.json.base_url` says.**
- `finding` runs outside the sandbox, so nothing stops that request.
- **Failure:** an edited or corrupted `session.json` makes it send the token to a non-loopback host.
- **Fix:** require `base_url` to be `http://127.0.0.1:<port>` before making the request.

**MINOR-8 (possible risk, not verified): the egress hook's loopback list is narrower than the test double's.**
- The sandbox hook allows only `localhost`, `127/8` and `::1`. The `no_egress` double also allows `None` and `""`.
- **Failure:** a passive lookup for a bind, such as `getaddrinfo(None, …)`, would make the instance fail at startup.
- **Fix:** let host `None` and `""` through in the hook, the same as the double.

**MINOR-9 (possible risk): `stop` may always fall back to a hard kill.**
- `CTRL_BREAK_EVENT` only reaches a process group on the caller's own console. A `stop` from a different shell than `start` (an agent's Bash, another terminal) would probably wait 10 s every time and then terminate the server.
- Whether uvicorn shuts down cleanly on SIGBREAK is also unverified.
- SC-10 checks that the port is free within 10 s, which could flake.
- **Fix:** have `serve` also watch for a `<root>/stop` request file, or say that SC-10 measures from when `stop` returns.

**INFO**
- `verify`'s guard check reads the `test_instance` status flag rather than testing the guards. That's acceptable, because the SL-01 tests exercise the guards themselves.
- `reset` seeds with the egress hook on, and `ui_shots.py` seeds without it. Any seed step that depended on the network would give different counts in the two. I found no such step.
- SC-07 steps 2–3 (upload while LM Studio is down; seeded screens still render) map to SL-03, but no named test covers them. Add one to the SL-03 list.

### Coverage

FR-01 to FR-18, I-1 to I-6 and SC-01 to SC-19 (including SC-06d) all have a slice and a verification. Apart from SC-07 steps 2–3 above, the gaps are the ones named in MINOR-2 to MINOR-5. The expected states come from the spec, and the test oracles are independent of the code under test: raw `sqlite3` counts, file hashes, bind checks and the model double's `state["requests"]`.

**Next step:** fix MAJOR-1 and MINOR-2 to MINOR-5 in the plan (the rest can be one-line notes), then re-run `review-plan` before you approve it.

## Round 4

### Plan review: agent-test-instance

**Gate:** the spec is APPROVED (`b2834186f166`, 2026-10-17 22:59). The plan's recorded hash matches `gate.py hash` exactly (`b2834186f166…5e76`).

**Coverage:** every requirement (FR-01 to FR-18), invariant (I-1 to I-6) and scenario (SC-01 to SC-19) maps to a slice and a test. SC-16 is covered by SC-09 and SC-06 by the opt-in twin, and FR-18 is a manual check, as the contract allows. Gaps are listed under the minor findings below.

**Checked against the code:**
- Every path input in U1 goes through `local_absolute` (`paths.py:33`), and nothing else in `src/` calls it.
- `configure_model` refuses any host that isn't `127.0.0.1` for vision, reasoning, reviewer and decision (`manager.py:1182-1185`, `model_client.py:54`).
- Only `ModelComputer` uses `endpoint_url(tailnet=True)` (`vision.py:104`).
- `configure` moves the open profile's folder when it changes the library (`manager.py:361-362`), which is why the plan's A4 change is right.
- The rate refresh runs at profile open (`manager.py:416`).
- There is no offer letter in `evals/synthetic.py`, and the deliberate injection receipt is at `:210`.

### Findings

### MAJOR

**M1. The real-path spies are scoped to all of `LOCALAPPDATA`, which breaks SC-03 and SC-14 as written.** (Verified)
- **Where:** the plan's test environment section says the spies raise on "the real `LOCALAPPDATA`". The contract only protects `<LOCALAPPDATA>\HomeManager`.
- **Failure:** on this machine `TEMP` is `C:\Users\Anirudh\AppData\Local\Temp`, inside `LOCALAPPDATA`. pytest's `tmp_path` lives under `TEMP`, so every decoy, control folder and instance folder trips a spy. All the in-process guard and UI tests fail.
- **Related wording in A1:** "`%LOCALAPPDATA%` is expanded at activation" reads the same way. If the sandbox protected all of `LOCALAPPDATA`, the root check would also refuse every in-process `tmp_path` root.
- **Fix:** say `%LOCALAPPDATA%\HomeManager` explicitly, in both the spies and `sandbox.activate`.

**M2. Restoring the test template rewrites too few absolute paths.** (The columns are verified; that they hold absolute paths is inferred.)
- **Where:** the `seeded_instance` fixture rewrites only `profiles.json`, the `sources` table and `seed.json`.
- **Failure:** the library database has more path columns: `source_root` (`001_inventory.sql:3,18,50`, `003_batches.sql:3`, `050_strict_tables.sql`) and `source_path` / `target_path` (`008_managed_library.sql`). The inbox scans in the seed fill them.
  - Plain string prefix replacement also misses `profiles.json`, because JSON escapes backslashes as `\\`.
  - Either the fixture's "nothing names the template" assertion fails, or the copied instance points at template paths that the sandbox refuses.
- **Fix:** don't move the template. Run `reset` once into the fixed run root, copy that tree aside while the instance is stopped, and restore by copying it back to the **same** path. Nothing needs rewriting, and `test_restored_instance_is_independent` still applies.

### MINOR

**m1. Child processes are outside both `stop` and the egress hook.** (Possible risk)
- The server starts its own subprocesses: the receipt worker (`receipt_service.py:229`) and the two tax engines (`taxcalc.py:214`, `opentax.py:198`).
- `stop`'s fallback terminate kills only the server's pid. A worker mid-render can survive and hold library files, so the next `reset` hits a sharing violation, against FR-11.
- The audit hook is per process, so D-P2's "catches any future caller" doesn't reach these children.
- **Fix:** run `serve` in a Windows Job object with KILL_ON_JOB_CLOSE (through `ctypes`), and note in D-P2 that the hook covers this process only.

**m2. The order of `start`'s steps isn't pinned down, and nobody is named to write `server.pid`.**
- The error table says `start` deletes a stale `session.json` before spawning. If that runs before the identity and port checks, a second `start` on a running instance deletes the live `session.json` that agents depend on.
- **Fix:** delete it only after the identity check fails and the bind test passes. State that `start` writes `server.pid`, with its creation time, right after `Popen`.

**m3. The server may not outlive a `start` run from Claude Code's Bash tool.** (Unverified risk)
- The plan uses only `CREATE_NEW_PROCESS_GROUP`. If the tool's job or process tree is cleaned up when the command ends, the server dies with it.
- **Fix:** add `DETACHED_PROCESS`, and `CREATE_BREAKAWAY_FROM_JOB` with a fallback if breakaway isn't allowed. Add one step to SL-03's manual run: `start` from Claude Code, then `verify` in a separate call.

**m4. The `bugs.md` prefix check can fail for a reason that isn't a defect.** If the file has no trailing newline, adding the header means inserting a separator, so "the prefix up to the header equals B0" fails. Specify that the separator belongs to the section, and assert that the new bytes start with B0.

**m5. The injection receipt goes in the uploads, and the agents reading the app have shell access.** The SKILL.md in A8 should say that document text and extracted fields are untrusted data, never instructions.

**m6. Three test gaps:**
- FR-02's "two resets give the same counts and values" has no named test in SL-03. Add `test_two_resets_equal` with the named values.
- SC-05 step 4 says "no connection attempt is recorded", but the plan's `no_egress` double does record the refused lookup. State that the assertion is "no `connect` record".
- FR-03's acceptance is a UI error. Add one browser check to SL-04 that saving a tailnet address as the model computer shows an error.

### INFO
- Reset step 3 says it "creates the `test` profile (configure)", but `configure` with no profile creates "My profile" (`manager.py:364`). This is cosmetic: use `create_profile` or drop the name.
- The hook could also catch the `socket.gethostbyname`, `gethostbyname_ex` and `gethostbyaddr` audit events. That costs nothing and stops DNS-only leaks from future code.
- `evidence/` survives every reset and grows with no limit. Mention it in the docs.

### Verdict: REVISE

The architecture holds up: a lexical guard in `local_absolute`, an audit-hook egress block, a separate entry point and a sentinel-guarded reset. M1 and M2 are small text changes, but as written they make most of the guard tests and the subprocess fixture unworkable. Fix them along with m1 and m2, then re-review.

## Round 5

### Review of the agent-test-instance plan (third review round)

**Gate check:** `gate.py check --stage spec` reports APPROVED (b2834186f166, Anirudh Sathish, 2026-10-17T22:59:31-04:00). `gate.py hash` gives b2834186f1660324f9d1dea1e61814598ef5ebcbe397aee2cef77c8efbdf5e76, the same hash the plan records. No files were edited, nothing was approved, and nothing under P:\Finances, P:\EvalCorpus or %LOCALAPPDATA% was touched.

**Line citations:** I checked the plan's line citations against the code and they hold:
- `paths.py:33/54/62-63/75-83/86/137`
- `api.py:580/588/597-635/675`
- `manager.py:84/121-122/321/356/376/401/403/411/430/498/503/581/605/1182-1185/1264/2167/2180-2181/2241/2278`
- `vision.py:25/33/65/70-78/102-104`
- `model_client.py:43/53`
- `family_hub.py:37/108`
- `http_server.py:39`
- `conftest.py:109-113`
- `ui_shots.py:40-154` (configure at :43, reviewer at :91, car loan at :115)
- `evals/synthetic.py:198/210/241/244/262/280`
- `pyproject.toml:42-45`
- `seed_processing.py:39`

U1 still holds: every path field in `api.py` goes through `local_absolute`. `LocalMemberInput.folder` (`api.py:145`) is not in U1, but it reaches `create_profile` and then `validate_managed` (`manager.py:568`), so it is covered too. The earlier decisions D-P3, D-P4/R8, D-P5 and R2 are consistent with the spec and the code, and I have not reopened them.

### BLOCKER
None.

### MAJOR

**M-1. The `lmstudio` tests are registered but never skipped by default** (plan sections: Verified integration points, "Pytest config"; SL-03).
- **Evidence:** the plan says only "Register the `lmstudio` marker". `pyproject.toml:42-45` has `addopts = "-ra"` and no marker filter. The contract's model-doubles convention requires these tests to be "skipped by default and run by the developer".
- **Why it matters:** registering a marker doesn't skip anything. SL-03's own verification command (`pytest tests/test_agent_instance.py`) would run SC-06 against the real LM Studio at 127.0.0.1:1234. On a machine without LM Studio it waits up to 300 s and fails; on the developer's machine it sends real model requests during the targeted run. Either way the contract is broken.
- **Fix:** add a default exclusion, either `addopts = "-ra -m 'not lmstudio'"` or a `conftest.py` hook that skips `lmstudio` tests unless `-m lmstudio` or an opt-in variable is given. Add a static check that the default run deselects SC-06.

### MINOR

**m-1. Who writes `server.pid` is not stated, and the venv launcher makes this matter** (A5 "Process identity", `start` and `stop`).
- **Evidence:** `.venv/Scripts/python.exe` is 255 KB, which is the venv redirector, not the interpreter. `pyvenv.cfg` points at `C:\Program Files\Python313\python.exe`. So the pid that `Popen(...)` returns is the launcher's, not the server's.
- **Why it matters:** the old `environment.json` `start` records `p.pid`. If the new script does the same:
  - the creation-time identity check and the stop fallback act on the launcher;
  - SC-10's "no process alive (by recorded pids)" passes even if the real server is still running.
- **Fix:** have `serve` write `server.pid` itself, using `os.getpid()` and its own creation time, after uvicorn starts and before `session.json`. `start` waits for both files. Add an assertion in `test_stale_pid_is_not_signalled` or SC-10 that the recorded pid is the process that holds the port.

**m-2. The `no_egress` double raises the wrong exception type for a refused DNS lookup** (Test environments, `no_egress`).
- **Evidence:** the plan says that when the sandbox doesn't raise, the double "raises `ConnectionRefusedError` itself" for any refused host, including `getaddrinfo`. But:
  - `web_lookup.public_address` (`:40-43`) catches only `socket.gaierror`;
  - `https_get` calls it outside its `try` (`:56`);
  - `fx.py:139` and `prices.py:142` catch only `LookupFailed`.
- **Why it matters:** with the sandbox off (SC-11 step 4, SL-05 `test_non_loopback_base_url_refused`), the double's `ConnectionRefusedError` escapes `https_get` as a raw `OSError`. The rate or price refresh then crashes or returns a 5xx. That is a test-only artifact, but it can fail or hide results.
- **Fix:** the double should raise `socket.gaierror` for refused `getaddrinfo` calls (the same type the sandbox hook raises) and `ConnectionRefusedError` only for `connect`.

**m-3. The `bugs.md` prefix can't be byte-identical as worded** (A7 step 7; contract SC-09).
- **Evidence:** I checked `docs/bugs.md` with a read-only `od`/`grep`: it has 29 lines, CRLF line endings, no `#` headings, and **no trailing newline** (it ends with "screen. ").
- **Why it matters:** to append `## Agent findings`, the writer has to insert a line break first. So "the prefix of the file up to the section header is byte-identical to B0" fails as written, unless the test is read as "the new file starts with B0".
- **Fix:**
  - In the plan, say the assertion is `new_bytes.startswith(B0)`. The writer inserts the target's own newline (CRLF here) before the header when B0 lacks a trailing newline.
  - Add a no-trailing-newline variant to SC-09 (the real file is in that state).
- See also spec note S-2.

**m-4. Setup for SC-05 step 4 (family sync to a 100.64.0.1 member) is undescribed** (SL-01).
- **Evidence:** in test mode `tailnet_address()` returns `None`, so `invite_member` raises "can't reach" (`manager.py:582-584`). `join_family` needs an invite file read through `local_absolute` (`:605`).
- **Why it matters:** no API path can create a remote link to 100.64.0.1 in test mode, and the plan doesn't say how the test creates one.
- **Fix:** state that the test writes an invite with `family_sync.write_invite(...)` into `<root>`, or writes the profile's `family` link directly. Then it triggers publish or refresh and asserts `refused_by="sandbox"` for 100.64.0.1.

**m-5. Where the marker goes is not tied to the real DOM** (A3).
- **Evidence:** `index.html:50-64`. There is no shell header: the shell is `aside.sidebar`. Below 820 px it becomes a top bar, and its contents sit in `#sidebar-sheet`, which is collapsed behind `#nav-toggle`. There is also a collapsed icon-only sidebar where `.nav-label` text is hidden.
- **Why it matters:** if the marker lands inside `#sidebar-sheet` or relies on label text, FR-08 ("visible on every route at 390/768/1440") fails at 390 and on the collapsed sidebar.
- **Fix:** name the exact location: a direct child of `aside.sidebar` outside `#sidebar-sheet`, or a fixed banner outside the sidebar. Make sure it shows text, or an icon plus a visible label, in collapsed mode.

**m-6. Copying the template instance can leave paths behind without failing the check** (Test environments, `seeded_instance`).
- **Evidence:** `profiles.json` stores Windows paths JSON-escaped (`C:\\...`).
- **Why it matters:** a plain prefix replacement plus a plain byte search for the template path can both miss the escaped form. The fixture then believes it is independent while the server still opens the template's library (the sandbox would refuse it, giving a confusing failure).
- **Fix:** rewrite paths by parsing JSON and SQLite values, not by byte replacement. Search for raw, JSON-escaped and forward-slash forms of the template root, and also open each `sources.path` and profile folder and check it lies under the run root.

**m-7. The test profile's name and id change from today** (A5 `reset` step 3).
- **Evidence:** `reset` uses `configure`. With no active profile, that calls `profiles.add("My profile", ...)` (`manager.py:363-364`). The baseline `environment.json` reset writes `id: "test", name: "Test"`.
- **Why it matters:** this is harmless for the FRs, but the plan says it "creates the `test` profile".
- **Fix:** either say the profile is called "My profile", or create it by name and folder through `create_profile` and then `switch_profile`, or rename it after `configure`.

**m-8. Two different logs, and "the instance log" is ambiguous** (A5 `serve` and FR-05 tests).
- **Evidence:** `serve` sends stdout to `<root>/server.log` and the app log to `<root>/control/logs` (`core/logs.py:38`).
- **Why it matters:** the subprocess tests "check the instance log" for refusal lines without saying which file. The `log.warning` refusal lines go to the app log.
- **Fix:** name the file the tests grep (control/logs/…), or attach the app logger to stdout in `serve`.

**m-9. Scripted outputs for SC-06d are unspecified** (Test environments, Models).
- **Evidence:** `tests/model_server.py:96` returns `state["output"]` (a vision `full_text`) for every request unless `outputs` is scripted.
- **Why it matters:** SC-06d's "document reaches read", and the plan's "records exactly the vision and reasoning requests", depend on scripted outputs for the grocery upload. Without them, the reasoning step gets a vision-shaped reply.
- **Fix:** state that the test scripts `state["outputs"]` from the upload's known lines, following the pattern of `seed_documents._read_and_record` (`seed_documents.py:26-33`).

### Findings that go back to the spec
- **S-1 (SC-11 step 3 and FR-03 wording).** The contract says saving "a non-loopback model address" is "accepted, as today". In the code, the live app already refuses every LAN or public address (`vision.py:33`) and refuses tailnet hosts for vision, reasoning, reviewer and decision (`manager.py:1182-1185`). The only setting that accepts a non-loopback (tailnet) address today is the model computer. The plan works around this correctly. Next time the spec is opened, SC-11 step 3 should say "a tailnet model-computer address", so the contract matches the code.
- **S-2 (SC-09 byte-identical prefix).** As in m-3, the contract's "prefix up to the section header is byte-identical to B0" can't hold when B0 has no trailing newline, which is the real `docs/bugs.md` today. The spec should say "the new file starts with B0's bytes".

### Not defects
- **INFO-1. Duplicates by rewording.** Duplicate detection uses an exact key on the normalized symptom. An agent that rewords a symptom creates a second entry. FR-10 leaves deciding "same route and symptom" to the agent, so this is accepted, but the skill should tell agents to reuse the existing symptom text.
- **INFO-2. Slower seeding.** `reset` builds its Manager without `ScanLimits(stability_seconds=0)`, unlike `ui_shots.py:176`. Each seeded capture then waits about 1 s (`scanner.py:22,113`). That only adds time (R4); passing the zero-stability limits would match `ui_shots`.

### Coverage
Every FR-01…FR-18 and SC-01…SC-19 is mapped to a slice and a test. The I-1…I-6 mappings are present. The only coverage gaps are the default skip for `lmstudio` (M-1) and the undescribed setup for SC-05 step 4 (m-4).

### Verdict: REVISE
M-1 is a one-line fix but breaks the contract's default-skip rule as written. m-1 to m-3 are small edits to the plan text; m-4 to m-9 are clarifications. No re-architecture is needed, and I found no blockers.

## Round 6

### Plan re-review: agent-test-instance (revised plan)

I read the spec, the test contract, the plan and the code it cites. I edited nothing.

**Gate:** `gate.py check --stage spec` gives APPROVED b2834186f166. The bundle hash `b2834186f1660324f9d1dea1e61814598ef5ebcbe397aee2cef77c8efbdf5e76` matches the plan header.

**Verdict: REVISE.** There is one MAJOR finding and four MINOR ones. Each fix is a few lines in the plan. No decision needs reopening.

### Status of each prior finding

| ID | Status | What I checked |
|---|---|---|
| M-1 | **Resolved** | `pyproject.toml:45` has `addopts = "-ra"` today. Pytest puts `addopts` in front of the command-line arguments, and `-m` keeps only the last value given, so a command-line `-m lmstudio` replaces the default `-m "not lmstudio"`. `test_lmstudio_deselected_by_default` (collect-only in a subprocess) is a sound test of this. INFO: any other command-line `-m` expression also drops the default, so `-m "not slow"` would bring the lmstudio tests back in. No other markers exist today. |
| m-1 | **Resolved** | `serve` records its own `os.getpid()` and creation time, so the pid is not the venv launcher's. Checking it with `GetExtendedTcpTable` in `test_pid_is_the_server` can be done. |
| m-2 | **Resolved** | `web_lookup.py:40-43`: `public_address` catches only `gaierror`, and `:56` calls it outside the `try`. `no_egress` raising `gaierror` for getaddrinfo is therefore correct. |
| m-3 | **Resolved** | `docs/bugs.md` is 3901 bytes, CRLF only (no lone LF), and its last bytes are `screen. ` with no newline. The `startswith(B0)` oracle and `test_no_trailing_newline_prefix` match this. Spec-level note S-2 is below. |
| m-4 | **Workable, but the fix has an error** | See MINOR N-1. `join_family` (`manager.py:597-613`) only needs an open individual profile. The invite path goes through `local_absolute` and is allowed inside the root. `join_family` calls `start_family_publish` → `start_family_sync` itself (`:612`, `:669-694`). The first step there is `pull_deliveries` → `_request`. No hub or family computer is needed on the member side. |
| m-5 | **Resolved** | `style.css:172` makes `#sidebar-sheet` `display: contents`. At 1279px and below the sidebar becomes a 64px rail that hides `.brand-name` and `.nav-label` (`:1268-1276`). Below 820px the brand and `#nav-toggle` sit in a row and the sheet is hidden (`:1286-1292`, `:173`). A direct child of `aside.sidebar` placed after `.brand` stays visible in all three layouts, and "Test data" fits beside the brand at 390px. INFO: the collapsed rail comes only from a width between 820 and 1279 (no toggle exists), and none of the spec widths 390/768/1440 falls in that range. Name a width such as 1024 in `test_marker_visible_everywhere`. |
| m-6 | **Not resolved** | See MAJOR N-0. |
| m-7 | **Resolved** | `create_profile` (`manager.py:427-441`): `<root>/library` doesn't exist after the delete, so the non-empty-folder refusal can't fire. `switch_profile` → `activate` (`:393-417`) opens the library and calls `leave_family` and `start_rate_refresh`. `start_rate_refresh` (`:1668-1692`) does nothing on an empty library, because it needs coins held or foreign amounts. No family refresh or hub start happens. After seeding, the rate and price refresh fires only at `serve` start, and the sandbox refuses it there, which is the intended behavior. |
| m-8 | **Resolved** | `core/logs.py:1,35-40`: the log is `<control>/logs/home-manager.log`. `__main__.py:33` is the only caller of `configure`, so `serve` must call it, as the plan says. In-process tests should assert through `caplog`, since there is no file handler there. |
| m-9 | **Resolved** | `model_server.py:96` pops `outputs`. I also checked that the reviewer the plan configures does not add a request to SC-06d. It runs only in `reason_and_file` (`manager.py:2062-2071`), which is reached from `start_reasoning` (`:1474`), not from Inbox extraction. Only POST requests are recorded (`:85`), so residency's GETs don't count. |
| INFO-2 | **Adopted** | Matches `ui_shots.py:176`. |
| S-1 / S-2 | Recorded as notes | Flagged as spec-level below. |

### Findings

**MAJOR N-0: the template-restore fixture misses absolute paths stored in lowercase, and its own check can't see them** (plan section "Test environments", the subprocess `seeded_instance` fixture, step 2)
- **Evidence:**
  - The library database stores `path_key(...)`, which is `os.path.normcase` and so lowercase on Windows (`paths.py:50`), of the **absolute** Inbox path in four places: `jobs.source_root` (`storage.py:270-271`), `occurrences.source_root` (`:402-405`), and the `receipt_batches` and `capture_intents` keys (`receipt_batch.py:46`).
  - These keys are compared against the current Inbox: `storage.py:386-387`, `:412`, `:439-440`, `managed_library.py:161-162`.
  - `sources.path_key` (`053_sources.sql:7`, `storage.py:295-298`) is also stored lowercase.
  - The app's own restore rewrites exactly these four tables for this reason (`backup.py:217-221`: "Documents captured through Inbox are keyed by the Inbox's absolute path").
  - The plan rewrites only `profiles.json`, `seed.json` and `sources.path`. Its leftover search covers the raw, JSON-escaped and forward-slash forms. On Windows `tmp_path` contains capitals (`C:\Users\Anirudh\AppData\...`), so the lowercased keys pass that search.
- **Why it matters:** this fixture backs SC-02, SC-06d, SC-07, SC-10, SC-12, SC-18 and SC-19. In a restored copy, the seeded occurrences point at the template's Inbox key. The `UNIQUE(source_root, path_key)` dedupe no longer matches. Any Inbox file the seed left behind, or the same name added again, is captured a second time, and missing-file and `source_kind` checks go wrong.
- **Credible failure:**
  - `verify --fresh` or SC-10's C0 count fails on a restored instance and not after a real `reset`, an intermittent failure blamed on the harness.
  - Or the tests pass against a copy that behaves differently from a real reset, while `test_restored_instance_is_independent` reports the copy as clean.
- **Fix:**
  - In step 2, also run backup.py's update: `UPDATE {occurrences,jobs,receipt_batches,capture_intents} SET source_root=path_key(run/library/Library/Inbox) WHERE source_root=path_key(template/library/Library/Inbox)`, and update `sources.path_key` along with `sources.path`.
  - Make the leftover search also look for the `normcase` (lowercase) forms of the template root, and leave out or delete logs the template's reset wrote.
  - Have `test_restored_instance_is_independent` drop a file into the restored Inbox and check that exactly one new document appears.
  - Alternatively, drop the template and run a real `reset` once per module.

**MINOR N-1: the SC-05 step 4 invite uses the wrong hub format** (SL-01, "SC-05 step 4 setup")
- **Evidence:** `write_invite` takes `hub` as `"100.x.y.z:port"` (`family_sync.py:123`). `hub_address` does `rpartition(":")` and then `ip_address(host)` (`family_client.py:31-41`). The plan writes `http://100.64.0.1:<port>`. That gives the host `http://100.64.0.1`, which raises `HubError("refused")` before any socket call.
- **Why it matters:** the assertion "the 100.64.0.1 attempt is recorded with `refused_by="sandbox"`" will fail. Worse, a looser assertion such as "no connection attempt" would pass without the guard being tested.
- **Fix:**
  - Pass `hub="100.64.0.1:<port>"`.
  - Build valid `family` and `member` dicts. `read_invite` needs hex `family_id` and `member_id` (`family_sync.py:147-148`), so `FamilyFolder.create` in the root is the easiest source.
  - Wait on `manager.future.result()` before asserting.
  - Drop "then triggers a publish/refresh". `join_family` already starts the sync at `manager.py:612`.

**MINOR N-2: the browser test commands would skip everything** (SL-04 verification, plus the browser steps in SL-03)
- **Evidence:** browser tests run only with `--browser` or `RUN_BROWSER_TESTS=1` (`conftest.py:11-18`, `test_settings_browser.py:9`, `docs/development.md:87,98`). The plan's SL-04 command `pytest tests/test_agent_instance_browser.py tests/test_settings_browser.py` has neither. Nowhere does the plan say whether the new browser module follows the `browser_test` skipif convention.
- **Why it matters:** the slice's evidence would be all skips, with the only sign being the skip lines in the `-ra` summary. That breaks "never claim tests ran without evidence".
- **Fix:**
  - Add `--browser` to the SL-04 command, and to SL-03's command if SC-06d, SC-07 step 2 or SC-14 drive a browser.
  - State that `test_agent_instance_browser.py` uses the `browser_test` marker.
  - Require the slice report to give pass and skip counts.

**MINOR N-3: the hub guard conflicts with the autouse `no_tailnet` fixture** (A1 "Hub"; SL-01 files)
- **Evidence:** `conftest.py:108-113` already monkeypatches `family_hub.tailnet_address` to return `None` in every test. A1 says the sandbox "wraps it the way conftest does", while the SL-01 files column says the function "honors the sandbox". A wrapper installed at `activate()` can be undone by monkeypatch teardown, or can wrap the lambda.
- **Why it matters:** any in-process test of "the hub stays off in test mode" passes vacuously.
- **Fix:**
  - Put the check inline at `family_hub.py:108`: `None if sandbox.active() else tailnet_address()`.
  - In that test, monkeypatch `tailnet_address` to return `"100.64.0.1"` and assert that the hub does not listen.

**MINOR N-4: `test_non_loopback_base_url_refused` needs `finding` to run in-process** (SL-05)
- **Evidence:** the test asserts "`no_egress` records no attempt". `no_egress` is an in-process patch. The plan doesn't say whether SL-05 calls `finding` in-process or as a subprocess.
- **Fix:** have the SL-05 tests call the CLI's `main(argv)` in-process, at least for this test and for `HM_TEST_FINDING_DATE` through monkeypatch. Or state that this test uses a subprocess and asserts a different way.

### Coverage
Every FR-01–FR-18, SC-01–SC-19 and I-1–I-6 maps to a slice and a test in the plan's matrix. I found no gaps beyond the findings above. SC-06 (opt-in) and FR-18 (manual) are correctly labeled.

### Spec-level items (for the human; not reopened)
- **S-1 is a genuine contradiction.** The approved SC-11 step 3 says saving a non-loopback model address is "accepted, as today". The code refuses one for vision, reasoning, reviewer and decision (`vision.py:33`, `manager.py:1182-1185`), and accepts only a tailnet address for the model computer (`vision.py:101-105`). The plan's narrowing to the model computer matches the code. Amend the spec wording the next time it is opened.
- **S-2 changes the oracle.** SC-09's literal oracle is "the prefix up to the section header is byte-identical to B0". The plan inserts a CRLF before the header and counts it as part of the header, so the oracle becomes `startswith(B0)`. This is reasonable, and a no-trailing-newline file forces it. It is still a reinterpretation of the approved contract that the developer should acknowledge.

### Verdict: REVISE
Fix N-0 (the four `source_root` tables and `sources.path_key` rewrite, plus a case-insensitive leftover check), N-1 (the hub string format) and N-2 (`--browser` in the commands). N-3 and N-4 are wording-level. After that the plan should be ready to approve.

## Round 7

### Review of plans/agent-test-instance/plan.md (final cycle)

**Gate:** the spec is APPROVED. `gate.py hash` gives b2834186f1660324…5e76, which matches the plan header. The plan is not approved yet. I edited nothing and ran no approve.

### Prior findings

- **N-0: mostly resolved, with one new MAJOR gap (M-1 below).** The DB rewrite design is sound when checked against the code:
  - `path_key()` is plain `os.path.normcase` (`core/paths.py:50`).
  - `occurrences.path_key` holds *relative* names (`storage.py:402-404`), so the prefix match never touches it. That is correct.
  - The four `source_root` tables match what `backup.py:217-221` rewrites. `sources.path_key` / `path` are written at `storage.py:297-298`.
  - No column stores a hash of a path. I grepped for sha256 over a path, root, folder or inbox and found only the tax-engine file hashes.
  - The only UPDATE trigger on these tables is `revision_occurrences_update` (`066:23`). It bumps `library_revision.version` and changes no counts, so `verify --fresh` is unaffected.
  - The FTS5 table is external-content (`042:12`). Its shadow tables have no declared TEXT columns, so a filter on declared TEXT type skips them.
  - Leaving logs uncopied, the case-insensitive and JSON-escaped leftover search, and the Inbox-drop independence test are all present and correct.
- **N-1: resolved, with a MINOR detail gap (m-2).**
  - The `write_invite(family, member, destination, passphrase, hub, token)` signature matches `family_sync.py:122`.
  - `hub_address` parses a bare `host:port` with `ip_address` and accepts addresses in TAILNET (`family_client.py:31-41`).
  - `join_family` calls `local_absolute` on the invite and then `start_family_publish` (`manager.py:597-613`). That leads to `start_family_sync`, which sets `self.future` (`:714`).
  - `_request` uses `http.client.HTTPConnection` (`:52`). Its `OSError` becomes `HubError("waiting")`, so a `refused_by="sandbox"` record is reachable.
- **N-2: resolved.** `--browser` is in both the SL-03 and SL-04 commands, along with pass/skip counts. INFO: `browser_test` is not a registered marker and does not live in `conftest.py:11-18`. Those lines define the `--browser` option, which sets `RUN_BROWSER_TESTS`. `browser_test` is a per-module alias, `pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1")` (for example `test_accounts_v2_browser.py:13`). The approach works; only the citation is off.
- **N-3: resolved, with a MINOR wording issue (m-3).**
- **N-4: resolved, with a MINOR fixture-scope issue (m-4).**
- **D-P6: still open for the developer, and I verified its premise.** The real `docs/bugs.md` is 3901 bytes, all CRLF (no bare LF), and its last bytes are `screen. ` with no trailing newline. Under the literal reading of SC-09 line 197, no writer could pass. The `startswith(B0)` + one newline + header oracle is the right reading.

### MAJOR

**M-1: The restore fixture leaves `control/settings.json` unrewritten, so its own leftover check always fails.** (Plan: "Test environments", `seeded_instance` step 2.)
- **Evidence:** `reset` opens the profile with `switch_profile` → `activate(persist=True)` (`manager.py:425, 411`). That calls `open_library(..., persist=True)`, which writes `write_atomic(self.settings_file, json.dumps({"managed_directory": str(managed)}))` (`manager.py:1126`). So `<template>/control/settings.json` holds the template library's absolute path. The plan rewrites only `profiles.json` and `seed.json`, then searches every copied text file for the template root and fails on any hit.
- **Impact:** every subprocess test that uses `seeded_instance` fails during setup.
  - The failure is loud, not a data risk. Startup reads `profiles.active()` first (`manager.py:155`), so the stale `settings.json` wouldn't break the app.
  - It is a verified defect in exactly the area N-0 fixed. Any other JSON written under `control/profiles/` would hit the same failure.
- **Fix:** apply the value-based JSON rebase to *every* copied `.json` file, not two named ones, or at least name `control/settings.json`. Keep the leftover search as the backstop.

### MINOR

- **m-1 (N-0 rewrite rule): prefix match has no boundary, and "TEXT column" is undefined.**
  - "Equals or starts with the template root" would also rebase `<template>\instance-old\…`. Require an exact match, or the root followed by a separator (`\` or `/`, in the matching form).
  - Pick columns by value (`typeof(col)='text'`) and skip virtual tables and FTS shadow tables. Otherwise a STRICT `ANY` column holding a path is skipped by the rewrite but caught by the leftover search, which fails loudly.
  - Copy with `copy2` / `copytree` so mtimes are kept. The independence test already catches recapture if they aren't.
- **m-2 (SL-01, SC-05 step 4): the setup omits two required steps and conflicts with the contract's wording.**
  - `FamilyFolder.create` makes only `family_id` (`family_sync.py:332`). The `member_id` comes from `family.add_member(name, "remote")` (`:355-365`, `uuid.hex[:12]`), and the token from `family.new_token(member_id)` (`:469`). Pass `family.data` and the member dict to `write_invite`. Close the `FamilyFolder` afterwards, because it holds a `DirectoryLock`.
  - The contract says "No connection attempt is recorded" (`test-contract.md:132-133`), while the plan asserts that an attempt *is* recorded with `refused_by="sandbox"`. Both can hold, but the test should state both: the lookup is refused at the `getaddrinfo` audit event, and no connect-stage record exists for 100.64.0.1.
- **m-3 (A1 "Hub", `family_hub.py:108`): the inline expression must keep the loopback branch, and the hub test can pass vacuously.**
  - The current line is `address = "127.0.0.1" if self.loopback else tailnet_address()`. The new one should read `"127.0.0.1" if self.loopback else (None if sandbox.active() else tailnet_address())`, not replace the whole right-hand side.
  - `test_hub_stays_off_in_test_mode` needs a registered family folder. Without one, `start()` returns early with "No family folder" (`:105-107`) and the test passes for the wrong reason. Assert the reason is "Tailscale isn't running…" and that `tailnet_address` was never called.
  - The stale note at plan line 405 lists `tailnet_address` as a startup egress trigger. That no longer holds in test mode.
- **m-4 (SL-05 `test_server` fixture): the scope doesn't work as written.** A module-scoped fixture can't use `tmp_path` (pytest raises ScopeMismatch). The tests also pass a per-test `--root tmp_path`, but `finding` reads `<root>/session.json`, which the module fixture writes in its own directory. And if `finding` resolves paths through `local_absolute` while the module's sandbox is active, a per-test `tmp_path` is outside the allowed root. Fix: use `tmp_path_factory` for the server, plus a function-scoped fixture that writes `session.json` (and creates `evidence/`) under the per-test `--root`. Alternatively, make every test use the fixture's root.

### Spec-level notes
- There is no new contradiction. S-1 and S-2 / D-P6 stand as recorded.
- SC-05 step 4's "No connection attempt is recorded" needs only the reading in m-2, not a spec change.
- The accepted decisions D-P3, D-P4/R8, D-P5 and R2 are consistent with the code. I did not reopen them.

### Coverage
Every FR, SC and invariant maps to a slice and a test. I found no gaps.

### Verdict: REVISE (narrow)
Only M-1 blocks approval. It needs a one-sentence amendment: rebase every copied JSON file, `control/settings.json` included (`manager.py:1126`). The minors can be folded in at the same time. Once those land, they can be checked without a full re-review. D-P6 still needs the developer's acknowledgement.

## Round 8

**Verdict: REVISE.** Two MAJOR gaps, both cheap to fix. The rest of the plan holds up well after six rounds.

**Gate:** `gate.py check --stage spec` reports APPROVED (b2834186f166, 2026-10-17 22:59). The hash recorded in the plan (`b2834186…5e76`) matches `gate.py hash --stage spec`.

### Findings

**MAJOR-1: SC-05 steps 1–3 can pass without testing the guard (FR-05, E1). Verified.**
- The contract's SC-05 starts from "seeded (it has a crypto investment account and a non-USD amount)". The seed has neither:
  - Every `seed_wealth.py` account is `currency="USD"`, and none is crypto.
  - `fetch_crypto_prices` is `False` by default (`finance/ledger.py:284`).
  - The exchange-rate refresh only runs if foreign amounts exist (`manager.py:1683`).
  - The item lookup's `WebLookup.search` stops early with "not configured" when there's no Brave key (`web_lookup.py:145`).
- The contract accepts "refused, or no attempt at all". So all three steps pass even if the egress hook is missing. SL-01 spells out the setup for step 4 only.
- **Fix:** give SC-05 its own setup in SL-01:
  - set `fetch_crypto_prices=True` and `fetch_exchange_rates=True`;
  - add a coin holding and one non-USD amount;
  - use the barcode lookup (Open Food Facts needs no key), or set a dummy Brave key.
  - Then assert each host is recorded with `refused_by="sandbox"`, and drop "no attempt" as a pass.

**MAJOR-2: nothing tests the FR-09 "guard is off" case, and the guard check may always pass. Verified gap.**
- FR-09's acceptance says `verify` "exits non-zero, naming the failed check, when … a guard is off." SL-03 has no test for that.
- A5 checks `settings.test_instance` "has both guards true", but A1 never says how `status()` works out those values. If `activate()` just sets them to True, the check only proves test mode is on.
- Credible failure: someone starts the instance the old `environment.json` way (`python -m home_manager --control-dir <root>/control`). There's no sandbox, `test_instance` is `None`, and nothing proves `verify` catches it.
- **Fix:**
  - Make `status()` probe for real. `check_path(<a protected root>)` must raise, and `getaddrinfo("example.invalid", 443)` must raise the sandbox's `gaierror`. This sends nothing out, because the audit hook fires before the lookup.
  - Add `test_verify_fails_without_guards`: run the plain launcher on the instance's control folder and port, with a fake `LOCALAPPDATA`, and write `session.json` from its stdout token. `verify` must exit 1 and name the guard check.
  - Add a `verify` case for an incomplete seed (`.seed-incomplete` present). Today SC-13 step 3 only tests that case for `start`.

**MINOR**
1. **Taxes depend on the year.** `seed_tax_year` seeds nothing when the year isn't in `opentax.YEARS` (`{2025, 2026}`, `seed_taxes.py:22`). From 2027, SC-02 step 3's Taxes check fails as if the screen were broken. Fix: record `taxes_seeded` in the manifest, and skip the Taxes check the way `this_year_covered` does.
2. **`start` doesn't say what happens when `serve` fails.** A5 says `start` waits 30 s but not what follows: the exit code, the `server.log` tail, killing a stuck `serve`. Fix: on timeout, exit 1, print the log tail, and end the child.
3. **`reset` doesn't say it waits for background work.** `open_library` can queue a text-index backfill (`manager.py:1150`), and `seed.json` and the template are taken from the DB `reset` leaves. Fix: wait until `busy()` is false, then call `manager.close()` (`manager.py:2316`) before computing the manifest.
4. **The second screenshot on a duplicate isn't cited.** SC-09 says "both screenshot paths exist", but the "Seen again" line holds only dates. Fix: add the evidence path to that line.
5. **One path input is missing from SC-03's list.** `PUT …/members/{mid}` with `LocalMemberInput.folder` (`api.py:142-145`, `manager.py:568`) also takes a path. The `local_absolute` guard covers it through `create_profile`, but SC-03 should list it.
6. **Child processes are outside the egress hook.** "Catches any future caller" (A1, D-P2) is only true inside the server process. The OpenTax Node runner, the Tax-Calculator runner and the PDF reader run as separate processes the hook doesn't see. None of them makes network calls today (OpenTax telemetry is turned off by environment variable, `opentax.py:190`). Fix: say this scope in A1.

**INFO**
- FR-10 says "same scenario twice → two dates", but the plan treats a repeat on the same date as a no-op. SC-09 uses another date, so the contract is still met. Worth noting in the skill.
- `reset` refuses when any process holds the port, even one unrelated to the instance. Its message should say that.
- Entries are appended at the end of the file. If the developer later adds text below `## Agent findings`, entries land after it. Define the section's end as the next `## ` heading or the end of the file.

### Checked and correct
- One guard in `local_absolute` covers every path input. All U1 inputs reach it (`paths.py:55,77`; `manager.py:605,2278`).
- The model-address scope matches the code: `configure_model` and `is_remote` refuse everything but `127.0.0.1` (`manager.py:1183`), and only the `ModelComputer` validator takes tailnet hosts (`vision.py:104`).
- The `family_hub.py:108` call site is as described.
- `https_get` uses `http.client`, which ignores proxy settings, so a local proxy can't get around the hook.
- The Manager is built in uvicorn's lifespan (`api.py:588`), so `serve` turns test mode on before any library opens.
- The coverage matrix maps every FR and SC to a slice, apart from the two MAJOR gaps.

I made no edits and no approvals.

## Round 9

### Plan review: agent-test-instance (round 7)

**Gate.** `gate.py check --stage spec` gives `APPROVED spec: b2834186f166 by Anirudh Sathish at 2026-10-17T22:59:31-04:00`. `gate.py hash` gives `b2834186f1660324f9d1dea1e61814598ef5ebcbe397aee2cef77c8efbdf5e76`, which matches plan.md line 3.

**Coverage.** Every FR-01..FR-18, I-1..I-6 and SC-01..SC-19 maps to a slice and a test in the matrix (plan.md:397-423). The only gaps are inside SC-05 (see M3). FR-08's dark theme is covered only through SC-02, which is fine.

### What I checked against the code and found correct
- **`status()` probing is feasible.** `check_path` is purely lexical. The `socket.getaddrinfo` audit event fires before any lookup, and the `test_status_probes_guards` double path works.
- **SC-05 crypto setup.** `CryptoPrices.wanted` needs a market-valued account with a crypto position whose units are above zero (prices.py:108-129). The `crypto` kind is `market` (migration 036_investments.sql:31). The plan's precondition assertion on `wanted()` guards this.
- **SC-05 rates.** `EcbRates.refresh` fetches whenever rates are on (fx.py:134-138).
- **No 5xx from refusals.** PriceError and ProviderError are ValueErrors, and so is pydantic's ValidationError, which ModelComputer raises when it is built inside the handler (api.py:1378). All of them map to 400 (api.py:644-646).
- **SC-05 step 4.** `join_family` → `start_family_sync` sets `self.future` (manager.py:714). `hub_address` parses a bare `host:port` (family_client.py:31-41). `family_hub.py:108` is the only place the hub calls `tailnet_address`.
- **Reset settling.** `close()` stops the monitor, waits for the executors, closes the store and the lock (manager.py:2316-2327). `busy()` exists (:197).
- **`taxes_seeded`.** `seed_tax_year` returns False when the year isn't covered (seed_taxes.py:17-36), and `YEARS = {2025, 2026}` (opentax.py:35).
- **Path guard.** The list of `local_absolute` / `validate_managed` / `separate_folder` callers matches the plan exactly. P12 goes `set_up_local_member` → `create_profile` → `validate_managed` (manager.py:568, :430).
- **Child processes.** The plan's list is accurate. OpenTax telemetry is turned off by env (opentax.py:190).
- **Marker.** The CSS for the 64 px rail (style.css:1268-1276) and the sidebar markup (index.html:50-54) are as the plan describes.
- **`start` failure path and `HM_TEST_SERVE_FAIL`.** Consistent with "nothing in home_manager reads HM_TEST_*".

### Findings

**MINOR M1 (verified defect): wrong route for P12.** SL-01 gives P12 as `PUT /api/families/{id}/members/{mid}`. The real route is `POST /api/families/{profile_id}/members/{member_id}/local` (api.py:714-715).
- *Failure:* the test calls a route that doesn't exist and gets 404/405. A test checking "any 4xx" would then pass without the guard ever running.
- *Fix:* correct the route, and assert the sandbox's refusal message, not just a 4xx.

**MINOR M2 (verified): SC-05 step 3 needs exact preconditions and a correct oracle.**
- `resolve` only looks a barcode up if `valid_gtin` passes, and that checks the check digit (items.py:67-74). "A 13-digit `product_code`" isn't enough.
- `LookupFailed` from the barcode lookup is swallowed (resolver.py:143-146). The run then ends `succeeded` with `method: None` and the note "No reasoning model is configured." When a reasoning model is set, it goes on to the agent (`resolver.py:155-157`).
- *Failure:* the test asserts a "failed" run that never happens. Or a reasoning model left configured sends model calls the test didn't expect.
- *Fix:* use a check-digit-valid GTIN (e.g. `4006381333931`) and no reasoning model. Wait on `manager.future`, then assert the run succeeded, the line has no proposal, the `world.openfoodfacts.org` lookup was refused by the sandbox, and the refusal was logged.

**MINOR M3 (coverage gap): parts of SC-05 aren't assigned.**
- Step 5 (no `pageerror` on Money, Investments and Inventory in the browser) isn't planned anywhere. SL-01 has no browser run. SC-02's seeded household has no crypto, so it doesn't exercise this state.
- The expected end state "no new rows in price or rate tables" (`price_quotes`, `fx_rate_sets`, `fx_rates`) isn't planned.
- The retry variant isn't planned.
- *Fix:* add all three to the SL-01 SC-05 test, with a `--browser` step or a browser test in SL-04 against the same setup.

**MINOR M4 (possible risk): the findings writer's parsing rules are underspecified.**
- The plan doesn't say that duplicate keys are matched only inside `## Agent findings`. A `<!-- finding:KEY -->` copied into the developer's text above the section could send a "Seen again" write above the header, which breaks the byte-identical prefix.
- It doesn't say where an entry ends, so "under that entry" has no defined insertion point.
- A field value containing `<!-- finding:` can forge a key. Only `## ` is escaped today.
- *Fix:* match keys only inside the section. An entry ends at the next marker or the section end. Escape `<!--` in field text as well as `## `. Add one test for each.

**MINOR M5 (possible risk): log dedupe can make tests order-dependent.** The hook logs each refused host only once, and it is installed once per pytest session. A later test that checks `caplog` for a host an earlier test already refused would miss the line.
- *Fix:* clear the logged-hosts set on every `activate()`.

**INFO I1: inaccurate claim about subprocess tests.** The plan says their only non-loopback trigger is the startup rate/price refresh (plan.md:449-452). On the seeded household neither fires: crypto prices are off by default (ledger.py:284, manager.py:1675), and rates need non-USD money (manager.py:1683), but the seed is all USD.
- Subprocess tests can only assert that no refusal line appears. Contract line 28 implies they read refusal lines.
- *Fix:* reword. FR-05 is proven in-process and by `verify`'s probe.

**INFO I2: inconsistent slice text.** SL-03's verification note says SC-14 drives the UI, but SC-14's screens are in SL-04.

**INFO I3: unneeded setup.** The EUR transaction isn't needed for `POST /api/rates/refresh`. It's harmless.

**INFO I4: reset step order.** `configure_model` raises when inference is busy (manager.py:1187). The seed is synchronous (seed_documents.py:31-32), so this is safe today. Draining the inference queue before step 5 would make it robust.

**INFO I5: hook scope.** The hook doesn't cover `socket.sendto` (UDP without connect). Nothing calls it today.

### Verdict
**PASS WITH MINORS.** M1–M3 are small edits to SL-01's test description. M4–M5 are small rules for SL-05 and SL-01. None of them needs a spec change or a new decision.
