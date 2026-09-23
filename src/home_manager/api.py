"""Loopback-only API and minimal manual-testing UI."""

from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .manager import Manager, default_control_dir
from .scanner import ScanLimits
from .vision import VisionConfig
from .folders import DocumentFolder


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_directory: str = Field(min_length=1, max_length=4096)
    managed_directory: str = Field(min_length=1, max_length=4096)


class ScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    year: int | None = Field(default=None, ge=1000, le=9999)
    month: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def scope(self):
        if self.month is not None and self.year is None:
            raise ValueError("A month scope also requires a year.")
        return self


class ReceiptInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    blob_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    clockwise_rotation: Literal[0, 90, 180, 270] = 0
    force: bool = False
    organize: bool = True


class BatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    force: bool = False


class LibraryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class MoveInput(LibraryInput):
    folder: DocumentFolder


class DeleteInput(LibraryInput):
    confirmed: bool = Field(strict=True)

    @model_validator(mode="after")
    def confirmation(self):
        if self.confirmed is not True:
            raise ValueError("Explicit confirmation is required to move a document to Trash.")
        return self


def create_app(control: Path | None = None, token: str | None = None,
               port: int = 8765, limits: ScanLimits | None = None) -> FastAPI:
    session_token = token or secrets.token_urlsafe(32)
    origin = f"http://127.0.0.1:{port}"

    @asynccontextmanager
    async def lifespan(app):
        app.state.manager = Manager(control or default_control_dir(), limits)
        try:
            yield
        finally:
            app.state.manager.close()

    app = FastAPI(title="Home Manager document capture", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        if request.headers.get("host") != f"127.0.0.1:{port}":
            return JSONResponse({"detail": "Use the loopback URL printed by the launcher."}, status_code=403)
        if request.headers.get("origin") not in (None, origin):
            return JSONResponse({"detail": "Cross-origin requests are not allowed."}, status_code=403)
        if request.method not in ("GET", "HEAD"):
            try:
                if int(request.headers.get("content-length", "0")) > 16384:
                    return JSONResponse({"detail": "Request too large."}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid content length."}, status_code=400)
            # These endpoints accept tiny settings, never uploaded document bytes.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({"detail": "Request too large."}, status_code=413)
            request._body = bytes(body)
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + session_token):
                return JSONResponse({"detail": "Open the current launch link to unlock this session."}, status_code=401)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        return JSONResponse({"detail": "Could not access local storage. Check folder permissions, locks and free disk space."}, status_code=400)

    static = Path(__file__).parent / "static"

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/app.js")
    def javascript():
        return FileResponse(static / "app.js", media_type="text/javascript")

    @app.get("/receipt.js")
    def receipt_javascript():
        return FileResponse(static / "receipt.js", media_type="text/javascript")

    @app.get("/library.js")
    def library_javascript():
        return FileResponse(static / "library.js", media_type="text/javascript")

    @app.get("/style.css")
    def stylesheet():
        return FileResponse(static / "style.css", media_type="text/css")

    def manager() -> Manager:
        return app.state.manager

    def store():
        if not manager().store:
            raise HTTPException(409, "Configure directories first.")
        return manager().store

    @app.get("/api/settings")
    def settings():
        return manager().settings()

    @app.put("/api/settings")
    def configure(value: SettingsInput):
        return manager().configure(value.source_directory, value.managed_directory)

    @app.post("/api/scans", status_code=202)
    def scan(value: ScanInput):
        return {"job_id": manager().start(value.year, value.month)}

    @app.put("/api/vision-settings")
    def vision_settings(value: VisionConfig):
        return manager().configure_vision(value)

    @app.post("/api/receipt-batches", status_code=202)
    def receipt_batch(value: BatchInput):
        return manager().start_receipt_batch(value.force)

    @app.get("/api/receipt-batches/{batch_id}")
    def receipt_batch_status(batch_id: str):
        store()
        return manager().batches.get(batch_id)

    @app.get("/api/scans")
    def scans():
        return store().jobs()

    @app.get("/api/scans/{job_id}")
    def scan_status(job_id: str):
        result = store().job(job_id)
        if result is None:
            raise HTTPException(404, "Scan not found.")
        return result

    @app.get("/api/scans/{job_id}/events")
    def events(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
        return store().events(job_id, offset, limit)

    @app.get("/api/documents")
    def documents(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), folder: str = "all"):
        return store().documents(manager().source, offset, limit, folder)

    @app.get("/api/folders")
    def folders():
        return store().folders(manager().source)

    @app.put("/api/documents/{document_id}/folder")
    def move_document(document_id: int, value: MoveInput):
        return manager().library_action(document_id, value.expected_hash, "move", value.folder.value)

    @app.post("/api/documents/{document_id}/trash")
    def trash_document(document_id: int, value: DeleteInput):
        return manager().library_action(document_id, value.expected_hash, "trash")

    @app.post("/api/documents/{document_id}/restore")
    def restore_document(document_id: int, value: LibraryInput):
        return manager().library_action(document_id, value.expected_hash, "restore")

    @app.get("/api/documents/{document_id}/versions")
    def versions(document_id: int):
        return store().versions(document_id)

    @app.post("/api/documents/{document_id}/receipt-runs", status_code=202)
    def parse_receipt(document_id: int, value: ReceiptInput):
        return manager().start_receipt(document_id, value.blob_hash, value.clockwise_rotation, value.force, value.organize)

    @app.post("/api/documents/{document_id}/organization-runs", status_code=202)
    def organize_document(document_id: int, value: LibraryInput):
        return manager().start_organization(document_id, value.expected_hash)

    @app.get("/api/organization-runs/{run_id}")
    def organization_result(run_id: str):
        store()
        return manager().organization.get(run_id)

    @app.get("/api/documents/{document_id}/receipt-runs")
    def receipt_history(document_id: int, blob_hash: str | None = Query(None, pattern=r"^[a-f0-9]{64}$")):
        store()
        return manager().receipts.history(document_id, blob_hash)

    @app.get("/api/receipt-runs/{run_id}")
    def receipt_result(run_id: str):
        store()
        return manager().receipts.get(run_id)

    @app.get("/api/receipt-runs/{run_id}/preview")
    def receipt_preview(run_id: str):
        store()
        return FileResponse(manager().receipts.preview(run_id), media_type="image/png")

    @app.get("/api/documents/{document_id}/image")
    def receipt_image(document_id: int, blob_hash: str | None = Query(None, pattern=r"^[a-f0-9]{64}$")):
        from .storage import digest_file
        document, selected = store().document_version(document_id, blob_hash)
        extension = Path(document["relative_path"]).suffix.lower()
        if extension not in (".png", ".jpg", ".jpeg"):
            raise HTTPException(400, "Only PNG/JPEG source image previews are available.")
        path = store().blob_path(selected["hash"])
        if digest_file(path) != selected["hash"]:
            raise HTTPException(409, "Preserved image failed its integrity check.")
        return FileResponse(path, media_type="image/png" if extension == ".png" else "image/jpeg")

    return app
