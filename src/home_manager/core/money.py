"""Exact money: integer minor units plus ISO 4217 currency. Never binary floating point.

Parsing is deliberately strict. Ambiguous separators ("1.234,56"), a currency that
contradicts the declared one, or more precision than the currency allows are
rejected rather than guessed. The currency always comes from the caller; a "$"
sign alone never selects one.
"""

from decimal import Decimal, InvalidOperation
import re

# Minor-unit exponents (ISO 4217) for supported currencies.
EXPONENTS = {"USD": 2, "EUR": 2, "GBP": 2, "CAD": 2, "AUD": 2, "NZD": 2, "CHF": 2, "SEK": 2, "NOK": 2, "DKK": 2,
             "MXN": 2, "PHP": 2, "INR": 2, "CNY": 2, "HKD": 2, "SGD": 2, "ZAR": 2, "BRL": 2, "PLN": 2, "CZK": 2,
             "JPY": 0, "KRW": 0, "BHD": 3, "KWD": 3, "JOD": 3, "OMR": 3, "TND": 3}
SYMBOLS = {"$": {"USD", "CAD", "AUD", "NZD", "MXN", "HKD", "SGD"}, "€": {"EUR"}, "£": {"GBP"}, "¥": {"JPY", "CNY"},
           "₹": {"INR"}, "₱": {"PHP"}, "₩": {"KRW"}}
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+")


class MoneyError(ValueError):
    pass


def currency_code(value) -> str:
    code = (value or "").strip().upper()
    if code not in EXPONENTS:
        raise MoneyError("Currency must be an explicit supported ISO 4217 code.")
    return code


def to_minor(text, currency) -> int:
    """Parse a printed amount such as "-1,234.50", "(45.10)", "45.10-" or "25.00 USD"."""
    currency = currency_code(currency)
    if isinstance(text, bool) or not isinstance(text, (str, int)):
        raise MoneyError("Amounts must be text or integers, never floating point.")
    value = str(text).strip()
    negative = False
    if value.startswith("(") and value.endswith(")"):
        negative, value = True, value[1:-1].strip()
    if value.endswith("-"):
        negative, value = not negative, value[:-1].strip()
    if value[:1] in ("+", "-"):
        negative, value = negative != (value[0] == "-"), value[1:].strip()
    code = re.fullmatch(r"(.*?)\s*([A-Za-z]{3})", value)
    if code:
        if code.group(2).upper() != currency:
            raise MoneyError("The printed currency differs from the declared currency.")
        value = code.group(1).strip()
    for symbol, currencies in SYMBOLS.items():
        if value.startswith(symbol):
            if currency not in currencies:
                raise MoneyError("The printed currency symbol differs from the declared currency.")
            value = value[len(symbol):].strip()
    if value[:1] in ("+", "-"):
        negative, value = negative != (value[0] == "-"), value[1:].strip()
    if not NUMBER.fullmatch(value):
        raise MoneyError("Amount is not an unambiguous number (use digits, optional thousands commas and a decimal point).")
    try:
        amount = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise MoneyError("Amount is not a valid number.") from exc
    scaled = amount.scaleb(EXPONENTS[currency])
    if scaled != scaled.to_integral_value():
        raise MoneyError(f"Amount has more precision than {currency} allows.")
    minor = int(scaled)
    return -minor if negative else minor


def decimals_in(text) -> set[Decimal]:
    """Every number printed in a source line, as an exact absolute Decimal (currency-independent)."""
    return {Decimal(match.group(0).replace(",", "")) for match in NUMBER.finditer(text or "")}


def printed_decimal(value):
    """The single number in a proposed amount such as "-1,234.50" or "$19.99", else None."""
    matches = NUMBER.findall(value or "")
    return Decimal(matches[0].replace(",", "")) if len(matches) == 1 else None


def as_decimal_text(amount: int, currency) -> str:
    """Exact machine-readable decimal string, e.g. "-45.10" (Decimal formatting never rounds here)."""
    exponent = EXPONENTS[currency_code(currency)]
    return f"{Decimal(amount).scaleb(-exponent):.{exponent}f}"


def format_minor(amount: int, currency) -> str:
    exponent = EXPONENTS[currency_code(currency)]
    return f"{Decimal(amount).scaleb(-exponent):,.{exponent}f} {currency_code(currency)}"


def money(amount: int, currency) -> dict:
    """The exact views of one amount that callers may show: minor units, decimal text and display text."""
    return {"minor": amount, "currency": currency, "decimal": as_decimal_text(amount, currency), "display": format_minor(amount, currency)}
