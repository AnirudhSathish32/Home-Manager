"""Full-text index over saved document text (docs/documents.md "Searching document text"). Synthetic transcriptions only."""

import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from home_manager.app.api import create_app
from home_manager.core.jobs import Work
from home_manager.documents import extraction
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance.assistant import AssistantService, route
from home_manager.finance.tools import DOCUMENT_TYPES, DocumentSearchInput, DocumentTextInput, FinanceTools
from home_manager.library import text_index
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import MIGRATIONS, Store, now
from home_manager.library.trash import empty
from test_managed_library import library, scan  # noqa: F401 (library is a fixture)

LEASE = [["RESIDENTIAL LEASE AGREEMENT", "Landlord: Maple Property Co", "Tenant: A. Resident", "Monthly rent 1,850.00 due on the 1st",
          "Security deposit 1,850.00", "Pets allowed with written consent", "Utilities: tenant pays electricity", "Water included"],
         ["EARLY TERMINATION", "Tenant may end this lease early with 60 days written", "notice and a fee equal to one month's rent.",
          "Renewal is automatic for 12 months unless either party", "gives notice 30 days before the end date.", "", "Signed 2026-01-15"]]
POLICY = ["HOMEOWNERS INSURANCE DECLARATIONS", "Policy number HO-5521-889", "Annual premium 1,204.00", "Dwelling coverage 350,000",
          "All other perils deductible 1,000", "Wind and hail deductible 2% of dwelling", "Water backup coverage 10,000"]


def pdf_lines(pages):
    return [{"id": f"page-{number}-line-{index}", "text": text, "block_ids": []}
            for number, page in enumerate(pages, 1) for index, text in enumerate(page, 1)]


def image_lines(texts):
    return [{"id": f"line-{index}", "text": text, "block_ids": []} for index, text in enumerate(texts, 1)]


def read(store, doc, lines, run_id, status="succeeded", parser="pdf-pages-v1", created="2026-09-01T00:00:00+00:00"):
    """A saved reading of the document's current version, as ReceiptService.publish leaves it."""
    with store.connection() as db:
        db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at,result_json) VALUES(?,?,?,'{}',?,?,?,?)",
                   (run_id, doc["current_hash"], parser, status, created, created, json.dumps({"lines": lines})))
    text_index.index_quietly(store, run_id)
    return run_id


def capture(store, inbox, name, content):
    (inbox / name).write_bytes(content)
    scan(store)
    return next(doc for doc in store.documents()["items"] if doc["relative_path"].endswith(name))


@pytest.fixture
def documents(library):  # noqa: F811
    store, inbox = library
    lease = capture(store, inbox, "lease.pdf", b"synthetic lease")
    policy = capture(store, inbox, "policy.png", b"synthetic policy")
    read(store, lease, pdf_lines(LEASE), "a" * 32)
    read(store, policy, image_lines(POLICY), "b" * 32, parser="vision-v1")
    return store, inbox, lease, policy


def test_passages_keep_line_ids_overlap_and_never_cross_pages():
    found = text_index.passages(pdf_lines(LEASE))
    assert found[0][0] == [f"page-1-line-{i}" for i in range(1, 9)]
    assert all(len({line.split("-line-")[0] for line in ids}) == 1 for ids, _ in found)  # One page each.
    second_page = [ids for ids, _ in found if ids[0].startswith("page-2-")]
    assert second_page[0][0] == "page-2-line-1" and "page-2-line-6" not in sum(second_page, [])  # The blank line is skipped.
    long = text_index.passages(image_lines([f"row {i}" for i in range(1, 16)]))
    assert [ids[0] for ids, _ in long] == ["line-1", "line-7", "line-13"]  # Eight lines, overlapping by two.
    assert text_index.passages([]) == []


@pytest.mark.parametrize("typed, expected", [
    ("deductible", '"deductible"*'),
    ("early termination", '"early" "termination"*'),
    ("$1,000", '"1 000"*'),
    ('" OR NEAR( x:y -z *', '"OR" "NEAR" "x y" "z"*'),
    ("*** ---", None),
    ("", None),
])
def test_typed_words_never_become_fts_syntax(typed, expected):
    assert text_index.match_expression(typed) == expected


def test_search_finds_words_in_the_text_with_a_snippet_and_the_lines(documents):
    store, _, lease, policy = documents
    found = store.documents(query="deductible")
    assert [doc["id"] for doc in found["items"]] == [policy["id"]]
    match = found["items"][0]["match"]
    assert "\x02deductible\x03" in match["snippet"].lower() and match["line_ids"][0] == "line-1"
    # A phrase broken across two lines still matches; a word ending in a prefix does too.
    assert [doc["id"] for doc in store.documents(query="written notice")["items"]] == [lease["id"]]
    assert [doc["id"] for doc in store.documents(query="termin")["items"]] == [lease["id"]]
    assert store.documents(query="1,850.00")["items"][0]["id"] == lease["id"]
    # Names still match without any text match.
    by_name = store.documents(query="policy.png")["items"]
    assert [doc["id"] for doc in by_name] == [policy["id"]] and by_name[0]["match"] is None
    assert store.documents(query="asbestos")["total"] == 0
    assert store.documents(query="%%")["total"] == 0


def test_only_the_current_good_reading_is_searched(documents):
    store, _, lease, _ = documents
    read(store, lease, pdf_lines([["Replaced reading about a trampoline"]]), "c" * 32, created="2026-09-02T00:00:00+00:00")
    assert store.documents(query="trampoline")["total"] == 1
    assert store.documents(query="termination")["total"] == 0  # The older reading is no longer the document's text.
    read(store, lease, pdf_lines([["Failed reading about a unicycle"]]), "d" * 32, status="failed", created="2026-09-03T00:00:00+00:00")
    assert store.documents(query="unicycle")["total"] == 0
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM document_passages WHERE parse_run_id=?", ("d" * 32,)).fetchone()[0] == 0


def test_backfill_is_idempotent_and_reindexes_on_a_new_version(documents, monkeypatch):
    store, *_ = documents
    assert text_index.backfill(store) == 0
    with store.connection() as db:
        count = db.execute("SELECT count(*) FROM document_passages").fetchone()[0]
    monkeypatch.setattr(text_index, "INDEX_VERSION", text_index.INDEX_VERSION + 1)
    assert text_index.backfill(store) == 2
    assert text_index.backfill(store) == 0
    assert text_index.backfill(store, rebuild=True) == 2
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM document_passages").fetchone()[0] == count
        assert db.execute("SELECT count(*) FROM document_passages_fts WHERE document_passages_fts MATCH 'deductible'").fetchone()[0] == 1


def test_trash_removes_a_documents_passages(documents):
    store, _, lease, _ = documents
    store.library_action(lease["id"], lease["current_hash"], "trash")
    assert store.documents(query="termination")["total"] == 0
    assert store.documents(folder="trash", query="termination")["total"] == 1
    assert empty(store)["deleted"] == 1
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM document_passages WHERE parse_run_id=?", ("a" * 32,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM document_passages_fts WHERE document_passages_fts MATCH 'termination'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM document_passages_fts WHERE document_passages_fts MATCH 'deductible'").fetchone()[0] == 1
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_upgrade_leaves_earlier_readings_waiting_for_the_index():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    for number, script in MIGRATIONS:
        if number == 42:  # A reading saved before the index existed.
            db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at,result_json) "
                       "VALUES('old','h','pdf-pages-v1','{}','succeeded','t','t',?)", (json.dumps({"lines": image_lines(POLICY)}),))
            db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at) VALUES('ocr','h','receipt-ocr-v1','{}','succeeded','t','t')")
        db.executescript(script.read_text())
    assert text_index.pending(db) == ["old"]
    assert text_index.index_run(db, "old") == 1 and text_index.pending(db) == []


def test_document_tools_return_passages_and_surrounding_lines(documents):
    store, _, lease, policy = documents
    tools = FinanceTools(store)
    found = tools.search_documents(DocumentSearchInput(query="early termination"))
    assert [doc["document_id"] for doc in found["documents"]] == [lease["id"]]
    passage = found["documents"][0]["passages"][0]
    assert "60 days written" in passage["text"] and passage["line_ids"][0] == "page-2-line-1"
    assert tools.search_documents(DocumentSearchInput(query="deductible", document_type="housing_document"))["documents"] == []
    text = tools.get_document_text(DocumentTextInput(document_id=lease["id"], around_line="page-2-line-2", lines=6))
    assert [line["line_id"] for line in text["lines"]][0] == "page-1-line-7" and text["total_lines"] == 14
    with pytest.raises(ValueError, match="not in the document"):
        tools.get_document_text(DocumentTextInput(document_id=policy["id"], around_line="page-9-line-1"))
    with pytest.raises(ValueError, match="words to look for"):
        tools.search_documents(DocumentSearchInput(query="!!"))


def test_tool_document_types_match_the_classifier():
    assert DOCUMENT_TYPES == extraction.DOCUMENT_TYPES


def test_questions_about_what_a_document_says_route_to_document_text():
    assert route("What's my deductible for wind damage?") == "documents"
    assert route("Can I end my lease early?") == "documents"
    assert route("What does the insurance policy say about water backup?") == "documents"
    assert route("How much did I spend on groceries in August?") == "finance"
    assert route("Is milk cheaper at Costco or Walmart?") == "items"


def test_answers_keep_only_lines_the_cited_search_returned(documents, local_model):
    store, _, _, policy = documents
    service = AssistantService(store, FinanceTools(store))
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    step = lambda **fields: {"action": "call_tool", "tool": None, "arguments_json": None, "answer": None,  # noqa: E731
                             "cited_calls": [], "cited_lines": [], "missing_evidence": [], **fields}
    local_model["outputs"] = [
        step(tool="search_documents", arguments_json=json.dumps({"query": "deductible"})),
        step(action="answer", answer="Your policy says: \"All other perils deductible 1,000\"; wind is 2,500.00.",
             cited_calls=[1], cited_lines=["line-5", "line-99"])]
    run_id = service.enqueue("What's my deductible?", config)
    service.run(run_id, config, Work("inference", "assistant", "Answering", sink=store.record_model_run))
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    result = run["result"]
    assert result["route"] == "documents"
    assert result["sources"] == [{"document_id": policy["id"], "title": "policy.png", "line_ids": ["line-5"]}]
    assert result["unverified_figures"] == ["2500.00"]  # 1,000 is printed in the passage; 2,500.00 is not.
    prompt = local_model["requests"][0]["messages"][0]["content"]
    assert "search_documents" in prompt and "get_spending" not in prompt


def test_search_api_returns_the_text_match(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        doc = capture(store, store.library.inbox, "policy.png", b"synthetic policy")
        read(store, doc, image_lines(POLICY), "e" * 32, parser="vision-v1", created=now())
    finally:
        store.close()
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        found = client.get("/api/search", params={"q": "water backup"}).json()["documents"]
        assert found["total"] == 1 and found["items"][0]["match"]["line_ids"][0] == "line-1"
        assert client.post("/api/finance/tools/search_documents", json={"query": "premium"}).json()["documents"][0]["document_id"] == doc["id"]
