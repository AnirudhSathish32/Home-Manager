"""A receipt's money divided by item category (docs/money.md, "Item categories and splits").

One receipt can hold several kinds of spending: a hot dog, a mattress and groceries on one Costco
receipt. Each item carries its own category, and the amount actually paid is shared out so the
categories add up exactly to it:

1. An item's own amount is its line total less any discount printed on it.
2. An order-wide discount (the printed subtotal differing from the items) is shared by item amount.
3. Tax is shared by amount across the items the receipt marks as taxed, or across every item
   when none are marked.
4. A tip is dining.
5. A difference between the receipt and what was charged (a tip added after signing) is dining for a
   dining receipt, otherwise shared by amount.

Shares are exact fractions until the end; largest-remainder rounding keeps the sum exact.
"""

from fractions import Fraction
import math

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


def allocate(items, subtotal, tax, tip, target, fallback, recorder=NULL, currency=None):
    """[(item index or None, category, minor units)] summing to target.
    items: dicts with line_total_minor, discount_minor, taxed and category (None falls back to fallback), and a
    description for a live recorder's step labels."""
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
    if tax:
        taxed = [value if item.get("taxed") else 0 for item, value in zip(items, base)]
        spread(tax, taxed if sum(taxed) else base)
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
