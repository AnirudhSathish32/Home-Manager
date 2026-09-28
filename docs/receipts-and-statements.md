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
`finance/tools.py`, `app/static/finance.js`, `library.js`, `receipt.js`).

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

## Near matches

Exact-amount matching misses a tip added after the receipt printed, or a currency conversion. When no charge
has the receipt's exact total, a same-merchant charge up to 30% larger within the posting window becomes an
"ambiguous receipt match" question in Review instead of a link. Choosing it links the two (signal `near_amount`).

## Categories

Receipts have one category from a fixed list (`RECEIPT_CATEGORIES`): dining, groceries, shopping (including
furniture, hardware and household supplies), travel (including fuel, parking, transit and rideshare), health,
entertainment, insurance, housing (rent, mortgage, HOA, repairs and utilities), other. The model suggests one while
recording the receipt; change it with **Edit details** (kept as a correction, so re-recording the document doesn't
undo it). Migrations 027-029 moved receipts marked utilities to housing, transport to travel and home to shopping.

Investments are deliberately not a category: buying shares or contributing moves money into something you still own,
so it is not spending. They are planned as their own document type and Investments section.

- The Documents **Receipts** folder collapses and expands. Inside: **All receipts**, then one subfolder per
  category, plus Uncategorized.
- A charge without its own category (set by you or a rule) takes its matched receipt's category in spending totals.
- Transaction categories remain free text, as before.

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
