# Scanned receipt reader and local vision batches

Implemented first: PNG/JPEG receipts. CSV exports, Excel workbooks, scanned bills and PDF statements remain required subsequent readers. The capture allowlist currently includes CSV/XLSX/PNG/JPEG; PDF capture and parsing are not implemented yet.

## Manual testing

Restart the server after updating. Open the private launch link printed by `python -m home_manager`.

1. Place receipt images in the configured source directory under `YYYY/MM`, then select **Scan documents**. Previously preserved images need no new scan.
2. Start your local vision server with an image-capable model, initially Qwen3.5-9B. Under **gear → Settings → Local model**, save the API base URL (LM Studio usually `http://127.0.0.1:1234/v1`) and exact model ID. Saving does not download/load a model or test connectivity. The server must support image input and `json_schema` structured output on `/chat/completions`.
3. Newly scanned images are now organized automatically when the model is configured and the automatic-organization setting is enabled. For existing captures, press **Parse and organize all images**. This queues the latest active preserved PNG/JPEG version across all folders/pages/months, excluding Trash. Requests run sequentially. CSV/XLSX remain unparsed until their readers exist.
4. Generated titles and folder assignments appear in the folder browser with unchanged source paths. **Inspect document** opens the saved transcription, decoded codes and financial suggestions. Individual **Parse receipt** uses the configured model too. Leave the model ID empty only to use legacy OCR for individual receipts. See [library organization and Trash](library-browser.md).
5. Compare the image with **Complete extracted text**, including the footer, merchant details and any decoded QR/barcode payload. The prompt requests all text without filtering relevance. Codes are decoded separately and displayed as inert text; URLs are never followed.
6. Inspect proposed date, currency, total and detected subtotal/tax/tip/fee/discount components. Vision results offer **Find in transcription**; only legacy OCR has text-region polygons and **Highlight source**. No image coordinates or confidence scores are invented for model text. Arithmetic uses Python Decimal. A matching sum does not establish correctness.
7. Try an unclear or rotated scan using the individual inspector. **Create new parsing run**, or the batch **Reprocess previously completed receipts** checkbox, forces reprocessing. Ordinary batches reuse matching completed/partial results; failed/interrupted results are retried. Identical bytes share one request/result even when found at multiple paths. Batches use rotation zero; use the inspector for images requiring a manual rotation.

The full-text field retains the complete returned transcription plus independently decoded code text. Models can omit, hallucinate or reorder text, and long images may be downscaled by the inference server. An incomplete/token-truncated or invalid JSON response fails explicitly without replacing earlier results. The model is instructed to mark unreadable spans, which produce partial results. A succeeded run means processing completed, never financial verification. Actual accuracy on household receipts is not established by synthetic integration tests.

## Data and implementation boundaries

The source remains unchanged. Parsing reads the captured hash-verified blob. `parse_runs` stores status/results; batch tables retain snapshots. Schema 4 adds library folders/Trash and scan-organization state, with a backup before upgrading existing stores. `extracted/<run-id>/` stores preview and extraction artifacts. Do not downgrade code against an upgraded store or manually edit these artifacts.

Vision results include complete returned text, generated title, line references, model ID, endpoint, prompt/parser version and generation settings. The server's actual model weight hash is not available from this API; changing weights under the same ID requires explicit reprocessing. QR results retain exact bytes and polygons. Source hash, dimensions and rotation are retained. Legacy OCR additionally records text polygons, scores and model hashes. Anchors and titles belong to a specific run/source hash. A changed source version never inherits an older title. Previous successful titles remain available when a later run fails.

The vision path prepares the image and decodes codes with zxing-cpp in a bounded subprocess, then calls the configured local API from the coordinator. It does not run RapidOCR first or silently fall back to OCR after model failure. Bundled RapidOCR remains available for individual receipts with no model configured. English labels remain the financial-field baseline; broader layouts/languages need evaluation.

Financial fields remain conservative label-based suggestions from the transcription; model-based financial interpretation is a later stage. Ambiguous dates/currencies/totals remain unresolved and missing tax/tip is not invented. Judge evaluation, currency conversion, ledger posting and editable review remain future work.

## Limits and security

One capture or batch/individual parsing operation runs at a time. Image preparation limits: one PNG/JPEG frame, 24 megapixels, 40,000 pixels per side, 180 seconds, 2 GiB per Windows worker process and four processes per job. Model requests have a 300-second socket timeout, 16 MiB image limit, 8,192 output-token budget and 4 MiB response limit. Model-server VRAM limits are managed by the inference runtime, not by the image-worker Job Object. Artifacts are limited to 64 MiB preview, 4 MiB final JSON and 2 GiB total extracted storage. Legacy OCR uses overlapping tiles; the model receives the complete oriented image. No silent application-side resizing occurs. Storage cleanup is not yet in the UI.

Batch state survives restart; interrupted batches are surfaced rather than automatically resumed. Press the batch button again to reuse completed results and retry interrupted work. The browser may close while the server continues. Normal server shutdown currently waits for queued work; force termination is recovered on restart.

Workers receive a minimal environment without application tokens; the parent validates output and owns SQLite. Windows Job Objects limit image-worker resources. **This is resource isolation, not an OS security sandbox:** restricted Windows identity/ACL/network confinement remains future hardening. The vision adapter accepts only explicit `http://127.0.0.1:PORT/v1` URLs, bypasses proxy environment variables, rejects redirects and sends image bytes as a data URL. It never follows document links or gives model output tools/file access. Local model servers must themselves be configured for local-only processing/logging. Only synthetic documents are used in automated tests.

Image and result API endpoints require the current local session token. The UI displays extracted content as text, not executable HTML. Originals, OCR output, previews and database backups all contain private information and need the same local disk/backup protection.

## Validation

The vision-v3 adapter sends an explicit JSON schema for title, full text and the allowed folder names, matching LM Studio's documented structured-output interface. HTTP failures show a status code and a safe diagnostic category; raw server error bodies are not stored because they may echo private document text. If the request fails, inspect the model server's actual error after the request log. A received POST only establishes connectivity, not successful image decoding or generation. Restart Home Manager after adapter updates before retrying.

Tests cover OCR preservation, real QR decoding, HTTP image payloads to a synthetic loopback model server, invalid/truncated model responses, redirect rejection, auth, batch failures/reuse/recovery, title versioning and migrations. The optional Edge test exercises model configuration, the batch button, title/path display and Inspect receipt. No real model or private receipt is required by these tests; model accuracy remains a separate manual evaluation.
