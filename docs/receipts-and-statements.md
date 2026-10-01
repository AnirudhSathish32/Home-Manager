# Receipts, statements and reconciliation

## Two stores, one library

- **Receipts & statements** (Money section): Receipts (with its category subfolders), Bank Statements, Credit Card
  Statements. Proof of what was spent; counted and reconciled.
- **Documents**: Housing, Insurance, Investments, Jobs, Loans, Taxes, plus the shared Inbox and Unfiled. Papers
  kept because they matter.
- Files arrive in the one Inbox and are filed to whichever store fits. Trash shows each store's trashed files;
  emptying it is offered from Documents only, because it empties both. Folders stay on disk as before
  (`core/folders.py`: `MONEY_FOLDERS`, `DOCUMENT_FOLDERS`); `scope=money|documents` on `/api/documents` and
  `/api/folders` selects the store.
- **Bills are not tracked** (migration 029). A bill ("you owe … by …") is recognized but not recorded, and is filed
  to Unfiled. The Bills folder is retired: startup moves its files to `Library/Unfiled`. Recurring bills come from
  payments, statement payees and contract terms instead (below). Bill instances may return later for emailed bill
  notices (the exact amount and due date before paying), linked to their recurring bill; not built.

Status: implemented 2026-09-27/28 (migrations 026-029, `core/categories.py`, `finance/ledger.py`, `finance/reconcile.py`,
`finance/tools.py`, `app/static/finance.js`, `library.js`, `receipt.js`). Item categories added 2026-09-28 (migration 032,
`finance/splits.py`, `finance/item_categories.py`).

Implements the rule in [architecture.md](architecture.md) ("Ingestion and document lifecycle"): a reviewed receipt
establishes a standalone expense until a bank or card posting replaces it, without double counting.

## What counts

- **Receipts count on their own.** An approved receipt (verified automatically or by you) with a positive total and
  a purchase date counts as spending (`STANDALONE_RECEIPT`). Receipts have no account, so they appear only in
  household-wide totals, never in a single account's. Refund receipts stay evidence until a posted credit settles them.
- **A matched charge replaces its receipt.** Once a card or bank line is linked to the receipt (proposed or
  confirmed, and not rejected), the line counts and the receipt stops counting. Never both.
- **Totals show the split.** Spending results carry `from_receipts` and `receipts`: the part only receipts show so far.

## New statements wait for you

Recording a bank or credit card statement marks it `awaiting` (`statements.reconciliation`). Until you reconcile
it, its lines are neither counted nor matched (`HELD`), so a receipt and its charge are never counted together.
Lines that also came from a CSV/XLSX import keep counting.

The app asks: "Credit card statement recorded … Begin reconciling receipts?"

- **Yes** releases the lines and runs reconciliation. The result says how many charges matched your receipts and
  how many need you to pick the right charge in Review.
- **No** leaves the statement waiting. A reminder with **Reconcile now** stays until you do.

Statements recorded before this change were already reconciled and are unaffected.

## Reading a statement or receipt again

Extracting a document again (a better model, or **Try again**) never touches a record you approved or rejected
yourself. For one waiting in Review or approved automatically, the new reading replaces the old one, line by line:

- A line it finds again keeps its place in the ledger and everything attached to it, and takes the new reading's text.
  - A statement line is the same line when it has the same posted date, amount and currency. Its category, write-off
    tags and receipt match stay.
  - A receipt item is the same item when it has the same description (ignoring case and punctuation) and line total.
    It keeps its identification, write-off tags, household item and your own category, and it moves to the new
    reading's position, so a line the first reading missed can appear above it.
- A line it no longer finds is removed, with the app's own proposals about it (matches, open questions).
- A line it no longer finds but that you worked on is kept, and the record waits in Review with a note to check it.
  - For a statement line, that means one you categorised, tagged, matched to a receipt, a transfer or a bill, or
    linked to an investment.
  - For a receipt item, it means one you categorised, identified or tagged, or one in your household items. It's kept
    after the new reading's items.

## Near matches

Exact-amount matching misses a tip added after the receipt printed, or a currency conversion. When no charge
has the receipt's exact total, a same-merchant charge up to 30% larger within the posting window becomes an
"ambiguous receipt match" question in Review instead of a link. Choosing it links the two (signal `near_amount`).

## Categories

Receipts and their items take categories from one fixed, flat list (`RECEIPT_CATEGORIES` in `core/categories.py`):
groceries, dining, furniture & decor, household supplies, home improvement, clothing, electronics, personal care,
transportation, travel, health, entertainment, subscriptions, housing, insurance, pets, kids & baby,
gifts & donations, other. `CATEGORY_GUIDE`, in the same file, says what each covers, and it's what the model is
shown.

- **How a receipt gets its category.** The model suggests one while recording the receipt. Change it with
  **Edit details**. It's kept as a correction, so re-recording the document doesn't undo it.
- **Earlier renames.** Migrations 027-029 moved receipts marked utilities to housing, transport to travel and home to
  shopping.
- **Shopping is retired** (2026-09-28, migration 034). It covered all general retail, which hid furniture, home goods,
  clothing and electronics.
  - Items still under it are marked `legacy`. They keep counting under "shopping", and the Library lists a Shopping
    folder, until the model re-sorts them: **Categorise their items** in the Items view (`finance/item_categories.py`).
  - Items you categorised under a current category are never touched.
  - A receipt whose own category was shopping takes the model's new one. If shopping was your correction, the
    replacement is recorded as a correction too.
  - "shopping" can't be chosen any more (`LEGACY_CATEGORIES`).
- **Free-text categories aren't changed.** Budgets and category rules for transactions are free text, so one named
  "shopping" keeps working. Re-point it on Spending & budgets.
- **Subscriptions propose bills.** A single subscription payment proposes a recurring bill, as housing and insurance
  do (`BILL_CATEGORIES`).

Investments are deliberately not a category: buying shares or contributing moves money into something you still own,
so it is not spending. They have their own document type and Investments section ([investments.md](investments.md)).

- The Documents **Receipts** folder collapses and expands. Inside: **All receipts**, then one subfolder per
  category, plus Uncategorized. A receipt appears in the subfolder of every category its items fall in.
- Transaction categories remain free text, as before.

## Item categories

One receipt can hold several kinds of spending. A Costco trip might include a food-court hot dog (dining), a mattress
(shopping) and eggs, bacon and milk (groceries). So categories belong to **receipt items**, not to whole receipts
(migration 032, `finance/splits.py`).

**How items get a category**
- While recording a receipt, the model gives a category for each item (`item_categories`), from the same fixed list.
- It also reads each item's printed tax code, when there is one, into `receipt_items.taxed`.
- A category you chose for an item earlier is used ahead of the model's answer. It is remembered per seller and item
  text in `item_category_memory`.
- An item with no category takes the receipt's own category.
- **Changing one item** (dropdown in the item table, `PUT /api/receipts/{id}/items/{position}/category`) changes only
  that item, and remembers the choice.
- **Changing the whole receipt's category** (Edit details) sets every item you haven't chosen yourself.

**How the money is shared out.** The amount paid is divided so the categories add up exactly to it. This is stored
in `category_splits`, rebuilt whenever items, categories or receipt links change. The rules:
1. An item's own amount is its line total less any discount printed on it.
2. An order-wide discount (the printed subtotal differing from the items) is shared by item amount.
3. Tax is shared by amount across the items the receipt marks as taxed. If no item is marked, it is shared across
   every item.
4. A tip is dining.
5. A charge that differs from the receipt (a tip added after signing, an accepted near match): the difference is
   dining for a dining receipt, otherwise shared by amount.
6. Shares stay exact fractions until the end; largest-remainder rounding keeps the sum exact.

Worked example:

| Item | Price | Taxed | Counts as |
|---|---|---|---|
| Hot dog | $1.50 | yes | Dining $1.62 |
| Mattress | $499.99 | yes | Shopping $539.99 |
| Groceries | $80.00 | no | Groceries $80.00 |
| **Total** (tax $40.12) | | | **$621.61** |

Without tax codes the tax would be shared across all three items: Dining $1.60, Shopping $534.49, Groceries $85.52.

**Which category a charge counts under**, in order:
1. A category you set on the charge itself covers all of it.
2. Otherwise, a charge matched to an itemised receipt is divided by the receipt's items. This beats category rules,
   so "COSTCO → groceries" no longer files a mattress under groceries.
3. Otherwise, a category rule.
4. Otherwise, the matched receipt's own category, or uncategorized.

**Reconciliation stays per charge.** A statement shows one line per charge, not per item, so the two sources that
agree are the statement line and the receipt total. Every item on a matched charge is **Reconciled**. Items on a
receipt no line has replaced yet are **Receipt only**. A line with no receipt is **Statement only**.

**Where it shows**
- **Transactions page.** Opens on **Items**: one row per item, with its share of what was paid, a category dropdown
  and that status (`get_spending_items`). A matched charge's items appear once, under the charge. **Charges** lists
  each card or bank line as before.
- **Transaction drawer.** Shows a charge's split.
- **Receipt page.** Shows each item's price, category and share, then the totals by category.
- **Totals.** Category totals, budgets, the Home donut, the forecast and anomaly checks all count by item category.

**Receipts recorded before this change.** Their items have no categories. The Items view offers **Categorise their
items**, a one-time job (`finance/item_categories.py`) that asks the model about the stored item names; nothing is
transcribed again. Tax codes can't be recovered this way, so tax on those receipts is shared across all items.

## Reading the whole receipt

Every question about a receipt as a whole (its type, summary fields, seller, item categories, and rewards) sees the
entire transcription. Totals, payment lines and rewards are printed at the bottom, and a long supercenter receipt runs
past 80 lines. Item rows are still read 80 lines per call, because that leaves room for the answer, and together those
calls cover every line.

Other documents are read whole when they fit one call (`WHOLE_BYTES`, 48 KB). A longer one, such as a long
statement, is read as its start and end, with a note. The classification prompt also defines a receipt, statement
and bill, so a clear receipt isn't answered `unknown`. An `unknown` type leaves the copy in Unfiled.

A receipt that went to Unfiled for "the document type is not confirmed" before this change files itself when you
extract it again (**Try again** on its ledger step). The Unfiled placement was automatic, so it doesn't block refiling.

## Rewards and offers

Each receipt is also asked for the rewards, perks and offers printed on it or encoded in its QR codes and barcodes
(`receipt_rewards`, migration 033). Each decoded code is shown to the model as a citable line, named by the code's id.

**Kinds:**
- `earned` or `redeemed`: points or cash back, e.g. Walmart Cash earned
- `balance`: a points or rewards balance
- `membership`: member or loyalty savings
- `offer`: a coupon or offer for a future visit
- `survey`: a survey invitation

**Checks.** Each reward is cited. Its amount and link are kept only if they're printed verbatim in the cited lines;
otherwise that reward is left out. Its expiry must be a full date. A failed answer never stops the receipt being
recorded.

**On the receipt page.** They're listed under **Rewards & offers**. Links show as text rather than clickable,
because they come from a document.

## Recurring bills

Recurring bills are for forecasting and budgets (migration 028, `Reconciler.propose_bills` / `track_bills`).

- **One payment proposes one.** While recording a receipt, the model also says how often it is billed (`recurrence`:
  weekly, monthly, quarterly, every six months, yearly) when it is a payment for an ongoing service. Such a receipt,
  or any approved housing or insurance receipt, proposes a recurring bill in Review. So does a card or bank charge
  categorized housing or insurance (by you or a category rule); how often can't be told from one charge, so it is
  proposed as monthly and you choose the frequency when confirming. The older rule (the same exact amount three
  times at a steady cadence) still applies.
- **Statement payees** (migration 030, `finance/recurring_scan.py`). After a statement is recorded, and from the Bills
  page's "Look for recurring bills" button (for CSV imports), the local model is shown each payee not yet asked and
  with no bill — its name and up to six recent charges — and says whether it is an ongoing service billed on a
  schedule (phone, internet, utilities, insurance, subscriptions) and how often. Answers are stored in
  `payee_recurrence`, so each payee is asked once; a recurring answer proposes a bill (`statement_model`) in Review.
- **Contract terms** (migration 030). Housing, insurance and loan documents are read in full, chunk by chunk, for
  scheduled payments (rent, a premium, a loan payment, dues). Each term needs a cited payee and amount; a chunk
  whose citations fail twice is skipped with a note and never fails the document. Each term is proposed
  (`contract_terms`) with its document and quoted amount line, next due from a printed first due date rolled
  forward (else set by the first matched payment).
- **Bill or subscription** (migration 048, `recurring_obligations.kind`). Every recurring payment is one or the
  other, and you decide: a bill is one you count as important, a subscription one you count as less so (a game
  subscription can be either). A new proposal is suggested from its category (subscriptions and entertainment
  start as subscriptions, everything else as a bill; contract terms are always bills). You confirm or change it in
  Review, and change it later on the Bills page; each change is audited in `review_events`. Re-detection never
  overwrites it. Both kinds count the same in spending, budgets and the forecast; the Bills page totals
  subscriptions separately, and What If can cancel them from a month on.
- **One bill per payee.** A payee that already has a bill, including one you rejected, gets no new proposal.
- **Deleting the source** (a receipt or document emptied from Trash) keeps the recurring bill and clears the link.
- **Later payments keep it current.** A counted payment to the same payee within 50%-150% of the usual amount is a
  payment of the bill: it sets last paid and the next due date, and the expected amount becomes the average of the
  last three payments, so varying utility bills track. A receipt and its matched charge are one payment.
- **Forecast.** Confirmed bills are placed on their due months (weekly ones spread evenly); their past payments leave
  the category averages so nothing is counted twice. See [forecast.md](forecast.md).
- **Budgets.** Each budget shows what confirmed bills in its category still expect this month (`recurring_due`) and
  the projected month-end total (`projected`).
- **Upcoming bills.** Home and the Bills page list confirmed bills by next due date (`get_upcoming_bills`); proposed
  ones stay in Review. Since each matched payment moves the next due date on, a due date already past means no
  payment has been found since: the bill shows as overdue.
