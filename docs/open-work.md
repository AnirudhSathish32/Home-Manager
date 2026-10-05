# Open work

This is the only list of known open work, gathered from every doc on 2026-10-04. Feature docs describe what is built
and link here for what isn't. When an item is built, remove it from this list and describe it in its feature doc.

## Ingestion

- **Email ingestion (Gmail first)**, including bill notices from email (the exact amount and due date before paying,
  linked to their recurring bill). The approved design (on hold while you decide whether to include email):
  - Gmail API with your OAuth and the `gmail.readonly` scope only: no modify or send, and never mark read, move, label
    or delete.
  - The refresh token goes in Windows-protected credential storage, outside prompts and logs.
  - Bounded historical backfill, incremental cursors, rate limits, and a visible sync status that tells an empty result
    apart from incomplete sync.
  - Attachments are downloaded into the library like any capture, and processing stays local.
  - Before ingesting mail, set a retention and user-controlled deletion policy. Deleting mail at Google doesn't delete
    local evidence.
- **Split receipts and combined images can't be donated** yet ([evals](evals.md#donating-documents)).
- **Which document languages are required?** This affects vision evaluation and parsing conventions.
- **A native folder picker** for choosing the library folder (paths are pasted today).

## Models and evals

- **Decision model:**
  - check the `/v1/responses` log-probability shape against the installed LM Studio;
  - calibrate a chosen model on real documents before it gets any routing role;
  - the documents suite doesn't yet report decision-model calibration.
- **Evaluate the vision and reasoning models on real documents** (the donated corpus); accuracy has only been measured
  on synthetic data.
- **Judge.** No hand labels exist yet, so no judge is calibrated.
- **Assistant eval:** compare tool arguments, and add document-search questions.
- **Eval open questions:** candidate models, gate thresholds, eval temperature, task weights, and a latency limit
  ([evals](evals.md#open-questions)).
- **Donation consent:** fill in the retention date in [donation-consent.md](donation-consent.md) before the first
  donation.

## Money

- **Per-currency totals.** Category totals, budgets and the Home dashboard are still per currency, with no USD total.
- **Family shared bills.** A shared recurring bill's payments still count in full for whoever paid.
- **Family corrections.** Records corrected in the family library after they were sent need **Send** again.

## Planning and investments

- **Investment income modelled separately** in the forecast (`yield_bp`, `reinvest`, `investment_tax_percent`). The
  spec is in [planning](planning.md#planned-investment-income).
- **Forecast taxes** beyond the flat rate on tax-deferred withdrawals and pensions.
- **Not computed:**
  - the Education Savings Bond exclusion;
  - pension survivor benefits in the forecast;
  - the 10% additional tax on non-qualified 529 earnings;
  - separating paper I bonds bought with a tax refund.
- **What If doesn't model:**
  - the pre-2020 W-4;
  - payroll rounding to whole dollars;
  - state withholding formulas beyond brackets, deduction or exemption and typed credits;
  - state rules for pre-tax deductions.

## Taxes

- **Returns Engine 1 doesn't cover** (some fall back to Engine 2):
  - both spouses self-employed;
  - educator expenses on a joint return;
  - forcing the standard deduction;
  - the energy credit;
  - other credits typed in;
  - more than three AOTC students.

  Engine 2 also doesn't take other itemized deductions typed in.
- **MFS and QSS filing statuses** aren't offered (the engine supports them).
- **1099-R box 4 withholding** isn't gathered.
- **Retirement distributions** aren't split into IRA and pension.
- **State returns.** Full state returns: OpenTax has composers for IL, VA, CA, NY and PA, which aren't wired in.
  Everything else uses the simplified state return.
- **Additional Medicare.** Payroll starts Additional Medicare withholding at $200k regardless of filing status, but the
  pay stub explanation uses the filing-status table's threshold.
- **1040-ES and Form 2210.** 1040-ES due dates aren't shifted for holidays, and there is no annualized-income method
  (Form 2210 Schedule AI).
- **Tax lots:** no wash sales, no specific identification, no basis adjustments.
- **RMD exceptions:** the still-working exception, inherited IRAs, the joint-life table, and QCDs.
- **Schedule C lines** for cost of goods sold, depreciation, home office and mileage.
- **Not built from the design:** an IRS Withholding Estimator adapter, and recalculation triggered by investment
  events.
- **Before distributing Home Manager:** offer OpenTax's source (AGPL §6), buy its commercial license, or replace the
  Engine 1 adapter ([taxes](taxes.md#engine-1-opentax)).

## Household

- **Product recall checks** (CPSC/FDA): undecided.
- **Brave free-tier limits:** unconfirmed.

## Security

- **The Brave API key in Windows Credential Manager** (it is an environment variable today).
- **OS-level confinement of the reader worker**, which has resource limits only today. The design:
  - a restricted Windows token and identity;
  - explicit file ACLs (read-only on the one snapshot, write only to the job's scratch space);
  - network denial;
  - a Job Object for process-tree cleanup and CPU and memory limits.

  The confinement must be validated by tests before claiming a sandbox.

## UI

- **The redesign** is listed under [UI redesign](#ui-redesign) below.
- **Home:** live balances, customizable panels, a month-end projection, and a daily or weekly view.
- **UX findings from the 2026-09-30 review:**
  - **Decisions below the fold:** Review's buttons sit under a late-loading thumbnail, Home's "Needs attention" comes
    after the charts, and the document page's Read and Record buttons are in its footer.
  - **One action, many names:** Read, Record, Count it, Reject, Remove; and "Reconcile now" means two things.
  - **Missing states:** loading and error states exist only on Home, Review and Spending. Unconfigured pages show empty
    tables.
  - **Forms:** form errors are toasts instead of messages next to the field. Budget and asset currencies are free text.
  - **Filters lost on reload:** Documents, Inventory, the Spending month, Forecast assumptions and the Settings tab.
  - **Deep links** from Home, Review and Search open the Documents library, which leaves out receipts and statements.
  - **Too many primary buttons** in Documents rows and Review questions.
  - **Dead ends:** no link from a receipt to its matched charge, no Import on Accounts, and CSV/XLSX files can't be
    opened.
  - **Internal wording** in the document page's default tab and in Processing titles.
  - **The Assistant panel** covers the page and toasts.
  - **Not built:** a first-run welcome, a `?` shortcut overlay, a non-modal drawer, and skeletons.

## UI redesign

The design is in [ui](ui.md#redesign-calculation-observability). The items below are in build order, with
one or two per session. Paths are under `src/home_manager/`. Each item is done when its test passes; remove it from
this list once it's built.

**4. What's left of the traces** (sections 3 and 4 are built, engine worksheets included: ui.md "Trace contract",
"What's built"; taxes.md "The engines' worksheets").
- **Engine 2's opaque lines** (`TaxCalculatorEngine.opaque_lines`): the tax from the rate schedules and the capital
  gains worksheet (`taxbc`), the AMT, itemized deductions, the senior and QBI deductions, the dependent care and education
  credits, the EITC, ACTC and refundable AOTC.
  - Tax-Calculator overwrites these lines' intermediate values in place (a credit is limited to the tax) or keeps them in
    local variables (`GainsTax`, `EITC`, `AMT`).
  - Deepening one means reading back whatever intermediate outputs exist (the `dwks*` capital gains worksheet lines,
    for example), or writing the steps from the law in `taxcalc_map.json` and checking them against the engine's final
    value.
  - A line comes out of `opaque_lines` only when the conformance test passes without it there.

**5. Design and components.**
- **Phase 0:** MASTER.md with `ui-ux-pro-max`, shown as browser pages.
- **Phase 1 foundation:**
  - tokens and a dark theme;
  - self-hosted fonts;
  - one `pageState()` loading/error/empty helper. Today Bills and Accounts have no error handling, Investments can stick
    on "Loading…", and Forecast and Taxes fall back to a toast;
  - fix the hard-coded chart hex values.
- **The components** in `app/static/trace.js`.
- **The `ui_v2_screens` flag** and `tests/test_ui_parity.py`.

**6. Screens, one per session.** Taxes → Today → To check and the document page (with Correct) → This month,
Transactions (Add, Import), Bills, Accounts (Import) → Investments, Forecast, What If → Inventory (Item insights) →
Processing (Data health), Settings (Independent checks editable, Donate) → Search, Ask.

**7. Surface or remove backend-only features.**
- Give a caller to `GET /api/finance/health`, `PUT /api/reviewer-settings`, `POST /api/decision-model-tests`,
  `PUT/DELETE /api/tax/businesses/{id}`, and `GET /api/tax-tags/on/{receipt|receipt_item}`.
- Remove `POST /api/finance/bills/{id}/payment` (see Code cleanups).

**8. Cleanup.** Remove the old loaders, the duplicate helpers (`asyncButton`/`actionButton`, the five table builders)
and dead CSS. Then rewrite ui.md "Design system" and "Pages" to match what was built.

## Family hub (its own project)

Decided 2026-10-04. The shared GPU for testers is built ([family](family.md#shared-gpu)); the hub itself isn't
started. It changes [family](family.md)'s promise that families never exchange data through a
network listener, so it needs a security review first.
- **Transport: Tailscale only.** The shared-folder sync is retired.
  - The family computer runs a hub while its app is open. It reuses `models/gpu_host.py`: `make_server` binds only to
    100.64.0.0/10, plus `tailnet_address()` and per-member tokens stored as SHA-256.
  - Members push their database copy (the existing encrypted `.hmfamily` format) and pull their deliveries.
  - Both sides queue and retry while the other is offline. Settings shows "Waiting for the family computer" with the
    last sync time.
  - `.hminvite` carries the hub address and token. Existing families re-join once.
- **Documents.** Members push the documents their records cite, incrementally by blob hash. The family computer keeps
  them encrypted at rest, with no size cap; Settings shows the size.
- **Editable family ledger.** Every member uses it.
  - Transactions, This month, Bills and Accounts span the members' copies with the counted-once rules, and each row
    shows its owner.
  - Corrections travel back to the member as encrypted deliveries and apply as `record_corrections` rows with an actor.
  - If the member changed the same field since, the correction becomes a Review question instead.
  - The member can reject a correction. The family gets no notice: the record reverts when the member's next copy
    arrives.
- **Tests:**
  - refusals: wrong token, a non-tailnet bind, replay, wrong family;
  - a copy, a delivery and a correction each make the full trip;
  - originals show while the member's app is stopped.
- **Decided 2026-10-05:**
  - A correction applies silently. The member's record history shows "Changed by family (<who>)" with **Reject**, and
    only a conflict becomes a Review question.
  - The family ledger shows a correction at once, tagged "Waiting for <member>", until the member's copy acknowledges
    or rejects it.
  - The hub listens whenever the app is open on the computer holding the family folder, whichever profile is active.
- **Build order:** security review sign-off (done 2026-10-05) → hub transport for copies and deliveries → documents → family ledger
  (read) → corrections (migration 062: `family_corrections`, plus a `reconciliation_issues` rebuild for the
  `family_correction` question). Each step is below, about one session each. Paths are under `src/home_manager/`.

**1. Hub transport for copies and deliveries.**
- **Bind check:** move the address check out of `models/gpu_host.py` `make_server` into
  `models/http_server.py` `check_bind(address, loopback)`, so the GPU relay and the hub share it. Reuse
  `tailnet_address()`.
- **New `app/family_hub.py`:** `HubServer(GracefulHTTPServer)` on port 8767.
  - Its handler streams request bodies to disk in 1 MiB chunks. The GPU relay reads bodies into memory, so that part
    isn't reused.
  - Routes, each needing a Bearer token:
    - `GET /v1/ping` returns the family id and the server time.
    - `PUT /v1/families/{fid}/members/{mid}/copy` takes a sealed `.hmfamily`. The hub stages it as `.importing`, then
      runs the existing `FamilyFolder._import_snapshot` → `prepare_copy`.
    - `GET /v1/families/{fid}/members/{mid}/deliveries` lists the keys waiting for that member.
    - `GET` and `DELETE /v1/families/{fid}/members/{mid}/deliveries/{key}` fetch a delivery and acknowledge it.
  - **Tokens:** `family.json` keeps `members[mid].token_sha256` and `last_seq`.
  - **Deliveries** are queued at `<family>/outbox/to-<mid>/` until the member acknowledges them. `write_delivery` writes
    there instead of the sync folder.
- **Lifecycle:** `Manager.__init__` starts the hub on a daemon thread when this computer holds a family folder, and
  `close()` stops it. `GET /api/profiles` returns a `hub_status`: the address it listens on, or why it isn't listening.
- **New `app/family_client.py`** for the member side (urllib with timeouts):
  - `push_copy` seals the copy into `<control>/family/<fid>/outbox/copy.hmfamily`. A newer copy replaces an unsent
    older one.
  - `pull_deliveries` downloads each delivery, applies it with the existing `apply_delivery`, then acknowledges it.
  - It retries with backoff while the hub can't be reached.
  - `Manager.check_family` calls it in place of `publish` and `read_deliveries`.
  - The profile's family link gains `last_sync`, `hub_state` (`ok`, `waiting` or `refused`) and `hub_error`.
- **Invites:** `.hminvite` moves to version 2 (`HMINVIT2`), which carries the hub's `address:port` and the member's
  token.
  - A version 1 invite is refused with "Ask the family computer for a new invite".
  - Existing member links with no hub show "Re-join needed".
  - The join form loses its sync-folder field.
- **Local members** on the family computer keep the direct path, with no network: `_import_local`, and writing to their
  `Store` directly.
- **Retiring the folder:**
  - Remove the `sync` paths: `sync_folder`, the sync folder in `create_family`, `link_local` and invites,
    `publish`'s target, and `read_deliveries`.
  - Keep the `.hmfamily` and `.hmdelivery` formats; their sealed headers gain `seq`.
- **UI (`static/profiles.js`):**
  - `membershipSection` shows "Waiting for the family computer · last synced <time>", or "Synced <time>".
  - `familyMembersSection` shows the hub's address, or why it isn't listening.
- **Tests (`tests/test_family_hub.py`):** the hub runs on 127.0.0.1 through a test-only loopback flag (like the
  `relay` fixture in `tests/test_gpu_host.py`), with two `Manager`s.
  - Refusals: a wrong token, another member's token, a non-tailnet bind, a replayed copy (the same or a lower `seq`),
    a wrong family id in the sealed header, an oversized body, and a GPU token used on the hub (and a hub token on the
    relay).
  - Full trips: a copy is pushed, imported and shown in the family dashboard; a delivery is pulled, applied and
    acknowledged.
  - Offline: while the hub is down the member queues its copy and shows `waiting`, then syncs when the hub is back.
  - Update `tests/test_profiles.py`, `test_family_inbox.py` and `test_family_routing.py` for the removed sync folder.

**2. Documents.**
- **Member side:** after a copy is pushed, the member collects the `blob_hash` values its records cite
  (`financial_evidence_links`, plus each record's own `blob_hash`).
  - `POST /v1/.../blobs/missing` returns the ones the hub lacks.
  - Each missing one goes up sealed to `PUT /v1/.../blobs/{hash}`, read from `Store.blob_path`.
- **Hub side:** it decrypts each upload to check the SHA-256 against `{hash}`, then keeps the sealed bytes at
  `<family>/blobs/<hh>/<hash>.hmblob`.
  - Documents are encrypted at rest with the family key, with no size cap.
  - `FamilyFolder.blob_size()` feeds a "Documents: <size>" line in Settings.
- **Family view:** the route that serves original files gets a family branch that streams the decrypted blob, so
  originals open while the member's app is stopped.
- **Tests:** an original opens after the member's `Manager` is closed, the stored file isn't the plaintext, and a blob
  whose hash doesn't match is refused.

**3. Family ledger, read side.**
- **Routes:** add `transactions`, `spending`, `bills` and `accounts` to `FAMILY_ROUTES` in `static/shell.js`.
- **`finance/family.py`:** a new `family_tool(members, name, args)` runs the `FinanceTools` method on each `MemberStore`
  view copy. Those copies already have the counted-once rules from `rebuild_views`.
  - It merges list rows, tagging each with `member_id` and `owner`.
  - It adds up totals with `add()`.
- **API:**
  - In family mode, `POST /api/finance/tools/{name}` dispatches to `family_tool`, the way `/api/dashboard` uses
    `Manager.family_dashboard`.
  - `GET /api/finance/records/{type}/{id}` takes `?member=`.
- **`static/finance.js`:** an Owner column in family mode, and row links that carry the member.

**4. Corrections round trip** (one or two sessions).
- **Migration `062_family_corrections.sql`:**
  - a new table `family_corrections`: `key` (the primary key), `direction` (`sent` or `received`), `member_id`,
    `record_type`, `record_id`, `field`, `value`, `previous`, `actor`, `correction_id`, `status` (`pending`, `applied`,
    `conflict` or `rejected`), `created_at` and `updated_at`;
  - a rebuild of `reconciliation_issues` (as in `061_provenance.sql`) to allow the `family_correction` issue type and
    the `kept_mine` and `took_family` resolutions.
- **Family side:**
  - `PATCH /api/finance/records/{type}/{id}?member=` gets past `FAMILY_READ_ONLY` and calls a new
    `Manager.correct_family_record`.
  - That checks the field with `Ledger.correct`'s rules, reads `previous` from the view copy, and inserts a `sent` row.
  - It then writes a delivery: `{kind: "correction", key, record_type, record_id, field, value, previous, actor}`.
  - `rebuild_views` applies pending sent corrections to the view copies again. Ledger rows then carry `pending_fields`,
    which the UI shows as "Waiting for <member>".
- **Member side:** a new `finance/family_corrections.py` with `apply_correction(store, delivery)`, which applies each
  key only once.
  - If the current value equals `previous`, it calls `Ledger.correct(..., actor="Family · <who>")` with the reason
    "Family correction". `Ledger.correct` needs a new `actor=` override, since today it takes the actor from
    `core.actor.current()`.
  - If the current value already equals the new value, it records `applied` and changes nothing.
  - Otherwise it records a `conflict` and raises `Reconciler.issue(db, "family_correction", …)` with the detail
    `{key, field, value, previous, current, actor}`. `resolve_issue` and `static/review.js` gain "Use family's" and
    "Keep mine".
- **Reject:** the record's history (`finance/provenance.py` and its UI) shows family corrections with a **Reject**
  button.
  - It calls `POST /api/finance/family-corrections/{key}/reject`, which puts `previous` back through `Ledger.correct`
    under the member's own actor and marks the row `rejected`.
  - The family isn't notified.
- **Acknowledgement:** the `.hmfamily` header carries `corrections: {key: status}` for the received rows. On import the
  hub updates its sent rows, which removes the "Waiting" tag. A rejected correction goes back in the family view when
  that copy arrives.
- **Tests:**
  - a correction is applied, then acknowledged, and its tag goes;
  - a conflicting correction becomes a Review question, and each resolution works;
  - a rejected correction goes back in the family view on the next copy;
  - `test_family_browser.py` with `--browser` checks the Owner column, the pending tag and the Settings sync line.

**5. Docs.**
- Rewrite family.md "Families" for the hub, and add "Family ledger" and "Family corrections".
- Update "Family inbox", and drop its open item about corrections made after Send.
- Remove this section from open-work.md.
- Update code comments that cite renamed headings.

### Security review (approved 2026-10-05)
The user approved this review on 2026-10-05. It replaces family.md's "never through a network listener" once built.
The next step is the hub transport for copies and deliveries.
- **Exposure:**
  - The hub has its own port (8767), and binds only to the Tailscale address. It reuses the GPU relay's bind check,
    moved to `models/http_server.py`, and refuses 0.0.0.0, LAN addresses and loopback-as-remote.
  - It has no route into the main app, which stays on 127.0.0.1.
  - Shared-GPU testers are kept off it by the tailnet policy ([family](family.md#shared-gpu)).
- **Authentication:**
  - Each member has a bearer token from `secrets.token_urlsafe(32)`. Only its SHA-256 is stored, in `family.json`, and
    tokens are compared with `hmac.compare_digest`.
  - A token is bound to one family and one member, and the path's ids must match it.
  - The hub re-reads tokens on every request, so removing a member takes effect at once.
  - GPU tokens and hub tokens are separate files and never accepted by the other server.
- **Confidentiality and integrity:** every copy, delivery and document is still sealed with the family key
  (AES-256-GCM, `library/share.py`), under Tailscale's WireGuard. A stolen token alone can't forge or read a payload.
- **Replay:**
  - Sealed headers carry the family id, member id, a per-member `seq` and `created_at`. A copy whose `seq` is not above
    the last accepted one is refused.
  - Documents are content-addressed, so a replayed upload changes nothing.
  - Deliveries and corrections have unique keys, and each is applied once.
- **Resource limits:**
  - Bodies are streamed to disk: at most 4 GiB per copy, with a per-document cap.
  - Paths follow a fixed grammar (ids and hex hashes only).
  - No request body is logged.
- **Not covered:**
  - a compromised family computer;
  - a member's computer that is compromised while it holds the family key;
  - `members/*.sqlite3`, which sit decrypted on the family computer, as they do today with folder sync.

## Code cleanups

- `library.js` still has the bill payment labels ("Paid" / "Marked unpaid"), and `POST /api/finance/bills/{id}/payment`
  is still registered, though bills are no longer tracked.
- A stale `__pycache__/tax_figures.cpython-313.pyc` remains after `household/tax_figures.py` was deleted.

## Database

These are left over from the 2026-09-30 audit ([development](development.md#database-checks)):
- **Dead columns** to drop when their tables are next rebuilt: `investment_events.reverses_event_id`, `jobs.year` and
  `jobs.month`, and `occurrences.folder_year` and `occurrences.folder_month` (which also make up most of index
  `occurrences_root`).
- **`library_query()`** is one 70-line SQL string with about 30 correlated subqueries. It was left alone on purpose;
  revisit only if the library page gets slow with real data.
- **Run `scripts/db_checks.py` on your live data** yourself, and paste the output redacted as you like.
