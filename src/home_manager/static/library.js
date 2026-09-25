"use strict";
let activeFolder = "all", activeStatus = "all", searchQuery = "", activeFrom = "", activeTo = "", activeSort = "date";
let libraryCatalog = null, pendingLibraryAction = null;
let renderedDocuments = "", renderedFolders = "";  // Last rendered data, to skip identical re-renders.
const selection = new Map();  // Selected documents on the current page: id -> document.

// Server work filters, named for what the user sees rather than processing internals.
const WORK_FILTERS = [["all", "All"], ["needs_text", "Not read yet"], ["ready_for_ledger", "Ready to record"], ["needs_review", "Needs review"], ["failed", "Couldn't process"]];
const PENDING = ["queued", "running"];
const isTable = doc => /\.(csv|xlsx)$/i.test(doc.relative_path);  // Tables are imported, never transcribed.
const isReadable = doc => /\.(png|jpe?g|pdf)$/i.test(doc.relative_path);

function folderLabel(folder) {
  return folder === "all" ? "All documents" : folder === "trash" ? "Trash" : folder.replaceAll("_", " ");
}
function fileName(doc) { return doc.relative_path.split(/[\\/]/).pop(); }
function documentName(doc) { return doc.title || fileName(doc); }
function documentState(doc) {
  // One summary per document, derived from the per-step statuses (docs/ui-design-plan.md §3.7).
  if (doc.deleted_at) return "in_trash";
  if (PENDING.includes(doc.parse_status) || PENDING.includes(doc.extraction_status)) return "running";
  if (["failed", "interrupted"].includes(doc.parse_status) || ["failed", "interrupted"].includes(doc.extraction_status)) return "process_failed";
  if (isTable(doc)) return doc.ledger_status === "imported" ? "imported" : "ready_to_import";
  if (!doc.ledger_status && (doc.extraction_status === "cancelled" || doc.parse_status === "cancelled" && !doc.text_run_id)) return "cancelled";
  if (!doc.text_run_id) return "not_read";
  if (!doc.ledger_status) return "read";
  return {proposed: "needs_review", needs_review: "needs_review", verified: "recorded", rejected: "rejected"}[doc.ledger_status] || doc.ledger_status;
}
function documentStateBadge(doc) {
  const badge = statusBadge(documentState(doc));
  const steps = isTable(doc) ? [["Import", doc.ledger_status || "not_imported"]]
    : [["Text", doc.parse_status || "not_extracted"], ["Ledger", doc.ledger_status || doc.extraction_status || "not_extracted"]];
  badge.title = steps.map(([label, state]) => `${label}: ${statusLabel(state)}`).join(" · ");
  return badge;
}
function reload() { docOffset = 0; selection.clear(); loadDocuments().catch(error => notice(error, true)); }
function folderButton(folder, count) {
  const button = element("button", "", "folder-link"); button.type = "button";
  button.dataset.folder = folder;
  button.classList.toggle("empty", !count && folder !== activeFolder);
  button.append(element("span", folderLabel(folder)), element("span", count, "folder-count"));
  if (folder === activeFolder) button.setAttribute("aria-current", "page");
  else button.removeAttribute("aria-current");
  button.addEventListener("click", () => { activeFolder = folder; reload(); });
  return button;
}
function setNavCount(target, count, label) {
  target.textContent = count ? String(count) : ""; target.hidden = !count;
  if (count) target.setAttribute("aria-label", `${count} ${label}`); else target.removeAttribute("aria-label");
}
async function renderNavCounts(catalog) {
  // Sidebar attention counts: Inbox/Unfiled under Documents, pending review on Finances.
  setNavCount($("nav-inbox").querySelector(".nav-count"), catalog.counts.Inbox, "in Inbox");
  setNavCount($("nav-unfiled").querySelector(".nav-count"), catalog.counts.Unfiled, "unfiled");
  const queue = await api("/api/finance/tools/review_queue", {method:"POST", body:"{}"});
  setNavCount($("nav-review-count"), queue.records.length + queue.links.length + queue.issues.length, "need review");
}
function showFolder(folder) {
  activeFolder = folder; activeStatus = "all";
  if (location.hash !== "#/documents") location.hash = "#/documents";
  reload();
}
for (const id of ["nav-inbox", "nav-unfiled"]) $(id).addEventListener("click", () => showFolder($(id).dataset.folder));
function renderFolders(catalog) {
  libraryCatalog = catalog;
  renderNavCounts(catalog).catch(() => {});
  const key = JSON.stringify([catalog, activeFolder, activeStatus]);
  if (key === renderedFolders) return;
  renderedFolders = key;
  $("folder-tree").replaceChildren(...["all", ...catalog.folders, "trash"].map(folder => folderButton(folder, catalog.counts[folder])));
  $("work-filters").replaceChildren(...WORK_FILTERS.map(([key, label]) => {
    const count = key === "all" ? catalog.counts.all : catalog.work[key];
    const chip = element("button", "", "filter-chip"); chip.type = "button"; chip.dataset.filter = key;
    chip.append(element("span", label), element("span", count, "chip-count"));
    chip.setAttribute("aria-pressed", String(key === activeStatus));
    chip.addEventListener("click", () => { activeStatus = key; reload(); });
    return chip;
  }));
  $("folder-breadcrumb").textContent = folderLabel(activeFolder);
  $("empty-trash").hidden = activeFolder !== "trash";
  $("empty-trash").disabled = false;
  $("folder-description").textContent = activeFolder === "trash" ? "Restore documents or empty Trash to permanently delete them."
    : activeFolder === "Inbox" ? "Newly dropped files waiting to be read and filed." : activeFolder === "Unfiled" ? "Documents whose type, merchant or date could not be confirmed. Extract them to the ledger or use Move." : "";
}
function actionButton(label, callback, className = "") {
  const button = element("button", label, className); button.type = "button";
  button.addEventListener("click", () => Promise.resolve().then(callback).catch(error => notice(error, true)));
  return button;
}
function stepButton(label, path, body, message, className = "primary-action") {
  const button = element("button", label, className); button.type = "button"; button.dataset.step = "true"; button.disabled = busy.inference;
  button.addEventListener("click", async () => {
    try {
      busy.inference = true; controls();
      await api(path, {method:"POST", body:JSON.stringify(body)});
      notice(message); await loadDocuments();
    } catch (error) { busy.inference = false; controls(); notice(error, true); }
  });
  return button;
}
function nextStep(doc) {
  // The one most useful action for this document, so routine work never needs the inspector.
  const name = documentName(doc);
  let button = null;
  if (doc.deleted_at) button = actionButton("Restore", () => restoreDocuments([doc]), "primary-action");
  else if (isTable(doc)) button = actionButton("Import transactions", () => openImport(doc), "primary-action");
  else if (!doc.text_run_id && !PENDING.includes(doc.parse_status))
    button = stepButton("Read", `/api/documents/${doc.id}/receipt-runs`, {blob_hash: doc.current_hash}, "Reading started. Progress shows in the sidebar.");
  else if (doc.text_run_id && !doc.ledger_status && !PENDING.includes(doc.extraction_status))
    button = stepButton("Record", `/api/documents/${doc.id}/extraction-runs`, {parse_run_id: doc.text_run_id}, "Ledger extraction started. Progress shows in the sidebar.");
  if (button && !isTable(doc) && !doc.deleted_at) button.setAttribute("aria-label", `${button.textContent} ${name}`);
  return button;
}
function rowMenu(doc) {
  const items = [actionButton("Edit description…", () => openDescription(doc)), actionButton(`Versions (${doc.version_count})`, () => showVersions(doc))];
  if (!doc.deleted_at) {
    items.push(actionButton("Move", () => openLibraryAction([doc], "move")));
    items.push(actionButton("Delete", () => openLibraryAction([doc], "trash"), "danger-text"));
  }
  items.push(element("small", doc.managed_path ? `Library/${doc.managed_path}` : "Managed copy pending", "managed-path"));
  return menu("More actions", items);
}
function renderSelection() {
  const docs = [...selection.values()], trash = activeFolder === "trash";
  $("selection-bar").hidden = !docs.length;
  $("selection-count").textContent = `${docs.length} selected`;
  for (const id of ["read-selected", "move-selected", "trash-selected"]) $(id).hidden = trash;
  $("restore-selected").hidden = !trash;
  $("read-selected").disabled = busy.inference || !docs.some(isReadable);
  const boxes = [...document.querySelectorAll("#documents input[data-select]")];
  for (const box of boxes) box.checked = selection.has(Number(box.dataset.select));
  $("select-all").checked = boxes.length > 0 && boxes.every(box => box.checked);
  $("select-all").indeterminate = docs.length > 0 && !$("select-all").checked;
}
function clearFilters() {
  searchQuery = activeFrom = activeTo = ""; activeStatus = "all";
  $("document-search").value = $("date-from").value = $("date-to").value = "";
  reload();
}
function emptyMessage() {
  if (searchQuery || activeStatus !== "all" || activeFrom || activeTo) return emptyState("No documents match these filters.", actionButton("Clear filters", clearFilters));
  if (activeFolder === "trash") return emptyState("Trash is empty.");
  if (activeFolder !== "all") return emptyState(`No documents in ${folderLabel(activeFolder)}.`);
  const box = emptyState("Your library is empty. Drop files into your Inbox folder, or scan your source folders from Processing.");
  if (inboxDirectory) box.append(element("code", inboxDirectory), copyButton(inboxDirectory, "Copy Inbox path"));
  return box;
}
let deferredDocuments = null;
function renderDocuments(data) {
  // Polling re-fetches often; re-render only on change so open menus and focus survive.
  const key = JSON.stringify(data);
  if (key === renderedDocuments) return;
  if (document.querySelector("#documents .menu-list:not([hidden])")) { deferredDocuments = data; return; }  // Applied when the menu closes.
  deferredDocuments = null;
  renderedDocuments = key;
  $("document-count").textContent = `${data.total} document${data.total === 1 ? "" : "s"}`;
  $("empty-folder").hidden = data.items.length !== 0;
  if (!data.items.length) $("empty-folder").replaceChildren(emptyMessage());
  const current = new Map(data.items.map(doc => [doc.id, doc]));
  for (const id of [...selection.keys()]) if (current.has(id)) selection.set(id, current.get(id)); else selection.delete(id);
  $("documents").replaceChildren();
  for (const doc of data.items) {
    const row = document.createElement("tr"), name = documentName(doc);
    const pick = cell(row, ""); pick.className = "select-col";
    const box = document.createElement("input"); box.type = "checkbox"; box.dataset.select = doc.id; box.setAttribute("aria-label", `Select ${name}`);
    box.addEventListener("change", () => { if (box.checked) selection.set(doc.id, doc); else selection.delete(doc.id); renderSelection(); });
    pick.appendChild(box);
    const title = cell(row, ""); title.className = "doc-name";
    if (isReadable(doc)) { const link = element("a", name, "doc-link"); link.href = `#/documents/${doc.id}`; title.appendChild(link); }
    else title.appendChild(element("span", name, "doc-link"));
    // Beneath the description: the business and the file, which the description does not repeat.
    if (doc.title) title.appendChild(element("small", fileName(doc), "source-path"));
    if (doc.description_source === "model") title.firstChild.title = "The description is the AI's. Use Edit description to change it.";
    if (doc.source_status !== "present" && doc.source_status !== "organized") title.appendChild(element("small", SOURCE_STATES[doc.source_status] || `Source ${doc.source_status}`, "item-warning"));
    if (doc.managed_error) title.appendChild(element("small", doc.managed_error, "item-warning"));
    cell(row, folderLabel(doc.folder)).className = "secondary-cell";
    cell(row, "").appendChild(doc.document_date ? dateDisplay(doc.document_date) : element("span", "—", "muted"));
    const value = cell(row, ""); value.className = "numeric";
    if (doc.ledger_amount) value.appendChild(amount(doc.ledger_amount, {signed: false}));
    cell(row, "").appendChild(documentStateBadge(doc));
    const actions = cell(row, "").appendChild(element("div", "", "document-actions"));  // Flex inside the cell keeps table layout intact.
    const next = nextStep(doc);
    if (next) actions.appendChild(next);
    actions.appendChild(rowMenu(doc));
    $("documents").appendChild(row);
  }
  renderSelection();
}
let searchTimer = null;
$("document-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { searchQuery = $("document-search").value.trim(); reload(); }, 250);
});
for (const [id, apply] of [["date-from", value => { activeFrom = value; }], ["date-to", value => { activeTo = value; }], ["document-sort", value => { activeSort = value; }]])
  $(id).addEventListener("change", () => { apply($(id).value); reload(); });
$("select-all").addEventListener("change", () => {
  const docs = JSON.parse(renderedDocuments || '{"items":[]}').items;
  if ($("select-all").checked) for (const doc of docs) selection.set(doc.id, doc); else selection.clear();
  renderSelection();
});
$("documents").addEventListener("menuclose", () => { if (deferredDocuments) setTimeout(() => deferredDocuments && renderDocuments(deferredDocuments)); });
$("clear-selection").addEventListener("click", () => { selection.clear(); renderSelection(); });
$("read-selected").addEventListener("click", async () => {
  const ids = [...selection.values()].filter(isReadable).map(doc => doc.id);
  try {
    busy.inference = true; controls();
    await api("/api/receipt-batches", {method:"POST", body:JSON.stringify({document_ids: ids})});
    notice(`Reading ${ids.length} document${ids.length === 1 ? "" : "s"}. Progress shows in the sidebar.`);
    selection.clear(); await loadDocuments(); renderSelection();
  } catch (error) { busy.inference = false; controls(); notice(error, true); }
});
$("move-selected").addEventListener("click", () => openLibraryAction([...selection.values()], "move"));
$("trash-selected").addEventListener("click", () => openLibraryAction([...selection.values()], "trash"));
$("restore-selected").addEventListener("click", () => restoreDocuments([...selection.values()]).catch(error => notice(error, true)));

async function afterLibraryChange() {
  selection.clear(); await loadDocuments(); renderSelection();
  if (receipt) await refreshInspectorDoc();
}
async function eachDocument(docs, request) {
  // Applies one action per document; reports every failure instead of stopping at the first.
  const failures = [];
  for (const doc of docs) {
    try { await request(doc); } catch (error) { failures.push(`${documentName(doc)}: ${error.message}`); }
  }
  return failures;
}
async function restoreDocuments(docs) {
  const failures = await eachDocument(docs, doc => api(`/api/documents/${doc.id}/restore`, {method:"POST", body:JSON.stringify({expected_hash:doc.current_hash})}));
  await afterLibraryChange();
  const restored = docs.length - failures.length;
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
    await loadDocuments();
    if (receipt?.doc.id === updated.id) renameInspector(updated);
    notice(updated.description_source === "user" ? "Description saved." : "Your description was removed; the AI's description is used.");
  } catch (error) { $("description-error").textContent = error.message; }
});

$("empty-trash").addEventListener("click", () => {
  pendingLibraryAction = {action: "empty", docs: []};
  $("library-action-title").textContent = "Permanently empty Trash?";
  $("library-action-document").textContent = `All ${libraryCatalog.counts.trash} documents in Trash, including those hidden by filters or on other pages.`;
  $("library-action-description").textContent = "Permanently deletes managed copies, preserved versions, extracted text and associated ledger records. Data still used by other documents is kept. This cannot be undone. External source files and existing backups remain; rescanning an external source can add its documents again.";
  $("move-folder-label").hidden = true;
  $("confirm-library-action").textContent = "Permanently empty Trash";
  $("confirm-library-action").className = "danger";
  $("library-action-error").textContent = "";
  $("library-action-dialog").showModal();
  $("cancel-library-action").focus();
});

function openLibraryAction(docs, action) {
  if (!docs.length) return;
  pendingLibraryAction = {docs, action};
  const count = docs.length, plural = count === 1 ? "document" : `${count} documents`;
  $("library-action-title").textContent = action === "trash" ? `Delete ${count === 1 ? "document" : plural}?` : `Move ${plural}`;
  $("library-action-document").textContent = count === 1 ? `${documentName(docs[0])} — ${docs[0].relative_path}`
    : docs.slice(0, 3).map(documentName).join(", ") + (count > 3 ? ` and ${count - 3} more` : "");
  $("library-action-description").textContent = action === "trash" ? "This removes the document from the active library and puts it in Trash. You can restore it. Source files and preserved copies are not deleted from disk, and rescanning will not restore it automatically." : "Move the app-owned Library copy to this folder. External originals stay unchanged. Edited managed files will not be overwritten.";
  $("move-folder-label").hidden = action !== "move";
  $("move-folder").replaceChildren(new Option("Unfiled", "Unfiled"));
  for (const folder of libraryCatalog.folders.filter(folder => !["Unfiled", "Inbox"].includes(folder))) $("move-folder").add(new Option(folder.replaceAll("_", " "), folder));
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
    if (action === "empty") {
      const result = await api("/api/trash/empty", {method: "POST", body: JSON.stringify({confirmed: true})});
      pendingLibraryAction = null; $("library-action-dialog").close();
      closeReceipt();
      await afterLibraryChange();
      notice(`${result.deleted} documents permanently deleted.`);
      if (result.cleanup_pending) notice("Some files could not be removed. Close them in other programs and retry Empty trash, or restart the app to retry cleanup.", true);
      return;
    }
    const failures = await eachDocument(docs, doc => api(`/api/documents/${doc.id}/${action === "trash" ? "trash" : "folder"}`,
      {method: action === "trash" ? "POST" : "PUT", body: JSON.stringify(action === "trash" ? {expected_hash: doc.current_hash, confirmed: true} : {expected_hash: doc.current_hash, folder})}));
    if (failures.length === docs.length) { $("library-action-error").textContent = failures.join(" "); return; }
    pendingLibraryAction = null; $("library-action-dialog").close();
    await afterLibraryChange();
    const done = docs.length - failures.length;
    notice(action === "trash" ? (done === 1 ? "Document moved to Trash. Its source file is unchanged." : `${done} documents moved to Trash. Their source files are unchanged.`)
      : (done === 1 ? "Document moved to the selected folder." : `${done} documents moved to the selected folder.`));
    if (failures.length) notice(`${failures.length} couldn't be changed. ${failures.join(" ")}`, true);
  } catch (error) { $("library-action-error").textContent = error.message; }
  finally { $("confirm-library-action").disabled = false; }
});

const MAP_KEYS = ["date", "description", "amount", "debit", "credit"];
let importDoc = null;
async function openImport(doc) {
  importDoc = doc;
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
    if (typeof loadFinance === "function") loadFinance().catch(() => {});
  } catch (error) { $("import-status").textContent = error.message; $("confirm-import").disabled = false; }
});
