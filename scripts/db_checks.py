"""Read-only integrity checks for a Home Manager library database.

Usage:  python scripts/db_checks.py "<path to inventory.sqlite3>"

Opens the file read-only, copies it into memory with SQLite's backup API (a consistent snapshot, including
the WAL), closes the file, and runs every check on the in-memory copy. Nothing is written anywhere.
Prints only counts, row ids and app-defined enum values: no names, amounts, descriptions or paths.
Findings it reports are explained in docs/development.md "Database checks".
"""
from pathlib import Path
import re
import sqlite3
import sys

path = Path(sys.argv[1]).resolve()
source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=15)
db = sqlite3.connect(":memory:")
source.backup(db)
source.close()
x = db.execute
SAFE = re.compile(r"^[a-z0-9_\-]{1,32}$")


def ids(rows, n=5):
    return [r[0] for r in rows[:n]]


print("user_version:", x("PRAGMA user_version").fetchone()[0])
print("integrity_check:", x("PRAGMA integrity_check").fetchone()[0])

fk = x("PRAGMA foreign_key_check").fetchall()
print(f"\n[foreign_key_check] violations: {len(fk)}")
by_table = {}
for table, rowid, parent, _ in fk:
    by_table.setdefault((table, parent), []).append(rowid)
for (table, parent), rows in sorted(by_table.items()):
    print(f"  {table} -> {parent}: {len(rows)} (rowids {rows[:5]})")

tables = [r[0] for r in x("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'document_passages_fts%'")]
print("\n[type drift] INTEGER-declared columns holding non-integer values")
found = False
for t in tables:
    for c in x(f'PRAGMA table_info("{t}")'):
        if c[2].upper() == "INTEGER":
            rows = x(f'SELECT rowid, typeof("{c[1]}") FROM "{t}" WHERE "{c[1]}" IS NOT NULL AND typeof("{c[1]}")<>\'integer\'').fetchall()
            if rows:
                found = True
                kinds = sorted({r[1] for r in rows})
                print(f"  {t}.{c[1]}: {len(rows)} rows, types {kinds}, rowids {ids(rows)}")
if not found:
    print("  none")

POLY = {"receipt": "receipts", "bill": "bills", "statement": "statements", "income_record": "income_records",
        "transaction": "transactions", "receipt_item": "receipt_items"}
print("\n[orphans] (record_type, record_id) rows whose record no longer exists")
for t in ("financial_evidence_links", "reconciliation_issues", "review_events", "record_corrections", "record_shares", "family_assignments"):
    for rtype, target in POLY.items():
        rows = x(f"SELECT rowid FROM {t} WHERE record_type=? AND record_id NOT IN (SELECT id FROM {target})", (rtype,)).fetchall()
        if rows:
            print(f"  {t} ({rtype}): {len(rows)} (rowids {ids(rows)})")
    if t == "review_events":  # An audit log over many record kinds (warranties, tax tags, assets…), not only these.
        continue
    unknown = x(f"SELECT count(*) FROM {t} WHERE record_type NOT IN ({','.join('?' * len(POLY))})", tuple(POLY)).fetchone()[0]
    if unknown:
        print(f"  {t}: {unknown} rows with an unknown record_type")

print("\n[enum values] columns with no CHECK constraint (value: count)")
ENUMS = ["jobs.status", "jobs.organization_status", "parse_runs.status", "reasoning_runs.status", "extraction_runs.status",
         "extraction_runs.document_type", "organization_runs.status", "managed_organization_intents.status",
         "managed_organization_intents.action", "managed_organization_events.action", "receipt_batches.status",
         "analysis_reviews.status", "occurrences.source_status", "occurrences.source_kind", "events.status",
         "library_events.action", "model_runs.status", "model_runs.metrics_source", "bills.bill_type",
         "recurring_obligations.obligation_type", "recurring_obligations.confidence_source", "reconciliation_issues.issue_type",
         "reconciliation_issues.record_type", "review_events.record_type", "review_events.previous_status", "review_events.new_status",
         "tax_rules.kind", "transaction_links.match_method", "transaction_receipt_links.match_method",
         "investment_events.transaction_previous_type", "accounts.active", "receipt_batch_items.reused"]
for spec in ENUMS:
    t, c = spec.split(".")
    values = x(f'SELECT "{c}", count(*) FROM "{t}" GROUP BY 1 ORDER BY 2 DESC').fetchall()
    shown = ", ".join(f"{v if v is None or SAFE.match(str(v)) else '<other>'}: {n}" for v, n in values)
    print(f"  {spec}: {shown or '(empty)'}")

print("\n[dates] values not in the expected format")
DAY = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$")
for t in tables:
    for c in x(f'PRAGMA table_info("{t}")'):
        name = c[1]
        if re.search(r"(_date|_on|^as_of|period_start|period_end|^tax_date)$", name):
            rows = x(f'SELECT rowid FROM "{t}" WHERE "{name}" IS NOT NULL AND ("{name}" NOT GLOB \'{DAY}\' OR date("{name}") IS NULL OR date("{name}")<>"{name}")').fetchall()
            if rows:
                print(f"  {t}.{name} (YYYY-MM-DD expected): {len(rows)} (rowids {ids(rows)})")
        elif re.search(r"(_at|^first_seen|^last_seen)$", name):
            bad = [r[0] for r in x(f'SELECT rowid, "{name}" FROM "{t}" WHERE "{name}" IS NOT NULL') if not STAMP.match(str(r[1]))]
            if bad:
                print(f"  {t}.{name} (ISO-8601 UTC expected): {len(bad)} (rowids {bad[:5]})")

print("\n[duplicates] rows the app treats as one")
for label, q in {
    "receipts per document version": "SELECT min(id) FROM receipts GROUP BY document_id, blob_hash HAVING count(*)>1",
    "open issues per record": "SELECT min(id) FROM reconciliation_issues WHERE status='open' GROUP BY record_type, record_id, issue_type HAVING count(*)>1",
    "verified receipt links per receipt": "SELECT receipt_id FROM transaction_receipt_links WHERE review_status='verified' GROUP BY receipt_id HAVING count(*)>1",
}.items():
    rows = x(q).fetchall()
    print(f"  {label}: {len(rows)}" + (f" (ids {ids(rows)})" if rows else ""))
print("\ndone")
