"""The arithmetic checks document forms add (specs/document-forms FR-07 – FR-09, FR-21, FR-26, FR-28): each a function of
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
