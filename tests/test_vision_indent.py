"""SC-10 – SC-12 of specs/dining-receipt-indent: the vision reading's lines carry an indent, the rescue asks for the same,
and the new reading versions leave old readings readable (FR-15 – FR-20). Step 4 of SC-10 and step 3 and (e) of SC-12
are the extraction request (FR-21, FR-22, D28, D33).

Old readings are the SL-01 captures (tests/dining_receipt_data/, D28), laid over a fresh reading's run, never output of the
code under test. Synthetic data and the local model stub only."""

import hashlib
import json

import pytest

from dining_receipt_fixtures import (
    B8_TEXTS,
    BREAKFAST,
    BREAKFAST_INDENTS,
    BREAKFAST_TEXTS,
    CAPTURES,
    GROUP_SPLIT,
    b8_stub,
    breakfast_stub,
    dump_requests,
    group_id,
    image_id,
    pdf_id,
    vision_lines,
)
from home_manager.app.manager import Manager
from home_manager.documents.extraction import EXTRACTION_VERSION, KIND_ROWS, SIDE_LINES_RULE
from home_manager.documents.pdf_reader import GROUP_VERSION, GROUP_VERSIONS, LAYOUT_PDF_VERSIONS, PDF_VERSION, PDF_VERSIONS
from home_manager.library.scanner import ScanLimits
from home_manager.models.vision import VISION_VERSION
from test_dining_baseline_capture import record, start_reasoning
from test_pdf import make_pdf
from test_receipts import make_receipt

OLD = {"R6": "receipt-vision-v6-tables", "P3": "pdf-pages-v3-layout", "G2": "receipt-images-v2-tables"}
KEY_PHRASES = ["indent of 0, 1 or 2", "0 for a line at the main left edge", "1 for a line printed further right, under the line above it",
               "2 for a line printed deeper", "Centered headings and footers are 0", "indent for no other reason", "without leading spaces",
               # An item and its price stay on one line: a list of lines must not cost the receipt its rows.
               "everything printed at the same height across the page", "an item and its price, or a label and its amount, are one text"]


def manager_for(tmp_path, local_model, read=True):
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    manager.configure(str(tmp_path / "managed"))
    if read:
        manager.configure_vision(local_model["config"])
    return manager


def wait(manager):
    manager.future.result(timeout=60)


def read_again(manager, doc_id, force=False):
    """Read the document again (the app's job path): (the run's id, whether it was reused), once the job has finished."""
    started = manager.start_receipt(doc_id, force=force)
    if not started["reused"]:
        wait(manager)
    return started["run_id"], started["reused"]


def image_document(tmp_path, local_model, answer):
    """The breakfast image, read once under the current version with the stub's answer: (manager, document id, run id)."""
    manager = manager_for(tmp_path, local_model)
    make_receipt(manager.store.library.inbox / "breakfast.png", BREAKFAST_TEXTS)
    local_model["output"] = answer
    manager.start_inbox()
    wait(manager)
    [doc] = manager.store.documents()["items"]
    [run] = manager.receipts.history(doc["id"])
    return manager, doc["id"], run["id"]


def reading(manager, run_id):
    run = manager.receipts.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    return run["result"]


def line_payloads(requests):
    """Every `lines` payload of dict entries a reasoning request carries: [(schema name, [entry, …])]. (The purchase description
    question sends plain strings, which FR-21 leaves alone.)"""
    found = []
    for request in requests:
        content = json.loads(request["messages"][-1]["content"])
        if content.get("lines") and isinstance(content["lines"][0], dict):
            found.append((request["response_format"]["json_schema"]["name"], content["lines"]))
    return found


def folder_hash(manager, run_id):
    """Every file of a parse run's folder, by relative path, with its sha256."""
    root = manager.receipts.folder(run_id)
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob("*")) if path.is_file()}


# SC-10 -------------------------------------------------------------------------------------------------------------------

# V10: 27 entries. Lines 13 and 14 are one entry with a line break (indent 1); line 16 has indent 5.
V10 = [(text, indent) for number, (text, indent) in enumerate(BREAKFAST, 1) if number not in (13, 14, 16)]
V10.insert(12, ("Veggie Sausage\nJalapeno Cheese Grits", 1))
V10.insert(14, ("No Allergies", 5))
V10_ANSWER = {"lines": [{"text": text, "indent": indent} for text, indent in V10]}


def test_v10_is_27_entries_over_the_28_breakfast_lines():
    assert len(V10) == 27 and "\n".join(text for text, _ in V10).split("\n") == BREAKFAST_TEXTS


def test_sc10_lines_with_indent(tmp_path, local_model):
    expected_indents = list(BREAKFAST_INDENTS)
    expected_indents[15] = None  # Line 16's 5 is out of range: unknown.
    manager, doc_id, run_id = image_document(tmp_path, local_model, V10_ANSWER)
    try:
        # 1. The request asks for the lines schema; the prompt states each of FR-15's rules.
        [request] = local_model["requests"]
        schema = request["response_format"]["json_schema"]
        assert schema["name"] == "document_transcription" and schema["strict"] is True
        assert set(schema["schema"]["properties"]) == {"lines", "tables"} and schema["schema"]["required"] == ["lines", "tables"]
        item = schema["schema"]["properties"]["lines"]["items"]
        assert set(item["properties"]) == {"text", "indent"} and item["required"] == ["text", "indent"] and item["additionalProperties"] is False
        prompt = request["messages"][0]["content"]
        assert all(phrase in prompt for phrase in KEY_PHRASES), [phrase for phrase in KEY_PHRASES if phrase not in prompt]
        assert "full_text" not in prompt and "zero-based in the final lines" in prompt
        # 2. 28 lines, line-1 … line-28, texts exactly the table's; indent known except line 16.
        result = reading(manager, run_id)
        assert result["parser_version"] == VISION_VERSION == "receipt-vision-v7-indent"
        assert [line["id"] for line in result["lines"]] == [image_id(number) for number in range(1, 29)]
        assert [line["text"] for line in result["lines"]] == BREAKFAST_TEXTS
        assert [line.get("indent") for line in result["lines"]] == expected_indents
        assert result["lines"][12]["indent"] == result["lines"][13]["indent"] == 1 and "indent" not in result["lines"][15]
        # 3. model_text is the joined texts; extracted_text keeps today's form (the capture's, text then code transcript).
        old = json.loads(CAPTURES["result"]["R6"].read_text(encoding="utf-8"))
        assert result["model_text"] == "\n".join(BREAKFAST_TEXTS) == old["model_text"]
        assert result["extracted_text"] == result["model_text"] + old["extracted_text"][len(old["model_text"]):]
        assert len(result["lines"]) == 28
        # 5. A citation quoting a whole line validates, and Find on line-12 matches its text exactly.
        assert result["lines"][11]["id"] == "line-12" and result["lines"][11]["text"] == "Fresh Berry Pancakes"
        assert [line["id"] for line in result["lines"] if "Fresh Berry Pancakes" in line["text"]] == ["line-12"]
        start_reasoning(manager, local_model)
        _, _, replies = breakfast_stub("B0", image_id)
        run, requests = record(manager, local_model, doc_id, run_id, replies)  # Every whole-line quote of B0 validates; publication succeeded.
        assert run["status"] == "succeeded"
        # 4. The extraction request's lines carry indent: 1 on line-11 … line-14 (and 12–13 from the split entry), 0 on the known-0 lines,
        # no key on line-16.
        payloads = line_payloads(requests)
        assert {name for name, _ in payloads} >= {"Classification", "ReceiptDiningSummary", "Items", "Rewards"}
        for name, entries in payloads:
            for entry in entries:
                number = int(entry["line_id"].removeprefix("line-")) if entry["line_id"].startswith("line-") else None
                if number is None:
                    assert set(entry) == {"line_id", "text"}, entry  # A decoded code is no part of the reading's lines.
                elif number == 16:
                    assert entry == {"line_id": "line-16", "text": "No Allergies"}, (name, entry)
                else:
                    assert entry == {"line_id": entry["line_id"], "text": BREAKFAST_TEXTS[number - 1], "indent": BREAKFAST_INDENTS[number - 1]}, (name, entry)
        assert [entry["indent"] for entry in dict(payloads)["Items"][10:14]] == [1, 1, 1, 1]
        # Expected final state: one succeeded v7 run, its stored result holding the lines with indent.
        [run] = manager.receipts.history(doc_id)
        assert (run["id"], run["status"], run["parser_version"]) == (run_id, "succeeded", VISION_VERSION)
        with manager.store.connection() as db:
            stored = json.loads(db.execute("SELECT result_json FROM parse_runs WHERE id=?", (run_id,)).fetchone()[0])
        assert [line.get("indent") for line in stored["lines"]] == expected_indents
    finally:
        manager.close()


@pytest.mark.parametrize("bad", ["1", 1.5, -1, None, True, 3, [1]], ids=["string", "float", "negative", "null", "bool", "three", "list"])
def test_sc10a_a_bad_indent_is_unknown_and_the_reading_is_kept(tmp_path, local_model, bad):
    answer = vision_lines(BREAKFAST_TEXTS, BREAKFAST_INDENTS)
    answer["lines"][10] = {"text": BREAKFAST_TEXTS[10], "indent": bad}
    manager, _, run_id = image_document(tmp_path, local_model, answer)
    try:
        lines = reading(manager, run_id)["lines"]
        assert len(lines) == 28 and "indent" not in lines[10]
        assert [line.get("indent") for line in lines[11:14]] == [1, 1, 1]
        assert len(local_model["requests"]) == 1  # No rescue: a bad indent never fails a reading.
    finally:
        manager.close()


def test_sc10b_a_line_with_no_indent_key_is_unknown(tmp_path, local_model):
    indents = list(BREAKFAST_INDENTS)
    indents[11] = None  # vision_lines leaves the key out.
    manager, _, run_id = image_document(tmp_path, local_model, vision_lines(BREAKFAST_TEXTS, indents))
    try:
        lines = reading(manager, run_id)["lines"]
        assert "indent" not in lines[11] and lines[10]["indent"] == 1 and lines[12]["indent"] == 1
        assert len(local_model["requests"]) == 1
    finally:
        manager.close()


@pytest.mark.parametrize("blank", ["", "  ", "\n"])
def test_sc10c_every_line_blank_fails_the_run_and_publishes_nothing(tmp_path, local_model, blank):
    manager = manager_for(tmp_path, local_model)
    try:
        make_receipt(manager.store.library.inbox / "breakfast.png", BREAKFAST_TEXTS)
        local_model["output"] = {"lines": [{"text": blank, "indent": 0}, {"text": " ", "indent": 1}]}
        manager.start_inbox()
        wait(manager)
        [doc] = manager.store.documents()["items"]
        [run] = manager.receipts.history(doc["id"])
        assert run["status"] == "failed" and run["error"] == "Model response was blank."
        assert manager.receipts.get(run["id"])["result"] is None
    finally:
        manager.close()


def test_sc10d_table_line_indexes_count_the_final_lines(tmp_path, local_model):
    """line_index is zero-based over the lines after a line break inside a text is split: rows 7–10 are line-7 … line-10, and a row
    after the split entry (line 15, which is entry 13 of the answer) is line-15, as for a reading of the same text."""
    tables = [{"header_rows": [{"line_index": 5, "cells": ["Amount:", "$52.76"]}],
               "rows": [{"line_index": 6, "cells": ["Bottled Water", "$3.95"]}, {"line_index": 7, "cells": ["Bottled Water", "$3.95"]},
                        {"line_index": 8, "cells": ["Coffee", "$14.95"]}, {"line_index": 9, "cells": ["Georgia Peach Stack", "$18.70"]},
                        {"line_index": 14, "cells": ["Better Than No Y'all Biscuits (3)", "$7.30"]}]}]
    manager, _, run_id = image_document(tmp_path, local_model, {**V10_ANSWER, "tables": tables})
    try:
        result = reading(manager, run_id)
        [table] = result["vision_tables"]["tables"]
        assert [row["line_id"] for row in table["header_rows"]] == ["line-6"]
        assert [row["line_id"] for row in table["rows"]] == ["line-7", "line-8", "line-9", "line-10", "line-15"]
        assert table["rows"][-1]["cells"][0]["quote"] == "Better Than No Y'all Biscuits (3)"
        assert not [issue for issue in result["issues"] if issue["code"] == "vision_table_invalid"]
    finally:
        manager.close()


def test_a_line_break_inside_a_text_makes_lines_with_the_same_indent(tmp_path, local_model):
    manager, _, run_id = image_document(tmp_path, local_model, {"lines": [{"text": "A\nB", "indent": 1}, {"text": "C", "indent": 2}]})
    try:
        lines = reading(manager, run_id)["lines"]
        assert [(line["id"], line["text"], line["indent"]) for line in lines] == [("line-1", "A", 1), ("line-2", "B", 1), ("line-3", "C", 2)]
    finally:
        manager.close()


# SC-11 -------------------------------------------------------------------------------------------------------------------

def test_sc11_rescue_asks_for_lines(tmp_path, local_model):
    clean = vision_lines(BREAKFAST_TEXTS, BREAKFAST_INDENTS)
    manager, doc_id, first_id = image_document(tmp_path, local_model, clean)
    try:
        before_first = folder_hash(manager, first_id)
        # 1. An old-shape main answer is invalid (D25): the rescue runs, asking for `lines` only, with FR-15's rules.
        local_model["requests"].clear()
        local_model["outputs"] = [{"full_text": "\n".join(BREAKFAST_TEXTS)}, clean]
        second_id, reused = read_again(manager, doc_id, force=True)
        assert not reused and second_id != first_id and len(local_model["requests"]) == 2
        main, rescue = local_model["requests"]
        assert main["response_format"]["json_schema"]["name"] == "document_transcription"
        schema = rescue["response_format"]["json_schema"]
        assert schema["name"] == "document_text_fallback" and schema["strict"] is True
        assert set(schema["schema"]["properties"]) == {"lines"} and schema["schema"]["required"] == ["lines"]
        assert set(schema["schema"]["properties"]["lines"]["items"]["properties"]) == {"text", "indent"}
        assert "tables" not in json.dumps(schema["schema"])
        prompt = rescue["messages"][0]["content"]
        assert all(phrase in prompt for phrase in KEY_PHRASES), [phrase for phrase in KEY_PHRASES if phrase not in prompt]
        assert "full_text" not in prompt
        result = reading(manager, second_id)
        assert [line["text"] for line in result["lines"]] == BREAKFAST_TEXTS
        assert [line.get("indent") for line in result["lines"]] == BREAKFAST_INDENTS
        assert [issue["code"] for issue in result["issues"] if issue["code"] == "vision_table_invalid"] == ["vision_table_invalid"]
        # 2. Both answers invalid: the run fails, the readings of step 1 stay, nothing is published from the failed run.
        before = {run_id: folder_hash(manager, run_id) for run_id in (first_id, second_id)}
        assert before[first_id] == before_first
        local_model["outputs"] = [{"wrong": "shape"}, {"also": "wrong"}]
        third_id, _ = read_again(manager, doc_id, force=True)
        history = {run["id"]: run for run in manager.receipts.history(doc_id)}
        assert {run_id: run["status"] for run_id, run in history.items()} == {first_id: "succeeded", second_id: "succeeded", third_id: "failed"}
        assert history[third_id]["error"] == "Model output did not contain valid full text after a text-only retry."
        assert manager.receipts.get(third_id)["result"] is None
        assert {run_id: folder_hash(manager, run_id) for run_id in (first_id, second_id)} == before
    finally:
        manager.close()


@pytest.mark.parametrize("answer", [{"lines": []}, {"lines": "A"}, {"lines": [{"indent": 1}]}, {"lines": [{"text": 1, "indent": 0}]}, {"lines": ["A"]},
                                    {"lines": [{"text": "A", "indent": 0}], "extra": 1}, {"full_text": "A", "lines": [{"text": "A", "indent": 0}]}],
                         ids=["empty", "string", "no-text", "text-not-string", "entry-not-object", "extra-key", "both-shapes"])
def test_a_main_answer_that_is_not_usable_lines_gets_the_rescue(tmp_path, local_model, answer):
    manager = manager_for(tmp_path, local_model)
    try:
        make_receipt(manager.store.library.inbox / "breakfast.png", BREAKFAST_TEXTS)
        local_model["outputs"] = [answer, vision_lines(["A", "B"], [0, 1])]
        manager.start_inbox()
        wait(manager)
        assert len(local_model["requests"]) == 2
        [doc] = manager.store.documents()["items"]
        [run] = manager.receipts.history(doc["id"])
        assert [(line["text"], line.get("indent")) for line in reading(manager, run["id"])["lines"]] == [("A", 0), ("B", 1)]
    finally:
        manager.close()


# SC-12 -------------------------------------------------------------------------------------------------------------------

PAGE_ANSWERS = [vision_lines(BREAKFAST_TEXTS[:GROUP_SPLIT], BREAKFAST_INDENTS[:GROUP_SPLIT]), vision_lines(BREAKFAST_TEXTS[GROUP_SPLIT:], BREAKFAST_INDENTS[GROUP_SPLIT:])]


def old_library(tmp_path, local_model, kind):
    """One document of kind R6 (image), P3 (one scanned PDF page) or G2 (two images combined), with its reading under the old
    version: the breakfast receipt read under the current code, then that run's version and stored result replaced by the SL-01
    capture (what today's code read, D28). Returns (manager, document id, old run id)."""
    manager = manager_for(tmp_path, local_model, read=kind != "G2")  # The two images are captured and suggested before any reading.
    inbox = manager.store.library.inbox
    if kind == "R6":
        make_receipt(inbox / "breakfast.png", BREAKFAST_TEXTS)
        local_model["output"] = vision_lines(BREAKFAST_TEXTS, BREAKFAST_INDENTS)
    elif kind == "P3":
        make_pdf(inbox / "breakfast.pdf", [None])
        local_model["output"] = vision_lines(BREAKFAST_TEXTS, BREAKFAST_INDENTS)
    else:
        for name, texts in (("receipt_p1.png", BREAKFAST_TEXTS[:GROUP_SPLIT]), ("receipt_p2.png", BREAKFAST_TEXTS[GROUP_SPLIT:])):
            make_receipt(inbox / name, texts)
    manager.start_inbox()
    wait(manager)
    if kind == "G2":
        [group] = manager.suggested_groups()
        manager.configure_vision(local_model["config"])
        local_model["outputs"] = list(PAGE_ANSWERS)
        manager.change_group(group["id"], "confirmed")
        wait(manager)
        doc_id = group["pages"][0]["document_id"]
    else:
        [doc_id] = [doc["id"] for doc in manager.store.documents()["items"]]
    [run] = [run for run in manager.receipts.history(doc_id) if run["status"] == "succeeded"
             and run["parser_version"] in (VISION_VERSION, PDF_VERSION, GROUP_VERSION)]
    stored = CAPTURES["result"][kind].read_text(encoding="utf-8")
    assert json.loads(stored)["parser_version"] == OLD[kind]
    with manager.store.connection() as db:
        db.execute("UPDATE parse_runs SET parser_version=?,result_json=? WHERE id=?", (OLD[kind], stored, run["id"]))
    # The folder holds what the worker wrote: for a page-based result, the stored one without its derived `lines` and `layout_context`.
    worker_file = stored if kind == "R6" else json.dumps({key: value for key, value in json.loads(stored).items() if key not in ("lines", "layout_context")})
    (manager.receipts.folder(run["id"]) / "result.json").write_text(worker_file, encoding="utf-8", newline="")
    return manager, doc_id, run["id"]


def answer_next_reading(local_model, kind):
    """The vision stub's answers for the next reading of a document of this kind."""
    local_model["outputs"] = list(PAGE_ANSWERS) if kind == "G2" else []
    local_model["output"] = vision_lines(BREAKFAST_TEXTS, BREAKFAST_INDENTS)


def test_sc12_step1_version_values():
    assert VISION_VERSION == "receipt-vision-v7-indent"
    assert PDF_VERSION == "pdf-pages-v4-indent" != "pdf-pages-v3-layout" and "pdf-pages-v3-layout" in PDF_VERSIONS and PDF_VERSION in PDF_VERSIONS
    assert GROUP_VERSION == "receipt-images-v3-indent" != "receipt-images-v2-tables"
    assert GROUP_VERSIONS == ("receipt-images-v1", "receipt-images-v2-tables", GROUP_VERSION)
    assert LAYOUT_PDF_VERSIONS == ("pdf-pages-v3-layout", PDF_VERSION)


def test_sc12_old_runs_open_and_a_new_reading_is_one_new_run_per_version(tmp_path, local_model):
    ids = {"R6": image_id, "P3": pdf_id, "G2": group_id}
    for kind, new_version in (("R6", VISION_VERSION), ("P3", PDF_VERSION), ("G2", GROUP_VERSION)):
        manager, doc_id, old_id = old_library(tmp_path / kind, local_model, kind)
        try:
            old = json.loads(CAPTURES["result"][kind].read_text(encoding="utf-8"))
            frozen = folder_hash(manager, old_id)
            assert manager.receipts.get(old_id)["parser_version"] == OLD[kind]
            # 2. The old run opens (the API's view of it): line ids, texts, block ids, model text and extracted text are the capture's, no indent.
            result = reading(manager, old_id)
            assert [line["id"] for line in result["lines"]] == [ids[kind](number) for number in range(1, 29)]
            assert [line["text"] for line in result["lines"]] == BREAKFAST_TEXTS
            assert all(line["block_ids"] == [] and "indent" not in line for line in result["lines"])
            if kind == "R6":
                assert result["model_text"] == old["model_text"] and result["extracted_text"] == old["extracted_text"]
                assert result["engine"]["base_url"] == "http://127.0.0.1:18734/v1"  # The capture's own value (SL-01), never compared with a new port.
            else:
                assert result["parser_version"] == OLD[kind] and result["pages"][0]["lines"][0]["id"] == "page-1-line-1"
            # 4 – 6. Read again (no force): exactly one new run under the new version, its lines carrying indent.
            answer_next_reading(local_model, kind)
            new_id, reused = read_again(manager, doc_id)
            assert not reused and new_id != old_id
            runs = manager.receipts.history(doc_id)
            assert sorted(run["parser_version"] for run in runs) == sorted([OLD[kind], new_version])
            new = reading(manager, new_id)
            assert new["parser_version"] == new_version
            assert [line["id"] for line in new["lines"]] == [ids[kind](number) for number in range(1, 29)]
            assert [line.get("indent") for line in new["lines"]] == BREAKFAST_INDENTS
            assert len(new.get("pages", [])) == {"R6": 0, "P3": 1, "G2": 2}[kind]
            # 7. The same model identity, no force: reused, no new run.
            assert read_again(manager, doc_id) == (new_id, True)
            assert len(manager.receipts.history(doc_id)) == 2
            # 8. History lists the old run, selectable and openable; its folder is byte-identical to before.
            assert {run["id"]: run["status"] for run in runs} == {old_id: "succeeded", new_id: "succeeded"}
            assert manager.receipts.get(old_id)["result"]["lines"] == result["lines"]
            assert folder_hash(manager, old_id) == frozen
        finally:
            manager.close()


def masked(requests, old_text, new_text):
    """The request bodies with the receipt row instruction replaced by one placeholder (D28): `old_text` in a capture, `new_text` in a new request."""
    placeholder = "<<receipt row instruction>>"
    text = dump_requests(requests)
    for what in (old_text, new_text):
        text = text.replace(json.dumps(what, ensure_ascii=False)[1:-1], placeholder)
    return json.loads(text)


def test_sc12_step3_and_e_an_old_reading_sends_today_s_requests_but_for_the_row_instruction(tmp_path, local_model):
    """D28, D33: Extract again from the R6, P3 and G2 runs with B0 sends the same requests as the SL-01 capture (made by v56): the
    `lines` payloads byte for byte, the rest byte for byte once the row instruction (today's text; the new text) is masked."""
    ids = {"R6": image_id, "P3": pdf_id, "G2": group_id}
    old_text = CAPTURES["row_instruction"].read_text(encoding="utf-8")
    assert old_text.startswith(" Missing fields are null; never assume a quantity of one.") and old_text.endswith(KIND_ROWS["dining"])
    new_text = old_text[:-len(KIND_ROWS["dining"])] + SIDE_LINES_RULE + KIND_ROWS["dining"]  # FR-22's sentence closes the common part.
    for kind in ("R6", "P3", "G2"):
        manager, doc_id, old_id = old_library(tmp_path / kind, local_model, kind)
        try:
            start_reasoning(manager, local_model)
            _, replies = breakfast_stub("B0", ids[kind])[1:]
            run, requests = record(manager, local_model, doc_id, old_id, replies)
            capture = json.loads(CAPTURES["requests"][kind].read_text(encoding="utf-8"))
            assert run["prompt_version"] == EXTRACTION_VERSION and EXTRACTION_VERSION == "typed-extraction-v57-dining-indent"
            # Same number of requests, in the same order.
            names = [request["response_format"]["json_schema"]["name"] for request in requests]
            assert names == [request["response_format"]["json_schema"]["name"] for request in capture] and len(names) == 7
            # The lines payloads: byte for byte, and no entry carries an indent (the reading has none).
            for request, old in zip(requests, capture):
                now, then = json.loads(request["messages"][-1]["content"]), json.loads(old["messages"][-1]["content"])
                assert json.dumps(now["lines"], ensure_ascii=False) == json.dumps(then["lines"], ensure_ascii=False)
                assert request["messages"][-1]["content"] == old["messages"][-1]["content"]
                assert not any(isinstance(line, dict) and "indent" in line for line in now["lines"])
            # The rest of each body, with the row instruction masked: only the rows request carried it, and it is the only difference.
            assert masked(requests, old_text, new_text) == masked(capture, old_text, new_text)
            assert [name for name, request, old in zip(names, requests, capture) if request != old] == ["Items"]
            [rows] = [request for request in requests if request["response_format"]["json_schema"]["name"] == "Items"]
            assert new_text in rows["messages"][0]["content"] and old_text not in rows["messages"][0]["content"]
            # (e) D33: no body holds the extraction version, and every prompt but the masked instruction equals the capture's.
            assert EXTRACTION_VERSION not in dump_requests(requests) and "v56" not in dump_requests(requests)
            assert [request["messages"][0]["content"] for request in requests if request is not rows] == \
                [old["messages"][0]["content"] for old in capture if old["response_format"]["json_schema"]["name"] != "Items"]
        finally:
            manager.close()


def test_sc12a_an_embedded_text_page_sends_no_indent_to_the_extraction_model(tmp_path, local_model):
    manager = manager_for(tmp_path, local_model, read=False)
    try:
        make_pdf(manager.store.library.inbox / "digital.pdf", ["\n".join(B8_TEXTS)])
        manager.start_inbox()
        wait(manager)
        [doc] = manager.store.documents()["items"]
        [parse] = manager.receipts.history(doc["id"])
        start_reasoning(manager, local_model)
        _, _, replies = b8_stub(lambda number: f"page-1-layout-line-{number}")  # An embedded-text page is sent as its native layout lines.
        replies.pop("ReceiptStarts")  # One short page: nothing asks where a receipt starts.
        _, requests = record(manager, local_model, doc["id"], parse["id"], replies)
        payloads = line_payloads(requests)
        assert payloads and all(set(entry) == {"line_id", "text"} for _, entries in payloads for entry in entries)
        assert not any(isinstance(line, dict) and "indent" in line for _, entries in payloads for line in entries)
    finally:
        manager.close()


def test_sc12_step5_a_scanned_pdf_read_again_is_one_run_not_one_per_page(tmp_path, local_model):
    manager = manager_for(tmp_path, local_model)
    try:
        make_pdf(manager.store.library.inbox / "scan.pdf", [None, None])
        local_model["outputs"] = [vision_lines(["PAGE ONE", "  side", "Total 1.00"], [0, 1, 0]), vision_lines(["PAGE TWO"], [0])]
        manager.start_inbox()
        wait(manager)
        [doc] = manager.store.documents()["items"]
        [run] = manager.receipts.history(doc["id"])
        assert run["parser_version"] == PDF_VERSION
        pages = reading(manager, run["id"])["pages"]
        assert [(line["id"], line["text"], line.get("indent")) for line in pages[0]["lines"]] == [
            ("page-1-line-1", "PAGE ONE", 0), ("page-1-line-2", "  side", 1), ("page-1-line-3", "Total 1.00", 0)]
        assert [(line["id"], line["indent"]) for line in pages[1]["lines"]] == [("page-2-line-1", 0)]
        assert len(manager.receipts.history(doc["id"])) == 1 and len(local_model["requests"]) == 2
    finally:
        manager.close()


def test_sc12a_an_embedded_text_page_has_no_indent(tmp_path, local_model):
    manager = manager_for(tmp_path, local_model)
    try:
        make_pdf(manager.store.library.inbox / "digital.pdf", ["Embedded line one has enough text\nEmbedded line two has enough text as well"])
        manager.start_inbox()
        wait(manager)
        [doc] = manager.store.documents()["items"]
        [run] = manager.receipts.history(doc["id"])
        result = reading(manager, run["id"])
        [page] = result["pages"]
        assert page["method"] == "embedded_text" and page["lines"] and all("indent" not in line for line in page["lines"])
        assert all("indent" not in line for line in result["lines"]) and not local_model["requests"]
    finally:
        manager.close()


def test_sc12b_a_pdf_with_an_embedded_and_a_scanned_page_has_indent_only_on_the_scanned_one(tmp_path, local_model):
    manager = manager_for(tmp_path, local_model)
    try:
        make_pdf(manager.store.library.inbox / "mixed.pdf", ["Embedded text page " + "word " * 30, None])
        local_model["output"] = vision_lines(["SCANNED PAGE", "a note"], [0, 1])
        manager.start_inbox()
        wait(manager)
        [doc] = manager.store.documents()["items"]
        [run] = manager.receipts.history(doc["id"])
        first, second = reading(manager, run["id"])["pages"]
        assert (first["method"], second["method"]) == ("embedded_text", "vision_model")
        assert all("indent" not in line for line in first["lines"])
        assert [line["indent"] for line in second["lines"]] == [0, 1]
        assert len(local_model["requests"]) == 1
    finally:
        manager.close()


def test_sc12c_an_interrupted_old_group_run_is_published_by_recovery(tmp_path, local_model):
    """A run under receipt-images-v2-tables left running with its result.json: startup recovery publishes it as a page-based result
    (the check in ReceiptService.publish accepts every group version, D32)."""
    manager, doc_id, old_id = old_library(tmp_path, local_model, "G2")
    try:
        with manager.store.connection() as db:
            db.execute("UPDATE parse_runs SET status='running',result_json=NULL WHERE id=?", (old_id,))
        manager.receipts.recover()
        run = manager.receipts.get(old_id)
        assert run["status"] == "succeeded" and run["parser_version"] == "receipt-images-v2-tables", run["error"]
        assert [line["id"] for line in run["result"]["lines"]] == [group_id(number) for number in range(1, 29)]
        assert [line["id"] for line in run["result"]["lines"]][0] == "page-1-line-1" and run["result"]["lines"][GROUP_SPLIT]["id"] == "page-2-line-1"
        assert all("indent" not in line for line in run["result"]["lines"])
        assert run["error"] is None
    finally:
        manager.close()


def test_a_line_with_unknown_indent_serializes_exactly_as_before():
    from pydantic import ValidationError

    from home_manager.documents.receipt_schema import TextLine
    old = TextLine(id="line-1", text="A", block_ids=[])
    assert old.indent is None and old.model_dump() == {"id": "line-1", "text": "A", "block_ids": []}
    assert old.model_dump_json() == '{"id":"line-1","text":"A","block_ids":[]}'
    assert TextLine.model_validate({"id": "line-1", "text": "A", "block_ids": []}) == old
    known = TextLine(id="line-1", text="A", block_ids=[], indent=0)
    assert known.model_dump() == {"id": "line-1", "text": "A", "block_ids": [], "indent": 0}
    assert TextLine.model_validate_json(known.model_dump_json()) == known
    for bad in (-1, 3):
        with pytest.raises(ValidationError):
            TextLine(id="line-1", text="A", block_ids=[], indent=bad)
