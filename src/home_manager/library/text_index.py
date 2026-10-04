"""Full-text index over saved transcriptions (docs/documents.md "Searching document text"): SQLite FTS5, no model involved.

A reading's lines are cut into short overlapping passages that never cross a PDF page. Each passage keeps its
line IDs, so a hit opens the transcription at the right place and an answer can cite it. The index is rebuilt
from parse_runs at any time; it is never the only copy of anything.
"""

import json
import logging
import re

from ..core.logs import log_failure

log = logging.getLogger(__name__)

# Bump when the passage rules change: every reading is indexed again at the next start.
INDEX_VERSION = 1
PASSAGE_LINES, OVERLAP = 8, 2
MAX_WORDS = 12
# The readings a library row shows as its text (storage.py text_run_id): finished, and not the retired OCR parser.
INDEXABLE = "p.status IN ('succeeded','partial') AND p.parser_version<>'receipt-ocr-v1'"
PAGE = re.compile(r"^page-(\d+)-")
# Snippet markers, turned into highlighting by the browser. Control characters never occur in transcriptions.
MARK_START, MARK_END = "\x02", "\x03"
# The type the latest ledger extraction gave this reading, or NULL.
DOCUMENT_TYPE = ("(SELECT e.document_type FROM extraction_runs e WHERE e.document_id=l.id AND e.parse_run_id=l.text_run_id "
                 "AND e.document_type IS NOT NULL ORDER BY e.created_at DESC LIMIT 1)")


def passages(lines):
    """[(line_ids, text)] from transcription lines: PASSAGE_LINES non-blank lines each, overlapping by OVERLAP."""
    pages = {}
    for line in lines:
        text = " ".join(str(line.get("text") or "").split())
        if text:
            page = PAGE.match(str(line.get("id") or ""))
            pages.setdefault(page.group(1) if page else None, []).append((str(line["id"]), text))
    result = []
    for page in pages.values():
        start = 0
        while True:
            window = page[start:start + PASSAGE_LINES]
            result.append(([line_id for line_id, _ in window], "\n".join(text for _, text in window)))
            if start + PASSAGE_LINES >= len(page):
                break
            start += PASSAGE_LINES - OVERLAP
    return result


def match_expression(text):
    """A safe FTS5 query: each typed word is a quoted phrase (a word split by punctuation, like 1,000 or 401(k),
    stays one phrase), all of them must appear, and the last one may be unfinished. Never FTS syntax; None if empty."""
    phrases = []
    for word in (text or "").split():
        parts = re.findall(r"\w+", word)
        if parts:
            phrases.append('"' + " ".join(parts) + '"')
    if not phrases:
        return None
    phrases = phrases[:MAX_WORDS]
    phrases[-1] += "*"
    return " ".join(phrases)


def index_run(db, run_id):
    """Replace one reading's passages. A reading that is not (or no longer) indexable ends with none."""
    row = db.execute(f"SELECT p.result_json FROM parse_runs p WHERE p.id=? AND {INDEXABLE}", (run_id,)).fetchone()
    db.execute("DELETE FROM document_passages WHERE parse_run_id=?", (run_id,))
    if row is None:
        db.execute("DELETE FROM document_index_state WHERE parse_run_id=?", (run_id,))
        return 0
    lines = (json.loads(row["result_json"]) if row["result_json"] else {}).get("lines") or []
    found = passages(lines)
    db.executemany("INSERT INTO document_passages(parse_run_id,ordinal,line_ids,text) VALUES(?,?,?,?)",
                   [(run_id, ordinal, json.dumps(line_ids), text) for ordinal, (line_ids, text) in enumerate(found, 1)])
    from .storage import now
    db.execute("INSERT INTO document_index_state(parse_run_id,index_version,passages,indexed_at) VALUES(?,?,?,?) "
               "ON CONFLICT(parse_run_id) DO UPDATE SET index_version=excluded.index_version,passages=excluded.passages,indexed_at=excluded.indexed_at",
               (run_id, INDEX_VERSION, len(found), now()))
    return len(found)


def index_quietly(store, run_id):
    """Index a reading just saved. A failure is logged and left to the next start's backfill; it never fails the reading."""
    try:
        with store.connection() as db:
            index_run(db, run_id)
    except Exception as exc:
        log_failure(log, "document text index", exc, run=run_id)


def pending(db):
    return [row[0] for row in db.execute(f"SELECT p.id FROM parse_runs p LEFT JOIN document_index_state s ON s.parse_run_id=p.id "
                                         f"WHERE {INDEXABLE} AND (s.parse_run_id IS NULL OR s.index_version<>?) ORDER BY p.created_at",
                                         (INDEX_VERSION,))]


def backfill(store, work=None, rebuild=False):
    """Index every reading not yet indexed with the current rules; with rebuild, all of them. Returns how many."""
    if rebuild:
        with store.connection() as db:
            db.execute("DELETE FROM document_passages")
            db.execute("DELETE FROM document_index_state")
    with store.connection() as db:
        waiting = pending(db)
    for run_id in waiting:
        if work is not None:
            work.check()
        with store.connection() as db:
            index_run(db, run_id)
    if waiting:
        log.info("document text indexed readings=%s", len(waiting))
    return len(waiting)


def matching_runs(expression):
    """SQL (one parameter: the expression) for the readings with a passage that matches."""
    return ("SELECT p.parse_run_id FROM document_passages_fts f JOIN document_passages p ON p.id=f.rowid "
            "WHERE document_passages_fts MATCH ?", [expression])


def best_matches(db, expression, run_ids):
    """{run_id: {"snippet", "line_ids"}}: each reading's best passage for the expression."""
    run_ids = sorted({run_id for run_id in run_ids if run_id})
    if not run_ids:
        return {}
    rows = db.execute("SELECT p.parse_run_id,p.line_ids,snippet(document_passages_fts,0,?,?,'…',16) AS snippet FROM document_passages_fts "
                      "JOIN document_passages p ON p.id=document_passages_fts.rowid WHERE document_passages_fts MATCH ? "
                      f"AND p.parse_run_id IN ({','.join('?' * len(run_ids))}) ORDER BY bm25(document_passages_fts)",
                      [MARK_START, MARK_END, expression, *run_ids])
    found = {}
    for row in rows:
        found.setdefault(row["parse_run_id"], {"snippet": row["snippet"], "line_ids": json.loads(row["line_ids"])})
    return found


def search(store, text, document_type=None, limit=8):
    """Passages matching the words, best first, grouped by document: what the assistant reads. Current versions
    of documents outside Trash only."""
    expression = match_expression(text)
    if expression is None:
        raise ValueError("Give words to look for in the documents.")
    with store.connection() as db:
        rows = db.execute(store.library_query() + f"SELECT * FROM (SELECT l.id AS document_id,l.title,l.relative_path,l.document_date,"
                          f"{DOCUMENT_TYPE} AS document_type,p.id AS passage_id,p.line_ids,p.text,bm25(document_passages_fts) AS rank "
                          "FROM document_passages_fts JOIN document_passages p ON p.id=document_passages_fts.rowid "
                          "JOIN library l ON l.text_run_id=p.parse_run_id WHERE document_passages_fts MATCH ? AND l.deleted_at IS NULL) "
                          "WHERE ? IS NULL OR document_type=? ORDER BY rank LIMIT ?",
                          (expression, document_type, document_type, limit * 3)).fetchall()
    documents, seen, count = {}, set(), 0
    for row in rows:
        # Duplicate documents share one reading: its passages are shown once, under the first document.
        if row["passage_id"] in seen or count >= limit:
            continue
        seen.add(row["passage_id"])
        count += 1
        document = documents.setdefault(row["document_id"], {
            "document_id": row["document_id"], "title": row["title"] or row["relative_path"].replace("\\", "/").rsplit("/", 1)[-1],
            "document_type": row["document_type"], "document_date": row["document_date"], "passages": []})
        document["passages"].append({"line_ids": json.loads(row["line_ids"]), "text": row["text"]})
    return {"query": text, "documents": list(documents.values()),
            "notes": ["Passages are the document's own words as read from the page. Words that are not found here may still be printed "
                      "in a part the reading missed."]}


def document_lines(store, document_id, around_line=None, count=40):
    """Up to count lines of a document's current reading, centred on around_line (or from the start)."""
    document = store.document(document_id)
    if document.get("deleted_at"):
        raise ValueError("That document is in Trash.")
    if not document.get("text_run_id"):
        raise ValueError("That document has no saved text yet.")
    with store.connection() as db:
        row = db.execute("SELECT result_json FROM parse_runs WHERE id=?", (document["text_run_id"],)).fetchone()
    lines = [line for line in (json.loads(row["result_json"]).get("lines") or []) if str(line.get("text") or "").strip()]
    start = 0
    if around_line is not None:
        index = next((i for i, line in enumerate(lines) if line.get("id") == around_line), None)
        if index is None:
            raise ValueError("That line is not in the document. Use a line ID from search_documents.")
        start = max(0, index - count // 2)
    window = lines[start:start + count]
    return {"document_id": document_id, "title": document.get("title") or document["relative_path"].replace("\\", "/").rsplit("/", 1)[-1],
            "total_lines": len(lines), "lines": [{"line_id": line["id"], "text": line["text"]} for line in window]}
