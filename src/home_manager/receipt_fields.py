"""Conservative label-based suggestions. Never hide or alter the raw OCR text."""

from datetime import date
from decimal import Decimal, InvalidOperation
import re

from .receipt_schema import Candidate, ReceiptFields, TextBlock, TextLine


def reading_lines(blocks: list[TextBlock]) -> list[TextLine]:
    """Group horizontal neighbors without discarding any OCR block."""
    groups: list[list[TextBlock]] = []
    def geometry(block):
        xs, ys = zip(*block.polygon)
        return min(xs), min(ys), max(ys), (min(ys) + max(ys)) / 2
    for block in sorted(blocks, key=lambda b: (geometry(b)[3], geometry(b)[0])):
        _, top, bottom, middle = geometry(block)
        if groups:
            previous = groups[-1][0]
            _, ptop, pbottom, pmiddle = geometry(previous)
            same_row = abs(middle - pmiddle) <= max(2, min(bottom - top, pbottom - ptop) * .45)
        else:
            same_row = False
        if same_row:
            groups[-1].append(block)
        else:
            groups.append([block])
    result = []
    for group in groups:
        group.sort(key=lambda b: geometry(b)[0])
        result.append(TextLine(id=f"line-{len(result)+1}", text=" ".join(b.text for b in group), block_ids=[b.id for b in group]))
    return result


# A decimal-bearing amount, not a percentage, account number or date. Integer
# totals remain unresolved rather than guessing a monetary scale.
AMOUNT = re.compile(r"(?<![\w.,])(?P<amount>[-+]?\(?\d[\d.,]*[.,]\d{2}\)?)(?![\d.,]|\s*%)")
LABELS = [
    ("subtotal", re.compile(r"\bsub\s*total\b", re.I)),
    ("tax", re.compile(r"\b(?:sales\s+tax|tax|vat|gst|hst|pst)\b", re.I)),
    ("tip", re.compile(r"\b(?:tip|gratuity)\b", re.I)),
    ("service_charge", re.compile(r"\bservice\s+(?:charge|fee)\b", re.I)),
    ("discount", re.compile(r"\b(?:discount|coupon)\b", re.I)),
    ("total", re.compile(r"\b(?:grand\s+total|total\s+due|amount\s+due|total)\b", re.I)),
]


def decimal_amount(value: str) -> Decimal | None:
    negative = value.startswith("(") and value.endswith(")")
    text = value.strip("()")
    decimal_mark = text[-3]
    if decimal_mark not in ".,":
        return None
    integer = text[:-3]
    grouping = "," if decimal_mark == "." else "."
    if decimal_mark in integer:
        return None
    if grouping in integer and not re.fullmatch(r"[-+]?\d{1,3}(?:" + re.escape(grouping) + r"\d{3})+", integer):
        return None
    try:
        number = Decimal(integer.replace(grouping, "") + "." + text[-2:])
        return -number if negative else number
    except InvalidOperation:
        return None


def financial_fields(lines: list[TextLine]) -> ReceiptFields:
    dates = []
    currencies: dict[str, list[str]] = {}
    components = []
    totals = []
    for line in lines:
        text = line.text
        # Require a year. Ambiguous MM/DD versus DD/MM stays unresolved.
        for match in re.finditer(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b|\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text):
            raw = match.group()
            value = None
            try:
                if match.group(1):
                    value = date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
                else:
                    a, b, year = map(int, match.group(4, 5, 6))
                    if a > 12:
                        value = date(year, b, a).isoformat()
                    elif b > 12 or a == b:
                        value = date(year, a, b).isoformat()
            except ValueError:
                pass
            dates.append(Candidate(name="date", value=value, raw_text=raw, evidence_ids=[line.id], status="proposed" if value else "ambiguous"))
        for code in re.findall(r"\b(?:USD|EUR|GBP|MXN|PHP|CAD|AUD|NZD|JPY|CNY|INR|CHF|BRL|SGD|HKD|KRW|AED|SAR|ZAR|SEK|NOK|DKK|PLN|THB|IDR|MYR)\b", text.upper()):
            currencies.setdefault(code, []).append(line.id)
        if "€" in text:
            currencies.setdefault("EUR", []).append(line.id)
        if re.search(r"\bUS\s*\$", text, re.I):
            currencies.setdefault("USD", []).append(line.id)

        for kind, pattern in LABELS:
            label = pattern.search(text)
            if label is None:
                continue
            if re.search(r"\b(?:suggested|suggestion|recommended|savings|saved|items|change|tendered|cashback)\b", text, re.I):
                break
            amounts = list(AMOUNT.finditer(text[label.end():]))
            # Multiple money values on the same label line need interpretation.
            parsed = decimal_amount(amounts[-1].group("amount")) if len(amounts) == 1 else None
            candidate = Candidate(name=kind, value=f"{parsed:.2f}" if parsed is not None else None,
                                  raw_text=text, evidence_ids=[line.id],
                                  status="proposed" if parsed is not None else "ambiguous")
            if kind in ("tax", "tip", "service_charge") and re.search(r"\b(?:included|inclusive|incl)\b", text, re.I):
                candidate.status = "ambiguous"
                candidate.note = "Printed component may already be included in the subtotal/total. Retained but not added again."
            (totals if kind == "total" else components).append(candidate)
            break

    def choose(name, items):
        if not items:
            return Candidate(name=name, status="missing", note="No unambiguous supported label/value found; inspect the full receipt.")
        values = {item.value for item in items}
        if len(values) == 1 and None not in values:
            result = items[0].model_copy(deep=True)
            result.evidence_ids = list(dict.fromkeys(key for item in items for key in item.evidence_ids))
            return result
        return Candidate(name=name, status="ambiguous", raw_text=" | ".join(item.raw_text for item in items),
                         evidence_ids=list(dict.fromkeys(key for item in items for key in item.evidence_ids)),
                         note="Conflicting or ambiguous values; no value selected.")
    receipt_date, total = choose("date", dates), choose("total", totals)
    if len(currencies) == 1:
        code, refs = next(iter(currencies.items()))
        currency = Candidate(name="currency", value=code, raw_text=code, evidence_ids=list(dict.fromkeys(refs)), status="proposed")
    else:
        currency = Candidate(name="currency", status="ambiguous" if currencies else "missing",
                             raw_text=", ".join(currencies),
                             evidence_ids=list(dict.fromkeys(key for refs in currencies.values() for key in refs)),
                             note="A dollar/peso/pound symbol alone is not a reliable currency code. Review the receipt.")
    fields = ReceiptFields(date=receipt_date, currency=currency, total=total, components=components,
                           calculation_note="No complete, unambiguous subtotal breakdown is available. Missing components are not assumed to be zero.")
    counts = {name: sum(c.name == name for c in components) for name, _ in LABELS}
    if counts.get("subtotal") == 1 and components and total.value and all(c.value is not None and c.status == "proposed" for c in components):
        # Duplicated tax/fee labels may be alternatives or breakdowns. Do not double count.
        if all(count <= 1 for count in counts.values()):
            amount = sum((-abs(Decimal(c.value)) if c.name == "discount" else Decimal(c.value) for c in components), Decimal("0"))
            fields.calculated_total = f"{amount:.2f}"
            fields.difference = f"{Decimal(total.value) - amount:.2f}"
            fields.calculation_status = "matches" if amount == Decimal(total.value) else "mismatch"
            fields.calculation_note = "Arithmetic comparison of detected subtotal + tax + tip + service charge - discount only. A match does not prove all receipt content was read or that tax is additional."
    return fields
