"""Sensitive identifiers kept out of stored records (specs/document-forms FR-30, docs/documents.md "Pay stub and statement
fields"): full account, card and routing numbers, employee IDs and SSNs. Only their last four digits are kept.

The saved transcription (parse_runs, document_passages and its search index) keeps the document as printed; everything
read from it into a record goes through mask().
"""

import re

# An unbroken run of five or more digits that isn't part of an amount (12500.00, 32,500.00), a card-style group of
# three or more four-digit blocks, or an SSN (123-45-6789, XXX-XX-1234). Dates (2026-10-03) and phone numbers
# (555-123-4567) don't match.
IDENTIFIER = re.compile(r"(?<![\d.,])\d{5,}(?!\d|[.,]\d)|\d{4}(?:[ -]\d{4}){2,}|(?<![\w-])[\dX]{3}-[\dX]{2}-\d{4}(?![\w-])")


def mask(text):
    """text with every identifier replaced by asterisks and its last four digits (000123456789 -> ********6789)."""
    if not text:
        return text

    def hide(match):
        found = match.group(0)
        return "*" * (len(found) - 4) + found[-4:]
    return IDENTIFIER.sub(hide, text)


def scrub(value, keys):
    """A copy of value (a dict) with every string under the named keys masked, at any depth below them."""
    def masked(item):
        if isinstance(item, str):
            return mask(item)
        if isinstance(item, dict):
            return {key: masked(entry) for key, entry in item.items()}
        if isinstance(item, list):
            return [masked(entry) for entry in item]
        return item
    if not isinstance(value, dict):
        return value
    return {key: masked(entry) if key in keys else entry for key, entry in value.items()}


def last_four(text):
    """The last four digits of a printed account reference, or None when it has fewer than four."""
    digits = re.sub(r"\D", "", text or "")
    return digits[-4:] if len(digits) >= 4 else None
