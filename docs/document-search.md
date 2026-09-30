# Searching document text

Status: built 2026-09-29 (migration 042, `library/text_index.py`).

Search and the assistant can use the words inside documents, not only their names. A local SQLite FTS5 index
covers every saved reading. No model and no GPU are involved.

## Why not RAG

Receipts, statements, bills, pay stubs and investment documents are already read line by line into typed ledger
records, and each value cites its source line. Money questions are answered from those records by exact SQL
(`finance/tools.py`). Retrieving text chunks for them would miss rows and leave the arithmetic to a small local
model. Two things were missing:

1. Search matched only a document's title, merchant and file name.
2. Prose documents (insurance, leases, loans, employment and tax letters) have no ledger rows for their clauses,
   so the assistant could not answer "what's my deductible?".

Embeddings stay deferred. [architecture.md](architecture.md) keeps them for measured misses of keyword retrieval.

## The index

- **Passages.** `document_passages` holds eight consecutive non-blank lines of one page, overlapping by two
  lines so a phrase broken across lines still matches. Each passage keeps its line IDs (`line-N` or
  `page-N-line-M`).
- **Full-text table.** `document_passages_fts` is an external-content FTS5 table (`unicode61`, diacritics
  removed, prefix indexes). Triggers keep it in step with the passages.
- **What is indexed.** Only finished readings (`succeeded`/`partial`, not the retired OCR parser) are indexed.
  Queries join through the library's `text_run_id`, so only a document's current reading counts. Earlier
  versions and superseded readings never match.
- **When it is built.**
  - `ReceiptService.publish` indexes a reading as it is saved. A failure is logged and never fails the reading.
  - At library open, readings not yet indexed are indexed on the capture queue ("Indexing document text for
    search"). This also covers readings indexed under older passage rules (`INDEX_VERSION`).
  - `home-manager index-documents --rebuild` rebuilds the index with the app closed.
- **Removal.** Emptying Trash removes passages through their `parse_runs` foreign key. The Trash walk now lists
  ordinary tables only (`pragma_table_list`), so the FTS shadow tables are left to the triggers.
- **Query safety.** Typed words become quoted FTS phrases. All words must appear, and the last may be
  unfinished. Operators, quotes and colons are never passed through.

## Search

`LibraryStore.documents(query=…)` also matches readings whose passages contain the words. Each matched row
carries `match: {snippet, line_ids}` for its best passage. The snippet marks matched words with `\x02…\x03`,
which the browser turns into `<mark>` from text nodes. Global search and the Documents list show the snippet.
The link opens `#/documents/ID?lines=…`, which selects those lines in the extracted text.

## Assistant

- **Tools.**
  - `search_documents(query, document_type?, limit ≤ 8)` returns passages grouped by document.
  - `get_document_text(document_id, around_line?, lines ≤ 40)` returns the lines around a hit.
- **Routing.** Questions with document words (policy, coverage, deductible, lease, clause, warranty, vesting,
  "what does … say", …) take the `documents` route. That route offers the two tools plus accounts, recurring
  payments, bills and receipts. The finance and item routes also offer `search_documents`.
- **Citations.** An answer lists `cited_lines`. Only lines that a cited document call returned are kept, as
  `sources` (document, title, lines), and the answer shows them as links. Figures must still appear in the cited
  results, and passages count as results. `financial-assistant-v2`.

## Limits

- Keyword search does not find synonyms. "Excess" will not find "deductible".
- The index holds the text as read. A misread word can only be found as it was misread.
- Only readings in the library are indexed. CSV and Excel imports have no transcription.

## Verification

- `tests/test_text_index.py` covers:
  - passages, query safety, snippets and line IDs;
  - current reading only, backfill and reindexing, and Trash;
  - the upgrade from v41, the tools and routing;
  - cited-line filtering and the search API.
- `tests/test_document_search_browser.py` (opt-in `--browser`) searches, clicks through to the selected line,
  and checks page width at 390, 768 and 1440 px.
