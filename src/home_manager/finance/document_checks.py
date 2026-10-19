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
