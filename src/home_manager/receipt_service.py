"""Trusted coordinator for durable receipt runs and a bounded local OCR child."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from pydantic import ValidationError

from .paths import safe_path
from .receipt_schema import PARSER_VERSION, ReceiptResult
from .storage import Store, digest_file, now
from .worker_limits import WorkerJob
from .vision import VisionConfig, VISION_VERSION, interpret_preview


class ReceiptService:
    def __init__(self, store: Store):
        self.store = store
        self.progress = None
        self.root = safe_path(store.root / "extracted")
        self.root.mkdir(exist_ok=True)

    def folder(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid parsing run ID.")
        return safe_path(self.root / run_id)

    def enqueue(self, document_id, digest=None, rotation=0, force=False, vision=None, organize=True):
        document, selected = self.store.document_version(document_id, digest)
        if document.get("deleted_at"):
            raise ValueError("Restore the document from Trash before parsing it.")
        if Path(document["relative_path"]).suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError("Receipt parsing currently supports PNG/JPEG images. CSV, Excel and PDF readers are planned separately.")
        if rotation not in (0, 90, 180, 270):
            raise ValueError("Rotation must be 0, 90, 180 or 270 degrees clockwise.")
        options_data = {"clockwise_rotation": rotation}
        parser = PARSER_VERSION
        if vision and vision.model:
            options_data["vision"] = vision.model_dump()
            options_data["organize"] = organize
            parser = VISION_VERSION
        options = json.dumps(options_data, sort_keys=True)
        with self.store.connection() as db:
            reusable = db.execute("SELECT id,status FROM parse_runs WHERE blob_hash=? AND parser_version=? AND options_json=? "
                                  "AND status IN ('queued','running','succeeded','partial') ORDER BY created_at DESC",
                                  (selected["hash"], parser, options)).fetchall()
            for row in reusable:
                if row["status"] in ("queued", "running") or not force:
                    return row["id"], False
            run_id = uuid.uuid4().hex
            db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at) VALUES(?,?,?,?,'queued',?,?)",
                       (run_id, selected["hash"], parser, options, now(), now()))
        return run_id, True

    def get(self, run_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM parse_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Parsing run not found.")
        result = dict(row)
        result["options"] = json.loads(result.pop("options_json"))
        payload = result.pop("result_json")
        result["result"] = json.loads(payload) if payload else None
        return result

    def history(self, document_id, digest=None):
        _, selected = self.store.document_version(document_id, digest)
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT id,blob_hash,parser_version,options_json,status,created_at,updated_at,error "
                                                  "FROM parse_runs WHERE blob_hash=? ORDER BY created_at DESC", (selected["hash"],))]

    def state(self, run_id, status, error=None):
        with self.store.connection() as db:
            db.execute("UPDATE parse_runs SET status=?,error=?,updated_at=? WHERE id=?", (status, error, now(), run_id))

    def publish(self, run_id):
        run = self.get(run_id)
        folder = self.folder(run_id)
        result_path, preview = safe_path(folder / "result.json"), safe_path(folder / "preview.png")
        if result_path.stat().st_size > 4 * 1024**2 or preview.stat().st_size > 64 * 1024**2:
            raise ValueError("Parser output exceeds the configured limits.")
        result = ReceiptResult.model_validate_json(result_path.read_bytes())
        if (result.input_hash != run["blob_hash"] or result.clockwise_rotation != run["options"]["clockwise_rotation"]
                or result.parser_version != run["parser_version"]):
            raise ValueError("Parser output does not match the requested evidence/version.")
        has_text = bool(result.model_text) if result.transcription_method == "vision_model" else bool(result.blocks)
        status = "partial" if not has_text or any(issue.code in ("low_confidence_text", "code_decode_error", "unreadable_text") for issue in result.issues) else "succeeded"
        with self.store.connection() as db:
            db.execute("UPDATE parse_runs SET status=?,result_json=?,preview_hash=?,updated_at=?,error=NULL WHERE id=?",
                       (status, result.model_dump_json(), digest_file(preview), now(), run_id))

    def run(self, run_id, timeout=180):
        process = job = None
        try:
            run = self.get(run_id)
            artifact_bytes = sum(safe_path(path).stat().st_size for path in self.root.glob("*/*") if path.is_file())
            if artifact_bytes > 2 * 1024**3 - 68 * 1024**2:
                raise ValueError("Receipt extraction storage limit reached (2 GiB). No new parsing run was started.")
            folder = self.folder(run_id)
            folder.mkdir(exist_ok=True)
            source = self.store.blob_path(run["blob_hash"])
            if digest_file(source) != run["blob_hash"]:
                raise ValueError("Preserved image failed its integrity check. No parsing was performed.")
            self.state(run_id, "running")
            # No API token, OAuth credentials or inherited proxy environment.
            env = {key: value for key, value in os.environ.items() if key.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "COMSPEC")}
            env.update({"TEMP": str(folder), "TMP": str(folder), "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2"})
            vision = run["options"].get("vision")
            process = subprocess.Popen([sys.executable, "-I", "-m", "home_manager.receipt_worker", str(source), str(folder), str(run["options"]["clockwise_rotation"]), "prepare" if vision else "ocr"],
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       cwd=folder, env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            job = WorkerJob(process)
            process.communicate(input=b"start\n", timeout=timeout)
            if process.returncode:
                error_file = safe_path(folder / "error.json")
                if error_file.exists() and error_file.stat().st_size < 8192:
                    raise ValueError(json.loads(error_file.read_text(encoding="utf-8"))["error"])
                raise ValueError("Receipt worker stopped before completion. Check dependencies and image size; retry or rotate the receipt.")
            if vision:
                job.close()
                job = None
                interpret_preview(folder, VisionConfig.model_validate(vision),
                                  progress=lambda value: setattr(self, "progress", {"run_id": run_id, **value}),
                                  organize=run["options"].get("organize", True))
            self.publish(run_id)
        except subprocess.TimeoutExpired:
            self.state(run_id, "failed", "Receipt parsing exceeded 180 seconds. Try an individual receipt or a smaller scan.")
        except Exception as exc:
            message = ("Parser/model output failed validation. No result was published." if isinstance(exc, ValidationError)
                       else str(exc) if isinstance(exc, ValueError)
                       else "Local receipt parsing failed. Check image integrity, available memory and disk access.")
            self.state(run_id, "failed", message[:1200])
        finally:
            self.progress = None
            if job:
                job.close()
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    def recover(self):
        with self.store.connection() as db:
            interrupted = [row[0] for row in db.execute("SELECT id FROM parse_runs WHERE status IN ('queued','running')")]
        for run_id in interrupted:
            try:
                # The completed worker result is the durable commit intent.
                self.publish(run_id)
            except Exception:
                self.state(run_id, "interrupted", "Parsing was interrupted. Previous completed runs remain available; select Parse receipt to retry.")

    def preview(self, run_id):
        run = self.get(run_id)
        if run["status"] not in ("succeeded", "partial"):
            raise ValueError("No completed image preview is available for this run.")
        path = safe_path(self.folder(run_id) / "preview.png")
        if digest_file(path) != run["preview_hash"]:
            raise ValueError("Receipt preview failed its integrity check.")
        return path
