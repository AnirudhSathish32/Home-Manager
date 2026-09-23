"""Persistent batches over a snapshot of all current preserved image versions."""

from pathlib import Path
import uuid

from .paths import path_key
from .storage import now


class ReceiptBatches:
    def __init__(self, store, receipts):
        self.store, self.receipts = store, receipts

    def recover(self):
        with self.store.connection() as db:
            db.execute("UPDATE receipt_batches SET status='interrupted' WHERE status IN ('queued','running')")

    def enqueue(self, source, vision, force=False, scan_job=None):
        if not vision.model:
            raise ValueError("Save a local vision model ID before parsing all receipts.")
        with self.store.connection() as db:
            query = "SELECT o.id,o.current_hash,o.relative_path FROM occurrences o WHERE o.source_root=? AND o.deleted_at IS NULL"
            params = [path_key(source)]
            if scan_job:
                query += " AND EXISTS(SELECT 1 FROM events e WHERE e.job_id=? AND e.relative_path=o.relative_path AND e.hash=o.current_hash AND e.status IN ('captured','duplicate','new_version'))"
                params.append(scan_job)
            documents = list(db.execute(query + " ORDER BY o.id", params))
        images = [doc for doc in documents if Path(doc["relative_path"]).suffix.lower() in (".png", ".jpg", ".jpeg")]
        if not images:
            if scan_job:
                return None
            raise ValueError("No preserved PNG/JPEG documents are available. Scan the source folder first.")
        batch = uuid.uuid4().hex
        with self.store.connection() as db:
            db.execute("INSERT INTO receipt_batches VALUES(?,?,'queued',?,?)", (batch, path_key(source), now(), len(documents)-len(images)))
        try:
            for document in images:
                run_id, created = self.receipts.enqueue(document["id"], document["current_hash"], force=force, vision=vision)
                with self.store.connection() as db:
                    db.execute("INSERT INTO receipt_batch_items VALUES(?,?,?,?)", (batch, document["id"], run_id, int(not created)))
        except Exception:
            self.state(batch, "interrupted")
            self.receipts.recover()
            raise
        return batch

    def state(self, batch, state):
        with self.store.connection() as db:
            db.execute("UPDATE receipt_batches SET status=? WHERE id=?", (state, batch))

    def run(self, batch):
        self.state(batch, "running")
        try:
            with self.store.connection() as db:
                runs = [row[0] for row in db.execute("SELECT DISTINCT run_id FROM receipt_batch_items WHERE batch_id=?", (batch,))]
            for run_id in runs:
                if self.receipts.get(run_id)["status"] == "queued":
                    self.receipts.run(run_id)
            counts = self.get(batch)["counts"]
            self.state(batch, "partial" if any(counts.get(key, 0) for key in ("failed", "interrupted", "partial")) else "completed")
        except Exception:
            self.receipts.recover()
            self.state(batch, "interrupted")

    def get(self, batch):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM receipt_batches WHERE id=?", (batch,)).fetchone()
            if row is None:
                raise ValueError("Batch not found.")
            value = dict(row)
            value["counts"] = {row[0]: row[1] for row in db.execute(
                "SELECT p.status,count(*) FROM receipt_batch_items i JOIN parse_runs p ON p.id=i.run_id WHERE i.batch_id=? GROUP BY p.status", (batch,))}
            value["total"] = sum(value["counts"].values())
            value["reused"] = db.execute("SELECT coalesce(sum(reused),0) FROM receipt_batch_items WHERE batch_id=?", (batch,)).fetchone()[0]
            value["unique_runs"] = db.execute("SELECT count(DISTINCT run_id) FROM receipt_batch_items WHERE batch_id=?", (batch,)).fetchone()[0]
            return value

    def latest(self, source):
        with self.store.connection() as db:
            row = db.execute("SELECT id FROM receipt_batches WHERE source_root=? ORDER BY created_at DESC LIMIT 1", (path_key(source),)).fetchone()
        return self.get(row[0]) if row else None
