"use strict";
let receipt = null, receiptImageURL = null;

const setSourceTab = wireTabs(["source-image-tab", "source-text-tab"]);

const setDetailTab = wireTabs(["details-tab", "history-tab"]);
const PENDING_RUN = ["queued", "running"];

function receiptControls() {
  const ready = receipt?.result && !receipt.pending && !busy.inference && !receipt.doc.deleted_at && receipt.resultRunId === receipt.runId;
  $("extract-ledger").disabled = !ready;
  $("extract-ledger").textContent = $("extraction-state").dataset.status === "succeeded" ? "Extract again" : "Extract to ledger";
  $("parse-receipt").disabled = !receipt || busy.inference || Boolean(receipt?.doc.deleted_at) || Boolean(receipt?.pending);
  $("parse-receipt").textContent = receipt?.result ? "Read again" : "Read document";
  $("reparse-receipt").disabled = !receipt || busy.inference || Boolean(receipt?.doc.deleted_at);
  $("receipt-rotation").disabled = busy.inference;
  // Buttons in the record pane stand in for the step buttons and share their state.
  for (const button of document.querySelectorAll("#record-empty [data-proxy]")) button.disabled = $(button.dataset.proxy).disabled;
}
function closeReceipt() {
  receipt = null;
  if (receiptImageURL) { URL.revokeObjectURL(receiptImageURL); receiptImageURL = null; }
  $("receipt-image").removeAttribute("src");
  $("receipt-pdf").removeAttribute("src");
  $("receipt-pdf").hidden = true;
  $("receipt-image-frame").parentElement.hidden = false;
}
async function imageForReceipt(path, expected) {
  const response = await fetch(path, {headers:{"Authorization":`Bearer ${token}`}});
  if (!response.ok) { const data = await response.json(); throw new Error(data.detail || "Could not retrieve image."); }
  const blob = await response.blob();
  if (receipt !== expected) return;
  if (receiptImageURL) URL.revokeObjectURL(receiptImageURL);
  receiptImageURL = URL.createObjectURL(blob);
  const pdf = blob.type === "application/pdf";
  $("receipt-pdf").hidden = !pdf;
  $("receipt-image-frame").parentElement.hidden = pdf;
  $(pdf ? "receipt-pdf" : "receipt-image").src = receiptImageURL;
}
async function openDocument(id, version = null) {
  // Route entry point (#/documents/ID). Re-showing the same document keeps its state.
  if (receipt && receipt.doc.id === id && receipt.digest === (version || receipt.doc.current_hash)) {
    document.title = `${documentName(receipt.doc)} · Home Manager`; return;
  }
  const doc = await api(`/api/documents/${id}`);
  await openReceipt(doc, version || doc.current_hash);
}
function proxyButton(label, target, primary = false) {
  const button = element("button", label, primary ? "primary" : ""); button.type = "button"; button.dataset.proxy = target;
  button.disabled = $(target).disabled;
  button.addEventListener("click", () => $(target).click());
  return button;
}
function copyButton(text, label = "Copy") {
  const button = element("button", label, "small"); button.type = "button";
  button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; }
    catch { notice("Copying isn't available here. Select the text and press Ctrl+C.", true); }
  });
  return button;
}
function detailRow(list, label, ...values) {
  const value = document.createElement("dd");
  value.append(...values.map(item => item instanceof Node ? item : document.createTextNode(String(item))));
  list.append(element("dt", label), value);
}
const SOURCE_STATES = {present: "In Inbox, unchanged", missing: "No longer in Inbox", organized: "Moved from Inbox into the library"};
function renameInspector(doc) {
  // Set on open and after the user edits the description; loading results never rename the page.
  if (receipt) receipt.doc = {...receipt.doc, ...doc};
  $("receipt-title").textContent = documentName(doc);
  document.title = `${documentName(doc)} · Home Manager`;
  $("receipt-subtitle").textContent = [folderLabel(doc.folder), doc.document_date && dateText(doc.document_date), doc.title && fileName(doc)].filter(Boolean).join(" · ");
}
function renderDocumentHeader(state) {
  const doc = state.doc;
  $("document-state").replaceChildren(documentStateBadge(doc));
  const items = [actionButton("Edit description…", () => openDescription(state.doc)), actionButton(`Versions (${doc.version_count})`, () => showVersions(doc))];
  if (doc.deleted_at) items.push(actionButton("Restore", () => restoreDocuments([doc])));
  else items.push(actionButton("Move", () => openLibraryAction([doc], "move")), actionButton("Delete", () => openLibraryAction([doc], "trash"), "danger-text"));
  $("inspector-menu").replaceChildren(menu("More actions", items));
}
function renderDocumentDetails(state) {
  const doc = state.doc, list = $("document-details"); list.replaceChildren();
  detailRow(list, "Managed location", element("code", doc.managed_path ? `Library/${doc.managed_path}` : "Managed copy pending"));
  if (doc.managed_error) detailRow(list, "Filing problem", element("span", doc.managed_error, "item-warning"));
  detailRow(list, "Original source", element("code", doc.relative_path), element("small", SOURCE_STATES[doc.source_status] || statusLabel(doc.source_status)));
  detailRow(list, "Folder", folderLabel(doc.folder));
  detailRow(list, "Preserved version", element("code", state.digest), element("small", state.digest === doc.current_hash ? "Latest version" : "Earlier version"), copyButton(state.digest, "Copy hash"));
  detailRow(list, "Versions", String(doc.version_count));
}
async function refreshInspectorDoc(state = receipt) {
  // Keeps the header state current after actions; the title stays as set on open.
  if (!state) return;
  const doc = await api(`/api/documents/${state.doc.id}`);
  if (receipt !== state) return;
  state.doc = doc; renderDocumentHeader(state); renderDocumentDetails(state); receiptControls();
}
async function openReceipt(doc, digest = doc.current_hash) {
  closeReceipt();
  const state = {doc, digest, runId: "", pending: false, result: null, loaded: false, textStatus: "", textError: "", actionError: "", extraction: null};
  receipt = state;
  $("extraction-result").replaceChildren(); $("extraction-status").textContent = "";
  setStatusBadge($("extraction-state"), "not_extracted");
  setStatusBadge($("text-state"), "not_extracted"); $("text-step-note").textContent = "Reads the preserved copy locally.";
  document.querySelector(".source-extras").open = false;
  setDetailTab("details-tab"); setSourceTab("source-image-tab");
  // The title is set once from the best name available; loading never changes it.
  renameInspector(doc);
  const latest = element("a", "View the latest version"); latest.href = `#/documents/${doc.id}`;
  $("version-banner").replaceChildren(...(digest !== doc.current_hash ? [alertBox("You're viewing an earlier preserved version of this document.", {tone: "warning", action: latest})] : []));
  renderDocumentHeader(state); renderDocumentDetails(state);
  $("receipt-status").textContent = "Loading the preserved document.";
  $("receipt-rotation").value = "0";
  for (const id of ["receipt-codes", "receipt-issues", "receipt-overlay", "receipt-provenance", "pdf-page"]) $(id).replaceChildren();
  $("pdf-page-label").hidden = true;
  $("receipt-text").value = ""; $("receipt-telemetry").textContent = "";
  $("receipt-runs").replaceChildren(new Option("Not read yet", ""));
  renderRecordPane(state); receiptControls();
  await imageForReceipt(`/api/documents/${doc.id}/preview?blob_hash=${digest}`, state);
  await receiptHistory(state);
  if (receipt !== state) return;
  if (state.runId) await displayReceiptRun(state.runId, state);
  else {
    $("receipt-status").textContent = "Not read yet. Reading uses the preserved copy locally; the original stays unchanged.";
    state.loaded = true; renderRecordPane(state);
  }
}
async function receiptHistory(state) {
  const history = await api(`/api/documents/${state.doc.id}/receipt-runs?blob_hash=${state.digest}`);
  if (receipt !== state) return;
  const selector = $("receipt-runs"); selector.replaceChildren();
  if (!history.length) { selector.add(new Option("Not read yet", "")); return; }
  for (const run of history) {
    const rotation = JSON.parse(run.options_json).clockwise_rotation;
    selector.add(new Option(`${new Date(run.created_at).toLocaleString()} · ${statusLabel(run.status)} · ${rotation}°`, run.id));
  }
  if (!state.runId) state.runId = history[0].id;
  selector.value = state.runId;
}
function modelNote(text) {
  const note = element("p", `${text} `, "muted small"), link = element("a", "Set one up in Settings"); link.href = "#/settings";
  note.appendChild(link); return note;
}
function renderRecordPane(state) {
  // What the right pane says when there is no record to show yet, in the user's terms.
  if (receipt !== state) return;
  const parts = [], extraction = state.extraction;
  if (state.actionError) parts.push(alertBox(state.actionError, {tone: "error"}));
  if (!state.loaded) parts.push(element("p", "Loading the preserved document…", "muted"));
  else if (state.doc.deleted_at) parts.push(element("p", "This document is in Trash. Restore it from More actions to read or record it.", "muted"));
  else if (state.pending) parts.push(element("p", "Reading this document with the local vision model. Progress shows in the sidebar.", "muted"));
  else if (!state.result && ["failed", "interrupted"].includes(state.textStatus))
    parts.push(alertBox(`Home Manager couldn't read this document. ${state.textError || ""}`.trim(), {tone: "error", action: proxyButton("Try again", "parse-receipt", true)}));
  else if (!state.result) {
    const box = emptyState(state.textStatus === "cancelled" ? "Reading was cancelled before it finished." : "Home Manager hasn't read this document yet.", proxyButton("Read document", "parse-receipt", true));
    if (!modelsConfigured.vision) box.appendChild(modelNote("Reading needs a local vision model."));
    parts.push(box);
  } else if (extraction?.pending) parts.push(element("p", "Extracting this document to the ledger. Progress shows in the sidebar.", "muted"));
  else if (!extraction) {
    const box = emptyState("Read, but not recorded yet. Extracting checks every amount against its source line and records it for your review.", proxyButton("Extract to ledger", "extract-ledger", true));
    if (!modelsConfigured.reasoning) box.appendChild(modelNote("Extracting needs a local reasoning model."));
    parts.push(box);
  }
  else if (["failed", "interrupted"].includes(extraction.status))
    parts.push(alertBox(`Home Manager couldn't extract this document. ${extraction.error || ""}`.trim(), {tone: "error", action: proxyButton("Try again", "extract-ledger", true)}));
  else if (extraction.status === "cancelled") parts.push(emptyState("Extraction was cancelled before it finished.", proxyButton("Extract to ledger", "extract-ledger", true)));
  else if (!extraction.publication)
    parts.push(element("p", `Classified as ${(extraction.documentType || "an unknown document").replaceAll("_", " ")}, which has no ledger record. Nothing was recorded; use Move to file it.`, "muted"));
  else if (extraction.publication.status === "blocked") parts.push(alertBox(`Can't record this: ${extraction.publication.reason}`, {tone: "warning"}));
  $("record-empty").replaceChildren(...parts);
  const key = [state.textStatus, extraction?.status, state.pending].join(":");
  if (state.loaded && state.stateKey !== undefined && state.stateKey !== key) refreshInspectorDoc(state).catch(() => {});
  state.stateKey = key;
}
function highlightEvidence(ids) {
  if (!receipt?.result) return;
  if (["vision_model", "pdf_pages"].includes(receipt.result.transcription_method) && !ids.some(id => id.startsWith("code-"))) {
    const line = receipt.result.lines.find(line => ids.includes(line.id));
    if (line) {
      setSourceTab("source-text-tab");
      const index = receipt.result.lines.indexOf(line);
      const field = $("receipt-text"), start = receipt.result.lines.slice(0, index).reduce((offset, row) => offset + row.text.length + 1, 0);
      field.focus(); field.setSelectionRange(start, start + line.text.length);
    }
    return;
  }
  const wanted = new Set(ids);
  setSourceTab("source-image-tab");
  for (const line of receipt.result.lines) if (wanted.has(line.id)) for (const id of line.block_ids || []) wanted.add(id);
  for (const element of $("receipt-overlay").children) element.classList.toggle("selected", wanted.has(element.dataset.evidenceId));
}
function showCitingRows(blockId) {
  // Reverse lookup: from a region on the image to the recorded rows that cite it.
  const lines = new Set(receipt.result.lines.filter(line => (line.block_ids || []).includes(blockId)).map(line => line.id));
  let first = null;
  for (const row of document.querySelectorAll("#extraction-result tr[data-lines]")) {
    const cited = row.dataset.lines.split(" ").some(id => lines.has(id));
    row.classList.toggle("cited", cited);
    if (cited && !first) first = row;
  }
  first?.scrollIntoView({block: "nearest"});
}
const METHODS = {vision_model: "Local vision model", pdf_pages: "PDF pages (embedded text, vision for scanned pages)"};
function renderProvenance(result) {
  const list = $("receipt-provenance"); list.replaceChildren();
  const code = value => element("code", typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "—"));
  detailRow(list, "Method", METHODS[result.transcription_method] || String(result.transcription_method || "—"));
  if (result.pages) {
    detailRow(list, "Pages", result.pages.map(page => `Page ${page.number}: ${page.method}, ${page.lines.length} lines`).join(" · "));
    return;
  }
  for (const [label, value] of [["Engine", result.engine], ["Parser version", result.parser_version], ["Schema version", result.schema_version],
                                ["Input hash", result.input_hash], ["Model identity", result.model_hashes], ["Coverage", result.coverage],
                                ["Original size", `${result.original_width} × ${result.original_height}`], ["Preview size", `${result.width} × ${result.height}`],
                                ["EXIF orientation", result.exif_orientation], ["Rotation", `${result.clockwise_rotation}°`], ["Coordinates", result.coordinate_space]])
    if (value !== undefined) detailRow(list, label, code(value));
}
function renderReceipt(result) {
  renderProvenance(result);
  if (result.transcription_method === "pdf_pages") {
    $("receipt-text").value = result.lines.map(line => line.text).join("\n");
    $("receipt-issues").replaceChildren();
    // Page navigation: jump to a page's first line in the text.
    $("pdf-page").replaceChildren(...result.pages.map(page => new Option(`${page.number} of ${result.pages.length} · ${page.method}`, String(page.number))));
    $("pdf-page-label").hidden = result.pages.length < 2;
    return;
  }
  $("receipt-text").value = result.extracted_text;
  $("receipt-issues").replaceChildren();
  for (const issue of result.issues) {
    if (issue.code === "interpretation_pending") continue;
    const li = document.createElement("li"); li.textContent = issue.message; $("receipt-issues").appendChild(li);
  }
  $("receipt-codes").replaceChildren();
  if (!result.codes.length) $("receipt-codes").textContent = "No code decoded. A QR code may be absent or unreadable; check the image.";
  for (const code of result.codes) {
    const card = document.createElement("div"); card.className = "receipt-field";
    const title = document.createElement("strong"); title.textContent = `${code.format} · ${code.valid ? "decoded" : "decode error"}`;
    const text = document.createElement("pre"); text.textContent = code.text || "No text representation";
    const bytes = document.createElement("details"), summary = document.createElement("summary"), value = document.createElement("pre");
    summary.textContent = "Exact payload bytes (base64)"; value.textContent = code.bytes_base64; bytes.append(summary,value);
    const highlight = document.createElement("button"); highlight.type = "button"; highlight.textContent = "Highlight code";
    highlight.addEventListener("click", () => highlightEvidence([code.id]));
    card.append(title,text,bytes,highlight); $("receipt-codes").appendChild(card);
  }
  $("receipt-overlay").replaceChildren(); $("receipt-overlay").setAttribute("viewBox", `0 0 ${result.width} ${result.height}`);
  for (const block of [...result.blocks,...result.codes]) {
    const polygon = document.createElementNS("http://www.w3.org/2000/svg","polygon");
    polygon.setAttribute("points",block.polygon.map(pair => pair.join(",")).join(" ")); polygon.dataset.evidenceId = block.id;
    const title = document.createElementNS("http://www.w3.org/2000/svg","title"); title.textContent = block.text; polygon.appendChild(title);
    polygon.addEventListener("click", () => { highlightEvidence([block.id]); showCitingRows(block.id); });
    $("receipt-overlay").appendChild(polygon);
  }
}
function runTelemetry(run) {
  if (!run.model_runs?.length) return "No model requests recorded for this run.";
  const workflow = run.status === "queued" || run.status === "running" ? "in progress" : seconds(new Date(run.updated_at) - new Date(run.created_at));
  return `Model requests: ${run.model_runs.map(telemetryText).join("; ")}. Total workflow time (queued to finished): ${workflow}. Model identity: ${run.model_identity || "unavailable (results are not reused)"}.`;
}
async function displayReceiptRun(runId, state) {
  const run = await api(`/api/receipt-runs/${runId}`);
  if (receipt !== state || state.runId !== runId) return;
  state.pending = PENDING_RUN.includes(run.status);
  state.textStatus = run.status; state.textError = run.error || "";
  $("receipt-status").textContent = `${statusLabel(run.status)}${run.error ? ": " + run.error : ""}${run.result ? " · Unreviewed reading. Compare it with the document before relying on any field." : ""}${!run.result && state.result ? " · The previous completed reading stays displayed." : ""}`;
  if (run.result) {
    state.resultRunId = runId;
    state.result = run.result; renderReceipt(run.result);
    if (run.result.transcription_method !== "pdf_pages") await imageForReceipt(`/api/receipt-runs/${runId}/preview`,state);
  }
  $("receipt-telemetry").textContent = runTelemetry(run);
  setStatusBadge($("text-state"), run.status);
  $("text-step-note").textContent = run.error || (state.result ? "Text ready. Compare it with the image." : "Reads the preserved copy locally.");
  state.loaded = true; renderRecordPane(state);
  await loadExtraction(state, runId);
  receiptControls();
  await receiptHistory(state);
}
async function startReceipt(force) {
  if (!receipt) return;
  const state = receipt;
  try {
    busy.inference = true; controls(); state.actionError = "";
    const data = await api(`/api/documents/${state.doc.id}/receipt-runs`,{method:"POST",body:JSON.stringify({blob_hash:state.digest,clockwise_rotation:Number($("receipt-rotation").value),force})});
    if (receipt !== state) return;
    state.runId = data.run_id; state.pending = true;
    $("receipt-status").textContent = "Reading locally with the configured vision model. Image reading and QR/barcode decoding may take several minutes.";
    await displayReceiptRun(state.runId,state);
  } catch (error) {
    $("receipt-status").textContent = error.message; state.actionError = error.message; renderRecordPane(state);
    busy.inference = false; controls();
  }
}
async function pollReceipt() {
  const state = receipt;
  if (state?.pending && state.runId) await displayReceiptRun(state.runId,state);
  if (state?.runId && (state.extractionPending || busy.inference)) await loadExtraction(state, state.runId);
}
$("parse-receipt").addEventListener("click", () => startReceipt(Boolean(receipt?.result)));
$("reparse-receipt").addEventListener("click", () => startReceipt(true));
$("receipt-runs").addEventListener("change", () => {
  if (!receipt || !$("receipt-runs").value) return;
  receipt.runId = $("receipt-runs").value;
  displayReceiptRun(receipt.runId,receipt).catch(error => { $("receipt-status").textContent = error.message; });
});
$("pdf-page").addEventListener("change", () => {
  const first = receipt?.result?.lines.find(line => line.id.startsWith(`page-${$("pdf-page").value}-`));
  if (first) highlightEvidence([first.id]);
});
$("copy-receipt-text").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("receipt-text").value); $("copy-receipt-text").textContent = "Copied"; }
  catch { $("receipt-text").select(); $("receipt-status").textContent = "Text selected. Press Ctrl+C to copy."; }
});

const RECORD_FIELDS = {
  receipt: [["Merchant", "merchant"], ["Location", "location"], ["Purchase date", "purchase_date"], ["Subtotal", "subtotal_minor"], ["Tax", "tax_minor"], ["Tip", "tip_minor"], ["Total", "total_minor"]],
  statement: [["Period", "period_start", "period_end"], ["Opening balance", "opening_balance_minor"], ["Closing balance", "closing_balance_minor"],
              ["Statement balance", "statement_balance_minor"], ["Minimum payment", "minimum_payment_minor"], ["Due", "due_date"]],
  bill: [["Provider", "merchant"], ["Issued", "issue_date"], ["Due", "due_date"], ["Amount due", "amount_due_minor"]],
  income_record: [["Payer", "merchant"], ["Pay date", "pay_date"], ["Gross pay", "gross_pay_minor"], ["Net pay", "net_pay_minor"]],
};
// Fields the user may correct, by the key shown above -> the correction field the server accepts.
const CORRECTABLE = {receipt: {merchant: "merchant", location: "location", purchase_date: "purchase_date"},
                     bill: {merchant: "provider", issue_date: "issue_date", due_date: "due_date"},
                     income_record: {merchant: "payer", pay_date: "pay_date"}};
const isDateField = field => field.endsWith("_date");
function layaPanel(laya, extractedType) {
  // Advisory only: shown beside the record, never used to approve, reject or file it.
  const panel = element("details", "", "laya-panel");
  if (laya.error) { panel.append(element("summary", "Laya check unavailable"), element("p", laya.error, "muted")); return panel; }
  const scored = laya.checks.filter(check => check.supported !== null), doubted = scored.filter(check => !check.supported);
  const shadow = laya.classification;
  panel.appendChild(element("summary", `Independent check (Laya): ${scored.length - doubted.length} of ${scored.length} values confirmed`));
  panel.appendChild(element("p", `Laya classifies this as ${shadow.document_type.replaceAll("_", " ")} (${Math.round(shadow.confidence * 100)}%)` +
    (shadow.agrees ? ", matching the extraction." : `; the extraction says ${(extractedType || "unknown").replaceAll("_", " ")}.`), shadow.agrees ? "muted" : "item-warning"));
  const list = element("ul", "", "analysis-limitations");
  for (const check of doubted) list.appendChild(element("li", `${check.field.replaceAll("_", " ")}: not confirmed from its cited text (${Math.round(check.probability * 100)}%)`));
  if (doubted.length) panel.appendChild(list);
  panel.appendChild(element("p", "Laya runs on this computer after every extraction. A value it cannot confirm sends the record to review; it never approves one, and its document type is shown only for reference.", "muted"));
  return panel;
}
async function loadExtraction(state, parseId) {
  const runs = await api(`/api/receipt-runs/${parseId}/extraction-runs`);
  if (receipt !== state || state.runId !== parseId) return;
  state.extractionPending = runs.some(run => PENDING_RUN.includes(run.status));
  if (!runs.length) {
    setStatusBadge($("extraction-state"), "not_extracted"); $("extraction-result").replaceChildren();
    state.extraction = null; state.renderedExtractionKey = ""; renderRecordPane(state); return;
  }
  const run = await api(`/api/extraction-runs/${runs[0].id}`);
  if (receipt !== state || state.runId !== parseId) return;
  setStatusBadge($("extraction-state"), run.status);
  state.extraction = {status: run.status, error: run.error, publication: run.publication, documentType: run.document_type, pending: PENDING_RUN.includes(run.status)};
  renderRecordPane(state);  // Failures, blocked publications and unrecordable types are explained there.
  const key = `${run.id}:${run.status}`;
  if (state.renderedExtractionKey === key) return;
  state.renderedExtractionKey = key;
  const target = $("extraction-result"); target.replaceChildren();
  const publication = run.publication;
  if (run.status !== "succeeded" || !publication || publication.status === "blocked") return;
  if (publication.record_type === "asset") { await renderAssetRecord(target, publication); return; }
  await renderLedgerRecord(target, publication.record_type, publication.id, publication.status === "kept_reviewed");
  if (run.result.laya) target.appendChild(layaPanel(run.result.laya, run.document_type));
}
const RECORD_LABELS = {receipt: "receipt", statement: "statement", bill: "bill", income_record: "pay stub"};
function ledgerTitle(type, record) {
  // Same naming rule as documents: Merchant - Location - Description; dates and amounts are fields below.
  const parts = [record.merchant || record.institution, record.location, record.description].filter(Boolean);
  return parts.length ? parts.join(" - ") : RECORD_LABELS[type].replace(/^./, character => character.toUpperCase());
}
function sourceButton(lineIds) {
  const button = element("button", "Find", "source-link"); button.type = "button";
  button.setAttribute("aria-label", "Find this row in the transcription");
  button.addEventListener("click", () => highlightEvidence(lineIds));
  return button;
}
function ledgerRows(record) {
  // Items or transactions exactly as recorded, each linked to its source line.
  const rows = record.items || record.transactions || [];
  if (!rows.length) return null;
  const wrap = element("div", "", "table-wrap");
  const table = element("table", "", "ledger-rows");
  const columns = record.items ? ["Item", "Code", "Amount", ""] : ["Posted", "Description", "Amount", ""];
  const head = document.createElement("tr");
  columns.forEach((title, index) => { const th = head.appendChild(element("th", title, index === 2 ? "numeric" : "")); th.scope = "col"; });
  table.appendChild(document.createElement("thead")).appendChild(head);
  const body = table.appendChild(document.createElement("tbody"));
  for (const row of rows.slice(0, 200)) {
    const tr = document.createElement("tr");
    if (row.line_ids?.length) tr.dataset.lines = row.line_ids.join(" ");  // For reverse lookup from the image.
    const values = record.items ? [row.description, row.product_code || "", row.display.line_total_minor || "—"] : [row.posted_date, row.description_raw, row.display.amount_minor];
    values.forEach((value, index) => {
      const td = tr.appendChild(element("td", index === 2 ? "" : value, index === 2 ? "numeric" : ""));
      if (index === 2) td.appendChild(amount(value, {signed: !record.items}));  // Statement rows carry a direction; item prices don't.
    });
    const source = document.createElement("td"); if (row.line_ids?.length) source.appendChild(sourceButton(row.line_ids)); tr.appendChild(source);
    body.appendChild(tr);
  }
  wrap.appendChild(table);
  if (rows.length > 200) wrap.appendChild(element("p", `Showing 200 of ${rows.length} rows.`, "muted"));
  return wrap;
}
async function renderAssetRecord(target, publication) {
  // Investment and loan statements feed the forecast's assets; their values wait for review (docs/items-assets-search.md §6).
  const asset = (await api("/api/assets?include_archived=true")).find(row => row.id === publication.id);
  if (!asset) { target.replaceChildren(element("p", "The asset recorded from this statement was removed.", "muted")); return; }
  const heading = element("div", "", "ledger-record-heading");
  heading.append(element("strong", asset.name), statusBadge(asset.review_status));
  const facts = element("dl", "", "detail-list");
  for (const [label, value] of [[asset.kind === "loan" ? "Amount owed" : "Value", asset.value.display], ["As of", dateText(asset.as_of)],
                                ...(asset.kind === "loan" ? [["Yearly rate", `${asset.annual_rate_percent}%`], ["Monthly payment", asset.monthly_payment?.display || "Not printed"]] : [])]) {
    facts.append(element("dt", label), element("dd", value));
  }
  const notes = [];
  if (publication.status === "kept_newer") notes.push(element("p", "A newer statement for this account is already recorded, so this one didn't change it.", "muted"));
  if (publication.status === "kept_reviewed") notes.push(element("p", "You already reviewed this value, so the new extraction did not change it.", "muted"));
  for (const issue of asset.issues) notes.push(element("p", issue, "item-warning"));
  const next = asset.review_status === "proposed" ? homeLink("Confirm it in Review", "#/review") : homeLink("See it in Forecast", "#/forecast");
  target.replaceChildren(heading, facts, ...notes, element("p", "Statement values count in your forecast once you confirm them.", "muted small"), next);
}
async function renderLedgerRecord(target, type, id, kept) {
  const record = await api(`/api/finance/records/${type}/${id}`);
  target.replaceChildren();
  const heading = element("div", "", "ledger-record-heading");
  // Exception-based review: records that passed every automatic check need no action; only flagged ones ask.
  const automatic = record.review_status === "verified" && record.review_source === "automatic";
  heading.append(element("strong", ledgerTitle(type, record)), statusBadge(automatic ? "checked" : record.review_status));
  const choices = automatic ? [["Not right? Reject", "rejected"]]
    : record.review_status === "verified" ? [["Undo verification", "needs_review"]]
    : record.review_status === "rejected" ? [["Undo rejection", "needs_review"]]
    : [["Count it anyway", "verified"], ["Reject", "rejected"]];
  for (const [label, status] of choices) {
    const button = element("button", label, status === "rejected" ? "danger-text" : status === "verified" ? "primary" : ""); button.type = "button";
    button.addEventListener("click", () => api(`/api/finance/records/${type}/${id}/review`, {method:"POST", body:JSON.stringify({status})})
      .then(() => Promise.all([renderLedgerRecord(target, type, id, false), refreshInspectorDoc()])).catch(error => notice(error, true)));
    heading.appendChild(button);
  }
  const correctable = CORRECTABLE[type];
  if (correctable) heading.appendChild(actionButton("Edit details", () => editRecord(target, type, record)));
  target.appendChild(heading);
  if (kept) target.appendChild(element("p", "You already reviewed this record, so the new extraction did not change it.", "muted"));
  // Warnings ask for a decision; once the user has decided (verify or reject), they are no longer shown.
  const userDecided = ["verified", "rejected"].includes(record.review_status) && record.review_source === "user";
  if (record.issues?.length && !userDecided) {
    const list = element("ul", "", "analysis-limitations");
    for (const issue of record.issues) list.appendChild(element("li", issue));
    target.append(element("p", "Why this needs you (fix it with Edit details, or count it anyway):", "item-warning"), list);
  }
  const summary = document.createElement("div"); summary.className = "receipt-summary";
  const entered = new Set((record.corrections || []).map(correction => correction.field));
  for (const [label, field, end] of RECORD_FIELDS[type] || []) {
    const shown = end ? `${dateText(record[field]) || "?"} to ${dateText(record[end]) || "?"}` : record.display[field] || record[field];
    const fixable = correctable && field in correctable;
    if (shown == null && !fixable) continue;
    const value = element("strong");
    if (shown == null) value.appendChild(element("span", isDateField(field) ? "Not printed" : "Not found", "muted"));
    else value.appendChild(record.display[field] ? amount(shown, {signed: false}) : document.createTextNode(isDateField(field) ? dateText(shown) : shown));
    const metric = document.createElement("div"); metric.append(element("small", label), value);
    if (fixable && entered.has(correctable[field])) metric.appendChild(element("small", "Entered by you", "muted"));
    else if (fixable && shown == null) metric.appendChild(actionButton(`Add ${label.toLowerCase()}`, () => editRecord(target, type, record), "small"));
    summary.appendChild(metric);
  }
  target.appendChild(summary);
  const rows = ledgerRows(record);
  if (rows) target.appendChild(rows);
}
function editRecord(target, type, record) {
  // Inline correction form for what the document did not print or the model misread.
  const form = element("form", "", "record-edit"), inputs = {};
  form.appendChild(element("p", "Correct what the document did not print or was misread. Your values are kept if the document is extracted again.", "muted small"));
  for (const [label, field] of RECORD_FIELDS[type].filter(([, field]) => field in CORRECTABLE[type])) {
    const input = document.createElement("input"); input.id = `correct-${field}`;
    input.type = isDateField(field) ? "date" : "text"; input.value = record[field] || ""; input.maxLength = field === "location" ? 60 : 120;
    if (field === "location") input.placeholder = "City, or Online";
    const box = element("div", "", "field"); const caption = element("label", label); caption.htmlFor = input.id;
    box.append(caption, input); form.appendChild(box); inputs[field] = input;
  }
  const error = element("p", "", "error-text"); error.setAttribute("role", "alert");
  const actions = element("div", "", "button-row");
  const save = element("button", "Save", "primary"); save.type = "submit";
  actions.append(save, actionButton("Cancel", () => renderLedgerRecord(target, type, record.id, false)));
  form.append(error, actions);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const changes = {};
    for (const [field, input] of Object.entries(inputs)) {
      if (input.value.trim() !== (record[field] || "")) changes[CORRECTABLE[type][field]] = input.value.trim() || null;
    }
    if (!Object.keys(changes).length) { renderLedgerRecord(target, type, record.id, false); return; }
    try {
      save.disabled = true;
      await api(`/api/finance/records/${type}/${record.id}`, {method: "PATCH", body: JSON.stringify({changes})});
      await Promise.all([renderLedgerRecord(target, type, record.id, false), refreshInspectorDoc(), loadDocuments()]);
      notice("Details saved. Matching and spending were updated.");
    } catch (failure) { error.textContent = failure.message; save.disabled = false; }
  });
  target.querySelector(".receipt-summary").replaceWith(form);
  Object.values(inputs)[0]?.focus();
}
$("extract-ledger").addEventListener("click", async () => {
  const state = receipt; if (!state) return;
  const parseId = state.runId;
  try {
    busy.inference = true; controls();
    await api(`/api/documents/${state.doc.id}/extraction-runs`, {method:"POST", body:JSON.stringify({parse_run_id:parseId, force:state.extractionPending === false && $("extraction-state").dataset.status === "succeeded"})});
    state.actionError = ""; state.renderedExtractionKey = ""; await loadExtraction(state, parseId);
  } catch (error) { state.actionError = error.message; renderRecordPane(state); busy.inference = false; controls(); }
});
