"""Donation checks and bundles: field-by-field labels for the private eval corpus, never ledger changes."""

import io
import json
import zipfile

from PIL import Image
import pytest

from home_manager.core.answers import Answers, empty_answers
from test_extraction import classification, extract, identity, receipt, receipt_items, receipt_summary  # noqa: F401

DESCRIBE = {"description": "Coffee", "category": None, "recurrence": None, "item_categories": []}


@pytest.fixture
def extracted(receipt, local_model):  # noqa: F811
    manager, doc, parse_id = receipt
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), DESCRIBE, {"rewards": []}]
    run = extract(manager, doc, parse_id)
    assert run["status"] == "succeeded", run["error"]
    return manager, run["publication"]["id"]


def bundle_files(manager, exported):
    path = manager.donations().bundle_file(exported["name"])
    with zipfile.ZipFile(path) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


def test_a_check_starts_from_the_proposal_saves_typed_answers_and_exports_a_bundle(extracted):
    manager, receipt_id = extracted
    donations = manager.donations()
    assert [(row["record_type"], row["id"], row["check_id"]) for row in donations.candidates()] == [("receipt", receipt_id, None)]
    check = donations.start("receipt", receipt_id)
    assert donations.start("receipt", receipt_id)["id"] == check["id"]  # One check per record and content version.
    fields = {field["name"]: field for field in check["fields"]}
    assert fields["total_minor"]["value"] == 2500 and fields["total_minor"]["display"] == "25.00 USD" and fields["total_minor"]["input"] == "25.00"
    assert fields["merchant"]["proposed"] == "Local Test Cafe" and all(field["state"] == "unchecked" for field in check["fields"])
    assert check["pages"] == 1 and check["status"] == "draft" and check["source_kind"] in ("phone_photo", "scan")
    assert [row["line_total_minor"]["value"] for row in check["rows"]] == [500, 500, 1000] and check["rows_state"] == "unchecked"
    with pytest.raises(ValueError, match="Finish checking"):
        donations.export([check["id"]])
    with pytest.raises(ValueError, match="at least one field"):
        donations.save(check["id"], {}, finish=True)
    with pytest.raises(ValueError, match="Total"):
        donations.save(check["id"], {"total_minor": {"text": "twenty five", "state": "fixed"}})
    rows = [{"description": row["description"]["input"], "line_total_minor": row["line_total_minor"]["input"]} for row in check["rows"]]
    saved = donations.save(check["id"], {"merchant": {"text": "Local Test Cafe Inc", "state": "fixed"}, "total_minor": {"text": "25.00", "state": "correct"},
                                         "tip_minor": {"text": "3.00", "state": "unchecked"}},
                           rows=rows, rows_state="correct", rows_complete=True, finish=True)
    assert saved["status"] == "checked" and {field["name"]: field["state"] for field in saved["fields"]}["merchant"] == "fixed"
    exported = donations.export([check["id"]], donor="d07")
    files = bundle_files(manager, exported)
    manifest = json.loads(files["manifest.json"])
    assert manifest["format"] == "home-manager-donation/1" and manifest["donor"] == "d07" and len(manifest["cases"]) == 1
    case = manifest["cases"][0]
    assert case["document_type"] == "receipt" and case["redacted"] is False and case["home_currency"] is None
    answers = Answers.model_validate_json(files[f"cases/{case['case_id']}/answers.json"])
    assert answers.checked_fields() == {"merchant": "Local Test Cafe Inc", "total_minor": 2500}
    assert answers.fields["tip_minor"].state == "unchecked" and answers.rows_complete is True and len(answers.rows) == 3
    # The original as preserved; the proposal is only the checked fields and rows, never quotes or locators.
    doc = manager.store.documents()["items"][0]
    assert files[case["original"]] == manager.store.blob_path(manager.store.document_version(doc["id"])[1]["hash"]).read_bytes()
    proposal = json.loads(files[f"cases/{case['case_id']}/proposal.json"])
    assert proposal["fields"]["merchant"] == "Local Test Cafe" and "locator" not in json.dumps(proposal)
    # A check never changes the ledger.
    assert manager.ledger.record("receipt", receipt_id)["merchant"] == "Local Test Cafe"
    assert set(files) == {"manifest.json", case["original"], f"cases/{case['case_id']}/answers.json", f"cases/{case['case_id']}/proposal.json"}


def test_redaction_boxes_are_burned_into_the_donated_copy(extracted):
    manager, receipt_id = extracted
    donations = manager.donations()
    check = donations.start("receipt", receipt_id)
    with pytest.raises(ValueError, match="outside its page"):
        donations.save(check["id"], {}, redactions=[{"page": 2, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}])
    with pytest.raises(ValueError, match="outside its page"):
        donations.save(check["id"], {}, redactions=[{"page": 1, "x": 0.9, "y": 0.1, "w": 0.5, "h": 0.2}])
    donations.save(check["id"], {"total_minor": {"text": "25.00", "state": "correct"}}, redactions=[{"page": 1, "x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}],
                   finish=True)
    files = bundle_files(manager, donations.export([check["id"]]))
    case = json.loads(files["manifest.json"])["cases"][0]
    assert case["redacted"] is True and case["original"].endswith(".png")
    image = Image.open(io.BytesIO(files[case["original"]])).convert("RGB")
    assert image.getpixel((image.width // 2, image.height // 2)) == (0, 0, 0)


def test_checks_can_be_reopened_and_deleted_and_bad_ids_are_refused(extracted):
    manager, receipt_id = extracted
    donations = manager.donations()
    check = donations.start("receipt", receipt_id)
    donations.save(check["id"], {"total_minor": {"text": "25.00", "state": "correct"}}, finish=True)
    assert donations.reopen(check["id"])["status"] == "draft"
    donations.delete(check["id"])
    assert donations.checks() == [] and not donations.folder(check["id"]).exists()
    with pytest.raises(ValueError, match="not found"):
        donations.get(check["id"])
    with pytest.raises(ValueError, match="donor ID"):
        donations.export([1], donor="Bad Name")
    with pytest.raises(ValueError, match="Unknown donation file"):
        donations.bundle_file("../inventory.sqlite3")
    with pytest.raises(ValueError, match="Only receipts"):
        donations.start("bill", 1)


def test_answers_validate_their_fields_and_rows():
    answers = empty_answers("receipt", {"merchant": "  Shop  ", "total_minor": 1200, "purchase_date": "22/09/2026", "items": [{"description": None, "line_total_minor": 5}]})
    assert answers.fields["merchant"].value == "Shop" and answers.fields["purchase_date"].value is None
    assert answers.rows == [{"description": "(no description)", "line_total_minor": 5}] and answers.rows_complete is None
    with pytest.raises(ValueError, match="exactly the critical fields"):
        Answers.model_validate({"document_type": "receipt", "fields": {"total_minor": {"value": 1, "state": "correct"}}})
    data = answers.model_dump()
    data["fields"]["total_minor"] = {"value": 12.5, "state": "correct"}
    with pytest.raises(ValueError):
        Answers.model_validate(data)
    data["fields"]["total_minor"] = {"value": 1250, "state": "correct"}
    data["rows"] = [{"description": "A", "line_total_minor": 1, "extra": 2}]
    with pytest.raises(ValueError, match="columns"):
        Answers.model_validate(data)
