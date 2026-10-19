"""Identifiers are masked to their last four digits; dates, phone numbers and amounts pass through (FR-30)."""

import pytest

from document_forms_fixtures import IDENTIFIERS, P_EXTRAS
from home_manager.core.identifiers import last_four, mask, scrub


@pytest.mark.parametrize("text", ["2026-10-03", "555-123-4567", "32,500.00", "12500.00", "TOTAL 8.55", "PAY DATE 2026-07-03", "VISA ****4242",
                                  "Regular 80.00 h @ 31.25", "STORE 1234", "401(k) 650.00", "-1,200.50"])
def test_dates_phones_and_amounts_pass_through(text):
    assert mask(text) == text


@pytest.mark.parametrize("text,masked", [("ACCOUNT 000123456789", "ACCOUNT ********6789"), ("ROUTING 021000021", "ROUTING *****0021"),
                                         ("EMPLOYEE ID 445566", "EMPLOYEE ID **5566"),
                                         ("GIFT CARD 6006491234565555 -5.00", "GIFT CARD ************5555 -5.00"),
                                         ("CARD 4111 1111 1111 1234", "CARD ***************1234"), ("SSN XXX-XX-1234", "SSN *******1234"),
                                         ("SSN 123-45-6789", "SSN *******6789")])
def test_identifiers_keep_their_last_four_digits(text, masked):
    assert mask(text) == masked
    assert mask(masked) == masked  # Masking twice changes nothing, so a stored quote still compares with its masked line.


def test_no_fixture_identifier_survives_masking():
    lines = [*P_EXTRAS, "EVERYDAY CHECKING ACCOUNT 000123456789", "ROUTING 021000021", "GIFT CARD 6006491234565555 -5.00"]
    assert not any(identifier in mask(line) for line in lines for identifier in IDENTIFIERS)


def test_scrub_masks_only_the_named_keys():
    value = {"account_reference": {"value": "000123456789", "evidence": [{"line_id": "line-2", "quote": "ACCOUNT 000123456789"}]},
             "merchant": {"value": "STORE 123456"}}
    scrubbed = scrub(value, {"account_reference"})
    assert scrubbed["account_reference"]["value"] == "********6789" and scrubbed["account_reference"]["evidence"][0]["quote"] == "ACCOUNT ********6789"
    assert scrubbed["merchant"] == {"value": "STORE 123456"} and value["account_reference"]["value"] == "000123456789"


def test_last_four():
    assert (last_four("****1234"), last_four("000123456789"), last_four("12"), last_four(None)) == ("1234", "6789", None, None)
