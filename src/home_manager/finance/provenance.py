"""Where a value came from (docs/ui.md "Redesign: calculation observability", "Provenance on every input").

provenance_for(db, record_type, record_id, field) answers, for one record (or one of its fields):
- imported: the file and row it was read from, deterministically;
- manual: entered on a page, by whom and when;
- extracted: read by a model: which model and run, the document, the cited lines, the quote and the page (from the line
  id), and whether the independent check doubted it (documents/extraction.py assess);
- override: changed by a person after that: the original, the new value, who, when and why (record_corrections).
Its verification is one of the three states in core/trace.py: confirmed, checked_automatically or needs_review.
"""

import json
import re

from .ledger import RECORD_TABLES

TABLES = {**RECORD_TABLES, "investment_valuation": "investment_valuations", "tax_form": "tax_forms", "holding": "holdings"}
PAGE = re.compile(r"^page-(\d+)-")
# The independent check names a header field by its name and a row by "row N" (documents/extraction.py assess).
CHECK_LABELS = {"merchant": "merchant", "provider": "provider", "payer": "payer"}


def light(record_type, record_id, origin=None, kind=None):
    """A trace input's provenance: its kind and the record (the page fetches the full one with provenance_for). origin is
    a transaction's (import, manual or extraction); kind names it outright (manual, extracted, rate, computed, rule)."""
    return {"kind": kind or {"import": "imported", "manual": "manual"}.get(origin, "extracted"), "record": {"type": record_type, "id": record_id}}


def page_of(line_id):
    """The page a cited line is on: "page-2-line-7" is page 2; a one-page document's lines ("line-7") are page 1."""
    found = PAGE.match(line_id or "")
    return int(found.group(1)) if found else 1


def verification_of(row):
    """The record's state: needs_review until a person or the automatic checks accept it; imported and entered rows
    are confirmed (docs/ui.md: confirmed means a person confirmed it, or it was imported)."""
    keys = row.keys()
    status = row["review_status"] if "review_status" in keys else row["status"] if "status" in keys else "verified"
    if "origin" in keys and row["origin"] in ("import", "manual"):
        return "confirmed"
    if status in ("proposed", "needs_review"):
        return "needs_review"
    if "review_source" in keys and row["review_source"] == "automatic":
        return "checked_automatically"
    return "confirmed"


def _extraction(db, row, record_type, record_id, field):
    """The model, run, cited lines, quote and the independent check's view of one extracted value."""
    run_id = row["extraction_run_id"] if "extraction_run_id" in row.keys() else None
    run = db.execute("SELECT * FROM extraction_runs WHERE id=?", (run_id,)).fetchone() if run_id else None
    found = {}
    if run is not None:
        model = db.execute("SELECT model_id FROM model_identities WHERE fingerprint=?", (run["model_identity"],)).fetchone() if run["model_identity"] else None
        found["model"] = {"id": model["model_id"] if model else None, "run": run["id"], "at": run["updated_at"]}
    result = json.loads(run["result_json"]) if run is not None and run["result_json"] else {}
    header = (result.get("header") or {}).get(field) if field else None
    cites = header.get("evidence", []) if isinstance(header, dict) else []
    if not cites:  # The record's own citations (its evidence link), when the field has none of its own.
        link = db.execute("SELECT locator_json FROM financial_evidence_links WHERE record_type=? AND record_id=? AND source_key LIKE 'extraction:%' "
                          "ORDER BY id DESC LIMIT 1", (record_type, record_id)).fetchone() if record_type in RECORD_TABLES else None
        locator = json.loads(link["locator_json"]) if link else {}
        cites = [{"line_id": line, "quote": quote} for line, quote in zip(locator.get("line_ids", []), locator.get("quotes", []) or [None] * 40)]
    lines = [cite["line_id"] for cite in cites if cite.get("line_id")]
    document_id = row["document_id"] if "document_id" in row.keys() else None
    found["document"] = {"id": document_id, "lines": lines, "quote": next((cite["quote"] for cite in cites if cite.get("quote")), None),
                         "page": page_of(lines[0]) if lines else None}
    check = result.get("decision") or result.get("laya")
    label = CHECK_LABELS.get(field, field)
    doubt = next((item for item in (check or {}).get("checks", []) if item.get("field") == label), None) if field else None
    found["confidence"] = None if doubt is None or doubt.get("supported") is None else {
        "level": "unchallenged" if doubt["supported"] else "doubted", "by": "independent check"}
    return found


def provenance_for(db, record_type, record_id, field=None):
    """The provenance of a record, or of one of its fields, in the trace contract's shape."""
    table = TABLES.get(record_type)
    if table is None:
        raise ValueError(f"No provenance for {record_type} records.")
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise ValueError("Record not found.")
    keys = row.keys()
    found = {"kind": None, "document": None, "model": None, "confidence": None, "import": None, "actor": None, "override": None}
    origin = row["origin"] if "origin" in keys else None
    source = row["source"] if "source" in keys else None
    if origin == "import":
        link = db.execute("SELECT e.locator_json,o.relative_path FROM financial_evidence_links e JOIN occurrences o ON o.id=e.document_id "
                          "WHERE e.record_type=? AND e.record_id=? ORDER BY e.id LIMIT 1", (record_type, record_id)).fetchone()
        rows = json.loads(link["locator_json"]).get("rows", []) if link else []
        found.update(kind="imported", **{"import": {"file": link["relative_path"].replace("\\", "/").rsplit("/", 1)[-1] if link else None,
                                                    "row": rows[0] if rows else None}})
    elif origin == "manual" or source == "manual":
        found.update(kind="manual", actor={"person": row["actor"] if "actor" in keys else None, "at": row["created_at"]})
    elif source == "quote":  # A market price times the units held (finance/prices.py).
        found.update(kind="rate")
    else:
        found.update(kind="extracted", **_extraction(db, row, record_type, record_id, field))
    corrections = db.execute("SELECT * FROM record_corrections WHERE record_type=? AND record_id=? AND (? IS NULL OR field=?) ORDER BY id",
                             ("tax_form_box" if record_type == "tax_form" else record_type, record_id, field, field)).fetchall()
    if corrections:
        first, last = corrections[0], corrections[-1]
        found["kind"] = "override"
        found["override"] = {"original": first["previous"], "value": last["value"], "field": last["field"], "reason": last["reason"],
                             "actor": {"person": last["actor"], "at": last["created_at"]}, "count": len(corrections)}
    return {"provenance": found, "verification": verification_of(row)}
