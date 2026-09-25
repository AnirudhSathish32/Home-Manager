"""Trusted coordinator for durable receipt runs and a bounded image preparation child."""

import json
import os
import re
import subprocess
import sys
import uuid
from pydantic import ValidationError

from .formats import TEXT_READERS, extension
from .jobs import Cancelled, Work
from .model_client import resolve_identity
from .paths import safe_path
from .receipt_schema import ReceiptResult
from .pdf_reader import PDF_VERSION, PDFResult, complete_pdf
from .storage import Store, digest_file, now
from .worker_limits import WorkerJob
from .vision import VisionConfig, VISION_VERSION, transcribe_preview

UNRESOLVED = object()


class ReceiptService:
    def __init__(self, store: Store):
        self.store = store
        self.root = safe_path(store.root / "extracted")
        self.root.mkdir(exist_ok=True)

    def folder(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid parsing run ID.")
        return safe_path(self.root / run_id)

    def enqueue(self, document_id, digest=None, rotation=0, force=False, vision=None, identity=UNRESOLVED):
        """Reuse an in-flight run, or a completed one only for the same verified model identity."""
        document, selected = self.store.document_version(document_id, digest)
        if document.get("deleted_at"):
            raise ValueError("Restore the document from Trash before parsing it.")
        suffix = extension(document["relative_path"])
        if suffix not in TEXT_READERS:
            raise ValueError("Text extraction supports PNG, JPEG and PDF documents. CSV and Excel files use transaction import.")
        is_pdf = suffix == ".pdf"
        if rotation not in (0, 90, 180, 270):
            raise ValueError("Rotation must be 0, 90, 180 or 270 degrees clockwise.")
        vision = vision or VisionConfig()
        if not is_pdf and not vision.model:
            raise ValueError("Configure a local vision model in Settings before extracting text. OCR is no longer supported.")
        if identity is UNRESOLVED:
            identity = resolve_identity(self.store, vision) if vision.model else None
        parser = PDF_VERSION if is_pdf else VISION_VERSION
        options = json.dumps({"clockwise_rotation": rotation, "vision": vision.model_dump()}, sort_keys=True)
        with self.store.connection() as db:
            existing = db.execute("SELECT id,status,model_identity FROM parse_runs WHERE blob_hash=? AND parser_version=? AND options_json=? "
                                  "AND status IN ('queued','running','succeeded','partial') ORDER BY created_at DESC",
                                  (selected["hash"], parser, options)).fetchall()
            for row in existing:
                if row["status"] in ("queued", "running"):
                    return row["id"], False
                # No model configured (digital PDF) or the same identified weights; an
                # unidentifiable model never reuses a result merely because its ID matches.
                if not force and (row["model_identity"] == identity and (identity or not vision.model)):
                    return row["id"], False
            run_id = uuid.uuid4().hex
            db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at,model_identity) VALUES(?,?,?,?,'queued',?,?,?)",
                       (run_id, selected["hash"], parser, options, now(), now(), identity))
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
        result["model_runs"] = self.store.model_runs(run_id)
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
        if run["parser_version"] == PDF_VERSION:
            path = safe_path(folder / "result.json")
            if path.stat().st_size > 4 * 1024**2:
                raise ValueError("PDF evidence exceeds storage limits.")
            result = PDFResult.model_validate_json(path.read_bytes())
            if result.input_hash != run["blob_hash"]:
                raise ValueError("PDF evidence does not match preserved bytes.")
            payload = result.model_dump()
            payload["lines"] = [line.model_dump() for line in result.lines]
            with self.store.connection() as db:
                db.execute("UPDATE parse_runs SET status='succeeded',result_json=?,updated_at=?,error=NULL WHERE id=?", (json.dumps(payload), now(), run_id))
            return
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

    def run(self, run_id, work=None, timeout=180):
        work = work or Work.detached()
        process = job = None
        try:
            work.check()
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
            is_pdf = run["parser_version"] == PDF_VERSION
            if not is_pdf and (not vision or not vision.get("model")):
                raise ValueError("This legacy run cannot be executed. Create a new run with a configured vision model.")
            vision = VisionConfig.model_validate(vision or {})
            identity = None
            if vision.model:
                # Record the weights actually used, which may differ from those seen at enqueue.
                identity = resolve_identity(self.store, vision)
                with self.store.connection() as db:
                    db.execute("UPDATE parse_runs SET model_identity=? WHERE id=?", (identity, run_id))
            process = subprocess.Popen([sys.executable, "-I", "-m", "home_manager.pdf_reader" if is_pdf else "home_manager.receipt_worker", str(source), str(folder), str(run["options"]["clockwise_rotation"])],
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       cwd=folder, env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            job = WorkerJob(process)
            with work.on_cancel(process.kill):  # Terminates only this run's bounded child.
                process.communicate(input=b"start\n", timeout=timeout)
            work.check()
            if process.returncode:
                error_file = safe_path(folder / "error.json")
                if error_file.exists() and error_file.stat().st_size < 8192:
                    raise ValueError(json.loads(error_file.read_text(encoding="utf-8"))["error"])
                raise ValueError("Receipt worker stopped before completion. Check dependencies and image size; retry or rotate the receipt.")
            job.close()
            job = None
            with work.attribute("transcription", run_id, run["parser_version"], identity):
                if is_pdf:
                    complete_pdf(folder, vision, run["blob_hash"], work)
                else:
                    transcribe_preview(folder, vision, work)
            work.check()  # A cancellation request always wins over late publication.
            self.publish(run_id)
        except Cancelled as exc:
            self.state(run_id, "cancelled", str(exc))
        except subprocess.TimeoutExpired:
            self.state(run_id, "failed", "Receipt parsing exceeded 180 seconds. Try an individual receipt or a smaller scan.")
        except Exception as exc:
            message = ("Parser/model output failed validation. No result was published." if isinstance(exc, ValidationError)
                       else str(exc) if isinstance(exc, ValueError)
                       else "Local receipt parsing failed. Check image integrity, available memory and disk access.")
            self.state(run_id, "failed", message[:1200])
        finally:
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
