# Inventory (Phase 2)

These are the page overrides for Inventory v2 (`inventory_v2.js`, route `#/inventory`). MASTER.md wins wherever this
file says nothing. The hand-off is `../phase2-system-plan.md` Build A.

**The user's jobs** (docs/household.md "The Inventory page"): answer the weekly check-in, see what's in the house, keep
warranties and return windows straight, answer "did this go back?", and see what items cost over time (Item insights).

Shared: figure tiles, the tinted region (`.today-region`, never nested; lists inside use 1px dividers), needs-attention
rows (`.needs-row.attention`, `--warning-subtle`, one text-link action), tables (sticky sunken header, 40px rows,
right-aligned amounts), 30px chips (pressed = `--accent-subtle` with an `--accent` border), status badges, one primary
per region. Thrown-out money is `--text` with `−`, never red. A price rise is text with ↑ under a "Went up by" heading,
never red.

## Inventory (built 2026-10-11, Build A)
- **Components:**
  - Header: h1, muted subline, one primary action that follows the tab: **+ Warranty** on Warranties (a picker of
    in-stock items that last, `dialog#it2-warranty-pick`, then the shared `#warranty-dialog`), **+ Return policy**
    elsewhere (`dialog#it2-policy-dialog`; field errors under their field).
  - Tabs (`wireTabs`): Check-in · Items · Warranties · Returns · Item insights. Check-in and Returns carry a count pill
    (`.nav-count.attention`) that is part of the accessible name ("Check-in, 2 waiting", "Returns, 1 to answer"). Each
    tab draws on first show, with its own loading line and an `alertBox` with Retry on error.
  - **Check-in:** `renderCheckin` (full) in a tinted region, then the free-text form and its reading
    (`submitCheckinText`, `renderReading` into `#it2-checkin-reading`).
  - **Items:** search and "Show finished and thrown out"; **To identify** (tinted region, only when receipts wait: one
    row per receipt with Identify items and Open); one table with a `tr.group-row` per category (`categoryLabel`, count)
    and columns Item, Bought, Status, Returnable / warranty (shield-check icon per warranty), Next question, and the
    row menu (`lotMenu`).
  - **Warranties:** an attention row when warranties found online wait in To check; then a table of confirmed ones:
    Item (+ store), Kind, Ends ("Lifetime" or the date), Source ("You added" or "Found online" + the page's title as
    text, never a link; the note), Status (`warranty_active` "In force", `warranty_ending` "Ends within 30 days" from
    `/api/warranties/expiring?days=30`, `ended`), and a menu with Remove (confirm, focus Cancel).
  - **Returns:** three tinted regions: **Did this go back?** (first, only when there are proposals; `returnedRow` with
    the undo-2 icon as attention rows), **Return windows closing** (14 days, dated list with `returnText`), **Return
    policies** (table; each row's menu has Change, which pre-fills the dialog, and Remove, which confirms).
  - **Item insights:** period chips (30 days · 90 days · 12 months · This year); four figure tiles (Spent on items,
    Cost per 30 days, Thrown out, Next month's consumables), each an `items.*` traced `figure()` opening `#breakdown`;
    then **Prices that went up** and **Costs most** side by side at ≥1180px; **Thrown out** as a dated list; the
    server's notes as a muted footnote list.
- **Layout:** 1440: tiles in four equal columns; the two tables side by side. Under 820px tiles go two a row. Under
  700px the Items table folds Bought and Next question into the item cell's second line, the Warranties table drops
  Kind and Source, and needs rows put their actions under the text. Under 560px the Returnable / warranty column folds
  into the item cell as well, so the row menu stays on screen, and tile figures drop to `--text-lg`. Tabs scroll inside
  `.tabs`; tables scroll inside `.table-wrap`.
- **URL:** `#/inventory?tab=checkin|items|warranties|returns|insights&q=…&closed=1&period=30|90|365|year`. Items is the
  default; `q` forces Items. Only non-default values, and only the shown tab's own controls, are written.
- **States:** no items: "No items yet. Items appear when you approve receipt lines." with a link to To check; a search
  with no match: "Nothing matches that search."; each tab has its own empty state; Cost per 30 days with no finished
  items says "Mark items finished in the check-in to see cost per day."; a reading that is queued or running disables
  Read my answer.

### Decided
- The insights endpoint takes `period=30|90|365|year` (default 90) as well as `start`/`end`, so the browser never
  works out dates. Without a currency it chooses as Home does (`choose_currency`: the home currency if items cost in
  it, else USD).
- The insights notes are the tools' notes for people, not the ones that explain a field to the assistant.
- Seeding (`tests/seed_items.py`): the closing return window is a drill at Hardware Depot with a 14-day policy of the
  user's (Walmart's typical 90 days never closes within 14); the Acme toaster's user warranty is the **extended** kind,
  so the manufacturer's warranty found online stays in To check for the review screen.
- `returnedRow(proposal, className)` was pulled out of v1's `renderReturned` so v2 reuses its buttons (the plan's A2
  list didn't name it).
- Parity: the pair is `("inventory?tab=insights", "inventory")` with `items.` in `NEW_ON_V2` (v1 showed no figures);
  the harness turns on the route before the "?".
