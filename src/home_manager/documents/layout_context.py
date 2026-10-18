"""Shared readable native evidence, without changing historical transcription IDs.

Rows get their own IDs: a PDF stream line is not a visual row. Geometry stays
in the saved layout; consumers use this small, deterministic projection.
"""

from types import SimpleNamespace

from .receipt_schema import TextLine


def native_page(page):
    return (page.method == "embedded_text" and page.layout is not None
            and not {"unsupported_text_rotation", "overlapping_text", "unicode_mapping", "degenerate_glyph"}.intersection(page.layout.issues)
            and not (not page.layout.tables and page.vision_tables and page.vision_tables.tables))


def project_page(page):
    layout = page.layout
    lines, tables = [], []
    source_lines = {line.id: line for line in layout.lines}
    source_tables = {table.id: table for table in layout.tables}
    for block in layout.blocks:
        if block.kind != "table":
            lines.extend(TextLine(id=id, text=source_lines[id].text, block_ids=[block.id]) for id in block.line_ids)
            continue
        table = source_tables[block.table_id]
        headers, rows = [], []
        for index in range(table.rows):
            row_id = f"{table.id}-row-{index}"
            cells = sorted((cell for cell in table.cells if cell.row == index), key=lambda cell: cell.column)
            # Spans remain explicit. Do not flatten a merged heading into made-up cells.
            adapted = [SimpleNamespace(id=cell.id, line_id=row_id, quote=cell.text,
                                       source_line_ids=cell.line_ids, word_ids=cell.word_ids,
                                       row_span=cell.row_span, column_span=cell.column_span) for cell in cells]
            lines.append(TextLine(id=row_id, text=" | ".join(cell.text for cell in cells), block_ids=[block.id]))
            (headers if index in table.header_rows else rows).append(SimpleNamespace(id=row_id, line_id=row_id, cells=adapted))
        tables.append(SimpleNamespace(id=table.id, header_rows=headers, rows=rows, source="pdf_text", page=page.number))
    return lines, tables


def evidence_lines(evidence):
    if not hasattr(evidence, "pages"):
        return evidence.lines
    return [line for page in evidence.pages for line in (project_page(page)[0] if native_page(page) else page.lines)]


def evidence_tables(evidence):
    result = []
    for page in getattr(evidence, "pages", [evidence]):
        if hasattr(page, "method") and native_page(page):
            result.extend(project_page(page)[1])
        else:
            result.extend(getattr(getattr(page, "vision_tables", None), "tables", []))
    return result


def citation_lines(evidence):
    """Both namespaces remain resolvable for older extraction runs and saved corrections."""
    return list({line.id: line for line in [*evidence.lines, *evidence_lines(evidence)]}.values())


def viewer_context(evidence):
    def cell_value(cell):
        return {"id": cell.id, "line_id": cell.line_id, "quote": cell.quote,
                "word_ids": cell.word_ids, "source_line_ids": cell.source_line_ids,
                "row_span": cell.row_span, "column_span": cell.column_span}

    return {"lines": [line.model_dump() for line in evidence_lines(evidence)],
            "tables": [{"id": table.id, "page": table.page, "source": table.source,
                        **{key: [{"id": row.id, "line_id": row.line_id, "cells": [cell_value(cell) for cell in row.cells]}
                                 for row in getattr(table, key)] for key in ("header_rows", "rows")}}
                       for table in evidence_tables(evidence) if getattr(table, "source", None) == "pdf_text"]}


def saved_lines(value):
    """Index old minimal payloads as before; validate native evidence before using it."""
    if any(page.get("layout") for page in value.get("pages", [])):
        from .pdf_reader import read_result
        return [line.model_dump() for line in evidence_lines(read_result(value))]
    return value.get("lines") or []
