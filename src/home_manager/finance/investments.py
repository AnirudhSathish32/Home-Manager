"""Investments (docs/investments.md): accounts, their holdings and activity, and their values over time.

What an investment is lives in the investment_kinds table. The page and the forecast use only a kind's section,
tax treatment and value model, so a new kind is a row there, not new code. A pension (value model 'income') pays a
monthly benefit from its terms instead of holding a balance; a 529 (section 'education') is never drawn on for living
costs; I bonds follow the published TreasuryDirect rates. Values come from documents and what the user types, plus,
only when the household turns it on, crypto market prices (finance/prices.py), which never replace a document's value
for the same day or later. A value read from a statement waits for review; a
value the user enters counts at once. Values are never overwritten: each statement date adds one. A statement's
holdings and activity follow its account value's review. An account linked to a ledger savings account (a HYSA)
reads its values and interest from that account's statements instead, so they are recorded and reviewed once.
A purchase confirmation (a trade, a CD or a Treasury bought) adds holdings with their terms; between statements, an
account valued by accrual (CDs, Treasuries, I bonds) is estimated from those terms, and the estimate is labeled so.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.formats import extension
from ..core.money import currency_code, format_minor, money, to_minor
from ..library.storage import now
from .ledger import name_tokens, normalize_name
from .retirement import HAS_RMD, divisor, required, rmd_start_age
from .tabular import parse_crypto_export
from .tax_lots import account_lots, realized, shares
from .tax_lots import share_text as lot_shares

SECTIONS = {"retirement": "Retirement", "health": "Health savings", "cash": "Cash and savings", "fixed_income": "CDs, bonds and Treasuries",
            "market": "Stocks and funds", "education": "Education", "other": "Other"}
TAX_TREATMENTS = {"taxable": "Taxable", "tax_deferred": "Tax-deferred", "tax_free": "Tax-free", "hsa": "HSA"}
# What a holding is, as a statement prints it. Open-ended like kinds: the table accepts any lower-case word.
INSTRUMENT_CLASSES = {"cash": "Cash or sweep", "money_market": "Money market fund", "stock": "Stock", "etf": "ETF", "mutual_fund": "Mutual fund",
                      "target_date": "Target-date fund", "bond": "Bond", "treasury_bill": "Treasury bill", "treasury_note": "Treasury note",
                      "treasury_bond": "Treasury bond", "i_bond": "I bond", "cd": "CD", "crypto": "Crypto", "other": "Other"}
# Money in, out and earned. Amounts are stored as printed magnitudes; the type says which way the money went.
ACTIVITY_TYPES = {"contribution": "Contribution", "withdrawal": "Withdrawal", "dividend": "Dividend", "interest": "Interest", "fee": "Fee",
                  "buy": "Buy", "sell": "Sell", "maturity": "Maturity", "rollover": "Rollover", "transfer_in": "Transfer in",
                  "transfer_out": "Transfer out", "qualified_withdrawal": "Qualified education withdrawal",
                  "nonqualified_withdrawal": "Non-qualified withdrawal", "reward": "Reward", "other": "Other"}
# Money taken out of an account: a 529's withdrawals are qualified (tuition and the like) or not (their earnings are taxed).
WITHDRAWAL_TYPES = ("withdrawal", "qualified_withdrawal", "nonqualified_withdrawal")
# Activity that changes how many units a holding has (crypto positions between statements): +1 adds, -1 takes away.
QUANTITY_SIGNS = {"buy": 1, "transfer_in": 1, "reward": 1, "sell": -1, "transfer_out": -1}
CONTRIBUTION_SOURCES = {"employee": "From your pay", "employer": "From your employer", "personal": "From you"}
# Holdings with a principal and terms (a rate or a face value, and usually a maturity date): valued by accrual.
TERM_CLASSES = ("cd", "treasury_bill", "treasury_note", "treasury_bond", "i_bond", "bond")
# What a confirmation says was done, as the activity it records.
TRADE_ACTIONS = {"buy": "buy", "reinvest": "buy", "sell": "sell", "redeem": "sell", "deposit": "contribution"}
MATURITY_WINDOW_DAYS = 90
# Pay stub line categories (documents/extraction.py PAY_CATEGORIES) that are contributions, by the section of account they
# go to. A line in the employer_paid group is the employer's (a match); the rest come out of pay.
PAYROLL_CATEGORIES = {"retirement": ("retirement_pretax", "retirement_roth"), "health": ("hsa",)}
PAYROLL_LABELS = {"retirement": "401(k) or retirement", "health": "HSA"}
# A statement contribution is the same money as a pay stub line when it matches it this closely (or a quarter's lines added up).
PAYROLL_MATCH_DAYS, PAYROLL_QUARTER_DAYS = 7, 92
# 1098 (a lender's mortgage interest statement) has no investment account: its boxes feed the year's return (finance/tax_year.py).
TAX_FORMS = ("1099-INT", "1099-DIV", "1099-B", "1099-R", "1099-SA", "1099-Q", "1099-DA", "5498", "5498-SA", "1098")
# What a form's boxes report, compared with what is recorded for its account and year: (measure, label, {form: boxes}).
# 1099-INT 1 interest and 3 Treasury interest; 1099-DIV 1a ordinary dividends; 1099-B 1d proceeds and 1e cost (1099-DA 1f and
# 1g for digital assets); 1099-R, 1099-SA and 1099-Q 1 distributions; 5498 1 IRA and 10 Roth IRA contributions; 5498-SA 2 HSA
# contributions for the year.
TAX_CHECKS = [("interest", "Interest", {"1099-INT": ("1", "3")}), ("dividends", "Dividends", {"1099-DIV": ("1a",)}),
              ("proceeds", "Sale proceeds", {"1099-B": ("1d",), "1099-DA": ("1f",)}),
              ("cost", "Cost of shares sold", {"1099-B": ("1e",), "1099-DA": ("1g",)}),
              ("withdrawals", "Withdrawals", {"1099-R": ("1",), "1099-SA": ("1",), "1099-Q": ("1",)}),
              ("contributions", "Contributions", {"5498": ("1", "10"), "5498-SA": ("2",)})]
# I bonds (TreasuryDirect): values are worked out per $25 bond and rounded to the cent; interest is added on the first of each
# month and compounds every six months; it stops after 30 years. Cashed within five years, the last three months' interest is lost.
IBOND_UNIT_MINOR, IBOND_MONTHS, IBOND_PENALTY_MONTHS, IBOND_PENALTY_YEARS = 2500, 360, 3, 5
IBOND_YEARLY_LIMIT_MINOR = 1_000_000  # Electronic I bonds a person may buy in a calendar year ($10,000).
# A ledger account can stand for an investment account (a HYSA): its statements are the values.
LINKABLE_TYPES = ("savings", "checking", "brokerage", "other")
PERCENT = r"^-?\d{1,3}(\.\d{1,2})?$"
# Statement kinds are told apart only by printed words, never guessed; the first match wins, so specific plans
# come before general words (a "Roth 401(k)" is a 401(k), a "Treasury money market" is a money market fund).
PRINTED_KINDS = [
    ("401k", r"401\s*\(?K\)?"), ("403b", r"403\s*\(?B\)?"), ("457b", r"457(?:\s*\(?B\)?)?"),
    ("hsa", r"HSA|HEALTH SAVINGS"), ("education_529", r"[A-Z]*529"),  # Plans print names like my529 or NY 529.
    ("roth_ira", r"ROTH(?:\s+IRA)?"), ("ira", r"(?:SEP\s+|SIMPLE\s+|ROLLOVER\s+|TRADITIONAL\s+)?IRA"), ("pension", r"PENSION"),
    ("retirement", r"RETIREMENT|TSP|THRIFT SAVINGS"),
    ("money_market", r"MONEY MARKET"), ("cd", r"CDS?|CERTIFICATES? OF DEPOSIT"), ("i_bond", r"I[- ]BONDS?|SERIES I"),
    ("treasury", r"TREASURY|TREASURIES|TREASURYDIRECT|T-?BILLS?|T-?NOTES?"), ("bonds", r"BONDS?"),
    ("hysa", r"HIGH[- ]YIELD SAVINGS|SAVINGS"),
    ("crypto", r"CRYPTO|BITCOIN|COINBASE"),
]
PRINTED = [(kind, re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE)) for kind, pattern in PRINTED_KINDS]


def printed_kind(text):
    """The investment kind named by an account's printed name or institution; a brokerage account when none is."""
    return next((kind for kind, pattern in PRINTED if pattern.search(text or "")), "brokerage")


def rate_bp(percent):
    rate = Decimal(percent) * 100
    if rate != rate.to_integral_value() or not -10000 <= rate <= 10000:
        raise ValueError("Use a yearly rate between -100% and 100% with at most two decimals.")
    return int(rate)


def percent_text(bp):
    return None if bp is None else f"{(Decimal(bp) / 100).normalize():f}"


def share_text(part, whole):
    return f"{(Decimal(part) * 100 / whole).quantize(Decimal('0.1'), ROUND_HALF_EVEN)}" if whole else "0.0"


def holding_key(holding):
    """A holding is the same from one statement to the next by its ticker or CUSIP, else by its printed name."""
    identifier = re.sub(r"\s", "", (holding.get("identifier") or "").upper())
    return f"id:{identifier}" if identifier else f"name:{normalize_name(holding['name'])}"


def add_months(day, months):
    """The same day some months later, or the month's last day when it has no such day (Aug 31 + 6 months is Feb 28)."""
    start = date.fromisoformat(day)
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(start.day, last)).isoformat()


def accrued(base_minor, since, on, rate_bp=None, face_minor=None, maturity=None):
    """A fixed-income holding's value on a date from its terms, exact and rounded half-even to the minor unit. With a face value
    (a Treasury bill bought at a discount) it rises in a straight line to the face at maturity; otherwise it compounds at its
    yearly rate (a CD's APY, an I bond's rate). Nothing accrues before `since` or after maturity."""
    start, end = date.fromisoformat(since), date.fromisoformat(on)
    if maturity:
        end = min(end, date.fromisoformat(maturity))
    days = (end - start).days
    if days <= 0:
        return base_minor
    with localcontext() as context:
        context.prec = 34
        if face_minor is not None and maturity:
            term = (date.fromisoformat(maturity) - start).days
            value = Decimal(base_minor) + (Decimal(face_minor) - base_minor) * days / term
        elif rate_bp:
            value = Decimal(base_minor) * (1 + Decimal(rate_bp) / 10000) ** (Decimal(days) / 365)
        else:
            value = Decimal(base_minor)
        return int(value.to_integral_value(ROUND_HALF_EVEN))


def ibond_composite_bp(fixed_bp, inflation_bp):
    """TreasuryDirect's composite rate: fixed + 2 × semiannual inflation + fixed × semiannual inflation, to the hundredth of a
    percent, and never below zero (deflation can take it down to zero, not under)."""
    value = Decimal(fixed_bp) + 2 * Decimal(inflation_bp) + Decimal(fixed_bp) * Decimal(inflation_bp) / 10000
    return max(int(value.to_integral_value(ROUND_HALF_EVEN)), 0)


def ibond_months(issue_date, on):
    """Whole months of interest an I bond has on a date: it is dated the first of its issue month and gains a month's interest
    on the first of each month after, for 30 years."""
    issued, day = date.fromisoformat(issue_date), date.fromisoformat(on)
    return min(max((day.year - issued.year) * 12 + day.month - issued.month, 0), IBOND_MONTHS)


def ibond_rate(rates, day):
    """The rate row in force on a day: the latest published on or before it."""
    found = None
    for row in rates:
        if row["period_start"] <= day:
            found = row
    return found


def ibond_value(principal_minor, issue_date, on, rates, months=None):
    """An I bond's value after `months` of interest (by default, those it has on `on`), from the published rates; None when no
    rate covers its issue month. Its fixed rate is the one for its issue month; the inflation rate resets every six months from
    the issue month to the one in force then (the latest published when a period begins after the last one known). Worked out
    for a $25 bond rounded to the cent at each step, as TreasuryDirect does, then scaled to the principal."""
    rates = sorted(rates, key=lambda row: row["period_start"])
    issued = issue_date[:7] + "-01"
    fixed = ibond_rate(rates, issued)
    if fixed is None:
        return None
    months = ibond_months(issue_date, on) if months is None else months
    with localcontext() as context:
        context.prec = 34
        unit, done = Decimal(IBOND_UNIT_MINOR), 0
        while done < months:
            period = ibond_rate(rates, add_months(issued, done))
            composite = ibond_composite_bp(fixed["fixed_bp"], period["inflation_semiannual_bp"])
            step = min(6, months - done)
            unit = (unit * (1 + Decimal(composite) / 20000) ** (Decimal(step) / 6)).to_integral_value(ROUND_HALF_EVEN)
            done += step
        return int((unit * Decimal(principal_minor) / IBOND_UNIT_MINOR).to_integral_value(ROUND_HALF_EVEN))


def ibond_cash_out(principal_minor, issue_date, on, rates):
    """What an I bond pays if cashed on a date: nothing before 12 months; before five years, its value three months earlier."""
    months = ibond_months(issue_date, on)
    if months < 12:
        return None
    if months < IBOND_PENALTY_YEARS * 12:
        months -= IBOND_PENALTY_MONTHS
    return ibond_value(principal_minor, issue_date, on, rates, months)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AccountUpdate(StrictInput):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(min_length=1, max_length=40)
    institution: str = Field(default="", max_length=80)
    annual_rate_percent: str | None = Field(default=None, pattern=PERCENT, description="Yearly growth or interest; blank uses the kind's default.")
    tax_treatment: str | None = Field(default=None, json_schema_extra={"enum": list(TAX_TREATMENTS)}, description="Blank uses the kind's.")
    ledger_account_id: int | None = Field(default=None, ge=1, description="A savings account whose statements are this account's values.")
    payroll_employer_id: int | None = Field(default=None, ge=0, description="The employer whose pay stub contributions go here; 0 for none, blank to match automatically.")
    monthly_contribution: str | None = Field(default=None, max_length=30, description="What you put in each month, for the forecast; blank uses recent contributions.")
    beneficiary: str | None = Field(default=None, max_length=80, description="A 529's beneficiary: a profile's name or anyone's.")
    plan_state: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$", description="The state whose 529 plan it is.")

    @model_validator(mode="after")
    def known_tax(self):
        if self.tax_treatment is not None and self.tax_treatment not in TAX_TREATMENTS:
            raise ValueError(f"Choose one of: {', '.join(TAX_TREATMENTS)}.")
        return self


class ValueInput(StrictInput):
    value: str = Field(min_length=1, max_length=30)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def real_date(self):
        date.fromisoformat(self.as_of)
        return self


class AccountInput(AccountUpdate):
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    value: str | None = Field(default=None, min_length=1, max_length=30, description="Today's value; a pension has none (it pays an income).")
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def real_date(self):
        if self.as_of:
            date.fromisoformat(self.as_of)
        if bool(self.value) != bool(self.as_of):
            raise ValueError("Enter the value with its date.")
        return self


class PensionInput(StrictInput):
    """A pension's terms, as its benefit statement prints them."""
    monthly_benefit: str = Field(min_length=1, max_length=30, description="What it pays a month from the start date, before tax.")
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    cola_percent: str = Field(default="0", pattern=r"^\d{1,2}(\.\d{1,2})?$", description="Its yearly cost-of-living raise, each January.")
    survivor_percent: int = Field(default=0, ge=0, le=100, description="The share a surviving spouse keeps.")
    lump_sum: str | None = Field(default=None, max_length=30, description="A lump sum offered instead, shown beside it and never counted in totals.")

    @model_validator(mode="after")
    def real_date(self):
        date.fromisoformat(self.start_date)
        return self


class EventInput(StrictInput):
    """Activity you record yourself, such as a 529 withdrawal: it counts at once."""
    event_type: str = Field(json_schema_extra={"enum": list(ACTIVITY_TYPES)})
    event_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: str = Field(min_length=1, max_length=30)
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def known(self):
        if self.event_type not in ACTIVITY_TYPES:
            raise ValueError(f"Choose one of: {', '.join(ACTIVITY_TYPES)}.")
        date.fromisoformat(self.event_date)
        return self


class WithdrawalKind(StrictInput):
    qualified: bool


class IbondRateInput(StrictInput):
    """A rate TreasuryDirect announces each May 1 and November 1."""
    period_start: str = Field(pattern=r"^\d{4}-(05|11)-01$", description="May 1 or November 1.")
    fixed_percent: str = Field(pattern=r"^\d{1,2}(\.\d{1,2})?$")
    inflation_percent: str = Field(pattern=r"^-?\d{1,2}(\.\d{1,2})?$", description="The semiannual inflation rate, as published.")


class HoldingInput(StrictInput):
    """A CD, Treasury or bond the user adds, with the terms its value is estimated from."""
    name: str = Field(min_length=1, max_length=200)
    instrument_class: str = Field(json_schema_extra={"enum": list(TERM_CLASSES)})
    principal: str = Field(min_length=1, max_length=30, description="What was paid for it.")
    issue_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    annual_rate_percent: str | None = Field(default=None, pattern=PERCENT, description="Its APY or yearly rate.")
    maturity_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    face_value: str | None = Field(default=None, max_length=30, description="What it pays at maturity, when printed (a Treasury bill's face).")
    rollover: bool = False

    @model_validator(mode="after")
    def consistent(self):
        if self.instrument_class not in TERM_CLASSES:
            raise ValueError(f"Choose one of: {', '.join(TERM_CLASSES)}.")
        date.fromisoformat(self.issue_date)
        if self.maturity_date and date.fromisoformat(self.maturity_date) <= date.fromisoformat(self.issue_date):
            raise ValueError("The maturity date must come after the issue date.")
        if self.face_value and not self.maturity_date:
            raise ValueError("A face value is paid at maturity; add the maturity date.")
        return self


class MaturedInput(StrictInput):
    outcome: str = Field(json_schema_extra={"enum": ["cash", "rollover"]})
    amount: str | None = Field(default=None, max_length=30, description="What was paid out; blank uses the value its terms give at maturity.")

    @model_validator(mode="after")
    def known(self):
        if self.outcome not in ("cash", "rollover"):
            raise ValueError("Choose cash or rollover.")
        return self


class PayrollChoice(StrictInput):
    employer_id: int = Field(ge=1)


class LotInput(StrictInput):
    """Shares bought before the documents here begin: when, how many, and what they cost."""
    acquired_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    quantity: str = Field(min_length=1, max_length=30)
    cost: str = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def valid(self):
        date.fromisoformat(self.acquired_date)
        if shares(self.quantity) is None:
            raise ValueError("Enter the number of shares, more than zero.")
        return self


class Investments:
    def __init__(self, store, today=None):
        self.store, self._today = store, today

    @property
    def today(self):
        return (self._today or date.today()).isoformat()

    # Kinds -------------------------------------------------------------------------------------------------------
    def kinds(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM investment_kinds ORDER BY position,key").fetchall()
        return [{**dict(row), "has_maturity": bool(row["has_maturity"]), "section_label": SECTIONS[row["section"]],
                 "tax_label": TAX_TREATMENTS[row["tax_treatment"]], "default_rate_percent": percent_text(row["default_rate_bp"])} for row in rows]

    def kind(self, db, key):
        row = db.execute("SELECT * FROM investment_kinds WHERE key=?", (key,)).fetchone()
        if row is None:
            raise ValueError("Choose an investment kind from the list.")
        return row

    # Reading -----------------------------------------------------------------------------------------------------
    def rows(self, db, include_archived=False, account_id=None):
        """Accounts with their kind and their confirmed and newest values (account-level values only)."""
        where = ["1=1" if include_archived else "a.archived_at IS NULL"] + (["a.id=?"] if account_id is not None else [])
        accounts = db.execute("SELECT a.*,k.label AS kind_label,k.section,k.tax_treatment AS kind_tax,k.value_model,k.has_maturity,k.default_rate_bp,"
                              "l.display_name AS ledger_account_name,m.canonical_name AS payroll_employer,p.monthly_benefit_minor,"
                              "p.start_date AS pension_start,p.cola_bp,p.survivor_pct,p.lump_sum_minor FROM investment_accounts a "
                              "JOIN investment_kinds k ON k.key=a.kind LEFT JOIN accounts l ON l.id=a.ledger_account_id "
                              "LEFT JOIN merchants m ON m.id=a.payroll_merchant_id LEFT JOIN pension_terms p ON p.account_id=a.id "
                              f"WHERE {' AND '.join(where)} "
                              "ORDER BY k.position,a.name,a.id", (account_id,) if account_id is not None else ()).fetchall()
        values = {}
        for row in db.execute("SELECT * FROM investment_valuations WHERE holding_id IS NULL AND review_status<>'rejected' ORDER BY as_of DESC,id DESC"):
            values.setdefault(row["account_id"], []).append(dict(row))
        return [self.view(dict(account), self.merged_values(db, account, values.get(account["id"], []))) for account in accounts]

    @staticmethod
    def ledger_values(db, account):
        """A linked savings account's statement closing balances as this account's values. They are reviewed with the statement."""
        if not account["ledger_account_id"]:
            return []
        values, seen = [], set()
        for row in db.execute("SELECT id,period_end,closing_balance_minor,document_id,blob_hash,review_status,validation_json,created_at,updated_at "
                              "FROM statements WHERE account_id=? AND period_end IS NOT NULL AND closing_balance_minor>=0 AND review_status<>'rejected' "
                              "ORDER BY period_end DESC,id DESC", (account["ledger_account_id"],)):
            if row["period_end"] in seen:
                continue
            seen.add(row["period_end"])
            values.append({"id": None, "statement_id": row["id"], "account_id": account["id"], "holding_id": None, "as_of": row["period_end"],
                           "value_minor": row["closing_balance_minor"], "source": "ledger_statement", "document_id": row["document_id"],
                           "blob_hash": row["blob_hash"], "validation_json": row["validation_json"],
                           "review_status": "verified" if row["review_status"] == "verified" else "proposed",
                           "created_at": row["created_at"], "updated_at": row["updated_at"]})
        return values

    def merged_values(self, db, account, own):
        """Own values plus a linked account's statements, and for an account valued by accrual an estimate for today from its
        holdings' terms. A value the account records itself wins for its date; the estimate only follows the newest value."""
        dates = {value["as_of"] for value in own}
        merged = own + [value for value in self.ledger_values(db, account) if value["as_of"] not in dates]
        estimate = self.estimated_value(db, account)
        if estimate is not None and all(value["as_of"] < self.today for value in merged):
            merged.append(estimate)
        return sorted(merged, key=lambda value: (value["as_of"], value["id"] or 0), reverse=True)

    # Terms and estimates ---------------------------------------------------------------------------------------------
    @staticmethod
    def latest_holdings_date(db, account_id):
        return db.execute("SELECT max(as_of) FROM investment_valuations WHERE account_id=? AND holding_id IS NOT NULL AND review_status<>'rejected'",
                          (account_id,)).fetchone()[0]

    def term_holdings(self, db, account_id):
        """Open holdings whose value can be carried forward from terms: those on the newest statement (from their statement
        value) and CDs or Treasuries bought or entered since (from their principal). Each says whether it counts yet (a
        confirmation still waiting for review doesn't) and whether it has matured."""
        latest = self.latest_holdings_date(db, account_id)
        rows = db.execute("SELECT h.*,c.review_status AS confirmation_status,v.value_minor AS statement_value,v.review_status AS statement_status "
                          "FROM holdings h LEFT JOIN investment_confirmations c ON c.id=h.confirmation_id "
                          "LEFT JOIN investment_valuations v ON v.holding_id=h.id AND v.as_of=? AND v.review_status<>'rejected' "
                          "WHERE h.account_id=? AND h.archived_at IS NULL ORDER BY h.maturity_date IS NULL,h.maturity_date,h.name",
                          (latest or "", account_id)).fetchall()
        found, rates = [], self.ibond_rates(db)
        for row in rows:
            if row["statement_value"] is not None:
                base, since, counts = row["statement_value"], latest, row["statement_status"] == "verified"
            elif row["source"] != "statement" and row["principal_minor"] is not None and row["confirmation_status"] != "rejected":
                base, since, counts = row["principal_minor"], row["issue_date"] or row["created_at"][:10], row["confirmation_status"] in (None, "verified")
            else:
                continue  # Listed only on an older statement: sold or matured since.
            if self.ibond_terms(row, rates):  # An I bond follows the published rates, not one fixed rate.
                value = lambda on, row=row: ibond_value(row["principal_minor"], row["issue_date"], on, rates)
            else:
                value = lambda on, row=row, base=base, since=since: accrued(base, since, on, row["rate_bp"], row["face_minor"], row["maturity_date"])
            found.append({**dict(row), "base_minor": base, "since": since, "counts": counts, "value_on": value,
                          "matured": bool(row["maturity_date"]) and row["maturity_date"] <= self.today})
        return found

    @staticmethod
    def ibond_rates(db):
        return [dict(row) for row in db.execute("SELECT * FROM ibond_rates ORDER BY period_start")]

    @staticmethod
    def ibond_terms(row, rates):
        """An I bond with what its value is worked out from: its principal, its issue month and a published rate for that month."""
        return row["instrument_class"] == "i_bond" and row["principal_minor"] is not None and bool(row["issue_date"]) \
            and ibond_rate(rates, row["issue_date"][:7] + "-01") is not None

    def ibond_rate_table(self):
        """The published I bond rates kept here, newest first, with each period's composite rate for a bond bought then."""
        with self.store.connection() as db:
            rows = self.ibond_rates(db)
        return [{**row, "fixed_percent": percent_text(row["fixed_bp"]), "inflation_percent": percent_text(row["inflation_semiannual_bp"]),
                 "composite_percent": percent_text(ibond_composite_bp(row["fixed_bp"], row["inflation_semiannual_bp"]))} for row in reversed(rows)]

    def set_ibond_rate(self, value: IbondRateInput):
        """Add or correct a published rate (each May and November). I bond values follow it at once."""
        fixed, inflation = rate_bp(value.fixed_percent), rate_bp(value.inflation_percent)
        if fixed > 1000 or abs(inflation) > 1000:
            raise ValueError("Enter rates of 10% or less, as TreasuryDirect publishes them.")
        with self.store.connection() as db:
            db.execute("INSERT INTO ibond_rates(period_start,fixed_bp,inflation_semiannual_bp) VALUES(?,?,?) ON CONFLICT(period_start) DO UPDATE SET "
                       "fixed_bp=excluded.fixed_bp,inflation_semiannual_bp=excluded.inflation_semiannual_bp", (value.period_start, fixed, inflation))
        return self.ibond_rate_table()

    def ibond_limits(self, db):
        """Calendar years whose electronic I bond purchases here pass the $10,000 a person may buy (a profile is one person).
        Purchases waiting for review count too, so the warning comes before they are confirmed; rejected ones don't."""
        rows = db.execute("SELECT substr(h.issue_date,1,4) AS year,a.currency,sum(h.principal_minor) AS total FROM holdings h "
                          "JOIN investment_accounts a ON a.id=h.account_id LEFT JOIN investment_confirmations c ON c.id=h.confirmation_id "
                          "WHERE h.instrument_class='i_bond' AND h.principal_minor IS NOT NULL AND h.issue_date IS NOT NULL "
                          "AND coalesce(c.review_status,'verified')<>'rejected' AND a.currency='USD' GROUP BY 1,2 HAVING sum(h.principal_minor)>? ORDER BY 1",
                          (IBOND_YEARLY_LIMIT_MINOR,)).fetchall()
        return [{"year": int(row["year"]), "total": money(row["total"], row["currency"]), "limit": money(IBOND_YEARLY_LIMIT_MINOR, row["currency"]),
                 "message": f"I bonds bought in {row['year']} add up to {format_minor(row['total'], row['currency'])}, more than the "
                            f"{format_minor(IBOND_YEARLY_LIMIT_MINOR, row['currency'])} a person may buy electronically in a year. Check the "
                            "amounts, or whether some belong to someone else's profile."} for row in rows]

    def estimated_value(self, db, account):
        """Today's value of an account valued by accrual, from its holdings' terms; None when it has none to estimate from.
        Holdings that matured, or wait for review, are left out; an account whose CDs all matured is estimated at zero."""
        if account["value_model"] != "accrual":
            return None
        holdings = self.term_holdings(db, account["id"])
        closed = db.execute("SELECT 1 FROM holdings WHERE account_id=? AND source<>'statement' AND archived_at IS NOT NULL", (account["id"],)).fetchone()
        if not any(holding["counts"] for holding in holdings) and not closed:
            return None  # Nothing confirmed to estimate from yet.
        counted = [holding for holding in holdings if holding["counts"] and not holding["matured"]]
        return {"id": None, "account_id": account["id"], "holding_id": None, "as_of": self.today, "source": "estimated",
                "value_minor": sum(holding["value_on"](self.today) for holding in counted), "document_id": None, "blob_hash": None,
                "validation_json": "[]", "review_status": "verified", "created_at": None, "updated_at": None}

    @staticmethod
    def valuation_view(row, currency):
        row = dict(row)
        row["issues"] = json.loads(row.pop("validation_json", None) or "[]")
        return {**row, "value": money(row["value_minor"], currency)}

    def view(self, account, values):
        currency = account["currency"]
        confirmed = [value for value in values if value["review_status"] == "verified"]
        current, previous = (confirmed + [None, None])[:2]
        waiting = [value for value in values if value["review_status"] == "proposed"]
        rate = account["annual_rate_bp"] if account["annual_rate_bp"] is not None else account["default_rate_bp"]
        kind_tax = account.pop("kind_tax")
        tax = account["tax_treatment"] or kind_tax
        change = current["value_minor"] - previous["value_minor"] if current and previous else None
        terms = {key: account.pop(key) for key in ("monthly_benefit_minor", "pension_start", "cola_bp", "survivor_pct", "lump_sum_minor")}
        # A pension pays an income: its terms, with the lump sum offered instead shown beside them, never counted as a balance.
        pension = {"monthly_benefit": money(terms["monthly_benefit_minor"], currency), "monthly_benefit_minor": terms["monthly_benefit_minor"],
                   "start_date": terms["pension_start"], "cola_bp": terms["cola_bp"], "cola_percent": percent_text(terms["cola_bp"]),
                   "survivor_percent": terms["survivor_pct"],
                   "lump_sum": money(terms["lump_sum_minor"], currency) if terms["lump_sum_minor"] is not None else None} \
            if terms["monthly_benefit_minor"] is not None else None
        return {**account, "has_maturity": bool(account["has_maturity"]), "section_label": SECTIONS[account["section"]],
                "tax_treatment": tax, "tax_label": TAX_TREATMENTS[tax], "tax_overridden": account["tax_treatment"] is not None,
                "rate_bp": rate, "annual_rate_percent": percent_text(rate), "rate_is_default": account["annual_rate_bp"] is None,
                "is_income": account["value_model"] == "income", "pension": pension,
                "current": self.valuation_view(current, currency) if current else None,
                "change": money(change, currency) if change is not None else None, "change_since": previous["as_of"] if previous else None,
                "awaiting_review": [self.valuation_view(value, currency) for value in waiting]}

    def summary(self, include_archived=False):
        """Every account grouped by section, with totals per currency by section and by tax treatment (confirmed values only)."""
        with self.store.connection() as db:
            self.link_payroll(db)  # Pay stubs read since the last visit may point to an account.
            questions = self.payroll_questions(db)
            accounts = self.rows(db, include_archived)
            confirmations = db.execute("SELECT count(*) FROM investment_confirmations c JOIN investment_accounts a ON a.id=c.account_id "
                                       "WHERE c.review_status='proposed' AND a.archived_at IS NULL").fetchone()[0] \
                + db.execute("SELECT count(*) FROM tax_forms WHERE review_status='proposed'").fetchone()[0]
            ibond_warnings = self.ibond_limits(db)
        totals = {}
        for account in accounts:
            if account["current"] is None or account["archived_at"] or account["is_income"]:
                continue  # A pension's value is the income it pays, not a balance.
            bucket = totals.setdefault(account["currency"], {"total": 0, "sections": {}, "tax": {}, "oldest": None, "estimated": 0})
            minor = account["current"]["value_minor"]
            bucket["estimated"] += account["current"]["source"] == "estimated"
            bucket["total"] += minor
            bucket["sections"][account["section"]] = bucket["sections"].get(account["section"], 0) + minor
            bucket["tax"][account["tax_treatment"]] = bucket["tax"].get(account["tax_treatment"], 0) + minor
            as_of = account["current"]["as_of"]
            bucket["oldest"] = min(bucket["oldest"] or as_of, as_of)
        views = []
        for currency, bucket in sorted(totals.items(), key=lambda item: -item[1]["total"]):
            # Called within this iteration only, so the loop variables are current.
            split = lambda parts, labels: [{"key": key, "label": labels[key], "total": money(parts[key], currency), "share_percent": share_text(parts[key], bucket["total"])}  # noqa: B023
                                           for key in labels if key in parts]
            views.append({"currency": currency, "total": money(bucket["total"], currency), "oldest_as_of": bucket["oldest"], "estimated_accounts": bucket["estimated"],
                          "sections": split(bucket["sections"], SECTIONS), "tax": split(bucket["tax"], TAX_TREATMENTS)})
        return {"accounts": accounts, "totals": views, "sections": SECTIONS, "maturities": self.maturities(), "payroll_questions": questions,
                "ibond_warnings": ibond_warnings,
                "awaiting_review": sum(len(account["awaiting_review"]) for account in accounts if not account["archived_at"]) + confirmations}

    def get(self, account_id):
        """One account with every value it has had, the holdings on its newest statement, its activity, and the ledger
        accounts it could be linked to."""
        with self.store.connection() as db:
            found = self.rows(db, True, account_id)
            if not found:
                raise ValueError("Investment account not found.")
            account = found[0]
            currency = account["currency"]
            own = [dict(row) for row in db.execute("SELECT * FROM investment_valuations WHERE account_id=? AND holding_id IS NULL", (account_id,))]
            history = [self.valuation_view(row, currency) for row in self.merged_values(db, account, own)]
            holdings, holdings_as_of = self.holdings(db, account_id, currency)
            if account["tax_treatment"] == "taxable":  # Gains are taxed only in taxable accounts; others need no lots.
                self.with_lots(holdings, account_lots(db, account_id), currency)
            events = self.events(db, account)
            confirmations = [self.confirmation_view(db, row, currency) for row in db.execute(
                "SELECT * FROM investment_confirmations WHERE account_id=? ORDER BY trade_date DESC,id DESC", (account_id,))]
            linkable = [dict(row) for row in db.execute(
                f"SELECT l.id,l.display_name,l.account_type FROM accounts l WHERE l.account_type IN ({','.join('?' * len(LINKABLE_TYPES))}) AND l.currency=? "
                "AND l.active=1 AND NOT EXISTS(SELECT 1 FROM investment_accounts a WHERE a.ledger_account_id=l.id AND a.id<>?) ORDER BY l.display_name",
                (*LINKABLE_TYPES, currency, account_id))]
            employers = [{"id": employer_id, "name": name} for employer_id, name, employer_currency, _ in self.payroll_employers(db, account["section"])
                         if employer_currency == currency]
            has_ibonds = any(holding["instrument_class"] == "i_bond" for holding in holdings)
            ibond_warnings = self.ibond_limits(db) if has_ibonds else []
        monthly = account["monthly_contribution_minor"]
        return {**account, "history": history, "holdings": holdings, "holdings_as_of": holdings_as_of, "events": events, "linkable_accounts": linkable,
                "confirmations": confirmations, "payroll_employers": employers, "takes_payroll": account["section"] in PAYROLL_CATEGORIES,
                "monthly_contribution": money(monthly, currency) if monthly is not None else None,
                "is_education": account["section"] == "education", "has_crypto": any(holding["instrument_class"] == "crypto" for holding in holdings),
                "has_ibonds": has_ibonds, "ibond_warnings": ibond_warnings}

    def holdings(self, db, account_id, currency):
        """The holdings valued on the account's newest statement date, largest first, with their gain where a cost basis is printed;
        then CDs and Treasuries bought or entered since, valued from their terms (estimated)."""
        latest = self.latest_holdings_date(db, account_id)
        views, rates = [], self.ibond_rates(db)
        if latest is not None:
            rows = db.execute("SELECT h.*,v.value_minor,v.quantity,v.price_minor,v.cost_basis_minor,v.review_status,v.source AS value_source FROM holdings h "
                              "JOIN investment_valuations v ON v.holding_id=h.id AND v.as_of=? AND v.review_status<>'rejected' "
                              "WHERE h.account_id=? AND h.archived_at IS NULL ORDER BY v.value_minor DESC,h.name", (latest, account_id)).fetchall()
            for row in rows:
                gain = row["value_minor"] - row["cost_basis_minor"] if row["cost_basis_minor"] is not None else None
                views.append(self.holding_view(row, currency, row["value_minor"], estimated=False, gain=gain, rates=rates))
        listed = {view["id"] for view in views}
        for holding in self.term_holdings(db, account_id):
            if holding["id"] in listed:
                continue
            views.append(self.holding_view(holding, currency, holding["value_on"](self.today), estimated=True,
                                           status=holding["confirmation_status"] or "verified", matured=holding["matured"], rates=rates))
        return views, latest

    @staticmethod
    def with_lots(holdings, lots, currency):
        """Each holding's open lots (oldest first), shares sold with no lot, and its unrealized gain by lot cost when its open
        lots hold exactly the shares the statement shows."""
        for holding in holdings:
            found = lots.get(holding["id"])
            if not found:
                continue
            holding["lots"] = [{**lot, "cost": money(lot["cost_minor"], currency)} for lot in found["lots"]]
            holding["lots_missing"] = found["missing"]
            held = shares(holding.get("quantity"))
            if held is not None and held == shares(found["open_shares"]) and not holding["estimated"]:
                holding["lot_gain"] = money(holding["value_minor"] - found["open_cost_minor"], currency)

    def holding_view(self, row, currency, value, estimated, gain=None, status=None, matured=False, rates=()):
        row = dict(row)
        row.pop("value_on", None)
        ibond = self.ibond_terms(row, rates)
        # An I bond's value at 30 years would rest on rates not yet published, so none is shown; what it pays if cashed today is.
        at_maturity = accrued(row["base_minor"], row["since"], row["maturity_date"], row["rate_bp"], row["face_minor"], row["maturity_date"]) \
            if estimated and row["maturity_date"] and not ibond else None
        cash_out = ibond_cash_out(row["principal_minor"], row["issue_date"], self.today, rates) if ibond else None
        if ibond:
            composite = ibond_rate(rates, row["issue_date"][:7] + "-01")
            current = ibond_rate(rates, add_months(row["issue_date"][:7] + "-01", min(ibond_months(row["issue_date"], self.today) // 6 * 6, IBOND_MONTHS - 6)))
            row["rate_bp"] = ibond_composite_bp(composite["fixed_bp"], current["inflation_semiannual_bp"])  # The composite rate it earns now.
        show = lambda minor: money(minor, currency) if minor is not None else None
        return {**row, "class_label": INSTRUMENT_CLASSES.get(row["instrument_class"], row["instrument_class"].replace("_", " ").capitalize()),
                "cash_out": show(cash_out), "penalty_until": add_months(row["issue_date"][:7] + "-01", IBOND_PENALTY_YEARS * 12) if ibond else None,
                "value_source": row.get("value_source") or ("estimated" if estimated else "statement"),
                "rate_percent": percent_text(row["rate_bp"]), "value": money(value, currency), "value_minor": value, "estimated": estimated,
                "review_status": status or row.get("review_status"), "matured": matured, "rollover": bool(row["rollover"]),
                "price": show(row.get("price_minor")), "cost_basis": show(row.get("cost_basis_minor")), "gain": show(gain),
                "principal": show(row["principal_minor"]), "face": show(row["face_minor"]), "at_maturity": show(at_maturity),
                "lots": [], "lots_missing": [], "lot_gain": None}

    @staticmethod
    def payroll_lines(db, merchant_id, section, currency, start=None, end=None):
        """Contributions on pay stubs from one employer that go to a section's account: this period's amount of each 401(k), Roth or
        HSA line, with who paid it (a line in the employer-paid group is the employer's). Pay stubs rejected in review are left out."""
        categories = PAYROLL_CATEGORIES.get(section)
        if not merchant_id or not categories:
            return []
        rows = db.execute(f"SELECT l.id,l.description,l.line_group,l.current_minor,r.id AS income_record_id,r.pay_date,r.review_status,r.document_id "
                          "FROM income_lines l JOIN income_records r ON r.id=l.income_record_id WHERE r.payer_merchant_id=? AND r.currency=? "
                          f"AND l.category IN ({','.join('?' * len(categories))}) AND l.current_minor IS NOT NULL AND l.current_minor<>0 "
                          "AND r.review_status<>'rejected' AND r.pay_date IS NOT NULL AND r.pay_date BETWEEN ? AND ? ORDER BY r.pay_date,l.position",
                          (merchant_id, currency, *categories, start or "0000-01-01", end or "9999-12-31")).fetchall()
        return [{**dict(row), "amount_minor": abs(row["current_minor"]), "contribution_source": "employer" if row["line_group"] == "employer_paid" else "employee"}
                for row in rows]

    def events(self, db, account):
        """Activity from statements, confirmations and the user; contributions from pay stubs (the linked employer's 401(k) or HSA
        lines, reviewed with the pay stub); and interest paid into a linked savings account. Newest first. A statement contribution
        that is the same money as a pay stub line (same payer and amount within a week) is shown once, as the pay stub's."""
        currency, rows = account["currency"], []
        for row in db.execute("SELECT * FROM investment_events WHERE account_id=? AND review_status<>'rejected'", (account["id"],)):
            rows.append({**dict(row), "source": "confirmation" if row["confirmation_id"] else "statement" if row["blob_hash"] else "manual"})
        for line in self.payroll_lines(db, account["payroll_merchant_id"], account["section"], currency):
            twin = next((row for row in rows if row["source"] == "statement" and row["event_type"] == "contribution" and not row.get("twin")
                         and row["contribution_source"] == line["contribution_source"] and row["amount_minor"] == line["amount_minor"]
                         and abs((date.fromisoformat(row["event_date"]) - date.fromisoformat(line["pay_date"])).days) <= PAYROLL_MATCH_DAYS), None)
            if twin:
                twin["twin"] = True
            rows.append({"id": None, "income_line_id": line["id"], "event_date": line["pay_date"], "event_type": "contribution",
                         "contribution_source": line["contribution_source"], "amount_minor": line["amount_minor"], "note": line["description"],
                         "review_status": line["review_status"], "document_id": line["document_id"], "source": "paystub", "also_on_statement": bool(twin)})
        rows = [row for row in rows if not row.get("twin")]
        if account["ledger_account_id"]:
            for row in db.execute("SELECT id,posted_date,amount_minor,description_raw,review_status,source_document_id FROM transactions "
                                  "WHERE account_id=? AND transaction_type='interest' AND review_status<>'rejected'", (account["ledger_account_id"],)):
                rows.append({"id": None, "transaction_id": row["id"], "event_date": row["posted_date"], "event_type": "interest", "contribution_source": None,
                             "amount_minor": abs(row["amount_minor"]), "note": row["description_raw"], "review_status": row["review_status"],
                             "document_id": row["source_document_id"], "source": "ledger"})
        rows.sort(key=lambda row: (row["event_date"], row["id"] or 0), reverse=True)
        # The bank or card line that paid a contribution in (Reconciler.investment_transfers): moved money, not spending.
        paid = {row["id"]: row["display_name"] for row in db.execute(
            "SELECT t.id,l.display_name FROM investment_events e JOIN transactions t ON t.id=e.transaction_id JOIN accounts l ON l.id=t.account_id "
            "WHERE e.account_id=?", (account["id"],))}
        return [{**row, "paid_from": paid.get(row.get("transaction_id")) if row["source"] != "ledger" else None,
                 "paid_from_link": row.get("transaction_link") if row["source"] != "ledger" else None,
                 "type_label": ACTIVITY_TYPES.get(row["event_type"], row["event_type"].replace("_", " ").capitalize()),
                 "source_label": CONTRIBUTION_SOURCES.get(row["contribution_source"]), "amount": money(row["amount_minor"], currency),
                 "review_status": "verified" if row["review_status"] == "verified" else "proposed" if row["review_status"] != "rejected" else "rejected"}
                for row in rows]

    def valuation(self, valuation_id=None, legacy_asset_id=None):
        """One value with its account and what its statement listed, for the document inspector and Review.
        Results recorded before 036 name the old asset."""
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM investment_valuations WHERE " + ("id=?" if valuation_id is not None else "legacy_asset_id=?"),
                             (valuation_id if valuation_id is not None else legacy_asset_id,)).fetchone()
            if row is None:
                raise ValueError("Investment value not found.")
            account = self.rows(db, True, row["account_id"])[0]
            counts = self.statement_counts(db, row)
        return {**self.valuation_view(row, account["currency"]), **counts,
                "account": {key: account[key] for key in ("id", "name", "kind", "kind_label", "institution", "currency")}}

    @staticmethod
    def statement_counts(db, valuation):
        """How many holdings and activity rows came with a statement value."""
        holdings = db.execute("SELECT count(*) FROM investment_valuations WHERE account_id=? AND as_of=? AND holding_id IS NOT NULL",
                              (valuation["account_id"], valuation["as_of"])).fetchone()[0]
        activity = db.execute("SELECT count(*) FROM investment_events WHERE account_id=? AND blob_hash=?",
                              (valuation["account_id"], valuation["blob_hash"])).fetchone()[0] if valuation["blob_hash"] else 0
        return {"holding_count": holdings, "activity_count": activity}

    def pending(self):
        """What waits for the user here, oldest first: investment statement values, purchase confirmations and tax forms. A linked
        savings account's statements are reviewed as statements, not here."""
        with self.store.connection() as db:
            rows = db.execute("SELECT v.*,a.name,a.kind,a.currency,k.label AS kind_label FROM investment_valuations v "
                              "JOIN investment_accounts a ON a.id=v.account_id JOIN investment_kinds k ON k.key=a.kind "
                              "WHERE v.review_status='proposed' AND v.source='statement' AND v.holding_id IS NULL AND a.archived_at IS NULL "
                              "ORDER BY v.as_of,v.id").fetchall()
            values = [{**self.valuation_view(row, row["currency"]), **self.statement_counts(db, row), "record_type": "investment_valuation",
                       "review_path": f"/api/investments/valuations/{row['id']}/review"} for row in rows]
            confirmations = [row[0] for row in db.execute("SELECT c.id FROM investment_confirmations c JOIN investment_accounts a ON a.id=c.account_id "
                                                          "WHERE c.review_status='proposed' AND a.archived_at IS NULL ORDER BY c.trade_date,c.id")]
            forms = [self.tax_form_view(db, row) for row in db.execute(
                "SELECT f.*,a.name AS account_name FROM tax_forms f LEFT JOIN investment_accounts a ON a.id=f.account_id WHERE f.review_status='proposed' "
                "ORDER BY f.tax_year,f.id")]
        return values + [self.confirmation(confirmation_id) for confirmation_id in confirmations] + forms

    def linked_ledger_accounts(self):
        """Ledger accounts whose balance counts as an investment, so the forecast leaves them out of cash."""
        with self.store.connection() as db:
            return {row[0] for row in db.execute("SELECT ledger_account_id FROM investment_accounts WHERE ledger_account_id IS NOT NULL AND archived_at IS NULL")}

    # Contributions from pay ------------------------------------------------------------------------------------------
    @staticmethod
    def payroll_employers(db, section=None):
        """Employers whose pay stubs list contributions, with the section of account each kind goes to: (id, name, currency, section)."""
        found = set()
        for row in db.execute("SELECT DISTINCT r.payer_merchant_id,m.canonical_name,r.currency,l.category FROM income_lines l "
                              "JOIN income_records r ON r.id=l.income_record_id JOIN merchants m ON m.id=r.payer_merchant_id "
                              "WHERE r.review_status<>'rejected' AND l.current_minor IS NOT NULL AND l.current_minor<>0"):
            found |= {(row[0], row[1], row[2], key) for key, categories in PAYROLL_CATEGORIES.items() if row[3] in categories and section in (None, key)}
        return sorted(found, key=lambda item: (item[1], item[3]))

    def contributions_match(self, db, account_id, lines):
        """An account's statement lists the employee contributions these pay stub lines made: one line's amount within a week, or a
        quarter's lines added up (all of them, or one kind of line, such as the pre-tax deferrals without the Roth)."""
        mine = [line for line in lines if line["contribution_source"] == "employee"]
        for event in db.execute("SELECT event_date,amount_minor FROM investment_events WHERE account_id=? AND event_type='contribution' "
                                "AND contribution_source='employee' AND review_status<>'rejected'", (account_id,)):
            day = date.fromisoformat(event["event_date"])
            near = [line for line in mine if abs((date.fromisoformat(line["pay_date"]) - day).days) <= PAYROLL_MATCH_DAYS]
            quarter = [line for line in mine if 0 <= (day - date.fromisoformat(line["pay_date"])).days < PAYROLL_QUARTER_DAYS]
            sums = {sum(line["amount_minor"] for line in quarter)} | {sum(line["amount_minor"] for line in quarter if line["description"] == kind)
                                                                     for kind in {line["description"] for line in quarter}}
            if any(line["amount_minor"] == event["amount_minor"] for line in near) or (quarter and event["amount_minor"] in sums):
                return True
        return False

    def payroll_candidates(self, db, employer_id, employer, currency, section):
        """Open accounts that could hold an employer's contributions of one kind, and the one the documents point to: the only one
        whose name or institution shares a word with the employer (an "Acme 401(k) Plan"), else the only one whose statement lists
        these contributions, else the only one there is. None when that stays ambiguous."""
        accounts = [dict(row) for row in db.execute(
            "SELECT a.* FROM investment_accounts a JOIN investment_kinds k ON k.key=a.kind WHERE k.section=? AND a.currency=? AND a.archived_at IS NULL "
            "AND a.payroll_merchant_id IS NULL AND coalesce(a.payroll_link,'auto')='auto' ORDER BY a.name,a.id", (section, currency))]
        words = name_tokens(employer)
        named = [account for account in accounts if words & name_tokens(f"{account['name']} {account['institution']}")]
        if len(named) == 1:
            return accounts, named[0]
        lines = self.payroll_lines(db, employer_id, section, currency)
        listed = [account for account in named or accounts if self.contributions_match(db, account["id"], lines)]
        if len(listed) == 1:
            return accounts, listed[0]
        return accounts, accounts[0] if len(accounts) == 1 else None

    def link_payroll(self, db):
        """Link each employer's 401(k) and HSA pay stub lines to the account they go to, when the documents make that clear. Links
        the user chose (or refused) are never changed."""
        for employer_id, employer, currency, section in self.payroll_employers(db):
            if db.execute("SELECT 1 FROM investment_accounts a JOIN investment_kinds k ON k.key=a.kind WHERE a.payroll_merchant_id=? AND k.section=? "
                          "AND a.archived_at IS NULL", (employer_id, section)).fetchone():
                continue
            _, chosen = self.payroll_candidates(db, employer_id, employer, currency, section)
            if chosen:
                db.execute("UPDATE investment_accounts SET payroll_merchant_id=?,payroll_link='auto',updated_at=? WHERE id=?", (employer_id, now(), chosen["id"]))

    def refresh_payroll_links(self):
        with self.store.connection() as db:
            self.link_payroll(db)

    def payroll_questions(self, db):
        """Employers whose contributions have no account: several could hold them, or none exists yet."""
        questions = []
        for employer_id, employer, currency, section in self.payroll_employers(db):
            if db.execute("SELECT 1 FROM investment_accounts a JOIN investment_kinds k ON k.key=a.kind WHERE a.payroll_merchant_id=? AND k.section=? "
                          "AND a.archived_at IS NULL", (employer_id, section)).fetchone():
                continue
            accounts, chosen = self.payroll_candidates(db, employer_id, employer, currency, section)
            if chosen is None:
                questions.append({"employer_id": employer_id, "employer": employer, "section": section, "label": PAYROLL_LABELS[section], "currency": currency,
                                  "accounts": [{"id": account["id"], "name": account["name"]} for account in accounts]})
        return questions

    def choose_payroll_account(self, account_id, employer_id):
        """The user's answer to a payroll question: this account gets that employer's contributions."""
        account = self.get(account_id)
        update = AccountUpdate(name=account["name"], kind=account["kind"], institution=account["institution"],
                               annual_rate_percent=None if account["rate_is_default"] else account["annual_rate_percent"],
                               tax_treatment=account["tax_treatment"] if account["tax_overridden"] else None, ledger_account_id=account["ledger_account_id"],
                               payroll_employer_id=employer_id, beneficiary=account["beneficiary"], plan_state=account["plan_state"],
                               monthly_contribution=format_minor(account["monthly_contribution_minor"], account["currency"]) if account["monthly_contribution_minor"] is not None else None)
        return self.update(account_id, update)

    # Changing ----------------------------------------------------------------------------------------------------
    def settings(self, db, value: AccountUpdate, currency, account_id=None):
        section = self.kind(db, value.kind)["section"]
        payroll: dict[str, int | str | None] = {"payroll_merchant_id": None, "payroll_link": None}  # Blank: matched automatically after saving.
        if value.payroll_employer_id == 0:
            payroll["payroll_link"] = "none"
        elif value.payroll_employer_id is not None:
            if section not in PAYROLL_CATEGORIES:
                raise ValueError("Only retirement accounts and HSAs get contributions from pay.")
            employer = db.execute("SELECT m.canonical_name FROM merchants m WHERE m.id=? AND EXISTS(SELECT 1 FROM income_records r WHERE r.payer_merchant_id=m.id)",
                                  (value.payroll_employer_id,)).fetchone()
            if employer is None:
                raise ValueError("Choose an employer from your pay stubs.")
            other = db.execute("SELECT a.id,a.name,a.payroll_link FROM investment_accounts a JOIN investment_kinds k ON k.key=a.kind WHERE a.payroll_merchant_id=? "
                               "AND k.section=? AND a.archived_at IS NULL AND a.id IS NOT ?", (value.payroll_employer_id, section, account_id)).fetchone()
            if other and other["payroll_link"] == "user":
                raise ValueError(f"{employer[0]}'s {PAYROLL_LABELS[section]} contributions already go to {other['name']}.")
            if other:  # Your choice replaces a match made from the documents.
                db.execute("UPDATE investment_accounts SET payroll_merchant_id=NULL,updated_at=? WHERE id=?", (now(), other["id"]))
            payroll = {"payroll_merchant_id": value.payroll_employer_id, "payroll_link": "user"}
        monthly = to_minor(value.monthly_contribution, currency) if value.monthly_contribution else None
        if monthly is not None and monthly < 0:
            raise ValueError("Enter a monthly contribution of zero or more.")
        if value.ledger_account_id is not None:
            ledger = db.execute("SELECT * FROM accounts WHERE id=?", (value.ledger_account_id,)).fetchone()
            if ledger is None or ledger["account_type"] not in LINKABLE_TYPES:
                raise ValueError("Link a savings, checking or brokerage account; cards and loans can't hold investments.")
            if ledger["currency"] != currency:
                raise ValueError("The linked account uses another currency.")
            other = db.execute("SELECT name FROM investment_accounts WHERE ledger_account_id=? AND id IS NOT ?", (value.ledger_account_id, account_id)).fetchone()
            if other:
                raise ValueError(f"That account is already linked to {other['name']}.")
        # A 529's beneficiary and plan state; other accounts keep none.
        education = section == "education"
        beneficiary = " ".join((value.beneficiary or "").split()) or None if education else None
        return {"name": " ".join(value.name.split()), "kind": value.kind, "institution": " ".join(value.institution.split()),
                "annual_rate_bp": rate_bp(value.annual_rate_percent) if value.annual_rate_percent is not None else None,
                "tax_treatment": value.tax_treatment, "ledger_account_id": value.ledger_account_id, **payroll, "monthly_contribution_minor": monthly,
                "beneficiary": beneficiary, "plan_state": value.plan_state.upper() if education and value.plan_state else None}

    def add(self, value: AccountInput):
        """An account the user adds, with its value today; the user's own values count at once."""
        currency = currency_code(value.currency)
        with self.store.connection() as db:
            if not value.value and self.kind(db, value.kind)["value_model"] != "income":
                raise ValueError("Enter the account's value and its date.")
            columns = {**self.settings(db, value, currency), "currency": currency, "source": "manual", "created_at": now(), "updated_at": now()}
            account_id = db.execute(f"INSERT INTO investment_accounts({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values())).lastrowid
            if value.value and value.as_of:
                self.write_value(db, account_id, currency, ValueInput(value=value.value, as_of=value.as_of))
            self.link_payroll(db)
        return self.get(account_id)

    def update(self, account_id, value: AccountUpdate):
        """Rename, reclassify or link an account; a statement's guessed kind is corrected here."""
        account = self.get(account_id)
        with self.store.connection() as db:
            columns = {**self.settings(db, value, account["currency"], account_id), "updated_at": now()}
            db.execute(f"UPDATE investment_accounts SET {','.join(f'{key}=?' for key in columns)} WHERE id=?", (*columns.values(), account_id))
            self.link_payroll(db)
        return self.get(account_id)

    def record_value(self, account_id, value: ValueInput):
        account = self.get(account_id)
        with self.store.connection() as db:
            self.write_value(db, account_id, account["currency"], value)
        return self.get(account_id)

    @staticmethod
    def write_value(db, account_id, currency, value: ValueInput):
        amount = to_minor(value.value, currency)
        if amount < 0:
            raise ValueError("Enter a value of zero or more.")
        # A value the user types for a date replaces whatever was recorded for that date.
        existing = db.execute("SELECT id FROM investment_valuations WHERE account_id=? AND holding_id IS NULL AND as_of=?", (account_id, value.as_of)).fetchone()
        if existing:
            db.execute("UPDATE investment_valuations SET value_minor=?,source='manual',review_status='verified',document_id=NULL,blob_hash=NULL,"
                       "extraction_run_id=NULL,validation_json='[]',updated_at=? WHERE id=?", (amount, now(), existing["id"]))
        else:
            db.execute("INSERT INTO investment_valuations(account_id,as_of,value_minor,source,review_status,created_at,updated_at) VALUES(?,?,?,'manual','verified',?,?)",
                       (account_id, value.as_of, amount, now(), now()))

    def set_pension(self, account_id, value: PensionInput):
        """A pension's terms (its benefit statement's monthly amount, start date, raise and survivor share). Counts at once."""
        account = self.get(account_id)
        if not account["is_income"]:
            raise ValueError("Only a pension has a monthly benefit; change the account's kind to Pension first.")
        currency = account["currency"]
        benefit = to_minor(value.monthly_benefit, currency)
        lump = to_minor(value.lump_sum, currency) if value.lump_sum else None
        if benefit < 0 or (lump is not None and lump < 0):
            raise ValueError("Enter amounts of zero or more.")
        cola = rate_bp(value.cola_percent)
        if cola > 2000:
            raise ValueError("Enter a yearly raise of 20% or less.")
        with self.store.connection() as db:
            db.execute("INSERT INTO pension_terms(account_id,monthly_benefit_minor,start_date,cola_bp,survivor_pct,lump_sum_minor,updated_at) VALUES(?,?,?,?,?,?,?) "
                       "ON CONFLICT(account_id) DO UPDATE SET monthly_benefit_minor=excluded.monthly_benefit_minor,start_date=excluded.start_date,"
                       "cola_bp=excluded.cola_bp,survivor_pct=excluded.survivor_pct,lump_sum_minor=excluded.lump_sum_minor,updated_at=excluded.updated_at",
                       (account_id, benefit, value.start_date, cola, value.survivor_percent, lump, now()))
        return self.get(account_id)

    def add_event(self, account_id, value: EventInput):
        """Activity you record (a 529 withdrawal, a contribution): it counts at once, like a value you type."""
        account = self.get(account_id)
        amount = to_minor(value.amount, account["currency"])
        if amount <= 0:
            raise ValueError("Enter an amount more than zero.")
        if value.event_type in ("qualified_withdrawal", "nonqualified_withdrawal") and not account["is_education"]:
            raise ValueError("Only a 529 has qualified and non-qualified withdrawals.")
        with self.store.connection() as db:
            db.execute("INSERT INTO investment_events(account_id,event_date,event_type,contribution_source,amount_minor,note,review_status,created_at) "
                       "VALUES(?,?,?,?,?,?,'verified',?)", (account_id, value.event_date, value.event_type,
                                                            "personal" if value.event_type == "contribution" else None, amount, " ".join(value.note.split()), now()))
        return self.get(account_id)

    def classify_withdrawal(self, event_id, value: WithdrawalKind):
        """Say whether a 529 withdrawal paid for qualified education costs. Only its kind changes; the amount stays as recorded."""
        with self.store.connection() as db:
            row = db.execute("SELECT e.*,k.section FROM investment_events e JOIN investment_accounts a ON a.id=e.account_id "
                             "JOIN investment_kinds k ON k.key=a.kind WHERE e.id=?", (event_id,)).fetchone()
            if row is None:
                raise ValueError("Activity not found.")
            if row["section"] != "education" or row["event_type"] not in WITHDRAWAL_TYPES:
                raise ValueError("Only a 529's withdrawals are qualified or not.")
            db.execute("UPDATE investment_events SET event_type=? WHERE id=?", ("qualified_withdrawal" if value.qualified else "nonqualified_withdrawal", event_id))
        return self.get(row["account_id"])

    def archive(self, account_id):
        self.get(account_id)
        with self.store.connection() as db:
            db.execute("UPDATE investment_accounts SET archived_at=?,updated_at=? WHERE id=?", (now(), now(), account_id))
        return {"id": account_id, "archived": True}

    def review(self, valuation_id, status):
        """Confirm or reject a value read from a statement; confirmed values count. The holdings and activity read from the
        same statement follow the decision. Audited like other reviews."""
        if status not in ("verified", "rejected", "proposed"):
            raise ValueError("Choose confirm, reject or undo.")
        current = self.valuation(valuation_id)
        if current["source"] != "statement" or current["holding_id"] is not None:
            raise ValueError("Only values read from statements are reviewed; values you enter count at once.")
        with self.store.connection() as db:
            db.execute("UPDATE investment_valuations SET review_status=?,updated_at=? WHERE id=?", (status, now(), valuation_id))
            db.execute("UPDATE investment_valuations SET review_status=?,updated_at=? WHERE account_id=? AND as_of=? AND holding_id IS NOT NULL AND source='statement'",
                       (status, now(), current["account_id"], current["as_of"]))
            if current["blob_hash"]:
                db.execute("UPDATE investment_events SET review_status=? WHERE account_id=? AND blob_hash=?", (status, current["account_id"], current["blob_hash"]))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('investment_valuation',?,?,?,'',?)",
                       (valuation_id, current["review_status"], status, now()))
        return self.valuation(valuation_id)

    @staticmethod
    def account_key(record):
        identity = record.get("last_four") or normalize_name(record.get("account_name")) or "-"
        return f"{normalize_name(' '.join(record['institution'].split()))}|{identity}|{record['currency']}"

    def account_for(self, db, record, create=True):
        """The account a document is about: one per institution and account (its last four digits, else its printed name) and
        currency. A new one takes the kind its printed words name; None when it isn't known and create is False."""
        account = db.execute("SELECT id FROM investment_accounts WHERE account_key=?", (self.account_key(record),)).fetchone()
        if account is not None or not create:
            return account["id"] if account else None
        institution = " ".join(record["institution"].split())
        kind = record.get("investment_kind") or "brokerage"
        kind = kind if db.execute("SELECT 1 FROM investment_kinds WHERE key=?", (kind,)).fetchone() else "other"
        label = record.get("account_name") or db.execute("SELECT label FROM investment_kinds WHERE key=?", (kind,)).fetchone()["label"]
        name = f"{institution} {label}{' ' + record['last_four'] if record.get('last_four') else ''}"[:80]
        return db.execute("INSERT INTO investment_accounts(kind,name,institution,currency,account_key,source,created_at,updated_at) "
                          "VALUES(?,?,?,?,?,'statement',?,?)", (kind, name, institution, record["currency"], self.account_key(record), now(), now())).lastrowid

    def publish_statement(self, record, source):
        """An investment statement's ending value, holdings and activity for its account (docs/investments.md). One account per
        institution and account; each statement date adds a value, older statements fill in history. A value the user already
        decided on for that date and document is kept, with what that statement listed."""
        values = {"value_minor": record["value_minor"], "blob_hash": source["blob_hash"], "document_id": source["document_id"],
                  "extraction_run_id": source["run_id"], "validation_json": json.dumps(record["issues"]), "updated_at": now()}
        with self.store.connection() as db:
            account_id = self.account_for(db, record)
            existing = db.execute("SELECT * FROM investment_valuations WHERE account_id=? AND holding_id IS NULL AND as_of=?",
                                  (account_id, record["period_end"])).fetchone()
            result = {"record_type": "investment_valuation", "account_id": account_id}
            if existing:
                # Re-extracting a statement the user already decided on, or a value they typed for that date, changes nothing.
                if existing["source"] == "manual" or (existing["blob_hash"] == source["blob_hash"] and existing["review_status"] in ("verified", "rejected")):
                    return {**result, "id": existing["id"], "status": "kept_reviewed"}
                # A market-price quote for the same date gives way to the statement.
                db.execute(f"UPDATE investment_valuations SET {','.join(f'{column}=?' for column in values)},source='statement',review_status='proposed' WHERE id=?",
                           (*values.values(), existing["id"]))
                valuation_id, status = existing["id"], "published"
            else:
                newer = db.execute("SELECT 1 FROM investment_valuations WHERE account_id=? AND holding_id IS NULL AND as_of>? AND review_status<>'rejected'",
                                   (account_id, record["period_end"])).fetchone()
                columns = {**values, "account_id": account_id, "as_of": record["period_end"], "source": "statement", "review_status": "proposed", "created_at": now()}
                valuation_id = db.execute(f"INSERT INTO investment_valuations({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values())).lastrowid
                status = "history" if newer else "published"
            self.write_holdings(db, account_id, record, source, current=status != "history")
            events = self.write_events(db, account_id, record, source)
            self.link_payroll(db)  # Its name or contributions may say whose pay stub lines it holds.
        return {**result, "id": valuation_id, "status": status, "holdings": len(record.get("holdings") or []), "activity": events}

    @staticmethod
    def write_holdings(db, account_id, record, source, current):
        """The statement's holdings as of its date, replacing what an earlier reading of that date listed. Terms (rate,
        maturity) are updated only from the newest statement."""
        db.execute("DELETE FROM investment_valuations WHERE account_id=? AND as_of=? AND holding_id IS NOT NULL AND source IN ('statement','quote')",
                   (account_id, record["period_end"]))
        for holding in record.get("holdings") or []:
            terms = {"instrument_class": holding["instrument_class"], "name": holding["name"][:200], "identifier": holding.get("identifier"),
                     "rate_bp": holding.get("rate_bp"), "maturity_date": holding.get("maturity_date"), "updated_at": now()}
            found = db.execute("SELECT id FROM holdings WHERE account_id=? AND holding_key=?", (account_id, holding_key(holding))).fetchone()
            if found is None:
                holding_id = db.execute(f"INSERT INTO holdings(account_id,holding_key,created_at,{','.join(terms)}) VALUES(?,?,?,{','.join('?' * len(terms))})",
                                        (account_id, holding_key(holding), now(), *terms.values())).lastrowid
            else:
                holding_id = found["id"]
                if current:
                    db.execute(f"UPDATE holdings SET {','.join(f'{column}=?' for column in terms)} WHERE id=?", (*terms.values(), holding_id))
            if holding.get("value_minor") is None:
                continue  # Listed without a value: the holding is known, but has no value to record.
            db.execute("INSERT OR REPLACE INTO investment_valuations(account_id,holding_id,as_of,value_minor,quantity,price_minor,cost_basis_minor,source,"
                       "document_id,blob_hash,extraction_run_id,review_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'statement',?,?,?,'proposed',?,?)",
                       (account_id, holding_id, record["period_end"], holding["value_minor"], holding.get("quantity"), holding.get("price_minor"),
                        holding.get("cost_basis_minor"), source["document_id"], source["blob_hash"], source["run_id"], now(), now()))

    @staticmethod
    def write_events(db, account_id, record, source):
        """The statement's activity, replacing an earlier reading of this document that no one decided on. An entry another
        statement already recorded (overlapping periods) is not added twice."""
        db.execute("DELETE FROM investment_events WHERE account_id=? AND blob_hash=? AND review_status='proposed'", (account_id, source["blob_hash"]))
        if db.execute("SELECT 1 FROM investment_events WHERE account_id=? AND blob_hash=?", (account_id, source["blob_hash"])).fetchone():
            return 0  # Decided on already: kept as the user left it.
        added = 0
        for event in record.get("activity") or []:
            holding = db.execute("SELECT id FROM holdings WHERE account_id=? AND holding_key=?", (account_id, holding_key(event))).fetchone() \
                if event.get("identifier") else None
            if db.execute("SELECT 1 FROM investment_events WHERE account_id=? AND event_date=? AND event_type=? AND amount_minor=? "
                          "AND coalesce(contribution_source,'')=? AND review_status<>'rejected'",
                          (account_id, event["event_date"], event["event_type"], event["amount_minor"], event.get("contribution_source") or "")).fetchone():
                continue
            db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,contribution_source,amount_minor,quantity,document_id,"
                       "blob_hash,note,review_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'proposed',?)",
                       (account_id, holding["id"] if holding else None, event["event_date"], event["event_type"], event.get("contribution_source"),
                        event["amount_minor"], event.get("quantity"), source["document_id"], source["blob_hash"], event["name"][:200], now()))
            added += 1
        return added

    # Purchase confirmations -------------------------------------------------------------------------------------------
    def publish_confirmation(self, record, source):
        """A trade, CD or Treasury confirmation: its holdings with their terms and the buys or sells it records, all waiting for
        review with the confirmation. Re-reading one the user decided on changes nothing; otherwise it replaces the earlier reading."""
        with self.store.connection() as db:
            account_id = self.account_for(db, record)
            result = {"record_type": "investment_confirmation", "account_id": account_id}
            existing = db.execute("SELECT * FROM investment_confirmations WHERE blob_hash=?", (source["blob_hash"],)).fetchone()
            if existing and existing["review_status"] in ("verified", "rejected"):
                return {**result, "account_id": existing["account_id"], "id": existing["id"], "status": "kept_reviewed"}
            values = {"account_id": account_id, "document_id": source["document_id"], "extraction_run_id": source["run_id"], "trade_date": record["trade_date"],
                      "validation_json": json.dumps(record["issues"]), "review_status": "proposed", "updated_at": now()}
            if existing:
                confirmation_id = existing["id"]
                db.execute(f"UPDATE investment_confirmations SET {','.join(f'{column}=?' for column in values)} WHERE id=?", (*values.values(), confirmation_id))
                db.execute("DELETE FROM investment_events WHERE confirmation_id=?", (confirmation_id,))
            else:
                columns = {**values, "blob_hash": source["blob_hash"], "created_at": now()}
                confirmation_id = db.execute(f"INSERT INTO investment_confirmations({','.join(columns)}) VALUES({','.join('?' * len(columns))})",
                                             tuple(columns.values())).lastrowid
            for trade in record["trades"]:
                holding_id = self.confirmed_holding(db, account_id, confirmation_id, trade)
                event_type = TRADE_ACTIONS[trade["action"]]
                db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,contribution_source,amount_minor,quantity,document_id,blob_hash,"
                           "note,review_status,confirmation_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'proposed',?,?)",
                           (account_id, holding_id, record["trade_date"], event_type, "personal" if event_type == "contribution" else None, trade["amount_minor"],
                            trade.get("quantity"), source["document_id"], source["blob_hash"], trade["name"][:200], confirmation_id, now()))
        return {**result, "id": confirmation_id, "status": "published", "trades": len(record["trades"])}

    @staticmethod
    def confirmed_holding(db, account_id, confirmation_id, trade):
        """The holding a trade is in, created when it's new. A purchase of a CD or Treasury sets its terms (principal, rate, face,
        issue and maturity dates); a later statement of the same holding keeps them."""
        if trade["action"] == "deposit":
            return None
        key = holding_key(trade)
        found = db.execute("SELECT id FROM holdings WHERE account_id=? AND holding_key=?", (account_id, key)).fetchone()
        terms = {}
        if trade["action"] in ("buy", "reinvest") and trade["instrument_class"] in TERM_CLASSES:
            maturity = trade.get("maturity_date")
            if not maturity and trade["instrument_class"] == "i_bond" and trade.get("issue_date"):
                maturity = add_months(trade["issue_date"][:7] + "-01", IBOND_MONTHS)  # 30 years unless printed otherwise.
            terms = {"principal_minor": trade.get("principal_minor") or trade["amount_minor"], "rate_bp": trade.get("rate_bp"), "face_minor": trade.get("face_minor"),
                     "issue_date": trade.get("issue_date"), "maturity_date": maturity, "redeemable_date": trade.get("redeemable_date")}
        if found is None:
            columns = {"account_id": account_id, "holding_key": key, "instrument_class": trade["instrument_class"], "name": trade["name"][:200],
                       "identifier": trade.get("identifier"), "source": "confirmation", "confirmation_id": confirmation_id,
                       **terms, "created_at": now(), "updated_at": now()}
            return db.execute(f"INSERT INTO holdings({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values())).lastrowid
        if terms:
            db.execute(f"UPDATE holdings SET {','.join(f'{column}=?' for column in terms)},confirmation_id=?,archived_at=NULL,updated_at=? WHERE id=?",
                       (*terms.values(), confirmation_id, now(), found["id"]))
        return found["id"]

    def confirmation_view(self, db, row, currency):
        row = dict(row)
        row["issues"] = json.loads(row.pop("validation_json") or "[]")
        trades = [dict(event) for event in db.execute("SELECT e.*,h.instrument_class,h.rate_bp,h.maturity_date,h.face_minor FROM investment_events e "
                                                       "LEFT JOIN holdings h ON h.id=e.holding_id WHERE e.confirmation_id=? ORDER BY e.id", (row["id"],))]
        return {**row, "trades": [{"event_type": trade["event_type"], "type_label": ACTIVITY_TYPES.get(trade["event_type"], trade["event_type"]), "name": trade["note"],
                                   "quantity": trade["quantity"], "amount": money(trade["amount_minor"], currency), "rate_percent": percent_text(trade["rate_bp"]),
                                   "maturity_date": trade["maturity_date"], "face": money(trade["face_minor"], currency) if trade["face_minor"] is not None else None}
                                  for trade in trades]}

    def confirmation(self, confirmation_id):
        """One confirmation with its account and trades, for Review and the document inspector."""
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM investment_confirmations WHERE id=?", (confirmation_id,)).fetchone()
            if row is None:
                raise ValueError("Investment confirmation not found.")
            account = self.rows(db, True, row["account_id"])[0]
            view = self.confirmation_view(db, row, account["currency"])
        return {**view, "record_type": "investment_confirmation", "review_path": f"/api/investments/confirmations/{confirmation_id}/review",
                "name": account["name"], "kind_label": account["kind_label"], "currency": account["currency"],
                "account": {key: account[key] for key in ("id", "name", "kind", "kind_label", "institution", "currency")}}

    def review_confirmation(self, confirmation_id, status):
        """Confirm or reject a confirmation; its trades follow, and confirmed CDs and Treasuries start counting. Audited."""
        if status not in ("verified", "rejected", "proposed"):
            raise ValueError("Choose confirm, reject or undo.")
        current = self.confirmation(confirmation_id)
        with self.store.connection() as db:
            db.execute("UPDATE investment_confirmations SET review_status=?,updated_at=? WHERE id=?", (status, now(), confirmation_id))
            db.execute("UPDATE investment_events SET review_status=? WHERE confirmation_id=?", (status, confirmation_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('investment_confirmation',?,?,?,'',?)",
                       (confirmation_id, current["review_status"], status, now()))
        return self.confirmation(confirmation_id)

    # Holdings the user adds, and maturities ----------------------------------------------------------------------------
    def holding_columns(self, value: HoldingInput, currency):
        principal = to_minor(value.principal, currency)
        face = to_minor(value.face_value, currency) if value.face_value else None
        if principal <= 0 or (face is not None and face < principal):
            raise ValueError("Enter what was paid (more than zero), and a face value no smaller than it.")
        ibond = value.instrument_class == "i_bond"
        redeemable = add_months(value.issue_date, 12) if ibond else None
        # An I bond earns interest for 30 years unless its maturity is printed otherwise.
        maturity = value.maturity_date or (add_months(value.issue_date[:7] + "-01", IBOND_MONTHS) if ibond else None)
        return {"instrument_class": value.instrument_class, "name": " ".join(value.name.split()), "principal_minor": principal, "face_minor": face,
                "rate_bp": rate_bp(value.annual_rate_percent) if value.annual_rate_percent is not None else None, "issue_date": value.issue_date,
                "maturity_date": maturity, "redeemable_date": redeemable, "rollover": int(value.rollover), "updated_at": now()}

    def add_holding(self, account_id, value: HoldingInput):
        """A CD, Treasury or bond the user enters: it counts at once, estimated from its terms."""
        account = self.get(account_id)
        columns = {**self.holding_columns(value, account["currency"]), "account_id": account_id, "source": "manual", "created_at": now()}
        columns["holding_key"] = f"manual:{normalize_name(columns['name'])}|{value.issue_date}"
        with self.store.connection() as db:
            if db.execute("SELECT 1 FROM holdings WHERE account_id=? AND holding_key=?", (account_id, columns["holding_key"])).fetchone():
                raise ValueError("This account already has that holding for that date.")
            db.execute(f"INSERT INTO holdings({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values()))
        return self.get(account_id)

    def holding(self, db, holding_id):
        row = db.execute("SELECT h.*,a.currency FROM holdings h JOIN investment_accounts a ON a.id=h.account_id WHERE h.id=?", (holding_id,)).fetchone()
        if row is None:
            raise ValueError("Holding not found.")
        return row

    def update_holding(self, holding_id, value: HoldingInput):
        """Correct a holding's terms (its rate, maturity, face value, or whether it renews)."""
        with self.store.connection() as db:
            row = self.holding(db, holding_id)
            columns = self.holding_columns(value, row["currency"])
            db.execute(f"UPDATE holdings SET {','.join(f'{column}=?' for column in columns)} WHERE id=?", (*columns.values(), holding_id))
        return self.get(row["account_id"])

    def archive_holding(self, holding_id):
        with self.store.connection() as db:
            row = self.holding(db, holding_id)
            db.execute("UPDATE holdings SET archived_at=?,updated_at=? WHERE id=?", (now(), now(), holding_id))
        return self.get(row["account_id"])

    def mark_matured(self, holding_id, value: MaturedInput):
        """The user's answer for a CD or Treasury that matured: paid out or renewed. Records the maturity with what it paid (its
        terms' value at maturity unless given) and closes the holding; a renewal is then added as a new holding."""
        with self.store.connection() as db:
            row = self.holding(db, holding_id)
            if row["archived_at"]:
                raise ValueError("This holding is already closed.")
            if not row["maturity_date"]:
                raise ValueError("This holding has no maturity date.")
            terms = next((holding for holding in self.term_holdings(db, row["account_id"]) if holding["id"] == holding_id), None)
            paid = to_minor(value.amount, row["currency"]) if value.amount else terms["value_on"](row["maturity_date"]) if terms else row["principal_minor"]
            if paid is None or paid < 0:
                raise ValueError("Enter what was paid out.")
            db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,amount_minor,note,review_status,created_at) "
                       "VALUES(?,?,?,'maturity',?,?,'verified',?)", (row["account_id"], holding_id, row["maturity_date"], paid,
                                                                     "Renewed" if value.outcome == "rollover" else "Paid out", now()))
            db.execute("UPDATE holdings SET archived_at=?,updated_at=? WHERE id=?", (now(), now(), holding_id))
        return self.get(row["account_id"])

    def maturities(self, days=MATURITY_WINDOW_DAYS, currency=None):
        """CDs, Treasuries and bonds maturing (or an I bond's lock ending) within the next days, and those that matured with no
        answer yet: no statement or value recorded since, and not closed. Soonest first."""
        until = (date.fromisoformat(self.today) + timedelta(days=days)).isoformat()
        found = []
        with self.store.connection() as db:
            for account in self.rows(db):
                if currency and account["currency"] != currency:
                    continue
                newest = db.execute("SELECT max(as_of) FROM investment_valuations WHERE account_id=? AND holding_id IS NULL AND review_status<>'rejected'",
                                    (account["id"],)).fetchone()[0]
                for holding in self.term_holdings(db, account["id"]):
                    if not holding["counts"]:
                        continue
                    for kind, day in (("matures", holding["maturity_date"]), ("redeemable", holding["redeemable_date"])):
                        if not day or day > until or (kind == "redeemable" and day < self.today):
                            continue
                        if day < self.today and newest and newest >= day and holding["source"] == "statement":
                            continue  # A statement since then already shows where the money went.
                        found.append({"holding_id": holding["id"], "name": holding["name"], "account_id": account["id"], "account": account["name"],
                                      "kind": kind, "date": day, "state": "matured" if day <= self.today and kind == "matures" else "due",
                                      "rollover": bool(holding["rollover"]), "currency": account["currency"],
                                      "amount": money(holding["value_on"](day), account["currency"])})
        return sorted(found, key=lambda row: (row["date"], row["name"]))

    # Tax lots, 1099s and 5498s -----------------------------------------------------------------------------------------
    def add_lot(self, holding_id, value: LotInput):
        """Shares bought before the documents here begin, so their sale has a cost."""
        with self.store.connection() as db:
            row = self.holding(db, holding_id)
            cost = to_minor(value.cost, row["currency"])
            if cost < 0:
                raise ValueError("Enter a cost of zero or more.")
            db.execute("INSERT INTO tax_lots(account_id,holding_id,acquired_date,quantity,cost_minor,created_at) VALUES(?,?,?,?,?,?)",
                       (row["account_id"], holding_id, value.acquired_date, lot_shares(shares(value.quantity)), cost, now()))
        return self.get(row["account_id"])

    def delete_lot(self, lot_id):
        with self.store.connection() as db:
            row = db.execute("SELECT account_id FROM tax_lots WHERE id=?", (lot_id,)).fetchone()
            if row is None:
                raise ValueError("Lot not found; only lots you entered can be removed.")
            db.execute("DELETE FROM tax_lots WHERE id=?", (lot_id,))
        return self.get(row["account_id"])

    def form_account(self, db, record):
        """The account a tax form reports on: by institution and last four digits, else the only account at that institution in
        its currency. None when no account here matches; the form is still kept."""
        found = self.account_for(db, record, create=False)
        if found is not None:
            return found
        matches = [row["id"] for row in db.execute("SELECT id,institution FROM investment_accounts WHERE currency=? AND archived_at IS NULL", (record["currency"],))
                   if normalize_name(row["institution"]) == normalize_name(record["institution"])]
        return matches[0] if len(matches) == 1 else None

    def publish_tax_form(self, record, source):
        """A 1099, 5498 or 1098 (or a consolidated 1099) and its boxes, waiting for review; re-reading one the user decided on changes nothing."""
        with self.store.connection() as db:
            existing = db.execute("SELECT * FROM tax_forms WHERE blob_hash=?", (source["blob_hash"],)).fetchone()
            if existing and existing["review_status"] in ("verified", "rejected"):
                return {"record_type": "tax_form", "id": existing["id"], "account_id": existing["account_id"], "status": "kept_reviewed"}
            values = {"account_id": self.form_account(db, record), "institution": " ".join(record["institution"].split()), "last_four": record.get("last_four"),
                      "tax_year": record["tax_year"], "currency": record["currency"], "document_id": source["document_id"], "extraction_run_id": source["run_id"],
                      "validation_json": json.dumps(record["issues"]), "review_status": "proposed", "updated_at": now()}
            if existing:
                form_id = existing["id"]
                db.execute(f"UPDATE tax_forms SET {','.join(f'{column}=?' for column in values)} WHERE id=?", (*values.values(), form_id))
                db.execute("DELETE FROM tax_form_boxes WHERE form_id=?", (form_id,))
            else:
                columns = {**values, "blob_hash": source["blob_hash"], "created_at": now()}
                form_id = db.execute(f"INSERT INTO tax_forms({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values())).lastrowid
            db.executemany("INSERT INTO tax_form_boxes(form_id,form,box,label,amount_minor,locator_json) VALUES(?,?,?,?,?,?)",
                           [(form_id, box["form"], box["box"], box["label"], box["amount_minor"], json.dumps(box["locator"])) for box in record["boxes"]])
        return {"record_type": "tax_form", "id": form_id, "account_id": values["account_id"], "status": "published", "boxes": len(record["boxes"])}

    def tax_form(self, form_id):
        with self.store.connection() as db:
            row = db.execute("SELECT f.*,a.name AS account_name FROM tax_forms f LEFT JOIN investment_accounts a ON a.id=f.account_id WHERE f.id=?",
                             (form_id,)).fetchone()
            if row is None:
                raise ValueError("Tax form not found.")
            return self.tax_form_view(db, row)

    @staticmethod
    def tax_form_view(db, row):
        form = dict(row)
        form["issues"] = json.loads(form.pop("validation_json") or "[]")
        boxes = [dict(box) for box in db.execute("SELECT form,box,label,amount_minor FROM tax_form_boxes WHERE form_id=? ORDER BY id", (form["id"],))]
        forms = list(dict.fromkeys(box["form"] for box in boxes))
        return {**form, "record_type": "tax_form", "forms": forms, "kind_label": "Tax form",
                "name": f"{form['institution']} {', '.join(forms) or 'tax form'} for {form['tax_year']}",
                "review_path": f"/api/investments/tax-forms/{form['id']}/review",
                "boxes": [{**box, "amount": money(box["amount_minor"], form["currency"])} for box in boxes]}

    def review_tax_form(self, form_id, status):
        if status not in ("verified", "rejected", "proposed"):
            raise ValueError("Choose confirm, reject or undo.")
        current = self.tax_form(form_id)
        with self.store.connection() as db:
            db.execute("UPDATE tax_forms SET review_status=?,updated_at=? WHERE id=?", (status, now(), form_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('tax_form',?,?,?,'',?)",
                       (form_id, current["review_status"], status, now()))
        return self.tax_form(form_id)

    def measures(self, db, account, year):
        """What is recorded for an account in a tax year, in the terms tax forms report: confirmed interest, dividends, withdrawals
        and contributions (from pay stubs too), and sales matched to lots."""
        totals = {"interest": 0, "dividends": 0, "withdrawals": 0, "contributions": 0, "proceeds": 0, "cost": 0}
        for event in self.events(db, account):
            if event["review_status"] == "verified" and event["event_date"][:4] == str(year):
                key = "withdrawals" if event["event_type"] in WITHDRAWAL_TYPES else \
                    {"interest": "interest", "dividend": "dividends", "contribution": "contributions"}.get(event["event_type"])
                if key:
                    totals[key] += event["amount_minor"]
        sales = realized(db, [account["id"]], year)
        totals["proceeds"], totals["cost"] = sales["proceeds_minor"], sales["cost_minor"]
        return totals

    def tax_year(self, year):
        """One tax year: each form's boxes beside what is recorded for its account (the difference shown), and realized gains in
        taxable accounts. Forms rejected in review are left out; one waiting for review is shown with its status."""
        with self.store.connection() as db:
            accounts = {account["id"]: account for account in self.rows(db, True)}
            years = sorted({row[0] for row in db.execute("SELECT tax_year FROM tax_forms WHERE review_status<>'rejected'")}
                           | {int(row[0]) for row in db.execute("SELECT DISTINCT substr(event_date,1,4) FROM investment_events WHERE review_status='verified'")}
                           | {int(year)}, reverse=True)
            forms = [self.tax_form_view(db, row) for row in db.execute(
                "SELECT f.*,a.name AS account_name FROM tax_forms f LEFT JOIN investment_accounts a ON a.id=f.account_id WHERE f.tax_year=? "
                "AND f.review_status<>'rejected' ORDER BY f.institution,f.id", (year,))]
            recorded, checks = {}, []
            for form in forms:
                account = accounts.get(form["account_id"])
                if account is not None and account["id"] not in recorded:
                    recorded[account["id"]] = self.measures(db, account, year)
                for measure, label, sources in TAX_CHECKS:
                    boxes = [box for box in form["boxes"] if box["box"] in sources.get(box["form"], ())]
                    if not boxes:
                        continue
                    printed = sum(box["amount_minor"] for box in boxes)
                    mine = recorded[account["id"]][measure] if account is not None else None
                    currency = form["currency"]
                    checks.append({"form_id": form["id"], "document_id": form["document_id"], "institution": form["institution"], "review_status": form["review_status"],
                                   "account_id": form["account_id"], "account": account["name"] if account else None, "label": label,
                                   "forms": sorted({box["form"] for box in boxes}), "boxes": [box["box"] for box in boxes],
                                   "form_amount": money(printed, currency), "recorded": money(mine, currency) if mine is not None else None,
                                   "difference": money(printed - mine, currency) if mine is not None else None, "matches": mine == printed})
            gains = []
            for currency in sorted({account["currency"] for account in accounts.values()}):
                taxable = [account["id"] for account in accounts.values() if account["currency"] == currency and account["tax_treatment"] == "taxable"]
                sales = realized(db, taxable, year)
                if sales["proceeds_minor"] or sales["missing"]:
                    gains.append({"currency": currency, **{key: money(sales[f"{key}_minor"], currency) for key in ("proceeds", "cost", "short", "long")},
                                  "missing": [{**gap, "account": accounts[gap["account_id"]]["name"]} for gap in sales["missing"]]})
            education = self.education_earnings(db, year)
        return {"year": int(year), "years": years, "forms": forms, "checks": checks, "gains": gains, "education": education}

    def education_earnings(self, db, year):
        """Each 529's withdrawals in a tax year that weren't for qualified education costs, and the part of them that is earnings
        (taxed as income, usually with a 10% additional tax). The earnings share is the account's confirmed 1099-Q box 2 (earnings)
        over box 1 (gross distribution); without one it is unknown. Withdrawals not yet marked either way are listed so they can be."""
        found = []
        for account in self.rows(db, True):
            if account["section"] != "education":
                continue
            taken = {row["event_type"]: row["total"] for row in db.execute(
                "SELECT event_type,sum(amount_minor) AS total FROM investment_events WHERE account_id=? AND review_status='verified' "
                f"AND substr(event_date,1,4)=? AND event_type IN ({','.join('?' * len(WITHDRAWAL_TYPES))}) GROUP BY event_type",
                (account["id"], str(year), *WITHDRAWAL_TYPES))}
            nonqualified, unmarked = taken.get("nonqualified_withdrawal", 0), taken.get("withdrawal", 0)
            if not nonqualified and not unmarked:
                continue
            boxes = {row["box"]: row["total"] for row in db.execute(
                "SELECT b.box,sum(b.amount_minor) AS total FROM tax_form_boxes b JOIN tax_forms f ON f.id=b.form_id WHERE f.account_id=? AND f.tax_year=? "
                "AND f.review_status='verified' AND b.form='1099-Q' GROUP BY b.box", (account["id"], year))}
            gross, earnings = boxes.get("1"), boxes.get("2")
            taxable = int((Decimal(nonqualified) * earnings / gross).to_integral_value(ROUND_HALF_EVEN)) if gross and earnings is not None else None
            currency = account["currency"]
            found.append({"account_id": account["id"], "account": account["name"], "currency": currency, "beneficiary": account["beneficiary"],
                          "nonqualified": money(nonqualified, currency), "unmarked": money(unmarked, currency) if unmarked else None,
                          "earnings_share_percent": share_text(earnings, gross) if gross and earnings is not None else None,
                          "taxable_earnings": money(taxable, currency) if taxable is not None else None, "taxable_earnings_minor": taxable})
        return found

    # Required minimum distributions --------------------------------------------------------------------------------
    def required_distributions(self, year, birth_year):
        """A year's required minimum distributions (finance/retirement.py), account by account: the balance at the end of the year
        before (the newest confirmed value on or before Dec 31, flagged when older than a month), the divisor for the age reached,
        the amount, confirmed withdrawals already taken that year, what is left, and the deadline (April 1 of the next year for
        the first one). Without a birth year, or before distributions begin, it says so instead."""
        with self.store.connection() as db:
            # A pension pays its benefit instead; it has no balance to take a distribution from.
            accounts = [account for account in self.rows(db) if account["tax_treatment"] in HAS_RMD and not account["is_income"]]
            result = {"year": year, "birth_year": birth_year, "accounts": [], "has_accounts": bool(accounts)}
            if not accounts or birth_year is None:
                return result
            start_age = rmd_start_age(birth_year)
            first = birth_year + start_age
            result.update(start_age=start_age, first_year=first, age=year - birth_year, begins_later=year < first)
            if year < first:
                return result
            year_end = f"{year - 1}-12-31"
            for account in accounts:
                currency = account["currency"]
                own = [dict(row) for row in db.execute("SELECT * FROM investment_valuations WHERE account_id=? AND holding_id IS NULL", (account["id"],))]
                balance = next((value for value in self.merged_values(db, account, own)
                                if value["review_status"] == "verified" and value["source"] != "estimated" and value["as_of"] <= year_end), None)
                amount = required(balance["value_minor"], birth_year, year) if balance else None
                taken = sum(event["amount_minor"] for event in self.events(db, account)
                            if event["event_type"] == "withdrawal" and event["review_status"] == "verified" and event["event_date"][:4] == str(year))
                show = lambda minor: money(minor, currency) if minor is not None else None  # noqa: B023 - used in this iteration only
                result["accounts"].append({
                    "account_id": account["id"], "name": account["name"], "currency": currency,
                    "balance": show(balance["value_minor"] if balance else None), "balance_as_of": balance["as_of"] if balance else None,
                    "stale": bool(balance) and (date.fromisoformat(year_end) - date.fromisoformat(balance["as_of"])).days > 31,
                    "divisor": f"{divisor(year - birth_year)}", "required": show(amount), "taken": show(taken),
                    "left": show(max(amount - taken, 0) if amount is not None else None),
                    "deadline": f"{year + 1}-04-01" if year == first else f"{year}-12-31", "status": "verified" if amount is not None and taken >= amount else "due"})
        return result

    # The forecast ------------------------------------------------------------------------------------------------
    def forecast_assets(self, start=None, end=None, months=None):
        """Confirmed current values shaped as forecast assets: each grows at its account's rate, or its kind's default. An account
        valued by accrual also lists each open CD or Treasury (`terms`): it grows to its value at maturity, then is paid out to
        cash unless it renews. Over the history window (start to end, `months` long) each account also has its monthly
        contributions: from pay (the linked employer's confirmed pay stub lines, employee and employer), and from you (the
        amount set on the account, else your contributions paid from a bank or card account in the ledger)."""
        found = []
        with self.store.connection() as db:  # Read only: family members' copies are opened read-only.
            for account in self.rows(db):
                if account["current"] is None or account["is_income"]:
                    continue  # A pension joins as an income stream (forecast_pensions), never as a balance.
                payroll = personal = 0
                if months:
                    average = lambda total: int((Decimal(total) / months).to_integral_value(ROUND_HALF_EVEN))
                    payroll = average(sum(line["amount_minor"] for line in self.payroll_lines(db, account["payroll_merchant_id"], account["section"],
                                                                                              account["currency"], start, end) if line["review_status"] == "verified"))
                    paid_in = db.execute("SELECT coalesce(sum(amount_minor),0) FROM investment_events WHERE account_id=? AND review_status='verified' "
                                         "AND transaction_id IS NOT NULL AND ((event_type='contribution' AND contribution_source='personal') OR event_type='transfer_in') "
                                         "AND event_date BETWEEN ? AND ?", (account["id"], start, end)).fetchone()[0]
                    personal = account["monthly_contribution_minor"] if account["monthly_contribution_minor"] is not None else average(paid_in)
                terms = []
                if account["value_model"] == "accrual":
                    for holding in self.term_holdings(db, account["id"]):
                        if holding["counts"] and not holding["matured"] and holding["maturity_date"]:
                            terms.append({"name": holding["name"], "value_minor": holding["value_on"](self.today), "maturity_month": holding["maturity_date"][:7],
                                          "maturity_value_minor": holding["value_on"](holding["maturity_date"]), "to_cash": not holding["rollover"]})
                found.append({"account_id": account["id"], "name": account["name"], "kind": account["kind"], "kind_label": account["kind_label"],
                              "value_model": account["value_model"], "section": account["section"],
                              "value_minor": account["current"]["value_minor"], "value": account["current"]["value"], "currency": account["currency"],
                              "as_of": account["current"]["as_of"], "annual_rate_bp": account["rate_bp"], "annual_rate_percent": account["annual_rate_percent"],
                              "monthly_payment_minor": None, "monthly_payment": None, "review_status": "verified", "source": "investment", "terms": terms,
                              "tax_treatment": account["tax_treatment"],
                              "payroll_monthly_minor": payroll, "personal_monthly_minor": personal})
        return found

    # Crypto exchange exports ----------------------------------------------------------------------------------------
    def import_crypto(self, account_id, document_id, digest=None, preset="coinbase"):
        """An exchange's transaction history (a CSV or XLSX in the library) as this account's buys, sells, transfers and rewards,
        each in a holding matched by its symbol (BTC, ETH). A deterministic import counts at once, like a transaction import;
        importing the same file again, or an overlapping one, adds nothing twice. Confirmed buys open tax lots (finance/tax_lots.py),
        and the units held feed market prices when they are on (finance/prices.py)."""
        account = self.get(account_id)
        document, version = self.store.document_version(document_id, digest)
        if document["deleted_at"]:
            raise ValueError("Restore the document from Trash before importing it.")
        suffix = extension(document["relative_path"])
        if suffix not in (".csv", ".xlsx"):
            raise ValueError("Exchange imports read CSV and XLSX documents.")
        data = self.store.blob_path(version["hash"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != version["hash"]:
            raise ValueError("Preserved evidence failed its integrity check. Nothing was imported.")
        rows, issues = parse_crypto_export(data, suffix, account["currency"], preset)
        added = duplicates = 0
        with self.store.connection() as db:
            for row in rows:
                trade = {"identifier": row["asset"], "name": row["asset"]}
                key = holding_key(trade)
                found = db.execute("SELECT id FROM holdings WHERE account_id=? AND holding_key=?", (account_id, key)).fetchone()
                holding_id = found["id"] if found else db.execute(
                    "INSERT INTO holdings(account_id,instrument_class,name,identifier,holding_key,source,created_at,updated_at) VALUES(?,'crypto',?,?,?,'manual',?,?)",
                    (account_id, row["asset"], row["asset"], key, now(), now())).lastrowid
                if db.execute("SELECT 1 FROM investment_events WHERE account_id=? AND holding_id=? AND event_date=? AND event_type=? AND amount_minor=? "
                              "AND quantity=? AND review_status<>'rejected'", (account_id, holding_id, row["date"], row["type"], row["amount_minor"], row["quantity"])).fetchone():
                    duplicates += 1
                    continue
                db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,amount_minor,quantity,document_id,blob_hash,note,review_status,created_at) "
                           "VALUES(?,?,?,?,?,?,?,?,?,'verified',?)", (account_id, holding_id, row["date"], row["type"], row["amount_minor"], row["quantity"],
                                                                      document_id, version["hash"], row["note"][:200], now()))
                added += 1
        return {"account_id": account_id, "added": added, "duplicates": duplicates, "issues": issues[:200], "preset": preset}

    def forecast_pensions(self):
        """Pensions with terms, shaped as the forecast's income streams (forecast.PensionIncome): the monthly benefit from its
        start month, raised by its cost-of-living rate each January, and taxed as income when it is tax-deferred."""
        with self.store.connection() as db:
            return [{"label": account["name"], "currency": account["currency"], "monthly_amount": account["pension"]["monthly_benefit"]["decimal"],
                     "start_month": account["pension"]["start_date"][:7], "cola_percent": account["pension"]["cola_percent"],
                     "taxed": account["tax_treatment"] in HAS_RMD}
                    for account in self.rows(db) if account["is_income"] and account["pension"]]

    def waiting_names(self):
        with self.store.connection() as db:
            return [account["name"] for account in self.rows(db) if account["awaiting_review"]]
