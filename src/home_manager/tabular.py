"""Deterministic CSV/XLSX transaction import. No model, no macros, no formula evaluation.

Workbooks are read with the standard library under explicit limits: DOCTYPE
declarations are refused (no entity expansion), members are size- and ratio-bounded,
formulas contribute only their cached values, and uncached formulas are reported.
Column mapping, date order and sign convention are explicit or unambiguously inferred.
"""

import csv
from datetime import date, timedelta
from decimal import Decimal
import io
import re
import zipfile
from typing import Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .money import EXPONENTS, MoneyError, currency_code, format_minor, to_minor

MAX_BYTES, MAX_ROWS, MAX_COLUMNS, MAX_CELL = 32 * 1024**2, 20_000, 60, 2000
XLSX_MEMBER_BYTES, XLSX_TOTAL_BYTES, XLSX_RATIO = 48 * 1024**2, 96 * 1024**2, 200
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
HEADER_NAMES = {
    "date": ("date", "posted date", "posting date", "post date", "transaction date", "trans date", "trans. date", "booking date"),
    "description": ("description", "payee", "merchant", "details", "memo", "name", "transaction description", "narrative"),
    "amount": ("amount", "transaction amount", "amount (usd)"),
    "debit": ("debit", "debits", "withdrawal", "withdrawals", "money out", "paid out"),
    "credit": ("credit", "credits", "deposit", "deposits", "money in", "paid in"),
    "currency": ("currency", "currency code"),
}
DATE_FORMATS = ("YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY")
BUILTIN_DATE_FORMATS = set(range(14, 23)) | {45, 46, 47}


class ImportMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=200)
    amount: str | None = Field(default=None, max_length=200)
    debit: str | None = Field(default=None, max_length=200)
    credit: str | None = Field(default=None, max_length=200)
    currency: str | None = Field(default=None, max_length=200)
    date_format: Literal["auto", *DATE_FORMATS] = "auto"
    sign: Literal["negative_is_outflow", "positive_is_outflow"] = "negative_is_outflow"

    @model_validator(mode="after")
    def one_amount_scheme(self):
        if self.amount and (self.debit or self.credit):
            raise ValueError("Map either a signed amount column or debit/credit columns, not both.")
        return self


class TableError(ValueError):
    pass


class MappingError(TableError):
    """The file is readable but needs a user choice (column or date order)."""

    def __init__(self, message, columns, mapping):
        super().__init__(message)
        self.columns, self.mapping = columns, mapping


def _cell(value):
    text = " ".join(str(value).split())
    if len(text) > MAX_CELL:
        raise TableError("A cell exceeds the import size limit.")
    return text


def read_csv(data):
    try:
        text, note = data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        text, note = data.decode("cp1252", errors="replace"), "The file is not UTF-8; it was read as Windows-1252. Check descriptions for odd characters."
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = []
    for row in csv.reader(io.StringIO(text), dialect):
        if len(rows) >= MAX_ROWS + 50 or len(row) > MAX_COLUMNS:
            raise TableError(f"The file exceeds the import limits ({MAX_ROWS:,} rows, {MAX_COLUMNS} columns).")
        rows.append([_cell(value) for value in row])
    return rows, [note] if note else []


def _xml(archive, name, budget):
    info = archive.getinfo(name)
    if info.file_size > XLSX_MEMBER_BYTES or info.file_size > XLSX_RATIO * max(info.compress_size, 1):
        raise TableError("The workbook contains an oversized or overly compressed part.")
    budget[0] += info.file_size
    if budget[0] > XLSX_TOTAL_BYTES:
        raise TableError("The workbook exceeds the import size limit.")
    data = archive.read(name)
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise TableError("The workbook contains XML declarations that are not accepted.")
    return ElementTree.fromstring(data)


def _column(reference):
    letters = re.match(r"[A-Z]+", reference or "")
    index = 0
    for letter in letters.group(0) if letters else "":
        index = index * 26 + ord(letter) - 64
    return index - 1


def read_xlsx(data, sheet=None):
    issues, budget = [], [0]
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise TableError("The workbook is not a valid XLSX file.") from exc
    with archive:
        names = set(archive.namelist())
        if len(names) > 2000 or "xl/workbook.xml" not in names:
            raise TableError("The workbook structure is not supported.")
        workbook = _xml(archive, "xl/workbook.xml", budget)
        base = date(1904, 1, 1) if (workbook.find("m:workbookPr", NS) is not None and workbook.find("m:workbookPr", NS).get("date1904") in ("1", "true")) else date(1899, 12, 30)
        sheets = workbook.findall("m:sheets/m:sheet", NS)
        chosen = next((item for item in sheets if item.get("name") == sheet), None) if sheet else (sheets[0] if sheets else None)
        if chosen is None:
            raise TableError("The requested worksheet was not found.")
        relations = _xml(archive, "xl/_rels/workbook.xml.rels", budget)
        target = next((item.get("Target") for item in relations.findall("rel:Relationship", NS) if item.get("Id") == chosen.get(f"{{{NS['r']}}}id")), None)
        path = "xl/" + (target or "").lstrip("/").removeprefix("xl/")
        if not target or path not in names:
            raise TableError("The worksheet part is missing.")
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = ["".join(node.text or "" for node in item.iter(f"{{{NS['m']}}}t")) for item in _xml(archive, "xl/sharedStrings.xml", budget).findall("m:si", NS)]
        date_styles = set()
        if "xl/styles.xml" in names:
            styles = _xml(archive, "xl/styles.xml", budget)
            custom = {item.get("numFmtId"): item.get("formatCode", "") for item in styles.findall("m:numFmts/m:numFmt", NS)}
            for index, xf in enumerate(styles.findall("m:cellXfs/m:xf", NS)):
                format_id = xf.get("numFmtId", "0")
                code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", custom.get(format_id, "")).lower()
                if int(format_id) in BUILTIN_DATE_FORMATS or (format_id in custom and re.search(r"[dy]", code)):
                    date_styles.add(str(index))
        rows, formulas = [], 0
        for row in _xml(archive, path, budget).findall("m:sheetData/m:row", NS):
            values = {}
            for cell in row.findall("m:c", NS):
                column, kind = _column(cell.get("r")), cell.get("t", "n")
                if column >= MAX_COLUMNS:
                    raise TableError(f"The worksheet exceeds {MAX_COLUMNS} columns.")
                formula, raw = cell.find("m:f", NS), cell.find("m:v", NS)
                formulas += formula is not None
                if kind == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter(f"{{{NS['m']}}}t"))
                elif raw is None or raw.text is None:
                    if formula is not None:
                        issues.append(f"Cell {cell.get('r')} has a formula without a saved value; open and save the workbook in Excel first.")
                    continue
                elif kind == "s":
                    value = shared[int(raw.text)]
                elif kind == "e":
                    issues.append(f"Cell {cell.get('r')} contains a spreadsheet error value.")
                    continue
                elif kind == "b":
                    value = "TRUE" if raw.text == "1" else "FALSE"
                elif kind == "n" and cell.get("s") in date_styles:
                    value = (base + timedelta(days=int(Decimal(raw.text)))).isoformat()
                else:
                    value = raw.text  # Exact stored text; converted with Decimal, never float.
                values[column] = _cell(value)
            if len(rows) >= MAX_ROWS + 50:
                raise TableError(f"The worksheet exceeds {MAX_ROWS:,} rows.")
            rows.append([values.get(index, "") for index in range(max(values, default=-1) + 1)])
        if formulas:
            issues.append(f"{formulas} formula cells were read from their saved values; formulas were not evaluated.")
    return rows, issues


def read_table(data, suffix, sheet=None):
    if len(data) > MAX_BYTES:
        raise TableError("The file exceeds the 32 MiB transaction import limit.")
    rows, issues = read_xlsx(data, sheet) if suffix == ".xlsx" else read_csv(data)
    for index, row in enumerate(rows[:25]):
        names = [cell.strip().lower() for cell in row]
        if any(name in HEADER_NAMES["date"] for name in names) and any(name in HEADER_NAMES[key] for key in ("amount", "debit", "credit") for name in names):
            header = [cell.strip() for cell in row]
            body = [(number, row) for number, row in enumerate(rows[index + 1:], index + 2)]
            if len(body) > MAX_ROWS:
                raise TableError(f"The file exceeds {MAX_ROWS:,} data rows.")
            return header, body, issues
    raise TableError("No header row with date and amount columns was found in the first 25 rows. Check that this is a transaction export.")


def detect(header):
    lowered = {name.lower(): name for name in header if name}
    found = {key: next((lowered[name] for name in names if name in lowered), None) for key, names in HEADER_NAMES.items()}
    if found["amount"]:
        found["debit"] = found["credit"] = None
    return found


def date_order(values, requested):
    """Resolve day/month order from the whole column; never guess from one ambiguous value."""
    if requested != "auto":
        return requested
    slashed = [re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", value) for value in values if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)]
    slashed = [match for match in slashed if match]
    if not slashed:
        return "YYYY-MM-DD"
    first, second = any(int(match.group(1)) > 12 for match in slashed), any(int(match.group(2)) > 12 for match in slashed)
    if first and not second:
        return "DD/MM/YYYY"
    if second and not first:
        return "MM/DD/YYYY"
    raise ValueError("The date column is ambiguous (month and day could be swapped). Choose the date format explicitly.")


def parse_date(value, order):
    value = value.strip()
    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if match:
        year, month, day = match.groups()
    else:
        match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", value)
        if not match or order == "YYYY-MM-DD":
            return None
        first, second, year = match.groups()
        month, day = (first, second) if order == "MM/DD/YYYY" else (second, first)
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def spreadsheet_amount(value, currency):
    """Workbook numbers are stored doubles: accept binary noise below 10^-6, never real sub-unit values."""
    try:
        return to_minor(value, currency)
    except MoneyError:
        if not re.fullmatch(r"-?\d+(\.\d+)?(E-?\d+)?", value or "", re.IGNORECASE):
            raise
        number = Decimal(value)
        exact = number.quantize(Decimal(1).scaleb(-EXPONENTS[currency]))
        if abs(number - exact) >= Decimal("0.000001"):
            raise
        return to_minor(f"{exact:f}", currency)


def parse_transactions(data, suffix, currency, mapping=None, sheet=None):
    """Return (rows, mapping, issues, counts). Rows carry exact minor units and their source row number."""
    currency = currency_code(currency)
    header, body, issues = read_table(data, suffix, sheet)
    mapping = mapping or ImportMapping()
    detected = detect(header)
    columns = {key: getattr(mapping, key) or detected[key] for key in HEADER_NAMES}
    if mapping.amount:
        columns["debit"] = columns["credit"] = None
    if mapping.debit or mapping.credit:
        columns["amount"] = None
    names = [name for name in header if name]

    def needs(message):
        return MappingError(message, names, {key: value for key, value in columns.items() if value})

    for key in ("date", "description"):
        if not columns[key]:
            raise needs(f"Choose the {key} column.")
    if not columns["amount"] and not (columns["debit"] or columns["credit"]):
        raise needs("Choose an amount column or debit/credit columns.")
    index = {name: position for position, name in enumerate(header)}
    for key, name in columns.items():
        if name and name not in index:
            raise needs(f"Column {name!r} is not in this file.")

    def cell(row, key):
        position = index.get(columns[key]) if columns[key] else None
        return row[position].strip() if position is not None and position < len(row) else ""

    try:
        order = date_order([cell(row, "date") for _, row in body if cell(row, "date")], mapping.date_format)
    except ValueError as exc:
        raise needs(str(exc)) from None
    rows, counts = [], {"parsed": 0, "rejected": 0, "blank": 0}
    for number, row in body:
        raw_date, amount_text = cell(row, "date"), cell(row, "amount")
        debit, credit = cell(row, "debit"), cell(row, "credit")
        if not any(value.strip() for value in row):
            counts["blank"] += 1
            continue
        posted = parse_date(raw_date, order)
        try:
            if columns["currency"] and cell(row, "currency") and cell(row, "currency").upper() != currency:
                raise MoneyError("its currency differs from the account currency")
            if columns["amount"]:
                amount = spreadsheet_amount(amount_text, currency)
                amount = amount if mapping.sign == "negative_is_outflow" else -amount
            elif debit and credit:
                raise MoneyError("it has both a debit and a credit")
            else:
                amount = -abs(spreadsheet_amount(debit, currency)) if debit else abs(spreadsheet_amount(credit, currency))
        except MoneyError as exc:
            counts["rejected"] += 1
            issues.append(f"Row {number} was not imported: {str(exc).rstrip('.')}.")
            continue
        if posted is None or not cell(row, "description"):
            counts["rejected"] += 1
            issues.append(f"Row {number} was not imported: it has no valid date or description.")
            continue
        counts["parsed"] += 1
        rows.append({"posted_date": posted, "description": cell(row, "description"), "amount_minor": amount,
                     "currency": currency, "locator": {"rows": [number]}})
    if counts["blank"]:
        issues.append(f"{counts['blank']} blank rows were skipped.")
    used = {**{key: value for key, value in columns.items() if value}, "date_format": order, "sign": mapping.sign}
    return rows, used, issues, {**counts, "columns": names}


def preview(rows, currency, limit=50):
    outflow = sum(row["amount_minor"] for row in rows if row["amount_minor"] < 0)
    inflow = sum(row["amount_minor"] for row in rows if row["amount_minor"] > 0)
    return {"rows": [{**row, "display_amount": format_minor(row["amount_minor"], currency)} for row in rows[:limit]],
            "totals": {"outflow": format_minor(outflow, currency), "inflow": format_minor(inflow, currency)}}
