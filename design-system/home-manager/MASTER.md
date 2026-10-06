# Home Manager design system (MASTER)

Approved in Phase 0 on 2026-10-06: direction **C · Family**, chosen from three directions shown as browser pages
(A · Ledger, B · Household book, C · Family). This file holds the visual decisions. `docs/ui.md` "Screen rules" win over it,
and page files in `pages/<page>.md` may refine it for one screen but never contradict it.

**Feel.** Friendly and calm, for family members who aren't finance-minded, but still dense where the data needs it. Use
tinted surfaces and soft corners instead of hairline ledgers, one cobalt accent for anything interactive, and quiet
healthy states. Stripe's ledger is the reference for table discipline, and Copilot Money for "how it's worked out" on
every figure.

**Pro Max input.** The query "friendly family home finance app, approachable budgets with insight into each figure"
(density 6, variance 4, motion 3) gave Plus Jakarta Sans and a trust-blue accent. These were dropped: glassmorphism
(blur hurts contrast and breaks "no shadows in the page flow"), the orange call-to-action color (orange reads as
warning here), hero and CTA page patterns, and scroll-reveal motion.

## Color tokens

Every color is a `:root` custom property in `style.css`. Dark redefines the same names under `[data-theme=dark]` and
`prefers-color-scheme: dark`. No hex values appear outside those blocks.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--canvas` | `#F7F6F3` | `#12141A` | app background (warm off-white) |
| `--surface` | `#FFFFFF` | `#191C24` | sidebar, tables, panels, tinted regions |
| `--surface-sunken` | `#F0EEE9` | `#20242E` | table header, hover, source text, code |
| `--border` | `#E6E3DC` | `#2B303C` | dividers, region outlines |
| `--border-strong` | `#CDC8BE` | `#3D4452` | inputs, secondary buttons |
| `--text` | `#1F2430` | `#E9ECF2` | primary text and amounts |
| `--text-secondary` | `#4F5767` | `#B0B7C4` | labels, metadata |
| `--text-muted` | `#636B7B` | `#8D95A3` | tertiary text |
| `--accent` | `#1D5BD8` | `#7FA6FF` | primary buttons, links, selected nav, focus ring |
| `--accent-hover` | `#174BB5` | `#9BB9FF` | primary button hover |
| `--accent-subtle` | `#E7EEFC` | `#1B2742` | selected row, pressed chip |
| `--on-accent` | `#FFFFFF` | `#12141A` | text on `--accent` |
| `--positive` | `#157A4A` | `#5CCB8F` | money in, verified |
| `--positive-subtle` | `#E3F4EA` | `#14281D` | |
| `--warning` | `#8C5900` | `#E8B04A` | needs review, stale, budget ahead of pace or over |
| `--warning-subtle` | `#FCF0D6` | `#2E2413` | needs-attention rows, unconfirmed inputs |
| `--danger` | `#B42318` | `#F2836F` | errors, past due, destructive |
| `--danger-subtle` | `#FCE8E6` | `#33191A` | |
| `--chart` | `#3B6FDB` | `#6F96F0` | single-series bars, share and budget meter fill |
| `--chart-track` | `#E4EBFA` | `#26324D` | meter track |

`--info` is `--accent`. Categorical chart colors stay the validated palette in `home.js` `CHART_COLORS` and
`finance/charts.py`, moved into tokens in Phase 1.

**Checked contrast** (WCAG; text ≥ 4.5:1, meter fill against track ≥ 3:1):
- Light: text/canvas 14.4; secondary/surface 7.3; muted/canvas 5.0; muted/sunken 4.6; accent/surface 5.9;
  on-accent/accent 5.9; accent/accent-subtle 5.1; positive/surface 5.4; positive/positive-subtle 4.7;
  warning/warning-subtle 5.2; danger/danger-subtle 5.6; chart/track 3.9; warning/track 5.0.
- Dark: text/canvas 15.6; muted/surface 5.7; muted/sunken 5.1; accent/surface 7.1; on-accent/accent 7.7;
  positive/surface 8.4; warning/warning-subtle 7.8; danger/danger-subtle 6.4; chart/track 4.4; warning/track 6.5.

**Meaning is fixed** (docs/ui.md "Conventions"):
- Accent means interactive.
- Green means money in or verified.
- Amber means it needs you: review, stale, or a budget ahead of pace or over.
- Red means an error, past due or destructive. **Red never marks spending, including an exceeded budget** (decided
  2026-10-06).

## Typography

- **UI and figures:** Plus Jakarta Sans 400/500/600/700, self-hosted woff2 in `app/static/fonts/` (SIL OFL 1.1;
  keep the license file next to it).
- **Mono:** JetBrains Mono 400/500 (OFL), for rule versions, source lines and file/row references.
- **Fallbacks:** `"Plus Jakarta Sans", "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif` and
  `"JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace`.
- Every amount, date and count uses `font-variant-numeric: tabular-nums`.

| Token | Size / line | Weight | Tracking | Use |
|---|---|---|---|---|
| `--text-xs` | 12 / 16 | 500–600 | 0 | badges, meta, uppercase kickers (+0.05em) |
| `--text-sm` | 13 / 18 | 400–550 | 0 | table body, secondary |
| `--text-md` | 14 / 20 | 400 | 0 | body default, nav |
| `--text-lg` | 15 / 22 | 600 | 0 | section headings (h2/h3) |
| `--text-xl` | 26 / 32 | 700 | −0.02em | page title (h1) |
| `--figure-lg` | 28 / 34 | 700 | −0.02em | headline figures |
| `--figure-xl` | 30 / 34 | 700 | −0.02em | the answer at the top of a breakdown |

## Space, shape, density

- **Spacing:** 4px base, `--space-1..8` = 4, 8, 12, 16, 20, 24, 32, 48. Sections are 32px apart; a heading is 12px
  above its content.
- **Radii:** `--radius-sm` 6px (buttons, inputs, badges' inner shapes), `--radius-md` 10px (attention rows, nav items,
  table wrap, input rows), `--radius-lg` 14px (figure tiles, tinted regions, dialogs). Pills (999px) are used only for
  chips, status badges and count badges.
- **Density** is balanced. Table rows are 40px by default with an optional compact 32px, and headers are 32px. Controls
  are 28 / 32 / 36px (sm / md / the page's primary action).
- **Elevation:** nothing in the page flow has a shadow. Regions are set apart by a `--surface` fill on `--canvas` and a
  1px `--border`. `--shadow-overlay` is for the drawer, popovers, menus and dialogs only.
- **Motion:** 120ms ease-out for hover and focus, 180ms for panels and the drawer, no scroll reveal. All of it turns off
  under `prefers-reduced-motion`. The running-job spinner is the only loop.

## Layout

- **Sidebar:** 220px on `--surface` with a right `--border`, collapsing to an icon rail below 1280px and to a top bar
  below 820px. Groups follow docs/ui.md "Redesigned navigation". Group labels are 12px semibold muted, sentence case.
  The selected item is a filled `--accent` pill with `--on-accent` text and 600 weight. Hover is `--surface-sunken`.
  The count badge is a warning pill.
- **Page:** `--canvas` background with 28px/32px padding (16px under 820px). The header has an h1, a muted subline,
  and actions on the right, with one primary button.
- **Breakdown and detail panel:** 360px on the right at 1180px and wider, `--surface`, with a left `--border`. Under
  1180px it moves below the content; under 900px it's a bottom sheet (docs/ui.md "Observability components").

## Components

- **Tinted region:** a `--surface` block with a 1px `--border` and `--radius-lg`, padding 16/18. Use it for figure
  tiles and grouped home sections. It never nests, and plain lists inside it use 1px dividers rather than more boxes.
- **Needs-attention row:** `--radius-md`, padding 12/14, `--surface` fill, or `--warning-subtle` when it needs you. A
  20px icon in its tone, a semibold *what*, a muted *why*, and one text link action on the right. Rows are 6px apart.
- **Figure tile:** a label (12.5px, secondary), the figure as a `figure()` button (`--figure-lg`), and a subline
  (12.5px muted with an optional flag such as "⚠ 1 unconfirmed"). When its breakdown is open, the tile gets an
  `--accent` 1px border plus a 1px ring. Money in is `--positive` with `+`; money out is `--text` with `−`.
- **Buttons:** primary is `--accent` fill with `--on-accent` text. Secondary is `--surface` with a `--border-strong`
  outline. A text link is `--accent` 550 weight and underlines on hover. The focus ring is a 2px `--accent` outline
  with a 2px offset.
- **Chips (filters):** pill-shaped and 30px high with a `--border` outline. Pressed is `--accent-subtle` fill with an
  `--accent` border and text.
- **Status badge:** a pill with icon + text, on `--{tone}-subtle` fill with `--{tone}` text, through `statusBadge()`.
  Verified rows show no badge.
- **Table:** in `.table-wrap` (`--surface`, `--border`, `--radius-md`). The header is sticky, `--surface-sunken`, 12px
  semibold secondary. Rows have 1px `--border` dividers, hover is `--surface-sunken`, and selected is
  `--accent-subtle`. Amounts are right-aligned with a fixed sign slot, and transfers are muted with ⇄. Extra categories
  show as "+ Household" in muted text.
- **Share bar:** 6px high, 3px radius, `--chart` on `--chart-track`. The width comes from a server percent
  (`share_bp`, `meter_percent`) as a class or `data-` value styled by CSS, never an inline `style` (CSP).
- **Budget meter** (decided 2026-10-06): the same bar, 8px high, with "$spent of $budget" above it and the remaining
  amount or state on the right.
  - `on_track`: `--chart` fill.
  - `ahead` (spent a larger share than the share of the month gone): `--warning` fill, with "Ahead of pace".
  - `over`: the bar is full, `--warning` fill, ⚠ icon and "Over by $12". **Not red.**
  - All values come from the server: `meter_percent`, `remaining_state` and `over`.
- **Breakdown panel** (`breakdownPanel()`): an uppercase kicker ("How it's worked out"), the title, the answer
  (`--figure-xl`), and the formula in plain words. Next comes a steps table (label, amount, running), where each line
  carries a share bar when the server sends shares. Its footer reads "✓ Sums to …". Inputs come next, unconfirmed
  first, as input rows: `--radius-md` with a `--border` outline, or a `--warning` outline on `--warning-subtle` when
  unconfirmed, with provenance as icon + text. The rule card closes it, with the version in mono and "Calculated … ·
  inputs unchanged".
- **Source text:** mono 11.5px on `--surface-sunken`, scrolling inside its own box. The highlighted line is
  `--warning-subtle` with a 1px `--warning` outline.

## Decided for later screens (record here, build in Phase 2)

These came from the Phase 0 review on 2026-10-06. Their screen sessions plan the layout, and the styling is above.
- **Today: budgets with "how it's worked out".** Today shows budgets in the breakdown style, as category lines with a
  budget meter instead of a running total. It uses `get_budgets` (spent, remaining, percent, pace).
- **Today: money across all accounts, as two figures.** **Cash** and **Net worth** sit side by side, each opening its
  breakdown (`worth.today` with `figure=cash` and `figure=net_worth`). Cash lists every account's latest statement
  balance with its date. The figure's subline shows the date range ("as of Jun 30 – Sep 30"). Accounts older than 35
  days carry the stale icon + text in the breakdown, and any stale account adds "Some balances are old" under the
  figure. This reverses docs/ui.md "Decisions" 4 ("no total across accounts") for Today.
- Everything else on the Phase 0 Today mock-up (the October figures, the weekly chart, Coming up) was a placeholder for
  the visual language, not a layout decision.
