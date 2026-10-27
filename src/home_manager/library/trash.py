"""Permanent document deletion, with shared evidence retained and durable file cleanup."""

from pathlib import PurePosixPath

from ..core.paths import safe_path
from .storage import digest_file

RECORDS = {"statements": "statement", "transactions": "transaction", "receipts": "receipt",
           "receipt_items": "receipt_item", "income_records": "income_record",
           "transaction_receipt_links": "receipt_link", "transaction_links": "transaction_link",
           "reconciliation_issues": "reconciliation_issue"}


def cleanup(store):
    """Only remove explicitly queued paths inside app-owned directories. Safe to retry."""
    with store.connection() as db:
        paths = db.execute("SELECT * FROM trash_cleanup").fetchall()
    failures = 0
    for row in paths:
        try:
            parts = PurePosixPath(row["relative_path"]).parts
            if len(parts) < 2 or parts[0] not in ("Library", "originals", "extracted") or any(p in ("..", ".") for p in parts):
                raise ValueError("Invalid trash cleanup path.")
            target = safe_path(store.root.joinpath(*parts))
            target.relative_to(store.root)
            # A later scan may have captured the same bytes again after a failed
            # unlink. An old cleanup request must never delete newly referenced data.
            with store.connection() as db:
                if parts[0] == "Library":
                    live = db.execute("SELECT 1 FROM managed_files WHERE relative_path=?", ("/".join(parts[1:]),)).fetchone()
                elif parts[0] == "originals":
                    live = db.execute("SELECT 1 FROM blobs WHERE hash=?", (target.stem,)).fetchone()
                else:
                    live = db.execute("SELECT 1 FROM parse_runs WHERE id=?", (parts[1],)).fetchone()
                if live:
                    db.execute("DELETE FROM trash_cleanup WHERE relative_path=?", (row["relative_path"],))
                    continue
            if row["is_directory"] and target.exists():
                # Validate every descendant before deleting any; do not follow reparse points.
                children = [safe_path(child) for child in target.rglob("*")]
                for child in sorted(children, key=lambda p: len(p.parts), reverse=True):
                    child.relative_to(target)
                    child.rmdir() if child.is_dir() else child.unlink(missing_ok=True)
                target.rmdir()
            elif not row["is_directory"]:
                target.unlink(missing_ok=True)
            with store.connection() as db:
                db.execute("DELETE FROM trash_cleanup WHERE relative_path=?", (row["relative_path"],))
        except (OSError, ValueError):
            failures += 1
    return failures


def empty(store, scope=None):
    """Caller holds the manager mutex with background work idle and the library lock. With a scope (money or documents),
    only that section's Trash: the trashed documents in its folders, with the later pages grouped under them."""
    if cleanup(store):
        raise ValueError("Previous trash cleanup could not finish. Close files open in other programs and try again.")
    scoped, scope_params = store.scope_clause(scope)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        ids = {row[0] for row in db.execute(store.library_query() + "SELECT id FROM library WHERE deleted_at IS NOT NULL AND "
                                            f"coalesce(grouped_under,id) IN (SELECT id FROM library WHERE grouped_under IS NULL{scoped})",
                                            scope_params)}
        if not ids:
            return {"deleted": 0, "cleanup_pending": 0}
        # Ordinary tables only: the full-text index (a virtual table and its shadow tables) follows document_passages by trigger.
        tables = [row[0] for row in db.execute("SELECT name FROM pragma_table_list WHERE schema='main' AND type='table' AND name NOT LIKE 'sqlite_%'")]
        rows = {table: {row["_rowid"]: dict(row) for row in db.execute(f'SELECT rowid AS _rowid,* FROM "{table}"')} for table in tables}
        doomed = {table: set() for table in tables}
        doomed["occurrences"] = ids
        hashes = {row["hash"] for row in rows["versions"].values() if row["occurrence_id"] in ids}
        retained = {row["hash"] for row in rows["versions"].values() if row["occurrence_id"] not in ids}
        doomed["blobs"] = {key for key, row in rows["blobs"].items() if row["hash"] in hashes - retained}

        # Canonical records can be shared by duplicate documents/imports. Transfer their
        # ownership to surviving evidence before following foreign-key dependencies.
        for table in ("statements", "transactions", "receipts", "income_records"):
            column = "source_document_id" if table == "transactions" else "document_id"
            for key, row in rows[table].items():
                if row[column] not in ids:
                    continue
                candidates = [link["document_id"] for link in rows["financial_evidence_links"].values()
                              if link["record_type"] == RECORDS[table] and link["record_id"] == row["id"] and link["document_id"] not in ids]
                if table != "transactions":
                    candidates += [v["occurrence_id"] for v in rows["versions"].values()
                                   if v["hash"] == row["blob_hash"] and v["occurrence_id"] not in ids]
                else:
                    evidence_hashes = {link["blob_hash"] for link in rows["financial_evidence_links"].values()
                                       if link["record_type"] == "transaction" and link["record_id"] == row["id"]}
                    candidates += [v["occurrence_id"] for v in rows["versions"].values()
                                   if v["hash"] in evidence_hashes and v["occurrence_id"] not in ids]
                if candidates:
                    row[column] = min(candidates)
                    db.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (row[column], key))

        for table in ("financial_evidence_links", "extraction_runs"):
            for key, row in rows[table].items():
                if row["document_id"] not in ids:
                    continue
                digest = row.get("blob_hash")
                if table == "extraction_runs":
                    digest = next(p["blob_hash"] for p in rows["parse_runs"].values() if p["id"] == row["parse_run_id"])
                candidates = [v["occurrence_id"] for v in rows["versions"].values() if v["hash"] == digest and v["occurrence_id"] not in ids]
                if candidates:
                    row["document_id"] = min(candidates)
                    db.execute(f'UPDATE "{table}" SET document_id=? WHERE rowid=?', (row["document_id"], key))

        # A statement groups transactions, but is not necessarily their only source.
        # Ownership and duplicate evidence have already been transferred above.
        independent_transactions = {
            key for key, row in rows["transactions"].items()
            if row["source_document_id"] is not None and row["source_document_id"] not in ids
            or any(link["record_type"] == "transaction" and link["record_id"] == row["id"]
                   and link["document_id"] not in ids for link in rows["financial_evidence_links"].values())
        }
        foreign = {table: list(db.execute(f'PRAGMA foreign_key_list("{table}")')) for table in tables}
        changed = True
        while changed:
            changed = False
            for table in tables:
                for fk in foreign[table]:
                    # A recurring bill outlives the receipt or document it was proposed from; only the link is cleared below.
                    if table == "recurring_obligations" and fk["from"] in ("source_receipt_id", "source_document_id"):
                        continue
                    targets = {rows[fk["table"]][key][fk["to"]] for key in doomed[fk["table"]]}
                    additions = {key for key, row in rows[table].items() if row[fk["from"]] in targets} - doomed[table]
                    if table == "transactions" and fk["from"] == "statement_id":
                        additions -= independent_transactions
                    if additions:
                        doomed[table].update(additions)
                        changed = True
            # These provenance and family tables use typed IDs rather than SQL foreign keys. Ids are reused once
            # deleted, so a row left behind here would attach itself to the next record that gets the same id.
            for table, kind in RECORDS.items():
                targets = {rows[table][key]["id"] for key in doomed[table]}
                for dependent in ("financial_evidence_links", "review_events", "record_corrections", "reconciliation_issues",
                                  "record_shares", "family_assignments"):
                    if dependent == "record_corrections" and kind == "receipt_item":
                        continue  # Item price corrections are keyed by receipt, not the replaceable item id.
                    additions = {key for key, row in rows[dependent].items()
                                 if (row["record_type"] == kind or dependent == "record_corrections" and kind == "receipt" and row["record_type"] == "receipt_item")
                                 and row["record_id"] in targets} - doomed[dependent]
                    if additions:
                        doomed[dependent].update(additions)
                        changed = True

        removed_statements = {rows["statements"][key]["id"] for key in doomed["statements"]}
        for key, row in rows["transactions"].items():
            if key not in doomed["transactions"] and row["statement_id"] in removed_statements:
                db.execute("UPDATE transactions SET statement_id=NULL WHERE rowid=?", (key,))

        removed_receipts = {rows["receipts"][key]["id"] for key in doomed["receipts"]}
        for row in rows["recurring_obligations"].values():
            receipt = None if row["source_receipt_id"] in removed_receipts else row["source_receipt_id"]
            document = None if row["source_document_id"] in ids else row["source_document_id"]
            if (receipt, document) != (row["source_receipt_id"], row["source_document_id"]):
                db.execute("UPDATE recurring_obligations SET source_receipt_id=?,source_document_id=? WHERE id=?", (receipt, document, row["id"]))
        owners = {rows[table][key]["id"] for table in ("parse_runs", "reasoning_runs", "extraction_runs", "organization_runs") for key in doomed[table]}
        doomed["model_runs"] = {key for key, row in rows["model_runs"].items() if row["owner_id"] in owners}

        paths = []
        for key in doomed["managed_files"]:
            row = rows["managed_files"][key]
            path = store.library.path(row["relative_path"])
            if path.exists() and digest_file(path) != row["blob_hash"]:
                raise ValueError("A managed file was edited after capture. Preserve the edit before emptying Trash.")
            paths.append((path.relative_to(store.root).as_posix(), 0))
        for key in doomed["blobs"]:
            paths.append((store.blob_path(rows["blobs"][key]["hash"]).relative_to(store.root).as_posix(), 0))
        for key in doomed["parse_runs"]:
            paths.append((f'extracted/{rows["parse_runs"][key]["id"]}', 1))
        db.executemany("INSERT OR IGNORE INTO trash_cleanup VALUES(?,?)", paths)
        # All dependencies are included; defer checks until the complete graph is removed.
        db.execute("PRAGMA defer_foreign_keys=ON")
        for table, keys in doomed.items():
            db.executemany(f'DELETE FROM "{table}" WHERE rowid=?', [(key,) for key in keys])
    return {"deleted": len(ids), "cleanup_pending": cleanup(store)}
