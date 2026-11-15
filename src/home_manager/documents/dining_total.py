"""A dining receipt's charged total and tip, decided in code from the printed lines (docs/documents.md "Receipt kinds").

Pure and deterministic: decide(header, lines) works on printed decimals, so it needs no currency, and returns a new header whose total and
tip carry the decided amount and cite whole lines. It runs in ExtractionService.record, before the result is saved, so the saved header
(which the traces read their citations from) holds the decided values. With no qualifying lines the header comes back unchanged."""

from dataclasses import dataclass, field
from decimal import Decimal
import re

from ..core.money import NUMBER
from .reasoning import EvidenceQuote

# Where each decided figure came from, as the Tip's note and Review reason name them.
LABELS = {"total": "Total", "grand total": "Grand Total", "bill": "Bill", "amount due": "Amount due", "balance due": "Balance due"}
# A printed total line: Total or Grand Total, never Subtotal, Total Tax, Total Item Count or Total Savings.
TOTAL = re.compile(r"^\s*(?P<label>(?:grand\s+)?total)\b(?!\s*(?:tax|savings?|saved|discounts?|items?|item\s+count|number|qty|quantity|units|points))",
                   re.IGNORECASE)
# The other labels a pre-tip amount takes (D30): nothing else, a card terminal's "Amount: $52.76" included.
BILL = re.compile(r"^\s*(?P<label>bill|amount\s+due|balance\s+due)\b", re.IGNORECASE)
ENDS_WITH_AMOUNT = re.compile(r"(?:[$€£]\s*)?(?P<amount>" + NUMBER.pattern + r")\s*$")
TIP_LINE = re.compile(r"^\s*tip\b", re.IGNORECASE)
PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
HEADING = re.compile(r"^\s*(?:suggested\s+tips?|tip\s+guide|tip\s+suggestions?)\b", re.IGNORECASE)
TABLE_NOTE = "The {what} the reading took from the suggested-tip table was not used."
DIFFERENT = "The receipt prints different amounts before the tip ({0} and {1}), so the tip wasn't worked out."
TIP_AND_BILL = "Tip ({0}) and the bill ({1}) don't make the total ({2})."
TIP_TOO_LARGE = "The tip the reading took ({0}) is not less than the total ({1}), so it was not used."


@dataclass
class Issue:
    """An issue with its amounts left as printed decimals: they are written with the receipt's currency once it is known (amount_text)."""
    template: str
    amounts: tuple = ()

    def dump(self):
        return {"template": self.template, "amounts": [format(amount, "f") for amount in self.amounts]}


@dataclass
class DiningDecision:
    header: object
    tip_basis: dict | None = None
    issues: list = field(default_factory=list)
    total_changed: bool = False
    tip_changed: bool = False

    def dump(self):
        return {"tip_basis": self.tip_basis, "issues": [issue.dump() for issue in self.issues]}


def printed_amount(text):
    """The Decimal a line ends with (with or without a currency symbol in front), else None."""
    found = ENDS_WITH_AMOUNT.search(text or "")
    return Decimal(found.group("amount").replace(",", "")) if found else None


def table_ids(lines):
    """The ids of the lines of every suggested-tip table: each maximal run of consecutive lines printing a percentage and an amount, and a
    "Suggested Tip" or "Tip Guide" heading line directly before it. A run of one line counts only when it names a tip."""
    def offers(text):
        rest = PERCENT.sub(" ", text)
        return PERCENT.search(text) is not None and NUMBER.search(rest) is not None
    found, start = set(), None
    for index in range(len(lines) + 1):
        inside = index < len(lines) and offers(lines[index].text)
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            run = lines[start:index]
            heading = start > 0 and HEADING.match(lines[start - 1].text) is not None
            if len(run) > 1 or heading or any(re.search(r"\btip", line.text, re.IGNORECASE) for line in run):
                found.update(line.id for line in run)
                if heading:
                    found.add(lines[start - 1].id)
            start = None
    return found


def cite(line):
    return EvidenceQuote(line_id=line.id, quote=line.text)


def proposed(like, text, *lines):
    """A copy of like (a Value) holding the amount text, citing these whole lines."""
    return like.model_copy(update={"value": text, "status": "proposed", "evidence": [cite(line) for line in lines]})


def missing(like):
    return like.model_copy(update={"value": None, "status": "missing", "evidence": []})


def label_of(text):
    found = TOTAL.match(text) or BILL.match(text)
    return LABELS[" ".join(found.group("label").lower().split())]


def decide(header, lines):
    """DiningDecision for a dining receipt's header (a ReceiptDiningSummary) and its transcription lines in reading order (FR-01 – FR-05)."""
    table = table_ids(lines)
    outside = [(index, line, printed_amount(line.text)) for index, line in enumerate(lines) if line.id not in table]
    pre = [(index, line, amount) for index, line, amount in outside
           if amount is not None and (TOTAL.match(line.text) or BILL.match(line.text))]

    def nearest(before):
        return next(((index, line, amount) for index, line, amount in reversed(pre) if index < before), None)
    post = None  # The latest total line larger than the nearest pre-tip amount before it.
    for index, line, amount in pre:
        if TOTAL.match(line.text):
            bill = nearest(index)
            if bill is not None and amount > bill[2]:
                post = (index, line, amount, bill)
    decision = DiningDecision(header)
    total, tip = header.total, header.tip

    def on_table(value):
        return value.status == "proposed" and bool(value.evidence) and all(cite.line_id in table for cite in value.evidence)
    new_total, new_tip = total, tip
    if on_table(total):
        decision.issues.append(Issue(TABLE_NOTE.format(what="total")))
        new_total = missing(total)
        if post is None:  # Rejected, with no post-tip total: the nearest pre-tip amount printed before the table, else missing (D22).
            first = next((index for index, line in enumerate(lines) if line.id in table), len(lines))
            found = nearest(first)
            if found is not None:
                new_total = proposed(total, format(found[2], "f"), found[1])
    if on_table(tip):
        decision.issues.append(Issue(TABLE_NOTE.format(what="tip")))
        new_tip = missing(tip)
    if post is not None:
        index, line, amount, bill = post
        new_total = proposed(total, format(amount, "f"), line)
        earlier = [(before, other, value) for before, other, value in pre if before < bill[0] and value != bill[2]]
        agree = not earlier
        if not agree:  # Which figure was the bill is unclear: the total stands, and no tip is invented (D23, D29).
            decision.issues.append(Issue(DIFFERENT, (earlier[0][2], bill[2])))
        printed = new_tip.status == "proposed" and printed_in(new_tip)
        if printed:
            if printed_amount_of(new_tip) + bill[2] != amount:
                decision.issues.append(Issue(TIP_AND_BILL, (printed_amount_of(new_tip), bill[2], amount)))
        elif agree and any(TIP_LINE.match(other.text) and not HEADING.match(other.text) for _, other, _ in outside):
            new_tip = proposed(tip, format(amount - bill[2], "f"), bill[1], line)
            decision.tip_basis = {"total": {"label": label_of(line.text), "line_id": line.id, "text": line.text},
                                  "bill": {"label": label_of(bill[1].text), "line_id": bill[1].id, "text": bill[1].text}}
    # A tip as large as the total leaves nothing for the items (a split "Tip: $" line read with the total under it): never used.
    tip_amount, total_amount = (printed_amount_of(value) if value.status == "proposed" else None for value in (new_tip, new_total))
    if tip_amount is not None and total_amount is not None and 0 < total_amount <= tip_amount:
        decision.issues.append(Issue(TIP_TOO_LARGE, (tip_amount, total_amount)))
        new_tip, decision.tip_basis = missing(new_tip), None
    decision.total_changed, decision.tip_changed = new_total != total, new_tip != tip
    decision.header = header.model_copy(update={"total": new_total, "tip": new_tip}) if decision.total_changed or decision.tip_changed else header
    return decision


def printed_in(value):
    """Whether the amount a tip proposes is printed in one of its cited lines."""
    wanted = printed_amount_of(value)
    return wanted is not None and any(wanted in {Decimal(match.group(0).replace(",", "")) for match in NUMBER.finditer(cite.quote)}
                                      for cite in value.evidence)


def printed_amount_of(value):
    matches = NUMBER.findall(value.value or "")
    return Decimal(matches[0].replace(",", "")) if len(matches) == 1 else None
