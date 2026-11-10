# A new Inbox file is a new document, even under an old file's name
Feature: inbox-document-identity

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: `docs/documents.md` "The managed library" ("A changed Inbox file creates a new captured version") for a file whose
Inbox copy has already been organized away; the rule stands for a file that is still in the Inbox. No approved spec covers
capture identity; the baseline below is taken from the code.

## Decisions already made (not to be re-asked)
- **D1 This is a defect worth fixing first** (user, 2026-11-09): reported as "evidence → document.pdf goes to the statement
  I read in but haven't approved", after an earlier transaction's evidence opened a pay stub. Diagnosed in the session
  that wrote this spec (below); the user asked for all three follow-ups to be specified.
- **D3 The capture fix first, the repair through a plan** (user, 2026-11-10): "Capture fix now, repair via plan". FR-01 –
  FR-05 were built and committed (`3466ebb`); FR-06 – FR-10 go through the test design and plan.
- **D4 Product decisions** (user, 2026-11-10, choosing each default): OD-1 the earliest file keeps the id; OD-2 watched
  folders are out of scope; OD-4 no "split from" link, counts only; OD-5 every piece of a document in Trash stays in
  Trash.
- **D2 Nothing private is read to write or test this.** Detection and repair are specified from the code and tested on
  synthetic libraries. How many of the user's documents are merged is unknown; the user may run the diagnostic of FR-09
  in their own terminal (CLAUDE.md "Private financial data").

## Goal / users / scope / non-goals
**Goal.** Two different files never become one document just because they reached the Inbox under the same name. A
document's versions are only the same file changed while it sat at its source path. Documents already merged that way
are split back apart, with every record, reading and decision following the file it came from.

**Users.** The household user dropping downloads (often all named `document.pdf`, `statement.pdf`, `download.pdf`)
into `Library/Inbox`, and a family member whose delivery arrives through the same capture path.

**In scope.** Capture identity for the Inbox and for family deliveries (FR-01 – FR-05); a one-time repair of documents
already merged (FR-06 – FR-08); a redacted diagnostic (FR-09); docs (FR-10).

**Non-goals.**
- Watched folders (OD-2 default). A watched folder's file is copied, never moved, so a file overwritten in place
  there is still a new version, as today.
- Telling a real edit from a different document by content (a second reading, a similarity check). Identity is decided
  from where the file was when it changed, not what it says.
- Merging two documents by hand, or a "these are the same document" link for split documents (OD-4 default).
- Any change to how a record counts, or to blobs, readings or evidence bytes.

## Existing behavior (verified paths, assumptions, unknowns)
Paths under `src/home_manager/` unless noted. Read at HEAD `06cbb9b` plus this session's uncommitted changes. FR-01 – FR-05 were built in `3466ebb` (2026-11-10); what follows is the
baseline the repair (FR-06 – FR-10) starts from.

- A document is an `occurrences` row keyed by `UNIQUE(source_root, path_key)` (`library/migrations/001_inventory.sql:28`,
  kept by `050_strict_tables.sql:830`). Its versions are `versions(occurrence_id, hash, …)` rows; `current_hash` is the
  latest.
- Capture (`library/storage.py` `publish`, `:412 – :441`) looks for an occurrence with the same `source_root` and
  `path_key`. If one exists, the new bytes become its `new_version` (or `unchanged`), whatever happened to the earlier
  file. Otherwise a new occurrence is made; identical bytes elsewhere get a `same_bytes` link.
- Right after capture the Inbox file is moved into the Library (`library/managed_library.py` `ensure_capture` `:159`,
  `ensure_document`; `finish` `:354` sets `source_status='organized'` for an Inbox occurrence). The occurrence keeps its
  Inbox `source_root` and `path_key`. So the next file dropped in as `document.pdf` matches it and becomes its next
  version. **This is the defect.**
- Family deliveries use the same path: `Store.import_document(name, data)` (`library/storage.py:453`) captures under
  `Inbox/<name>` and then looks the document up by that path.
- Records cite a version, not just a document: `statements`, `receipts` (bills included), `income_records` and
  `financial_evidence_links` carry `document_id` and `blob_hash`. `publish_statement` finds an earlier statement by
  `blob_hash` (`finance/ledger.py:1227`); receipts by `blob_hash` and `segment` (`:724`). So a merged document's older
  records still exist. They are shown under a document whose page opens the newest file.
- The transaction drawer's evidence link opened `#/documents/<id>` with no version. This session changed it to open the
  cited version and lines (`app/static/finance.js` `openTransaction`). Other places that link to a document by id alone
  (library rows, the account's "Open statement", Review) still open its newest version.
- Managed file names embed the document id (`docs/documents.md` "File names"); `managed_files` is keyed
  `(document_id, blob_hash)`.
- **Unknown:** the full list of tables keyed by `document_id` (or `occurrence_id`) that must follow a split. Known so far:
  `versions`, `managed_files`, `managed_organization_intents` and `_events`, `document_folders`, `library_events`,
  `occurrence_links`, `extraction_runs`, `document_segments`, `statements`, `receipts`, `income_records`,
  `financial_evidence_links`, `transaction_imports`, `pdf_import_index`, document groups, Trash state, tags, donation
  records and the family tables in `app/family_sync.py` `CITING_TABLES`. The plan must list them from the schema.
- **Unknown:** whether an Inbox file can change in place before it is organized often enough to matter. When filing is
  blocked (an edited or locked file), the file stays in the Inbox, so it can.

## Functional requirements
| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | A file captured at an Inbox path whose document's Inbox copy was already organized away starts a **new document**, never a version of the earlier one. | Drop file A as `Inbox/document.pdf`; it is captured as document 1 and organized. Drop a different file B as `Inbox/document.pdf`: B is a new document 2 with one version. Document 1 still has one version (A); its page, file and records are unchanged. The capture event's status is `captured`, not `new_version`. |
| FR-02 | A file that changes **while still in the Inbox** (not yet organized) stays a new version of its document, as today. | File A sits in the Inbox with filing blocked; replace its bytes with A′ at the same name: the document gains version A′; no new document. |
| FR-03 | Dropping the **same bytes** again under the same name after it was organized stays one document, as today (the Inbox copy is consumed and nothing new is made). | Drop A, let it organize, drop A again as `document.pdf`: still one document with one version, and the Inbox is empty afterwards. |
| FR-04 | Identical bytes under another name keep today's `same_bytes` link and shared reading. | Unchanged behavior: test kept green. |
| FR-05 | A **family delivery** follows FR-01 and FR-03: two deliveries with different bytes under the same name are two documents. | Deliver X then Y, both named `receipt.png`: two documents, each with its own record; delivering X again adds nothing. |
| FR-06 | **Repair at upgrade.** A document already merged this way is split. A version counts as merged in when it was captured after the document's Inbox copy of the version before it was organized. Each such version becomes a new document, and the **earliest version keeps the original id**. A version captured before the earlier one was organized (a real edit, FR-02) stays a version. | Synthetic library: document 1 with versions A (organized), then B captured after A's organization, then C captured after B's organization. After upgrade: document 1 has only A; new documents hold B and C, one version each. A document whose two versions were both captured before any organization keeps both. |
| FR-07 | **Everything follows its version.** In the repair, every row that names the merged document and the split version's `blob_hash` moves to the new document: readings, extraction runs, records (statement, receipt, bill, pay stub, investment), evidence links, transaction imports, segments, managed files, folder choices, tags, library and organization history, links, Trash state, donation and family rows. Rows not tied to one version stay with the earliest. No row is dropped and no blob or file byte changes. | After upgrade: every record's `document_id` names a document whose versions include its `blob_hash`; the number of rows in each affected table is unchanged; every blob's hash is unchanged; opening each record's document shows that record's file. |
| FR-08 | **Library files after the repair.** A split document's Library copy is renamed to carry its new id through the normal durable organization (recorded intents, never overwriting); until then it stays where it was and still opens. | After upgrade and one organization pass: each split document's managed path holds its own id; no file was overwritten; a pass interrupted halfway resumes at the next start. |
| FR-09 | **Redacted diagnostic.** A command reports, for the open library, how many documents would be or were split and how many versions moved, as counts only (no file names, paths, merchants or amounts). | Run on a synthetic merged library, the output holds numbers and fixed words only; a test asserts no fixture name or path appears in it. |
| FR-10 | **Docs.** `docs/documents.md` "The managed library" says which changes are versions and which are new documents. The open-work item is removed when this ships. | Doc text present; `docs/open-work.md` entry gone. |

## Invariants, privacy, security and data retention
- Nothing leaves the machine; no model or network call is added.
- Blobs (the evidence store) are never rewritten or deleted. The repair changes database rows and, through FR-08's
  normal organization, Library copy names only.
- The repair runs as one schema upgrade inside the existing upgrade-and-recovery path (`docs/documents.md` "Schema
  upgrades and recovering from a failed one"): all of it or none of it.
- Logs and the FR-09 report hold counts only.
- A record's decision (confirmed, rejected), corrections and history are kept as they are; only the document they hang
  from changes.

## Errors, recovery, duplicates, restart behavior
- An upgrade that fails part-way leaves the library as it was before the upgrade, with today's recovery message.
- A capture interrupted between "new document" and "organized" recovers as today's captures do; repeated recovery
  never makes a second new document for the same capture intent.
- If a later version's organization history is missing (a blocked or never-finished move), the repair cannot prove it
  was merged in, so it stays a version (FR-06), and FR-09 counts it as "left as a version, history incomplete".

## Nondeterministic outputs and how they are verified
None. Capture and repair are deterministic; ids of new documents are checked by what they hold, not by value.

## Scenarios
| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-01 | Empty library | Drop A as `document.pdf`; wait for organize; drop B as `document.pdf` | Two documents; doc 1 versions = [A]; doc 2 versions = [B]; the event for B is `captured` |
| SC-02 | FR-02 | A in Inbox, filing blocked | Replace A's bytes with A′ under the same name | One document, versions [A, A′] |
| SC-03 | FR-03 | A organized | Drop A again as `document.pdf` | One document, one version; Inbox empty |
| SC-04 | FR-05 | Empty library | Family delivers X `receipt.png`, then Y `receipt.png`, then X again | Two documents with one record each; the third delivery adds nothing |
| SC-05 | FR-06, FR-07 | Synthetic library at the previous schema: doc 1 with A (statement, confirmed, rows with evidence), B (pay stub record), C (unrecorded statement reading), each captured after the previous was organized | Start the app (upgrade) | Doc 1 = A with its statement, rows and evidence; doc B and doc C are new, each with its own reading, record and history; table row counts and blob hashes unchanged; the evidence link of A's rows opens A |
| SC-06 | FR-06 | Doc with versions A, A′ both captured before any organization | Upgrade | Unchanged: one document, two versions |
| SC-07 | FR-07 | As SC-05, plus a tag, a folder choice, a Trash entry and a transaction import on B | Upgrade | Each follows B to its new document |
| SC-08 | FR-08 | After SC-05 | One organization pass; interrupt a second split document's rename and restart | Each split file carries its own id; the interrupted one finishes at the next start; nothing overwritten |
| SC-09 | Errors | As SC-05 with a fault injected in the middle of the repair | Upgrade | Library exactly as before the upgrade; recovery message shown |
| SC-10 | FR-09 | After SC-05 | Run the diagnostic | Counts only (1 document split, 2 versions moved); no fixture name or path in the output |
| SC-11 | FR-06, FR-09, Errors | Doc with A, B; A filed but its organization history missing | Upgrade; run the diagnostic | Unchanged; "left as a version, history incomplete: 1" |
| SC-12 | FR-07, R5 | As SC-05, plus another document with B's bytes and a `same_bytes` link | Upgrade | The link names B's new document and the other one |
| SC-13 | FR-06 | After SC-05; separately a library never merged | Upgrade again; upgrade | Nothing changes either time |
| SC-14 | FR-06, FR-01, FR-03 | As SC-05, but C still in the Inbox | Upgrade; scan; drop D as `document.pdf` after C is filed | C's document holds the Inbox path; the scan reports unchanged; D is a new document |

Recommended: run `design-tests` before approval. The repair is stateful and touches many tables.

## Out of scope / product decisions requiring approval
- **OD-1 Which version keeps the original id.** Default: the earliest. Its records are the ones the user has had
  longest, and links from outside (bookmarks, Review history) most likely mean it.
- **OD-2 Watched folders.** Default: out of scope, recorded in `docs/open-work.md`. A re-download that overwrites
  `statement.pdf` in Downloads will still become a new version there. Alternative: treat a watched-folder change as a
  new document when the earlier version has a record.
- **OD-3 Other links by id alone.** Default: in scope only as far as the repair makes them right. Library rows, "Open
  statement" and Review links open the newest version; after the repair each document's newest version is its own file,
  so no link change is needed.
- **OD-5 Trash on a merged document** (from the test design). `deleted_at` is one flag per document. Default: every
  split document keeps the merged document's Trash state. Alternative: only the document holding the merged
  `current_hash` stays in Trash.
- **OD-4 Show that two documents were split.** Default: no link; the FR-09 report and the upgrade note say how many.
  Alternative: an `occurrence_links` reason `split_from` shown under "Also found".

**Domain risk candidates (accept or reject each):**
- **R1 Recorded rows matched across the split.** A transaction matched to a receipt, or a deposit matched to a pay
  stub, when both records were under the same merged document. Unhandled: matches could look like "same document"
  links. Default: links between records are untouched (they name records, not documents); `same_record`
  `occurrence_links` that would now point a document at itself are re-pointed to the split documents.
- **R2 A shared `.hmshare` or family copy names the old document id.** Unhandled: the family's copy points at the
  wrong file after the split. Default: family rows follow their version (FR-07), and the next sync sends the
  corrected ids. The plan confirms how family ids are keyed.
- **R3 Donated documents.** A donation of a merged document may have sent the newest version under the old id.
  Default: donation rows follow their version; nothing is re-sent.
- **R4 Very large merged documents** (one `document.pdf` with hundreds of versions). Default: no limit; the repair is
  one pass over versions in capture order.
- **R5 A version that is both merged in and a duplicate** (its bytes also exist at another path). Default: it becomes
  its own document and keeps its `same_bytes` link.
