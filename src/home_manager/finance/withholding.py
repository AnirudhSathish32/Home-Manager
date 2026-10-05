"""Withholding engines (docs/taxes.md "Design"): what payroll withholds from a paycheck for a W-4,
behind one interface, so a different method can replace IRS Publication 15-T without changing Tax Zen.

- WithholdingEngine: per_check(federal table, wages a paycheck, paychecks a year, W-4 entries) -> cents.
- Pub15T: the annual percentage method for 2020+ W-4s (Step 2's half-size schedule, Step 3 credits, 4(a) other income,
  4(b) deductions, 4(c) extra), from the confirmed federal tax table.
- PayrollProjection: when the next paycheck comes and how many are left once a new W-4 takes effect. An employer must
  put a new W-4 into effect by the first payroll period ending on or after the 30th day after it's handed in (Pub 15,
  section 9), so by default one paycheck passes before it counts.
- W4Recommendation: one W-4 answer, as Tax Zen gives it (§18–20).
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol

from ..core.trace import NULL
from .paycheck import step2_table
from .paystub import income_tax

W4_DELAY_CHECKS = 1  # Paychecks that pass before a new W-4 changes withholding (Pub 15, section 9).


class WithholdingEngine(Protocol):
    name: str

    def per_check(self, federal, wages, checks, w4, recorder=NULL) -> int: ...


class Pub15T:
    """IRS Publication 15-T, annual percentage method (finance/paystub.income_tax), for a 2020 or later W-4."""
    name = "pub15t"

    def per_check(self, federal, wages, checks, w4, recorder=NULL):
        """A live recorder gets the tax a paycheck bucket by bucket (paystub.income_tax) and the Step 4(c) extra."""
        table = step2_table(federal) if w4.get("step2") else federal
        part = income_tax("US", table, wages, checks, None, w4.get("other_income", 0), w4.get("deductions", 0), w4.get("credits", 0), recorder)
        if w4.get("extra"):
            recorder.add("Extra withholding a paycheck (W-4 Step 4(c))", w4["extra"], "USD")
        return part["estimate_minor"] + w4.get("extra", 0)


ENGINE: WithholdingEngine = Pub15T()


@dataclass(frozen=True)
class PayrollProjection:
    next_pay_date: str | None  # The next payday after today, or None when none is left this year.
    paychecks_left: int  # Paydays still ahead this year.
    delay_checks: int  # Of those, how many pass before a new W-4 takes effect.

    @property
    def paychecks_changed(self):
        """Paychecks a new W-4 handed in today changes."""
        return max(0, self.paychecks_left - self.delay_checks)

    def as_dict(self):
        return {**asdict(self), "paychecks_changed": self.paychecks_changed}


def projection(job, today: date, delay_checks=W4_DELAY_CHECKS):
    """The payroll projection for a gathered job (finance/tax_year.jobs)."""
    return PayrollProjection(job.get("next_pay_date"), job["paychecks_left"], min(delay_checks, job["paychecks_left"]))


@dataclass
class W4Recommendation:
    job_key: str
    field: str | None  # "4(a)", "4(b)", "4(c)", "3", or None when no change is needed.
    amount_minor: int | None  # The box's new total (a year for 3, 4(a) and 4(b); a paycheck for 4(c)).
    per_check_minor: int  # Each changed paycheck's federal withholding with it.
    year_end_minor: int | None  # The year's result with it.
    fields_changed: int = 1
    checked: bool | None = None  # Worked out again by the tax engine and it agreed (§46).

    def as_dict(self):
        return asdict(self)
