"""Required minimum distributions (docs/planning.md "Investments"): deterministic and exact.

The divisor is the Uniform Lifetime Table in 26 CFR 1.401(a)(9)-9(c), Table 2 (distribution calendar years from 2022; the
same table as IRS Publication 590-B, Appendix B, Table III), checked row by row against the regulation on 2026-09-28.
The year's required amount is the account's balance at the end of the year before, divided by the divisor for the age
reached that year. Distributions begin the year a person reaches 72 (born 1950 or earlier), 73 (born 1951 to 1959) or 75
(born 1960 or later), under SECURE 2.0. The first one may wait until April 1 of the next year.

Only tax-deferred accounts have them (a Roth account and an HSA have none), decided by tax treatment, never by kind.
Not modelled: the still-working exception for a current employer's plan, inherited accounts, and the joint table for a
spouse more than ten years younger.
"""

from decimal import ROUND_HALF_EVEN, Decimal

UNIFORM_LIFETIME = {age: Decimal(period) for age, period in {
    72: "27.4", 73: "26.5", 74: "25.5", 75: "24.6", 76: "23.7", 77: "22.9", 78: "22.0", 79: "21.1", 80: "20.2", 81: "19.4",
    82: "18.5", 83: "17.7", 84: "16.8", 85: "16.0", 86: "15.2", 87: "14.4", 88: "13.7", 89: "12.9", 90: "12.2", 91: "11.5",
    92: "10.8", 93: "10.1", 94: "9.5", 95: "8.9", 96: "8.4", 97: "7.8", 98: "7.3", 99: "6.8", 100: "6.4", 101: "6.0",
    102: "5.6", 103: "5.2", 104: "4.9", 105: "4.6", 106: "4.3", 107: "4.1", 108: "3.9", 109: "3.7", 110: "3.5", 111: "3.4",
    112: "3.3", 113: "3.1", 114: "3.0", 115: "2.9", 116: "2.8", 117: "2.7", 118: "2.5", 119: "2.3", 120: "2.0"}.items()}
HAS_RMD = ("tax_deferred",)  # Tax treatments whose accounts have required distributions.


def rmd_start_age(birth_year):
    return 72 if birth_year <= 1950 else 73 if birth_year <= 1959 else 75


def divisor(age):
    """The distribution period for an age reached in the year (120 and over share the last row); None below the table."""
    return UNIFORM_LIFETIME[min(age, 120)] if age >= 72 else None


def required(balance_minor, birth_year, year):
    """The year's minimum distribution from one account's balance at the end of the year before, rounded half-even to the minor
    unit; 0 before distributions begin."""
    age = year - birth_year
    if age < rmd_start_age(birth_year) or balance_minor <= 0:
        return 0
    return int((Decimal(balance_minor) / divisor(age)).to_integral_value(ROUND_HALF_EVEN))
