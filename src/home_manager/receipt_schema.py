"""Transcription evidence, with compatibility for historical OCR and field results."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .folders import HistoricalFolder

# Legacy defaults allow historical results to remain readable. New published runs
# explicitly set the vision parser version and transcription method.
PARSER_VERSION = "receipt-ocr-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TextBlock(StrictModel):
    id: str
    text: str = Field(max_length=16384)
    confidence: float = Field(ge=0, le=1)
    polygon: list[tuple[float, float]] = Field(min_length=4, max_length=4)


class TextLine(StrictModel):
    id: str
    text: str = Field(max_length=32768)
    block_ids: list[str]


class CodeEvidence(StrictModel):
    id: str
    format: str
    text: str = Field(max_length=65536)
    bytes_base64: str = Field(max_length=131072)
    valid: bool
    error: str | None = None
    polygon: list[tuple[float, float]] = Field(min_length=4, max_length=4)


class Issue(StrictModel):
    code: str
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


class Candidate(StrictModel):
    name: str
    value: str | None = None
    raw_text: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["proposed", "missing", "ambiguous"]
    note: str = "Unreviewed extraction; not an authoritative financial record."


class ReceiptFields(StrictModel):
    date: Candidate
    currency: Candidate
    total: Candidate
    components: list[Candidate] = Field(default_factory=list)
    calculation_status: Literal["matches", "mismatch", "incomplete"] = "incomplete"
    calculated_total: str | None = None
    difference: str | None = None
    calculation_note: str


def code_transcript(codes) -> str:
    """Decoded QR/barcode payloads appended verbatim after the visible text."""
    return "".join(f"\n\n[{code.id}: {code.format}; {'decoded' if code.valid else 'decode error'}]\n{code.text}" for code in codes)


class ReceiptResult(StrictModel):
    schema_version: Literal[1] = 1
    parser_version: str = PARSER_VERSION
    transcription_method: Literal["ocr", "vision_model"] = "ocr"
    title: str | None = Field(default=None, min_length=1, max_length=160)
    folder: HistoricalFolder | None = None
    model_text: str | None = Field(default=None, max_length=1_000_000)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    image_format: Literal["PNG", "JPEG"]
    original_width: int = Field(gt=0, le=40000)
    original_height: int = Field(gt=0, le=40000)
    width: int = Field(gt=0, le=40000)
    height: int = Field(gt=0, le=40000)
    exif_orientation: int | None = None
    clockwise_rotation: Literal[0, 90, 180, 270] = 0
    coordinate_space: Literal["oriented_preview_pixels"] = "oriented_preview_pixels"
    engine: dict[str, str]
    model_hashes: dict[str, str]
    blocks: list[TextBlock] = Field(max_length=5000)
    lines: list[TextLine] = Field(max_length=5000)
    ocr_text: str = Field(max_length=1_000_000)
    codes: list[CodeEvidence] = Field(max_length=100)
    extracted_text: str = Field(max_length=2_000_000)
    fields: ReceiptFields | None = None
    issues: list[Issue] = Field(max_length=1000)
    coverage: Literal["full_image_attempted_not_verified"] = "full_image_attempted_not_verified"

    @model_validator(mode="after")
    def evidence_consistent(self):
        blocks = {block.id: block for block in self.blocks}
        if len(blocks) != len(self.blocks) or len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("Duplicate evidence identifiers.")
        referenced = [key for line in self.lines for key in line.block_ids]
        if sorted(referenced) != sorted(blocks):
            raise ValueError("Every recognized block must occur exactly once in the complete text.")
        for line in self.lines:
            if self.transcription_method == "ocr" and line.text != " ".join(blocks[key].text for key in line.block_ids):
                raise ValueError("Text differs from preserved OCR evidence.")
        text = self.model_text if self.transcription_method == "vision_model" else self.ocr_text
        if self.transcription_method == "vision_model" and (self.blocks or self.ocr_text):
            raise ValueError("Vision output must not invent OCR regions/scores.")
        if text != "\n".join(line.text for line in self.lines):
            raise ValueError("Incomplete transcription text.")
        if self.extracted_text != text + code_transcript(self.codes):
            raise ValueError("Complete extraction must retain every recognized line and code payload.")
        ids = set(blocks) | {line.id for line in self.lines} | {code.id for code in self.codes}
        for candidate in ([self.fields.date, self.fields.currency, self.fields.total, *self.fields.components] if self.fields else []):
            if not set(candidate.evidence_ids) <= ids:
                raise ValueError("Candidate cites nonexistent evidence.")
        for evidence in [*self.blocks, *self.codes]:
            if any(x < 0 or y < 0 or x > self.width or y > self.height for x, y in evidence.polygon):
                raise ValueError("Evidence coordinates exceed image dimensions.")
        return self
