# Home Manager UI design plan

Status: **reviewed 2026-09-24** (decisions in §10). Implementation proceeds by phase (§9). It replaces `homepage-proposal.md`, which only covered the document list.

Inputs: `Home_Manager_Architecture_Implementation_Spec.docx`, `v2-phases.md`, and the current frontend (`static/index.html`, `style.css`, `app.js`, `library.js`, `receipt.js`, `finance.js`), plus the API it calls (`api.py`, `finance_tools.py`, `storage.py`).

---

## 1. What exists today

### 1.1 Shell

One page with three tabs: **Documents**, **Finances**, **Scans & activity**. The header has a brand mark, header count chips (Inbox, Unfiled, Needs review), a live activity pill with Cancel, and a gear icon that opens **Settings** as a modal. Other modals: Move/Delete confirmation, Import transactions, Preserved versions, and the full-screen **Document inspector**. A 1.5-second poll of `/api/settings` drives the busy state and activity.

### 1.2 Current user workflows

| # | Workflow | Where it happens today |
|---|---|---|
| W1 | First run: choose the source and managed directories | Settings modal → Directories |
| W2 | Configure the vision, reasoning, and checker models (LM Studio or Laya) | Settings modal → Local model |
| W3 | Capture: drop files in Inbox (auto-watched) or scan source folders | Scans & activity; the Inbox is watched in the background |
| W4 | Browse and search the library by folder and work filter | Documents tab |
| W5 | Extract text, then extract to the ledger (one document or all) | Row primary action, toolbar "Extract text for all", inspector steps |
| W6 | Inspect a document: image or text evidence beside the ledger record, cite-to-source | Inspector dialog |
| W7 | Verify or reject a ledger record | Inspector ledger heading, Finances → Needs review |
| W8 | Optional audit analysis, parse or analysis history, rotation, provenance | Inspector → Audit analysis / History & processing |
| W9 | Import CSV/XLSX transactions with a column mapping preview | Row action "Import transactions" → Import dialog |
| W10 | Monthly finances: spending, cash flow, categories, accounts, bills, recurring payments, refunds, transactions | Finances tab |
| W11 | Reconcile now; review proposed links and ambiguous issues | Finances tab |
| W12 | Categorize a transaction | Free-text input in each Finances transaction row |
| W13 | Move, delete to Trash, restore, and view versions | Row "More" menu, Trash folder |
| W14 | Watch or cancel running model work; read model telemetry | Header pill; Scans & activity → Model history |

A redesign has to keep every one of these working.

### 1.3 Usability problems

1. **Documents are the home screen, and finances are a secondary tab.** The first thing the user sees is a file browser with processing badges. Nothing answers "what is happening with my money?"
2. **The Finances tab is seven equal-weight bullet lists.** Figures sit inside sentences ("$X net spending ($Y spent, $Z refunded, N transactions)"), so they can't be scanned vertically or compared. Coverage caveats sit in a small grey paragraph.
3. **The review queue exposes internals.** Items look like `receipt #12 · needs review` and `Proposed receipt link: transaction #4 and receipt #9 (score 7; amount, date, merchant)`. There's no merchant, amount, or date, no link to the evidence, and no way to see why something needs review before clicking Verify.
4. **"Needs review" has no home.** The header chip jumps to the Finances tab, where the queue is one list among seven.
5. **The transactions table is thin.** It has only a month filter and a silent 200-row cap. Review state is raw text (`proposed · not counted`). A category text box in every row adds noise and gives no save feedback. There's no detail view and no way to see the receipt or statement behind a row.
6. **Document rows lead with processing state.** Each row shows three badges ("Text: succeeded / Ledger: needs review / Audit: not analyzed") and a relative path under the title. There's no document date column; rows sort by path.
7. **Operational controls sit in the browsing surface.** "Extract text for all" and "Include documents that already have text" live in the Documents toolbar, and batch status appears as a sentence under it.
8. **The inspector is a modal that replaces everything.** Its title changes as data loads (filename → parse title → document type → ledger title). The three process cards compete with the ledger record, provenance is a raw JSON `<pre>`, and two interpretations (the ledger record and the audit analysis) sit on one screen with similar weight.
9. **Errors are raw.** `api()` surfaces `detail` verbatim, or `JSON.stringify(detail)` for validation errors. One global notice line handles every message, and it's mirrored into Settings.
10. **Settings mixes first-run setup with advanced model plumbing.** Directories, home currency, three model endpoints, and the checker all share one modal. Backup doesn't exist.
11. **Scans & activity is a log.** It shows a scan picker, a raw path/result/detail events table, and model history hidden in a `<details>`. Capture, transcription, extraction, normalization, and reconciliation don't have separate states.

### 1.4 Visual problems

- **Every `<button>` is a filled green primary by default**, so a screen can show a dozen equally loud buttons. `.secondary` is opt-in.
- **Every `<section>` is a white card** with a 14px radius, 24px padding, and a border. The design is card-first by default.
- **Radii are inconsistent:** 20, 16, 14, 12, 10, 8, 6, 5, and 4px all appear.
- **The palette is green everywhere.** Brand, primary buttons, focus rings, links, and totals are all green. Green can't also mean *verified* or *money in*.
- **`style.css` is two generations layered.** The original rules are followed by a "Compact workspace layout" block that overrides them (`h1`, `main`, `.file-browser`, `.row-status`, `.document-actions` are each defined twice or more).
- **Type sizes are ad hoc:** .65, .68, .7, .72, .74, .75, .76, .78, .8, .82, .83, .85, .86, .87, .88rem. Tabular numerals appear only in a few tables.
- **Money shows as `-1,234.56 USD`.** The code comes last, there's no symbol, sign treatment is uniform, and the text never aligns in lists.

### 1.5 What works and must survive

- **The browser never does money arithmetic.** Figures come from server tools as exact strings. The design keeps this rule; see §6.
- **Provisional data is kept apart from verified data:** proposed, needs review, verified, and rejected, plus "not counted" and pending-review totals.
- **Evidence citations** ("Find in transcription", overlay polygon highlighting).
- **Capture and inference run on separate queues**, and model work can be cancelled from anywhere.
- **Destructive actions require confirmation.** Trash is reversible, and the dialog is explicit that nothing is deleted from disk.
- **Existing accessibility work:** ARIA tabs with arrow keys, native `<dialog>`, live regions, and `prefers-reduced-motion`.
- **The security envelope.** The strict CSP (`script-src 'self'; style-src 'self'`), the bearer token in the URL fragment, and no third-party assets. The redesign adds **no CDN fonts, scripts, or chart libraries**. Icons and any font are vendored under `static/`.

---

## 2. Information architecture

Organize around the user's questions, not the database tables.

```
┌──────────────────────┬────────────────────────────────────────────────────────┐
│ HM  Home Manager     │  Page header: title · period/context · page actions      │
│ ⌕ Search      Ctrl K │  ───────────────────────────────────────────────────── │
│                      │                                                          │
│ Overview             │                                                          │
│ Review          ●12  │                   page content                           │
│                      │                                                          │
│ MONEY                │                                   ┌──────────────────┐  │
│ Transactions         │                                   │ detail drawer    │  │
│ Spending             │                                   │ (non-modal,      │  │
│ Bills & recurring    │                                   │  keeps list      │  │
│ Accounts             │                                   │  context)        │  │
│                      │                                   └──────────────────┘  │
│ RECORDS              │                                                          │
│ Documents            │                                                          │
│   Inbox 3 · Unfiled 2│                                                          │
│                      │                                                          │
│ ──────────────────── │                                                          │
│ ◌ Transcribing IMG… │                                                          │
│   14 s        Cancel │                                                          │
│ Processing           │                                                          │
│ Settings             │                                                          │
└──────────────────────┴────────────────────────────────────────────────────────┘
```

### 2.1 Primary navigation

| Group | Item | Purpose | Replaces |
|---|---|---|---|
| — | **Overview** | Current financial state and what needs attention | (new) Finances-tab summary lists |
| — | **Review** (count badge) | One actionable queue for everything that needs a human decision | Finances → Needs review; the header "Needs review" chip |
| Money | **Transactions** | Search, filter, and inspect every canonical transaction | Finances → transactions table |
| Money | **Spending** | Where money went: categories, merchants, period comparison | Finances → Spending / By category / Refunds |
| Money | **Bills & recurring** | Obligations: upcoming bills, payment state, recurring payments | Finances → Upcoming bills / Recurring |
| Money | **Accounts** | Each account's balance-as-of, coverage, and import source | Finances → Accounts; the account part of Import |
| Records | **Documents** | Library browser and the evidence inspector | Documents tab |
| System | **Processing** | Queues, jobs, scan history, model telemetry | Scans & activity |
| System | **Settings** | Setup and preferences, with advanced options kept separate | Settings modal |
| (reserved) | **Assistant** | Phase 9. Not shown in navigation until the backend exists (§7) | — |

The design decisions behind this table:

- **Review sits directly under Overview, not in a group.** It's the only place that asks the user to act, and its badge is the one place in the app that asks for attention.
- **Accounts sits last under Money.** With statement-only balances, it's a reference screen rather than a daily one.
- **Documents shows Inbox and Unfiled counts inline** as sub-links. The header chips they replace were a good idea in the wrong place.
- **The processing indicator lives in the sidebar footer**, where it's always visible (it replaces the header pill). Clicking it opens Processing. It stays silent when idle.
- **Spending gets its own page** rather than an Overview section. Overview shows only the headline and top categories and links through.

### 2.2 Routing and context preservation

- Use **hash routes** (`#/transactions?account=3&from=2026-09-01`, `#/documents/418`). The server serves only `/` and static files, so the backend doesn't change. The existing `#token=` handling runs first and is then removed with `replaceState`, which is compatible.
- Filters live in the URL, so Back, reload, and "open in a new window" all keep the current view.
- **Detail drawer** (non-modal, right side, 480–560px, resizable later). Used for transactions, review items, bills, recurring payments, and accounts. The list stays visible and scrollable. <kbd>Esc</kbd> closes the drawer, and <kbd>↑</kbd>/<kbd>↓</kbd> in the list moves the selection while the drawer is open.
- **The document inspector stays a full-workspace view**, because side-by-side evidence needs the width. It becomes a route (`#/documents/418`) opened over the current page, not a `<dialog>`. Back returns to the exact list position and filters. "Open document" links from the transaction drawer, Review, and the Assistant all lead here.
- **Global search** (<kbd>Ctrl</kbd>+<kbd>K</kbd>) queries documents (existing `q`) and transactions (existing `query`), with results grouped by type. Phase C.

---

## 3. Screens

Each screen spec covers: the user's question · primary action · hierarchy · components · secondary actions · states. "Backend:" notes mark data that doesn't exist yet (collected in §7).

### 3.1 Overview

**User question:** "What is happening with my finances right now, and does anything need me?"
**Primary action:** none by default. When the review count is above zero, **Review N items** is the one primary button on the page.

**Hierarchy (top to bottom, one column at the fold with a right rail at ≥1440px):**

1. **Attention strip.** Shown only when something needs the user. One quiet horizontal band that says, for example, "12 items need review · 2 documents failed processing · 1 bill past due, no payment found", with each phrase linking through. When nothing is outstanding it collapses to a single muted line: "All caught up · last import 2 days ago".
2. **This month.** One typographic block, not tiles. Net spending in large type, next to cash in, cash out, and net cash flow at body size, plus the change from last month with a direction arrow and text ("▲ 214.10 more than August"). Directly under the figures, a coverage line: "Covers Chase Checking (Sep 1–24) and Amex (Sep 1–20). 3 transactions awaiting review aren't counted." Coverage is part of the number's truth, not fine print.
3. **Spending trend.** A six-month bar chart of net spending, with the current month highlighted as partial.
4. **Two columns:**
   - **Upcoming bills** (next 45 days): due date, provider, amount, and payment state.
   - **Accounts**: name, balance-as-of with an "as of Sep 20" date, and stale balances (more than 35 days old) marked.
5. **Two columns:**
   - **Recent transactions**: the last 8 counted transactions, with a link to Transactions.
   - **Top categories**: 5 rows with inline proportional bars, and a link to Spending.
6. **Recently added documents**: the last 5 captured, with type, date, and a one-word state (Filed, Unfiled, or Needs review). Links to Documents.

**Components:** PageHeader (with period picker), AttentionStrip, FigureGroup (the "this month" block), ChartContainer + BarChart, Panel (a titled section with a "View all" link; a border, no heavy card), CompactTable, AmountDisplay, StatusBadge, EmptyState.

**Secondary actions:** change the month; "Reconcile now" (moved into the page's `⋯` menu); "Import transactions" (opens the import flow from Accounts).

**States:**

| State | Treatment |
|---|---|
| Not configured | A full-page welcome with a three-step setup: 1) choose the managed library folder, 2) optionally add a source folder, 3) optionally connect a local model. Nothing else renders. |
| Configured, no financial data | Documents and processing sections render. The money blocks are replaced by one explanation: "No transactions yet. Import a bank CSV/XLSX export or extract a statement to see spending," with two actions. There are no zero-filled charts. |
| Loading | Skeleton rows at their final dimensions (no spinners in content); figures show `—` placeholders at the final size so nothing shifts. |
| Error (tool call failed) | Only the failing panel shows an inline alert with "Couldn't load upcoming bills. Retry." The rest of the page still renders. The technical detail is in a disclosure. |
| Needs review | The attention strip, plus a pending-review note beside any affected figure ("+ 84.20 USD awaiting review, not counted"). |
| Mixed currencies | One figure row per currency, never summed. The primary currency (the home currency) comes first. |

### 3.2 Review

**User question:** "What does Home Manager need me to decide, and how fast can I clear it?"
**Primary action:** confirm or reject the selected item.

**Layout:** a two-pane queue. On the left, the queue list grouped by kind with counts. On the right, the item detail with evidence and decision buttons. The keyboard flow is <kbd>J</kbd>/<kbd>K</kbd> to move, <kbd>V</kbd> to verify, and <kbd>R</kbd> to reject, and each decision advances to the next item.

**Queue groups (in priority order), mapped to existing data:**

| Group | Source | What the item shows | Decision |
|---|---|---|---|
| Failed processing | documents with failed parse or extraction status | document, stage, user-facing reason | Retry · Open document |
| Ambiguous matches | `review_queue.issues` (open reconciliation issues) | the receipt plus N equally plausible transactions side by side | Choose one (Backend: a resolve-issue endpoint) · Leave unmatched |
| Proposed receipt ↔ transaction links | `review_queue.links` (kind = receipt) | receipt summary ↔ transaction summary, with the matching signals listed in plain words ("Same amount · 2 days apart · merchant matches") | Confirm match · Not a match |
| Proposed transfers and refunds | `review_queue.links` (kind = transfer/refund) | both transactions, with the reason | Confirm · Not a transfer |
| Extracted records awaiting verification | `review_queue.records` | record type, merchant/provider, date, amount, validation issues in plain language | Verify · Reject · Open document |
| Unfiled documents | `folders.counts.Unfiled` + documents in Unfiled | document, why it's unfiled | Move to… · Open document |

Rules for every item:

- Every item shows **what**, **why it needs you**, and **the evidence** (a thumbnail or cited lines with Find in source). Internal IDs and `match_score` numbers never appear in the default view. The score and method are in a Details disclosure.
- Decisions are **reversible from the record's history**. Undo is offered in a toast for 8 seconds.
- **Backend:** today `review_queue` returns IDs, dates, and issues only, and links return only two IDs. The item needs a display summary: merchant, amount display, date, account, and document ID for both sides. This is a read-only enrichment of the existing tool (§7, B1).

**States:** empty ("Nothing needs your review. New documents and imports will appear here if Home Manager is unsure about them," plus the last-checked time) · loading (list skeleton) · error (inline, per group) · a decision that failed (the item stays selected and shows an inline error; the queue doesn't advance).

### 3.3 Transactions

**User question:** "What exactly happened, and what's the evidence?"
**Primary action:** find a transaction and open it.

**Toolbar (one row, sticky):** search (description/merchant) · date range (preset menu: This month, Last month, Last 90 days, Year to date, Custom) · Account (multi-select) · Category · Type (Purchases, Refunds, Transfers & payments, Income, Fees & interest) · Status (Counted, Awaiting review, Rejected) · Evidence (Has receipt, No receipt) · a "Clear filters" link when any filter is active. The active filter summary and result count show under the toolbar: "142 transactions · Sep 1 – Sep 24 · 3 accounts."

**Table (the reference implementation of DataTable):**

| Column | Width | Treatment |
|---|---|---|
| Date | 96px | `Sep 24`, with the year shown only when it differs from the current year; the transaction date appears in a tooltip when it differs from the posted date |
| Description | flex | merchant (normalized) in regular weight, raw description muted beneath, truncated to one line with a tooltip |
| Account | 160px | account short name + `··4821` |
| Category | 140px | a text label; editing happens in the drawer, not inline |
| Evidence | 32px | a paperclip icon when a receipt or statement is linked, with an accessible label |
| Status | 120px | shown only when the transaction isn't counted: "Awaiting review" (amber) or "Rejected" (grey, struck through). Counted rows show nothing, and that absence is the calm state. |
| Amount | 128px | right-aligned tabular numbers; money in shows `+` in the positive color, money out shows `−` in the default ink; transfers are muted with a ⇄ icon |

- Sortable by Date, Amount, and Description. The default is date descending.
- Group separators by day or month are off by default and available as an option.
- Density toggle: compact 32px rows or comfortable 40px rows.
- A footer row shows "Showing 142 of 142". When capped, it says "Showing first 1,000. Narrow the filters." The cap is never silent.
- Totals are **not** shown in the table footer. They'd require client-side arithmetic. A "Summarize these" link goes to Spending with the same filters, which the server computes.

**Transaction drawer:** header with the amount (large), description, date, and account. Then status plus the Verify/Reject buttons if the transaction is awaiting review. Then Category (editable select with free entry, with an explicit saved or failed state). Then **Evidence**: the linked receipt (merchant, total, items preview, "Open receipt"), the source statement or import file (document name, page or row, "Open document"), and transfer or refund links. Then **History**: review events. Then **Details** (disclosure): origin, fingerprint, and the raw description.

**Backend:** server-side filters for category, type, status, and receipt linkage; an offset for pagination; and sort order. Today `get_transactions` filters only by date, account, and query. Also a transaction detail that includes evidence and links. `/api/finance/records/transaction/{id}` returns the row but not its evidence or links (§7, B2–B3). Until those exist, Phase B filters the ≤1000 returned rows client-side (filtering only, no arithmetic) and marks the drawer's evidence section "unavailable".

**States:** no accounts yet (empty state with Import) · no results (show the active filters, and "Clear filters") · loading (a skeleton of 12 rows) · error (inline alert above the table; the filters stay usable).

### 3.4 Spending

**User question:** "Where did my money go, and how does that compare?"
**Primary action:** change the period or comparison.

**Hierarchy:** the period picker plus "compare to" (previous period, same month last year). Then a headline figure row (net spending, spent, refunds, number of transactions, excluded transfers and card payments) as one typographic row. Then **By category**: a horizontal bar list with the amount, share, and change versus the comparison period, where clicking a category filters Transactions. Then **Top merchants** (the same pattern). Then **Refunds**: posted credits, plus refund evidence awaiting settlement, labeled "Refund receipt found; no posted credit yet". Then the **coverage and notes** block, rendered from the tool's `notes` and `coverage` rather than hardcoded.

**Components:** PeriodPicker, FigureGroup, BarList (a table with inline bars, accessible as a table), CompactTable, Callout (for the notes).

**Backend:** a monthly trend series. The Overview/Spending trend chart can call `get_spending` once per month (six calls, all server-computed, which is acceptable). A dedicated `spending_series` tool would be cleaner (§7, B4). Category "change versus the prior period" requires `get_spending_by_category` for both periods and a client-side diff, which is arithmetic. Instead: B5, a server-side comparison, or omit the change column until then.

**States:** no counted spending ("No counted spending in this period"; if there are pending items: "84.20 USD awaits review"); uncategorized-heavy ("68% of spending is uncategorized · Categorize in Transactions"); loading and error as elsewhere.

### 3.5 Bills & recurring

**User question:** "What do I owe, when, and has it been paid?"
**Primary action:** open a bill and confirm its payment state.

**Layout:** two sections.

- **Bills**: a timeline-ordered table. The first group is Past due, no payment found (red with an icon), then Due in the next 7 days, then Later, then Paid (collapsed). Columns: due date, provider, amount due, payment state, and the source document. The drawer shows the bill document, the matched payment transaction if found, and the review state.
- **Recurring payments**: merchant, expected amount, frequency, next expected date, and status (Proposed/Verified). A proposal gets "Confirm recurring" or "Not recurring".

`get_upcoming_bills` states "no payment found" only reflects imported transactions. The page shows that as a persistent footnote, not a tooltip.

**Backend:** `payment_status` (unknown/unpaid/paid) exists on bills, but there's no endpoint to set it manually, and recurring obligations have no review endpoint. The reconcile review endpoint covers links, not obligations (§7, B6). A calendar view is out of scope.

**States:** no bills ("Bills appear here after a bill document is extracted"); an item needs review; loading and error.

### 3.6 Accounts

**User question:** "Which accounts do I have, what did they last show, and is my data complete?"
**Primary action:** Import transactions (CSV/XLSX).

**List:** one row per account, grouped by type (Cash: checking and savings; Credit; Investments; Loans). Row: institution + name + `··4821`, last statement balance with an "as of" date (credit cards labeled "amount owed"), data coverage ("Transactions Jan 3 – Sep 20"), and a freshness marker. **No sum across accounts**: the server doesn't compute one, and statement balances from different dates don't add into a meaningful total. If the owner wants a "cash on hand as of statements" figure, it must come from a server tool that states its dates (§7, B7).

**Account drawer:** statements list (period, closing balance, review state, open document), coverage gaps (Backend: months with no statement and no imported transactions), recent transactions, and a link to Transactions filtered by the account.

**Import flow:** the existing Import dialog, restructured as a three-step dialog: 1) choose the file (from the Documents library; Backend: a file picker that *captures* a new file isn't in scope, so files must first arrive through the Inbox), 2) account and column mapping with a live preview, 3) a confirmation with counts. Behavior is unchanged; the remembered account stays in `localStorage`.

**States:** no accounts (explain both routes: CSV/XLSX import, or statement extraction); a balance with no statement ("No statement balance yet · Balances aren't estimated from partial transaction history," which is the existing honest message, kept).

### 3.7 Documents

**User question:** "Where is that document, and has Home Manager understood it?"
**Primary action:** open a document.

**Layout:** a folder rail (180px: All, Inbox, Unfiled, then the flat library folders, then Trash, each with a count; Inbox and Unfiled show a count badge when nonzero) plus a table.

**Toolbar:** search · Status filter (All, Needs text, Ready for ledger, Needs review, Failed; these are the existing `WORK_FILTERS`, renamed in user language: "Not read yet", "Read, not recorded", "Needs review", "Couldn't process") · Type (Backend) · Date range (Backend) · selection actions appear only when rows are selected: "Process selected", "Move…", "Delete…". **Batch "Extract text for all" moves to Processing.**

**Table columns:**

| Column | Treatment |
|---|---|
| Name | The title if the model or ledger proposed one, otherwise the filename. When a title exists, the filename appears muted underneath. There's no path by default. |
| Type | The folder/type label ("Receipt", "Bank statement") |
| Date | The document's own date (purchase date, period end, due date). Backend B8: the list query doesn't return a ledger date yet. |
| Amount | `ledger_amount` right-aligned (exists) |
| State | **One** summary badge derived from the three existing statuses (see the mapping below). The three-step detail moves into the inspector and a tooltip. |
| Actions | Open (the row click) · `⋯` menu: Process next step, Versions, Move, Delete (danger, confirmed) |

**Document state mapping (UI-only, derived from existing fields):**

| Existing fields | Summary shown |
|---|---|
| `deleted_at` set | In Trash |
| parse/extraction `queued`/`running` | Processing… (live) |
| latest parse or extraction `failed`/`interrupted` | Couldn't process |
| `cancelled` | Cancelled |
| no text run, image/PDF | Not read yet |
| text run, no `ledger_status` | Read, not recorded |
| `ledger_status` proposed/needs_review | Needs review |
| `ledger_status` verified | Recorded ✓ |
| `ledger_status` rejected | Rejected |
| `ledger_status` imported (CSV/XLSX) | Imported ✓ |
| CSV/XLSX not imported | Ready to import |

The audit analysis status is **not** part of the summary. It's an optional, secondary tool.

**Managed location and provenance** move into the inspector's Details panel and the `⋯` menu ("Show managed location").

**Backend:** the spec's §20 asks the library to show reconciliation state and an unfiled reason. Neither is in the document list query (B8, B9). There's no document date or type filter (B8). The sort is `relative_path` only (B8).

**States:** unconfigured (link to Settings) · empty library ("Drop files into `<Inbox path>`, or add a source folder", with the copyable Inbox path) · empty folder · no search results · Trash explainer (the existing text, kept) · loading (skeleton) · error.

### 3.8 Document inspector

**User question:** "Is what Home Manager recorded actually what this document says?"
**Primary action:** Verify (or Reject) the recorded values. For unread documents, the primary action is **Read document**, the next step.

**Layout (full workspace, split 45/55, draggable divider):**

```
┌ ← Back to Documents   Costco receipt · Sep 15, 2026            Needs review   ⋯ ┐
├──────────────── SOURCE EVIDENCE ───────────┬──────── RECORDED INFORMATION ───────┤
│ [Image] [Text]            zoom − 100% +  ⟳ │ Merchant   Costco          Find ↗  │
│                                            │ Date       2026-09-15      Find ↗  │
│   ┌──────────────────────┐                 │ Total      163.82 USD      Find ↗  │
│   │   receipt image with │                 │ ── Checks ─────────────────────── │
│   │   highlighted region │                 │ ⚠ Items sum to 162.82; total 163.82│
│   └──────────────────────┘                 │ ── Items (14) ─────────────────── │
│                                            │ table…                              │
│ Original preserved · captured Sep 16       │ ── Linked transaction ──────────── │
│                                            │ Amex ··7314 · Sep 16 · −163.82  →   │
│                                            │                                     │
│                                            │           [Reject]  [Verify record] │
├────────────────────────────────────────────┴─────────────────────────────────────┤
│ Processing: Read ✓ · Recorded ✓ · Linked ✓        Details · History · Audit       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- **The title is set once** from the best available name and never changes as data loads. The document type and date are in the subtitle.
- **Left pane:** image with the overlay, or the text transcription for PDFs. Adds zoom and page navigation for PDFs (page IDs exist in the evidence). Clicking a field's "Find" highlights the region or line. Clicking a region highlights the fields that cite it (reverse lookup is UI-only).
- **Right pane:** the canonical record only. Field rows are label, value, Find. Checks (validation issues) use plain-language callouts. Items and transactions use DataTable. **Linked records** show the reconciliation link to the transaction (Backend B3).
- **The process footer** replaces the three step cards: a compact stepper (Read → Recorded → Linked) with each step's state. Clicking a step opens its run history. Re-run actions live here and in `⋯`, not as primary buttons.
- **Tabs in the footer drawer:**
  - **Details**: managed path, original source path, source status, versions, hash (monospace, copyable), current version.
  - **History**: parse, extraction, and review runs, with telemetry per run.
  - **Audit**: the optional line-by-line analysis. It's labeled **"Model interpretation, not your record"** and styled as secondary (no amounts in large type, no green).
- The Laya panel stays an advisory disclosure under Checks, labeled "Independent check (advisory)".

**States:** loading (both panes skeleton, title from the list row) · unread ("Home Manager hasn't read this document yet. [Read document]", with the model requirement noted if no model is configured) · reading (live stage and elapsed time, Cancel) · read but not recorded ("Record it to your ledger [Extract to ledger]") · recorded but needs review · verified (a quiet confirmation line with who and when; the Verify button becomes "Verified ✓ · Undo") · failed (a user-facing reason plus Retry, with the raw error in Details) · cancelled · blocked publication (e.g., currency unknown: "Can't record this: the document doesn't state a currency. Set a home currency in Settings or verify manually.", which maps the existing `publication.reason`) · historical version (a banner: "You're viewing an earlier version captured Sep 2").

### 3.9 Processing

**User question:** "Is Home Manager working, stuck, or broken, and why is it slow?"
**Primary action:** Cancel the running job, or start a batch.

**Sections:**

1. **Pipeline status:** five stage lanes (Capture, Transcription, Extraction, Normalization, Reconciliation). Each shows its idle, queued (N), or running state with the current item, stage, elapsed time, and Cancel where supported (inference only; the existing API says capture isn't interruptible, and the UI says so).
2. **Actions:** Scan Inbox · Scan source folders · Process unread documents (the existing receipt batch, with the "include already-read" option) · Reconcile now.
3. **Recent jobs:** a table of jobs: type, started, duration, result (succeeded, partial, failed, cancelled, interrupted), and counts. A row opens the job drawer with scan events (path, result, message), which are today's events table.
4. **Model runs:** the existing telemetry table (model, task, status, prompt tokens, completion tokens, TTFT, generation tok/s, model time) plus workflow time, with `~` marking estimates. Filter by task and status.

**Backend:**

- Normalization and reconciliation don't run as job records. Normalization is inline in extraction, and reconciliation is synchronous. The lanes for those stages show "Runs as part of extraction" and "Last run: <time>, result" (needs a last-reconciliation record, B10) rather than fake queue state.
- There's no unified job history across scans, batches, and runs. Scans (`/api/scans`) and model runs (`/api/model-runs`) exist separately. Phase A shows them as two tables, and B11 is a unified jobs view.

**States:** idle ("Nothing running · Inbox watched every few seconds"), running, a failed job (a user-facing reason; the raw message in the job drawer), and "no model configured" (a lane message linking to Settings → Local models).

### 3.10 Settings

A full page with a left sub-navigation (not a modal). Each section is a narrow 720px form column.

| Section | Contents | Status |
|---|---|---|
| **Library** | Managed library folder, Inbox path (copyable), capture limits | Exists |
| **Sources** | Read-only source folder(s), YYYY/MM legacy notice | Exists (single source); multiple sources is future work |
| **Financial preferences** | Home currency, date display format (UI-only preference), default period | Currency exists; the others are UI-only |
| **Local models** | Vision model, reasoning model: URL, model ID, a "Test connection" button (Backend B12), auto-read new files | Exists except the connection test |
| **Independent checks** | Laya / chat checker, installed state | Exists |
| **Backup & restore** | Planned; shows what will be covered and that it's not yet available | Backend B13 (spec §19) |
| **Privacy & security** | A read-only statement of guarantees: loopback-only, no telemetry, read-only sources, where data lives | Static content, derived from the architecture |
| **Advanced** | Raw endpoint URLs, model identity, schema/app version, database location | Mostly exists in `/api/settings` |

- Changing the managed directory is **consequential** (it switches libraries). It gets a confirmation dialog that explains the effect.
- Saving model settings while the model queue is busy is disabled, with an explanation. This is the existing behavior, made visible.

### 3.11 Assistant (reserved, Phase 9)

Not in navigation until the spec's Phase 9 backend exists. Designed now so the building blocks are shared:

- A **right-side panel** summoned from anywhere (<kbd>Ctrl</kbd>+<kbd>J</kbd>) with the current page as context, rather than a separate chat page. Answers stay next to the records they talk about.
- **Answers are prose plus EvidenceReference chips.** Each claim that uses a figure cites the tool result that produced it ("From transactions · Sep 1–24 · 3 accounts"). Clicking a chip opens the underlying Transactions filter or document in the main view.
- **Authority styling:** assistant text uses the secondary text color and a plain container, never the large figure style used for canonical totals. Figures inside answers come from tool results and are rendered with AmountDisplay, labeled with their source. Missing evidence is stated explicitly ("I couldn't find a posted credit for this refund").
- A "How I got this" disclosure lists the tool calls and arguments.

---

## 4. Design system

### 4.1 Principles in practice

- **Hierarchy through type and space, not boxes.** Panels are separated by a heading and 32px of space. A border appears only where a region needs containment: tables, the drawer, the inspector panes.
- **Color only means something.** The neutral palette carries layout, one accent carries interactivity, and semantic colors carry state. Nothing is colored for decoration.
- **One primary button per view region.**
- **A calm default:** healthy states are quiet (no "Succeeded" badges everywhere), and exceptions stand out.

### 4.2 Tokens (CSS custom properties in `tokens.css`)

**Color: neutrals (cool grey):**

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#F6F7F9` | app background |
| `--surface` | `#FFFFFF` | content regions, tables, drawer |
| `--surface-sunken` | `#EFF1F4` | table header, evidence background, code |
| `--border` | `#E1E4E8` | default dividers |
| `--border-strong` | `#C9CED6` | inputs, focusable outlines |
| `--text` | `#1A1F26` | primary text and amounts |
| `--text-secondary` | `#4D5663` | labels, metadata |
| `--text-muted` | `#6B7480` | tertiary text (≥4.5:1 on surface) |

**Color: accent and semantic:**

| Token | Value | Use |
|---|---|---|
| `--accent` | `#2B5A8A` (ink blue) | primary buttons, links, selected nav, focus |
| `--accent-subtle` | `#E8EFF7` | selected row, nav hover |
| `--positive` | `#1E6B45` | money in, verified |
| `--positive-subtle` | `#E4F2EA` | verified badge background |
| `--warning` | `#8A5A00` | needs review, stale, partial |
| `--warning-subtle` | `#FDF1D8` | |
| `--danger` | `#A33A2E` | failed, past due, destructive |
| `--danger-subtle` | `#FBE9E6` | |
| `--info` | `#2B5A8A` | proposed, running (shares the accent hue) |

**Decision for review:** the accent moves from the current green (`#205641`) to ink blue. Green then means exactly one thing: money in or verified. If the green brand identity matters to you, the alternative is to keep a green brand mark in the sidebar only and still use blue for interaction.

**Money color rule:** money out uses the default text color with a `−` sign. Money in uses `--positive` with a `+` sign. Transfers are muted with the ⇄ icon. **Red never means spending.** Red is for errors, past-due bills, and destructive actions.

**Typography:** system stack `"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif` (Windows-native, no network, and it has tabular figures). Monospace: `"Cascadia Mono", Consolas, ui-monospace`. `font-variant-numeric: tabular-nums` on every amount, date, and count column.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--text-xs` | 12 / 16 | 400–600 | badges, table meta |
| `--text-sm` | 13 / 18 | 400 | table body (compact), secondary |
| `--text-md` | 14 / 20 | 400 | body default |
| `--text-lg` | 16 / 24 | 600 | panel headings |
| `--text-xl` | 20 / 28 | 600 | page titles |
| `--figure-lg` | 28 / 34 | 600 | the one headline figure per page |

That's six sizes, and the scale is enforced.

**Spacing (4px base):** `--space-1..8` = 4, 8, 12, 16, 20, 24, 32, 48.
**Radii:** `--radius-sm` 4px (inputs, buttons, badges), `--radius-md` 6px (panels, drawer, popovers), `--radius-lg` 10px (dialogs). There are no pill shapes except count badges.
**Elevation:** none on in-flow content. `--shadow-overlay` (one soft shadow) only for the drawer, popovers, menus, and dialogs.
**Control heights:** `--control-sm` 28px (in tables, toolbars), `--control-md` 32px (default), `--control-lg` 36px (the page primary action).
**Table density:** row heights of 32px (compact) and 40px (comfortable), cell padding of 12px horizontal. Headers are 12px semibold secondary text and sticky.
**Layout:** sidebar 232px (collapses to a 56px icon rail below 1280px); content max-width 1600px with 24/32px gutters; drawer 520px; form column 720px.
**Motion:** 120ms ease-out for hover and focus, 180ms for drawer slide-in. Everything is disabled under `prefers-reduced-motion`. No decorative animation. The only looping animation is the running-job indicator.

### 4.3 Component inventory

All components are vanilla JS factory functions in a `ui.js` module. They return DOM nodes, which matches the existing `element()`/`cell()` idiom (no framework, no build step, CSP-compatible). Each component has one CSS block, named with a `hm-` prefix.

| Component | Responsibility | Notes |
|---|---|---|
| **AppShell** | sidebar + main + drawer slot + live region | owns routing and the global poll |
| **SidebarNav** | groups, active state, count badges, activity footer | `aria-current="page"` |
| **PageHeader** | title, subtitle/context, primary action, `⋯` overflow | one `<h1>` per page |
| **Toolbar** | search + filters + right-aligned actions, sticky | wraps at narrow widths |
| **SearchField** | debounced input, clear button, <kbd>/</kbd> to focus | |
| **FilterMenu** | single- or multi-select popover with a count in the trigger | keyboard navigable listbox |
| **PeriodPicker** | presets + custom range, month stepping ◀ ▶ | writes to the URL |
| **DataTable** | columns config, sort, selection, density, sticky header, row activation, empty/loading/error slots, "showing N of M" footer | one implementation for every table |
| **AmountDisplay** | renders `{decimal, currency, display}` with sign, direction, tabular alignment, and a currency code or symbol | lexical formatting only (§6) |
| **DateDisplay** | ISO → `Sep 24` / `Sep 24, 2025`, with the ISO date in a `title` | |
| **StatusBadge** | icon + text + semantic tone, from a single status map | never color-only |
| **FigureGroup** | the headline figure with supporting figures and a comparison line | replaces KPI tiles |
| **Panel** | titled section with an optional "View all" link; no card by default | |
| **BarList** | a table row with an inline proportional bar | accessible as a table |
| **ChartContainer / BarChart** | inline SVG, axis labels, an accessible data table fallback | no library |
| **Drawer** | non-modal side panel, focus management, <kbd>Esc</kbd>, deep-linkable | |
| **Dialog** | native `<dialog>` wrapper: title, body, footer actions, destructive variant | used only for confirmations and the import flow |
| **ConfirmDialog** | states the consequence, has a danger-styled confirm, and focuses Cancel first | |
| **Menu** | the `⋯` overflow: a button + `role="menu"`, closes on outside click or <kbd>Esc</kbd> | replaces `<details class="row-menu">` |
| **ReviewItem** | what / why / evidence / decision layout | used in the Review page and the drawer |
| **EvidenceReference** | a chip linking to a document, page, line, or record, with a hover preview | shared with the Assistant |
| **ProvenanceDisclosure** | a collapsed technical details list (hash, paths, versions, model identity), with copy buttons | |
| **ProcessStepper** | Read → Recorded → Linked, each with a state | used in the inspector footer and Processing |
| **ActivityIndicator** | running-job summary + Cancel | sidebar footer |
| **Alert** | inline, per-region: info, warning, error, with an optional action and technical detail | |
| **Toast** | transient confirmation with an optional Undo, `aria-live="polite"` | replaces the global `#notice` line |
| **EmptyState** | message + optional action, sized to the region | |
| **Skeleton** | row and figure placeholders at their final size | |
| **Icon** | an SVG sprite vendored at `static/icons.svg` (a Lucide subset, ISC license) | no emoji |

### 4.4 Status vocabulary (one map, used everywhere)

| Internal | Label | Tone | Icon |
|---|---|---|---|
| `proposed` | Proposed | info | circle-dashed |
| `needs_review` | Needs review | warning | alert-triangle |
| `verified` | Verified | positive | check-circle |
| `rejected` | Rejected | neutral (struck through) | x-circle |
| `queued` | Queued | neutral | clock |
| `running` | Processing | info (animated) | loader |
| `succeeded` | Done (usually hidden) | positive | check |
| `partial` | Partly done | warning | circle-half |
| `failed` | Failed | danger | alert-octagon |
| `interrupted` | Interrupted | warning | pause-circle |
| `cancelled` | Cancelled | neutral | slash-circle |
| `cancel_requested` | Cancelling… | neutral | loader |
| `imported` | Imported | positive | check |
| `payment_found` / `due` / `past_due_no_payment_found` | Paid (found) / Due / Past due · no payment found | positive / neutral / danger | |
| `evidence_only_not_settled` | Refund not yet posted | warning | |

### 4.5 Errors, in user language

`api()` gains an error mapper. The HTTP status and a known-message table map to a user-facing sentence, with the server's `detail` kept in a "Technical details" disclosure. Examples:

- **401:** "This session has expired. Reopen Home Manager from its launcher."
- **Model endpoint unreachable:** "The local model server isn't responding at 127.0.0.1:1234. Start it in LM Studio, then retry."
- **Validation error:** field-level messages next to the input, not a JSON dump.

The server already avoids document content in errors. The UI never adds it back.

---

## 5. Accessibility

- **Landmarks:** `nav` (sidebar), `main`, `aside` (drawer), one `h1` per page, `h2` for each panel.
- **Keyboard:**
  - Every control is reachable, and the tab order follows the visual order.
  - Tables are navigable with arrows when focused (roving tabindex), and <kbd>Enter</kbd> opens the row.
  - The drawer traps nothing because it's non-modal. <kbd>F6</kbd> cycles between the sidebar, main, and drawer regions.
  - Dialogs use native `<dialog>` with an initial focus and return focus to the trigger on close.
- **Shortcuts** are listed in a <kbd>?</kbd> help overlay, never required, and never fire inside inputs.
- **Focus:** a 2px `--accent` outline plus a 2px offset on every interactive element, visible against every surface.
- **Contrast:** all text tokens ≥4.5:1 on `--surface` and `--canvas`; badges ≥4.5:1 text on subtle backgrounds; and the non-text UI (borders of inputs, focus) ≥3:1.
- **State never relies on color alone:** every status has an icon and text; amounts have a `+`/`−` sign, and inflow and outflow are also announced ("money in 1,200.00 US dollars").
- **Live regions:** one polite region in AppShell for toasts and job completion. Running-job progress updates are throttled (announced at start and finish, not every second).
- **Tables:** `<th scope>` and `aria-sort` on sortable headers; charts carry a visually hidden data table.
- **Zoom:** usable at 200% zoom on 1440px, where the sidebar collapses to the icon rail.

---

## 6. Money presentation

The rule stays: **the browser does no money arithmetic.** It never sums, subtracts, converts, or rounds. Totals come only from server tools.

Presentation, though, needs more than the current `display` string (`-1,234.56 USD`). Two options:

- **A, backend (not chosen):** the `money()` helper and `format_minor` add a `parts` object: `{sign: "-", magnitude: "1,234.56", currency: "USD", symbol: "$"}`. The UI composes `−$1,234.56` or `−1,234.56 USD` without parsing. This is a tiny, additive, deterministic change in `money.py` (B14).
- **B, UI-only (chosen):** AmountDisplay derives the sign from the leading `-` of `decimal` and shows `display` without the sign. That's lexical, not arithmetic, and needs no backend change, but the currency code stays trailing.

**Display rules:**

- Use the currency symbol for the home currency only; every other currency uses its ISO code (`€` is ambiguous across contexts on statements; codes are not).
- Show the minor-unit precision of each currency, which is already correct in `EXPONENTS` (JPY 0, USD 2).
- Right-align amounts with tabular figures, and keep the sign in a fixed-width slot so digits align.
- **Dates:** tables use `Sep 24` (current year) or `Sep 24, 2025`. Detail views use `Sep 24, 2026`. Tooltips and provenance use ISO `2026-09-24`. Relative dates ("2 days ago") only for activity and freshness, never for financial dates.
- **Balances** always carry "as of <date>". Credit-card balances are labeled "Owed".

---

## 7. Backend dependencies — all built 2026-09-24

Every dependency below is implemented (migration 015, `tests/test_backend_dependencies.py`). The UI for Phases C–D can use them directly.

| ID | Needed for | Built as |
|---|---|---|
| B1 | Review | `review_queue` items carry a `summary` (name, date, amount, account, document) per record; links carry `from`/`to` summaries and `match_signals`; issues carry the `record` and every `candidates` summary. One batched lookup per record type (`Ledger.summaries`). |
| B2 | Transactions | `get_transactions` takes `category` (or `uncategorized`), `transaction_types`, `statuses` (`counted`/`pending`/`rejected`), `has_receipt`, `sort`, `offset`. Filtering, counting and paging run in SQL; word search compares merchant keys through a registered SQLite function, over the description and the linked merchant. Rows include `merchant` and `receipt_id`. |
| B3 | Transaction drawer, inspector "Linked" | `GET /api/finance/records/{transaction\|receipt}/{id}` includes `account` and `links` (kind, status, signals and the counterpart's summary). |
| B4 | Spending trend | `spending_series` tool: up to 36 months in one grouped query, empty months listed, pending review per month. |
| B5 | Category change | `compare_categories` tool: per currency and category, both periods, exact change and percentage. `get_spending`, `compare_periods`, `calculate_cashflow` and the series share one totals query. |
| B6 | Bills & recurring | `POST /api/finance/bills/{id}/payment` (paid/unpaid/unknown, optional paying transaction, validated); the user's state takes precedence in `get_upcoming_bills` (`payment_source`). `POST /api/finance/recurring/{id}/review` (verified/rejected/ended). Both audited in `review_events`. |
| ~~B7~~ | Overview cash figure | Dropped: per-account balances only (§10). |
| B8 | Documents | Done in Phase B. |
| B9 | Documents | Library rows carry `reconciliation_status` (receipt: matched/proposed/ambiguous/unmatched; bill: its payment state) and `unfiled_reason`, which now names exactly what was not confirmed (type, merchant or date). |
| B10 | Processing | Every reconciliation pass is a `reconciliation_runs` row (trigger, status, counts, timing); `GET /api/finance/reconciliation-runs`. |
| B11 | Processing | `GET /api/jobs[?kind=…]`: scans, Inbox captures, reading batches, single readings, extractions, audits, reconciliations, backups and assistant questions in one `UNION ALL` query. |
| B12 | Settings | `POST /api/model-connection-tests`: loopback-validated, `GET /v1/models` only (nothing loaded, no content sent); reports reachability, whether the model is listed, and the served models. |
| B13 | Settings | `POST /api/backups` writes to a separate folder (SQLite backup API snapshot, hash-verified originals, Library files, previews, manifest with SHA-256 per file; staged, renamed only when complete; cancellable). `POST /api/restores` verifies everything (manifest confinement, hashes, `integrity_check`, schema version), then builds a new library in an empty folder; the open library is never touched. |
| ~~B14~~ | Amounts | Dropped: the UI splits `display` lexically (§10). |
| B15 | Review | `POST /api/finance/issues/{id}/resolve` with a candidate (a verified link scored by the same rules, marked `user_choice`) or `null` (left unmatched; later passes respect it). Audited. |
| B16 | Assistant | `POST /api/assistant-runs` / `GET /api/assistant-runs[/{id}]`: the reasoning model calls only the read-only tools (at most six calls, bounded results), and every money figure in the answer is checked against the results it cites; unsupported figures are listed as `unverified_figures`. |

---|---|---|---|
| B1 | Review | `review_queue` items lack display summaries (merchant, amount, date, account, document) for records and both sides of links | S: read-only join |
| B2 | Transactions | `get_transactions` filters for category, type, review state, and has-receipt; sort order; offset pagination | S–M |
| B3 | Transaction drawer, inspector "Linked" | transaction evidence + receipt/transfer/refund links in the record endpoint | S |
| B4 | Spending trend | a monthly `spending_series` tool (the fallback is N `get_spending` calls) | S |
| B5 | Category change vs. the prior period | a server-side category comparison | S |
| B6 | Bills & recurring | a manual bill payment state; review for recurring obligations | S |
| ~~B7~~ | Overview cash figure | dropped: per-account balances only (§10) | — |
| B8 | Documents | document date, document type, and sort options in the library query | M |
| B9 | Documents | reconciliation state and an Unfiled reason per document (spec §20) | M |
| B10 | Processing | a last-reconciliation record (time, counts) | S |
| B11 | Processing | a unified job history (scans + batches + runs) | M |
| B12 | Settings | "Test connection" for model endpoints (loopback-validated) | S |
| B13 | Settings | backup and restore (spec §19) | L |
| ~~B14~~ | Amounts | dropped: UI splits `display` lexically (§10) | — |
| B15 | Review | a resolve-issue endpoint (choose one of the ambiguous candidates) | S |
| B16 | Assistant | the whole Phase 9 agent | L (deferred by spec) |
| — | Documents type/date filter, cross-entity search | combined search across documents and transactions (the UI can call both existing endpoints) | none for v1 |

---

## 8. From the document app to Home Manager: evolution

The existing document interface isn't discarded. It becomes one module of the shell:

1. **The Documents tab becomes the Documents page.** Same folder rail, same filters (renamed), same row actions (reorganized), same Move/Trash/Restore dialogs, and same import dialog.
2. **The inspector dialog becomes the inspector route.** The evidence overlay, text highlighting, ledger record, Verify/Reject, audit, history, and Laya panel are all kept. Their placement is re-weighted: the record is primary, and process, audit, and provenance are secondary.
3. **The Finances tab splits into Overview, Spending, Bills & recurring, Accounts, Transactions, and Review.** Every figure keeps coming from the same tools.
4. **Scans & activity becomes Processing.** The header activity pill becomes the sidebar ActivityIndicator.
5. **The Settings modal becomes the Settings page.**
6. **The header count chips** become sidebar badges (Review, and Inbox/Unfiled under Documents).

---

## 9. Phased implementation plan

Each phase ships a working app. At every phase the opt-in browser test (`RUN_BROWSER_TESTS=1`) is updated in the same change, because it checks many element IDs. Targeted tests run for touched areas.

### Phase A: foundation and shell (no behavior change) — done 2026-09-24

Implemented as `static/ui.js` (primitives), `static/shell.js` (hash router, sidebar) and a token-based `style.css`. Pages mount at `#/documents` (default until Overview exists), `#/finances`, `#/processing` and `#/settings`. Beyond the list below: identical poll results no longer re-render the document table (open menus and focus survive), overflow menus are fixed-positioned so scrolling tables can't clip them, the sidebar collapses to an icon rail below 1280px, and changing the managed library folder asks for confirmation.

- `tokens.css` + a rewritten `style.css` on the tokens. This removes the two-generation override layering.
- `ui.js` primitives: Button variants, StatusBadge + the status map, AmountDisplay (option B), DateDisplay, Panel, EmptyState, Skeleton, Alert, Toast, Menu, Dialog/ConfirmDialog, Icon sprite.
- AppShell + SidebarNav + hash router + ActivityIndicator. Existing panels mount as routes: Documents, Finances (temporarily one page), Processing (the old Scans & activity), Settings (moved from the modal to a page).
- The error mapper in `api()`, and Toast replacing `#notice`.
- **Acceptance:** every workflow W1–W14 still works, the browser test passes with updated selectors, and there are no backend changes.

### Phase B: Documents and inspector — done 2026-09-24

- Documents: DataTable, the single state badge, the `⋯` Menu, row selection with batch actions, and user-language filters. Batch processing moves to Processing.
- Inspector as a route: fixed title, split panes, the record-first right pane, the ProcessStepper footer, Details/History/Audit tabs, ProvenanceDisclosure replacing the JSON `<pre>`, and PDF page navigation.
- Backend (optional within this phase): B8 date/type/sort.

Implemented notes:
- **Backend B8 (done):** the library query returns `document_date` (purchase date, statement period end, bill due/issue date or pay date), and `/api/documents` takes `sort` (`date`, `name`, `added`, `path`) plus `date_from`/`date_to`. `GET /api/documents/{id}` returns one row for deep links. `POST /api/receipt-batches` accepts `document_ids` for **Read selected**. The Type column is the folder, which is already the document type.
- **Inspector route:** `#/documents/ID[?version=HASH]` works from a reload. Back (or <kbd>Esc</kbd>) returns to the list with its filters, page and scroll position. The title is set once on open; a ledger record's name appears on the next open.
- **Linked step:** the stepper shows Read, Recorded and the optional Audit. "Linked" waits for B3 (transaction links on the record endpoint) in Phase C.
- **Reverse lookup:** selecting a region on the image highlights the recorded rows that cite it. Summary fields (merchant, total) carry no per-field citations yet, so only item and transaction rows are highlighted.
- **Decisions are undoable:** a verified or rejected record offers "Undo verification/rejection", which returns it to Needs review.
- **Robustness:** table updates wait while a row menu is open, and menus follow their trigger when a container scrolls.
- **Still open:** B9 (per-document reconciliation state and an Unfiled reason) is not in the library query yet.

### Phase C: Money screens

- Transactions page with DataTable, filters (client-side over ≤1000 rows until B2), and the drawer (evidence "unavailable" until B3).
- Spending, Bills & recurring, and Accounts pages built from the existing tools. The trend chart uses N `get_spending` calls until B4.
- Overview built from the same tool calls.
- Global search (documents + transactions).
- Backend: B2, B3, B4 are recommended alongside.

### Phase D: Review workflow

- The Review page with a two-pane queue, keyboard flow, and Undo.
- Requires B1 (summaries) to meet the "no internal IDs" rule. Without B1, Phase D should wait rather than ship an ID-based queue. B15 for ambiguous matches.

### Phase E: Processing and Settings depth

- Pipeline lanes, the unified job history (B11), the last reconcile (B10), and the model-run filters.
- Settings sections: Test connection (B12), a Privacy statement, and a Backup placeholder until B13.

### Phase F (after spec Phase 9)

- The Assistant panel, built on the EvidenceReference, AmountDisplay, and Drawer primitives.

**Out of scope for all phases:** dark mode (the tokens make it cheap later), a mobile layout beyond "usable at narrow widths", charts beyond bars and bar lists, and multiple source folders.

---

## 10. Decisions (reviewed 2026-09-24)

1. **Accent color:** interaction color moves from green to ink blue; green means only money in or verified.
2. **Money parts:** no backend change. AmountDisplay uses option B (§6): it splits the server's `display` text lexically, with no arithmetic. B14 is dropped.
3. **Review page:** Phase D waits for B1 (display summaries in `review_queue`). No ID-based interim queue.
4. **Overview cash:** per-account balances with "as of" dates only. No cross-account total; B7 is dropped.
5. **Accounts:** stays a top-level page.
6. **Phase order:** A → B → C → D → E → F as written.
