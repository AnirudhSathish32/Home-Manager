import pytest

import json

from home_manager.core.jobs import Work
from home_manager.documents.extraction import PayLine, PayRowClasses, Value, anchor_paystub, ask, paystub_chunks, paystub_columns, paystub_table_context
from home_manager.documents.reasoning import EvidenceQuote, ReasoningConfig
from home_manager.documents.receipt_schema import TextLine
from home_manager.documents.vision_tables import validate_tables, verify_saved_tables
from home_manager.models.vision import transcribe
from test_receipts import make_receipt
from types import SimpleNamespace
from home_manager.documents.vision_tables import embedded_tables, restore_text_tables


def test_saved_text_tables_are_reconstructed_without_changing_source_lines():
    lines, raw = sample()
    result = SimpleNamespace(transcription_method="vision_model", lines=lines, vision_tables=None, regions=[])
    original = [line.model_dump() for line in lines]
    restore_text_tables(result)
    assert result.vision_tables.origin == "text_separators"
    assert result.vision_tables.tables[0].rows[1].cells[1].quote == ""
    assert [line.model_dump() for line in lines] == original
    verify_saved_tables(result.vision_tables, lines)
    saved = result.vision_tables
    restore_text_tables(result)
    assert result.vision_tables is saved
    flat = [TextLine(id="line-1", text="Description Current YTD", block_ids=[]),
            TextLine(id="line-2", text="Regular pay 2000.00 52000.00", block_ids=[])]
    assert not embedded_tables(flat).tables  # Whitespace alone never establishes columns.


def test_summary_cells_fit_input_budget_and_keep_last_totals():
    from home_manager.documents.extraction import table_summary, WHOLE_BYTES
    lines, raw = sample()
    tables = validate_tables(raw, lines).tables
    selected, context = table_summary(lines, tables, [])
    assert context[0]["rows"][-1]["cells"][1]["text"] == "1550.00"
    large = [TextLine(id=f"filler-{i}", text="x" * 1000, block_ids=[]) for i in range(100)]
    notes = []
    selected, context = table_summary(lines[:1] + large + lines[1:], tables, notes)
    payload = {"lines": [{"line_id": line.id, "text": line.text} for line in selected], "reported_tables": context}
    assert len(json.dumps(payload, ensure_ascii=False).encode()) <= WHOLE_BYTES
    assert context[0]["rows"][-1]["cells"][1]["text"] == "1550.00"
    assert notes


def sample():
    lines = [TextLine(id=f"line-{index + 1}", text=text, block_ids=[]) for index, text in enumerate([
        "Description | This period | Year to date",
        "Regular pay | 2000.00 | 52000.00",
        "Overtime | | 300.00",
        "Net pay | 1550.00 | 40100.00",
    ])]
    raw = [{"header_rows": [{"line_index": 0, "cells": ["Description", "This period", "Year to date"]}],
            "rows": [{"line_index": 1, "cells": ["Regular pay", "2000.00", "52000.00"]},
                     {"line_index": 2, "cells": ["Overtime", "", "300.00"]},
                     {"line_index": 3, "cells": ["Net pay", "1550.00", "40100.00"]}]}]
    return lines, raw


def test_tables_keep_exact_source_cells_and_reject_ambiguous_layout():
    lines, raw = sample()
    tables = validate_tables(raw, lines)
    assert tables.tables[0].rows[0].cells[2].id == "table-1-row-1-cell-3"
    assert tables.tables[0].rows[0].cells[2].quote == "52000.00"
    verify_saved_tables(tables, lines)
    assert paystub_columns(tables.tables[0]) == (1, 2)
    assert paystub_table_context(tables.tables, lines[2:])[0]["header_rows"][0]["cells"][1]["text"] == "This period"
    raw[0]["rows"][0]["cells"][1] = "52000.00"
    with pytest.raises(ValueError, match="out of order"):
        validate_tables(raw, lines)
    raw[0]["rows"][0]["cells"][1] = "2000.00"
    raw[0]["rows"][1]["line_index"] = 1
    with pytest.raises(ValueError, match="Duplicate"):
        validate_tables(raw, lines)


def test_paystub_money_is_copied_from_named_cells_not_model_guess():
    lines, raw = sample()
    tables = validate_tables(raw, lines).tables
    cite = lambda line: [EvidenceQuote(line_id=line.id, quote=line.text)]
    rows = [PayLine(description="Regular pay", group="earnings", category="regular_pay", current="52000.00", ytd="2000.00",
                    evidence=cite(lines[1])),
            PayLine(description="Overtime", group="earnings", category="overtime", current="300.00", ytd=None,
                    evidence=cite(lines[2]))]
    header = type("Header", (), {})()
    for name in ("gross_pay", "gross_pay_ytd", "net_pay", "net_pay_ytd", "taxes", "deductions"):
        setattr(header, name, Value(value=None, status="missing", evidence=[]))
    header.net_pay = Value(value="40100.00", status="proposed", evidence=cite(lines[3]))
    header.net_pay_ytd = Value(value="1550.00", status="proposed", evidence=cite(lines[3]))
    # Use a real model_copy-capable header, as the extraction pipeline does.
    from pydantic import create_model
    from home_manager.documents.receipt_schema import StrictModel
    Header = create_model("PayHeaderForTest", __base__=StrictModel,
                          **{name: (Value, ...) for name in ("gross_pay", "gross_pay_ytd", "net_pay", "net_pay_ytd", "taxes", "deductions")})
    header = Header(**{name: getattr(header, name) for name in Header.model_fields})
    fixed, rows, references = anchor_paystub(header, rows, tables, [])
    assert (rows[0].current, rows[0].ytd) == ("2000.00", "52000.00")
    assert (rows[1].current, rows[1].ytd) == (None, "300.00")
    assert (fixed.net_pay.value, fixed.net_pay_ytd.value) == ("1550.00", "40100.00")
    assert references[0]["current"] == {"cell_id": "table-1-row-1-cell-2", "line_id": "line-2", "quote": "2000.00"}


def test_vision_response_discards_invalid_table_but_keeps_full_text(tmp_path, local_model):
    image = tmp_path / "paystub.png"
    make_receipt(image)
    lines, raw = sample()
    full_text = "\n".join(line.text for line in lines)
    local_model["output"] = {"full_text": full_text, "tables": raw}
    reading = transcribe(local_model["config"], image)
    assert reading.full_text == full_text and reading.tables == raw and not reading.table_issue
    bad = [{**raw[0], "rows": [{"line_index": 1, "cells": ["Regular pay", "52000.00", "2000.00"]}]}]
    local_model["output"] = {"full_text": full_text, "tables": bad}
    reading = transcribe(local_model["config"], image)
    assert reading.full_text == full_text and reading.tables == [] and reading.table_issue


def test_malformed_structured_response_gets_one_text_only_retry(tmp_path, local_model):
    image = tmp_path / "document.png"
    make_receipt(image)
    local_model["outputs"] = [{"wrong": "shape"}, {"full_text": "Regular pay | 2000.00 | 52000.00"}]
    reading = transcribe(local_model["config"], image)
    assert reading.table_issue and reading.full_text.startswith("Regular pay")
    assert len(local_model["requests"]) == 2
    assert set(local_model["requests"][1]["response_format"]["json_schema"]["schema"]["properties"]) == {"full_text"}


def test_paystub_classification_request_contains_named_cells(local_model):
    lines, raw = sample()
    tables = validate_tables(raw, lines).tables
    context = paystub_table_context(tables, lines[1:2])
    local_model["output"] = {"lines": [{"description": "Regular pay", "group": "earnings", "category": "regular_pay",
                                      "evidence": [{"line_id": "line-2", "quote": lines[1].text}]}]}
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    answer = ask(config, Work.detached(), PayRowClasses, "Classify pay rows. ", lines[1:2], 2048, table_context=context)
    assert answer.lines[0].category == "regular_pay"
    request = local_model["requests"][-1]
    assert "current" not in request["response_format"]["json_schema"]["schema"]["$defs"]["PayRowClass"]["properties"]
    supplied = json.loads(request["messages"][1]["content"])["reported_tables"][0]
    assert supplied["header_rows"][0]["cells"][1]["text"] == "This period"
    assert supplied["rows"][0]["cells"][2]["text"] == "52000.00"


def test_table_header_is_repeated_after_chunk_boundary():
    lines = [TextLine(id=f"line-{index + 1}", text="filler" if index not in (0, 81) else
                      ("Description | This period | YTD" if index == 0 else "Regular pay | 2000.00 | 52000.00"),
                      block_ids=[]) for index in range(82)]
    tables = validate_tables([{"header_rows": [{"line_index": 0, "cells": ["Description", "This period", "YTD"]}],
                               "rows": [{"line_index": 81, "cells": ["Regular pay", "2000.00", "52000.00"]}]}], lines).tables
    parts = list(paystub_chunks(lines, tables))
    assert len(parts) == 2
    assert paystub_table_context(tables, parts[1])[0]["header_rows"][0]["cells"][1]["text"] == "This period"


def test_equal_numbers_keep_distinct_column_ids_and_multiple_headers():
    lines = [TextLine(id=f"line-{index + 1}", text=text, block_ids=[]) for index, text in enumerate([
        "Pay item | Current | YTD", "Name | Amount | Amount", "401k match | 50.00 | 50.00",
        "Tax item | This period | Year to date", "Medicare | 20.00 | 300.00",
    ])]
    raw = [{"header_rows": [{"line_index": 0, "cells": ["Pay item", "Current", "YTD"]},
                            {"line_index": 1, "cells": ["Name", "Amount", "Amount"]}],
            "rows": [{"line_index": 2, "cells": ["401k match", "50.00", "50.00"]}]},
           {"header_rows": [{"line_index": 3, "cells": ["Tax item", "This period", "Year to date"]}],
            "rows": [{"line_index": 4, "cells": ["Medicare", "20.00", "300.00"]}]}]
    tables = validate_tables(raw, lines).tables
    assert paystub_columns(tables[0]) == (1, 2)
    assert paystub_columns(tables[1]) == (1, 2)
    assert tables[0].rows[0].cells[1].quote == tables[0].rows[0].cells[2].quote
    assert tables[0].rows[0].cells[1].id != tables[0].rows[0].cells[2].id
