"""Loopback-only API and minimal manual-testing UI."""

from contextlib import asynccontextmanager
from datetime import date
import logging
from pathlib import Path
import secrets
import sqlite3
from typing import Literal
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core import actor
from ..core.categories import FREQUENCIES, RECURRING_KINDS
from ..core.folders import DocumentFolder
from ..core.formats import IMAGES, extension
from ..core.logs import attach_server, log_failure
from ..documents.reasoning import ReasoningConfig
from ..documents.reviewer import ReviewerConfig
from ..finance import rules, traces
from ..finance.forecast import AssetInput, Assets, ForecastInput, forecast
from ..finance.health import check_ledger, summary
from ..finance.investments import AccountInput as InvestmentAccountInput
from ..finance.investments import (
    AccountUpdate,
    EventInput,
    HoldingInput,
    IbondRateInput,
    Investments,
    LotInput,
    MaturedInput,
    PayrollChoice,
    PensionInput,
    ValueInput,
    WithdrawalKind,
)
from ..finance.item_categories import ItemCategorizer
from ..finance.ledger import ACCOUNT_TYPES, HouseholdConfig, UiRoute
from ..finance.paycheck import PaycheckInput
from ..finance.provenance import provenance_for
from ..finance.reconcile import OBLIGATION_DECISIONS, Reconciler
from ..finance.scenarios import MAX_COMPARED, ScenarioInput, Scenarios
from ..finance.tabular import ImportMapping
from ..finance.tax_family import TaxUnits
from ..finance.tax_lines import BUSINESS_KINDS, INCOME_KINDS, KINDS, LINES
from ..finance.tax_tags import TaxTags
from ..finance.tax_year import TaxYears
from ..finance.tools import ToolName, call_tool
from ..household.items import CHECKIN_ANSWERS, LOT_EVENTS, ResolutionFields
from ..household.warranty import Warranties
from ..library.scanner import ScanLimits
from ..library.storage import digest_file
from ..models.decisions import DecisionConfig
from ..models.vision import ModelComputer, VisionConfig
from .manager import FAMILY_READ_ONLY, Manager, default_control_dir

log = logging.getLogger(__name__)
RecordType = Literal["statement", "transaction", "receipt", "bill", "income_record"]
STATIC = {"index.html": "text/html", "ui.js": "text/javascript", "app.js": "text/javascript", "shell.js": "text/javascript", "receipt.js": "text/javascript",
          "library.js": "text/javascript", "finance.js": "text/javascript", "review.js": "text/javascript", "inventory.js": "text/javascript", "search.js": "text/javascript", "processing.js": "text/javascript", "assistant.js": "text/javascript", "home.js": "text/javascript", "today_v2.js": "text/javascript", "forecast.js": "text/javascript", "whatif.js": "text/javascript", "taxes.js": "text/javascript","investments.js": "text/javascript", "profiles.js": "text/javascript", "donate.js": "text/javascript", "trace.js": "text/javascript", "taxes_v2.js": "text/javascript", "theme.js": "text/javascript", "style.css": "text/css",
          # Self-hosted fonts (OFL; the license files sit beside them and aren't served).
          "fonts/PlusJakartaSans-Variable.woff2": "font/woff2", "fonts/JetBrainsMono-Regular.woff2": "font/woff2",
          "fonts/JetBrainsMono-Medium.woff2": "font/woff2"}


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    managed_directory: str = Field(min_length=1, max_length=4096)


class UiScreensInput(BaseModel):
    """The routes that show their redesigned screen (docs/ui.md "Migration")."""
    model_config = ConfigDict(extra="forbid", strict=True)
    routes: list[UiRoute] = Field(max_length=32)


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=4096)
    label: str = Field(default="", max_length=100)
    recursive: bool = True


class SourceChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    label: str | None = Field(default=None, max_length=100)
    recursive: bool | None = None
    enabled: bool | None = None


class SplitInput(BaseModel):
    """Where each receipt of a file starts, as line ids of its reading. One start: the file is one receipt."""
    model_config = ConfigDict(extra="forbid", strict=True)
    starts: list[str] = Field(min_length=1, max_length=200)


class GroupInput(BaseModel):
    """Images to read as one document, pages in this order."""
    model_config = ConfigDict(extra="forbid", strict=True)
    document_ids: list[int] = Field(min_length=2, max_length=20)


class GroupChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["confirmed", "dismissed"] | None = None
    document_ids: list[int] | None = Field(default=None, min_length=2, max_length=20)


class ModelComputerInput(ModelComputer):
    # Write-only: a new token replaces the saved one; omitted keeps it. Never returned.
    token: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{20,200}$")


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=60)
    folder: str = Field(min_length=1, max_length=4096)


class RenameInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=60)


class ActiveProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=40)


class FamilyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=60)
    folder: str = Field(min_length=1, max_length=4096)
    members: list[str] = Field(default_factory=list, max_length=20)
    my_profile: str | None = Field(default=None, max_length=40)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=60)


class LocalMemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile_id: str | None = Field(default=None, max_length=40)
    folder: str | None = Field(default=None, min_length=1, max_length=4096)


class InviteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    destination: str = Field(min_length=1, max_length=4096)
    passphrase: str = Field(min_length=1, max_length=1024)


class JoinInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    invite_file: str = Field(min_length=1, max_length=4096)
    passphrase: str = Field(min_length=1, max_length=1024)


class PublishingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    publishing: bool


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["member", "shared"]
    members: list[str] = Field(min_length=1, max_length=20)


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


class DonationStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    record_type: Literal["receipt", "statement", "income_record"]
    record_id: int = Field(ge=1)


class DonationField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str | None = Field(default=None, max_length=200)
    state: Literal["correct", "fixed", "unchecked"] = "unchecked"


class DonationBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, le=20)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class DonationAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, DonationField] = Field(default_factory=dict, max_length=20)
    rows: list[dict[str, str | None]] | None = Field(default=None, max_length=500)
    rows_state: Literal["correct", "fixed", "unchecked"] | None = None
    rows_complete: bool | None = None
    source_kind: Literal["phone_photo", "scan", "native_pdf", "image_pdf"] | None = None
    redactions: list[DonationBox] | None = Field(default=None, max_length=50)
    finish: bool = False


class DonationExport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    check_ids: list[int] = Field(min_length=1, max_length=200)
    donor: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,16}$")


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


class CryptoImportInput(BaseModel):
    """An exchange's transaction history in the library, read into an investment account (finance/tabular.py CRYPTO_PRESETS)."""
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: int = Field(ge=1)
    expected_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    preset: Literal["coinbase"] = "coinbase"


class LinkReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected"]


class ObligationReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal[*OBLIGATION_DECISIONS]
    note: str = Field(default="", max_length=1000)
    frequency: Literal[*FREQUENCIES] | None = None  # A correction of how often it recurs, made while deciding.
    kind: Literal[*RECURRING_KINDS] | None = None  # Bill or subscription, chosen while deciding.


class ObligationKindInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal[*RECURRING_KINDS]


class IssueResolutionInput(BaseModel):
    """Answer an ambiguous match: the chosen transaction, or null to leave the record unmatched. A conflicting family
    correction is answered with family: "mine" (keep this person's value) or "family" (use the family's)."""
    model_config = ConfigDict(extra="forbid", strict=True)
    transaction_id: int | None = None
    family: Literal["mine", "family"] | None = None


class FolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    destination: str = Field(min_length=1, max_length=4096)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    backup: str = Field(min_length=1, max_length=4096)
    target: str = Field(min_length=1, max_length=4096)


# Passphrases carry no field constraints: a validation error would echo the rejected value back.
# share.py checks them and never includes them in a message.
class ShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    destination: str = Field(min_length=1, max_length=4096)
    passphrase: str
    label: str = Field(default="", max_length=60)


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    share_file: str = Field(min_length=1, max_length=4096)
    passphrase: str


class ItemReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected"]
    edits: ResolutionFields | None = None  # The user's corrections, applied on approval.


class LotEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event: Literal[*LOT_EVENTS]
    effective_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    precision_days: int = Field(default=0, ge=0, le=7)


class LotReturnInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lot_id: int | None = None  # The lot the returned line closed; None says it closed none of them.


class CheckinAnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: Literal[*CHECKIN_ANSWERS]
    source: Literal["checkin", "manual"] = "checkin"  # Manual: an update made on the inventory screen.


class CheckinTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1, max_length=2000)


class CheckinApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lot_ids: list[int] = Field(min_length=1, max_length=30)


class RuleInput(BaseModel):
    """Transactions whose merchant or description contain every word of the pattern get the category."""
    model_config = ConfigDict(extra="forbid", strict=True)
    pattern: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    account_id: int | None = None


class BudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: str = Field(min_length=1, max_length=60)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    amount: str = Field(min_length=1, max_length=30, description="The monthly amount as printed, e.g. 450.00.")


class PolicyInput(BaseModel):
    """A merchant's return policy; days null means no fixed limit."""
    model_config = ConfigDict(extra="forbid", strict=True)
    merchant: str = Field(min_length=1, max_length=80)
    days: int | None = Field(ge=0, le=730)
    note: str = Field(default="", max_length=200)


class WarrantyInput(BaseModel):
    """The user's own warranty for an item: a length in months, or lifetime."""
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["manufacturer", "store", "extended"] = "manufacturer"
    months: int | None = Field(default=None, ge=1, le=600)
    lifetime: bool = False
    note: str = Field(default="", max_length=200)


class WarrantyReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected"]


class AssetReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected", "proposed"]


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=1000)
    context: str | None = Field(default=None, max_length=300, description="The page the user is viewing, e.g. 'Transactions · Sep 1 – Sep 30'.")


class CorrectionInput(BaseModel):
    """Field -> entered value (null clears it). Allowed fields depend on the record type."""
    model_config = ConfigDict(extra="forbid", strict=True)
    changes: dict[str, str | None] = Field(min_length=1, max_length=8)
    reason: str | None = Field(default=None, max_length=500)  # Optional: why, kept with the correction.


class ManualTransactionInput(BaseModel):
    """A payment entered by hand: it counts at once, until its statement or import line replaces it."""
    model_config = ConfigDict(extra="forbid", strict=True)
    account_id: int
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str = Field(min_length=1, max_length=200)
    amount: str = Field(min_length=1, max_length=40)
    direction: Literal["out", "in"] = "out"
    category: str | None = Field(default=None, max_length=60)


class ValueCorrectionInput(BaseModel):
    """A value read from a document, set right: the amount as printed (in the record's currency) and why, optionally."""
    model_config = ConfigDict(extra="forbid", strict=True)
    value: str = Field(min_length=1, max_length=40)
    reason: str | None = Field(default=None, max_length=500)


class BoxCorrectionInput(ValueCorrectionInput):
    form: str = Field(min_length=3, max_length=10)
    box: str = Field(min_length=1, max_length=10)


class HoldingCorrectionInput(BaseModel):
    """A holding's yearly rate (percent), maturity date, or its value on one statement date (as_of); null clears a term."""
    model_config = ConfigDict(extra="forbid", strict=True)
    field: Literal["rate", "maturity_date", "value"]
    value: str | None = Field(default=None, max_length=40)
    as_of: str | None = Field(default=None, max_length=10)
    reason: str | None = Field(default=None, max_length=500)


class DescriptionInput(BaseModel):
    """The user's short label for a document; null or blank returns to the AI's description."""
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str | None = Field(max_length=60)


class TaxTableLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    jurisdiction: str = Field(pattern=r"^(US|[A-Z]{2})$", description="US for federal, or a state's two-letter code.")
    year: int = Field(ge=2000, le=2100)
    filing_status: Literal["single", "married_joint", "head_of_household"] | None = Field(
        default=None, description="The household's status unless the paycheck planner plans for another.")


class CompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scenarios: list[int] = Field(default_factory=list, max_length=MAX_COMPARED)
    draft: ScenarioInput | None = Field(default=None, description="A plan being edited, compared before it is saved.")
    include_now: bool = True
    years: int = Field(default=10, ge=1, le=100)


class TaxTagInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_type: Literal["transaction", "receipt", "receipt_item"]
    target_id: int
    kind: str = Field(max_length=40)
    line: str = Field(max_length=40)
    business_id: int | None = None
    amount: str | None = Field(default=None, max_length=30, description="The part that counts; the whole item when left out.")
    note: str = Field(default="", max_length=200)


class TaxTagReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected"]
    rule_words: str | None = Field(default=None, max_length=120, description="Also tag every bank line with these words.")


class TaxRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pattern: str = Field(min_length=1, max_length=120)
    kind: str = Field(max_length=40)
    line: str = Field(max_length=40)
    business_id: int | None = None
    account_id: int | None = None


class BusinessInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=60)


class TaxUnitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(default="", max_length=60)
    members: list[str] = Field(min_length=1, max_length=2)
    filing_status: Literal["single", "married_joint", "head_of_household"]


class AdoptInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Budgets are the plan's set spending in this month; followed from then.")


class TaxTableReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["verified", "rejected"]


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
        attach_server()  # Uvicorn has reset its loggers by now; its errors join the app log (if configured).
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
        # Who's here (core/actor.py): checked against the profile's people and held for this request's writers. A profile
        # with one person needs no choice: it is them.
        people = manager().people()
        try:
            person = actor.checked(unquote(request.headers.get(actor.HEADER, "")), people)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        if person is None and len(people) == 1:
            person = people[0]
        with actor.acting_as(person):
            response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # FastAPI's default echoes each rejected value. Requests carry passphrases and document text,
        # so only where the problem is and what it is are returned.
        return JSONResponse({"detail": [{"loc": list(error.get("loc", ())), "msg": error.get("msg", ""), "type": error.get("type", "")}
                                        for error in exc.errors()]}, status_code=422)

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        return JSONResponse({"detail": "Could not access local storage. Check folder permissions, locks and free disk space."}, status_code=400)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        log_failure(log, "request", exc, path=request.url.path)
        return JSONResponse({"detail": "The library database could not complete this request. Details are in the Home Manager log."}, status_code=500)

    static = Path(__file__).parent / "static"
    for name, media_type in STATIC.items():
        app.add_api_route("/" if name == "index.html" else "/" + name,
                          lambda name=name, media_type=media_type: FileResponse(static / name, media_type=media_type),
                          methods=["GET"], include_in_schema=False)

    def manager() -> Manager:
        return app.state.manager

    def store():
        if not manager().store:
            raise HTTPException(409, FAMILY_READ_ONLY if manager().family else "Configure directories first.")
        return manager().store

    @app.get("/api/settings")
    def settings():
        return manager().settings()

    # Profiles and families -------------------------------------------------------

    @app.get("/api/profiles")
    def profiles():
        view = manager().settings()
        return {"active": view["profile"], "profiles": view["profiles"], "family": view["family"], "hub_status": view["hub_status"]}

    @app.post("/api/profiles", status_code=201)
    def create_profile(value: ProfileInput):
        return manager().create_profile(value.name, value.folder)

    @app.put("/api/profiles/active")
    def switch_profile(value: ActiveProfileInput):
        return manager().switch_profile(value.id)

    @app.patch("/api/profiles/{profile_id}")
    def rename_profile(profile_id: str, value: RenameInput):
        return manager().rename_profile(profile_id, value.name)

    @app.delete("/api/profiles/{profile_id}")
    def remove_profile(profile_id: str):
        return manager().remove_profile(profile_id)

    @app.post("/api/families", status_code=201)
    def create_family(value: FamilyInput):
        return manager().create_family(value.name, value.folder, value.members, value.my_profile)

    @app.post("/api/families/{profile_id}/members", status_code=201)
    def add_member(profile_id: str, value: MemberInput):
        return manager().add_family_member(profile_id, value.name)

    @app.delete("/api/families/{profile_id}/members/{member_id}")
    def remove_member(profile_id: str, member_id: str):
        return manager().remove_family_member(profile_id, member_id)

    @app.post("/api/families/{profile_id}/members/{member_id}/local")
    def local_member(profile_id: str, member_id: str, value: LocalMemberInput):
        return manager().set_up_local_member(profile_id, member_id, value.profile_id, value.folder)

    @app.post("/api/families/{profile_id}/members/{member_id}/invites", status_code=201)
    def invite_member(profile_id: str, member_id: str, value: InviteInput):
        return manager().invite_member(profile_id, member_id, value.destination, value.passphrase)

    @app.post("/api/family-refreshes", status_code=202)
    def refresh_family():
        return manager().start_family_refresh()

    @app.get("/api/family/net-worth")
    def family_net_worth(currency: str | None = Query(None, pattern=r"^[A-Z]{3}$")):
        if not manager().family:
            raise HTTPException(409, "Open a family profile first.")
        return manager().family_net_worth(currency)

    @app.get("/api/family/routing")
    def family_routing(include_delivered: bool = False):
        return manager().family_routing(include_delivered)

    @app.put("/api/family/routing/{record_type}/{record_id}")
    def assign_family_record(record_type: Literal["receipt", "bill", "statement", "income_record"], record_id: int, value: AssignmentInput):
        return manager().assign_family_record(record_type, record_id, value.mode, value.members)

    @app.post("/api/family-membership", status_code=201)
    def join_family(value: JoinInput):
        return manager().join_family(value.invite_file, value.passphrase)

    @app.put("/api/family-membership")
    def family_publishing(value: PublishingInput):
        return manager().set_publishing(value.publishing)

    @app.delete("/api/family-membership")
    def leave_family():
        return manager().leave_joined_family()

    @app.post("/api/family-publishes", status_code=202)
    def publish_family():
        return manager().start_family_publish()

    @app.put("/api/settings")
    def configure(value: SettingsInput):
        return manager().configure(value.managed_directory)

    @app.put("/api/vision-settings")
    def vision_settings(value: VisionConfig):
        return manager().configure_vision(value)

    @app.post("/api/inbox-scans", status_code=202)
    def scan_inbox():
        return {"job_id": manager().start_inbox()}

    @app.get("/api/sources")
    def sources():
        return manager().sources()

    @app.post("/api/sources", status_code=201)
    def add_source(value: SourceInput):
        return manager().add_source(value.path, value.label, value.recursive)

    @app.patch("/api/sources/{source_id}")
    def change_source(source_id: int, value: SourceChange):
        return manager().update_source(source_id, **value.model_dump())

    @app.delete("/api/sources/{source_id}")
    def remove_source(source_id: int):
        manager().remove_source(source_id)
        return {"removed": source_id}

    @app.post("/api/sources/{source_id}/scans", status_code=202)
    def scan_source(source_id: int):
        return {"job_id": manager().start_source(source_id)}

    @app.get("/api/documents/{document_id}/links")
    def document_links(document_id: int):
        return store().linked_documents(document_id)

    @app.get("/api/documents/{document_id}/segments")
    def document_split(document_id: int):
        return manager().split(document_id)

    @app.post("/api/documents/{document_id}/segments/confirm")
    def confirm_split(document_id: int):
        return manager().confirm_split(document_id)

    @app.put("/api/documents/{document_id}/segments", status_code=202)
    def set_split(document_id: int, value: SplitInput):
        return manager().set_split(document_id, value.starts)

    @app.get("/api/document-groups")
    def suggested_groups():
        return manager().suggested_groups()

    @app.post("/api/document-groups", status_code=202)
    def combine_documents(value: GroupInput):
        return manager().combine_documents(value.document_ids)

    @app.patch("/api/document-groups/{group_id}", status_code=202)
    def change_group(group_id: int, value: GroupChange):
        if (value.status is None) == (value.document_ids is None):
            raise HTTPException(400, "Either confirm or separate the combined document, or give its pages in a new order.")
        return manager().change_group(group_id, value.status, value.document_ids)

    @app.get("/api/documents/{document_id}/group")
    def document_group(document_id: int):
        return manager().document_group(document_id)

    @app.get("/api/receipt-runs/{run_id}/pages/{number}")
    def receipt_page(run_id: str, number: int):
        store()
        return FileResponse(manager().receipts.page_image(run_id, number), media_type="image/png")

    @app.post("/api/receipt-batches", status_code=202)
    def receipt_batch(value: ReceiptBatchInput):
        return manager().start_receipt_batch(value.force, value.document_ids)

    @app.put("/api/reviewer-settings")
    def reviewer_settings(value: ReviewerConfig):
        return manager().configure_reviewer(value)

    @app.put("/api/household-settings")
    def household_settings(value: HouseholdConfig):
        return manager().configure_household(value)

    @app.put("/api/ui-screens")
    def ui_screens(value: UiScreensInput):
        owner = manager()
        return owner.configure_household(owner.household.model_copy(update={"ui_v2_screens": value.routes}))

    @app.get("/api/dashboard")
    def home_dashboard(month: str = Query(pattern=r"^\d{4}-\d{2}$"), months: int = Query(6, ge=6, le=12),
                       currency: str | None = Query(None, pattern=r"^[A-Z]{3}$")):
        from ..finance.dashboard import dashboard, figures
        owner = manager()
        if owner.family:
            return owner.family_dashboard(month, months, currency)
        with owner.mutex:
            library = owner.require(False)
            found = dashboard(library, month, months, currency, owner.household.home_currency)
            traces.shown(library, figures(found))  # Each says whether it changed since it was last shown.
        found["attention"]["tax"] = owner.tax_attention()  # Tax Zen got worse since the Taxes page last showed it (§42).
        return found

    @app.put("/api/reasoning-settings")
    def reasoning_settings(value: ReasoningConfig):
        return manager().configure_reasoning(value)

    @app.put("/api/decision-settings")
    def decision_settings(value: DecisionConfig):
        return manager().configure_decision(value)

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

    @app.get("/api/finance/health")
    def ledger_health():
        """Every ledger rule the data breaks, by record id (finance/health.py), and whether each tax engine can run here.
        Read-only."""
        from ..finance import tax_engine
        with store().connection() as db:
            problems = check_ledger(db)
        return {"summary": summary(problems), "problems": [item._asdict() for item in problems],
                "tax_engines": [tax_engine.readiness(slot) for slot in tax_engine.ENGINES]}

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

    @app.get("/api/finance/statements/awaiting-reconciliation")
    def statements_awaiting():
        store()
        return manager().reconciler.awaiting()

    @app.post("/api/finance/statements/{statement_id}/reconcile")
    def reconcile_statement(statement_id: int):
        store()
        return manager().reconciler.reconcile_statement(statement_id)

    @app.get("/api/finance/reconciliation-runs")
    def reconciliation_runs(limit: int = Query(20, ge=1, le=200)):
        store()
        return manager().reconciler.history(limit)

    @app.post("/api/finance/issues/{issue_id}/resolve")
    def resolve_issue(issue_id: int, value: IssueResolutionInput):
        store()
        return manager().resolve_issue(issue_id, value.transaction_id, value.family)

    @app.post("/api/finance/recurring/scan", status_code=202)
    def recurring_scan():
        store()
        return manager().start_recurring_scan()

    @app.post("/api/finance/recurring/{obligation_id}/review")
    def review_obligation(obligation_id: int, value: ObligationReviewInput):
        store()
        return manager().reconciler.review_obligation(obligation_id, value.status, value.note, value.frequency, value.kind)

    @app.post("/api/finance/recurring/{obligation_id}/kind")
    def set_obligation_kind(obligation_id: int, value: ObligationKindInput):
        store()
        return manager().reconciler.set_obligation_kind(obligation_id, value.kind)

    @app.post("/api/finance/links/{kind}/{link_id}/review")
    def review_link(kind: Literal["receipt", "transfer", "refund"], link_id: int, value: LinkReviewInput):
        store()
        return manager().reconciler.review_link(kind, link_id, value.status)

    @app.put("/api/finance/transactions/{transaction_id}/category")
    def categorize(transaction_id: int, value: CategoryInput):
        store()
        return manager().ledger.set_category(transaction_id, value.category)

    @app.put("/api/receipts/{receipt_id}/items/{position}/category")
    def categorize_item(receipt_id: int, position: int, value: CategoryInput):
        store()
        return manager().ledger.set_item_category(receipt_id, position, value.category)

    @app.get("/api/finance/item-categories")
    def item_categories_pending():
        store()
        return {"receipts": len(ItemCategorizer(store()).pending())}

    @app.post("/api/finance/item-categories/backfill", status_code=202)
    def item_categories_backfill():
        store()
        return manager().start_item_categories()

    @app.post("/api/finance/tools/{name}")
    def finance_tool(name: ToolName, arguments: dict | None = None, members: bool = False):
        # members: the family ledger pages ask across every member's copy, merged (finance/family.py family_tool). Without
        # it a family profile's tools read the family's own library, its inbox (Review, Home).
        if members and manager().family:
            return manager().family_finance_tool(name, arguments)
        store()
        return call_tool(manager().tools, name, arguments)

    @app.get("/api/finance/records/{record_type}/{record_id}")
    def finance_record(record_type: RecordType, record_id: int, member: str | None = Query(None, pattern=r"^[0-9a-f]{12}$")):
        if member and manager().family:  # The family ledger's drawer: a member's record from their copy.
            return manager().family_record(member, record_type, record_id)
        store()
        if record_type == "income_record":  # With how its taxes were figured.
            return manager().paystub(record_id)
        return manager().ledger.record(record_type, record_id)

    @app.get("/api/tax-tables")
    def tax_tables(status: Literal["proposed", "verified", "rejected"] | None = None):
        store()
        return {"tables": manager().tax_tables.tables.list(status)}

    @app.post("/api/tax-tables/lookup", status_code=202)
    def tax_table_lookup(value: TaxTableLookupInput):
        store()
        return manager().start_tax_table_lookup(value.jurisdiction, value.year, value.filing_status)

    @app.post("/api/paycheck")
    def plan_paycheck(value: PaycheckInput):
        store()
        return manager().paycheck(value)

    @app.get("/api/paycheck/from-stub/{income_id}")
    def paycheck_from_stub(income_id: int):
        store()
        return manager().paycheck_from_stub(income_id)

    # What If scenarios: stored in the open library (the family's own library in the family view).
    @app.get("/api/scenarios")
    def list_scenarios():
        store()
        return manager().scenarios_view()

    @app.post("/api/scenarios", status_code=201)
    def create_scenario(value: ScenarioInput):
        return Scenarios(store()).create(value)

    @app.post("/api/scenarios/compare")
    def compare_scenarios(value: CompareInput):
        store()
        return manager().compare_scenarios(value.scenarios, value.draft, value.include_now, value.years)

    @app.put("/api/scenarios/{scenario_id}")
    def update_scenario(scenario_id: int, value: ScenarioInput):
        return Scenarios(store()).update(scenario_id, value)

    @app.post("/api/scenarios/{scenario_id}/duplicate", status_code=201)
    def duplicate_scenario(scenario_id: int):
        return Scenarios(store()).duplicate(scenario_id)

    @app.delete("/api/scenarios/{scenario_id}")
    def delete_scenario(scenario_id: int):
        return Scenarios(store()).delete(scenario_id)

    # Tax tags: write-offs, business income, credit spending and tax paid ahead (finance/tax_tags.py).
    @app.get("/api/tax/setup")
    def tax_setup():
        return {"kinds": KINDS, "lines": {kind: [{"key": key, "label": label, "form_line": form} for key, label, form in lines] for kind, lines in LINES.items()},
                "business_kinds": list(BUSINESS_KINDS), "income_kinds": list(INCOME_KINDS), "businesses": TaxTags(store()).businesses()}

    @app.post("/api/tax/businesses", status_code=201)
    def add_business(value: BusinessInput):
        return TaxTags(store()).add_business(value.name)

    @app.put("/api/tax/businesses/{business_id}")
    def rename_business(business_id: int, value: BusinessInput):
        return TaxTags(store()).rename_business(business_id, value.name)

    @app.delete("/api/tax/businesses/{business_id}")
    def archive_business(business_id: int):
        return TaxTags(store()).archive_business(business_id)

    @app.get("/api/tax-tags")
    def list_tax_tags(status: Literal["proposed", "verified", "rejected"] | None = None, year: int | None = Query(None, ge=1990, le=2100),
                      kind: str | None = None, receipt_id: int | None = None):
        return {"tags": TaxTags(store()).list(status, year, kind=kind, receipt_id=receipt_id)}

    @app.get("/api/tax-tags/on/{target_type}/{target_id}")
    def tax_tag_on(target_type: Literal["transaction", "receipt", "receipt_item"], target_id: int):
        return {"tag": TaxTags(store()).on(target_type, target_id)}

    @app.post("/api/tax-tags", status_code=201)
    def tag_item(value: TaxTagInput):
        return TaxTags(store()).tag(value.target_type, value.target_id, value.kind, value.line, value.business_id, value.amount, value.note)

    @app.post("/api/tax-tags/{tag_id}/not-a-write-off")
    def not_a_write_off(tag_id: int):
        return TaxTags(store()).not_a_write_off(tag_id)

    @app.post("/api/tax-tags/{tag_id}/review")
    def review_tax_tag(tag_id: int, value: TaxTagReviewInput):
        return TaxTags(store()).review(tag_id, value.status, value.rule_words)

    @app.get("/api/tax/rules")
    def tax_rules():
        return {"rules": TaxTags(store()).rules()}

    @app.post("/api/tax/rules", status_code=201)
    def add_tax_rule(value: TaxRuleInput):
        return TaxTags(store()).add_rule(value.pattern, value.kind, value.line, value.business_id, value.account_id)

    @app.put("/api/tax/rules/{rule_id}")
    def update_tax_rule(rule_id: int, value: TaxRuleInput):
        return TaxTags(store()).update_rule(rule_id, value.pattern, value.kind, value.line, value.business_id, value.account_id)

    @app.delete("/api/tax/rules/{rule_id}")
    def delete_tax_rule(rule_id: int):
        return TaxTags(store()).delete_rule(rule_id)

    @app.get("/api/tax/write-offs/{year}")
    def write_offs(year: int, currency: str = Query("USD", pattern=r"^[A-Z]{3}$")):
        if not 1990 <= year <= 2100:
            raise ValueError("Choose a tax year between 1990 and 2100.")
        return TaxTags(store()).year(year, currency)

    # The year's return, worked out by the tax engine (finance/tax_year.py, finance/tax_engine.py).
    def tax_year_value(year):
        if not 1990 <= year <= 2100:
            raise ValueError("Choose a tax year between 1990 and 2100.")
        return year

    @app.get("/api/tax/year/{year}")
    def tax_year(year: int):
        # Its figures carry their trace refs, and the result is remembered as shown (finance/traces.py shown_tax).
        return traces.shown_tax(store(), manager().tax_year(tax_year_value(year), seen=True))

    @app.put("/api/tax/year/{year}")
    def save_tax_year(year: int, value: dict):
        year = tax_year_value(year)
        TaxYears(store()).save(year, value, gathered=manager().gathered_tax_year(year))
        return traces.shown_tax(store(), manager().tax_year(year, seen=True))

    @app.get("/api/tax/year/{year}/changes")
    def tax_year_changes(year: int, key: str | None = None):
        """What was typed over the records' values, newest first (tax_input_changes)."""
        return TaxYears(store()).changes(tax_year_value(year), key=key)

    # The family's returns: who files together, and each return's estimate and Tax Zen (finance/tax_family.py).
    def family_only():
        if not manager().family:
            raise ValueError("Open the family profile to see the family's returns.")
        return store()

    @app.get("/api/tax/family/{year}")
    def family_tax(year: int):
        family_only()
        return traces.shown_family_tax(store(), manager().family_tax(tax_year_value(year), seen=True))

    @app.put("/api/tax/family/{year}/{unit_id}")
    def save_family_tax(year: int, unit_id: int, value: dict):
        TaxYears(family_only()).save(tax_year_value(year), value, f"unit-{unit_id}")
        return traces.shown_family_tax(store(), manager().family_tax(year, seen=True))

    # The year-end CPA pack (finance/cpa_pack.py): built only on the user's request, kept under Reports, never overwritten.
    @app.get("/api/tax/cpa-packs")
    def cpa_packs(year: int | None = Query(None, ge=1990, le=2100)):
        store()
        return {"packs": manager().cpa_packs(year)}

    @app.post("/api/tax/cpa-packs/{year}", status_code=201)
    def build_cpa_pack(year: int):
        store()
        return manager().build_cpa_pack(tax_year_value(year))

    @app.get("/api/tax/cpa-packs/{pack_id}/file")
    def cpa_pack_file(pack_id: int):
        store()
        path, name = manager().cpa_pack_file(pack_id)
        return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=name)

    # Donating checked documents for model evaluation (documents/donations.py): labels only, never ledger changes.
    @app.get("/api/donations")
    def donations():
        store()
        service = manager().donations()
        return {"candidates": service.candidates(), "checks": service.checks()}

    @app.post("/api/donations/checks", status_code=201)
    def start_donation_check(value: DonationStart):
        store()
        return manager().donations().start(value.record_type, value.record_id)

    @app.get("/api/donations/checks/{check_id}")
    def donation_check(check_id: int):
        store()
        return manager().donations().get(check_id)

    @app.put("/api/donations/checks/{check_id}")
    def save_donation_check(check_id: int, value: DonationAnswers):
        store()
        return manager().donations().save(check_id, {name: field.model_dump() for name, field in value.fields.items()}, value.rows,
                                          value.rows_state, value.rows_complete, value.source_kind,
                                          [box.model_dump() for box in value.redactions] if value.redactions is not None else None, value.finish)

    @app.post("/api/donations/checks/{check_id}/reopen")
    def reopen_donation_check(check_id: int):
        store()
        return manager().donations().reopen(check_id)

    @app.delete("/api/donations/checks/{check_id}", status_code=204)
    def delete_donation_check(check_id: int):
        store()
        manager().donations().delete(check_id)

    @app.get("/api/donations/checks/{check_id}/pages/{number}")
    def donation_page(check_id: int, number: int):
        store()
        return FileResponse(manager().donations().page(check_id, number), media_type="image/png")

    @app.post("/api/donations/bundles", status_code=201)
    def export_donation(value: DonationExport):
        store()
        return manager().donations().export(value.check_ids, value.donor)

    @app.get("/api/donations/bundles/{name}")
    def donation_bundle(name: str):
        store()
        return FileResponse(manager().donations().bundle_file(name), media_type="application/zip", filename=name)

    # Exchange rates (finance/fx.py): the cache's state, and the user's Refresh rates.
    @app.get("/api/rates")
    def rate_status():
        store()
        return manager().rate_status()

    @app.post("/api/rates/refresh")
    def refresh_rates():
        store()
        return manager().refresh_rates()

    # Crypto market prices (finance/prices.py): off unless the household turns them on.
    @app.get("/api/prices")
    def price_status():
        store()
        return manager().price_status()

    @app.post("/api/prices/refresh")
    def refresh_prices():
        store()
        return manager().refresh_prices()

    @app.post("/api/tax/units", status_code=201)
    def add_tax_unit(value: TaxUnitInput):
        family_only()
        return manager().add_tax_unit(value.name, value.members, value.filing_status)

    @app.delete("/api/tax/units/{unit_id}")
    def delete_tax_unit(unit_id: int):
        return TaxUnits(family_only()).delete(unit_id)

    # A plan put to use: its set spending as budgets, then compared with what happened.
    @app.get("/api/scenarios/{scenario_id}/budgets")
    def plan_budgets(scenario_id: int, month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
        store()
        return manager().plan_budgets(scenario_id, month)

    @app.post("/api/scenarios/{scenario_id}/adopt")
    def adopt_plan(scenario_id: int, value: AdoptInput):
        store()
        return manager().adopt_plan(scenario_id, value.month)

    @app.post("/api/scenarios/{scenario_id}/stop")
    def stop_plan(scenario_id: int):
        store()
        return manager().stop_plan(scenario_id)

    @app.get("/api/scenarios/{scenario_id}/actual")
    def plan_vs_actual(scenario_id: int):
        store()
        return manager().plan_vs_actual(scenario_id)

    @app.post("/api/tax-tables/{table_id}/review")
    def review_tax_table(table_id: int, value: TaxTableReviewInput):
        store()
        return manager().tax_tables.tables.review(table_id, value.status)

    @app.patch("/api/finance/records/{record_type}/{record_id}")
    def correct_record(record_type: RecordType, record_id: int, value: CorrectionInput, member: str | None = Query(None, pattern=r"^[0-9a-f]{12}$")):
        if member and manager().family:  # The family ledger: the change travels to the member (finance/family_corrections.py).
            return {"record": manager().correct_family_record(member, record_type, record_id, value.changes)}
        store()  # Otherwise this profile's own records (in the family view, the family's inbox).
        return manager().correct_record(record_type, record_id, value.changes, value.reason)

    @app.post("/api/finance/family-corrections/{key}/reject")
    def reject_family_correction(key: str = PathParam(pattern=r"^[0-9a-f]{32}$")):
        return manager().reject_family_correction(key)

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

    @app.post("/api/decision-model-tests")
    def decision_model_test(value: DecisionConfig):
        return manager().test_decision_model(value)

    @app.put("/api/model-computer")
    def model_computer(value: ModelComputerInput):
        return manager().configure_model_computer(ModelComputer(**value.model_dump(exclude={"token"})), value.token)

    @app.post("/api/model-computer-tests")
    def model_computer_test():
        return manager().test_model_computer()

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

    @app.get("/api/assets")
    def assets(include_archived: bool = False):
        return Assets(store()).list(include_archived)

    @app.post("/api/assets", status_code=201)
    def add_asset(value: AssetInput):
        return Assets(store()).add(value)

    @app.put("/api/assets/{asset_id}")
    def update_asset(asset_id: int, value: AssetInput):
        return Assets(store()).update(asset_id, value)

    @app.delete("/api/assets/{asset_id}")
    def archive_asset(asset_id: int):
        return Assets(store()).archive(asset_id)

    # Investments (docs/planning.md "Investments"): accounts, their values over time, and statement values to confirm.
    @app.get("/api/investment-kinds")
    def investment_kinds():
        return Investments(store()).kinds()

    @app.get("/api/investments")
    def investments(include_archived: bool = False):
        return Investments(store()).summary(include_archived)

    @app.post("/api/investments", status_code=201)
    def add_investment(value: InvestmentAccountInput):
        return Investments(store()).add(value)

    @app.get("/api/investments/review")
    def investment_values_to_review():
        return Investments(store()).pending()

    # Observability (docs/ui.md "Redesign: calculation observability"): how a figure was worked out, where a value came
    # from, the rule sets figures rest on, and the history of changes.
    @app.get("/api/traces/{ref:path}")
    def figure_trace(ref: str):
        return traces.trace(store(), ref, manager())

    @app.get("/api/provenance/{record_type}/{record_id}")
    def record_provenance(record_type: Literal["statement", "transaction", "receipt", "bill", "income_record", "investment_valuation", "tax_form", "holding"],
                          record_id: int, field: str | None = Query(None, max_length=60)):
        with store().connection() as db:
            return provenance_for(db, record_type, record_id, field)

    @app.get("/api/rule-sources")
    def rule_sources():
        return rules.sources(store())

    @app.get("/api/finance/budgets/history")
    def budget_history(category: str = Query(min_length=1, max_length=60), currency: str = Query(pattern=r"^[A-Za-z]{3}$")):
        return manager().ledger.budget_history(category, currency)

    @app.post("/api/finance/transactions", status_code=201)
    def add_transaction(value: ManualTransactionInput):
        store()
        return manager().add_manual_transaction(value)

    @app.post("/api/investments/valuations/{valuation_id}/correction")
    def correct_valuation(valuation_id: int, value: ValueCorrectionInput):
        return Investments(store()).correct_valuation(valuation_id, value.value, value.reason)

    @app.post("/api/investments/tax-forms/{form_id}/boxes/correction")
    def correct_tax_form_box(form_id: int, value: BoxCorrectionInput):
        return Investments(store()).correct_tax_form_box(form_id, value.form, value.box, value.value, value.reason)

    @app.post("/api/investments/holdings/{holding_id}/correction")
    def correct_holding(holding_id: int, value: HoldingCorrectionInput):
        return Investments(store()).correct_holding(holding_id, value.field, value.value, value.as_of, value.reason)

    @app.get("/api/review/counts")
    def review_counts():
        """What waits in Review, counted once here for the sidebar badge, with no list limits: each group's count and the
        total, and the inventory check-in's (lots to answer plus waiting), or null when it can't be worked out."""
        library, owner = store(), manager()
        queue = owner.tools.review_queue()
        statement_assets = [asset for asset in Assets(library).list() if asset["source"] == "statement" and asset["review_status"] == "proposed"]
        groups = {"issue": len(queue["issues"]), "link": len(queue["links"]), "record": len(queue["records"]),
                  "asset": len(statement_assets) + len(Investments(library).pending()),
                  "warranty": len(owner.warranties.warranties.list(status="proposed")),
                  "tax_table": len(owner.tax_tables.tables.list("proposed")), "tax_tag": len(TaxTags(library).list("proposed")),
                  "recurring": sum(row["status"] == "proposed" for row in owner.tools.get_recurring_obligations()["obligations"]),
                  "item": owner.items.ledger.resolution_count("proposed")}
        try:
            found = owner.items.ledger.checkin(owner.household.checkin_weekday)
            checkin = len(found["lots"]) + found["waiting"]
        except (ValueError, sqlite3.Error):
            checkin = None
        return {"groups": groups, "total": sum(groups.values()), "checkin": checkin}

    @app.get("/api/investments/ibond-rates")
    def ibond_rates():
        return Investments(store()).ibond_rate_table()

    @app.put("/api/investments/ibond-rates")
    def set_ibond_rate(value: IbondRateInput):
        return Investments(store()).set_ibond_rate(value)

    @app.post("/api/investments/events/{event_id}/qualified")
    def classify_investment_withdrawal(event_id: int, value: WithdrawalKind):
        return Investments(store()).classify_withdrawal(event_id, value)

    @app.get("/api/investments/valuations/{valuation_id}")
    def investment_valuation(valuation_id: int):
        return Investments(store()).valuation(valuation_id)

    @app.get("/api/investments/valuations/by-asset/{asset_id}")
    def investment_valuation_by_asset(asset_id: int):
        return Investments(store()).valuation(legacy_asset_id=asset_id)

    @app.post("/api/investments/valuations/{valuation_id}/review")
    def review_investment_valuation(valuation_id: int, value: AssetReviewInput):
        return Investments(store()).review(valuation_id, value.status)

    @app.get("/api/investments/confirmations/{confirmation_id}")
    def investment_confirmation(confirmation_id: int):
        return Investments(store()).confirmation(confirmation_id)

    @app.post("/api/investments/confirmations/{confirmation_id}/review")
    def review_investment_confirmation(confirmation_id: int, value: AssetReviewInput):
        return Investments(store()).review_confirmation(confirmation_id, value.status)

    @app.get("/api/investments/rmd")
    def investment_rmd(year: int | None = None):
        """This year's (or a chosen year's) required minimum distributions, from the profile's birth year."""
        return Investments(store()).required_distributions(year or date.today().year, manager().household.birth_year)

    @app.get("/api/investments/tax-forms/{form_id}")
    def investment_tax_form(form_id: int):
        return Investments(store()).tax_form(form_id)

    @app.post("/api/investments/tax-forms/{form_id}/review")
    def review_investment_tax_form(form_id: int, value: AssetReviewInput):
        return Investments(store()).review_tax_form(form_id, value.status)

    @app.get("/api/investments/tax-years/{year}")
    def investment_tax_year(year: int):
        if not 1990 <= year <= 2100:
            raise ValueError("Choose a tax year between 1990 and 2100.")
        return Investments(store()).tax_year(year)

    @app.post("/api/investments/events/{event_id}/unlink")
    def unlink_investment_payment(event_id: int):
        return Reconciler(store()).unlink_investment(event_id)

    @app.post("/api/investments/holdings/{holding_id}/lots", status_code=201)
    def add_investment_lot(holding_id: int, value: LotInput):
        return Investments(store()).add_lot(holding_id, value)

    @app.delete("/api/investments/lots/{lot_id}")
    def delete_investment_lot(lot_id: int):
        return Investments(store()).delete_lot(lot_id)

    @app.put("/api/investments/holdings/{holding_id}")
    def update_investment_holding(holding_id: int, value: HoldingInput):
        return Investments(store()).update_holding(holding_id, value)

    @app.delete("/api/investments/holdings/{holding_id}")
    def archive_investment_holding(holding_id: int):
        return Investments(store()).archive_holding(holding_id)

    @app.post("/api/investments/holdings/{holding_id}/matured")
    def investment_holding_matured(holding_id: int, value: MaturedInput):
        return Investments(store()).mark_matured(holding_id, value)

    @app.get("/api/investments/{account_id}")
    def investment(account_id: int):
        return Investments(store()).get(account_id)

    @app.put("/api/investments/{account_id}")
    def update_investment(account_id: int, value: AccountUpdate):
        return Investments(store()).update(account_id, value)

    @app.delete("/api/investments/{account_id}")
    def archive_investment(account_id: int):
        return Investments(store()).archive(account_id)

    @app.post("/api/investments/{account_id}/values")
    def record_investment_value(account_id: int, value: ValueInput):
        return Investments(store()).record_value(account_id, value)

    @app.post("/api/investments/{account_id}/holdings", status_code=201)
    def add_investment_holding(account_id: int, value: HoldingInput):
        return Investments(store()).add_holding(account_id, value)

    @app.post("/api/investments/{account_id}/payroll")
    def choose_investment_payroll(account_id: int, value: PayrollChoice):
        return Investments(store()).choose_payroll_account(account_id, value.employer_id)

    @app.put("/api/investments/{account_id}/pension")
    def set_investment_pension(account_id: int, value: PensionInput):
        return Investments(store()).set_pension(account_id, value)

    @app.post("/api/investments/{account_id}/events", status_code=201)
    def add_investment_event(account_id: int, value: EventInput):
        return Investments(store()).add_event(account_id, value)

    @app.post("/api/investments/{account_id}/crypto-import", status_code=201)
    def import_crypto(account_id: int, value: CryptoImportInput):
        return Investments(store()).import_crypto(account_id, value.document_id, value.expected_hash, value.preset)

    @app.post("/api/forecast")
    def run_forecast(value: ForecastInput):
        from ..finance.charts import forecast_charts
        result = forecast(store(), value, birth_year=manager().household.birth_year)
        return {**result, "charts": forecast_charts(result)}

    @app.post("/api/shares", status_code=202)
    def create_share(value: ShareInput):
        return manager().start_share_export(value.destination, value.passphrase, value.label)

    @app.get("/api/shares/{share_id}")
    def share_status(share_id: str):
        return manager().share(share_id)

    @app.post("/api/sessions", status_code=202)
    def open_session(value: SessionInput):
        return manager().start_session(value.share_file, value.passphrase)

    @app.delete("/api/sessions/current")
    def end_session():
        return manager().end_session()

    @app.post("/api/assistant-runs", status_code=202)
    def ask(value: QuestionInput):
        return manager().start_assistant(value.question, value.context)

    @app.get("/api/assistant-runs")
    def assistant_runs(limit: int = Query(20, ge=1, le=200)):
        store()
        return manager().assistant.history(limit)

    @app.get("/api/assistant-runs/{run_id}")
    def assistant_run(run_id: str):
        store()
        return manager().assistant.get(run_id)

    @app.post("/api/receipts/{receipt_id}/item-resolution-runs", status_code=202)
    def resolve_items(receipt_id: int):
        store()
        return manager().start_item_resolution(receipt_id)

    @app.get("/api/item-resolution-runs/{run_id}")
    def item_resolution_run(run_id: str):
        store()
        return manager().items.get(run_id)

    @app.get("/api/receipts/{receipt_id}/items")
    def receipt_lines(receipt_id: int):
        store()
        return manager().items.ledger.lines(receipt_id)

    @app.get("/api/items/resolutions")
    def item_resolutions(receipt_id: int | None = None, status: Literal["proposed", "verified", "rejected"] = "proposed",
                         limit: int = Query(200, ge=1, le=1000)):
        store()
        return manager().items.ledger.resolutions(receipt_id, status, limit)

    @app.post("/api/items/resolutions/{resolution_id}/review")
    def review_item(resolution_id: int, value: ItemReviewInput):
        store()
        return manager().items.ledger.review(resolution_id, value.status, value.edits)

    @app.get("/api/inventory")
    def inventory(query: str | None = Query(None, max_length=100), include_closed: bool = False, limit: int = Query(200, ge=1, le=1000)):
        store()
        owner = manager()
        lots = owner.items.ledger.inventory(query, include_closed, limit)
        warranties = {}
        for warranty in owner.warranties.warranties.list(lot_ids=[lot["id"] for lot in lots]):
            if warranty["review_status"] != "rejected":
                warranties.setdefault(warranty["lot_id"], []).append(warranty)
        return [{**lot, "warranties": warranties.get(lot["id"], []), "warranty_suggested": Warranties.suggested(lot)} for lot in lots]

    @app.post("/api/inventory/lots/{lot_id}/warranties", status_code=201)
    def add_warranty(lot_id: int, value: WarrantyInput):
        store()
        return manager().warranties.warranties.add(lot_id, value.kind, value.months, value.lifetime, value.note)

    @app.get("/api/warranties")
    def warranties(status: Literal["proposed", "verified", "rejected"] | None = None):
        store()
        return manager().warranties.warranties.list(status=status)

    @app.get("/api/warranties/expiring")
    def expiring_warranties(days: int = Query(60, ge=1, le=365)):
        store()
        return manager().warranties.warranties.expiring(days)

    @app.post("/api/warranties/{warranty_id}/review")
    def review_warranty(warranty_id: int, value: WarrantyReviewInput):
        store()
        return manager().warranties.warranties.review(warranty_id, value.status)

    @app.delete("/api/warranties/{warranty_id}")
    def delete_warranty(warranty_id: int):
        store()
        return manager().warranties.warranties.delete(warranty_id)

    @app.post("/api/inventory/lots/{lot_id}/warranty-lookups", status_code=202)
    def lookup_warranty(lot_id: int):
        store()
        return manager().start_warranty_lookup(lot_id)

    @app.get("/api/warranty-lookups/{run_id}")
    def warranty_lookup(run_id: str):
        store()
        return manager().warranties.get(run_id)

    @app.post("/api/inventory/lots/{lot_id}/events")
    def lot_event(lot_id: int, value: LotEventInput):
        store()
        return manager().items.ledger.update_lot(lot_id, value.event, value.effective_on, value.precision_days)

    @app.post("/api/inventory/lots/{lot_id}/undo")
    def undo_lot(lot_id: int):
        store()
        return manager().items.ledger.undo_lot(lot_id)

    @app.get("/api/inventory/lots/{lot_id}/history")
    def lot_history(lot_id: int):
        store()
        return manager().items.ledger.lot_history(lot_id)

    @app.get("/api/inventory/checkin")
    def checkin():
        store()
        owner = manager()
        return {**owner.items.ledger.checkin(owner.household.checkin_weekday), "weekday": owner.household.checkin_weekday}

    @app.post("/api/inventory/lots/{lot_id}/checkin-answer")
    def checkin_answer(lot_id: int, value: CheckinAnswerInput):
        store()
        return manager().items.ledger.answer(lot_id, value.answer, value.source)

    @app.post("/api/inventory/checkin-runs", status_code=202)
    def checkin_text(value: CheckinTextInput):
        store()
        return manager().start_checkin_text(value.answer)

    @app.get("/api/inventory/checkin-runs/{run_id}")
    def checkin_run(run_id: str):
        store()
        return manager().checkins.get(run_id)

    @app.post("/api/inventory/checkin-runs/{run_id}/apply")
    def apply_checkin(run_id: str, value: CheckinApplyInput):
        store()
        return manager().checkins.apply(run_id, value.lot_ids)

    @app.get("/api/inventory/returned")
    def returned_items():
        store()
        return manager().items.ledger.return_proposals()

    @app.post("/api/inventory/returned/{receipt_item_id}")
    def review_returned(receipt_item_id: int, value: LotReturnInput):
        store()
        return manager().items.ledger.review_return(receipt_item_id, value.lot_id)

    @app.get("/api/inventory/receipts-to-identify")
    def receipts_to_identify(limit: int = Query(20, ge=1, le=100)):
        store()
        return manager().items.ledger.receipts_to_identify(limit)

    @app.get("/api/inventory/returns")
    def returns_closing(days: int = Query(14, ge=1, le=90)):
        store()
        return manager().items.ledger.returns_closing(days)

    @app.get("/api/return-policies")
    def return_policies():
        store()
        return manager().items.ledger.policies()

    @app.put("/api/return-policies")
    def set_return_policy(value: PolicyInput):
        store()
        return manager().items.ledger.set_policy(value.merchant, value.days, value.note)

    @app.delete("/api/return-policies/{policy_id}")
    def delete_return_policy(policy_id: int):
        store()
        return manager().items.ledger.delete_policy(policy_id)

    @app.post("/api/assets/{asset_id}/review")
    def review_asset(asset_id: int, value: AssetReviewInput):
        return Assets(store()).review(asset_id, value.status)

    @app.get("/api/search")
    def search(q: str = Query(min_length=1, max_length=100), limit: int = Query(6, ge=1, le=50)):
        """The first matches across documents, transactions, household items and accounts, with each kind's total."""
        from ..finance.tools import TransactionsInput
        owner, text = manager(), " ".join(q.split())
        library = store().documents(limit=limit, query=text, sort="date")
        transactions = owner.tools.get_transactions(TransactionsInput(query=text, statuses=["counted", "pending", "rejected"], limit=limit))
        items = owner.items.ledger.inventory(text, include_closed=True, limit=200)
        words = text.lower().split()
        accounts = [account for account in owner.ledger.accounts() if all(word in f"{account['display_name']} {account['institution']}".lower() for word in words)]
        return {"query": text, "total": library["total"] + transactions["total_matching"] + len(items) + len(accounts),
                "documents": {"total": library["total"], "items": library["items"]},
                "transactions": {"total": transactions["total_matching"], "items": transactions["transactions"]},
                "inventory": {"total": len(items), "items": items[:limit]},
                "accounts": {"total": len(accounts), "items": accounts[:limit]}}

    @app.get("/api/finance/category-rules")
    def category_rules():
        store()
        return manager().ledger.rules()

    @app.post("/api/finance/category-rules", status_code=201)
    def add_rule(value: RuleInput):
        store()
        return manager().ledger.add_rule(value.pattern, value.category, value.account_id)

    @app.put("/api/finance/category-rules/{rule_id}")
    def update_rule(rule_id: int, value: RuleInput):
        store()
        return manager().ledger.update_rule(rule_id, value.pattern, value.category, value.account_id)

    @app.delete("/api/finance/category-rules/{rule_id}")
    def delete_rule(rule_id: int):
        store()
        return manager().ledger.delete_rule(rule_id)

    @app.get("/api/finance/budgets")
    def budgets():
        store()
        return manager().ledger.budgets()

    @app.put("/api/finance/budgets")
    def set_budget(value: BudgetInput):
        store()
        return manager().ledger.set_budget(value.category, value.currency, value.amount)

    @app.delete("/api/finance/budgets/{budget_id}")
    def delete_budget(budget_id: int):
        store()
        return manager().ledger.delete_budget(budget_id)

    @app.get("/api/model-runs")
    def model_runs(limit: int = Query(50, ge=1, le=200), task: str | None = Query(None, max_length=40), status: str | None = Query(None, max_length=20)):
        return store().model_runs(limit=limit, task=task, status=status)

    @app.get("/api/model-runs/facets")
    def model_run_facets():
        return store().model_run_facets()

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
                  date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), category: str | None = Query(None, max_length=40),
                  scope: Literal["money", "documents"] | None = None, employer: int | None = Query(None, ge=1),
                  section: Literal["Paystubs", "Documents"] | None = None):
        return store().documents(offset, limit, folder, status, q, sort, date_from, date_to, category, scope, employer, section)

    @app.get("/api/documents/{document_id}")
    def document(document_id: int):
        return store().document(document_id)

    @app.put("/api/documents/{document_id}/description")
    def describe_document(document_id: int, value: DescriptionInput):
        return store().set_description(document_id, value.description)

    @app.get("/api/folders")
    def folders(scope: Literal["money", "documents"] | None = None):
        return store().folders(scope)

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
    def receipt_image(document_id: int, blob_hash: str | None = Query(None, pattern=r"^[a-f0-9]{64}$"),
                      member: str | None = Query(None, pattern=r"^[0-9a-f]{12}$")):
        def media(relative_path):
            suffix = extension(relative_path)
            if suffix not in IMAGES | {".pdf"}:
                raise HTTPException(400, "Only PNG/JPEG and PDF previews are available.")
            return "application/pdf" if suffix == ".pdf" else "image/png" if suffix == ".png" else "image/jpeg"

        if member:  # The family view: a member's document, from the family computer (Manager.family_original).
            media_type, chunks = manager().family_original(member, document_id, blob_hash, media)
            return StreamingResponse(chunks, media_type=media_type)
        document, selected = store().document_version(document_id, blob_hash)
        media_type = media(document["relative_path"])
        path = store().blob_path(selected["hash"])
        if digest_file(path) != selected["hash"]:
            raise HTTPException(409, "Preserved document failed its integrity check.")
        return FileResponse(path, media_type=media_type)

    return app
