# Sharing a library

One person exports an encrypted `.hmshare` file; another opens it as a temporary, separate library. Implemented 2026-09-25 (`library/share.py`, `Manager.start_share_export` / `start_session` / `end_session`).

## Use

- **Share:** Settings → Sharing → *Share your library*. Choose a folder, an optional name, and a passphrase of at least 12 characters. Send the file; tell the passphrase another way (a call, not the same message).
- **Open:** Settings → Sharing → *Open a shared library*. A banner shows whose library is open. **End session** deletes the copy and reopens your library.

## Guarantees

- **Your library is never written during a session.** It is closed when the session opens and reopened when it ends. Settings keep naming your library; switching library folders, backups and share exports are refused during a session.
- **The copy is temporary.** It lives in `<settings folder>\sessions\<id>` and is deleted when the session ends, when Home Manager exits, or at the next start after a crash. Anything done in the session (questions, readings, reviews, descriptions) goes to the copy only and is discarded with it.
- **Encryption:** AES-256-GCM in 1 MiB chunks; key from the passphrase with scrypt (N = 2^17, r = 8, p = 1, about 0.25 s and 128 MB). The header is authenticated with every chunk, and each nonce encodes the chunk's position and whether it is the last, so a wrong passphrase, a changed byte, reordered chunks or a truncated file all fail. Passphrases are never stored, logged or echoed in errors; validation errors from the API never repeat submitted values.
- **Import safety:** the archive is read as a stream and written by Home Manager itself. Only plain files at paths inside the backup layout are accepted (no absolute paths, drives, `..`, links); size and entry limits apply. Every file is then checked against the backup manifest and the database's integrity before the copy opens.

## Limits

- A share is a snapshot. Later changes in the sender's library need a new share.
- Sessions do not persist across restarts by design.
- The passphrase is the only protection once the file leaves the sender's computer; use four or more unrelated words.

# Profiles and families

Implemented 2026-09-28 (`app/profiles.py`, `app/family_sync.py`, `finance/family.py`; plan in `docs/profiles-and-family-plan.md`).

## Profiles

- Each person on a computer has a **profile**: their own library folder (its own `inventory.sqlite3`, originals and Inbox) and their own financial preferences (`<settings folder>\profiles\<id>\household.json`). Model settings stay per computer.
- The registry is `<settings folder>\profiles.json`. On the first start with profiles, the library in `settings.json` becomes a profile named "My profile", with the computer's old `household.json`. Nothing is moved.
- Switch with the **Profile** menu in the sidebar, or with Settings → Profiles & family. Switching closes one library (releasing its lock) and opens the other, the same way changing the library folder always has. It is refused while work runs or a shared-library session is open.
- Removing a profile only forgets it. Its folder stays on disk, and adding the same folder again brings it back (a family folder comes back as the family).

## Families

- A **family profile** holds no records. It adds up its members' spending, cash flow, bills, needs-attention counts and net worth, and shows each person's own row. Members' records are never changed from the family; its own library is only an inbox for uploads (see Family inbox below).
- **Members on this computer:** the family copies their library's database directly (read-only) whenever it changes.
- **Members on their own computer:** the family owner creates an encrypted **invite** (`.hminvite`, passphrase-protected: it carries the family key). The member chooses *Join a family* in their own profile. From then on their app writes `<sync folder>\<family id>\<member id>.hmfamily` after changes, at most every ten minutes, or at once with *Share now*. The file is their database only (no documents or images), encrypted with the family's random 32-byte key (AES-256-GCM, the same chunked format as shares). The sync folder can be any folder both computers see, such as a shared OneDrive folder. Only ciphertext is written there.
- The family computer checks every minute. It imports a new copy through a `.importing` file, and only after decryption, family and member checks, a schema upgrade when the member's app is older, and SQLite's integrity check. A copy from a newer app version, the wrong family or a different key is refused, and the member's status says why.
- **Counted once:** the family works on its own adjusted copies (`<family folder>\view\`). An account two members both recorded (same institution, type and last four digits) counts for the member listed first; the other copy leaves out its transactions, statements and the receipts matched to them. The same amount leaving one member's account and arriving in another's within three days, where either line reads like a transfer (Zelle, Venmo, transfer…) or names the other member, is a transfer within the family: neither spending nor income. Home lists both kinds under "Counted once".
- Family totals are exactly the sum of the per-person rows: each member's figures come from the same functions an individual profile uses, added in minor units per currency.

## Family inbox

Implemented 2026-09-28 (`finance/family_routing.py`, `app/family_sync.py` deliveries, migration `035_family_shares.sql`).

- **One upload for the house.** A family profile has its own library at `<family folder>\library`, with an Inbox, reading and Review like anyone's. Nothing recorded there counts in any total until it is routed: family totals still come only from members' libraries. While the family is open, Home, Review, Receipts & statements, Documents, Processing and Settings are available.
- **Who is it for?** Review lists every family record with a **For** choice: one person, or *Shared by the family* for receipts and bills. Statements and pay stubs belong to one person.
  - The app suggests an owner when exactly one member has an account ending in the card digits printed on a receipt (`receipts.payment_last_four`, read as the optional `card_last_four` field), or in a statement's or bill's account. For a pay stub, the suggestion is an employer exactly one member already has pay stubs from.
  - Nothing is sent until you choose **Send**.
- **Sharing a cost:** the total is divided into equal whole-cent parts among the people ticked (`splits.equal_shares`: 50.01 between two is 25.01 and 25.00, the first listed gets the extra cent).
  - Each person's library records the receipt and their part in `record_shares`.
  - Spending, categories (each item category keeps its proportion), budgets and the forecast count only that part.
  - The person whose card paid has the full charge on their statement. When it is matched to the shared receipt, it too counts only their part, and Transactions notes "Shared expense · your part … counted".
  - Across the family, the parts add up to the purchase, counted once.
- **Delivery:** the record, the document and the person's part travel together, encrypted with the family key.
  - **A person on the family's computer:** their library is updated straight away.
  - **A person on their own computer:** a file waits in `<sync folder>\<family id>\to-<member id>\`, and their app imports it within a minute of their profile being open. It never re-reads the document with a model (`Store.import_document`), and it files the document from the confirmed record. Delivered records count, since the family confirmed them; the person can still reject one in their own Review.
  - **Changes:** sending the same record again (a new person, or a different split) replaces what each person has. Anyone no longer on it gets a withdrawal, which rejects their copy.
- **Not included yet:**
  - A shared bill records each person's part, but bill payments still count in full for whoever paid, as before.
  - Records corrected in the family library after they were sent need **Send** again to update people's copies.
