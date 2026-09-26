# Warranties, automatic item identification, UI Phases E and F

Plan and record (2026-09-25). Migration 025. Status: implemented (`warranty.py`, `static/processing.js`, `static/assistant.js`).

## 1. Warranties

Warranties apply to durable items (products not marked "runs out"). Items costing at least 100 in
the currency's main unit (a bed, a computer) are *suggested* for a warranty lookup; any durable
item can have one entered by hand.

**Data.** `warranties`: one row per lot and kind (manufacturer, store or extended), with months or
lifetime, start (purchase date) and end, source (`user` or `lookup`), the source page's title, URL
and quote, and review status. A warranty the user enters counts at once; a looked-up one is
*proposed* until confirmed in Review ("Warranties to confirm").

**Lookup.** A short agent run on the inference queue with web search (Brave, as for item names):
`get_item`, `web_search`, `open_result`, `find_in_page`, `propose_warranty`. Queries may not
contain prices, dates, long numbers or the store location. A proposal must quote the opened page
exactly, the quote must mention a warranty or guarantee, and the months proposed must be stated in
the quote ("1-year", "12 months", "two year", "lifetime"). Anything else is refused and returned
to the model. Without a search key or a reasoning model, lookup is unavailable and entering a
warranty by hand still works.

**Shown** on the Inventory row ("Warranty until …"), with a Home card for warranties ending within
60 days.

## 2. Automatic item identification

When a receipt is recorded (by the Inbox pipeline or Extract to ledger) and the new setting
**Identify receipt items automatically** is on (default on), the item resolver runs on that
receipt's lines in the same model job. Known aliases and barcodes resolve without the model; the
rest use the model and, when a search key is set, web search. Every result is still a proposal in
Review.

## 3. Phase E: Processing and Settings

**Processing:** pipeline lanes (Capture, Transcription, Extraction, Item identification,
Reconciliation), each with its live state and last run; one job history across every kind of
work (B11) with a kind filter and links to documents; the last reconciliation with its counts
(B10); model runs filtered by task and status on the server.

**Settings:** **Test connection** for the vision and reasoning models (B12), listing the served
model IDs; a **Backup & restore** section (B13): back up to a separate folder with history, and
restore a backup into a new library folder with live status. The privacy statement no longer says
backup is unavailable. Household preferences add the automatic identification switch.

## 4. Phase F: the assistant panel

A right-side panel from anywhere (**Ask** in the sidebar, <kbd>Ctrl</kbd>+<kbd>J</kbd>). The current
page (its name and filters) is sent with the question as context, labelled as data. Answers render
in the secondary text style, never as large figures. Each cited tool call becomes an evidence chip
("From spending · Sep 1 – Sep 30") that opens the matching page and filter. Unverified figures are
flagged, missing evidence is listed, and "How I got this" shows every tool call with its arguments.
Earlier questions are listed and can be reopened.

## Verification

`tests/test_warranties.py` (validation of proposals, months parsing, manual entry, review, agent
run with fake search and model), automatic identification after extraction, job history kinds,
model-run filters, assistant context. Browser tests for Processing, Settings and the panel.
The free-text check-in could not be exercised against a real local model in this session (no
model server was running); it remains covered by the synthetic model server.
