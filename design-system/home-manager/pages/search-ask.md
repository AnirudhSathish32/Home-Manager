# Search and Ask (Phase 2)

These are the page overrides for Search v2 (`search_v2.js`, route `#/search`) and the Ask panel (`assistant.js`,
restyled in place). MASTER.md wins wherever this file says nothing. The hand-off is `../phase2-rest-plan.md` Build B.

**The user's jobs:**
- **Search:** find one record by a word (a merchant, product, file name, account or the words inside a document) and
  open it in its own place, without knowing which store holds it.
- **Ask** (docs/assistant.md "The Ask panel"): ask a question about the household's records beside the page they're
  on, and see where each answer came from.

Shared: tinted regions (`.today-region`, never nested; 1px dividers inside), 30px chips (pressed = `--accent-subtle`
with an `--accent` border), status badges through `statusBadge`, one primary per region. Money out is `−` in `--text`,
never red.

## Search (built 2026-10-11, Build B)
- **Components:**
  - Header: h1 "Search" and the muted subline "Documents, transactions, household items and accounts in one place."
    No header actions.
  - **Input row:** `#se2-input` (max 720px) and `#se2-submit` (primary, search icon). The polite status line
    `#se2-status`: "Searching…", then "14 matches for “fresh”.".
  - **Kind chips** (`#se2-kinds`, a group named "Kind"): All, Documents, Transactions, Items, Accounts, each with its
    total. A chip with 0 is disabled unless it's the chosen one.
  - **Groups:** one `section.today-region` per kind with matches, h2 "Documents · 9". "Show all 9" (`link-button`, right
    of the heading) when "All" shows fewer than the total.
  - **Rows** (`.se2-row`, `minmax(0,1fr) auto`, 1px dividers): the title link, a muted detail line, then the right
    side. Documents: `documentHref` (opens at the matched lines), "folder · date", the snippet with `<mark>` clamped to
    two lines (full text in `title`), the ledger amount unsigned. Transactions: a `link-button` opening the drawer,
    "date · account · category", the signed amount. Items: a link to `#/inventory?q=`, "category · bought date", the
    status badge. Accounts: a link to the account's transactions, "institution · currency".
  - **Single kind:** up to 50 rows; past that, "Open these in Documents" / "Open in Transactions".
- **Layout:** at 1440 the groups stack in the page width. Under 600px the input row stacks (the button goes full
  width), the chips scroll in one row, and amounts sit under the name.
- **States:** empty query (a hint with focus in the box); loading (the status line); error (`alertBox` error with
  Retry in the results, the form stays usable); no results ("Nothing matches “coffee”." plus "Try fewer words, or
  search the text of your documents or your transactions."); a chosen kind with none ("No accounts match …" with
  "Show every kind"); no library (`pageState`).
- **Decided:** `?q=&kind=` in the URL (kind left out when it's all); "All" asks the server for 6 per kind, a kind for
  50; a newer search drops older replies. The page's own form keeps the kind; the sidebar box and Ctrl+K / "/" set
  only `q`. Search isn't a family route.

## Ask (restyled in place 2026-10-11, Build B)
- **Placement:** `aside#assistant-panel.side-panel` in `.app-shell`, sharing the breakdown's 360px track
  (`--panel-width`). `.app-shell.assistant-open` opens the third column from 1180px; at 900–1179px it floats over the
  right edge (`--shadow-overlay`, non-modal); under 900px it's a bottom sheet, 80vh. Opening Ask closes the breakdown,
  and opening a breakdown closes Ask (focus stays with the figure). Toasts move left of the column, or to the top over
  a sheet.
- **Components:**
  - Header: h2 "Ask", the muted line "Answers from your records by the local model, with where each came from.", and
    the close button (x icon, "Close Ask").
  - **Log** (`#assistant-log`, polite live region) scrolls on its own between top and bottom rules. Each exchange is
    the question (semibold `--text`, the time muted on the right), then the answer (`--text-sm`, 1.5 line height,
    secondary), evidence chips (30px pills, accent text), the unverified-figures warning, missing evidence, and "How I
    got this (N lookups)". 1px dividers, no bubbles.
  - **Waiting:** a spinner and "Looking through your records with the local model…".
  - **Earlier questions** (`details#assistant-earlier`, collapsed) under the log: a divided list, 30vh at most.
  - **Composer** pinned to the bottom with a top rule: the textarea (3 rows, resizes up to 8), then "Ctrl+Enter to
    ask" muted on the left and **Ask** (primary) on the right.
- **States:** empty log ("Ask about your spending, bills or documents." plus three example questions that fill the
  box); no library; no reasoning model (warning with "Set one up"); a failed run (`alertBox` error with the server's
  message); family profile (Ctrl+J does nothing, as before).
- **Decided:** restyled in place, not a `data-ui="v2"` twin: it isn't a page, and a twin would duplicate the polling
  and history code. Every id is kept. Non-modal: focus isn't trapped; opening focuses the textarea; Escape inside
  closes it and returns focus to `#nav-ask`. Reduced motion drops the slide.
