# Home screen design

Status: Implemented September 25, 2026. Home is the default landing page, with monthly totals, spending bars, a category donut, attention links, bills, currency selection and accessible data tables. It extends the existing visual system in [UI design plan](ui-design-plan.md). The older [homepage proposal](homepage-proposal.md) concerned the document workspace.

Implementation uses `GET /api/dashboard` to read all panels from one SQLite snapshot. A failed snapshot shows a dashboard-level Retry rather than mixing partially refreshed figures. Finances supports dated, currency-specific category and metric links with transaction pagination. Browser checks cover the default route, category drill-down, six/twelve-month controls, retry and layouts at 390, 768 and 1440 pixels. Spending charts require counted bank/card transactions; unmatched receipts remain separate.

## Purpose

Answer three questions at a glance: How much have we spent, how is spending changing, and what needs attention? Keep a clear path from every total to the records behind it.

Add **Home** above Finances in the sidebar and make `#/home` the default landing page after setup. Documents, Finances, Processing and Settings keep their current roles. Home summarizes; Finances remains the place to inspect transactions and reconcile records.

## Proposed layout

The desktop page uses a wide trend chart beside a narrower category chart. Secondary panels sit beneath them. The wireframe describes structure, not real household figures.

```text
 Home                          [September 2026 v] [USD v]
 Recorded activity through Sep 25       View transactions

 Net spending             Money in                 Net cash flow
 Amount                   Amount                   Signed amount
 vs previous period       Counted inflows           Inflows less outflows

 Spending over time                       Spending by category
 [6 months] [12 months]                   September 2026
 +----------------------------------+    +----------------------+
 |                                  |    |      Donut chart     |
 |       Monthly spending bars      |    |   Category / amount   |
 |                                  |    |   / share legend     |
 +----------------------------------+    +----------------------+
 Current month is partial                Before refunds
 View data table                         View categories

 Needs attention                         Upcoming bills
 Unmatched receipts: count / amount      Provider    Due   Amount
 Records awaiting review: count          Provider    Due   Amount
 Documents ready to record: count        View all bills
 Review records

 Coverage: which accounts and dates are represented
 Totals reflect recorded transactions, not all household spending.
```

Use the current canvas, white surfaces, blue accent, typography and spacing tokens. Keep the header quiet, totals prominent, and chart frames free of decorative borders. Use a one-pixel divider above summary footers, matching the unmatched-receipts section.

## Totals and date controls

| Element | Definition | Interaction |
| --- | --- | --- |
| Net spending | Counted spending less posted refunds in the selected period | Open spending transactions with the same dates and currency |
| Money in | Counted inflows using the existing cash-flow rules | Open the corresponding inflows |
| Net cash flow | Counted inflows less outflows; not an account balance or a savings estimate | Open the cash-flow detail |
| Month | Defaults to the current local calendar month; older months use their full date range | Updates totals, categories and unmatched receipt totals together |
| Currency | Defaults to the home currency when present in the data, otherwise USD if present, otherwise the first available currency | Shows one currency throughout the financial visuals; never combines currencies |

For the current month, totals stop at today. Compare month-to-date with the same number of elapsed days in the preceding month, capped at that month's end. Label the comparison explicitly. For completed months, compare full months. If the previous value is zero or missing, show the two amounts without a percentage.

Do not call increased spending inherently bad or decreased spending inherently good. Use neutral comparison text with a direction indicator. Dates and currency remain visible when following a chart into Finances. Account balances are excluded from the first version because statement balances may be old and are not live available cash.

## Spending over time

Use vertical bars for monthly **net spending**, with a six-month default ending in the selected month and a twelve-month option. Bars make discrete monthly totals easy to compare. Keep a zero baseline; allow negative bars when refunds exceed spending. Show currency on the axis and readable month labels below it.

The current month is marked **Partial month** with a distinct outline or pattern. Its tooltip shows spending, refunds, net spending, and transaction count. Each bar opens that month's transactions. Do not draw an empty month as zero spending: show a gap and “No recorded transactions.” Where a period has transactions but nets to zero, show an explicit zero marker.

Do not project the rest of the month in the first version. Forecasting would need a separate definition and evidence of data completeness. A later daily or weekly view would require a new server aggregation; the existing series is monthly.

## Spending by category

Use a donut chart, a pie-chart variant with space for **Spending before refunds** and its amount in the center. Category amounts represent gross counted spending, so the donut reconciles to gross spending rather than the net-spending headline. Show refunds separately in nearby text to explain the difference.

Display the five largest named categories, **Other**, and **Uncategorized** when present. Keep Uncategorized visible rather than burying it inside Other. The adjacent legend lists category name, amount and percentage in descending amount order; omit empty groups. Other opens its underlying categories. Uncategorized opens transactions that need categorization.

Use stable category colors with a neutral gray for Uncategorized. Labels and values must communicate the meaning without color. If there is one category, show one complete ring and its label. If no category spending exists, show an empty-state message instead of an empty ring. A horizontal-bar alternative is a later option if the household prefers comparing categories over viewing shares.

## Attention and upcoming bills

Keep attention visible without making it dominate the page. Show distinct rows for unmatched receipts, financial records awaiting review, and documents ready to record. These counts refer to different work and must not be added into a misleading “total problems” number.

Unmatched receipts show a count and total for the selected month and currency, labeled **Not included in spending**. Receipts without purchase dates appear as a separate count with an action to add dates. A receipt enters spending through its matched transaction, never as an additional purchase. Review and document-work counts are labeled **All dates** if they are not scoped to the month.

Upcoming bills show the next three unpaid or unresolved bills due within 30 days of today, regardless of the selected historical spending month. Label this period directly. Show provider, due date, amount and payment state. Separate overdue bills from upcoming ones; the current upcoming-bills query alone should not be assumed to supply overdue bills. Link to the full bill list. Bills are obligations, not additional spending until a corresponding transaction is counted.

## Data and implementation plan

The current frontend is plain JavaScript with hash routes and shared UI helpers. Implement a `home.js` page module and `home-panel` markup using the existing shell. Use local SVG charts and a visible data-table alternative; do not introduce a remote chart service or send household data elsewhere.

| Surface | Existing source | Work required |
| --- | --- | --- |
| Headline spending and coverage | `get_spending` | Select the displayed currency; retain pending-review and coverage notes |
| Period comparison | `compare_periods` | Supply equal elapsed-day ranges for the current month |
| Monthly trend | `spending_series` | Render the monthly series; constrain the current month's bucket to today if future-dated entries exist |
| Categories | `get_spending_by_category` | Add server-calculated shares and Other grouping; preserve Uncategorized |
| Inflow and cash flow | `calculate_cashflow` | Apply the same dates and currency as the headline |
| Unmatched receipts | `get_unmatched_receipts` | Display its currency totals and separate undated items |
| Review work | `review_queue` and document folder/work counts | Use complete counts; label all-date scope |
| Bills | `get_upcoming_bills` | Query relative to today; add an explicit overdue query if included |
| Chart drill-down | Existing Finances view | Add route/query filters for dates, currency and category, including Other membership |

Financial totals, differences, shares and rounded amounts must come from the server, using existing integer minor-unit arithmetic. The browser may calculate chart positions, but must not recompute money totals from its paginated transaction table. Existing imported/verified eligibility rules remain authoritative. Pending, rejected, duplicate and unmatched records must not silently enter headline totals.

For initial implementation, use the existing read-only tool endpoints. Group requests under one page-load identifier, discard stale responses after filter changes, and refresh after ledger changes. Display a last-loaded timestamp. If separate calls can observe different ledger states, add a read-only dashboard endpoint that gathers its sections within one database snapshot before release.

## Responsive behavior and accessibility

At wide widths, totals occupy three columns and the chart row uses roughly a 2:1 split. Below 900 pixels, charts stack with the trend first. On narrow screens, totals stack, controls wrap, and chart labels shorten without removing access to full values. Avoid horizontal page scrolling.

Every chart has a heading, a short textual summary and a **View data table** control. Tooltips work on focus and tap as well as hover; equivalent table links support keyboard navigation. Use visible focus styles, adequate text contrast, patterns or outlines for partial periods, and reduced-motion preferences. Announce completed filter changes without reading every plotted value.

## Empty, incomplete and error states

- Before setup: show **Set up your library** and a short explanation; no fabricated charts.
- Receipts only: explain that receipts were recorded but need transactions before counted-spending visuals can be populated; link to unmatched receipts and transaction import.
- Partial coverage: retain totals with account/date coverage nearby. “No recorded spending” must not imply that the household spent nothing.
- Loading: show placeholders with the same dimensions as the finished panels.
- A failed section: show a local error and Retry; keep successful sections usable. If older data remains visible, label it with its previous period and loaded time.
- Multiple currencies: keep their totals separate; provide a visible currency selector even when USD is the default.

## Delivery and acceptance

1. Add Home navigation, controls, totals and coverage using existing tools.
2. Add the monthly trend, category donut, accessible tables and matching Finances filters.
3. Add attention links, bills and the complete empty/loading/error states.

Accept the first version when every displayed total reconciles to its corresponding server result; chart drill-downs reproduce the same scope; unmatched receipts and transfers are not double-counted; currencies never mix; missing months remain distinguishable from zero; and rapid filter changes cannot display values from an earlier selection. Verify keyboard use and layouts at 390, 768 and 1440 pixels.

Deferred: budgets, spending forecasts, net worth, live balances, automatic exchange-rate conversion and customization of dashboard panels.
