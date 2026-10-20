"""The arithmetic checks document forms add (specs/document-forms FR-07 – FR-09, FR-21, FR-26, FR-28; specs/bill-kinds
FR-49): each a function of
printed values, run with the NULL recorder when a document is read (documents/extraction.py normalize) and with a live
one for its trace (finance/document_traces.py), so the page's figure and its trace are the same calculation.

Each returns (computed_minor, compared_minor, passes). Products of printed decimals (hours × rate, volume × price,
count × unit price) round half-up to the minor unit and pass within one minor unit; sums must be exact.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..core.money import EXPONENTS, NUMBER
from ..core.trace import NULL

TOLERANCE = 1  # Minor units a rounded product may differ from its printed amount.


def decimal(text):
    """A printed decimal ("80.00", "3.459", "1,500.00") as an exact Decimal, or None when it isn't one number."""
    numbers = NUMBER.findall(text or "")
    if len(numbers) != 1:
        return None
    try:
        return Decimal(numbers[0].replace(",", ""))
    except InvalidOperation:
        return None


def product(first_text, second_text, compared_minor, currency, label, recorder=NULL):
    """first × second (printed decimals, the second a price per unit in currency), rounded half-up to the minor unit,
    against the printed amount. None when either isn't a printed number."""
    first, second = decimal(first_text), decimal(second_text)
    if first is None or second is None or currency not in EXPONENTS:
        return None
    exact = first * second
    computed = int((exact * (Decimal(10) ** EXPONENTS[currency])).quantize(Decimal(1), ROUND_HALF_UP))
    recorder.step(label, "+" if computed >= 0 else "−", abs(computed), currency)
    recorder.round(0, currency, method="half_up_minor", note=f"{first_text} × {second_text} = {exact}")
    return computed, compared_minor, compared_minor is not None and abs(computed - compared_minor) <= TOLERANCE


def fuel(volume_text, price_text, amount_minor, currency, recorder=NULL):
    """A fuel receipt's volume × price per unit against its fuel amount (FR-07)."""
    return product(volume_text, price_text, amount_minor, currency, f"{volume_text} × {price_text}", recorder)


def unit_line(count_text, unit_price_text, line_minor, currency, recorder=NULL):
    """A line sold as several units: its printed count × unit price against its line total (FR-09)."""
    return product(count_text, unit_price_text, line_minor, currency, f"{count_text} × {unit_price_text}", recorder)


def dining(subtotal, tax, tip, gratuity, total, currency, recorder=NULL):
    """A dining receipt's subtotal + tax + tip + included gratuity against its total (FR-08): an included gratuity is part
    of the sum, never on top of it, and an unprinted tip adds nothing (it isn't 0). None unless subtotal, tax and total
    are printed."""
    if None in (subtotal, tax, total):
        return None
    recorder.add("Subtotal", subtotal, currency)
    recorder.add("Tax", tax, currency)
    for label, amount in (("Gratuity", gratuity), ("Tip", tip)):
        if amount is None:
            recorder.step(f"{label} (not printed)", "+", 0, currency, missing=True)
        else:
            recorder.add(label, amount, currency)
    computed = subtotal + tax + (tip or 0) + (gratuity or 0)
    return computed, total, computed == total


def amount_paid(printed, gifts, other_tenders, currency, recorder=NULL):
    """What a receipt paid partly by gift card counts (FR-09, D15): its printed total less its gift-card deductions.
    Compared with the other printed tenders' sum when there is one; with none, it passes exactly when the deductions
    don't exceed the printed total. None without a printed total or a gift card."""
    if printed is None or not gifts:
        return None
    recorder.step("Total", "+", abs(printed), currency)
    for number, gift in enumerate(gifts, 1):
        recorder.step("Gift card" + (f" {number}" if len(gifts) > 1 else ""), "−", abs(gift), currency)
    computed = abs(printed) - sum(abs(gift) for gift in gifts)
    passes = computed == other_tenders if other_tenders is not None else computed >= 0
    return computed, other_tenders, passes


def hours_rate(hours_text, rate_text, amount_minor, currency, recorder=NULL):
    """A pay line's hours × rate against its this-period amount (FR-21)."""
    return product(hours_text, rate_text, amount_minor, currency, f"{hours_text} hours × {rate_text}", recorder)


def deposit_splits(amounts_minor, net_minor, currency, recorder=NULL):
    """The direct-deposit splits' sum against net pay (FR-21). None unless every split has an amount."""
    if not amounts_minor or any(amount is None for amount in amounts_minor):
        return None
    for number, amount in enumerate(amounts_minor, 1):
        recorder.add(f"Deposit {number}", amount, currency)
    computed = sum(amounts_minor)
    return computed, net_minor, net_minor is not None and computed == net_minor


def bank_summary(opening, deposits, withdrawals, closing, currency, recorder=NULL):
    """A bank statement's printed summary against itself (FR-26): opening + deposits − withdrawals = closing. Totals
    count by magnitude, whatever sign was printed. None unless all four are printed."""
    if None in (opening, deposits, withdrawals, closing):
        return None
    recorder.add("Opening balance", opening, currency)
    recorder.step("Deposits", "+", abs(deposits), currency)
    recorder.step("Withdrawals", "−", abs(withdrawals), currency)
    computed = opening + abs(deposits) - abs(withdrawals)
    return computed, closing, computed == closing


def bill_lines(lines, compared_minor, currency, recorder=NULL):
    """A bill's charge lines added up (specs/bill-kinds FR-49), against its printed new charges, or its amount due when
    no new charges are printed. lines: (label, signed minor) pairs, a credit negative. None without lines, or when a
    line has no amount."""
    if not lines or any(minor is None for _, minor in lines):
        return None
    for label, minor in lines:
        recorder.add(label, minor, currency)
    computed = sum(minor for _, minor in lines)
    return computed, compared_minor, compared_minor is not None and computed == compared_minor


def bill_carried(previous, payments, new, due, currency, recorder=NULL):
    """A bill's carried amounts against its amount due (FR-49): previous balance − payments + new charges = amount due.
    Payments count by magnitude. A printed 0.00 counts as printed; None unless all four are."""
    if None in (previous, payments, new, due):
        return None
    recorder.add("Previous balance", previous, currency)
    recorder.step("Payments", "−", abs(payments), currency)
    recorder.add("New charges", new, currency)
    computed = previous - abs(payments) + new
    return computed, due, computed == due


CARD_TERMS = (("Payments", "−"), ("Credits", "−"), ("Purchases", "+"), ("Fees", "+"), ("Interest", "+"))


def card_summary(previous, payments, credits, purchases, fees, interest, balance, currency, recorder=NULL):
    """A card statement's printed summary against itself (FR-28): previous − payments − credits + purchases + fees +
    interest = statement balance, by magnitude. A printed 0.00 counts as printed; None unless all are."""
    if None in (previous, payments, credits, purchases, fees, interest, balance):
        return None
    recorder.add("Previous balance", previous, currency)
    computed = previous
    for (label, op), amount in zip(CARD_TERMS, (payments, credits, purchases, fees, interest)):
        recorder.step(label, op, abs(amount), currency)
        computed += abs(amount) if op == "+" else -abs(amount)
    return computed, balance, computed == balance
