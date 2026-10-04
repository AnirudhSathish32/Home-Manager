# Money

How receipts, statements and imports become counted spending: what counts, reconciliation, categories and how a
payment is divided between them, rules and budgets, rewards, recurring bills, currency conversion, and the money pages
including Home. Investments, the forecast and What If are in [planning](planning.md). Taxes are in [taxes](taxes.md).

Code: `core/categories.py`, `core/money.py`, `finance/ledger.py`, `finance/reconcile.py`, `finance/splits.py`,
`finance/item_categories.py`, `finance/recurring_scan.py`, `finance/fx.py`, `finance/tools.py`, `finance/dashboard.py`,
`finance/checkin.py`; pages `app/static/finance.js`, `home.js`, `review.js`, `receipt.js`, `library.js`.

## Money rules

The rules every money figure follows. They are tested with fixtures, and the ledger health check (see
[operations](operations.md#ledger-health)) checks them.

- **Money is exact.** Amounts are integer minor units with an explicit currency and exponent (zero, two or three
  fractional digits). Ratios and rates use Python `Decimal` with an explicit rounding mode, and are serialized as exact
  strings. Binary floats are never used. Unknown currencies fail validation. Currency is never inferred from an
  ambiguous symbol.
- **Signs.** Each importer normalizes signs: positive is money in, negative is money out. The original fields are
  kept.
- **Spending.** Spending counts posted transactions and approved receipts. It leaves out matched internal transfers
  and card payments, and treats refunds as reductions. Pending entries stay visible but are not counted.
- **Dates.** Queries use half-open intervals `[start, end)`. Date-only transaction dates are never given an invented
  time. Results say whether they used the posted date or the transaction date.
- **Currencies are never added together directly.** Totals are per currency, and a separate USD figure is given when
  rates allow (see [Currency conversion](#currency-conversion)).
- **Balances come from statement snapshots,** with `as_of` and a source label. An incomplete import is never
  presented as a current bank balance.
- **Comparisons** return both totals, the exact difference and the coverage. A zero baseline gives no percentage,
  never infinity or a made-up number.
- **Import identity** prefers stable provider or account transaction ids. Heuristic fingerprints flag possible
  duplicates without dropping real transactions that happen to have equal values. Re-importing an identical batch
  changes nothing.
- **The model proposes, the code decides.** A model reading is a proposal, not proof. It counts only after
  deterministic checks pass and it is verified automatically or approved in Review.

## Two stores, one library

- **Receipts & statements** (the Money section) holds Receipts, with a subfolder per category, Bank Statements and
  Credit Card Statements: proof of what was spent, counted and reconciled.
- **Documents** holds Housing, Insurance, Investments, Jobs, Loans and Taxes, plus the shared Inbox and Unfiled: papers
  kept because they matter.
- Files arrive in the one Inbox and are filed to whichever store fits. Trash shows each store's trashed files.
  Emptying Trash is offered from Documents only, because it empties both. On disk the folders are listed in
  `core/folders.py` (`MONEY_FOLDERS`, `DOCUMENT_FOLDERS`). `scope=money|documents` on `/api/documents` and
  `/api/folders` selects the store.
- **Bills are not tracked** (migration 029). A bill ("you owe … by …") is recognized but not recorded, and is filed
  to Unfiled. The Bills folder is retired. Recurring bills come from payments, statement payees and contract terms
  instead (see [Recurring bills](#recurring-bills)).

What each document type means for money:

| Type | Facts read | Meaning |
|---|---|---|
| Bank statement | account, period, opening and closing balances, each posting | postings and balance evidence; a closing balance is not an expense |
| Credit card statement | account, period, purchases, refunds, fees, payments, statement balance | purchases and fees can be spending; paying the card is a transfer, not another purchase |
| Receipt | merchant, purchase date, currency, items, tax, tip, total, payment lines, rewards | purchase evidence: matched to a posting, or counted on its own until one replaces it |
| Bill | payee, amount due, due date | recognized but not recorded; recurring bills come from payments instead |

The dates are kept separate: the folder a file sits in, the document's issue date, statement coverage, transaction and
posted dates, purchase date and due date. A statement spanning two months is found by its coverage, not its folder.

## What counts

- **Receipts count on their own.** An approved receipt (verified automatically or by you) with a positive total and
  a purchase date counts as spending (`STANDALONE_RECEIPT`). Receipts have no account, so they appear only in
  household-wide totals, never in a single account's. A refund receipt stays as evidence until a posted credit
  settles it.
- **A matched charge replaces its receipt.** Once a card or bank line is linked to the receipt (proposed or
  confirmed, and not rejected), the line counts and the receipt stops counting. Never both.
- **Totals show the split.** Spending results carry `from_receipts` and `receipts`: the part that so far only receipts
  show.

## New statements wait for you

Recording a bank or credit card statement marks it `awaiting` (`statements.reconciliation`). Until you reconcile it,
its lines are neither counted nor matched (`HELD`), so a receipt and its charge are never counted together. Lines that
also came from a CSV/XLSX import keep counting.

The app asks: "Credit card statement recorded … Begin reconciling receipts?"

- **Yes** releases the lines and runs reconciliation. The result says how many charges matched your receipts and how
  many need you to pick the right charge in Review.
- **No** leaves the statement waiting. A reminder with **Reconcile now** stays until you do.

## Reading a statement or receipt again

Extracting a document again (with a better model, or with **Try again**) never touches a record you approved or
rejected yourself. If the record is waiting in Review or was approved automatically, the new reading replaces the old
one line by line:

- **A line found again** keeps its place in the ledger and everything attached to it, and takes the new reading's text.
  - A statement line is the same line when it has the same posted date, amount and currency (its fingerprint). Its
    category, write-off tags and receipt match stay.
  - A receipt item is the same item when it has the same description (ignoring case and punctuation) and the same line
    total. It keeps its identification, write-off tags, household item and your own category. It moves to its position
    in the new reading, so a line the first reading missed can appear above it.
- **A line no longer found** is removed, along with the app's own proposals about it (matches, open questions).
- **A line no longer found that you worked on** is kept, and the record waits in Review with a note asking you to
  check it.
  - For a statement line, "worked on" means you categorised it, tagged it, or matched it to a receipt, a transfer or a
    bill, or linked it to an investment.
  - For a receipt item, it means you categorised, identified or tagged it, or it is in your household items. It is
    placed after the new reading's items.

## Near matches and foreign receipts

Exact-amount matching misses a tip added after the receipt printed, or a currency conversion. When no charge has the
receipt's exact total, a charge from the same merchant up to 30% larger, within the posting window
(`RECEIPT_POSTING_DAYS`, 5 days), becomes an "ambiguous receipt match" question in Review instead of a link. Choosing it
links the two (signal `near_amount`). How a receipt in another currency is matched is covered in
[A foreign receipt and its USD card charge](#a-foreign-receipt-and-its-usd-card-charge).

## Categories

Receipts and their items take categories from one fixed, flat list (`RECEIPT_CATEGORIES` in `core/categories.py`):
groceries, dining, furniture & decor, household supplies, home improvement, clothing, electronics, personal care,
transportation, travel, health, entertainment, subscriptions, housing, insurance, pets, kids & baby, gifts & donations,
other. `CATEGORY_GUIDE`, in the same file, says what each one covers; it is what the model is shown. Household *product*
categories (for inventory) are a different list; see [household](household.md#items-and-inventory).

- **How a receipt gets its category.** The model suggests one while recording the receipt. You can change it with
  **Edit details**. Your change is kept as a correction, so recording the document again doesn't undo it.
- **Shopping is retired** (migration 034). It covered all general retail, which hid furniture, home goods, clothing and
  electronics.
  - Items still filed under it are marked `legacy`. They keep counting under "shopping" (and the Library lists a
    Shopping folder) until the model re-sorts them with **Categorise their items** in the Items view
    (`finance/item_categories.py`).
  - Items you put under a current category yourself are never touched.
  - A receipt whose own category was shopping takes the model's new category. If shopping was your own correction, the
    replacement is recorded as a correction too.
  - "shopping" can no longer be chosen (`LEGACY_CATEGORIES`).
  - Earlier migrations 027–029 had already moved utilities to housing, transport to travel and home to shopping.
- **Transaction categories are free text.** Budgets and category rules for transactions are free text too, so a budget
  named "shopping" keeps working. You can re-point it on Spending & budgets.
- **Investments are not a category.** Buying shares or contributing moves money into something you still own, so it
  is not spending. Investments have their own document type and section ([planning](planning.md#investments)).
- In Receipts & statements, the **Receipts** folder expands to **All receipts**, one subfolder per category, and
  Uncategorized. A receipt appears in the subfolder of every category its items fall in.

## Item categories and splits

One receipt can hold several kinds of spending. A Costco trip might include a food-court hot dog (dining), a mattress
(furniture & decor) and eggs, bacon and milk (groceries). So categories belong to **receipt items**, not to whole
receipts (migration 032, `finance/splits.py`).

**How items get a category**
- While recording a receipt, the model gives a category for each item (`item_categories`), from the same fixed list.
- It also reads each item's printed tax code, when there is one, into `receipt_items.taxed`.
- A category you chose for an item earlier takes precedence over the model's answer. Your choices are remembered per
  seller and item text in `item_category_memory`.
- An item with no category takes the receipt's own category.
- **Changing one item** (the dropdown in the item table, `PUT /api/receipts/{id}/items/{position}/category`) changes
  only that item, and remembers the choice.
- **Changing the whole receipt's category** (Edit details) sets every item you haven't categorised yourself.

**How the money is shared out.** The amount paid is divided so the categories add up exactly to it. The result is
stored in `category_splits` and rebuilt whenever items, categories or receipt links change. The rules:
1. An item's own amount is its line total less any discount printed on it.
2. An order-wide discount (when the printed subtotal differs from the sum of the items) is shared out in proportion
   to item amounts.
3. Tax is shared out in proportion to amount across the items the receipt marks as taxed. If no item is marked, it is
   shared across every item.
4. A tip counts as dining.
5. If the charge differs from the receipt (a tip added after signing, or an accepted near match), the difference counts
   as dining on a dining receipt. Otherwise it is shared out in proportion to amount.
6. Shares stay exact fractions until the end. Largest-remainder rounding keeps the sum exact.

| Item | Price | Taxed | Counts as |
|---|---|---|---|
| Hot dog | $1.50 | yes | Dining $1.62 |
| Mattress | $499.99 | yes | Furniture & decor $539.99 |
| Groceries | $80.00 | no | Groceries $80.00 |
| **Total** (tax $40.12) | | | **$621.61** |

Without tax codes, the tax would be shared across all three items: Dining $1.60, Furniture & decor $534.49, Groceries
$85.52.

**Which category a charge counts under**, in order:
1. A category you set on the charge itself covers all of it.
2. Otherwise, a charge matched to an itemised receipt is divided according to the receipt's items. This takes
   precedence over category rules, so "COSTCO → groceries" no longer files a mattress under groceries.
3. Otherwise, a category rule.
4. Otherwise, the matched receipt's own category, or uncategorized.

**Reconciliation stays per charge.** A statement shows one line per charge, not per item, so the statement line and
the receipt total are the two figures that can be checked against each other. Every item on a matched charge is
**Reconciled**. Items on a receipt that no line has replaced yet are **Receipt only**. A line with no receipt is
**Statement only**.

**Where it shows**
- **Transactions page.** Opens on **Items**: one row per item, with its share of what was paid, a category dropdown and
  its status (`get_spending_items`). A matched charge's items appear once, under the charge. **Charges** lists each card
  or bank line.
- **Transaction drawer.** Shows a charge's split.
- **Receipt page.** Shows each item's price, category and share, then the totals by category.
- **Totals.** Category totals, budgets, the Home donut, the forecast and anomaly checks all count by item category.

**Receipts recorded before item categories existed** have items with no categories. The Items view offers **Categorise
their items**, a one-time job (`finance/item_categories.py`) that asks the model about the stored item names; nothing is
transcribed again. Tax codes can't be recovered this way, so tax on those receipts is shared across all items.

## Category rules and budgets

**Rules** (migration 023). `category_rules(pattern, category, account_id?)`: a transaction whose merchant key contains
every word of the pattern gets that category. The merchant key is `normalize_name` applied to the description plus the
merchant name. The most specific rule wins (the most words, then the newest).

`transactions.category_source` records `user` or `rule`. A rule never touches a category you set by hand. Clearing a
category you set by hand hands the row back to the rules. Rules are applied:
- when rows are inserted (imports and extractions);
- when a rule is added, changed or deleted;
- at the end of `Reconciler.run` and `review_link`, because a matched receipt can give a transaction a merchant name and
  rejecting the link removes it. This re-run touches only rule-managed and uncategorized rows.

**Budgets.** `budgets(category, currency, amount_minor)` holds one monthly amount per category and currency.
`get_budgets(month)` returns, for each budget:
- what was spent (the same counted category spending as By category), what remains and the percent used;
- the pace for the current month: `over` when spending exceeds the budget, `ahead` when the share spent is above the
  share of the month elapsed, otherwise `on_track`;
- what confirmed recurring bills in that category still expect this month (`recurring_due`), and the projected
  month-end total (`projected`).

All figures use exact integer arithmetic with display text; percentages are exact Decimal strings. Home shows a Budgets
card when budgets exist. What If can turn a plan's spending into budgets ([planning](planning.md#what-if)).

## Reading the whole receipt

Every question about a receipt as a whole sees the entire transcription: its type, summary fields, seller, item
categories and rewards. Totals, payment lines and rewards are printed at the bottom, and a long supercenter receipt can
run past 80 lines. Item rows are still read 80 lines per call, which leaves room for the answer; together the calls
cover every line.

Other documents are read whole when they fit in one call (`WHOLE_BYTES`, 48 KB). A longer one, such as a long
statement, is read as its start and end, with a note saying so. The classification prompt defines a receipt, a
statement and a bill, so a clear receipt isn't answered `unknown`. A document of `unknown` type stays in Unfiled. An
automatic Unfiled placement never blocks refiling after **Try again**.

## Rewards and offers

Each receipt is also asked for the rewards, perks and offers printed on it or encoded in its QR codes and barcodes
(`receipt_rewards`, migration 033). Each decoded code is shown to the model as a line it can cite, named by the code's
id.

- **Kinds:**
  - `earned` or `redeemed`: points or cash back, e.g. Walmart Cash earned
  - `balance`: a points or rewards balance
  - `membership`: member or loyalty savings
  - `offer`: a coupon or offer for a future visit
  - `survey`: a survey invitation
- **Checks.** Each reward must be cited. Its amount and link are kept only if they're printed word for word in the
  cited lines; otherwise the reward is left out. Its expiry must be a full date. A failed answer never stops the
  receipt from being recorded.
- **On the receipt page,** rewards are listed under **Rewards & offers**. Links are shown as text, not made
  clickable, because they come from a document.

## Recurring bills

Recurring bills are used for forecasting and budgets (migration 028, `Reconciler.propose_bills` / `track_bills`).
There are three sources:

- **One payment proposes one.** While recording a receipt for an ongoing service, the model also says how often it is
  billed (`recurrence`: weekly, monthly, quarterly, every six months, yearly).
  - Such a receipt proposes a recurring bill in Review. So does any approved receipt in a `BILL_CATEGORIES` category
    (housing, insurance, subscriptions; defined in `finance/reconcile.py`).
  - So does a card or bank charge with such a category, whether set by you or by a category rule. One charge can't
    show how often it repeats, so it is proposed as monthly and you choose the frequency when confirming.
  - The older rule (the same exact amount three times at a steady cadence) still applies.
- **Statement payees** (migration 030, `finance/recurring_scan.py`). This scan runs after a statement is recorded, and
  from the Bills page's **Look for recurring bills** button (for CSV imports).
  - The local model is shown each payee that hasn't been asked yet and has no bill: its name and up to six recent
    charges.
  - It answers whether this is an ongoing service billed on a schedule (phone, internet, utilities, insurance,
    subscriptions), and how often.
  - Answers are stored in `payee_recurrence`, so each payee is asked once. A recurring answer proposes a bill
    (`statement_model`) in Review.
- **Contract terms** (migration 030). Housing, insurance and loan documents are read in full, chunk by chunk, for
  scheduled payments (rent, a premium, a loan payment, dues).
  - Each term needs a cited payee and amount. A chunk whose citations fail twice is skipped with a note, and never
    fails the document.
  - Each term is proposed (`contract_terms`) with its document and quoted amount line.
  - The next due date is a printed first due date rolled forward; without one, it is set by the first matched payment.

How proposed and confirmed bills behave:

- **Bill or subscription** (migration 048, `recurring_obligations.kind`). Every recurring payment is one or the other,
  and you decide: a bill is one you count as important, a subscription one you count as less so (a game subscription
  could be either).
  - A new proposal starts from its category: subscriptions and entertainment start as subscriptions, everything else
    as a bill, and contract terms are always bills.
  - You confirm or change the kind in Review, and can change it later on the Bills page. Each change is audited in
    `review_events`. Detecting the bill again never overwrites your choice.
  - Both kinds count the same in spending, budgets and the forecast. The Bills page totals subscriptions separately,
    and What If can cancel them from a chosen month on.
- **One bill per payee.** A payee that already has a bill, including one you rejected, gets no new proposal.
- **Deleting the source** (a receipt or document emptied from Trash) keeps the recurring bill and clears the link.
- **Later payments keep it current.** A counted payment to the same payee within 50%–150% of the usual amount is
  treated as a payment of the bill. It sets the last-paid date and the next due date, and the expected amount becomes
  the average of the last three payments, so varying utility bills are tracked. A receipt and its matched charge count
  as one payment.
- **Forecast.** Confirmed bills are placed in the months they fall due (weekly ones spread evenly). Their past payments
  are taken out of the category averages so nothing is counted twice ([planning](planning.md#forecast)).
- **Upcoming bills.** Home and the Bills page list confirmed bills by next due date (`get_upcoming_bills`). Proposed
  bills stay in Review. Each matched payment moves the next due date on, so a due date that has already passed means no
  payment has been found since, and the bill shows as overdue.
- **Emailed bill notices** (the exact amount and due date before paying) are not built; see [open work](open-work.md).

## Currency conversion

Code: `finance/fx.py`, `core/money.py` (`convert_minor`), the cross-currency match in `finance/reconcile.py`, and
`usd_total` in `finance/tools.py`. Tests: `tests/test_fx.py`.

Totals are still kept per currency. When a period includes anything other than USD, `get_spending`, `compare_periods`
and `calculate_cashflow` also return `usd_total`: everything added up in USD, with the rate ids used and a status of
`complete` or `partial`. USD-only data has no `usd_total` and never touches rates. Category totals, budgets and the Home
dashboard are still shown per currency.

### Rates
- **Source.** The ECB's euro reference rates, downloaded as one public file (`eurofxref-hist.zip`). The request carries
  no household data. USD per unit of X = (USD per EUR) / (X per EUR), computed in exact decimals from the same
  publication date.
- **When it downloads.** Only `EcbRates.refresh()` goes to the network. It runs in the background when a profile opens,
  if rates are on, foreign amounts are present and the last download was over 20 hours ago. It also runs from
  **Refresh rates** on the Taxes page.
- **Turning it off.** Settings → "Download ECB exchange rates" turns downloads off; foreign amounts then stay
  unconverted.
- **Downloads are recorded.** Each one goes into `fx_rate_sets` (SHA-256, size, date range).
- **Stored rates never change.** A published (date, currency) rate is stored once, by the first download that brings
  it. Triggers refuse updates and deletes. If a later file disagrees about a stored rate, the disagreement is counted in
  `conflicts` and the first value stands.
- **Rate ids.** A rate id is `ecb:<ECB date>:<currency>` and always resolves to the same values.
- **Unsupported currencies.** Currencies the ECB doesn't publish (BHD, KWD, JOD, OMR, TND) are `unsupported`.

### Which rate a line gets
1. A line is dated by its transaction date when it has one, otherwise by its posted date. A receipt is dated by its
   purchase date.
2. It gets the latest ECB publication on or before that date, at most 7 days earlier (covering weekends and holidays).
3. There is never a rate for a future date. A date after the last download is `rate_missing` until rates are
   refreshed. A gap of more than 7 days is `rate_stale`. Nothing is ever filled in with today's rate, zero or 1:1.
4. Each line is converted and rounded half-even on its own, then the lines are summed.

Lines that can't be converted are left out of the USD figure, listed under `unresolved`, and make the status `partial`.

### A foreign receipt and its USD card charge
A receipt in another currency can be matched to the USD card charge that paid it.
- **Finding candidates.** When no same-currency charge fits, reconciliation looks for USD charges within the posting
  window at 97–106% of the receipt's ECB estimate. Cards add foreign-transaction fees, and their network rate can be a
  little better. Charges naming the merchant are preferred.
- **Always your choice.** A match like this is always a question in Review, never linked automatically.
- **After you pick the charge,** the charge is what counts, once. The receipt's estimate and rate id stay on the link
  (`estimate_rate_id`, `estimate_minor`) as provenance. Its item categories are shared out in the receipt's currency,
  then resized to match the charge.

### "Pesos"
A document that says pesos without a currency code is not given a currency, because pesos can be Mexican (MXN) or
Philippine (PHP). Publishing is blocked until you choose. A printed `MXN` or `PHP`, or a statement account's own
currency, settles it.

### Assistant tools
- `lookup_exchange_rate` (currency, date) returns the cached rate and its `rate_id`, or `unavailable` with the reason.
- `convert_document_amount` (receipt id, rate id) converts using exactly that rate. It refuses an invented id, another
  currency, or a rate that isn't for the receipt's date.
- The model never supplies a rate or a URL, and converting approves nothing.

## Money pages

| Route | Content |
|---|---|
| `#/home` | The dashboard (see [Home](#home)). |
| `#/transactions` | Items and Charges views. The toolbar has search, from/to, account, category, type, status, receipt evidence and sort. The table pages 200 rows at a time (server offset). A row opens a drawer with the amount, status (Count/Reject), category with "always use for this merchant", the split, evidence and links, and history. |
| `#/spending` | **Spending & budgets.** The month compared with the previous month and the same month last year. Figures, a by-category table with change and budget, top merchants, refunds and coverage notes. Budgets and category rules are managed here. |
| `#/bills` | Confirmed recurring bills grouped as overdue, next 7 days and later, with subscriptions totalled separately. Recurring payments offer Confirm, Not recurring and Ended. **Look for recurring bills** runs the payee scan. |
| `#/accounts` | Accounts grouped by type, each with its statement balance and "as of" date, coverage, a stale marker (over 35 days) and a link to its transactions. There is no total across accounts. |
| `#/receipts` | Receipts & statements: the money store's folders. |
| `#/review` | The Review queue (see [ui](ui.md#review)). Its groups: Questions, Proposed matches, Records to verify, Investment and loan documents to confirm, Warranties to confirm, Tax tables to confirm, Possible write-offs and tax payments, Recurring payments, Receipt items to identify. Statements awaiting reconciliation and documents that couldn't be processed are listed beside the queue. |

Old `#/finances?…` links redirect: `section=review|unmatched` goes to Review, `section=bills` to Bills, and anything else
to Transactions with the same filters.

## Home

`#/home` is the default page once a library is set up. It answers three questions: how much have we spent, how is
spending changing, and what needs attention. Every total links to the records behind it.

- **One snapshot.** `GET /api/dashboard` reads every panel from one SQLite snapshot. If the snapshot fails, the whole
  dashboard shows one Retry rather than mixing partly refreshed figures.
- **Money comes from the server.** Totals, differences and shares are computed on the server in integer minor units.
  The browser only positions chart marks.
- **Controls.** The month defaults to the current calendar month. The currency defaults to the home currency if it is
  in the data, otherwise USD, otherwise the first currency available. Currencies are never combined on Home.
- **Totals.** Net spending (counted spending less refunds), Money in, and Net cash flow (counted money in less money
  out; not a balance or savings estimate).
  - For the current month, totals stop at today and are compared with the same number of elapsed days in the previous
    month. Completed months are compared as full months.
  - If the previous figure is zero or missing, both amounts are shown without a percentage.
  - Comparison text is neutral, with a direction marker: more spending is not called bad.
- **Spending over time.** Monthly net-spending bars: six months by default, twelve as an option.
  - The current month is marked partial.
  - A month with no records shows a gap, not a zero bar. A month that nets to zero shows an explicit zero marker.
  - Each bar opens that month's transactions.
- **Spending by category.** A donut of gross spending before refunds. Refunds are shown beside it to explain the gap
  to net spending.
  - It shows the top five categories, Other and Uncategorized, which is never folded into Other. Uncategorized is gray.
  - Every chart has a text summary and a **View data table** control (chart rules: the `forecast-charts` skill).
- **Needs attention.** Separate rows, never added into one total:
  - receipts with no matching charge (these count on their own until a charge replaces them);
  - receipts without a purchase date;
  - records awaiting review;
  - documents to deal with;
  - Taxes, when Tax Zen got worse ([taxes](taxes.md#tax-zen));
  - family documents waiting to be routed.
- **Upcoming bills.** The next three confirmed bills due within 30 days, plus up to three overdue ones.
- **Extra cards,** loaded without holding up the dashboard: Budgets, the weekly check-in, Return windows closing (next
  14 days) and Warranties ending soon (next 60 days); see [household](household.md).
- **Family view.** Shows "Counted once" totals and family net worth ([family](family.md)).
- **Not shown yet:** live balances, customizable panels, a month-end projection, and a daily or weekly view.
