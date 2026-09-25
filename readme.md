## readme

V2 Phase 1 adds an app-owned **Library/Inbox**, flat folders, physical managed copies, and recoverable filing. External source files remain read-only. See [managed-library setup and behavior](docs/managed-library.md).

Financial reasoning is available as a separate stage over saved vision text. Configure its model in **Settings → Local models**, then open a transcribed document and select **Analyze financial details**. Findings cite source lines and remain unreviewed. See [financial reasoning](docs/financial-reasoning.md).

Home Manager is a local-first household document and financial assistant in development.

D1–D2 and PNG/JPEG reading are implemented: preserve documents from `YYYY/MM` folders, then transcribe images with a configured local vision model. The inspector shows full returned text and decoded QR/barcodes. OCR and label-based fields have been removed. A separately configured reasoning model proposes financial facts, titles, document types and observations with source citations. Financial posting and CSV/Excel/PDF readers follow separately.

From PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m home_manager
```

Open the private loopback link printed in the terminal. Use **Settings → Library & sources** in the sidebar to choose your source and managed folders, then scan from **Processing**. See [manual testing and operation](docs/manual-testing.md) for setup and recovery behavior.

Run tests with `.\.venv\Scripts\python.exe -m pytest -q`.

In **Settings → Local models**, save the running local server's URL and model ID. New scanned images are automatically transcribed when automatic extraction is enabled. Use **Processing → Read all documents** (or **Read selected** in Documents) for existing files, **Import transactions** for CSV/XLSX exports, **Extract to ledger** on the document page (see [V2 phases](docs/v2-phases.md)), and **Move** for manual filing. Delete sends documents to restorable Trash after confirmation. Source files stay unchanged. See [the folder browser](docs/library-browser.md) and [image transcription](docs/receipt-parsing.md). The app does not download/load model weights.

Planning: [architecture](docs/architecture.md), [document reading](docs/document-reading.md), [milestones](docs/milestones.md).
