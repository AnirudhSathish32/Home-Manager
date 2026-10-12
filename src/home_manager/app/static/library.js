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
let importDoc = null, importDone = null;
// onDone runs after the rows are imported (the Money screens reload; money_v2.js importPicker).
async function openImport(doc, {onDone = null} = {}) {
  importDoc = doc; importDone = onDone;
  $("import-document").textContent = doc.relative_path;
  const select = $("import-account"); select.replaceChildren(new Option("New account…", ""));
  const accounts = await api("/api/finance/accounts");
  for (const account of accounts) select.add(new Option(`${account.display_name} · ${account.currency}`, account.id));
  let remembered = "";
  try { remembered = localStorage.getItem("home-manager-import-account") || ""; } catch { remembered = ""; }
  select.value = accounts.some(account => String(account.id) === remembered) ? remembered : accounts.length ? String(accounts[0].id) : "";
  $("import-new-account").hidden = select.value !== "";
  for (const key of MAP_KEYS) $(`import-map-${key}`).replaceChildren(new Option("Detect", ""));
  $("import-preview").replaceChildren(); $("import-issues").replaceChildren(); $("import-status").textContent = "";
  $("confirm-import").disabled = true;
  $("import-dialog").showModal();
  await previewImport();
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
$("import-account").addEventListener("change", () => { $("import-new-account").hidden = $("import-account").value !== ""; previewImport(); });
for (const id of ["import-date-format", "import-sign", ...MAP_KEYS.map(key => `import-map-${key}`)]) $(id).addEventListener("change", previewImport);
$("preview-import").addEventListener("click", previewImport);
$("close-import").addEventListener("click", () => $("import-dialog").close());
$("confirm-import").addEventListener("click", async () => {
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
