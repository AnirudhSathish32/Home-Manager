# Profiles, family and sharing

Each person has their own library. A family view adds the members up without merging their data, and a family inbox
takes one upload for the whole house. An encrypted `.hmshare` export lets someone look at a copy of your library. One
GPU computer can run the models for the whole family, and for friends testing the app.

Ground rules:
- **Each member runs the app on their own PC.**
- **Only model calls leave a member's machine** (rendered page images and text prompts, sent to the shared GPU).
- **Documents and databases stay local.** The exceptions are the encrypted family snapshot and family deliveries
  described below, which only ever travel as ciphertext, over Tailscale, to and from the family computer's hub.

Code: `app/profiles.py`, `app/family_sync.py`, `app/family_hub.py`, `app/family_client.py`, `finance/family.py`,
`finance/family_routing.py`, `library/share.py`, `models/gpu_host.py`. Tests use two control folders
(`--control-dir A` and `B`) to act as two PCs, with the family computer's hub on loopback (`tests/test_family_hub.py`).

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
  switch. Families exchange only encrypted database copies and deliveries, through the family hub (below), which
  listens only on the family computer's Tailscale address.

## Families

- **A family profile holds no records of its own.** It adds up its members' spending, cash flow, bills,
  needs-attention counts and net worth, and shows each person's own row. Members' records are never changed from the
  family.
- **Family totals are exactly the sum of the per-person rows.** Each member's figures come from the same functions an
  individual profile uses, added in minor units per currency.
- **Members on this computer:** the family copies their library's database directly (read-only) whenever it changes.
- **Members on their own computer:**
  - **Joining.** The family owner creates an encrypted **invite** (`.hminvite` version 2, passphrase-protected). It
    carries the family key, the hub's Tailscale address and a new token for that member; a new invite replaces the
    member's previous token. The member chooses **Join a family** in their own profile. An invite from before the hub
    (version 1) is refused with "Ask the family computer for a new invite", and a membership made with one shows
    **Re-join needed**.
  - **Sending copies.** From then on their app seals a copy after changes, at most every ten minutes, or at once with
    **Share now**, and sends it to the hub.
    - The copy is their database only (no documents or images), taken with SQLite's backup API.
    - It is encrypted with the family's random 32-byte key (AES-256-GCM, the same chunked format as shares). Its sealed
      header carries a `seq` that rises with every copy.
    - It is sealed into `<settings folder>\family\<family id>\outbox\copy.hmfamily` first and sent from there, so it
      waits while the family computer is off; a newer copy replaces an unsent one.
  - **Status.** Settings shows "Synced <time>", or "Waiting for the family computer · last synced <time>" while it
    can't be reached (the app backs off from one minute, doubling to 30), or the hub's reason when it refused.
  - **Importing.** The hub stages the upload in `<family folder>\incoming\`, then installs it through a `.importing`
    file. It installs only after decryption, family and member checks, a `seq` above the last accepted one, a schema
    upgrade if the member's app is older, and SQLite's integrity check.
  - **Refusals.** A copy from a newer app version, the wrong family or member, a different key or an old `seq` is
    refused, and the member's status says why. After a re-join the member's numbering restarts; the hub's refusal
    names its last `seq` and the member's next copy is numbered above it.
- **The family hub** (`app/family_hub.py`) runs inside the app on the computer holding the family folder, whichever
  profile is open, on port 8767. The app holds each family folder open for it while it listens.
  - It listens only on this computer's Tailscale address (`models/http_server.py` `check_bind`, shared with the GPU
    relay), never on 0.0.0.0, a LAN address or loopback. Without Tailscale it doesn't listen, Settings says why, and
    invites can't be made; the app tries again every minute.
  - Every route needs the member's bearer token. Only its SHA-256 is kept, in `family.json`, compared with
    `hmac.compare_digest`; a token works only for its own family and member, and removing a member or making them a new
    invite ends the old token at once. GPU relay tokens and hub tokens are separate.
  - Routes: `GET /v1/ping`; `PUT /v1/families/{fid}/members/{mid}/copy`; `GET …/deliveries`; `GET` and `DELETE`
    `…/deliveries/{key}`; `POST …/blobs/missing`; `PUT …/blobs/{hash}`. Bodies are streamed to disk in 1 MiB chunks (a
    copy at most 4 GiB, a document at most 1 GiB), never logged; the log has member, route, status and time only.
- **Members' documents.** After each copy the hub accepts, the member's app asks which documents its records cite
  (receipts, statements, bills, pay stubs, assets, tax forms, investment documents and their evidence links) the
  family doesn't hold, and sends each one sealed with the family key (`.hmblob`, its header naming the family, member
  and hash). If that is cut short, it carries on at the next sync.
  - The hub decrypts each upload to check that it hashes to its name, then keeps the sealed bytes at
    `<family folder>\blobs\<hh>\<hash>.hmblob`: encrypted at rest, content-addressed (a repeat changes nothing), with no
    cap on the total. Settings shows the total next to the hub's address.
  - **Opening an original from the family view** (`/api/documents/{id}/image?member=<member id>`) works while the
    member's app is stopped. A member on this computer is read from their library folder; anyone else from the
    family's copy, decrypted as it streams.
- **Security** (reviewed and approved 2026-10-05):
  - **Exposure.** Its own port, the Tailscale address only, and no route into the main app, which stays on 127.0.0.1.
    Shared-GPU testers are kept off it by the tailnet policy in [Shared GPU](#shared-gpu).
  - **Confidentiality and integrity.** Every copy, delivery and document is sealed with the family key (AES-256-GCM,
    `library/share.py`), inside Tailscale's WireGuard. A stolen token alone can't read or forge one.
  - **Replay.** A copy's `seq` must rise; documents are content-addressed; deliveries and corrections have unique keys
    and apply once.
  - **Limits.** Bodies are streamed to disk with per-copy and per-document caps; paths follow a fixed grammar (ids and
    hex hashes only); no body is logged.
  - **Not covered:** a compromised family computer; a member's computer compromised while it holds the family key;
    `members\*.sqlite3`, which sit decrypted on the family computer. A stolen token can't read anything, but it can
    acknowledge (and so delete) a member's waiting deliveries; the member's computer keeps the token in its settings
    folder.
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
  - While the family is open, Home, Review, Receipts & statements, Documents, Processing, Settings and the family
    ledger (below) are available.
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
  - **A shared return** ([money](money.md#returns)) is divided the same way, in negative parts. Each person's refund is
    their part: the card holder's credit, matched to the return receipt, counts their part, and everyone else's return
    receipt counts theirs. A shared purchase and its shared return net to zero for each person.
  - A refund credit is never paired with another member's payment as money sent between members.
- **Delivery.** The record, the document and the person's part travel together, encrypted with the family key (migration
  035).
  - **A person on the family's computer:** their library is updated straight away.
  - **A person on their own computer:** a file waits in `<family folder>\outbox\to-<member id>\` until their app pulls
    it from the hub (within a minute of their profile being open), applies it and acknowledges it, which deletes it.
  - **A person on the family's computer whose library was busy** gets the same file, and imports it from the family
    folder directly when their profile is next open.
    - The import never re-reads the document with a model (`Store.import_document`); it files the document from the
      confirmed record.
    - Delivered records count, since the family confirmed them, but the person can still reject one in their own
      Review.
  - **Changes.** Sending the same record again (to a new person, or with a different split) replaces what each person
    has. Anyone no longer on it gets a withdrawal, which rejects their copy.
  - **After Send**, a delivered record is the person's own: correct it from the family ledger ([Family
    corrections](#family-corrections)), not in the family's inbox.
- **Not included yet** ([open work](open-work.md)): a shared recurring bill's payments still count in full for whoever
  paid.

## Family ledger

- **Transactions, Spending & budgets, Bills & recurring and Accounts** show every member's records in the family view,
  each row with its **Owner** (`finance/family.py` `family_tool`).
  - Each page asks the same finance tool a person's own page asks (`POST /api/finance/tools/{name}?members=true`), once
    per member's view copy, so a joint account counts once and transfers between members aren't spending.
  - List rows are merged and tagged `member_id` and `owner`; a page of transactions is the same slice of the merged list
    (each member is asked for offset + limit rows). Totals are added exactly in minor units per currency, so they match
    Home's family figures.
  - Without `members=true` a family profile's tools read its own library, the inbox, as Review and Home expect.
- **Accounts** in a filter are `<member id>:<account id>`, since ids are only unique within one library.
- **Drawers and originals.** A record opens from its owner's copy (`GET /api/finance/records/{type}/{id}?member=`), and
  its documents open from the family computer ([Families](#families), "Members' documents").
- **Read-only parts.** Budgets, category rules, item categories, recurring-payment decisions and the recurring scan are
  each person's own and aren't shown. Spending shows each currency; the USD total isn't (each member converts with
  their own rates).

## Family corrections

- **Sending.** In the family ledger's transaction drawer, **Send correction** changes a member's category, merchant or
  date (`PATCH /api/finance/records/{type}/{id}?member=`, `Manager.correct_family_record`). Receipts, bills, pay stubs
  and statements take the same fields as a person's own correction, through the API.
  - The value is checked with the person's own correction rules against the family's view of the record; a value that
    already matches is refused.
  - The family keeps a `sent` row in its own library (`family_corrections`, migration 062) and sends a delivery.
    A member on this computer whose library isn't open gets it straight away; anyone else pulls it from the hub.
  - The family view shows the new value at once, tagged **Waiting for <member>**, until the member's next copy answers
    (its sealed header lists each received correction's status).
- **On the member's computer** (`finance/family_corrections.py` `apply_correction`), each key applies once:
  - the field still reads what the family saw: it is corrected, with the actor "Family · <who>" and the reason "Family
    correction", and the record's history shows "changed by family (<who>)" with **Reject**;
  - it already reads the new value: nothing changes, and it counts as applied;
  - the member changed it since: a Review question, "Your family changed something you changed too", answered **Use
    family's** or **Keep mine** (resolutions `took_family` and `kept_mine`).
- **Reject** (`POST /api/finance/family-corrections/{key}/reject`) puts the previous value back under the member's own
  name. The family isn't notified; the record shows the member's value in the family view once their next copy arrives.

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

## Shared GPU

People without a GPU send their model calls to one GPU computer over **Tailscale**. Their documents and database stay
on their own machine. Members are either **family** or **testers**: friends outside the family trying the app. A tester
needs no family, and the GPU computer never sees their library, only the model calls.

**On the GPU computer.** `home-manager gpu-host` runs the relay (`models/gpu_host.py`). It is a small separate stdlib
`ThreadingHTTPServer` process, independent of the main app, so it can run as a Windows startup task.
- **Commands:** `home-manager gpu-host [serve --bind 100.x.y.z]`, `gpu-host add-member NAME [--tester]
  [--expires YYYY-MM-DD]`, `gpu-host remove-member NAME`, `gpu-host members` (details in
  [operations](operations.md#commands)).
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
  - Prompts (page images and text) still pass through LM Studio, so keep any LM Studio option that logs or saves
    request contents turned off on the GPU computer.

**Testers.**
- **Tokens expire.** `add-member NAME --tester` gives a token that works for 30 days (`TESTER_DAYS`), or until
  `--expires`. An expired token gets 401, as a revoked one does, and takes effect without restarting the relay.
  `members` shows each person's kind and expiry. A `gpu_host.json` from before kinds existed reads as family members
  with no expiry.
- **Family first.** A tester's request waits behind this computer's and the family's, but is skipped at most
  `MAX_SKIPS` times, so it is never starved.
- **Joining the tailnet.** Share only the GPU computer with each tester through Tailscale's machine sharing; don't
  invite them into the tailnet. Restrict shared users to the relay in the tailnet policy:

  ```json
  {"grants": [{"src": ["autogroup:shared"], "dst": ["tag:gpu"], "ip": ["tcp:8766"]}]}
  ```

  `tag:gpu` is the tag on the GPU computer, and the port is the one in `gpu_host.json`. The default allow-all rule
  (`"src": ["*"]`) also covers shared users, so narrow it to `autogroup:member` first. Then a tester can't reach any
  other port or computer, including the family hub (port 8767).
- **Their side** is the same as a family member's, below.

**On a member's computer.** In Settings → Local models, choose "Model computer: Shared GPU (Tailscale)" and enter the
host URL and token (`model_computer.json`: `provider`, `gpu_host_url`, `manage_model_loading`).
- **The token** is kept in `gpu_token.txt` in the settings folder. It is never part of a config, a run option or an API
  response.
- **The URL** may be only `http://<100.64.0.0/10 address or *.ts.net host>:PORT/v1`. This PC's own model settings stay
  saved, and the vision and reasoning forms still accept loopback only.
- **Error messages.** A rejected token says to ask the host for a new one. A connection failure says the shared GPU
  computer is offline or not on Tailscale.
- **Test connection** works unchanged.
- **Residency** is skipped on members' computers, because the host owns it.
- **A System One decision server** is not behind the relay, and stays on the member's PC.
