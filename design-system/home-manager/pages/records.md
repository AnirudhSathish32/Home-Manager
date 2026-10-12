# Records (Phase 2)

These are the page overrides for Records v2 (`records_v2.js`, routes `#/documents` and `#/receipts`). MASTER.md wins
wherever this file says nothing. The hand-off is `../phase2-rest-plan.md` Build A.

**The user's jobs** (docs/documents.md "Browsing the library"): see what has arrived and what still waits (not read,
to record, to review, couldn't process), clear that backlog, find a document by folder, state, date or words, and file,
move or delete documents.

Shared: the needs-attention row (`.needs-row.attention`, `--warning-subtle`) as the work strip, tables (sticky sunken
header, right-aligned amounts), 30px chips (pressed = `--accent-subtle` with an `--accent` border), status badges
through `statusBadge` ("Couldn't process" is `danger`, an error; Not read / Needs review are `warning`), one primary per
page. Money out is `−` in `--text`, never red.

## Records (built 2026-10-11, Build A)
- **Components:**
  - Header: h1 "Documents" or "Receipts & statements" with v1's subtitle (`LIBRARY_SCOPES`); Refresh (secondary). No
    primary in the header.
  - **Work strip:** shown when any work count is above zero; the non-zero counts in `WORK_FILTERS` order
    ("21 not read yet · 2 ready to record · 4 need review · 1 couldn't process"), each a `link-button` that sets
    `status`. **Read all N** (primary, book-open icon) only when not-read is above zero: it collects the store's
    not-read ids (`status=needs_text`, 200 a page, up to 500) and posts one `/api/receipt-batches`; a 409 shows the
    server's message in the strip. With nothing waiting, one muted line: "Everything here has been read." with a
    positive check.
  - **Toolbar:** search (250ms debounce), the state chips with counts, From/To and Sort in `details#rc2-more` (forced
    open from 600px, its summary "More filters" shown only below). A muted, polite "Showing {folder} · {state} ·
    “q” · {dates} — Clear filters" line when anything is filtered; Clear keeps only the store.
  - **One region** (`.rc2-browser`, `--surface`, 1px border, `--radius-md`): the folder tree (220px, right border) beside
    the list pane. Tree rows are `button.rc2-folder` in a `16px minmax(0,1fr) auto` grid (icon, wrapping label, count),
    `aria-current="page"` on the chosen one with `--accent-subtle`; Receipts → categories and Jobs → employer →
    Paystubs/Documents are `aria-expanded` groups; Trash last (trash-2 icon).
  - **List pane:** breadcrumb h2 with the count; the folder's description; **Empty trash…** (secondary, Documents only)
    through `confirmAction` with danger wording; the sticky selection bar (N selected · Read · Combine (2–20 images,
    else disabled with a title) · Move · Delete, or Restore in Trash · Clear); the table (checkbox, Name with file name,
    snippet and notes under it, Folder, Date, Amount, State with the match state, then the next step as a text link
    and ⋯); the pager (50 a page, shown only past one page).
  - **Next step** as v1 `nextStep` chooses: Restore, Import (`openImport({onDone})`), Read, Record; its name includes
    the title ("Read Target"); "Starting…" while it posts; a failure is an `alertBox` in the state cell. Model steps carry
    `data-step`, so `controls()` disables them while model work runs.
  - **⋯ menu** ("More actions for {title}"): Edit description…, Versions (n), Move, Delete, then the managed path.
- **Layout:** 1440: as above. Under 1100px the tree becomes `select#rc2-folder` (indented categories and jobs; employers
  as disabled headings) and dates/sort take their own line. Under 820px rows stack on the same table: checkbox · name ·
  amount, then folder · date, then state · step · ⋯; the head is visually hidden and select-all moves into the selection
  bar. Under 600px the strip stacks (Read all full width), the chips scroll in one row, and dates/sort fold into More
  filters.
- **URL:** `#/documents?folder=&category=&employer=&section=&status=&q=&from=&to=&sort=&offset=` (the same keys on
  `#/receipts`); non-default values only; each is checked against `/api/folders`, `WORK_FILTERS` and the sorts, and a
  bad one is dropped. A page past the end falls back to the first.
- **States:** loading, no library and a first-load error through `pageState`; a later error above the list with Retry.
  Empty: filtered → "No documents match." with Clear filters; Inbox or All → the Inbox path with a copy button; other
  folders → "Nothing in {folder}.".

### Decided
- One `data-page="documents" data-ui="v2"` section serves both routes; `loadRecordsV2` sets `libraryScope` (the shell's
  nav highlight and `leaveDocument`) and `libraryCatalog` (the shared move dialog's folder list reads it).
- The shared dialogs (move/delete, description) are library.js's; the list catches up on their `close` event.
  `restoreDocuments` and `openImport` are awaited or given `onDone`.
- `app.js` `poll()` calls `rc2Refresh` while work runs; it redraws only when the folders or page changed, and waits for
  an open row menu to close.
- The sidebar's Inbox and Unfiled set `#/documents?folder=…` while the screen is on (`showFolder` guard).
- Rows stack below 820px, as the plan's "Changes by file" says, so at 768 the rows are stacked too (the plan's
  Layout section said the table stays at 768).
- The Name-column check at 390 measures the name cell, not the link, since a short title's link is narrower than 120px.
