# Image transcription with a local vision model

PNG/JPEG extraction uses the configured local vision model for every new run. It returns only `full_text`: visible wording in reading order, including line items and footers. RapidOCR, its runtime dependencies and label-based financial extraction have been removed. The separate [financial reasoning stage](financial-reasoning.md) now proposes titles, document types, financial facts and observations over saved text. Automatic filing and financial publication remain future work.

## Operation

1. Start a local image-capable server. In **Settings → Local model**, save its loopback URL and model ID. It must support streaming chat completions, image input and JSON-schema output. The app does not download or load weights.
2. Drop documents into Inbox. With automatic extraction enabled, newly captured PNG/JPEG images are transcribed sequentially. Without a model, capture still works; extraction requires configuration and never falls back to OCR.
3. Use **Processing → Read all documents** (or **Read selected** in Documents) for existing captures. Matching results are reused unless reprocessing is selected. The new prompt version causes older OCR/title/field runs to be transcribed anew. Identical bytes share one run.
4. Open the document page (select its name in Documents) to compare the complete returned transcription with the preserved image. Rotate and create a new reading under **History** when needed. Independently decoded QR/barcode payloads are appended as inert text; links are never followed.
5. Use **Move** for manual filing. New documents remain Unfiled until moved.

## Evidence and compatibility

Results retain source hash, dimensions, rotation, preview, full model text, line IDs, endpoint, model ID and prompt version. No text coordinates or confidence scores are invented. QR/barcodes retain exact bytes and polygons. New results have null `fields`, `title` and `folder` values. The inspector explains that interpretation is pending.

The reasoning stage consumes saved text and evidence IDs and persists an independent interpretation with the source run and model ID. It does not rewrite transcription. Citation and schema validation are implemented; approval, conversion and financial posting remain separate future stages.

Historical OCR and field suggestions remain readable through saved-run history. Compatibility schema fields do not enable OCR execution. Manual folder choices remain effective for their exact source version. Historical titles and automatic folders may remain visible until a newer successful transcription supersedes them. Originals never change.

For compatibility, `organize_after_scan` and scan `organization_*` API/database fields now govern/report automatic transcription only. The legacy organization endpoint returns an actionable error until separate reasoning exists; historical organization runs remain readable.

## Failure handling and limits

Blank/invalid output and interrupted or token-truncated streams fail without publishing partial text or replacing earlier successful evidence. `[unreadable]` and `[no visible text]` markers produce partial results for inspection. Success means processing completed, not verified accuracy. Synthetic tests validate plumbing and evidence preservation; actual model accuracy requires local evaluation.

Image preparation runs in a bounded child: one PNG/JPEG frame, 24 megapixels, 40,000 pixels per side, 180 seconds, and a 2 GiB Windows worker limit. Requests send the whole oriented preview without application-side resizing, with a 16 MiB image limit, 8,192 output tokens and 15 minutes without socket activity. Output limits are 64 MiB preview, 4 MiB JSON and 2 GiB total extraction artifacts. The model server manages its own memory.

Interrupted batches require retry after restart. The browser may close while server work continues. Workers have resource limits, not an OS security sandbox. Requests accept only `http://127.0.0.1:PORT/v1`, bypass proxies, reject redirects and expose no tools to the model. Originals, text, previews and backups remain private local data.
