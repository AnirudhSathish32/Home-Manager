"""Checked answers for one donated document (docs/evals.md).

The shape a donor's check is saved in (library/donations.py) and the eval suite grades against (evals/). Keys are the
normalized record's keys (documents/extraction.normalize), so a model's result and its answers compare field by field.
Each critical field is correct (the proposal was right), fixed (the person typed the right value) or unchecked (no one
looked; never scored). Rows count only when someone confirmed the list complete. Amounts are integer minor units.
"""

from datetime import date
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .money import EXPONENTS

ANSWERS_FORMAT = "home-manager-answers/1"
DOCUMENT_TYPES = ("receipt", "bank_statement", "credit_card_statement", "paystub")
STATES = ("correct", "fixed", "unchecked")
PAY_GROUPS = ("earnings", "pre_tax", "tax", "post_tax", "employer_paid")
# The fields a person checks for each document type, in the order they are shown.
CRITICAL = {
    "receipt": ("merchant", "purchase_date", "currency", "subtotal_minor", "tax_minor", "tip_minor", "total_minor"),
    "bank_statement": ("institution", "period_start", "period_end", "currency", "opening_balance_minor", "closing_balance_minor"),
    "credit_card_statement": ("institution", "period_start", "period_end", "due_date", "currency", "previous_balance_minor",
                              "statement_balance_minor", "minimum_payment_minor"),
    "paystub": ("payer_or_employer", "pay_date", "period_start", "period_end", "currency", "gross_pay_minor", "net_pay_minor",
                "taxes_minor", "deductions_minor", "gross_pay_ytd_minor", "net_pay_ytd_minor"),
}
# The record's row list and the columns checked in each row.
ROWS = {
    "receipt": ("items", ("description", "line_total_minor")),
    "bank_statement": ("transactions", ("posted_date", "description", "amount_minor")),
    "credit_card_statement": ("transactions", ("posted_date", "description", "amount_minor")),
    "paystub": ("lines", ("description", "line_group", "current_minor", "ytd_minor")),
}
LABELS = {"merchant": "Merchant", "purchase_date": "Purchase date", "currency": "Currency", "subtotal_minor": "Subtotal", "tax_minor": "Tax",
          "tip_minor": "Tip", "total_minor": "Total", "institution": "Bank or card issuer", "period_start": "Period start",
          "period_end": "Period end", "due_date": "Due date", "opening_balance_minor": "Opening balance", "closing_balance_minor": "Closing balance",
          "previous_balance_minor": "Previous balance", "statement_balance_minor": "Statement balance", "minimum_payment_minor": "Minimum payment",
          "payer_or_employer": "Employer", "pay_date": "Pay date", "gross_pay_minor": "Gross pay", "net_pay_minor": "Net pay",
          "taxes_minor": "Taxes", "deductions_minor": "Deductions", "gross_pay_ytd_minor": "Gross pay, year to date",
          "net_pay_ytd_minor": "Net pay, year to date", "description": "Description", "line_total_minor": "Amount", "posted_date": "Date",
          "amount_minor": "Amount", "line_group": "Group", "current_minor": "This period", "ytd_minor": "Year to date"}
DATES = {"purchase_date", "period_start", "period_end", "due_date", "pay_date", "posted_date"}
MAX_ROWS = 500
MAX_MINOR = 10**15
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def kind_of(name):
    """money, date, currency, group or text: how a field's value is written and compared."""
    if name.endswith("_minor"):
        return "money"
    if name in DATES:
        return "date"
    return {"currency": "currency", "line_group": "group"}.get(name, "text")


def check_value(name, value):
    """The value if it is valid for its field, else ValueError. None means the document does not print it."""
    if value is None:
        return None
    kind = kind_of(name)
    if kind == "money":
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > MAX_MINOR:
            raise ValueError(f"{LABELS.get(name, name)} must be a whole number of minor units.")
        return value
    if not isinstance(value, str) or CONTROL.search(value):
        raise ValueError(f"{LABELS.get(name, name)} must be plain text.")
    if kind == "date":
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError
            date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{LABELS.get(name, name)} must be a date written YYYY-MM-DD.") from None
        return value
    if kind == "currency":
        if value not in EXPONENTS:
            raise ValueError("Currency must be a supported three-letter code such as USD.")
        return value
    if kind == "group":
        if value not in PAY_GROUPS:
            raise ValueError("A pay line's group must be one of: " + ", ".join(PAY_GROUPS) + ".")
        return value
    value = " ".join(value.split())
    if not value or len(value) > 200:
        raise ValueError(f"{LABELS.get(name, name)} must be 1 to 200 characters.")
    return value


class FieldAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int | str | None = None
    state: Literal["correct", "fixed", "unchecked"] = "unchecked"


class Answers(BaseModel):
    """answers.json for one case. rows is None until someone looks at the row list."""
    model_config = ConfigDict(extra="forbid")
    format: Literal["home-manager-answers/1"] = "home-manager-answers/1"
    document_type: Literal["receipt", "bank_statement", "credit_card_statement", "paystub"]
    fields: dict[str, FieldAnswer]
    rows: list[dict[str, int | str | None]] | None = Field(default=None, max_length=MAX_ROWS)
    rows_state: Literal["correct", "fixed", "unchecked"] = "unchecked"
    rows_complete: bool | None = None

    @model_validator(mode="after")
    def consistent(self):
        expected = CRITICAL[self.document_type]
        if set(self.fields) != set(expected):
            raise ValueError("Answers must list exactly the critical fields of a " + self.document_type.replace("_", " ") + ".")
        for name, answer in self.fields.items():
            answer.value = check_value(name, answer.value)
        _, columns = ROWS[self.document_type]
        for row in self.rows or []:
            if set(row) != set(columns):
                raise ValueError("Each row must have exactly these columns: " + ", ".join(columns) + ".")
            for name in columns:
                row[name] = check_value(name, row[name])
            if row["description"] is None:
                raise ValueError("Each row needs a description.")
        if self.rows_state == "unchecked":
            self.rows_complete = None
        elif self.rows is None:
            raise ValueError("Checked rows need the row list.")
        return self

    def checked_fields(self):
        return {name: answer.value for name, answer in self.fields.items() if answer.state != "unchecked"}


def empty_answers(document_type, record):
    """Unchecked answers prefilled from a normalized record (the model's proposal, with any corrections applied)."""
    key, columns = ROWS[document_type]
    fields = {}
    for name in CRITICAL[document_type]:
        try:
            value = check_value(name, record.get(name))
        except ValueError:
            value = None
        fields[name] = FieldAnswer(value=value)
    rows = []
    for row in (record.get(key) or [])[:MAX_ROWS]:
        clean = {}
        for name in columns:
            try:
                clean[name] = check_value(name, row.get(name))
            except ValueError:
                clean[name] = None
        clean["description"] = clean["description"] or "(no description)"
        rows.append(clean)
    return Answers(document_type=document_type, fields=fields, rows=rows)
