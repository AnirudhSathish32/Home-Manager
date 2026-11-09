"""What Record made of the latest bank and card statements in a library database, without printing their contents.

Usage:  python scripts/statement_records.py "<path to inventory.sqlite3>"

Opens the file read-only, copies it into memory with SQLite's backup API, closes the file, then prints for the latest
statement readings: the reading's version and type, how many rows the model listed, how many were recorded and how many of
those came from the printed columns, and what publishing did (published or kept as reviewed, with the kept and new type and
row counts). For the latest statements: type, review status, the account's type and whether it waits for Confirm, the rows on
the statement and in the account, the account's import records, and where the document is filed (folder, in the trash,
grouped under another, ledger status). Last, each reading's issues and notes as patterns with counts.

Prints only counts, row ids, app enum values and code versions. Messages are printed with quotes, dates and amounts replaced by
"…", and a row's own text (after "on page N:", or a description in brackets) cut, so no merchant, amount, date or account number
should appear; read them before pasting anyway.
Never run it against a live library yourself; the user runs it and pastes the output (docs/development.md "Database checks").
"""
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from home_manager.finance.ledger import confirmed  # noqa: E402
from home_manager.library.storage import Store  # noqa: E402

READINGS, STATEMENTS = 6, 6
DATE = re.compile(r"\b\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?\b")
AMOUNT = re.compile(r"[-+(]?[$€£]?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?")
CUT = re.compile(r"^(.*?\bon page \d+): .*$")  # "…, on page 3: <the row's own date, text and amount>"


def pattern(message):
    """A message as a pattern: the document's quotes, dates and amounts become "…", page and row numbers "#", and a row's own
    text (after "on page N:", or a transaction's description in brackets) goes."""
    text = re.sub(r'"[^"]*"', '"…"', str(message))
    text = DATE.sub("…", AMOUNT.sub("…", text))
    cut = CUT.match(text)
    if cut:
        text = cut.group(1) + ": …"
    text = re.sub(r"\b(Transaction \d+) \([^)]*\)", r"\1 (…)", text)  # A row's description.
    text = re.sub(r"\b(page|pages|row|rows|Page|Row) [\d, ]+", lambda m: m.group(1) + " # ", text)
    text = re.sub(r"\b\d{3,}\b", "…", text)
    return " ".join(text.split())[:160]


path = Path(sys.argv[1]).resolve()
source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=15)
db = sqlite3.connect(":memory:")
source.backup(db)
source.close()
x = db.execute
print("user_version:", x("PRAGMA user_version").fetchone()[0])

print(f"\n[latest {READINGS} statement readings]")
patterns = []
for _run, document, version, status, kind, result, publication, error in x(
        "SELECT id,document_id,prompt_version,status,document_type,result_json,publication_json,error FROM extraction_runs "
        "WHERE document_type IN ('bank_statement','credit_card_statement') ORDER BY created_at DESC LIMIT ?", (READINGS,)).fetchall():
    result, publication = json.loads(result or "{}"), json.loads(publication or "{}") or {}
    record = result.get("normalized") or {}
    rows = record.get("transactions") or []
    pages = Counter((row.get("locator") or {}).get("page") for row in rows)
    print(f"  document {document}: {version} {status} {kind}; model rows {len(result.get('rows') or [])}; recorded rows {len(rows)} "
          f"(from printed columns {sum(1 for row in rows if (row.get('locator') or {}).get('rebuilt'))}; by page {dict(sorted(pages.items(), key=str))}); "
          f"issues {len(record.get('issues') or [])}, notes {len(record.get('notes') or [])}; error {bool(error)}")
    print(f"    publish: {publication.get('status')} {publication.get('review_status')} statement {publication.get('id')} "
          f"account {publication.get('account_id')} confirmed {publication.get('account_confirmed')}; "
          + (f"kept as {publication.get('kept')}; this reading {publication.get('reading')}" if publication.get("status") == "kept_reviewed"
             else f"rows inserted {publication.get('inserted')}, already there {publication.get('duplicates')}, kept for you {publication.get('kept')}"))
    for name in ("issues", "notes"):
        patterns += [(document, name, pattern(message)) for message in record.get(name) or []]

print(f"\n[latest {STATEMENTS} statements]")
documents = []
for row in x(f"SELECT s.id,s.document_id,s.statement_type,s.review_status,s.review_source,a.id,a.account_type,a.active,{confirmed('a')},"
             "(SELECT count(*) FROM transactions t WHERE t.statement_id=s.id),"
             "(SELECT count(*) FROM transactions t WHERE t.statement_id=s.id AND t.origin='import'),"
             "(SELECT count(*) FROM transactions t WHERE t.account_id=a.id),"
             "(SELECT count(*) FROM transactions t WHERE t.account_id=a.id AND t.statement_id IS NULL),"
             "(SELECT count(*) FROM transaction_imports i WHERE i.account_id=a.id),"
             "(SELECT count(*) FROM transaction_imports i WHERE i.account_id=a.id AND i.blob_hash=s.blob_hash) "
             "FROM statements s JOIN accounts a ON a.id=s.account_id ORDER BY s.id DESC LIMIT ?", (STATEMENTS,)).fetchall():
    documents.append(row[1])
    print(f"  statement {row[0]} (document {row[1]}): {row[2]} {row[3]} by {row[4]}; account {row[5]} {row[6]} active {row[7]} confirmed {bool(row[8])}; "
          f"rows on statement {row[9]} (imported {row[10]}); rows in account {row[11]} (on no statement {row[12]}); "
          f"imports into account {row[13]} (of this file {row[14]})")

print("\n[accounts]")
for row in x(f"SELECT a.id,a.account_type,a.active,{confirmed('a')},(SELECT count(*) FROM statements s WHERE s.account_id=a.id),"
             "(SELECT count(*) FROM transactions t WHERE t.account_id=a.id) FROM accounts a ORDER BY a.id").fetchall():
    print(f"  account {row[0]}: {row[1]} active {row[2]} confirmed {bool(row[3])}; statements {row[4]}, rows {row[5]}")

print("\n[where the documents are]")
if documents:
    for row in x(Store.library_query(None) + "SELECT id,folder,deleted_at IS NOT NULL,grouped_under IS NOT NULL,ledger_status,extraction_status "
                 f"FROM library WHERE id IN ({','.join('?' * len(documents))}) ORDER BY id", documents).fetchall():
        print(f"  document {row[0]}: folder {row[1]}; in trash {bool(row[2])}; grouped under another {bool(row[3])}; ledger {row[4]}; reading {row[5]}")

print("\n[issues and notes, as patterns]")
for (document, name, text), count in Counter(patterns).items():
    print(f"  document {document} {name} x{count}: {text}")
