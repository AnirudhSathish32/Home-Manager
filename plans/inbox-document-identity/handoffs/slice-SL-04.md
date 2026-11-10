```yaml
slice: SL-04
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 919567e
end_head: HEAD_PLACEHOLDER   # a following commit changes only this header
commit: HEAD_PLACEHOLDER
changed_files:
  - docs/documents.md
  - docs/development.md
  - docs/open-work.md
  - tests/test_document_v2_browser.py
checks:
  - command: ".venv/bin/python -m pytest --browser tests/test_document_v2_browser.py -k split -p no:cacheprovider -q"
    exit_code: 0   # 1 passed, 9 deselected; msedge launched headless here
  - command: ".venv/bin/python -m pytest tests/test_document_split.py -p no:cacheprovider -q"
    exit_code: 0   # 17 passed
  - command: ".venv/bin/ruff check tests/test_document_v2_browser.py"
    exit_code: 1   # one I001, the inner `import uuid` / `from datetime import datetime` in _newer_reading, which is not mine (it fails the same at START_HEAD); my import block is clean
escalations: []
```

# SL-04 handoff: docs and the opt-in browser checkpoint (FR-10)

The full suite was not run (the orchestrator does that once).

## Changes
- `docs/documents.md` "The managed library": the sentence "still one document with several versions until the repair is built" is gone. Added a bullet saying only an edit to a file still in the Inbox is a version, and a bullet on the one-time upgrade (migration 080): the earliest file keeps the id, every record follows its file, Trash is kept on every piece, a failed upgrade leaves the library as it was, the Library copies are renamed to their own id on the next start and never overwrite.
- `docs/development.md`: `document_splits.py` added to the `scripts/` list; 080 added to the schema map (heading renamed to "Account names, reading links and split documents (078 – 080)"; no citation uses that heading); `scripts/document_splits.py` described under "Database checks" (read-only, four count lines, the user runs it, exact `.\.venv\Scripts\python.exe` command).
- `docs/open-work.md`: the item "Split the documents already merged under one Inbox name" is removed; added the OD-2 item (a watched folder's file overwritten in place is still a new version).
- `tests/test_document_v2_browser.py`: `test_split_documents_open_without_an_earlier_version_banner` (`-k split`) with a `split_server` context manager. It builds `merged_library(tmp_path, standard())` from `tests/test_document_split.py`, upgrades by reopening, then serves it with `create_app` + `manager.configure`. It checks that B's document page is titled "Paystub 09/15/2026", shows B's hash and has an empty version banner, and that opening the statement row's evidence (`/api/finance/records/transaction/<row>` → `#/documents/<id>?version=<hash>`, the link `finance.js` builds) gives A's statement with A's hash and no banner.

## Notes for the verifier
- The test imports `merged_library, open_db, reopened, standard` from `test_document_split`; pytest does not collect them as tests there.
- The page title (`#doc2-title`) is what carries B's record. `#doc2-record-title` always reads "Recorded information" on these synthetic (unread-by-a-model) files, so it is not used.
- The docs cite `docs/documents.md "The managed library"` unchanged; no heading in `documents.md` changed.
- Not touched: spec, contract, plan, reviews.md, progress.yaml (its pre-existing modification is not in the commit), approvals/, migration 080, managed_library.py, scripts/document_splits.py, other features' untracked files.

## Open issues
None.
