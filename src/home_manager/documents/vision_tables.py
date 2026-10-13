"""Validated, model-reported table cells. These are text evidence, never pixel geometry."""

from .receipt_schema import TextLine, VisionCell, VisionRow, VisionTable, VisionTables


def validate_tables(raw, lines: list[TextLine], prefix="", index_offset=0, table_start=1) -> VisionTables:
    """All-or-nothing validation of the model's table claim against its full text."""
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Invalid table list")
    tables, used = [], set()
    previous_index = -1
    for table_number, source in enumerate(raw, table_start):
        if not isinstance(source, dict) or set(source) != {"header_rows", "rows"}:
            raise ValueError("Invalid table keys")
        table_id = f"{prefix}table-{table_number}"
        output = []
        width = None
        for section in ("header_rows", "rows"):
            source_rows = source[section]
            maximum = 10 if section == "header_rows" else 500
            if not isinstance(source_rows, list) or not 1 <= len(source_rows) <= maximum:
                raise ValueError("Invalid table rows")
            built = []
            for row_number, source_row in enumerate(source_rows, 1):
                if not isinstance(source_row, dict) or set(source_row) != {"line_index", "cells"}:
                    raise ValueError("Invalid table row keys")
                local_index, cells = source_row["line_index"], source_row["cells"]
                if type(local_index) is not int:
                    raise ValueError("Invalid table line")
                index = local_index + index_offset
                if not index_offset <= index < len(lines) or index in used or index <= previous_index:
                    raise ValueError("Duplicate or invalid table line")
                if not isinstance(cells, list) or not 1 <= len(cells) <= 40 or any(not isinstance(cell, str) for cell in cells):
                    raise ValueError("Invalid table cells")
                if width is None:
                    width = len(cells)
                if len(cells) != width:
                    raise ValueError("Table width differs from header")
                line = lines[index]
                cursor, verified = 0, []
                kind = "header" if section == "header_rows" else "row"
                row_id = f"{table_id}-{kind}-{row_number}"
                for cell_number, quote in enumerate(cells, 1):
                    if quote:
                        position = line.text.find(quote, cursor)
                        if position < 0:
                            raise ValueError("Table cell differs from source line or is out of order")
                        cursor = position + len(quote)
                    verified.append(VisionCell(id=f"{row_id}-cell-{cell_number}", line_id=line.id, quote=quote))
                used.add(index)
                previous_index = index
                built.append(VisionRow(id=row_id, line_id=line.id, cells=verified))
            output.append(built)
        tables.append(VisionTable(id=table_id, header_rows=output[0], rows=output[1]))
    return VisionTables(tables=tables)


def verify_saved_tables(value: VisionTables, lines: list[TextLine]):
    """Reject corrupted persisted cell evidence, including IDs or line text changed later."""
    by_id = {line.id: (index, line.text) for index, line in enumerate(lines)}
    raw = []
    try:
        for table in value.tables:
            source = {}
            for name in ("header_rows", "rows"):
                source[name] = [{"line_index": by_id[row.line_id][0], "cells": [cell.quote for cell in row.cells]}
                                for row in getattr(table, name)]
                for row in getattr(table, name):
                    if any(cell.line_id != row.line_id for cell in row.cells):
                        raise ValueError("Table cell cites a different line")
            raw.append(source)
    except KeyError as exc:
        raise ValueError("Table row cites a missing line") from exc
    rebuilt = validate_tables(raw, lines, prefix=value.tables[0].id.split("table-")[0] if value.tables else "")
    if rebuilt.tables != value.tables:
        raise ValueError("Table evidence IDs do not match the transcription")


def embedded_tables(lines: list[TextLine], prefix="") -> VisionTables:
    """Reconstruct only explicit pipe-delimited rows with recognizable column headings."""
    raw, current = [], None
    for index, line in enumerate(lines):
        cells = [part.strip() for part in line.text.split("|")]
        if len(cells) < 2 or any(cell and cell not in line.text for cell in cells):
            current = None
            continue
        lower = [cell.lower() for cell in cells]
        header = (any("current" in cell or "this period" in cell for cell in lower) and any(
            "ytd" in cell or "year to date" in cell for cell in lower)) or (
            any(cell in ("description", "item", "service", "product") for cell in lower) and
            any(cell in ("amount", "line total", "total", "unit price") for cell in lower))
        if header:
            current = {"header_rows": [{"line_index": index, "cells": cells}], "rows": []}
            raw.append(current)
        elif current and len(cells) == len(current["header_rows"][0]["cells"]):
            current["rows"].append({"line_index": index, "cells": cells})
        else:
            current = None
    raw = [table for table in raw if table["rows"]]
    return validate_tables(raw, lines, prefix=prefix).model_copy(update={"origin": "text_separators"})


def restore_text_tables(result):
    """Derive a view from saved separators, without changing source text or calling a model."""
    for source in getattr(result, "pages", None) or [result]:
        if getattr(source, "vision_tables", None) and source.vision_tables.tables:
            continue
        if not hasattr(source, "vision_tables") or (not hasattr(source, "number") and result.transcription_method != "vision_model"):
            continue
        # Separate receipts on one image must never be joined into one table.
        if getattr(source, "regions", None):
            continue
        try:
            tables = embedded_tables(source.lines, prefix=f"page-{source.number}-" if hasattr(source, "number") else "")
        except ValueError:
            continue
        if tables.tables:
            source.vision_tables = tables
    return result
