"""File from saved, evidence-linked classification; retain legacy run history."""

import json

from .storage import now


class OrganizationService:
    def __init__(self, store):
        self.store = store

    def enqueue(self, document_id, digest):
        document, _ = self.store.document_version(document_id, digest)
        if document["current_hash"] != digest:
            raise RuntimeError("Document version changed. Refresh before organizing.")
        with self.store.connection() as db:
            row = db.execute("SELECT r.* FROM reasoning_runs r JOIN parse_runs p ON p.id=r.parse_run_id WHERE p.blob_hash=? AND r.status='succeeded' ORDER BY r.created_at DESC LIMIT 1", (digest,)).fetchone()
        if not row:
            raise ValueError("Analyze the transcription with a reasoning model first, or use Move to choose a folder manually.")
        run = dict(row)
        run["result"] = json.loads(run["result_json"])
        intent = self.store.library.file_analysis(document_id, run)
        if not intent:
            raise ValueError("The document has a manual folder choice or an existing evidence-backed filing. Use Move to change it.")
        return intent

    def get(self, run_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM managed_organization_intents WHERE id=?", (run_id,)).fetchone()
            if row is None:
                row = db.execute("SELECT * FROM organization_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError("Organization run not found.")
        return dict(row)

    def recover(self):
        with self.store.connection() as db:
            db.execute("UPDATE organization_runs SET status='interrupted',error='Organization interrupted. Use Move; automatic classification awaits a reasoning model.',updated_at=? WHERE status IN ('queued','running')", (now(),))
