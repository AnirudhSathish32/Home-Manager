# Plan: Profiles, each with its own local database, plus a Family view

Status: built 2026-09-28; how it works now is in `docs/sharing.md` → Profiles and families. Companion plan: `docs/shared-gpu-plan.md`.
Changes from the plan while building it:
- Per-profile preferences live in `<settings folder>\profiles\<id>\household.json`, not in the library folder.
- The family is added up from each member's own dashboard, category and bill results; it does not merge raw databases.
- Joint accounts and transfers between members are handled on the family's adjusted copies (`view\`).

Decisions already made:
- Each family member runs the app **on their own PC**.
- Only model calls leave a member's machine (see the GPU plan). Their database never does, except for the encrypted Family view snapshot described below.

## Context
Today the app is single-household.
- `Manager` holds one `self.store`, one library folder and one `inventory.sqlite3` (`app/manager.py:204-248`).
- `settings.json` stores a single `managed_directory`.
- `household.json` (`HouseholdConfig`, `finance/ledger.py:153`: filing_status, home_currency, …) is global.
- No schema table has an owner or person column. `docs/architecture.md` (security table, "Unauthorized household access" row) flags multi-user support as future work.

The goal:
- Every person gets their own profile with its own library and database.
- A **Family** profile holds no transactions of its own. It collates its members' data into a family-wide view of spending, cash flow, assets and net worth, with a breakdown per person.

## Design

### 1. Profile registry (per machine)
- New `app/profiles.py`, backed by `<control>/profiles.json`:
  `{active: id, profiles: [{id, name, kind: "individual" | "family", library: path, family_id?, member_id?}]}`.
- **Migration:** if `settings.json` has an existing `managed_directory`, it becomes profile #1 (individual, named after the user) on first start. Nothing is moved.
- **Each profile gets its own library folder.** The default is `<chosen root>/<profile-slug>/`, holding its own `inventory.sqlite3`, `originals/`, inbox, `DirectoryLock` and backups. `Store` and `validate_managed` (`core/paths.py:54`) are reused unchanged.
- **Switching profiles** reuses `Manager.configure` → `open_library` (`manager.py:204-248`): the same "no work running" guard, the same service rebuild and the same close of the previous store. `open_library` persists the active profile id instead of a bare path.
- **Per-profile settings:** `household.json` moves into each profile's library folder as `profile.json`, because filing status and home currency are per person.
  - Model settings (`vision.json`, `reasoning.json`, `reviewer.json`) stay machine-level.
- **API:** `GET /api/profiles`, `POST /api/profiles` (create), `PUT /api/profiles/active` (switch) and `PATCH`/`DELETE` (rename, or remove from the registry; files are never deleted).
- **UI:** a profile switcher in the app header. Read the `app-ux` skill first.
- `settings()` gains `profile: {id, name, kind}`.

### 2. Family creation and member onboarding
- **"Create family"** makes a `kind: "family"` profile with:
  - `family_id`
  - a random 32-byte **family key**
  - a list of X members (name, member_id)
  - a **sync folder** path (any folder both machines can see: OneDrive/Google Drive/Dropbox folder, a network share, or a Tailscale-shared folder)

  Its library folder holds only a family cache (below) and `family.json`.
- **Members on the same PC:** "Add member → on this computer" creates a local individual profile that is already linked (`family_id`, `member_id`).
- **Members on another PC:** "Add member → on their computer" exports an **invite file** (`.hminvite`) containing family_id, member_id, family key and sync-folder hint.
  - It is encrypted with a passphrase using the existing `EncryptingWriter` / `DecryptingReader` (`library/share.py:70-143`, AES-256-GCM + scrypt).
  - The member does "Join family" in their app, which creates or links their individual profile.

### 3. Member → family snapshots (how collating works without sharing a live database)
- A linked individual profile publishes `<sync>/<family_id>/<member_id>.hmfamily`:
  - After each successful capture/inference pipeline, debounced to at most once every 10 minutes.
  - Also via a manual "Publish to family" button.
- **Contents:** a consistent copy of `inventory.sqlite3` only.
  - Taken with `sqlite3.Connection.backup`, the same approach as `library/backup.py`.
  - No `originals/` blobs, so it stays small.
  - Encrypted with the **family key**. `share.py`'s writer/reader get a small refactor so they accept a raw 32-byte key as well as a passphrase (`derive_key` is skipped when a key is given).
  - Written to `<name>.tmp` then renamed, so a half-synced file is never read. GCM authentication also rejects truncated files.
- **The Family profile** imports each newer snapshot into `<family library>/members/<member_id>.sqlite3`.
  - Imports are **read-only**, opened via the existing read-only check in `storage.py:69`.
  - The Family profile records last-updated time per member and shows it: "Mom — data as of 2 h ago".
- **Opt-out:** a member can pause publishing in their profile settings. Publishing is off until they join a family.

### 4. Family aggregation
- New `finance/family.py`: `family_dashboard(member_stores, month, months, currency, home_currency)`.
  - Calls the existing `finance/dashboard.py:24 dashboard()` per member store.
  - Merges money **per currency in minor units**, the same shape `dashboard()` already returns.
  - Returns `{total: <dashboard shape>, members: [{member_id, name, as_of, dashboard}]}`.
- **Net worth / assets:** call `finance/forecast.py baseline()` (182) and `project()` (266) per member and sum assets, loans and net_worth.
- **Spending by category:** `FinanceTools.get_spending_by_category` (`finance/tools.py:359`) per member, merged by category key.
- **Double-counting guards:**
  - **Joint accounts:** the same `accounts` identity (institution + type + last four) under two members is counted once and marked "joint". The UI shows a "Shared account — counted once" note.
  - **Transfers between members:** opposite-sign transactions with the same amount, within ±3 days, on two members' accounts are excluded from family spending and income, and listed under "Transfers within family".
- **Family profile UI** (read `app-ux` and `forecast-charts` first):
  - The Home dashboard in family mode shows totals.
  - A per-person breakdown (stacked by member) and a member filter chip row.
  - Editing is disabled, with the note "Edit in <member>'s profile".
  - Source documents are not shipped, so the source panel says "Original is on <member>'s computer".
- **Routes:** when the active profile is a family profile, the dashboard, spending, forecast and assets routes branch to `family.py`. Write routes return 409 with the message "Family view is read-only".

## Critical files
- `app/manager.py`: profile-aware `open_library`, settings, household per profile
- `app/api.py`: profile routes, family branching on read routes, read-only guard
- new `app/profiles.py`, `app/family_sync.py`, `finance/family.py`
- `library/share.py`: key-based encryption variant
- `app/static/index.html`, `app.js`: switcher, create family, invite and join, family dashboard
- `docs/architecture.md`, `docs/sharing.md`

## Verification
- **Unit tests:**
  - Registry migration from an old `settings.json`.
  - Profile switch rebuilds services and releases the previous lock.
  - Snapshot round trip (encrypt → decrypt → identical rows). A wrong key or truncated file is rejected.
  - `family_dashboard` sums two synthetic member stores built with the `books`-style fixtures (`tests/test_forecast.py:84`), including multi-currency, joint-account dedupe and transfer exclusion.
- **API tests:** use the `create_app` + `TestClient` pattern (`tests/test_dashboard.py:63`): create family → add a local member → publish → family dashboard totals; write routes are refused in family mode.
- **Manual check:** two control dirs on one machine (`--control-dir A` / `B`) sharing a sync folder simulate two PCs end-to-end.
- Run only the touched tests.
