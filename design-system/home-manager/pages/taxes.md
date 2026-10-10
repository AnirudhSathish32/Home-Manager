# Taxes (Phase 2)

Page overrides for Taxes v2 (`src/home_manager/app/static/taxes_v2.js`). MASTER.md wins where this says nothing; the
hand-off is `../phase2-taxes-plan.md`.

**The user's job:** see where the tax year ends (refund or owed), why, and what to change (usually the W-4); then fix
or add what the estimate is built from.

## Components (from MASTER "Components")
- **Figure tile:** label 12px secondary, `figure()` at `--figure-lg`, subline muted. Accent border and ring when its
  figure's breakdown is open (`.figure-tile`).
- **Tinted region:** `--surface`, `--border`, `--radius-lg`, never nested. Used once, for "What to do" (`.panel`).
- **Table:** `.table-wrap` and `.data-table`, sticky header, amounts right-aligned with tabular figures. The return's
  row labels are body text (not the sunken header style); group rows keep the sunken header style; totals are 600.
- **Status badge:** through `statusBadge()` (`ZEN_BADGES`).
- **Chips:** not used.

## Layout (from MASTER "Layout")
- Page header: h1, the muted subline, and the year select (plus "Return" in the family view) on the right.
- Six `.tabs` under the header; under 600px they scroll inside themselves.
- The breakdown panel is 360px beside the page from 1180px (the Phase 1b deviation stands).
- **This year:** three tiles (`repeat(auto-fit, minmax(200px, 1fr))`), the meta line, "What to do", then "The return,
  line by line" and "About these numbers". "What to do" is in view at 1366×768. Under 600px the second and third
  tiles become one line each.
- **Built from:** a 200px sticky section list (the `.settings-nav` look) beside rows `minmax(0,1fr) 150px 160px`
  (Box · From records · Yours); under 900px the list becomes `select#taxes2-section`; under 800px each row is Box
  above records and Yours; under 600px one column. A sticky save bar ends the tab.
- **Jobs & pay stubs:** one tinted region per job: header line, two columns ≥ 900px ("This year" figures; "W-4 on
  file"), then the pay-stub table. The same save bar.

## Meaning (from MASTER "Meaning is fixed")
- Owed is not red: text color, unsigned, with the words "You'd owe".
- Refund is `--positive` with `+` and the word "Refund".
- "Change recommended" is amber through `tax_action`.
- "Not CPA-reviewed" is neutral text in the rule card.

## Pro Max input
`search.py "personal tax return estimate dashboard…" --density 8` returned "Data-Dense Dashboard" plus marketing
patterns (Enterprise Gateway, hero, Fira fonts, a blue and amber palette). Kept: the density and row-hover table
discipline. Dropped: the pattern, palette and fonts (MASTER wins).

## Deviations from MASTER
None. No new tokens.
