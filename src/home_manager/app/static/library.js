"use strict";
// The library's shared parts (records_v2.js draws the lists): document states and names, the sidebar's Inbox and
// Unfiled counts, and the dialogs for a description, moving, deleting and importing.
let libraryCatalog = null, pendingLibraryAction = null;

// Server work filters, named for what the user sees rather than processing internals.
const WORK_FILTERS = [["all", "All"], ["needs_text", "Not read yet"], ["ready_for_ledger", "Ready to record"], ["needs_review", "Needs review"], ["failed", "Couldn't process"]];
const PENDING = ["queued", "running"];
const isTable = doc => /\.(csv|xlsx)$/i.test(doc.relative_path);  // Tables are imported, never transcribed.
const isReadable = doc => /\.(png|jpe?g|pdf)$/i.test(doc.relative_path);
const isImage = doc => /\.(png|jpe?g)$/i.test(doc.relative_path);

// One library, two stores: Documents (papers you keep, plus the shared Inbox) and Money (receipts and statements).
const LIBRARY_SCOPES = {
  documents: {title: "Documents", all: "All documents", route: "#/documents",
              subtitle: "Your important papers: leases, policies, pay stubs, tax forms and more. New files arrive in the Inbox."},
  money: {title: "Receipts & statements", all: "All receipts & statements", route: "#/receipts",
          subtitle: "Proof of what you spent: receipts and your bank and card statements. They count in your spending and are reconciled."},
};
let libraryScope = "documents";
function folderLabel(folder) {
  return folder === "all" ? LIBRARY_SCOPES[libraryScope].all : folder === "trash" ? "Trash" : folder.replaceAll("_", " ");
}
function fileName(doc) { return doc.relative_path.split(/[\\/]/).pop(); }
function documentName(doc) { return doc.title || fileName(doc); }
function documentState(doc) {
  // One summary per document, derived from the per-step statuses (docs/documents.md "Browsing the library").
  if (doc.deleted_at) return "in_trash";
  if (PENDING.includes(doc.parse_status) || PENDING.includes(doc.extraction_status)) return "running";
  if (["failed", "interrupted"].includes(doc.parse_status) || ["failed", "interrupted"].includes(doc.extraction_status)) return "process_failed";
  if (isTable(doc)) return doc.ledger_status === "imported" ? "imported" : "ready_to_import";
  if (!doc.ledger_status && (doc.extraction_status === "cancelled" || doc.parse_status === "cancelled" && !doc.text_run_id)) return "cancelled";
  if (!doc.text_run_id) return "not_read";
  if (!doc.ledger_status) return "read";
  return {proposed: "needs_review", needs_review: "needs_review", verified: "recorded", rejected: "rejected"}[doc.ledger_status] || doc.ledger_status;
}
function matchText(doc) {
  // B9: a receipt's match to a card or bank charge (docs/documents.md "Browsing the library").
  if (!doc.reconciliation_status || doc.deleted_at) return "";
  return {matched: "Matched to a charge", proposed: "Match proposed", ambiguous: "Several possible charges", unmatched: "No matching charge yet"}[doc.reconciliation_status] || "";
}
function documentStateBadge(doc) {
  const badge = statusBadge(documentState(doc));
  const steps = isTable(doc) ? [["Import", doc.ledger_status || "not_imported"]]
    : [["Text", doc.parse_status || "not_extracted"], ["Ledger", doc.ledger_status || doc.extraction_status || "not_extracted"]];
  badge.title = steps.map(([label, state]) => `${label}: ${statusLabel(state)}`).join(" · ");
  return badge;
}
function setNavCount(target, count, label) {
  target.textContent = count ? String(count) : ""; target.hidden = !count;
  if (count) target.setAttribute("aria-label", `${count} ${label}`); else target.removeAttribute("aria-label");
}
async function renderNavCounts() {
  // Sidebar attention counts: Inbox/Unfiled under Documents, pending decisions on To check, the weekly check-in on Inventory.
  if (!configured) return;
  const catalog = await api("/api/folders?scope=documents");
  setNavCount($("nav-inbox").querySelector(".nav-count"), catalog.counts.Inbox, "in Inbox");
  setNavCount($("nav-unfiled").querySelector(".nav-count"), catalog.counts.Unfiled, "unfiled");
  await loadNavCounts();
}
function showFolder(folder) {
  // Inbox and Unfiled belong to Documents; Records (records_v2.js) keeps the folder in its URL.
  location.hash = `#/documents?folder=${encodeURIComponent(folder)}`;
}
for (const id of ["nav-inbox", "nav-unfiled"]) $(id).addEventListener("click", () => showFolder($(id).dataset.folder));

async function afterLibraryChange() {
  // Records v2 redraws when the dialog closes (records_v2.js); the document page reloads its document here.
  if (doc2) await refreshDocumentV2();
}
async function eachDocument(docs, request) {
  // Applies one action per document; reports every failure instead of stopping at the first. Each request's own
  // answer is counted (one request per document, so the server never sees the batch).
  const failures = [];
  let done = 0;
  for (const doc of docs) {
    try { await request(doc); done += 1; } catch (error) { failures.push(`${documentName(doc)}: ${error.message}`); }
  }
  return {done, failures};
}
async function restoreDocuments(docs) {
  const {done: restored, failures} = await eachDocument(docs, doc => api(`/api/documents/${doc.id}/restore`, {method:"POST", body:JSON.stringify({expected_hash:doc.current_hash})}));
  await afterLibraryChange();
  if (restored) notice(restored === 1 ? "Document restored to the library." : `${restored} documents restored to the library.`);
  if (failures.length) notice(`${failures.length} couldn't be restored. ${failures.join(" ")}`, true);
}
let describing = null;
function openDescription(doc) {
  // The user's own short label; clearing it returns to the AI's description or the business name.
  describing = doc;
  $("description-document").textContent = fileName(doc);
  $("description-input").value = doc.description_source === "user" ? doc.description : "";
  $("description-input").placeholder = doc.description_source === "model" ? doc.description : "For example: Snacks/Office";
  $("description-error").textContent = "";
  $("description-dialog").showModal(); $("description-input").focus();
}
$("cancel-description").addEventListener("click", () => $("description-dialog").close());
$("description-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const updated = await api(`/api/documents/${describing.id}/description`, {method: "PUT", body: JSON.stringify({description: $("description-input").value.trim() || null})});
    $("description-dialog").close();
    if (doc2?.doc?.id === updated.id) renameDocumentV2(updated);
    notice(updated.description_source === "user" ? "Description saved." : "Your description was removed; the AI's description is used.");
  } catch (error) { $("description-error").textContent = error.message; }
});

function openLibraryAction(docs, action) {
  if (!docs.length) return;
  pendingLibraryAction = {docs, action};
  const count = docs.length, plural = count === 1 ? "document" : `${count} documents`;
  $("library-action-title").textContent = action === "trash" ? `Delete ${count === 1 ? "document" : plural}?` : `Move ${plural}`;
  $("library-action-document").textContent = count === 1 ? `${documentName(docs[0])} — ${docs[0].relative_path}`
    : docs.slice(0, 3).map(documentName).join(", ") + (count > 3 ? ` and ${count - 3} more` : "");
  $("library-action-description").textContent = action === "trash" ? "This removes the document from the active library and puts it in Trash. You can restore it. Preserved copies are not deleted from disk, and scanning Inbox again will not restore it automatically." : "Move the Library file to this folder. Its preserved copy stays unchanged. Edited Library files will not be overwritten.";
  $("move-folder-label").hidden = action !== "move";
  $("move-folder").replaceChildren(new Option("Unfiled", "Unfiled"));
  for (const [store, folders] of Object.entries(libraryCatalog.stores)) {
    const group = document.createElement("optgroup"); group.label = LIBRARY_SCOPES[store].title;
    for (const folder of folders) group.append(new Option(folder.replaceAll("_", " "), folder));
    $("move-folder").append(group);
  }
  $("move-folder").value = docs[0].folder === "Inbox" ? "Unfiled" : docs[0].folder;
  $("confirm-library-action").textContent = action === "trash" ? "Delete to Trash" : count === 1 ? "Move document" : `Move ${plural}`;
  $("confirm-library-action").className = action === "trash" ? "danger" : "primary";
  $("library-action-error").textContent = ""; $("library-action-dialog").showModal();
  $("cancel-library-action").focus();
}
$("cancel-library-action").addEventListener("click", () => { pendingLibraryAction = null; $("library-action-dialog").close(); });
$("library-action-dialog").addEventListener("cancel", () => { pendingLibraryAction = null; });
$("confirm-library-action").addEventListener("click", async () => {
  if (!pendingLibraryAction) return;
  const {docs, action} = pendingLibraryAction, folder = $("move-folder").value;
  $("confirm-library-action").disabled = true;
  try {
    const {done, failures} = await eachDocument(docs, doc => api(`/api/documents/${doc.id}/${action === "trash" ? "trash" : "folder"}`,
      {method: action === "trash" ? "POST" : "PUT", body: JSON.stringify(action === "trash" ? {expected_hash: doc.current_hash, confirmed: true} : {expected_hash: doc.current_hash, folder})}));
    if (!done) { $("library-action-error").textContent = failures.join(" "); return; }
    pendingLibraryAction = null; $("library-action-dialog").close();
    await afterLibraryChange();
    notice(action === "trash" ? (done === 1 ? "Document moved to Trash. You can restore it from Trash." : `${done} documents moved to Trash. You can restore them from Trash.`)
      : (done === 1 ? "Document moved to the selected folder." : `${done} documents moved to the selected folder.`));
    if (failures.length) notice(`${failures.length} couldn't be changed. ${failures.join(" ")}`, true);
  } catch (error) { $("library-action-error").textContent = error.message; }
  finally { $("confirm-library-action").disabled = false; }
});

const MAP_KEYS = ["date", "description", "amount", "debit", "credit"];
const READ_FIRST = "Read this document first.";  // The server's refusal for a PDF with no saved reading (finance/ledger.py pdf_reading).
const isPdf = doc => /\.pdf$/i.test(doc.relative_path);
let importDoc = null, importDone = null, importOpener = null, importPdf = null, importAfterPdf = false;
// onDone runs after the rows are imported (the Money screens reload; money_v2.js importPicker). missed: opened from a
// library row's or document page's Add missed transactions, which adds only rows not already recorded (docs/documents.md
// "Transaction imports").
async function openImport(doc, {onDone = null, missed = false} = {}) {
  importDoc = doc; importDone = onDone; importOpener = document.activeElement;
  $("import-title").textContent = !missed ? "Import transactions" : isPdf(doc) ? "Add transactions the reading missed" : "Add missed transactions";
  $("confirm-import").textContent = missed ? "Add missed transactions" : "Import transactions";
  // PDF mode (docs/documents.md "PDFs"): what the user has chosen so far, as the preview request sends it. A choice left
  // empty is the server's default (tables: all, sign: the account type's); ticks are only the rows the user changed.
  importPdf = isPdf(doc) ? {tables: null, sign: null, ticked: new Set(), unticked: new Set(), result: null, sequence: 0, latest: null, matched: false, importing: false, done: false} : null;
  $("import-document").textContent = doc.relative_path;
  const select = $("import-account"); select.replaceChildren(new Option("New account…", ""));
  const accounts = await api("/api/finance/accounts");
  for (const account of accounts) select.add(new Option(`${account.display_name} · ${account.currency}`, account.id));
  if (importPdf) {
    // The account starts from the PDF's printed last four, never from the remembered CSV account (FR-13).
    select.add(new Option("Choose an account…", "none"), 0); select.value = "none";
  } else {
    let remembered = "";
    try { remembered = localStorage.getItem("home-manager-import-account") || ""; } catch { remembered = ""; }
    select.value = accounts.some(account => String(account.id) === remembered) ? remembered : accounts.length ? String(accounts[0].id) : "";
  }
  $("import-new-account").hidden = select.value !== "";
  for (const key of MAP_KEYS) $(`import-map-${key}`).replaceChildren(new Option("Detect", ""));
  $("import-preview").replaceChildren(); $("import-issues").replaceChildren(); $("import-status").textContent = "";
  if (importPdf || importAfterPdf) $("import-date-format").value = "auto";
  importAfterPdf = Boolean(importPdf);
  showImportMode();
  $("confirm-import").disabled = true;
  $("import-dialog").showModal();
  await previewImport();
}
function showImportMode() {
  const pdf = Boolean(importPdf);
  for (const id of ["import-csv-map", "import-csv-sign", "import-csv-wrap"]) $(id).hidden = pdf;
  for (const id of ["import-account-note", "import-tables", "import-pdf-wrap", "import-pdf-sign-field", "import-year-field", "import-sign-note", "import-read-first"]) $(id).hidden = true;
  $("import-body").hidden = false; $("import-actions").hidden = false;
  for (const control of $("import-body").querySelectorAll("input, select, button")) control.disabled = false;  // A finished PDF import locks them.
  $("preview-import").disabled = false;
  $("import-pdf-rows").replaceChildren(); $("import-table-list").replaceChildren();
  if (!pdf) return;
  $("import-last-four").value = ""; delete $("import-last-four").dataset.touched;
  $("import-pdf-wrap").hidden = false;
  // The year is a choice the PDF never makes for you; the list only offers recent years (no default).
  const year = $("import-year"), now = new Date().getFullYear();
  year.replaceChildren(new Option("Choose…", ""));
  for (let value = now + 1; value >= now - 30; value -= 1) year.add(new Option(String(value), String(value)));
  $("import-pdf-sign").value = "";
}
function importMapping() {
  const mapping = {date_format: $("import-date-format").value, sign: $("import-sign").value};
  for (const key of MAP_KEYS) if ($(`import-map-${key}`).value) mapping[key] = $(`import-map-${key}`).value;
  return mapping;
}
function importBody() {
  const accountId = Number($("import-account").value) || null;
  return {expected_hash: importDoc.current_hash, mapping: importMapping(),
          ...(accountId ? {account_id: accountId} : {currency: $("import-currency").value.trim().toUpperCase()})};
}
async function previewImport() {
  if (importPdf) return previewPdf();
  $("confirm-import").disabled = true;
  try {
    const result = await api(`/api/documents/${importDoc.id}/transaction-import/preview`, {method:"POST", body:JSON.stringify(importBody())});
    for (const key of MAP_KEYS) {
      const select = $(`import-map-${key}`), chosen = select.value;
      select.replaceChildren(new Option(result.mapping[key] ? `Detect (${result.mapping[key]})` : "Not used", ""));
      for (const column of result.counts.columns) select.add(new Option(column, column));
      select.value = chosen;
    }
    $("import-preview").replaceChildren();
    for (const row of result.rows) {
      const tr = document.createElement("tr");
      cell(tr, row.locator.rows[0]); cell(tr, "").appendChild(dateDisplay(row.posted_date)); cell(tr, row.description);
      const value = cell(tr, ""); value.className = "numeric"; value.appendChild(amount(row.display_amount));
      $("import-preview").appendChild(tr);
    }
    $("import-issues").replaceChildren(...result.issues.map(issue => element("li", issue)));
    $("import-status").textContent = result.error || `${result.counts.parsed} rows ready, ${result.counts.rejected} not importable. Money out ${result.totals.outflow}; money in ${result.totals.inflow}. Dates read as ${result.mapping.date_format}.`;
    $("confirm-import").disabled = !result.counts.parsed;
  } catch (error) { $("import-status").textContent = error.message; }
}

// PDF mode (FR-28) -------------------------------------------------------------------------------------------------
// The server decides every row, status and total (finance/ledger.py preview_pdf_import); this only sends the choices and draws the answer.
function pdfBody({forImport = false} = {}) {
  const value = $("import-account").value, body = {expected_hash: importDoc.current_hash, date_format: $("import-date-format").value};
  if (/^\d+$/.test(value)) body.account_id = Number(value);
  else if (value === "") {
    // A new account: the import creates it in its own transaction (FR-14). A preview takes the type and currency typed so far.
    const currency = $("import-currency").value.trim().toUpperCase(), lastFour = $("import-last-four").value.trim(), institution = $("import-institution").value.trim();
    if (!forImport) { body.account_type = $("import-type").value; if (/^[A-Z]{3}$/.test(currency)) body.currency = currency; }
    if (institution && /^[A-Z]{3}$/.test(currency) && /^(\d{4})?$/.test(lastFour)) {
      body.new_account = {institution, account_type: $("import-type").value, currency, ...(lastFour ? {last_four: lastFour} : {})};
    }
  }
  if (importPdf.tables) body.tables = importPdf.tables;
  if ($("import-year").value) body.year = Number($("import-year").value);
  if (importPdf.sign) body.sign = importPdf.sign;
  if (importPdf.ticked.size) body.ticked = [...importPdf.ticked];
  if (importPdf.unticked.size) body.unticked = [...importPdf.unticked];
  return body;
}
function previewPdf() {
  const state = importPdf;
  state.latest = runPdfPreview(state);
  return state.latest;
}
async function runPdfPreview(state) {
  const sequence = ++state.sequence;
  try {
    const result = await api(`/api/documents/${importDoc.id}/transaction-import/preview`, {method: "POST", body: JSON.stringify(pdfBody())});
    if (importPdf !== state || sequence !== state.sequence) return;  // Closed, or a newer choice is already on its way.
    state.result = result;
    showPdfPreview(result);
  } catch (error) {
    if (importPdf !== state || sequence !== state.sequence) return;
    state.result = null;
    if (error.message === READ_FIRST) showReadFirst();
    else { $("import-status").textContent = error.message; updatePdfImport(); }
  }
}
function showReadFirst() {
  for (const id of ["import-body", "import-actions", "import-tables", "import-pdf-wrap"]) $(id).hidden = true;
  $("import-read-first").hidden = false; $("import-read").disabled = false;
  $("import-issues").replaceChildren(); $("import-status").textContent = "";
  $("import-read").focus();
}
function pdfTableItem(table, tables) {
  const item = element("li"), heads = table.headings.filter(Boolean).join(" · "), count = `${table.row_count} row${table.row_count === 1 ? "" : "s"}`;
  if (!table.selectable) {
    const parent = tables.find(other => other.id === table.linked_to);
    item.append(element("span", parent ? `Page ${table.page} · continues the table on page ${parent.page} (${count})` : `Page ${table.page} · not a transactions table${heads ? ` · ${heads}` : ""}`, "muted"));
    return item;
  }
  const label = element("label", "", "check-field"), box = document.createElement("input");
  box.type = "checkbox"; box.checked = table.selected; box.dataset.key = `table:${table.id}`; box.dataset.table = table.id;
  box.addEventListener("change", () => {
    importPdf.tables = [...$("import-table-list").querySelectorAll("input[data-table]")].filter(input => input.checked).map(input => input.dataset.table);
    previewImport();
  });
  label.append(box, element("span", `Page ${table.page}${heads ? ` · ${heads}` : ""} · ${count}${table.kind === "rebuilt" ? " (rebuilt from the page)" : ""}`));
  item.append(label);
  return item;
}
const PDF_ROW_STATUS = {new: "not_imported", already_recorded: "imported", rejected_earlier: "rejected", rejected: "rejected"};
function pdfRow(row) {
  const tr = document.createElement("tr");
  cell(tr, row.page); cell(tr, row.date); cell(tr, row.description);
  const printed = cell(tr, row.amount); printed.className = "numeric";
  const signed = cell(tr, ""); signed.className = "numeric"; signed.appendChild(amount(row.display_amount));
  const status = cell(tr, ""); status.appendChild(statusBadge(PDF_ROW_STATUS[row.status], "", row.status_text));
  for (const label of row.labels) status.appendChild(element("small", label, "import-row-label"));
  const tick = cell(tr, ""), box = document.createElement("input");
  box.type = "checkbox"; box.checked = row.ticked; box.disabled = Boolean(row.rejected); box.dataset.key = `row:${row.key}`;
  box.setAttribute("aria-label", `Import page ${row.page} row ${row.row}: ${row.description}`);
  box.addEventListener("change", () => {
    const [add, remove] = box.checked ? [importPdf.ticked, importPdf.unticked] : [importPdf.unticked, importPdf.ticked];
    add.add(row.key); remove.delete(row.key);
    previewImport();
  });
  tick.appendChild(box);
  return tr;
}
function pdfSummary(result) {
  if (result.blocked) return result.blocked;
  if (result.required.length) return result.required_messages.join(" ");
  const counts = result.counts;
  if (!counts.seen) return "No rows to import in the selected tables.";
  // Ticked New rows and Already recorded rows are totalled apart (FR-05); both come from the server.
  const recorded = counts.already_recorded + counts.rejected_earlier ? ` Already recorded: money out ${result.already_recorded_totals.outflow}; money in ${result.already_recorded_totals.inflow}.` : "";
  return `${counts.new} new, ${counts.already_recorded} already recorded${counts.rejected_earlier ? `, ${counts.rejected_earlier} rejected earlier` : ""}, ${counts.rejected} not importable, ${counts.left_out} left out. New: money out ${result.totals.outflow}; money in ${result.totals.inflow}.${recorded}`;
}
function showPdfPreview(result) {
  const state = importPdf, focused = document.activeElement?.dataset?.key || null;
  $("import-read-first").hidden = true; $("import-body").hidden = false; $("import-actions").hidden = false; $("import-pdf-wrap").hidden = false;
  // The account: the match the first time, then the user's own choice. The note says why it was chosen.
  const select = $("import-account"), match = result.account_match;
  if (!state.matched && select.value === "none" && match && [...select.options].some(option => option.value === String(match.account_id))) select.value = String(match.account_id);
  state.matched = true;
  $("import-new-account").hidden = select.value !== "";
  const note = $("import-account-note");
  note.textContent = match && select.value === String(match.account_id) ? match.text : select.value === "none" ? "No saved account matches this PDF. Choose one, or add a new account." : "";
  note.hidden = !note.textContent;
  if (select.value === "" && result.new_account_last_four && !$("import-last-four").dataset.touched) $("import-last-four").value = result.new_account_last_four;
  $("import-tables").hidden = !result.tables.length;
  $("import-table-list").replaceChildren(...result.tables.map(table => pdfTableItem(table, result.tables)));
  $("import-year-field").hidden = !(result.required.includes("year") || $("import-year").value);
  // A single Amount column needs a sign; the default is the account type's, and only a choice of yours is sent.
  const signed = result.signed || result.required.includes("sign") || Boolean(state.sign);
  $("import-pdf-sign-field").hidden = !signed;
  $("import-pdf-sign").value = result.sign || "";
  $("import-sign-note").textContent = !signed ? "" : state.sign ? "" : result.sign_default ? "This is the usual sign for this type of account." : "";
  $("import-sign-note").hidden = !$("import-sign-note").textContent;
  $("import-pdf-rows").replaceChildren(...result.rows.map(pdfRow));
  $("import-issues").replaceChildren(...result.issues.map(issue => element("li", issue.message)));
  if (!state.done) $("import-status").textContent = pdfSummary(result);
  updatePdfImport();
  if (focused) document.querySelector(`#import-dialog [data-key="${CSS.escape(focused)}"]`)?.focus();
}
function pdfAccountReady() {
  const value = $("import-account").value;
  if (/^\d+$/.test(value)) return true;
  return value === "" && Boolean($("import-institution").value.trim()) && /^[A-Za-z]{3}$/.test($("import-currency").value.trim()) && /^(\d{4})?$/.test($("import-last-four").value.trim());
}
function pdfBlocked(state) {
  const result = state.result;
  return !result || Boolean(result.blocked) || result.required.length > 0 || !pdfAccountReady() || !result.rows.some(row => row.ticked && !row.rejected);
}
function updatePdfImport() {
  const state = importPdf;
  if (state) $("confirm-import").disabled = state.importing || state.done || pdfBlocked(state);
}
async function importPdfRows() {
  const state = importPdf;
  state.importing = true; updatePdfImport();
  try {
    // A field's change event fires as the click lands and starts a preview: that settles first, and may block the import.
    await state.latest;
    if (importPdf !== state || pdfBlocked(state)) return;
    const done = await api(`/api/documents/${importDoc.id}/transaction-imports`, {method: "POST", body: JSON.stringify({...pdfBody({forImport: true}), reading_id: state.result.reading_id})});
    state.done = true;
    // The summary stays in the dialog's live region; the Money screens behind it reload.
    $("import-status").textContent = `Imported ${done.inserted} new transactions into ${done.account_name}; ${done.duplicates} were already recorded, ${done.rejected} rows were not importable and ${done.left_out} were left out.`
      + (done.pages_without_rows ? ` ${done.pages_without_rows} pages had no rows.` : "");
    for (const control of $("import-dialog").querySelectorAll("#import-body :is(input, select, button), #import-pdf-wrap input")) control.disabled = true;
    $("preview-import").disabled = true;
    $("close-import").focus();
    loadNavCounts().catch(() => {});
    if (importDone) Promise.resolve(importDone(done)).catch(error => notice(error, true));
  } catch (error) { $("import-status").textContent = error.message; }
  finally { state.importing = false; updatePdfImport(); }
}
// Read, then preview in place (FR-27): the reading job runs on its own queue and the dialog waits for it.
async function waitForReading(runId, state) {
  for (;;) {
    const run = await api(`/api/receipt-runs/${runId}`);
    if (importPdf !== state) return null;
    if (!PENDING.includes(run.status)) return run;
    await new Promise(resolve => setTimeout(resolve, 700));
    if (importPdf !== state) return null;
  }
}
$("import-read").addEventListener("click", async () => {
  const state = importPdf;
  $("import-read").disabled = true; $("import-status").textContent = "Reading the document …";
  try {
    const started = await api(`/api/documents/${importDoc.id}/receipt-runs`, {method: "POST", body: JSON.stringify({blob_hash: importDoc.current_hash})});
    const run = await waitForReading(started.run_id, state);
    if (!run) return;
    if (!["succeeded", "partial"].includes(run.status)) throw new Error(run.error || `The reading ${statusLabel(run.status).toLowerCase()}.`);
    $("import-status").textContent = "";
    await previewImport();
    // The Read button is gone once the preview shows; keep focus inside the dialog.
    if (importPdf === state && !$("import-body").hidden && (document.activeElement === document.body || document.activeElement === $("import-read"))) $("import-account").focus();
  } catch (error) { if (importPdf === state) { $("import-status").textContent = error.message; $("import-read").disabled = false; } }
});
$("import-account").addEventListener("change", () => {
  $("import-new-account").hidden = $("import-account").value !== "";
  previewImport();
});
for (const id of ["import-date-format", "import-sign", ...MAP_KEYS.map(key => `import-map-${key}`)]) $(id).addEventListener("change", previewImport);
$("import-year").addEventListener("change", previewImport);
$("import-pdf-sign").addEventListener("change", () => { importPdf.sign = $("import-pdf-sign").value || null; previewImport(); });
// A partly typed new account still moves the sign default and the currency checks (FR-15).
for (const id of ["import-institution", "import-type", "import-currency", "import-last-four"]) {
  $(id).addEventListener("input", () => { if (id === "import-last-four") $(id).dataset.touched = "1"; updatePdfImport(); });
  $(id).addEventListener("change", () => { if (importPdf) previewImport(); });
}
$("preview-import").addEventListener("click", previewImport);
$("close-import").addEventListener("click", () => $("import-dialog").close());
$("import-dialog").addEventListener("close", () => {
  // A PDF dialog may be waiting on a preview or a reading: stop listening, and give focus back to what opened it.
  const pdf = importPdf; importPdf = null;
  if (pdf && (document.activeElement === document.body || !document.activeElement?.isConnected) && importOpener?.isConnected) importOpener.focus();
});
$("confirm-import").addEventListener("click", async () => {
  if (importPdf) return importPdfRows();
  try {
    $("confirm-import").disabled = true;
    if (!$("import-account").value) {
      const account = await api("/api/finance/accounts", {method:"POST", body:JSON.stringify({institution:$("import-institution").value.trim(),
        account_type:$("import-type").value, currency:$("import-currency").value.trim().toUpperCase(), last_four:$("import-last-four").value.trim() || null})});
      $("import-account").add(new Option(`${account.display_name} · ${account.currency}`, account.id)); $("import-account").value = account.id;
    }
    const result = await api(`/api/documents/${importDoc.id}/transaction-imports`, {method:"POST", body:JSON.stringify(importBody())});
    try { localStorage.setItem("home-manager-import-account", String(result.account_id)); } catch { /* Convenience only. */ }
    $("import-dialog").close();
    notice(`Imported ${result.inserted} new transactions; ${result.duplicates} were already recorded and ${result.rejected} rows were not importable.`);
    loadNavCounts().catch(() => {});
    if (importDone) Promise.resolve(importDone(result)).catch(error => notice(error, true));
  } catch (error) { $("import-status").textContent = error.message; $("confirm-import").disabled = false; }
});
