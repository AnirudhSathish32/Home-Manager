"""Classify saved transcription without rereading or modifying preserved evidence."""

import json
import uuid

from .paths import path_key
from .storage import now
from .vision import VisionConfig, choose_folder


class OrganizationService:
    def __init__(self, store, source):
        self.store, self.source, self.progress = store, source, None

    def enqueue(self, document_id, digest, config):
        if not config.model:
            raise ValueError("Configure a local model in Settings first.")
        with self.store.connection() as db:
            doc = db.execute("SELECT * FROM occurrences WHERE id=? AND source_root=?", (document_id, path_key(self.source))).fetchone()
            if not doc or doc["deleted_at"]:
                raise ValueError("Document unavailable. Restore it from Trash first if necessary.")
            if doc["current_hash"] != digest:
                raise RuntimeError("Document changed. Refresh before organizing.")
            if db.execute("SELECT 1 FROM document_folders WHERE document_id=? AND blob_hash=?", (document_id, digest)).fetchone():
                raise ValueError("This version has a manually selected folder. Use Move to change it.")
            parsed = db.execute("SELECT id,result_json FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') AND length(coalesce(json_extract(result_json,'$.model_text'),json_extract(result_json,'$.ocr_text'),''))>0 ORDER BY created_at DESC LIMIT 1", (digest,)).fetchone()
            if not parsed:
                raise ValueError("Parse this document first; Organize uses saved text.")
            run_id = uuid.uuid4().hex
            db.execute("INSERT INTO organization_runs(id,document_id,blob_hash,parse_run_id,config_json,status,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?)", (run_id, document_id, digest, parsed["id"], config.model_dump_json(), now(), now()))
        return run_id

    def get(self, run_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM organization_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError("Organization run not found.")
        return dict(row)

    def run(self, run_id):
        try:
            run = self.get(run_id)
            with self.store.connection() as db:
                db.execute("UPDATE organization_runs SET status='running',updated_at=? WHERE id=?", (now(), run_id))
                result = json.loads(db.execute("SELECT result_json FROM parse_runs WHERE id=?", (run["parse_run_id"],)).fetchone()[0])
            folder = choose_folder(VisionConfig.model_validate_json(run["config_json"]), result.get("model_text") or result["ocr_text"],
                                   progress=lambda value: setattr(self, "progress", {"run_id": run_id, **value}))
            with self.store.connection() as db:
                doc = db.execute("SELECT current_hash,deleted_at FROM occurrences WHERE id=?", (run["document_id"],)).fetchone()
                if doc["current_hash"] != run["blob_hash"] or doc["deleted_at"]:
                    raise ValueError("Document changed during organization; folder was not applied.")
                db.execute("UPDATE organization_runs SET status='succeeded',result_folder=?,updated_at=? WHERE id=?", (folder, now(), run_id))
        except Exception as exc:
            message = str(exc) if type(exc) is ValueError else "Local organization failed. Check the model server log."
            with self.store.connection() as db:
                db.execute("UPDATE organization_runs SET status='failed',error=?,updated_at=? WHERE id=?", (message[:1200], now(), run_id))
        finally:
            self.progress = None

    def recover(self):
        with self.store.connection() as db:
            db.execute("UPDATE organization_runs SET status='interrupted',error='Organization interrupted; retry Organize.',updated_at=? WHERE status IN ('queued','running')", (now(),))
