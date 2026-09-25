"""Loopback-only API and minimal manual-testing UI."""

from contextlib import asynccontextmanager
from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .finance import ACCOUNT_TYPES, PAYMENT_STATES, HouseholdConfig
from .finance_tools import ToolName, call_tool
from .folders import DocumentFolder
from .formats import IMAGES, extension
from .manager import Manager, default_control_dir
from .reasoning import ReasoningConfig
from .reconcile import OBLIGATION_DECISIONS
from .reviewer import ReviewerConfig
from .scanner import ScanLimits
from .storage import digest_file
from .tabular import ImportMapping
from .vision import VisionConfig

RecordType = Literal["statement", "transaction", "receipt", "bill", "income_record"]
STATIC = {"index.html": "text/html", "ui.js": "text/javascript", "app.js": "text/javascript", "shell.js": "text/javascript", "receipt.js": "text/javascript",
          "library.js": "text/javascript", "finance.js": "text/javascript", "home.js": "text/javascript", "style.css": "text/css"}


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


class BatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    force: bool = False


class EmptyTrashInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmed: Literal[True]


class ReceiptBatchInput(BatchInput):
    document_ids: list[int] | None = Field(default=None, min_length=1, max_length=500)


class ReasoningInput(BatchInput):
    parse_run_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class CancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    work_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected", "needs_review"]
    note: str = Field(default="", max_length=1000)


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    institution: str = Field(min_length=1, max_length=120)
    account_type: Literal[*ACCOUNT_TYPES]
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    display_name: str | None = Field(default=None, max_length=160)
    last_four: str | None = Field(default=None, pattern=r"^\d{4}$")


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    account_id: int | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    mapping: ImportMapping | None = None


class LinkReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected"]


class BillPaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal[*PAYMENT_STATES]
    transaction_id: int | None = None
    note: str = Field(default="", max_length=1000)


class ObligationReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal[*OBLIGATION_DECISIONS]
    note: str = Field(default="", max_length=1000)


class IssueResolutionInput(BaseModel):
    """Answer an ambiguous match: the chosen transaction, or null to leave the record unmatched."""
    model_config = ConfigDict(extra="forbid", strict=True)
    transaction_id: int | None


class FolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    destination: str = Field(min_length=1, max_length=4096)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    backup: str = Field(min_length=1, max_length=4096)
    target: str = Field(min_length=1, max_length=4096)


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=1000)


class CorrectionInput(BaseModel):
    """Field -> entered value (null clears it). Allowed fields depend on the record type."""
    model_config = ConfigDict(extra="forbid", strict=True)
    changes: dict[str, str | None] = Field(min_length=1, max_length=5)


class DescriptionInput(BaseModel):
    """The user's short label for a document; null or blank returns to the AI's description."""
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str | None = Field(max_length=60)


class CategoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: str | None = Field(default=None, min_length=1, max_length=60)


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
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
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
    for name, media_type in STATIC.items():
        app.add_api_route("/" if name == "index.html" else "/" + name,
                          lambda name=name, media_type=media_type: FileResponse(static / name, media_type=media_type),
                          methods=["GET"], include_in_schema=False)

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

    @app.post("/api/inbox-scans", status_code=202)
    def scan_inbox():
        return {"job_id": manager().start_inbox()}

    @app.post("/api/receipt-batches", status_code=202)
    def receipt_batch(value: ReceiptBatchInput):
        return manager().start_receipt_batch(value.force, value.document_ids)

    @app.put("/api/reviewer-settings")
    def reviewer_settings(value: ReviewerConfig):
        return manager().configure_reviewer(value)

    @app.put("/api/household-settings")
    def household_settings(value: HouseholdConfig):
        return manager().configure_household(value)

    @app.get("/api/dashboard")
    def home_dashboard(month: str = Query(pattern=r"^\d{4}-\d{2}$"), months: int = Query(6, ge=6, le=12),
                       currency: str | None = Query(None, pattern=r"^[A-Z]{3}$")):
        from .dashboard import dashboard
        owner = manager()
        with owner.mutex:
            return dashboard(owner.require(False), owner.source, month, months, currency, owner.household.home_currency)

    @app.put("/api/reasoning-settings")
    def reasoning_settings(value: ReasoningConfig):
        return manager().configure_reasoning(value)

    @app.post("/api/documents/{document_id}/reasoning-runs", status_code=202)
    def analyze_document(document_id: int, value: ReasoningInput):
        return manager().start_reasoning(document_id, value.parse_run_id, value.force)

    @app.post("/api/documents/{document_id}/extraction-runs", status_code=202)
    def extract_document(document_id: int, value: ReasoningInput):
        return manager().start_extraction(document_id, value.parse_run_id, value.force)

    @app.get("/api/receipt-runs/{parse_run_id}/extraction-runs")
    def extraction_history(parse_run_id: str):
        store()
        return manager().extractions.history(parse_run_id)

    @app.get("/api/extraction-runs/{run_id}")
    def extraction_result(run_id: str):
        store()
        return manager().extractions.get(run_id)

    @app.get("/api/finance/accounts")
    def accounts():
        store()
        return manager().ledger.accounts()

    @app.post("/api/finance/accounts", status_code=201)
    def create_account(value: AccountInput):
        store()
        return manager().ledger.create_account(value.institution, value.account_type, value.currency, value.display_name, value.last_four)

    @app.post("/api/documents/{document_id}/transaction-import/preview")
    def preview_import(document_id: int, value: ImportInput):
        store()
        ledger = manager().ledger
        currency = ledger.account(value.account_id)["currency"] if value.account_id else value.currency
        if not currency:
            raise HTTPException(400, "Choose an account or a currency for the preview.")
        return ledger.preview_import(document_id, currency, value.mapping, value.expected_hash)

    @app.post("/api/documents/{document_id}/transaction-imports", status_code=201)
    def import_transactions(document_id: int, value: ImportInput):
        if value.account_id is None:
            raise HTTPException(400, "Choose the account these transactions belong to.")
        return manager().import_transactions(document_id, value.account_id, value.mapping, value.expected_hash)

    @app.post("/api/finance/reconcile")
    def reconcile():
        store()
        return manager().reconciler.run("manual")

    @app.get("/api/finance/reconciliation-runs")
    def reconciliation_runs(limit: int = Query(20, ge=1, le=200)):
        store()
        return manager().reconciler.history(limit)

    @app.post("/api/finance/issues/{issue_id}/resolve")
    def resolve_issue(issue_id: int, value: IssueResolutionInput):
        store()
        return manager().reconciler.resolve_issue(issue_id, value.transaction_id)

    @app.post("/api/finance/bills/{bill_id}/payment")
    def bill_payment(bill_id: int, value: BillPaymentInput):
        store()
        return manager().ledger.set_bill_payment(bill_id, value.status, value.transaction_id, value.note)

    @app.post("/api/finance/recurring/{obligation_id}/review")
    def review_obligation(obligation_id: int, value: ObligationReviewInput):
        store()
        return manager().reconciler.review_obligation(obligation_id, value.status, value.note)

    @app.post("/api/finance/links/{kind}/{link_id}/review")
    def review_link(kind: Literal["receipt", "transfer", "refund"], link_id: int, value: LinkReviewInput):
        store()
        return manager().reconciler.review_link(kind, link_id, value.status)

    @app.put("/api/finance/transactions/{transaction_id}/category")
    def categorize(transaction_id: int, value: CategoryInput):
        store()
        return manager().ledger.set_category(transaction_id, value.category)

    @app.post("/api/finance/tools/{name}")
    def finance_tool(name: ToolName, arguments: dict | None = None):
        store()
        return call_tool(manager().tools, name, arguments)

    @app.get("/api/finance/records/{record_type}/{record_id}")
    def finance_record(record_type: RecordType, record_id: int):
        store()
        return manager().ledger.record(record_type, record_id)

    @app.patch("/api/finance/records/{record_type}/{record_id}")
    def correct_record(record_type: RecordType, record_id: int, value: CorrectionInput):
        store()
        return manager().correct_record(record_type, record_id, value.changes)

    @app.post("/api/finance/records/{record_type}/{record_id}/review")
    def review_record(record_type: RecordType, record_id: int, value: ReviewInput):
        store()
        return manager().ledger.review(record_type, record_id, value.status, value.note)

    @app.get("/api/receipt-runs/{parse_run_id}/reasoning-runs")
    def reasoning_history(parse_run_id: str):
        store()
        return manager().reasoning.history(parse_run_id)

    @app.get("/api/reasoning-runs/{run_id}")
    def reasoning_result(run_id: str):
        store()
        return manager().reasoning.get(run_id)

    @app.get("/api/receipt-batches/{batch_id}")
    def receipt_batch_status(batch_id: str):
        store()
        return manager().batches.get(batch_id)

    @app.get("/api/activity")
    def activity():
        store()
        return manager().activity()

    @app.post("/api/activity/cancel")
    def cancel_work(value: CancelInput):
        store()
        return manager().cancel(value.work_id)

    @app.post("/api/model-connection-tests")
    def model_connection(value: ReasoningConfig):
        return manager().test_model_connection(value)

    @app.get("/api/jobs")
    def job_history(limit: int = Query(50, ge=1, le=500), kind: list[str] | None = Query(None)):
        return store().job_history(limit, kind)

    @app.post("/api/backups", status_code=202)
    def create_backup(value: FolderInput):
        return manager().start_backup(value.destination)

    @app.get("/api/backups")
    def backups(limit: int = Query(20, ge=1, le=200)):
        store()
        return manager().backups.history(limit)

    @app.post("/api/restores", status_code=202)
    def create_restore(value: RestoreInput):
        return manager().start_restore(value.backup, value.target)

    @app.get("/api/restores/{restore_id}")
    def restore_status(restore_id: str):
        return manager().restore(restore_id)

    @app.post("/api/assistant-runs", status_code=202)
    def ask(value: QuestionInput):
        return manager().start_assistant(value.question)

    @app.get("/api/assistant-runs")
    def assistant_runs(limit: int = Query(20, ge=1, le=200)):
        store()
        return manager().assistant.history(limit)

    @app.get("/api/assistant-runs/{run_id}")
    def assistant_run(run_id: str):
        store()
        return manager().assistant.get(run_id)

    @app.get("/api/model-runs")
    def model_runs(limit: int = Query(50, ge=1, le=200)):
        return store().model_runs(limit=limit)

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
    def documents(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), folder: str = "all",
                  status: str = "all", q: str | None = Query(None, max_length=200), sort: str = "path",
                  date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                  date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
        return store().documents(manager().source, offset, limit, folder, status, q, sort, date_from, date_to)

    @app.get("/api/documents/{document_id}")
    def document(document_id: int):
        return store().document(manager().source, document_id)

    @app.put("/api/documents/{document_id}/description")
    def describe_document(document_id: int, value: DescriptionInput):
        return store().set_description(manager().source, document_id, value.description)

    @app.get("/api/folders")
    def folders():
        return store().folders(manager().source)

    @app.put("/api/documents/{document_id}/folder")
    def move_document(document_id: int, value: MoveInput):
        return manager().library_action(document_id, value.expected_hash, "move", value.folder.value)

    @app.post("/api/trash/empty")
    def empty_trash(value: EmptyTrashInput):
        return manager().empty_trash()

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
        return manager().start_receipt(document_id, value.blob_hash, value.clockwise_rotation, value.force)

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

    @app.get("/api/documents/{document_id}/preview")
    @app.get("/api/documents/{document_id}/image")
    def receipt_image(document_id: int, blob_hash: str | None = Query(None, pattern=r"^[a-f0-9]{64}$")):
        document, selected = store().document_version(document_id, blob_hash)
        suffix = extension(document["relative_path"])
        if suffix not in IMAGES | {".pdf"}:
            raise HTTPException(400, "Only PNG/JPEG and PDF previews are available.")
        path = store().blob_path(selected["hash"])
        if digest_file(path) != selected["hash"]:
            raise HTTPException(409, "Preserved document failed its integrity check.")
        media_type = "application/pdf" if suffix == ".pdf" else "image/png" if suffix == ".png" else "image/jpeg"
        return FileResponse(path, media_type=media_type)

    return app
