"""The corpus on disk: donors, their cases, and run results.

<corpus>/
  corpus.json                       format, the bundles already taken in, donors withdrawn
  donors/<donor>/cases/<case_id>/   original.<png|jpg|pdf>, answers.json, proposal.json, case.json
  results/<run_id>/                 run.json, results.jsonl, report.md, summary.json; outputs.jsonl with --keep-outputs

case.json holds what intake decided: status (pending until the collector has checked the answers a second time,
admitted, or dropped), split (dev cases may be used to tune prompts; test cases are frozen) and used_for_tuning.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from home_manager.core.answers import Answers

CORPUS_FORMAT = "home-manager-corpus/1"
CASE_FORMAT = "home-manager-case/1"
CASE_ID = re.compile(r"[0-9a-f]{16}")
# The edges a case tests (docs/evals.md). Synthetic cases carry them; the collector may add them to donated ones.
TAGS = ("long", "multi_page", "non_usd", "injection", "ambiguous_kind", "no_items", "duplicates", "date_format", "faded", "ytd")
DONOR_ID = re.compile(r"[a-z0-9-]{1,16}")
ORIGINALS = ("original.png", "original.jpg", "original.pdf")


class CaseInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["home-manager-case/1"] = CASE_FORMAT
    case_id: str
    donor: str
    bundle_id: str
    document_type: Literal["receipt", "bank_statement", "credit_card_statement", "paystub"]
    source_kind: Literal["phone_photo", "scan", "native_pdf", "image_pdf"]
    pages: int
    redacted: bool
    home_currency: str | None = None
    extraction_version: str | None = None
    status: Literal["pending", "admitted", "dropped"] = "pending"
    split: Literal["dev", "test"]
    used_for_tuning: bool = False
    added_at: str
    notes: str = ""
    tags: list[Literal["long", "multi_page", "non_usd", "injection", "ambiguous_kind", "no_items", "duplicates", "date_format", "faded", "ytd"]] = []


@dataclass
class Case:
    folder: Path
    info: CaseInfo

    @property
    def id(self):
        return self.info.case_id

    @property
    def original(self):
        for name in ORIGINALS:
            if (self.folder / name).is_file():
                return self.folder / name
        raise ValueError(f"Case {self.id} has no original.")

    def answers(self):
        return Answers.model_validate_json((self.folder / "answers.json").read_bytes())

    def save(self):
        write_json(self.folder / "case.json", self.info.model_dump())


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class Corpus:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @classmethod
    def create(cls, root):
        corpus = cls(root)
        corpus.root.mkdir(parents=True, exist_ok=True)
        if not corpus.manifest_path.exists():
            write_json(corpus.manifest_path, {"format": CORPUS_FORMAT, "bundles": [], "withdrawn": []})
        return corpus

    @property
    def manifest_path(self):
        return self.root / "corpus.json"

    def manifest(self):
        if not self.manifest_path.is_file():
            raise ValueError(f"{self.root} is not a corpus: corpus.json is missing. Create one with: python -m evals.intake init {self.root}")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != CORPUS_FORMAT:
            raise ValueError("Unknown corpus format.")
        return manifest

    def save_manifest(self, manifest):
        write_json(self.manifest_path, manifest)

    def case_folder(self, donor, case_id):
        if not DONOR_ID.fullmatch(donor) or not CASE_ID.fullmatch(case_id):
            raise ValueError("Invalid donor or case ID.")
        return self.root / "donors" / donor / "cases" / case_id

    def cases(self, statuses=("admitted",), split=None):
        """Every case in a stable order (donor, then case ID)."""
        self.manifest()
        found = []
        for path in sorted((self.root / "donors").glob("*/cases/*/case.json")):
            info = CaseInfo.model_validate_json(path.read_bytes())
            if info.status in statuses and (split in (None, "all") or info.split == split):
                found.append(Case(path.parent, info))
        return found

    def case(self, case_id):
        for path in (self.root / "donors").glob(f"*/cases/{case_id}/case.json"):
            return Case(path.parent, CaseInfo.model_validate_json(path.read_bytes()))
        raise ValueError(f"No case {case_id} in this corpus.")

    def results(self):
        return sorted(path for path in (self.root / "results").glob("*") if (path / "run.json").is_file())
