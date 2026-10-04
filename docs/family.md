# Profiles, family and sharing

Each person has their own library. A family view adds the members up without merging their data, and a family inbox
takes one upload for the whole house. An encrypted `.hmshare` export lets someone look at a copy of your library. One
GPU computer can run the models for the whole family.

Ground rules:
- **Each member runs the app on their own PC.**
- **Only model calls leave a member's machine** (rendered page images and text prompts, sent to the family GPU).
- **Documents and databases stay local.** The exceptions are the encrypted family snapshot and family deliveries
  described below, which only ever travel as ciphertext.

Code: `app/profiles.py`, `app/family_sync.py`, `finance/family.py`, `finance/family_routing.py`, `library/share.py`,
`models/gpu_host.py`. Tests use two control folders that share one sync folder (`--control-dir A` and `B`) to act as two
PCs.

## Profiles

- **What a profile holds.** Each person on a computer has a **profile**: their own library folder (its own
  `inventory.sqlite3`, originals and Inbox) and their own financial preferences
  (`<settings folder>\profiles\<id>\household.json`). Model settings stay per computer.
- **The registry** is `<settings folder>\profiles.json`. On the first start with profiles, the library in
  `settings.json` became a profile named "My profile", with the computer's old `household.json`. Nothing was moved.
- **Switching.** Use the **Profile** menu in the sidebar, or Settings → Profiles & family. Switching closes one library
  (releasing its lock) and opens the other, the same way changing the library folder does. It is refused while work
  runs or a shared-library session is open.
- **Removing a profile** only forgets it. Its folder stays on disk, and adding the same folder again brings it back (a
  family folder comes back as the family).
- **Not access control.** Profiles separate libraries but don't restrict who can open them: anyone at the computer can
  switch. Families exchange only encrypted database copies through a folder, never through a network listener.

## Families

- **A family profile holds no records of its own.** It adds up its members' spending, cash flow, bills,
  needs-attention counts and net worth, and shows each person's own row. Members' records are never changed from the
  family.
- **Family totals are exactly the sum of the per-person rows.** Each member's figures come from the same functions an
  individual profile uses, added in minor units per currency.
- **Members on this computer:** the family copies their library's database directly (read-only) whenever it changes.
- **Members on their own computer:**
  - **Joining.** The family owner creates an encrypted **invite** (`.hminvite`, passphrase-protected; it carries the
    family key). The member chooses **Join a family** in their own profile.
  - **Publishing.** From then on their app writes `<sync folder>\<family id>\<member id>.hmfamily` after changes, at
    most every ten minutes, or at once with **Share now**.
    - The file is their database only (no documents or images), taken with SQLite's backup API.
    - It is encrypted with the family's random 32-byte key (AES-256-GCM, the same chunked format as shares).
    - It is written to a temporary name and then renamed, so a half-synced file is never read.
  - **The sync folder** can be any folder both computers see, such as a shared OneDrive folder. Only ciphertext is
    written there.
  - **Importing.** The family computer checks every minute and imports a new copy through a `.importing` file. It
    imports only after decryption, family and member checks, a schema upgrade if the member's app is older, and
    SQLite's integrity check.
  - **Refusals.** A copy from a newer app version, the wrong family or a different key is refused, and the member's
    status says why.
- **Counted once.** The family works on its own adjusted copies (`<family folder>\view\`).
  - **Shared accounts.** An account two members both recorded (same institution, type and last four digits) counts for
    the member listed first. The other copy leaves out its transactions, statements and the receipts matched to them.
  - **Transfers within the family.** Sometimes the same amount leaves one member's account and arrives in another's
    within three days. If either line reads like a transfer (Zelle, Venmo, transfer…) or names the other member, it is
    a transfer within the family: neither spending nor income.
  - Home lists both kinds under "Counted once".

## Family inbox

- **One upload for the house.** A family profile has its own library at `<family folder>\library`, with an Inbox,
  reading and Review like anyone's.
  - Nothing recorded there counts in any total until it is routed. Family totals still come only from members'
    libraries.
  - While the family is open, Home, Review, Receipts & statements, Documents, Processing and Settings are available.
- **Who is it for?** Review lists every family record with a **For** choice: one person, or *Shared by the family* for
  receipts. Statements and pay stubs belong to one person.
  - The app suggests an owner when exactly one member has an account ending in the card digits printed on a receipt
    (`receipts.payment_last_four`), or in a statement's account.
  - For a pay stub, the suggestion is an employer that exactly one member already has pay stubs from.
  - Nothing is sent until you choose **Send**.
- **Sharing a cost.** The total is divided into equal whole-cent parts among the people ticked (`splits.equal_shares`:
  50.01 between two is 25.01 and 25.00; the first listed gets the extra cent).
  - Each person's library records the receipt and their part in `record_shares`.
  - Spending, categories (each item category keeps its proportion), budgets and the forecast count only that part.
  - The person whose card paid has the full charge on their statement. When it is matched to the shared receipt, it
    too counts only their part, and Transactions notes "Shared expense · your part … counted".
  - Across the family, the parts add up to the purchase, counted once.
- **Delivery.** The record, the document and the person's part travel together, encrypted with the family key (migration
  035).
  - **A person on the family's computer:** their library is updated straight away.
  - **A person on their own computer:** a file waits in `<sync folder>\<family id>\to-<member id>\`, and their app
    imports it within a minute of their profile being open.
    - The import never re-reads the document with a model (`Store.import_document`); it files the document from the
      confirmed record.
    - Delivered records count, since the family confirmed them, but the person can still reject one in their own
      Review.
  - **Changes.** Sending the same record again (to a new person, or with a different split) replaces what each person
    has. Anyone no longer on it gets a withdrawal, which rejects their copy.
- **Not included yet** ([open work](open-work.md)):
  - A shared recurring bill's payments still count in full for whoever paid.
  - Records corrected in the family library after they were sent need **Send** again to update people's copies.

## Sharing a library

One person exports an encrypted `.hmshare` file. Another person opens it as a temporary, separate library
(`Manager.start_share_export` / `start_session` / `end_session`).

**Use**
- **Share:** Settings → Sharing → *Share your library*. Choose a folder, an optional name, and a passphrase of at least
  12 characters. Send the file, and give the passphrase another way (a call, not the same message).
- **Open:** Settings → Sharing → *Open a shared library*. A banner shows whose library is open. **End session**
  deletes the copy and reopens your library.

**Guarantees**
- **Your library is never written during a session.** It is closed when the session opens and reopened when it ends.
  Settings keep naming your library. Switching library folders, backups and share exports are refused during a
  session.
- **The copy is temporary.** It lives in `<settings folder>\sessions\<id>` and is deleted when the session ends, when
  Home Manager exits, or at the next start after a crash. Anything done in the session goes to the copy only and is
  discarded with it.
- **Encryption.** AES-256-GCM in 1 MiB chunks, with the key derived from the passphrase by scrypt (N = 2^17, r = 8,
  p = 1; about 0.25 s and 128 MB).
  - The header is authenticated with every chunk. Each nonce encodes the chunk's position and whether it is the last.
  - So a wrong passphrase, a changed byte, reordered chunks or a truncated file all fail.
  - Passphrases are never stored, logged or echoed in errors.
- **Import safety.** The archive is read as a stream and written by Home Manager itself.
  - Only plain files at paths inside the backup layout are accepted: no absolute paths, drives, `..` or links.
  - Size and entry limits apply.
  - Every file is checked against the backup manifest, and the database's integrity is checked, before the copy opens.

**Limits**
- A share is a snapshot. Later changes in the sender's library need a new share.
- Sessions don't persist across restarts, by design.
- The passphrase is the only protection once the file leaves the sender's computer. Use four or more unrelated words.

## Family GPU

Family members without a GPU send their model calls to one GPU computer over **Tailscale**. Their documents and
database stay on their own machine.

**On the GPU computer.** `home-manager gpu-host` runs the relay (`models/gpu_host.py`). It is a small separate stdlib
`ThreadingHTTPServer` process, independent of the main app, so it can run as a Windows startup task.
- **Commands:** `home-manager gpu-host [serve --bind 100.x.y.z]`, `gpu-host add-member NAME`,
  `gpu-host remove-member NAME`, `gpu-host members` (details in [operations](operations.md#commands)).
- **Two listeners on one port (8766):**
  - the Tailscale IP, where a per-member bearer token is required. `add-member` prints the token and stores only its
    SHA-256. Tailscale provides encryption and device identity; the token adds revocation per person;
  - 127.0.0.1, with no token and any model. The owner's own app points here, so everyone shares one queue and one
    residency manager.
- **Role aliases.** Members ask for `home-manager/vision`, `home-manager/reasoning`, `home-manager/reviewer` or
  `home-manager/decision`.
  - The host maps these to the models in its own `vision.json`, `reasoning.json`, `reviewer.json` and `decision.json`,
    read on each request.
  - `reviewer` falls back to the reasoning model when no reviewer chat model is set.
  - Members never choose model names, and the owner can change models centrally.
- **What it forwards.** `GET /v1/models` (filtered), the model details used for identity, and
  `POST /v1/chat/completions` streamed straight through to local LM Studio. It also forwards `/v1/responses`, for the
  decision role only.
- **Queue and residency.** There is one first-in, first-out queue across all clients. Before forwarding, the relay
  makes sure the requested model is the only one loaded ([operations](operations.md#local-models)).
  - When several requests are waiting, those for the model already loaded go first, with a cap so nothing starves.
  - While a streamed request is queued, the relay sends SSE comment keepalives (`: queued 2`), which the client
    ignores. A queued decision request waits without keepalives, because its reply is one JSON object.
- **Managed marker.** The relay answers `GET /api/v1/models` with a `managed_by` marker, so an app pointed at it skips
  its own residency calls.
- **Privacy.** The relay never logs or stores request or response bodies. It logs only member, model role, token
  counts and duration. A loopback-only `GET /status` shows who is running and who is queued.

**On a member's computer.** In Settings → Local models, choose "Model computer: Family GPU (Tailscale)" and enter the
host URL and token (`model_computer.json`: `provider`, `gpu_host_url`, `manage_model_loading`).
- **The token** is kept in `gpu_token.txt` in the settings folder. It is never part of a config, a run option or an API
  response.
- **The URL** may be only `http://<100.64.0.0/10 address or *.ts.net host>:PORT/v1`. This PC's own model settings stay
  saved, and the vision and reasoning forms still accept loopback only.
- **Error messages.** A rejected token says to ask the host for a new one. A connection failure says the family GPU
  computer is offline or not on Tailscale.
- **Test connection** works unchanged.
- **Residency** is skipped on members' computers, because the host owns it.
- **A System One decision server** is not behind the relay, and stays on the member's PC.
