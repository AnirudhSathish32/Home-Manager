# Financial reasoning over saved text

This line-by-line interpretation (the former audit analysis) is no longer offered in the interface: typed extraction, the automatic checks and Laya do its job. The service and its API remain; ledger records come from typed extraction; see [v2-phases.md](v2-phases.md).

The reasoning stage consumes an exact saved vision transcription. It produces a proposed document title and type, financial facts, evidence-linked observations and limitations. It is separate from image extraction: running or retrying analysis does not call the vision model or change its output.

## Use

1. Restart Home Manager after updating the application.
2. In **Settings → Local models**, save the reasoning server URL and its exact model ID under **Reasoning model**. This selection is independent of the vision model. The endpoint must support streaming chat completions and JSON-schema output on loopback; no cloud fallback exists.
3. Request an analysis through the API (`POST /api/documents/{id}/reasoning-runs`); the interface no longer shows this step.
4. Select **Analyze financial details**. Use **Create a new analysis** to retry with the same configuration without reusing a successful result. Saved analyses remain selectable for that transcription.
5. Review the item table, totals and insights. Expand **View source**, then **Find in transcription** to open the extracted-text view at the cited line. Compare it with the original image as well.

Version 2 requires a separate row for every printed purchased item, including repeated products. Each row retains description, product code, quantity/weight, printed unit price, discount and printed line total where present. Missing values stay null. The model must account for every nonblank transcription line as item evidence or grouped non-item text; omitted lines and contradictory coverage statuses fail validation. This verifies line coverage, not semantic completeness: a model can still misclassify a line or misread a value. Uncertain itemization is marked partial.

Older analyses remain readable and show a prompt to create a new analysis for structured itemization. Selecting **Analyze financial details** with the new prompt version generates a fresh result without rerunning vision. Saved-analysis labels update as processing completes and preserve the selected history entry.

Version 3 explicitly distinguishes an unreviewed proposed value from an ambiguous value. Ambiguous/missing facts must have a null value. Metadata lines already cited by classification or non-item financial facts count as covered; they do not need duplicate entries in other_lines. Merchandise still requires item evidence or explicit line disposition. When a completed response fails schema, citation or item-coverage validation, the application makes at most one correction request to the same local model with specific validation feedback. The complete corrected result must pass all checks. Oversized responses, transport errors and truncated streams do not trigger correction. Final errors report safe field locations or omitted line IDs without quoting private values. Invalid intermediate responses are not persisted by the application; the local model server may retain its own request logs.

The application serializes vision and reasoning jobs through its existing worker. It does not manage model residency or unload weights. Configure the local server so model switching fits available VRAM; selecting a reasoning model does not require both models to remain resident.

## Evidence and limits

Each durable run retains its source parsing run ID, model ID, endpoint, prompt version, timestamps, status and final structured output. The parsing run identifies the preserved document hash and transcription settings. Schema migration 6 adds an independent table, with a database backup before upgrading an existing store. Interrupted analyses become retryable interrupted runs at startup.

The model proposes facts such as issuer, merchant, dates, currency, totals, taxes, fees, obligations, balances and transactions. Missing and ambiguous facts have null values. Observations may identify a payment due, fee, refund or possible recurring charge. This first stage operates on one document; it does not infer household trends, perform currency conversion, post transactions, approve records or automatically file documents.

Proposed facts and observations must cite existing transcription lines with exact text quotes. Invalid citations, invalid schemas and truncated/disconnected responses publish no analysis; older successful analyses remain available. Quote validation proves that cited text exists, not that a normalized value or observation is correct. All results remain unreviewed. A text model cannot detect vision transcription mistakes by inspecting pixels it never receives.

Input is capped at 64 KiB of serialized lines and extraction issues, without silent truncation. Output is capped at 8,192 tokens and uses the existing bounded streaming adapter. Large inputs may still exceed a model's token context; the server must have capacity for the actual input plus output. Financial values remain proposed strings, not authoritative numeric ledger entries. Provenance records the requested model ID and a server-reported model identity (see v2-phases.md); servers do not expose model file hashes.

Synthetic HTTP and browser tests cover the workflow. Accuracy and performance on the user's chosen reasoning model require a separate local evaluation.
