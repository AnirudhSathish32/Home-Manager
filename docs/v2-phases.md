# V2 Phases 2–8: implementation notes

Implemented from `Home_Manager_Architecture_Implementation_Spec.docx` (sections 4–15, 20–23) on top of the Phase 1 [managed library](managed-library.md). Restart Home Manager to apply schema migrations 010–014; an existing store receives one SQLite-consistent `inventory.before-v14.sqlite3` snapshot first.

## Phase 2 — telemetry, queues, cancellation

- **Model telemetry** (`model_runs`, migration 010): every model request records task, owner run, model ID, server-reported model identity, prompt version, time to first token, prompt/completion tokens, generation rate, total model time, bytes and finish reason — including failed and cancelled requests. Server `timings`/`usage` are used when reported; otherwise the rate is estimated from characters and labelled `estimated`. Shown under **Processing → Model runs** and per run in the inspector.
- **Model identity**: a fingerprint of the server's `/v1/models` entry (plus LM Studio's `/api/v0/models/{id}` details when available). Completed transcriptions, analyses and extractions are reused only for the same identity. If the server cannot identify the model, nothing is reused. Servers do not expose file hashes, so identity is metadata-based.
- **Queues**: capture (filesystem) and inference (model, concurrency 1) run independently. Browsing, moving, importing, reviewing and settings other than directories/models work while a model generates.
- **Cancellation**: the sidebar activity indicator and **Processing → Now running** offer **Cancel**. The worker is released immediately (the HTTP exchange runs on a helper thread because Windows cannot interrupt a blocked receive during prompt processing); the socket is shut down so the server stops at its next token; the image-preparation child is killed. Cancelled runs are marked `cancelled` and never publish.

## Phase 3 — PDF ingestion

Page-aware reading with embedded text where a page has a usable text layer, vision only for scanned/near-empty pages, `page-N-line-M` evidence IDs, no silent page omission, and chunked analysis. A pypdfium2 incompatibility that made every PDF fail was fixed; mixed digital/scanned PDFs are now covered by tests.

## Phase 4 — canonical finance store

Accounts (last four digits only), merchants, statements, transactions, receipts and items, bills, income records, recurring obligations, evidence links and review history (migration 011). Money is integer minor units plus an ISO currency; database checks reject floating-point values. Review states are `proposed`, `needs_review`, `verified`, `rejected`. Transactions are de-duplicated by a source-independent fingerprint (account, date, amount, currency, ordinal among equal entries), so a CSV row and the same statement row are one transaction, while two equal purchases on one day stay distinct.

## Phase 5 — classifier and type-specific extraction

**Extract to ledger** in the inspector classifies the document, then extracts only its type's schema (receipt, bank statement, credit-card statement, bill, income) in bounded chunks with task-specific output limits. Deterministic checks: every citation is an exact quote, every amount is printed in its cited line, names appear in their citation, dates are unambiguous ISO, currency is explicit (or taken from a known account for statements), and document arithmetic reconciles (receipt totals, item sums, statement opening/closing balances, pay stubs). A failed chunk is corrected on its own. Problems mark records `needs_review`; a missing currency blocks publication. Records the user already reviewed are never overwritten. Inbox auto-processing now uses this path; the older **Analyze financial details** remains an optional audit analysis under History.

## Phase 6 — CSV/XLSX import

**Import transactions** on a CSV/XLSX row previews and imports from the preserved copy: column mapping (detected or chosen), date order (inferred only when the whole column is unambiguous), sign convention, explicit rejected-row reasons. XLSX is read with the standard library under size/ratio limits, without DOCTYPE processing or formula evaluation. Re-importing never duplicates.

## Phase 7 — reconciliation

Runs after each import and extraction (or **Reconcile now**): receipt ↔ transaction by exact amount, posting window and merchant; transfers and card payments between owned accounts (excluded from spending); refunds to their purchases; steady-cadence recurring payments. Scores are integer rule points, not probabilities. Several plausible matches create an open issue and no link; rejected links are never re-proposed.

## Phase 8 — deterministic tools

`POST /api/finance/tools/{name}` with typed arguments: accounts, statement balances (dated, never a guessed live balance), transactions, spending, spending by category, period comparison, cash flow, recurring obligations, upcoming bills, receipts, purchases, statements, receipt match candidates, refunds (a refund document is not settled until a posted credit is linked) and the review queue. Totals are per currency with explicit coverage; model-extracted rows count only after verification and are otherwise reported as pending. The **Finances** tab presents these results.

## Not implemented (updated 2026-09-24)

Phase 10 (email ingestion, Laya evaluation) is deferred until the classifier has been benchmarked on real documents. Currency conversion remains open.

Since added (see `ui-design-plan.md` §7): backup to a separate destination and verified restore into a new library (section 19), and a first Phase 9 assistant that answers only through the read-only tools, with figure checks against the cited results. The spec's caution still applies: judge the assistant against real records before relying on it.

## Laya, in-process (advisory)

```text
                         HOME MANAGER
              ┌───────────────┴───────────────┐
       Laya Python SDK                  LM Studio API
       same process                     127.0.0.1
      classification /                 generative models
      scoring / routing                VLM / reasoning
```

Laya runs inside Home Manager through the `laya` SDK (`pip install -e .[laya]`); there is no laya-serve HTTP server. Install the weights once with `home-manager --install-laya`: it downloads `convaiinnovations/laya` at pinned revision `55cf4c4ebb4e` (about 850 MB, Apache-2.0) to `%LOCALAPPDATA%\HomeManager\models\laya`, verifying TLS against the Windows certificate store. The LM Studio `laya_english_q8_0.gguf` file is not used; the SDK needs the safetensors checkpoint.

**Privacy.** The SDK source contains no telemetry. Its only network paths are Hugging Face downloads and an optional laya-serve client that Home Manager never imports. Before loading, Home Manager sets `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` and `HF_HUB_DISABLE_TELEMETRY`; an opt-in test (`RUN_LAYA_TESTS=1`) loads and scores with all socket connections blocked.

**Use.** When the weights are installed, every ledger extraction runs Laya automatically: a shadow classification plus a support score for every proposed value and row. It acts only as a veto: a value it cannot confirm sends the record to review with a reason; it never approves a record, and its classification is shown for reference only. The Independent checks setting now chooses the checker for audit analyses.

**Exception-based review (2026-09-24).** An extracted record counts in your finances automatically ("Checked automatically") when every deterministic check passes: its required fields are present (a receipt's merchant, date and total), at least one arithmetic cross-check ran and agreed (subtotal, tax and tip equal the total, or items equal the subtotal; statement balances reconcile), nothing was ambiguous or dropped, and Laya doubted nothing. Anything else goes to Needs review with the reasons listed. Correcting a field with Edit details clears the reasons about it; when none remain, the record passes. Only the user's own decisions stop a later extraction from rewriting a record.

**Why only a veto.** The checkpoint warns that some temperatures are uncalibrated. On the household's Target receipts it scored exact totals correctly (0.94 for the printed total, 0.03 for a wrong one) but gave a correct footer-derived merchant 0.17 and classified a receipt as a bill with 95% confidence. Per the spec, it earns routing or gating authority only after a benchmark on real documents.
