"""The figures that can be traced, by ref name (core/trace.py; docs/ui.md "Trace contract").

Each builder re-runs the calculation that produced the figure, with a live Recorder, and returns the trace. A ref's
parameters are the calculation's own arguments, so the trace is of exactly the figure shown. A step that is itself a
figure carries that figure's ref, so the breakdown opens it in turn.
"""

from datetime import date

from ..core.money import currency_code
from ..core.trace import Recorder, build, parse, ref, remember
from .dashboard import group_categories
from .fx import REPORTING
from .ledger import Ledger
from .reconcile import bill_payments, expected_amount
from .tax_traces import TRACES as TAX_TRACES
from .tools import AccountInput, BudgetInput, FinanceTools, PeriodInput
from .wealth_traces import CONTEXT_TRACES as WEALTH_CONTEXT_TRACES
from .wealth_traces import TRACES as WEALTH_TRACES


def _day(params, key):
    text = params.get(key, "")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError(f"The trace needs {key} as a date (YYYY-MM-DD).") from None


def _id(params, key):
    try:
        return int(params[key])
    except (KeyError, ValueError):
        raise ValueError(f"The trace needs {key} as a number.") from None


def _period(params):
    """(start, end, currency, account id or None) from a ref's parameters."""
    account_id = int(params["account_id"]) if params.get("account_id") else None
    return _day(params, "start"), _day(params, "end"), currency_code(params.get("currency", REPORTING)), account_id


# Ledger and spending -------------------------------------------------------------------------------------------------

def spending_net(store, ref_text, params):
    """Net spending for a period and currency (tools.get_spending): charges plus receipts no charge replaced, less refunds."""
    start, end, currency, account_id = _period(params)
    recorder = Recorder()
    totals = FinanceTools(store)._totals(start, end, account_id, recorder=recorder)
    bucket = totals.get((None, currency), {"spending": 0, "refunds": 0})
    return build(ref_text, f"Net spending, {start} to {end}", bucket["spending"] - bucket["refunds"], currency,
                 "Card and bank charges counted in the period, plus receipts no charge has replaced yet, minus refunds. "
                 "Transfers, card payments and lines still waiting for review aren't counted.", recorder.only(currency))


def cashflow_net(store, ref_text, params):
    """Cash flow (tools.calculate_cashflow): money in less net spending."""
    start, end, currency, account_id = _period(params)
    recorder = Recorder()
    rows = FinanceTools(store).calculate_cashflow(PeriodInput(start=start, end=end, account_id=account_id), recorder)["by_currency"]
    row = next((item for item in rows if item["currency"] == currency), None)
    return build(ref_text, f"Cash flow, {start} to {end}", row["net"]["minor"] if row else 0, currency,
                 "Deposits, interest and other money in, minus net spending. Transfers between your own accounts and card payments "
                 "aren't money in or out.", recorder.only(currency))


def spending_category(store, ref_text, params):
    """One category's counted spending (tools._category_totals), refunds not taken off."""
    start, end, currency, account_id = _period(params)
    category = " ".join(params.get("category", "").split()).lower()
    if not category:
        raise ValueError("The trace needs a category.")
    recorder = Recorder()
    totals = FinanceTools(store)._category_totals(start, end, account_id, recorder, (currency, category))
    return build(ref_text, f"{category.capitalize()}, {start} to {end}", totals.get((currency, category), (0, 0))[0], currency,
                 "Charges and receipts counted in the period, in this category. A charge or receipt whose items are in several "
                 "categories counts only its items' share here, tax and discounts shared out with them. Refunds aren't taken off.", recorder)


def _categories(store, params):
    start, end, currency, account_id = _period(params)
    period = PeriodInput(start=start, end=end, account_id=account_id)
    return period, currency, [row for row in FinanceTools(store).get_spending_by_category(period)["categories"] if row["currency"] == currency]


def spending_other(store, ref_text, params):
    """Home's Other group (dashboard.group_categories): every named category after the five largest."""
    period, currency, categories = _categories(store, params)
    recorder = Recorder()
    groups, _, _ = group_categories(categories, currency, period, recorder, "other")
    other = next((row for row in groups if row["category"] == "Other"), None)
    return build(ref_text, f"Other categories, {period.start} to {period.end}", other["spending"]["minor"] if other else 0, currency,
                 "Every named category after the five largest, added together.", recorder)


def spending_gross(store, ref_text, params):
    """Home's category spending (dashboard.group_categories): every category, each net of its refunds."""
    period, currency, categories = _categories(store, params)
    recorder = Recorder()
    _, gross, _ = group_categories(categories, currency, period, recorder, "gross")
    return build(ref_text, f"Spending by category, {period.start} to {period.end}", gross, currency,
                 "Every category's counted spending added together, each after its refunds: the whole the category shares are of.", recorder)


def spending_usd(store, ref_text, params):
    """Net spending in USD (tools._usd_total, fx.consolidate): USD as is, every other line at its day's ECB rate."""
    start, end, _, account_id = _period(params)
    tools, recorder = FinanceTools(store), Recorder()
    net = tools._net_by_currency(start, end, account_id)
    total = tools._usd_total(start, end, account_id, net, always=True, recorder=recorder)
    found = build(ref_text, f"Net spending in USD, {start} to {end}", total["net"]["minor"], REPORTING,
                  "USD amounts as they are, plus every other line converted on its own day at the European Central Bank's reference rate. "
                  "A line with no rate for its day is left out and listed.", recorder)
    return {**found, "unresolved": total["unresolved"], "status": total["status"]}


def split(store, ref_text, params, charge):
    """A charge's or receipt's division by item category (ledger.shares, finance/splits.py)."""
    ledger = Ledger(store)
    with store.connection() as db:
        if charge:
            transaction_id = _id(params, "transaction_id")
            row = db.execute("SELECT l.receipt_id FROM transaction_receipt_links l WHERE l.transaction_id=? AND l.review_status<>'rejected' ORDER BY l.id LIMIT 1",
                             (transaction_id,)).fetchone()
            receipt_id = row["receipt_id"] if row else None
        else:
            transaction_id, receipt_id = None, _id(params, "receipt_id")
        found = ledger.split_inputs(db, receipt_id) if receipt_id else None
        if found is None:
            raise ValueError("This isn't divided by item category.")
        receipt, items, charges, shared = found
        target = next(((target, currency) for key, target, currency in charges if key == transaction_id), None)
        if target is None:
            raise ValueError("This charge isn't matched to that receipt.")
        recorder = Recorder()
        shares = ledger.shares(receipt, items, target[0], target[1], shared, recorder)
    what = "The charge" if charge else "The receipt"
    return build(ref_text, f"{what} by item category", sum(amount for _, _, amount in shares), target[1],
                 f"{what}'s amount shared out by item: each item's own amount, with the order-wide discount and the tax shared by amount, a tip "
                 "as dining, and any difference from what was charged shared the same way" + (", then this person's part of a shared receipt" if shared else "")
                 + ". Shares are exact until the end; the cents left by rounding go to the largest remainders.", recorder)


def budget_figure(store, ref_text, params, which):
    """A budget's remaining or projected amount (tools.get_budgets)."""
    month, currency = params.get("month", ""), currency_code(params.get("currency", ""))
    category = " ".join(params.get("category", "").split()).lower()
    recorder = Recorder()
    rows = FinanceTools(store).get_budgets(BudgetInput(month=month), recorder, (currency, category, which))["budgets"]
    row = next((item for item in rows if (item["currency"], item["category"]) == (currency, category)), None)
    if row is None:
        raise ValueError("There's no budget for that category and currency.")
    if which == "remaining":
        return build(ref_text, f"{category.capitalize()} budget left, {month}", row["remaining"]["minor"], currency,
                     "The month's budget minus what the category has spent so far.", recorder)
    return build(ref_text, f"{category.capitalize()} expected by the end of {month}", row["projected"]["minor"], currency,
                 "What the category has spent so far, plus confirmed recurring bills in it still due this month and not yet paid.", recorder)


def recurring_total(store, ref_text, params):
    """Confirmed recurring payments' cost a month or a year (tools.get_recurring_obligations)."""
    currency, kind, per = currency_code(params.get("currency", "")), params.get("kind", ""), params.get("per", "month")
    if per not in ("month", "year"):
        raise ValueError("The trace needs per as month or year.")
    recorder = Recorder()
    totals = FinanceTools(store).get_recurring_obligations(None, recorder, (currency, kind, per))["totals"]
    row = next((item for item in totals if (item["currency"], item["kind"]) == (currency, kind)), None)
    if row is None:
        raise ValueError("There are no confirmed recurring payments of that kind.")
    return build(ref_text, f"{kind.capitalize()}s, a {per}", row["monthly" if per == "month" else "yearly"]["minor"], currency,
                 f"Each confirmed {kind}'s cost a {per}: weekly ones count 52/12 times a month, others their amount over the months between "
                 "payments.", recorder)


def bill_expected(store, ref_text, params):
    """A recurring bill's expected amount (reconcile.track_bills): the average of its last three payments."""
    obligation_id = _id(params, "obligation_id")
    with store.connection() as db:
        bill = db.execute("SELECT o.*,m.canonical_name AS merchant FROM recurring_obligations o JOIN merchants m ON m.id=o.merchant_id WHERE o.id=?",
                          (obligation_id,)).fetchone()
        if bill is None:
            raise ValueError("Recurring payment not found.")
        bill = dict(bill)
        paid = bill_payments(db, bill)
    recorder, currency = Recorder(), bill["currency"]
    if paid:
        expected_amount(paid, currency, recorder)
        formula = "The average of the last three payments found to this payee (or of fewer, when that's all there are), rounded half to even."
    else:
        recorder.step("The amount when this recurring payment was found", "+", bill["expected_amount_minor"], currency)
        recorder.input(f"recurring:{obligation_id}", f"{bill['merchant']} · found from {bill['confidence_source'] or 'your records'}",
                       bill["expected_amount_minor"], currency, {"kind": "computed", "record": {"type": "recurring_obligation", "id": obligation_id}})
        formula = "No payment to this payee has been found yet, so it's the amount it was found with."
    return build(ref_text, f"{bill['merchant']}, expected", bill["expected_amount_minor"], currency, formula, recorder)


def account_balance(store, ref_text, params):
    """An account's balance (tools.get_account_balance): the latest statement's, never worked out from transactions."""
    tools, recorder = FinanceTools(store), Recorder()
    found = tools.get_account_balance(AccountInput(account_id=_id(params, "account_id")), recorder)
    if found["balance"] is None:
        raise ValueError(found["note"])
    return build(ref_text, f"Balance as of {found['balance']['as_of']}", found["balance"]["minor"], found["balance"]["currency"],
                 "The balance printed on the latest statement, as of its period end. It isn't worked out from transactions, "
                 "which may be incomplete.", recorder)


def tax_tags(store, ref_text, params):
    """A tax tag line's counted amount for a year (tax_tags.year): each confirmed tag's counted part."""
    from .tax_tags import TaxTags
    year, currency = _id(params, "year"), currency_code(params.get("currency", REPORTING))
    business_id = int(params["business_id"]) if params.get("business_id") else None
    only = (params.get("kind", ""), params.get("line", ""), business_id)
    recorder = Recorder()
    lines = TaxTags(store).year(year, currency, recorder, only)["lines"]
    row = next((item for item in lines if (item["kind"], item["line"], item["business_id"]) == only), None)
    if row is None:
        raise ValueError("Nothing is tagged on that line this year.")
    return build(ref_text, f"{row['line_label']}, {year}", row["counted_minor"], currency,
                 "Every confirmed tag on this line in the year, each item once (a receipt's tags replace its card charge's), at the share the "
                 "return counts.", recorder)


TRACES = {
    "spending.net": spending_net, "tax.tags": tax_tags, "cashflow.net": cashflow_net, "spending.category": spending_category, "spending.other": spending_other,
    "spending.gross": spending_gross, "spending.usd": spending_usd,
    "split.receipt": lambda store, text, params: split(store, text, params, False),
    "split.charge": lambda store, text, params: split(store, text, params, True),
    "budget.remaining": lambda store, text, params: budget_figure(store, text, params, "remaining"),
    "budget.projected": lambda store, text, params: budget_figure(store, text, params, "projected"),
    "recurring.total": recurring_total, "bill.expected": bill_expected, "account.balance": account_balance,
}
TRACES.update(WEALTH_TRACES)


# The family view (finance/family.py) -------------------------------------------------------------------------------
# A family figure is its members' figures added up, each worked out on that member's read-only copy. A member's own
# figure is the ordinary ref with `member` (its member id), so the same builder runs on that member's library.

def family_members(context):
    with context.family.mutex:
        return context.family_members()


def family_sum(store, ref_text, params, context):
    """A family total: each member's own figure (the same calculation on their copy), added up."""
    name = parse(ref_text)[0].removeprefix("family.")
    builder = TRACES.get(name)
    if builder is None or context is None or not context.family:
        raise ValueError("That isn't a family figure.")
    currency = currency_code(params.get("currency", REPORTING))
    recorder, total, label = Recorder(), 0, name
    for member, member_store in family_members(context):
        shown = ref(name, **params, member=member["member_id"])
        try:
            found = builder(member_store, shown, params)
        except ValueError:
            continue  # Nothing of this kind in their records.
        recorder.add(member["name"], found["result"]["minor"], currency, trace=shown)
        total += found["result"]["minor"]
        label = found["label"]
    return build(ref_text, f"The family: {label}", total, currency,
                 "Each member's own figure, worked out from their shared records the same way as on their own profile, added up.", recorder)


def family_other(store, ref_text, params, context):
    """The family Home's Other group: the family's categories after its five largest, each added up across members."""
    start, end, currency, _ = _period(params)
    combined: dict = {}
    for _, member_store in family_members(context):
        for row in FinanceTools(member_store).get_spending_by_category(PeriodInput(start=start, end=end))["categories"]:
            if row["currency"] == currency:
                combined[row["category"]] = combined.get(row["category"], 0) + row["spending"]["minor"]
    named = [name for name, _ in sorted(combined.items(), key=lambda item: -item[1]) if name != "uncategorized"]
    recorder = Recorder()
    for name in named[5:]:
        recorder.add(name.capitalize(), combined[name], currency,
                     trace=ref("family.spending.category", start=start, end=end, currency=currency, category=name))
    return build(ref_text, f"The family's other categories, {start} to {end}", sum(combined[name] for name in named[5:]), currency,
                 "Every named category after the family's five largest, each added up across members.", recorder)


FAMILY_TRACES = {f"family.{name}": family_sum for name in ("spending.net", "cashflow.net", "spending.category", "spending.gross", "worth.today")}
FAMILY_TRACES["family.spending.other"] = family_other
# Figures worked out with the app's settings and tables as well as the store (finance/tax_traces.py, finance/wealth_traces.py).
CONTEXT_TRACES = {**TAX_TRACES, **WEALTH_CONTEXT_TRACES, **FAMILY_TRACES}


def build_for(store, ref_text, context=None):
    """The trace for a ref, not yet compared with how it was last shown. context: what a figure outside the ledger is
    worked out with (the app's Manager: settings, tax tables, the tax engine, the family's members); ledger figures need
    only the store. A ref with `member` runs on that family member's read-only copy."""
    name, params = parse(ref_text)
    builder, needs = TRACES.get(name), CONTEXT_TRACES.get(name)
    if builder is None and needs is None:
        raise ValueError(f"{name} can't be traced yet.")
    if (needs is not None or params.get("member")) and context is None:
        raise ValueError(f"{name} is traced only in the app.")
    if params.get("member"):
        store = next((member_store for member, member_store in family_members(context) if member["member_id"] == params["member"]), None)
        if store is None:
            raise ValueError("That family member has no shared records here.")
    if needs is not None:
        return needs(store, ref_text, params, context)
    return builder(store, ref_text, params)


def shown(store, figures, context=None):
    """Figures a page is showing (docs/ui.md "Trace contract"): each traceable one is compared with the inputs it was last
    shown or opened with, gets `stale`, and is remembered, so "changed since" works without opening its breakdown first."""
    for item in figures:
        name, _ = parse(item.get("trace") or "")
        if name in TRACES or (name in CONTEXT_TRACES and context is not None):
            item["stale"] = remember(store, build_for(store, item["trace"], context))["stale"]
    return figures


def shown_tax(store, view):
    """The Taxes page's return, with its figures' refs (tax_traces.refs); its result is remembered as shown, from this view."""
    from .tax_traces import refs, result_trace
    refs(view)
    found = view["return"].get("result_figure")
    if found:
        found["stale"] = remember(store, result_trace(found["trace"], view))["stale"]
    return view


def shown_family_tax(store, found):
    """The family's returns, each with its figures' refs (unit-<id>), and each result remembered as shown."""
    from .tax_traces import refs, result_trace
    for item in found["returns"]:
        unit = f"unit-{item['id']}"
        refs(item["view"], unit)
        shown = item["view"]["return"].get("result_figure")
        if shown:
            shown["stale"] = remember(store, result_trace(shown["trace"], item["view"], {"year": found["year"], "unit": unit}))["stale"]
    return found


def trace(store, ref_text, context=None):
    """The trace for a ref, compared with the inputs the figure was last shown with (stale)."""
    return remember(store, build_for(store, ref_text, context))
