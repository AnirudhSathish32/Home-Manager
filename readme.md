## readme

Home Manager is a local-first household document and financial assistant in development.

D1–D2 and PNG/JPEG receipt reading are implemented: preserve documents from `YYYY/MM` folders, then batch-transcribe receipts with a configured local vision model. Generated titles appear alongside source paths; the inspector shows full returned text, decoded QR codes and provisional financial fields. Legacy OCR remains available. Financial posting and CSV/Excel/PDF readers follow separately.

From PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m home_manager
```

Open the private loopback link printed in the terminal. Use the top-right **gear → Settings → Directories** to choose your source and managed folders, then open the **Scan documents** tab. See [manual testing and operation](docs/manual-testing.md) for setup and recovery behavior.

Run tests with `.\.venv\Scripts\python.exe -m pytest -q`.

In **Settings → Local model**, save the running local server's URL and model ID. New scanned PNG/JPEG documents are automatically transcribed, titled and assigned to the folder hierarchy under **Inspect documents**. Use **Parse and organize all images** for existing files. Documents can be moved manually or deleted to a restorable Trash after confirmation. Source files stay unchanged. See [the folder browser](docs/library-browser.md) and [receipt parsing](docs/receipt-parsing.md) for details. The app does not download/load model weights.

Planning: [architecture](docs/architecture.md), [document reading](docs/document-reading.md), [milestones](docs/milestones.md).
