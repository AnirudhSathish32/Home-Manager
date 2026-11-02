"""A receipt's money divided by item category (docs/money.md, "Item categories and splits").

One receipt can hold several kinds of spending: a hot dog, a mattress and groceries on one Costco
receipt. Each item carries its own category, and the amount actually paid is shared out so the
categories add up exactly to it:

1. An item's own amount is its line total less any discount printed on it.
2. An order-wide discount (the printed subtotal differing from the items) is shared by item amount.
3. Tax is shared by amount across the items the receipt marks as taxed, or across every item
   when none are marked. A receipt that printed a tax line per tax code shares each line's amount across the
   items carrying that code (tax_parts).
4. A tip is dining.
5. A difference between the receipt and what was charged (a tip added after signing) is dining for a
   dining receipt, otherwise shared by amount.

Shares are exact fractions until the end; largest-remainder rounding keeps the sum exact.
"""

from decimal import Decimal
from fractions import Fraction
import math
from typing import NamedTuple

from ..core.money import format_minor
from ..core.trace import NULL

DINING = "dining"


def share(amount, weights):
    """Exact shares of amount in proportion to weights, or None when the weights give no proportion."""
    total = sum(weights)
    if total == 0:
        return None
    return [Fraction(amount) * weight / total for weight in weights]


def rounded(values, target):
    """Whole units summing exactly to target (the exact sum of values): floor each, then give the rest to the largest remainders."""
    floors = [math.floor(value) for value in values]
    order = sorted(range(len(values)), key=lambda index: (floors[index] - values[index], index))
    for index in order[:target - sum(floors)]:
        floors[index] += 1
    return floors


def item_amount(item):
    """The line less its discount; a returned (negative) line's discount makes the refund smaller."""
    total = item.get("line_total_minor") or 0
    discount = abs(item.get("discount_minor") or 0)
    return total + discount if total < 0 else total - discount


def tax_basis(items):
    """What each item weighs when the receipt's tax is shared: its amount where the receipt marks it taxed, or every item's
    amount when no taxed item has one (the rule allocate() spreads tax by, and the rule behind an item's "with tax" note)."""
    base = [item_amount(item) for item in items]
    taxed = [value if item.get("taxed") else 0 for item, value in zip(items, base)]
    return taxed if sum(taxed) else base


class TaxPlan(NamedTuple):
    """How a receipt's tax is shared. parts: [(amount, weights, tax code or None)], each amount spread over its weights.
    by_code: each part is one printed tax line's. issues: what to tell the reader. codes: {item index: the tax line code the item belongs to}."""
    parts: list
    by_code: bool
    issues: list
    codes: dict

    def included(self, index):
        """Whether item index holds part of the tax: some part with an amount gives it weight, within weights that add up to something."""
        return any(amount and sum(weights) != 0 and weights[index] != 0 for amount, weights, _ in self.parts)


def printed_code(text):
    """A tax code as compared: no spaces, upper case ("" when none)."""
    return "".join((text or "").split()).upper()


def tax_parts(items, tax, tax_lines, source, currency=None):
    """The TaxPlan for a receipt's tax (docs/money.md "Item categories and splits"). items: dicts as allocate() takes, with
    tax_code. tax_lines: [(code, amount magnitude or None)] in printed order. source: the receipt's tax_source.
    Without per-code tax lines it is today's rule (tax_basis), except that a receipt read with neither tax lines nor a legend
    spreads tax over every item when any item's taxed answer is empty."""
    if source == "tax_lines" and tax_lines:
        plan = by_tax_line(items, tax or 0, tax_lines, currency)
        if plan is not None:
            return plan
    if not tax:
        return TaxPlan([], False, [], {})
    if source == "printed" and any(item.get("taxed") is None for item in items):
        return TaxPlan([(tax, [item_amount(item) for item in items], None)], False, [], {})
    return TaxPlan([(tax, tax_basis(items), None)], False, [], {})


def by_tax_line(items, tax, tax_lines, currency):
    """tax_parts() for a receipt with per-code tax lines: one part per code when the lines add up to the tax and every code has
    items to carry it, else tax_basis over the items' stored taxed flags and the reason. None when no line has a code. A tax of
    zero has nothing to share, so it gets no parts, but lines that don't add up to it are still named."""
    amounts = {}  # code -> summed amount, or None when a line of that code couldn't be read.
    for code, amount in tax_lines:
        code = printed_code(code)
        if code:
            before = amounts.get(code, 0)
            amounts[code] = None if before is None or amount is None else before + amount
    if not amounts:
        return None
    members, codes, issues = {code: [] for code in amounts}, {}, []
    for index, item in enumerate(items):
        code = printed_code(item.get("tax_code"))
        name = item.get("description") or f"Item {index + 1}"
        found = sorted(line for line in amounts if line in code) if code else []
        if len(found) == 1:
            members[found[0]].append(index)
            codes[index] = found[0]
        elif found:
            issues.append(f"{name} carries more than one tax line's code ({', '.join(found)}), so it got no share of either.")
        elif code:
            issues.append(f"{name}'s tax code {code} matches no tax line, so it got no tax line's share.")
    weights = {code: [item_amount(item) if index in members[code] else 0 for index, item in enumerate(items)] for code in amounts}
    text = lambda amount: format_minor(amount, currency) if currency else f"{Decimal(amount).scaleb(-2):,.2f}"
    reasons = [f"The {code} tax line's amount couldn't be read, so tax was shared across the taxed items." for code, amount in amounts.items() if amount is None]
    if not reasons and sum(amounts.values()) != abs(tax):
        reasons.append(f"The tax lines ({text(sum(amounts.values()))}) don't add up to the tax ({text(abs(tax))}), so tax was shared across the taxed items.")
    reasons += [f"The {code} tax line has no items carrying its code, so tax was shared across the taxed items." for code in amounts if not members[code]]
    reasons += [f"The {code} tax line's items add up to nothing, so tax was shared across the taxed items."
                for code, amount in amounts.items() if amount and members[code] and sum(weights[code]) == 0]
    if reasons or not tax:
        return TaxPlan([(tax, tax_basis(items), None)] if tax else [], False, [*issues, *reasons], {})
    sign = -1 if tax < 0 else 1
    return TaxPlan([(sign * amount, weights[code], code) for code, amount in amounts.items()], True, issues, codes)


def record(recorder, values, target, labels, currency):
    """A live recorder (core/trace.py) gets each share rounded down, and the cents largest-remainder rounding handed out
    as the rounding row, so the steps add up to target."""
    if not recorder.live:
        return
    floors = [math.floor(value) for value in values]
    for label, floor in zip(labels, floors):
        recorder.add(label, floor, currency)
    recorder.round(target - sum(floors), currency, method="largest_remainder",
                   note="Each share is exact until the end, then rounded down; the cents left go one each to the largest remainders.")


def allocate(items, subtotal, tax, tip, target, fallback, recorder=NULL, currency=None, tax_parts=None):
    """[(item index or None, category, minor units)] summing to target.
    items: dicts with line_total_minor, discount_minor, taxed and category (None falls back to fallback), and a
    description for a live recorder's step labels. tax_parts: a TaxPlan's parts, each spread over its own weights; None
    spreads tax over tax_basis(items)."""
    fallback = fallback or "uncategorized"
    amounts = [Fraction(item_amount(item)) for item in items]
    extra = []  # (category, amount) that no item carries.

    def spread(amount, weights, category=None):
        if not amount:
            return
        parts = share(amount, weights)
        if parts is None:
            extra.append((category or fallback, Fraction(amount)))
            return
        for index, part in enumerate(parts):
            amounts[index] += part

    base = [item_amount(item) for item in items]
    if subtotal is not None:
        spread(subtotal - sum(base), base)
    if tax_parts is not None:
        for amount, weights, _ in tax_parts:
            spread(amount, weights)
    elif tax:
        spread(tax, tax_basis(items))
    if tip:
        extra.append((DINING, Fraction(tip)))
    difference = target - sum(amounts) - sum(amount for _, amount in extra)
    if difference > 0 and fallback == DINING:
        extra.append((DINING, difference))
    else:
        spread(difference, [max(amount, 0) for amount in amounts] if any(amount > 0 for amount in amounts) else amounts)
    values = [*amounts, *(amount for _, amount in extra)]
    whole = rounded(values, target)
    rows = [(index, item.get("category") or fallback, whole[index]) for index, item in enumerate(items)]
    rows += [(None, category, whole[len(items) + index]) for index, (category, _) in enumerate(extra)]
    if recorder.live:
        record(recorder, values, target, [label(items, index, category) for index, category, _ in rows], currency)
    return rows


def label(items, index, category):
    """A share's step label: the item and its category, or the category of an amount no item carries (a tip)."""
    if index is None:
        return f"{category.capitalize()}: an amount no item carries"
    return f"{items[index].get('description') or 'Item ' + str(index + 1)} · {category}"


def scale(rows, target, recorder=NULL, items=(), currency=None):
    """allocate()'s rows resized to sum exactly to target, each keeping its proportion (a person's part of a shared receipt)."""
    total = sum(amount for _, _, amount in rows)
    if not total:
        return [(index, category, int(amount)) for index, category, amount in rows]
    values = [Fraction(amount) * target / total for _, _, amount in rows]
    whole = rounded(values, target)
    if recorder.live:
        record(recorder, values, target, [label(items, index, category) for index, category, _ in rows], currency)
    return [(index, category, amount) for (index, category, _), amount in zip(rows, whole)]


def line_shares(items, total):
    """{member id: minor units} for a bill shared by line (docs/family.md "Sharing a bill by line"), adding up exactly to
    total: each person's own lines, plus a part of everything no line names anyone on (taxes, fees, other lines, amounts
    no line carries) in proportion to their own lines. Empty when no line names anyone, or their lines add up to nothing."""
    tagged: dict = {}
    for item in items:
        if item.get("member_id"):
            tagged[item["member_id"]] = tagged.get(item["member_id"], 0) + item_amount(item)
    base = sum(tagged.values())
    if not tagged or base <= 0 or any(amount < 0 for amount in tagged.values()):
        return {}
    people = list(tagged)
    values = [Fraction(tagged[person]) + Fraction(total - base) * tagged[person] / base for person in people]
    return dict(zip(people, rounded(values, total)))


def by_line(rows, items, member_id):
    """allocate()'s rows cut down to one person's part of a bill shared by line: their own lines' shares, and each share
    no one is named on in proportion to their own lines. Exact fractions; scale() rounds them to the person's part."""
    owner = lambda index: None if index is None else items[index].get("member_id")
    tagged: dict = {}
    for index, _, amount in rows:
        if owner(index):
            tagged[owner(index)] = tagged.get(owner(index), 0) + amount
    base, mine = sum(tagged.values()), tagged.get(member_id, 0)
    found = []
    for index, category, amount in rows:
        if owner(index) == member_id:
            found.append((index, category, Fraction(amount)))
        elif owner(index) is None and base:
            found.append((index, category, Fraction(amount) * mine / base))
    return found or [(None, "uncategorized", Fraction(0))]


def equal_shares(total, count):
    """total divided into count whole parts that add up exactly: the first parts get the extra units (50.00 / 3 = 16.67, 16.67, 16.66)."""
    if count < 1:
        raise ValueError("Choose at least one person to share it.")
    base, extra = divmod(abs(total), count)
    sign = -1 if total < 0 else 1
    return [sign * (base + (1 if index < extra else 0)) for index in range(count)]


def by_category(rows):
    """{category: minor units} from allocate()'s rows."""
    totals = {}
    for _, category, amount in rows:
        totals[category] = totals.get(category, 0) + amount
    return totals
