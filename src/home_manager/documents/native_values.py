"""Conservative typed column roles over native cells. No magnitude/position guesses."""

import re

ROLES = {
    "quantity": {"quantity", "qty", "shares", "units"},
    "unit_price": {"unit price", "unit cost", "price each"},
    "price": {"price", "unit price", "share price", "price per share"},
    "line_total": {"amount", "total", "line total", "extended amount", "extended price"},
    "amount": {"amount", "total", "line total", "extended amount", "extended price"},
    "cost_basis": {"cost basis", "basis"},
    "principal": {"principal", "principal amount"},
    "face_value": {"face value", "par value"},
    "fees": {"fees", "commission", "commissions and fees"},
    "discount": {"discount"},
}

SUMMARY_ROLES = {
    "invoice_total": {"invoice total", "grand total", "total"},
    "invoice_subtotal": {"subtotal", "sub total"},
    "invoice_tax": {"tax", "sales tax"},
    "payments_received": {"payments", "payments received", "paid", "deposits"},
    "balance_due": {"balance due", "remaining balance", "amount due"},
    "new_charges": {"new charges", "current charges"},
    "total": {"total", "grand total"},
    "ending_value": {"ending value", "market value", "account value"},
    "opening_balance": {"opening balance", "beginning balance", "starting balance"},
    "closing_balance": {"closing balance", "ending balance"},
}


def anchor_summary(header, tables, notes):
    from .extraction import AMOUNTS, EvidenceQuote, cell_amount
    by_line = {row.line_id: (table, row) for table in tables if getattr(table, "source", None) == "pdf_text" for row in table.rows}
    changes, references = {}, {}
    for name in type(header).model_fields.keys() & AMOUNTS:
        field = getattr(header, name)
        if field.status != "proposed":
            continue
        found = {cite.line_id for cite in field.evidence if cite.line_id in by_line}
        if not found:
            continue
        cell = None
        if len(found) == 1:
            table, row = by_line[next(iter(found))]
            labels = SUMMARY_ROLES.get(name, {name.replace("_", " ")})
            index = column(table, labels)
            if index is None:
                # The row's label is its first printed cell: a statement's Beginning Balance row leaves its Date cell blank.
                first = next((cell.quote for cell in row.cells if cell.quote.strip()), "")
                label = re.sub(r"[^a-z0-9]+", " ", first.lower()).strip()
                if label in labels:
                    index = column(table, {"amount", "value", "total"})
                    # A statement prints its opening and closing balances in the Balance column, with Amount blank.
                    if index is None or not cell_amount(row.cells[index]):
                        index = column(table, {"balance"}) if name in ("opening_balance", "closing_balance") else index
            if index is not None:
                cell = row.cells[index]
        amount = cell_amount(cell) if cell else None
        changes[name] = field.model_copy(update={"value": amount, "status": "proposed" if amount is not None else "ambiguous",
                                                "evidence": [EvidenceQuote(line_id=cell.line_id, quote=cell.quote)] if amount is not None else field.evidence})
        if amount is None:
            notes.append(f"{name.replace('_', ' ').capitalize()} has no unambiguous native source cell; check its column.")
        else:
            references[name] = reference(cell)
    return header.model_copy(update=changes), references


def column(table, labels):
    width = len(table.header_rows[0].cells)
    if any(len(row.cells) != width or any(getattr(cell, "column_span", 1) != 1 or getattr(cell, "row_span", 1) != 1
                                        for cell in row.cells) for row in [*table.header_rows, *table.rows]):
        return None
    names = [" ".join(row.cells[index].quote for row in table.header_rows) for index in range(width)]
    matches = [i for i, name in enumerate(names) if re.sub(r"[^a-z0-9]+", " ", name.lower()).strip() in labels]
    return matches[0] if len(matches) == 1 else None


def reference(cell):
    return {"cell_id": cell.id, "line_id": cell.line_id, "quote": cell.quote, "source": "pdf_text",
            "source_line_ids": cell.source_line_ids, "word_ids": cell.word_ids}


def anchor_rows(kind, rows, tables, notes):
    from .extraction import cell_amount
    by_line = {row.line_id: (table, row) for table in tables if getattr(table, "source", None) == "pdf_text" for row in table.rows}
    output, references = [], []
    for item in rows:
        found = {cite.line_id for cite in item.evidence if cite.line_id in by_line}
        refs, changes = {}, {}
        if len(found) != 1:
            if found:
                notes.append("A row cites several native table rows; its column associations need review.")
            output.append(item)
            references.append(refs)
            continue
        table, row = by_line[next(iter(found))]
        for name, aliases in ROLES.items():
            if not hasattr(item, name):
                continue
            labels = aliases
            if name == "amount" and kind == "investment_statement":
                labels = {"market value", "value", "ending value"} if item.row_type == "holding" else {"amount", "net amount"}
            elif name == "amount" and kind == "investment_confirmation":
                labels = {"net amount", "net proceeds", "net cost", "settlement amount"}
            index = column(table, labels)
            cell = row.cells[index] if index is not None else None
            amount = cell_amount(cell) if cell else None
            if name == "amount" and kind in ("bank_statement", "credit_card_statement"):
                debit = column(table, {"debit", "debits", "withdrawal", "withdrawals", "charges"})
                credit = column(table, {"credit", "credits", "deposit", "deposits", "payments"})
                if debit is not None or credit is not None:
                    populated = [(direction, row.cells[i]) for direction, i in (("debit", debit), ("credit", credit))
                                 if i is not None and row.cells[i].quote.strip()]
                    if len(populated) == 1:
                        changes["direction"], cell = populated[0]
                        amount = cell_amount(cell)
                    else:
                        amount, cell = None, None
                elif amount is not None:
                    # A signed Amount without a printed debit/credit heading does
                    # not establish the institution's sign convention.
                    notes.append("A statement amount has no debit/credit column; check its direction.")
            changes[name] = amount
            if amount is not None:
                refs[name] = reference(cell)
            elif getattr(item, name) is not None:
                notes.append(f"{name.replace('_', ' ').capitalize()} has no unambiguous native source column; check the row.")
        if "amount" in changes and changes["amount"] is None and kind in (
                "bank_statement", "credit_card_statement", "investment_confirmation", "investment_tax_form"):
            notes.append("A table row with an unresolved required amount was left out of the ledger; review the source.")
            continue
        output.append(item.model_copy(update=changes))
        references.append(refs)
    return output, references
