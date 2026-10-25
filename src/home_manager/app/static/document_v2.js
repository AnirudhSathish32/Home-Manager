"use strict";
// The document page, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/document.md): the source beside
// the record, whose sticky header holds the steps, the one next action and the decision (Confirm, Reject, Correct…),
// then the tabs Record · History · Details. Re-run actions live in the ⋯ menu. Every amount and date is the server's;
// the route stays #/documents/ID[?version=HASH][&lines=ID,ID][&tab=history|details].
let doc2 = null;

V2_SCREENS.document = {title: "Document page", show: route => configured ? openDocumentV2(route.id, route.params) : null};

const DOC2_TABS = ["record", "history", "details"];
const setDoc2Tab = wireTabs(DOC2_TABS.map(name => `doc2-tab-${name}`));
for (const name of DOC2_TABS) {
  $(`doc2-tab-${name}`).addEventListener("tabshow", () => {
    if (!doc2) return;
    doc2.tab = name;
    if (!doc2.doc) return;  // Opening: the URL already says it, and History loads with the record.
    doc2Url();
    if (name === "history") doc2History(doc2).catch(error => notice(error, true));
  });
}
$("doc2-back").prepend(icon("arrow-left"));
$("doc2-back").addEventListener("click", event => { event.preventDefault(); leaveDocument(); });
$("doc2-runs").addEventListener("change", () => {
  const state = doc2;
  if (!state || !$("doc2-runs").value) return;
  state.runId = $("doc2-runs").value;
  doc2ShowRun(state.runId, state).catch(error => { $("doc2-status").textContent = error.message; });
});
$("doc2-reread").addEventListener("click", () => doc2Read(true));

// The tab and the shown lines stay in the URL (Layout rule 5), next to the version.
function doc2Url() {
  if (currentRoute?.name !== "document" || !doc2) return;
  const params = new URLSearchParams(currentRoute.params);
  if (doc2.tab === "record") params.delete("tab"); else params.set("tab", doc2.tab);
  currentRoute.params = params;
  history.replaceState(null, "", `#/documents/${doc2.doc.id}${[...params].length ? `?${params}` : ""}`);
}

async function openDocumentV2(id, params) {
  const version = params.get("version"), wanted = (params.get("lines") || "").split(",").filter(Boolean);
  const tab = DOC2_TABS.includes(params.get("tab")) ? params.get("tab") : "record";
  if (doc2?.doc && doc2.doc.id === id && doc2.digest === (version || doc2.doc.current_hash)) {
    renameDocumentV2(doc2.doc);
    if (doc2.tab !== tab) setDoc2Tab(`doc2-tab-${tab}`);
    if (wanted.length) doc2.viewer?.highlight(wanted);
    return;
  }
  closeDocumentV2();
  const state = {doc: null, digest: null, runId: "", run: null, result: null, resultRunId: null, extraction: null, record: null, type: null,
                 segment: 0, viewer: null, cc: null, tab, pending: false, loaded: false, textStatus: "", textError: "", actionError: "",
                 recordStatus: null, reload: null, wanted};
  doc2 = state;
  for (const target of ["doc2-panel-record", "doc2-history", "doc2-details", "doc2-provenance", "doc2-next", "doc2-why", "doc2-decision", "doc2-steps",
                        "doc2-record-badge", "doc2-viewer", "doc2-group", "doc2-version-banner", "doc2-state", "doc2-menu"]) $(target).replaceChildren();
  $("doc2-status").textContent = ""; $("doc2-telemetry").textContent = ""; $("doc2-rotation").value = "0";
  $("doc2-record-title").textContent = "Recorded information"; $("doc2-group").hidden = true;
  $("doc2-runs").replaceChildren(new Option("Not read yet", ""));
  setDoc2Tab(`doc2-tab-${tab}`);
  const doc = await pageState($("doc2-loading"), () => api(`/api/documents/${id}`), {loading: "Loading the document …", what: "this document", content: [$("doc2-body")]});
  if (!doc || doc2 !== state) return;
  state.doc = doc; state.digest = version || doc.current_hash;
  renameDocumentV2(doc);
  const latest = element("a", "View the latest version"); latest.href = `#/documents/${doc.id}`;
  $("doc2-version-banner").replaceChildren(...(state.digest !== doc.current_hash ? [alertBox("You're viewing an earlier preserved version of this document. Decisions apply to the latest version.", {tone: "warning", action: latest})] : []));
  state.viewer = sourceViewer(doc, null, {digest: state.digest});
  state.viewer.onRegionClick(({lineIds}) => doc2Cite(lineIds));
  $("doc2-viewer").replaceChildren(state.viewer.el);
  doc2Head(state); doc2Details(state); doc2Steps(state);
  doc2Group(state).catch(() => {});
  await doc2Runs(state);
  if (doc2 !== state) return;
  if (state.runId) await doc2ShowRun(state.runId, state);
  else { state.loaded = true; doc2Steps(state); }
  if (doc2 !== state) return;
  if (wanted.length) state.viewer.highlight(wanted);
  if (state.tab === "history") await doc2History(state);
}
function closeDocumentV2() {
  doc2?.viewer?.destroy();
  doc2 = null;
}
function renameDocumentV2(doc) {
  // Set on open and after the user edits the description; loading results never rename the page.
  if (doc2) doc2.doc = {...doc2.doc, ...doc};
  $("doc2-title").textContent = documentName(doc);
  document.title = `${documentName(doc)} · Home Manager`;
  $("doc2-subtitle").textContent = [folderLabel(doc.folder), doc.document_date && dateText(doc.document_date), doc.title && fileName(doc)].filter(Boolean).join(" · ");
}
async function refreshDocumentV2(state = doc2) {
  // Keeps the header state current after actions; the title stays as set on open.
  if (!state?.doc) return;
  const doc = await api(`/api/documents/${state.doc.id}`);
  if (doc2 !== state) return;
  state.doc = doc; doc2Head(state); doc2Details(state); doc2Steps(state);
}
function doc2Head(state) {
  $("doc2-state").replaceChildren(documentStateBadge(state.doc));
  state.menuKey = null; doc2Menu(state);
}
function doc2Menu(state) {
  const doc = state.doc, ready = Boolean(state.result && !state.pending && !busy.inference && !doc.deleted_at && state.resultRunId === state.runId);
  const canRead = Boolean(state.runId && !busy.inference && !doc.deleted_at && !state.pending);
  const key = [doc.version_count, doc.deleted_at, ready, canRead, Boolean(state.extraction), Boolean(state.result)].join(":");
  if (state.menuKey === key) return;  // Rebuilt only when it changes, so polling never closes an open menu.
  state.menuKey = key;
  const items = [asyncButton("Edit description…", () => openDescription(state.doc), ""), asyncButton(`Versions (${doc.version_count})`, () => showVersions(doc), "")];
  if (doc.deleted_at) items.push(asyncButton("Restore", () => restoreDocuments([doc]), ""));
  else items.push(asyncButton("Move", () => openLibraryAction([doc], "move"), ""), asyncButton("Delete", () => openLibraryAction([doc], "trash"), "danger-text"));
  const read = asyncButton("Read again", () => doc2Read(true), ""); read.disabled = !canRead;
  const extract = asyncButton("Extract again", () => doc2Record(true), ""); extract.disabled = !ready || !state.extraction;
  const copy = asyncButton("Copy text", async () => {
    try { await navigator.clipboard.writeText((state.result.layout_context?.lines || state.result.lines).map(line => line.text).join("\n")); notice("Text copied."); }
    catch { notice("Copying isn't available here. Use the source's Text tab and press Ctrl+C.", true); }
  }, "");
  copy.disabled = !state.result;
  items.push(read, extract, copy);
  $("doc2-menu").replaceChildren(menu("More actions", items));
}
function doc2Details(state) {
  const doc = state.doc, list = $("doc2-details"); list.replaceChildren();
  detailRow(list, "Managed location", element("code", doc.managed_path ? `Library/${doc.managed_path}` : "Managed copy pending"));
  if (doc.managed_error) detailRow(list, "Filing problem", element("span", doc.managed_error, "item-warning"));
  detailRow(list, "Original source", element("code", sourcePath(doc)),
            element("small", (doc.source_kind === "inbox" ? SOURCE_STATES : WATCHED_STATES)[doc.source_status] || statusLabel(doc.source_status)));
  // Every other place this document was found, never just one.
  for (const link of doc.links || []) {
    const open = element("a", sourcePath(link)); open.href = `#/documents/${link.document_id}`;
    detailRow(list, `Also found · ${LINK_REASONS[link.reason] || link.reason}`, open, ...(link.deleted_at ? [element("small", "In Trash")] : []));
  }
  detailRow(list, "Folder", folderLabel(doc.folder));
  detailRow(list, "Preserved version", element("code", state.digest), element("small", state.digest === doc.current_hash ? "Latest version" : "Earlier version"), copyButton(state.digest, "Copy hash"));
  detailRow(list, "Versions", String(doc.version_count));
}
function doc2Provenance(result) {
  const list = $("doc2-provenance"); list.replaceChildren();
  const code = value => element("code", typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "—"));
  detailRow(list, "Method", METHODS[result.transcription_method] || String(result.transcription_method || "—"));
  if (result.pages) { detailRow(list, "Pages", result.pages.map(page => `Page ${page.number}: ${page.method}, ${page.lines.length} lines`).join(" · ")); return; }
  for (const [label, value] of [["Engine", result.engine], ["Parser version", result.parser_version], ["Schema version", result.schema_version],
                                ["Input hash", result.input_hash], ["Model identity", result.model_hashes], ["Coverage", result.coverage],
                                ["Original size", `${result.original_width} × ${result.original_height}`], ["Preview size", `${result.width} × ${result.height}`],
                                ["EXIF orientation", result.exif_orientation], ["Rotation", `${result.clockwise_rotation}°`], ["Coordinates", result.coordinate_space]])
    if (value !== undefined) detailRow(list, label, code(value));
}

// Several images as one document (documents/grouping.py), beside the source.
async function doc2ChangeGroup(state, group, body, message) {
  await api(`/api/document-groups/${group.id}`, {method: "PATCH", body: JSON.stringify(body)});
  notice(message);
  const lead = body.document_ids ? body.document_ids[0] : state.doc.id;
  if (lead !== state.doc.id) location.hash = `#/documents/${lead}`;
  else { closeDocumentV2(); await openDocumentV2(state.doc.id, currentRoute?.params || new URLSearchParams()); }
}
async function doc2Group(state) {
  const group = await api(`/api/documents/${state.doc.id}/group`);
  if (doc2 !== state || !group) return;
  const strip = $("doc2-group"), pages = group.pages, index = pages.findIndex(page => page.document_id === state.doc.id);
  if (group.status === "proposed") {
    strip.replaceChildren(alertBox(`This image may be one page of a document photographed in ${pages.length} parts.`, {action: homeLink("Decide in To check", "#/review")}));
    strip.hidden = false; return;
  }
  if (index > 0) {
    const link = element("a", "Open the combined document"); link.href = `#/documents/${pages[0].document_id}`;
    strip.replaceChildren(alertBox(`This image is page ${index + 1} of ${pages.length} of a combined document; it is read and recorded there.`, {action: link}));
    strip.hidden = false; return;
  }
  const order = pages.map(page => page.document_id), picker = element("div", "", "work-filters");
  picker.setAttribute("aria-label", "Pages");
  pages.forEach((page, number) => {
    const button = element("button", `Page ${number + 1}`, "filter-chip"); button.type = "button";
    button.setAttribute("aria-pressed", String(number === 0)); button.title = page.relative_path;
    button.addEventListener("click", async () => {
      for (const other of picker.children) other.setAttribute("aria-pressed", String(other === button));
      await state.viewer.showDocument(page.document_id);
      const first = state.result?.lines?.find(line => line.id.startsWith(`page-${number + 1}-`));
      if (first) state.viewer.highlight([first.id]);
      state.groupPage = number;
    });
    picker.append(button);
  });
  const move = offset => {
    const from = state.groupPage || 0, to = from + offset;
    if (to < 0 || to >= order.length) return null;
    const moved = [...order]; [moved[from], moved[to]] = [moved[to], moved[from]];
    return doc2ChangeGroup(state, group, {document_ids: moved}, "Pages reordered. The document is read again in the new order.");
  };
  const actions = element("div", "", "button-row");
  actions.append(asyncButton("Move page earlier", () => move(-1)), asyncButton("Move page later", () => move(1)),
                 asyncButton("Separate pages…", async () => {
                   if (!await confirmAction({title: "Separate these pages?", message: `The ${pages.length} images become separate documents again, and each is read and recorded on its own. The combined document's record stops counting.`,
                                             confirmLabel: "Separate pages", danger: true})) return;
                   await doc2ChangeGroup(state, group, {status: "dismissed"}, "Separated. Each image is read and recorded on its own.");
                 }));
  strip.replaceChildren(element("strong", `Combined document · ${pages.length} pages`), picker, actions);
  strip.hidden = false;
}

// Readings: the run history, the shown run, and reading again.
async function doc2Runs(state) {
  const runs = await api(`/api/documents/${state.doc.id}/receipt-runs?blob_hash=${state.digest}`);
  if (doc2 !== state) return;
  const selector = $("doc2-runs"); selector.replaceChildren();
  if (!runs.length) { selector.add(new Option("Not read yet", "")); return; }
  for (const run of runs) {
    const rotation = JSON.parse(run.options_json).clockwise_rotation;
    selector.add(new Option(`${new Date(run.created_at).toLocaleString()} · ${statusLabel(run.status)} · ${rotation}°`, run.id));
  }
  if (!state.runId) state.runId = runs[0].id;
  selector.value = state.runId;
}
async function doc2ShowRun(runId, state) {
  const run = await api(`/api/receipt-runs/${runId}`);
  if (doc2 !== state || state.runId !== runId) return;
  state.run = run; state.pending = PENDING_RUN.includes(run.status);
  state.textStatus = run.status; state.textError = run.error || "";
  $("doc2-status").textContent = state.pending || run.status === "succeeded" ? "" : `Reading ${statusLabel(run.status).toLowerCase()}${run.error ? `: ${run.error}` : ""}.`;
  if (run.result && state.resultRunId !== runId) {
    state.resultRunId = runId; state.result = run.result;
    clearReadings();
    await state.viewer.update({doc: state.doc, run, result: run.result}, runId);
    doc2Provenance(run.result);
  }
  $("doc2-telemetry").textContent = runTelemetry(run);
  state.loaded = true; doc2Steps(state);
  await doc2Extraction(state, runId);
  await doc2Runs(state);
}
async function doc2Read(force) {
  const state = doc2;
  if (!state?.doc) return;
  try {
    busy.inference = true; controls(); state.actionError = "";
    const data = await api(`/api/documents/${state.doc.id}/receipt-runs`, {method: "POST", body: JSON.stringify({blob_hash: state.digest, clockwise_rotation: Number($("doc2-rotation").value), force})});
    if (doc2 !== state) return;
    state.runId = data.run_id; state.pending = true;
    await doc2ShowRun(state.runId, state);
  } catch (error) { state.actionError = error.message; busy.inference = false; controls(); doc2Steps(state); }
}
async function doc2Record(force = null) {
  const state = doc2;
  if (!state?.runId) return;
  const parseId = state.runId;
  try {
    busy.inference = true; controls();
    await api(`/api/documents/${state.doc.id}/extraction-runs`, {method: "POST", body: JSON.stringify({parse_run_id: parseId,
      force: force ?? (state.extractionPending === false && state.extraction?.status === "succeeded")})});
    state.actionError = ""; state.renderedKey = ""; await doc2Extraction(state, parseId);
  } catch (error) { state.actionError = error.message; busy.inference = false; controls(); doc2Steps(state); }
}
async function pollDocumentV2() {
  const state = doc2;
  if (state?.pending && state.runId) await doc2ShowRun(state.runId, state);
  if (state?.runId && (state.extractionPending || busy.inference)) await doc2Extraction(state, state.runId);
  if (state?.doc) doc2Steps(state);
}

// Read → Recorded, each with an icon and a hidden state word (never color alone), then the one next action.
const DOC2_STEP = {done: ["check-circle", "done"], running: ["loader", "in progress"], failed: ["x-circle", "failed"], attention: ["alert", "needs you"],
                   todo: ["dashed", "not started"], none: ["slash", "nothing to record"], rejected: ["x-circle", "rejected"]};
function doc2StepStates(state) {
  const failed = status => ["failed", "interrupted", "cancelled"].includes(status);
  const read = state.pending ? "running" : state.result ? "done" : failed(state.textStatus) ? "failed" : "todo";
  if (!state.loaded) return [];
  if (read !== "done" || !state.extractionChecked) return [["Read", read]];
  const extraction = state.extraction;
  const recorded = !extraction ? "todo" : extraction.pending ? "running" : failed(extraction.status) ? "failed"
    : !extraction.publication ? "none" : extraction.publication.status === "blocked" ? "attention"
    : ["needs_review", "proposed"].includes(state.recordStatus) ? "attention" : state.recordStatus === "verified" ? "done"
    : state.recordStatus === "rejected" ? "rejected" : "running";
  return [["Read", read], ["Recorded", recorded]];
}
function doc2Steps(state) {
  if (doc2 !== state || !state.doc) return;
  $("doc2-steps").replaceChildren(...doc2StepStates(state).map(([label, key]) => {
    const [glyph, word] = DOC2_STEP[key], item = element("li", "", "doc2-step"); item.dataset.state = key;
    item.append(icon(glyph, key === "running" ? "icon spin" : "icon"), element("span", label), element("span", `, ${word}`, "visually-hidden"));
    return item;
  }));
  const parts = [], extraction = state.extraction, doc = state.doc, idle = !busy.inference;
  const next = (label, action, tone = "primary") => { const button = element("button", label, tone); button.type = "button"; button.disabled = !idle; button.addEventListener("click", action); return button; };
  // Import transactions (FR-26, docs/documents.md "Transaction imports"): primary when one saved account matches the PDF, else beside Record.
  // Offered only on the latest version of a read PDF, and never while it is being read or recorded.
  const offer = state.loaded && state.result && state.extractionChecked && !state.pending && !extraction?.pending && state.digest === doc.current_hash ? pdfImportOffer(doc) : null;
  const importButton = offer && next("Import transactions", () => openImport(doc, {onDone: () => refreshDocumentV2(state)}), offer === "primary" ? "primary" : "secondary");
  const recordTone = offer === "primary" ? "secondary" : "primary";
  if (state.actionError) parts.push(alertBox(state.actionError, {tone: "error"}));
  if (!state.loaded) { /* The page's loading state says it. */ }
  else if (doc.deleted_at) parts.push(element("p", "This document is in Trash. Restore it from ⋯ to read or record it.", "muted small"));
  else if (state.pending) parts.push(element("p", "Reading … progress shows in the sidebar.", "muted small"));
  else if (!state.result && ["failed", "interrupted", "cancelled"].includes(state.textStatus))
    parts.push(alertBox(state.textStatus === "cancelled" ? "Reading was cancelled before it finished." : `Home Manager couldn't read this document. ${state.textError}`.trim(),
                        {tone: state.textStatus === "cancelled" ? "info" : "error", action: next("Try again", () => doc2Read(true))}));
  else if (!state.result) {
    const row = element("div", "", "doc2-next-row");
    row.append(next("Read document", () => doc2Read(false)));
    if (!modelsConfigured.vision) row.append(modelNote("Reading needs a local vision model."));
    parts.push(row);
  } else if (!state.extractionChecked) { /* Until its recordings are checked, the next step isn't known. */ }
  else if (extraction?.pending) parts.push(element("p", "Recording … progress shows in the sidebar.", "muted small"));
  else if (!extraction) {
    const row = element("div", "", "doc2-next-row");
    const record = next("Record it", () => doc2Record(), recordTone);
    row.append(element("p", "Read, but not recorded yet. Recording checks every amount against its source line.", "small"), ...(offer === "primary" ? [importButton, record] : [record, ...(importButton ? [importButton] : [])]));
    if (!modelsConfigured.reasoning) row.append(modelNote("Recording needs a local reasoning model."));
    parts.push(row);
  } else if (["failed", "interrupted"].includes(extraction.status))
    parts.push(alertBox(`Home Manager couldn't record this document. ${extraction.error || ""}`.trim(), {tone: "error", action: next("Try again", () => doc2Record(true))}));
  else if (extraction.status === "cancelled") parts.push(alertBox("Recording was cancelled before it finished.", {action: next("Record it", () => doc2Record(true), recordTone)}));
  else if (!extraction.publication)
    parts.push(element("p", `Filed as ${(extraction.documentType || "an unknown document").replaceAll("_", " ")}, which has no ledger record. Use Move to put it elsewhere.`, "muted small"));
  else if (extraction.publication.status === "blocked") parts.push(alertBox(`Can't record this: ${extraction.publication.reason}`, {tone: "warning"}));
  // Where Record isn't the next step (recorded, filed elsewhere, failed, cancelled), Import transactions stands on its own row.
  if (importButton && !parts.some(part => part.contains?.(importButton))) {
    const row = element("div", "", "doc2-next-row"); row.append(importButton); parts.push(row);
  }
  $("doc2-next").replaceChildren(...parts);
  // An earlier version or a document in Trash shows its record without a decision.
  $("doc2-decision").hidden = state.digest !== doc.current_hash || Boolean(doc.deleted_at);
  doc2Menu(state);
  const key = [state.textStatus, extraction?.status, state.pending].join(":");
  if (state.loaded && state.stateKey !== undefined && state.stateKey !== key) refreshDocumentV2(state).catch(() => {});
  state.stateKey = key;
}

// The record (receipt.js keeps its row, pay stub and investment builders) with this page's header, decision and tabs.
function doc2ClearRecord() {
  for (const id of ["doc2-panel-record", "doc2-why", "doc2-decision", "doc2-record-badge"]) $(id).replaceChildren();
  $("doc2-record-title").textContent = "Recorded information";
  if (doc2) { doc2.record = null; doc2.type = null; doc2.cc = null; doc2.recordStatus = null; doc2.reload = null; }
}
async function doc2Extraction(state, parseId) {
  const runs = await api(`/api/receipt-runs/${parseId}/extraction-runs`);
  if (doc2 !== state || state.runId !== parseId) return;
  state.extractionPending = runs.some(run => PENDING_RUN.includes(run.status));
  // extractionChecked: the Recorded step and the next action wait until the record's state is known, so a recorded
  // document never flashes "Record it" while it loads.
  if (!runs.length) {
    if (state.renderedKey !== "") { doc2ClearRecord(); $("doc2-panel-record").append(emptyState("Nothing is recorded from this document yet.")); }
    state.extraction = null; state.renderedKey = ""; state.extractionChecked = true; doc2Steps(state); return;
  }
  const run = await api(`/api/extraction-runs/${runs[0].id}`);
  if (doc2 !== state || state.runId !== parseId) return;
  state.extraction = {status: run.status, error: run.error, publication: run.publication, documentType: run.document_type, pending: PENDING_RUN.includes(run.status)};
  const key = `${run.id}:${run.status}`;
  if (state.renderedKey === key) { state.extractionChecked = true; doc2Steps(state); return; }
  state.renderedKey = key;
  doc2ClearRecord();
  const target = $("doc2-panel-record"), publication = run.publication;
  if (run.status !== "succeeded" || !publication || publication.status === "blocked") {
    target.append(emptyState("Nothing is recorded from this document yet.")); state.extractionChecked = true; doc2Steps(state); return;
  }
  if (["asset", "investment_valuation", "investment_confirmation", "tax_form"].includes(publication.record_type)) await doc2Other(state, target, publication);
  else if (publication.segments) await doc2Split(target, state, publication);
  else await doc2Ledger(state, target, publication.record_type, publication.id, publication.status === "kept_reviewed");
  const check = run.result?.decision || run.result?.laya;
  if (check && doc2 === state) {
    const checks = element("section", "", "doc2-section"); checks.append(element("h3", "Checks"), decisionPanel(check, run.document_type));
    target.append(checks);
  }
  state.extractionChecked = true; doc2Steps(state);
  if (state.tab === "history") doc2History(state).catch(() => {});
}
// Lines the user picked on the source: the record's rows that cite them light up.
function doc2Cite(lineIds) {
  const lines = new Set(lineIds);
  let first = null;
  for (const row of $("doc2-panel-record").querySelectorAll("tr[data-lines]")) {
    const cited = row.dataset.lines.split(" ").some(id => lines.has(id));
    row.classList.toggle("cited", cited);
    if (cited && !first) first = row;
  }
  first?.scrollIntoView({block: "nearest"});
}
function doc2Decision(state, options) {
  state.cc = confirmCorrect({...options, showState: false, onChange: () => doc2Changed(state)});
  $("doc2-decision").replaceChildren(state.cc.el);
}
async function doc2Changed(state) {
  if (doc2 !== state) return;
  await Promise.all([state.reload?.(), refreshDocumentV2(state), renderNavCounts().catch(() => {})]);
  if (state.tab === "history") await doc2History(state);
}
// The page's h1 is the document's name; the record header says what was recorded and from whom.
function doc2RecordTitle(type, record) {
  if (type === "income_record") return ledgerTitle(type, record);
  const kind = (record.invoice ? "Invoice" : record.document_kind === "bill" ? "Bill" : {receipt: "Receipt", statement: "Statement"}[type]) || "Record";
  const from = record.merchant || record.account || record.institution;
  return from ? `${kind} from ${from}` : kind;
}
// Warnings, one bullet each, behind a Hide/Show button whose choice this browser remembers for every document.
const WARNINGS_HIDDEN_KEY = "home-manager-doc-warnings-hidden";
function doc2Why(issues) {
  const row = element("div", "", "needs-row attention doc2-why-row"), text = element("div", "", "doc2-why-text");
  const heading = element("strong", `${issues.length} ${issues.length === 1 ? "warning" : "warnings"} to check`);
  const list = element("ul", "", "doc2-why-list"); list.id = "doc2-why-list";
  list.append(...issues.map(issue => element("li", issue)));
  const hint = element("small", "Check them against the source, then confirm, correct or reject the record.", "muted");
  const toggle = element("button", "", "link-button doc2-why-toggle"); toggle.type = "button"; toggle.setAttribute("aria-controls", list.id);
  const show = hidden => {
    list.hidden = hint.hidden = hidden;
    toggle.textContent = hidden ? "Show" : "Hide"; toggle.setAttribute("aria-expanded", String(!hidden));
  };
  let hidden;
  try { hidden = localStorage.getItem(WARNINGS_HIDDEN_KEY) === "1"; } catch { hidden = false; }
  show(hidden);
  toggle.addEventListener("click", () => {
    hidden = !hidden; show(hidden);
    try { if (hidden) localStorage.setItem(WARNINGS_HIDDEN_KEY, "1"); else localStorage.removeItem(WARNINGS_HIDDEN_KEY); } catch { /* This page only. */ }
  });
  const top = element("div", "", "doc2-why-top"); top.append(heading, toggle);
  text.append(top, list, hint);
  row.append(icon("alert", "icon needs-icon"), text);
  return row;
}
async function doc2Ledger(state, target, type, id, kept) {
  const record = await api(`/api/finance/records/${type}/${id}?figures=1`);
  if (doc2 !== state) return;
  state.record = record; state.type = type; state.recordStatus = record.review_status;
  state.reload = () => doc2Ledger(state, target, type, id, false);
  const automatic = record.review_status === "verified" && record.review_source === "automatic";
  $("doc2-record-title").textContent = doc2RecordTitle(type, record);
  $("doc2-record-badge").replaceChildren(...saleBadges(record), statusBadge(automatic ? "checked" : record.review_status));
  // Warnings ask for a decision; once the user has decided (verify or reject), they are no longer shown.
  const decided = ["verified", "rejected"].includes(record.review_status) && record.review_source === "user";
  $("doc2-why").replaceChildren(...(record.issues?.length && !decided ? [doc2Why(record.issues)] : []));
  state.itemsSection = null;
  doc2Decision(state, {recordType: type, recordId: id, reviewStatus: record.review_status, reviewSource: record.review_source, correctable: record.correctable || [],
                       onOpen: () => doc2ShowRowEdits(state, true), onClose: () => doc2ShowRowEdits(state, false)});
  const find = ids => state.viewer.highlight(ids);
  const parts = [];
  if (kept) parts.push(element("p", "You already reviewed this record, so the new extraction did not change it.", "muted small"));
  parts.push(doc2Fields(state, type, record), ...doc2Forms(state, type, record, find));
  const categories = type === "receipt" && record.review_status !== "rejected" ? await receiptCategories() : [];
  if (doc2 !== state) return;
  const rows = ledgerRows(record, categories, state.reload, find, state.cc?.correctButton ? field => state.cc.openCorrect(field) : null);
  if (rows) {
    if (["statement", "receipt"].includes(type)) doc2RowCorrect(state, rows, record, type === "receipt" && record.review_status !== "rejected");
    // A receipt's row Correct and Delete show only while the record's Correct is open (doc2ShowRowEdits).
    const section = element("section", "", type === "receipt" ? "doc2-section doc2-hide-edits" : "doc2-section");
    if (type === "receipt") state.itemsSection = section;
    section.append(element("h3", type === "statement" ? `Transactions (${record.transactions.length})` : `Items (${record.items?.length || 0})`), rows);
    parts.push(section);
  }
  if (record.shareable_by_line && !familyMode && activeProfile?.family && record.review_status !== "rejected") parts.push(doc2ShareByLine(state, record));
  if (record.links?.length) parts.push(doc2Links(record, type));
  if (record.rewards?.length) parts.push(rewardsList(record.rewards, find));
  if (type === "income_record") parts.push(...paystubBreakdown(record, find, () => doc2Changed(state)), ...withholdingSection(record));
  if (type === "receipt" && record.review_status !== "rejected") parts.push(taxReceiptSection(record, state.reload));
  target.replaceChildren(...parts);
  doc2Steps(state);
}
// One row per field shown: its value, a mark when a person changed it, then Find (its source line) and Correct.
function doc2Fields(state, type, record) {
  const list = element("dl", "", "doc2-fields");
  const fix = field => (record.correctable || []).find(item => item.shown_as === field || `${item.shown_as}_minor` === field);
  const corrected = field => (record.corrections || []).filter(item => item.field === field).at(-1);
  for (const [fieldLabel, field, end] of RECORD_FIELDS[type === "receipt" && record.document_kind === "bill" ? "bill" : type] || []) {
    const label = record.invoice && field === "total_minor" ? "Invoice total"
      : record.invoice && field === "amount_due_minor" ? "Remaining balance" : fieldLabel;
    if (end && !record[field] && !record[end] && !fix(field)) continue;  // A bill without a printed period.
    if (field === "tip_minor" && !showsTip(record)) continue;
    // A receipt's Total is its printed total; what was paid after gift cards is in its Paid line (doc2Forms).
    const printed = type === "receipt" && field === "total_minor" && record.paid_summary ? record.printed_total?.display : null;
    const shown = end ? (record[field] || record[end] ? `${dateText(record[field]) || "?"} to ${dateText(record[end]) || "?"}` : null) : printed || record.display[field] || record[field];
    const correction = fix(field);
    if (shown == null && !correction) continue;
    const value = element("dd", "", "doc2-value");
    // A receipt belongs to every category its items fall in, largest share first (rule 3).
    const spread = type === "receipt" && field === "category" ? (record.splits || []).filter(row => row.amount_minor).map(row => row.category) : [];
    if (spread.length) value.append(...spread.map(name => element("span", categoryLabel(name === "uncategorized" ? null : name), "category-tag")));
    else if (shown == null) value.append(element("span", isDateField(field) ? "Not printed" : field === "category" ? "Not set" : "Not found", "muted"));
    else value.append(record.display[field] || printed ? amount(shown, {signed: false})
      : document.createTextNode(isDateField(field) ? dateText(shown) : field === "category" ? categoryLabel(shown) : field === "direction" ? directionText(record)
        : field === "document_kind" ? DOCUMENT_KIND_LABELS[shown] || shown
        : field === "recurrence" ? FREQUENCY_LABELS[shown] || shown : field === "pay_frequency" ? PAY_FREQUENCIES[shown] || shown : shown));
    // Not printed as a total: the server's subtotal of the lines in From gross pay to net pay.
    if (record.worked_out?.includes(field)) value.append(element("small", " Worked out from the pay lines", "muted"));
    const change = correction && corrected(correction.field);
    if (change) value.append(provenanceBadge({kind: "override", actor: {person: change.actor}, override: {reason: change.reason}}));
    const links = element("span", "", "doc2-field-actions");
    if (state.result && field !== "document_kind" && field in record) {  // A field shown only (worked out) has no source of its own.
      const find = element("button", "Find", "link-button"); find.type = "button"; find.setAttribute("aria-label", `Find ${label.toLowerCase()} in the source`);
      find.addEventListener("click", async () => {
        try {
          const found = await api(`/api/provenance/${type}/${record.id}?field=${encodeURIComponent(correction?.field || field.replace(/_minor$/, ""))}`);
          const cells = found.provenance.document?.cells?.filter(cell => cell.source === "pdf_text") || [];
          const lines = cells.length ? cells.map(cell => cell.cell_id) : found.provenance.document?.lines || [];
          if (lines.length) state.viewer.highlight(lines);
          else { find.disabled = true; $("doc2-status").textContent = `No source line is cited for ${label.toLowerCase()}.`; }
        } catch (error) { notice(error, true); }
      });
      links.append(find);
    }
    if (correction && state.cc?.correctButton) {
      const correct = element("button", "Correct", "link-button"); correct.type = "button"; correct.setAttribute("aria-label", `Correct ${label.toLowerCase()}`);
      correct.addEventListener("click", () => state.cc.openCorrect(correction.field));
      links.append(correct);
    }
    if (end && fix(end) && state.cc?.correctButton) {
      const correct = element("button", "Correct end", "link-button"); correct.type = "button";
      correct.setAttribute("aria-label", "Correct period end");
      correct.addEventListener("click", () => state.cc.openCorrect(fix(end).field)); links.append(correct);
    }
    value.append(links);
    list.append(element("dt", label), value);
  }
  // What the record adds to the app's totals, each a figure whose breakdown says how.
  const figureRow = (label, items) => {
    const value = element("dd", "", "doc2-value doc2-counts");
    for (const item of items) {
      const line = element("span", "", "doc2-count");
      if (item.label !== label) line.append(element("span", item.label, "muted"));
      line.append(figure(item, {size: "inline", signed: false}));
      value.append(line);
    }
    list.append(element("dt", label), value);
  };
  if (record.figures?.split) figureRow("Counts as", [record.figures.split]);
  if (record.figures?.counts_in?.length) figureRow("Counts in", record.figures.counts_in);
  if (record.figures?.balance) figureRow("Account balance", [record.figures.balance]);
  return list;
}
// Document forms (docs/documents.md "Receipt kinds", "Pay stub and statement fields"): what the document printed beyond
// its counted amounts, each with its source line; the receipt's kind and how to change it; the details a reviewed
// receipt's new kind waits to apply; and the arithmetic checks, each a figure whose breakdown is its trace.
const RECEIPT_KINDS = {fuel: "Fuel", dining: "Dining", grocery: "Grocery", general: "General"};
const DETAIL_LABELS = {volume: "Volume", price_per_unit: "Price per unit", fuel_grade: "Grade", pump_number: "Pump", fuel_amount: "Fuel amount",
                       gratuity_included: "Gratuity included", gratuity: "Gratuity", party_size: "Party size", server: "Server", table: "Table",
                       savings_total: "Member savings", account_type: "Account type", deposits_total: "Deposits", withdrawals_total: "Withdrawals",
                       interest_earned: "Interest earned", fees_total: "Fees", apy: "Interest rate (APY)", purchase_apr: "Purchase rate (APR)",
                       cash_advance_apr: "Cash advance rate (APR)", credit_limit: "Credit limit", available_credit: "Available credit",
                       rewards_earned: "Rewards earned", rewards_balance: "Rewards balance", pto_balance: "Paid time off", sick_balance: "Sick leave"};
const ACCOUNT_TYPES = {checking: "Checking", savings: "Savings", money_market: "Money market", other: "Other"};
const TENDER_LABELS = {gift_card: "Gift card", ebt: "EBT", card: "Card", cash: "Cash", other: "Payment"};
function doc2Forms(state, type, record, find) {
  const parts = [];
  if (type === "receipt" && record.document_kind !== "bill") {
    if (record.pending_details) parts.push(doc2Pending(state, record));
    parts.push(doc2Kind(state, record));
  }
  if (record.paid_summary) parts.push(doc2Paid(record.paid_summary));
  const details = doc2DetailList(state, record, find);
  if (details) parts.push(details);
  if (record.checks?.length) parts.push(doc2Checks(record.checks));
  return parts;
}
// One detail's row: its shown value, Find (its cited line) and, when it can be corrected, Correct.
function doc2DetailRow(state, record, list, label, detail, find, field = null) {
  const value = element("dd", "", "doc2-value");
  value.append(detail.minor != null ? amount(detail.display, {signed: false}) : document.createTextNode(detail.display ?? detail.text ?? "—"));
  const actions = element("span", "", "doc2-field-actions");
  if (detail.locator?.line_ids?.length) {
    const button = element("button", "Find", "link-button"); button.type = "button";
    button.setAttribute("aria-label", `Find ${label.toLowerCase()} in the source`);
    button.addEventListener("click", () => find(detail.locator.line_ids));
    actions.append(button);
  }
  const correction = field && (record.correctable || []).find(item => item.field === field);
  if (correction && state.cc?.correctButton) {
    const correct = element("button", "Correct", "link-button"); correct.type = "button"; correct.setAttribute("aria-label", `Correct ${label.toLowerCase()}`);
    correct.addEventListener("click", () => state.cc.openCorrect(field));
    actions.append(correct);
  }
  value.append(actions);
  list.append(element("dt", label), value);
}
function doc2DetailList(state, record, find) {
  const details = record.details;
  if (!details || !Object.keys(details).length) return null;
  const section = element("section", "", "doc2-section doc2-details-section"), list = element("dl", "", "doc2-detail-fields");
  section.append(element("h3", "Printed details"), list);
  for (const [name, detail] of Object.entries(details)) {
    if (!DETAIL_LABELS[name] || !detail || typeof detail !== "object" || !("locator" in detail)) continue;
    const shown = name === "account_type" ? {...detail, display: ACCOUNT_TYPES[detail.text] || detail.text} : detail;
    doc2DetailRow(state, record, list, DETAIL_LABELS[name], shown, find, `detail:${name}`);
    if (detail.label) list.lastElementChild.append(element("span", `printed as ${detail.label.text}`, "muted small"));
  }
  (details.tenders || []).forEach((tender, index) => {
    const label = `${TENDER_LABELS[tender.tender_type] || "Payment"}${tender.last_four ? ` ****${tender.last_four}` : ""}`;
    doc2DetailRow(state, record, list, label, tender, find, `detail:tenders.${index + 1}.amount`);
  });
  (details.deposit_splits || []).forEach(split => doc2DetailRow(state, record, list, `Direct deposit${split.last_four ? ` ****${split.last_four}` : ""}`, split, find));
  // A grocery row's weight and price per weight, or its count and unit price, beside the item it belongs to.
  for (const item of record.items || []) {
    const weight = item.details?.weight, per = item.details?.price_per_weight;
    if (weight) {
      list.append(element("dt", item.description), element("dd", `${weight.display}${per ? ` @ ${per.text}/${per.unit || weight.unit || ""}` : ""}`, "doc2-value"));
      continue;
    }
    if (item.quantity && item.display?.unit_price_minor && record.receipt_kind === "grocery") {
      const value = element("dd", "", "doc2-value");
      value.append(document.createTextNode(`${item.quantity} × `), amount(item.display.unit_price_minor, {signed: false}));
      list.append(element("dt", item.description), value);
    }
  }
  return list.children.length ? section : null;
}
// "Total 8.55 · Gift card −5.00 · Paid 3.55": Paid opens how it's worked out.
function doc2Paid(summary) {
  const section = element("section", "", "doc2-section doc2-paid"), line = element("p", "", "doc2-paid-line");
  line.append(element("span", "Total ", "muted"), amount(summary.total, {signed: false}), element("span", " · Gift card ", "muted"),
              amount(summary.gift_cards), element("span", " · Paid ", "muted"), figure(summary.paid, {size: "inline", signed: false}));
  section.append(line);
  if (!summary.counted)
    section.append(element("p", `Paid ${summary.paid.display} isn't counted: this receipt was reviewed before its gift card was read. Correcting the gift card, `
                                + "the total or sale or return with Edit details counts it.", "muted small"));
  return section;
}
function doc2Checks(checks) {
  const section = element("section", "", "doc2-section doc2-checks"), list = element("ul", "", "finance-list");
  section.append(element("h3", "Arithmetic checks"));
  for (const check of checks) {
    const item = element("li", "", "doc2-check"); item.dataset.passes = String(check.passes);
    item.append(icon(check.passes ? "check-circle" : "alert"), element("span", `${check.label} `), figure(check.figure, {size: "inline", signed: false}));
    if (check.compared_with) item.append(element("span", check.passes ? " matches the printed " : " doesn't match the printed ", "muted"),
                                         amount(check.compared_with, {signed: false}));
    else if (!check.passes) item.append(element("span", " doesn't check out", "muted"));
    list.append(item);
  }
  section.append(list);
  return section;
}
// The receipt's kind, and reading it again as another kind: its details and rows, from the saved text only.
function doc2Kind(state, record) {
  const section = element("section", "", "doc2-section doc2-kind"), list = element("dl", "", "doc2-detail-fields");
  const value = element("dd", "", "doc2-value");
  value.append(document.createTextNode(record.receipt_kind ? RECEIPT_KINDS[record.receipt_kind] : "Not read with kinds"));
  const select = document.createElement("select"); select.id = "doc2-kind-choice";
  select.setAttribute("aria-label", "Receipt kind");
  for (const [key, label] of Object.entries(RECEIPT_KINDS)) select.add(new Option(label, key, false, key === record.receipt_kind));
  const reviewed = ["verified", "rejected"].includes(record.review_status) && record.review_source === "user";
  const change = asyncButton("Change kind…", async () => {
    const kind = select.value, label = RECEIPT_KINDS[kind];
    if (kind === record.receipt_kind) { notice(`This receipt is already read as ${label.toLowerCase()}.`); return; }
    const message = `Its details and rows are read again from the saved text with the ${label.toLowerCase()} form; the image isn't read again, `
      + "and your corrections stay. " + (reviewed ? "You reviewed this receipt, so its amounts and review stay as they are, and the new details wait for Apply details."
        : "Its amounts and items follow the new reading.");
    if (!await confirmAction({title: `Read this receipt as ${label.toLowerCase()}?`, message, confirmLabel: "Read again"})) return;
    const started = await api(`/api/receipts/${record.id}/kind`, {method: "PATCH", body: JSON.stringify({kind})});
    if (started.run_id) await doc2WaitForRun(started.run_id);
    if (doc2 !== state) return;
    state.renderedKey = "";
    await doc2Extraction(state, state.runId);
    notice(`Read as ${label.toLowerCase()}.`);
  }, "link-button");
  change.disabled = Boolean(busy.inference);
  value.append(select, change);
  list.append(element("dt", "Receipt kind"), value);
  section.append(list);
  return section;
}
async function doc2WaitForRun(runId) {
  for (let tries = 0; tries < 240; tries += 1) {
    const run = await api(`/api/extraction-runs/${runId}`);
    if (!PENDING_RUN.includes(run.status)) {
      if (run.status !== "succeeded") throw new Error(run.error || `Reading ${statusLabel(run.status).toLowerCase()}.`);
      return run;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error("The reading is taking a while; it continues in the sidebar.");
}
function doc2Pending(state, record) {
  const kind = RECEIPT_KINDS[record.pending_details.kind] || record.pending_details.kind;
  return alertBox(`${kind} details were read for this receipt after you reviewed it. Applying them changes no amount and keeps your review.`,
                  {action: asyncButton("Apply details", async () => {
                    await api(`/api/receipts/${record.id}/details/apply`, {method: "POST", body: "{}"});
                    notice("Details applied.");
                    await doc2Changed(state);
                  }, "secondary")});
}
function doc2ShowRowEdits(state, shown) {
  const section = state.itemsSection;
  if (!section) return;
  section.classList.toggle("doc2-hide-edits", !shown);
  if (shown) return;
  section.querySelectorAll(".doc2-row-form").forEach(node => node.remove());
  for (const button of section.querySelectorAll(".doc2-row-correct")) button.setAttribute("aria-expanded", "false");
}
// A statement's rows each take a correction of their own, opened in a row under it.
function doc2RowCorrect(state, rows, record, allowDelete = false) {
  const items = Boolean(record.items), lines = (record.items || record.transactions).slice(0, 200);
  [...rows.querySelectorAll("tbody tr")].forEach((tr, index) => {
    const row = lines[index];
    if (!row?.correctable?.length) return;
    const open = element("button", "Correct", "link-button doc2-row-correct doc2-row-edit"); open.type = "button";
    open.setAttribute("aria-label", `Correct ${row.description || row.description_raw || "this row"}`); open.setAttribute("aria-expanded", "false");
    open.addEventListener("click", () => {
      const shown = tr.nextElementSibling?.classList.contains("doc2-row-form");
      tr.parentElement.querySelectorAll(".doc2-row-form").forEach(node => node.remove());
      for (const other of rows.querySelectorAll(".doc2-row-correct")) other.setAttribute("aria-expanded", "false");
      if (shown) return;
      const formRow = element("tr", "", "doc2-row-form"), cell = element("td"); cell.colSpan = tr.children.length;
      // A bill line's type and person are chosen in the table itself; Correct here is its price.
      const cc = confirmCorrect({recordType: items ? "receipt" : "transaction", recordId: items ? record.id : row.id, decision: false,
                                 correctable: items ? row.correctable.filter(item => item.field === "price") : row.correctable,
                                 preview: !items, saveCorrection: items ? body => api(`/api/receipts/${record.id}/items/${row.position}`, {method: "PATCH", body: JSON.stringify({price: body.changes.price, reason: body.reason})}) : null,
                                 onChange: () => doc2Changed(state), onClose: () => { formRow.remove(); open.setAttribute("aria-expanded", "false"); open.focus(); }});
      cc.el.querySelector(".cc-actions").hidden = true;
      cell.append(cc.el); formRow.append(cell); tr.after(formRow);
      open.setAttribute("aria-expanded", "true");
      cc.openCorrect();
    });
    tr.lastElementChild.append(open);
    if (items && allowDelete) {
      const remove = element("button", "Delete", "link-button danger-text doc2-row-edit"); remove.type = "button";
      remove.setAttribute("aria-label", `Delete ${row.description || "this item"}`);
      remove.addEventListener("click", async () => {
        if (!await confirmAction({title: `Delete ${row.description || "this item"}?`,
          message: "This line will be removed from the receipt and its category totals. The printed receipt total stays as recorded.",
          confirmLabel: "Delete item", danger: true})) return;
        remove.disabled = true;
        try {
          await api(`/api/receipts/${record.id}/items/${row.position}`, {method: "DELETE"});
          await doc2Changed(state);
          notice("Receipt item deleted.");
        } catch (error) { notice(error, true); remove.disabled = false; }
      });
      tr.lastElementChild.append(remove);
    }
  });
}
// A bill with lines for more than one person: the family's inbox shares it by line (docs/family.md "Sharing a bill by line").
function doc2ShareByLine(state, record) {
  const section = element("section", "", "doc2-section"), asked = Boolean(record.share_request);
  section.append(element("h3", "Share by line"));
  if (record.share?.member_id) { section.append(element("p", "Your family shared this bill by line; only your part counts.", "muted small")); return section; }
  section.append(element("p", asked ? "Asked. Your family's inbox will show this bill at the next sync; once they send it, only your part counts."
                                    : "This bill has lines for more than one person. Your family can share it so each person counts their own lines and their part of the taxes and fees.",
                         "muted small"));
  section.append(asyncButton(asked ? "Take the request back" : "Ask the family to share by line", async () => {
    await api(`/api/receipts/${record.id}/share-by-line`, {method: "PUT", body: JSON.stringify({requested: !asked})});
    await doc2Changed(state);
  }, asked ? "link-button" : "secondary"));
  return section;
}
function doc2Links(record, type) {
  const section = element("section", "", "doc2-section"), list = element("ul", "", "finance-list doc2-links");
  section.append(element("h3", record.document_kind === "bill" ? "Payment" : type === "receipt" ? "Matched charge" : type === "income_record" ? "Deposit" : "Matched records"));
  for (const link of record.links) {
    const other = link.counterpart, item = element("li");
    if (!other) continue;
    item.append(element("strong", other.name || other.description || "A record"), element("span", ` · ${dateText(other.date)} · `, "muted"), amount(other.amount), document.createTextNode(" "), statusBadge(link.review_status));
    if (other.document_id) item.append(document.createTextNode(" "), homeLink("Open its document", `#/documents/${other.document_id}`));
    list.append(item);
  }
  section.append(list);
  return section;
}
// Statement values, purchases and tax forms: receipt.js's record with this page's decision.
async function doc2Other(state, target, publication) {
  let record, path, render;
  if (publication.record_type === "asset") {
    const asset = (await api("/api/assets?include_archived=true")).find(row => row.id === publication.id);
    if (asset) { record = asset; path = `/api/assets/${asset.id}/review`; render = () => renderAssetRecord(target, publication); }
    else {
      record = await api(`/api/investments/valuations/by-asset/${publication.id}`).catch(() => null);
      path = record && `/api/investments/valuations/${record.id}/review`;
      render = () => renderInvestmentRecord(target, publication, `/api/investments/valuations/by-asset/${publication.id}`);
    }
  } else {
    const base = {investment_valuation: "/api/investments/valuations", investment_confirmation: "/api/investments/confirmations", tax_form: "/api/investments/tax-forms"}[publication.record_type];
    record = await api(`${base}/${publication.id}`).catch(() => null);
    path = `${base}/${publication.id}/review`;
    render = {investment_valuation: () => renderInvestmentRecord(target, publication, `${base}/${publication.id}`),
              investment_confirmation: () => renderConfirmationRecord(target, publication), tax_form: () => renderTaxFormRecord(target, publication)}[publication.record_type];
  }
  if (doc2 !== state) return;
  await render();
  if (doc2 !== state || !record) return;
  state.recordStatus = record.review_status;
  $("doc2-record-title").textContent = record.name || record.account?.name || "Recorded information";
  $("doc2-record-badge").replaceChildren(statusBadge(record.review_status));
  $("doc2-why").replaceChildren(...(record.issues?.length && ["proposed", "needs_review"].includes(record.review_status) ? [doc2Why(record.issues)] : []));
  state.reload = () => doc2Other(state, target, publication);
  doc2Decision(state, {recordType: publication.record_type, recordId: publication.id, reviewStatus: record.review_status, reviewSource: null, correctable: [],
                       reviewPath: path, undoBody: {status: "proposed"}});
  doc2Steps(state);
}
// A file holding several receipts (docs/documents.md): pick one, confirm the split once, or change it.
async function doc2ChangeSplit(state, starts, message) {
  await api(`/api/documents/${state.doc.id}/segments`, {method: "PUT", body: JSON.stringify({starts})});
  notice(message);
  state.renderedKey = "";
  await doc2Extraction(state, state.runId);
}
async function doc2Split(target, state, publication) {
  const split = await api(`/api/documents/${state.doc.id}/segments`);
  if (doc2 !== state) return;
  const segments = split.segments, chosen = Math.min(state.segment || 0, segments.length - 1);
  const published = publication.segments.find(part => part.ordinal === segments[chosen]?.ordinal) || publication.segments[chosen];
  const panel = element("section", "", "split-panel");
  panel.setAttribute("aria-label", "Receipts in this file");
  panel.append(element("h3", `This file holds ${segments.length} receipts`));
  if (!split.confirmed) panel.append(alertBox("Each receipt waits in To check until you confirm how the file was split.", {tone: "warning"}));
  const picker = element("div", "", "work-filters");
  segments.forEach((segment, index) => {
    const button = element("button", "", "filter-chip"); button.type = "button";
    button.setAttribute("aria-pressed", String(index === chosen));
    button.append(element("span", segment.merchant || `Receipt ${index + 1}`),
                  element("span", [segment.display?.total_minor, segment.purchase_date && dateText(segment.purchase_date)].filter(Boolean).join(" · "), "chip-count"));
    button.addEventListener("click", () => { state.segment = index; state.renderedKey = ""; doc2Extraction(state, state.runId); });
    picker.append(button);
  });
  panel.append(picker);
  const starts = segments.map(segment => segment.first_line_id), lines = segmentLines(segments[chosen], state.result?.layout_context?.lines || state.result?.lines);
  const actions = element("div", "", "button-row");
  if (!split.confirmed) actions.append(asyncButton("Confirm split", async () => {
    await api(`/api/documents/${state.doc.id}/segments/confirm`, {method: "POST", body: "{}"});
    notice("Split confirmed. Each receipt now counts by its own checks."); state.renderedKey = ""; await doc2Extraction(state, state.runId);
  }, "primary"));
  if (lines.length) actions.append(sourceButton(lines.map(line => line.id), ids => state.viewer.highlight(ids)));
  if (chosen < segments.length - 1) actions.append(asyncButton("Merge with next", () =>
    doc2ChangeSplit(state, starts.filter((_, index) => index !== chosen + 1), "Merging the two receipts. The file is read again with your split.")));
  panel.append(actions);
  if (lines.length > 1) {
    // Split one receipt in two at a line the user picks from its own text.
    const field = element("div", "", "field"), label = element("label", "Start a new receipt at"), select = document.createElement("select");
    select.id = "doc2-split-at"; label.htmlFor = select.id;
    select.append(...lines.slice(1).map(line => new Option(line.text.slice(0, 80), line.id)));
    const row = element("div", "", "button-row");
    row.append(select, asyncButton("Split here", () => doc2ChangeSplit(state, [...starts.slice(0, chosen + 1), select.value, ...starts.slice(chosen + 1)],
                                                                       "Splitting the receipt. The file is read again with your split.")));
    field.append(label, row);
    panel.append(field);
  }
  const record = element("div");  // The chosen receipt's record; rendering it replaces only this.
  target.append(panel, record);
  if (published?.status === "blocked") { record.append(alertBox(`Can't record this receipt: ${published.reason}`, {tone: "warning"})); return; }
  if (published?.id) await doc2Ledger(state, record, published.record_type, published.id, published.status === "kept_reviewed");
}

// History: the record's changes and decisions, newest first.
async function doc2History(state) {
  const host = $("doc2-history");
  if (!state.record) { host.replaceChildren(emptyState("Nothing is recorded from this document yet, so nothing has changed.")); return; }
  const entries = await loadHistory(state.type, state.record.id);
  if (doc2 !== state) return;
  host.replaceChildren(element("h3", "Changes"), historyList(entries));
}
