"""The tax profile (docs/taxes.md "The tax engines") and a simplified state return.

ReturnInput is what every tax engine works from (finance/tax_engine.py): whole-year amounts in cents, gathered from
records by tax_year.py and adjusted by the user. The federal return itself is worked out by the tax engine; the state
return here is simplified and labeled so, for states the engine has no return for. Exact integer and Decimal arithmetic,
rounded half-even to the cent.
"""

from decimal import ROUND_HALF_EVEN, Decimal
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.money import format_minor

CURRENCY = "USD"
# The Treasury Tipped Occupation list (Treas. Reg. §1.224-1): qualified tips are deductible only in these ("other": none).
TIPPED_OCCUPATIONS = (
    "bartenders", "wait-staff", "food-servers-nonrestaurant", "dining-room-and-cafeteria-attendants-and-bartender-helpers", "chefs-and-cooks",
    "food-preparation-workers", "fast-food-and-counter-workers", "dishwashers", "host-staff-restaurant-lounge-and-coffee-shop", "bakers",
    "gambling-dealers", "gambling-change-persons-and-booth-cashiers", "gambling-cage-workers", "gambling-and-sports-book-writers-and-runners",
    "dancers", "musicians-and-singers", "disc-jockeys-except-radio", "entertainers-and-performers", "digital-content-creators",
    "ushers-lobby-attendants-and-ticket-takers", "locker-room-coatroom-and-dressing-room-attendants", "baggage-porters-and-bellhops", "concierges",
    "hotel-motel-and-resort-desk-clerks", "maids-and-housekeeping-cleaners", "home-maintenance-and-repair-workers",
    "home-landscaping-and-groundskeeping-workers", "home-electricians", "home-plumbers", "home-heating-and-air-conditioning-mechanics-and-installers",
    "home-appliance-installers-and-repairers", "home-cleaning-service-workers", "locksmiths", "roadside-assistance-workers",
    "personal-care-and-service-workers", "private-event-planners", "private-event-and-portrait-photographers", "private-event-videographers",
    "event-officiants", "pet-caretakers", "tutors", "nannies-and-babysitters", "visual-artists", "floral-designers", "skincare-specialists",
    "massage-therapists", "barbers-hairdressers-hairstylists-and-cosmetologists", "shampooers", "manicurists-and-pedicurists", "makeup-artists",
    "exercise-trainers-and-group-fitness-instructors", "tattoo-artists-and-piercers", "tailors", "shoe-and-leather-workers-and-repairers",
    "eyebrow-threading-and-waxing-technicians", "golf-caddies", "self-enrichment-teachers", "sports-and-recreation-instructors", "tour-guides",
    "travel-guides", "recreational-and-tour-pilots", "parking-and-valet-attendants", "taxi-and-rideshare-drivers-and-chauffeurs", "shuttle-drivers",
    "goods-delivery-people", "personal-vehicle-and-equipment-cleaners", "private-and-charter-bus-drivers",
    "water-taxi-operators-and-charter-boat-workers", "rickshaw-pedicab-and-carriage-drivers", "home-movers", "gas-pump-attendants", "other")


def cents(value):
    return int(Decimal(value).to_integral_value(ROUND_HALF_EVEN))


def rate(amount, basis_points):
    return cents(Decimal(amount) * basis_points / 10000)


def bracket_tax(amount, brackets):
    """Exact tax on taxable income over the brackets (starts in cents over taxable income, rates in basis points)."""
    tax = Decimal(0)
    for index, bracket in enumerate(brackets):
        end = brackets[index + 1]["from_minor"] if index + 1 < len(brackets) else None
        piece = max(0, (min(amount, end) if end is not None else amount) - bracket["from_minor"])
        tax += Decimal(piece) * bracket["rate_bp"] / 10000
    return tax


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    owner: str = ""
    wages: int = 0  # W-2 box 1: pay less pre-tax deductions.
    ss_wages: int = 0
    medicare_wages: int = 0
    federal_withheld: int = 0
    state_withheld: int = 0
    medicare_withheld: int = 0


class Business(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    owner: str = ""
    income: int = 0
    expenses: int = 0  # The part that counts (meals at 50%).


class Student(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expenses: int = 0
    aotc: bool = True  # One of the first four years of college, at least half-time.


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    birth_year: int | None = None


class ReturnInput(BaseModel):
    """The tax profile every tax engine works from (finance/tax_engine.py). A new field needs a mapping in each engine
    (docs/taxes.md "The tax engines"); a field an engine can't use is a FEATURE it names, never dropped."""
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 2
    year: int
    filing_status: str
    people: list[Person] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    interest: int = 0
    us_obligation_interest: int = 0  # The part of interest from I bonds and Treasuries: federal-taxable, state-exempt.
    tax_exempt_interest: int = 0
    ordinary_dividends: int = 0  # 1099-DIV box 1a, qualified ones included.
    qualified_dividends: int = 0
    short_term_gain: int = 0  # Net; negative for a loss.
    long_term_gain: int = 0
    capital_loss_carryover: int = 0  # From last year, as a positive number.
    retirement_distributions: int = 0  # Taxable part.
    early_distributions: int = 0  # The part taken before 59½ with no exception.
    hsa_nonqualified: int = 0
    social_security_benefits: int = 0
    unemployment: int = 0
    other_income: int = 0
    businesses: list[Business] = Field(default_factory=list)
    educator_expenses: int = 0
    hsa_contributions: int = 0
    hsa_coverage: Literal["self", "family"] | None = None  # The HDHP coverage, for the HSA limit.
    se_health_insurance: int = 0
    ira_deduction: int = 0
    student_loan_interest: int = 0
    other_adjustments: int = 0
    medical: int = 0
    state_local_tax: int = 0
    property_tax: int = 0
    mortgage_interest: int = 0
    mortgage_average_balance: int | None = None  # Acquisition debt, Pub 936; the interest is limited above $750,000.
    charity: int = 0  # Cash.
    charity_noncash: int = 0  # Goods.
    other_itemized: int = 0
    itemize: bool | None = None  # None: whichever is larger; True: itemize anyway.
    qualified_tips: int = 0  # Below the line (IRC §224, 2025–2028).
    tipped_occupation: str | None = None  # One of TIPPED_OCCUPATIONS; needed with qualified tips.
    qualified_overtime: int = 0  # The premium part of overtime pay (IRC §225, 2025–2028).
    qualifying_children: int = 0
    other_dependents: int = 0
    dependent_care_expenses: int = 0
    dependent_care_people: int = 0
    students: list[Student] = Field(default_factory=list)
    energy_home_expenses: int = 0
    other_credits: int = 0
    other_refundable_credits: int = 0
    other_federal_withholding: int = 0  # 1099 box 4 and the like.
    federal_estimated_paid: int = 0
    state: str | None = None
    state_deduction: int | None = None
    state_credits: int = 0
    state_estimated_paid: int = 0


def marginal(taxable, brackets):
    """The ordinary rate on the next dollar of taxable income."""
    found = brackets[0]["rate_bp"]
    for bracket in brackets:
        if taxable >= bracket["from_minor"]:
            found = bracket["rate_bp"]
    return found


def state_return(value: ReturnInput, agi, table):
    """A simplified state return: AGI less the state's deduction, the state's brackets, less its credits, against state
    withholding and estimated payments. State rules differ from federal in many ways; this is labelled simplified."""
    withheld = sum(job.state_withheld for job in value.jobs)
    if not value.state:
        return None
    if table is None or table.get("status") != "verified":
        return {"state": value.state, "complete": False, "withheld_minor": withheld, "note": "The state's tax table isn't confirmed, so its return isn't estimated."}
    deduction = value.state_deduction if value.state_deduction is not None else table["standard_deduction_minor"]
    taxable = max(0, agi - min(value.us_obligation_interest, value.interest) - deduction)  # States can't tax US savings bond or Treasury interest.
    tax = max(0, cents(bracket_tax(taxable, json.loads(table["brackets_json"]))) - value.state_credits)
    paid = withheld + value.state_estimated_paid
    return {"state": value.state, "complete": True, "taxable_minor": taxable, "tax_minor": tax, "withheld_minor": withheld, "estimated_minor": value.state_estimated_paid,
            "payments_minor": paid, "result_minor": paid - tax,
            "display": {key: format_minor(amount, CURRENCY) for key, amount in (("taxable_minor", taxable), ("tax_minor", tax), ("payments_minor", paid),
                                                                                  ("result_minor", abs(paid - tax)))},
            "note": "Simplified: federal AGI less I bond and Treasury interest and the state's deduction, on the state's brackets, less the credits you entered."}
