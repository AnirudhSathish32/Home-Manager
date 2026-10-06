"use strict";
let activeFolder = "all", activeStatus = "all", searchQuery = "", activeFrom = "", activeTo = "", activeSort = "date";
let activeCategory = null;  // A Receipts subfolder: one receipt category. Applies only while Receipts is the folder.
let receiptsOpen = false;   // Whether the Receipts group in the folder tree is expanded.
const receiptCategory = () => activeFolder === "Receipts" ? activeCategory : null;
let activeJob = null;  // Within Jobs: {employer, name, section}; section null for all of an employer's documents.
let jobsOpen = false;  // Whether the Jobs group is expanded.
const openEmployers = new Set();  // Employer folders expanded inside Jobs.
const jobFilter = () => activeFolder === "Jobs" ? activeJob : null;
const sameJob = (a, b) => (a && b) ? a.employer === b.employer && a.section === b.section : a === b;
let libraryCatalog = null, pendingLibraryAction = null;
let renderedDocuments = "", renderedFolders = "";  // Last rendered data, to skip identical re-renders.
const selection = new Map();  // Selected documents on the current page: id -> document.

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
function showLibrary(scope, route) {
  if (scope !== libraryScope) {
    libraryScope = scope; activeFolder = "all"; activeCategory = activeJob = null; activeStatus = "all"; docOffset = 0; selection.clear();
  }
  const view = LIBRARY_SCOPES[scope];
  $("library-title").textContent = view.title; $("library-subtitle").textContent = view.subtitle;
  $("close-receipt").lastChild.textContent = view.title; $("close-receipt").href = view.route;
  if (route.params.get("status")) { activeStatus = route.params.get("status"); activeFolder = "all"; docOffset = 0; selection.clear(); }
  if (route.params.has("q")) { searchQuery = $("document-search").value = route.params.get("q"); activeFolder = "all"; activeStatus = "all"; docOffset = 0; selection.clear(); }
  return configured ? loadDocuments() : null;
}
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
function reload() { docOffset = 0; selection.clear(); loadDocuments().catch(error => notice(error, true)); }
function folderButton(folder, count, category = null, label = null) {
  const button = element("button", "", label || category ? "folder-link subfolder" : "folder-link"); button.type = "button";
  if (category) button.dataset.category = category; else button.dataset.folder = folder;
  const current = folder === activeFolder && category === receiptCategory() && !jobFilter();
  button.classList.toggle("empty", !count && !current);
  button.append(element("span", label || (category ? categoryLabel(category === "uncategorized" ? null : category) : folderLabel(folder))), element("span", count, "folder-count"));
  if (current) button.setAttribute("aria-current", "page");
  else button.removeAttribute("aria-current");
  button.addEventListener("click", () => { activeFolder = folder; activeCategory = category; activeJob = null; reload(); });
  return button;
}
function jobButton(job, count, label, className) {
  const button = element("button", "", `folder-link subfolder ${className}`); button.type = "button";
  button.dataset.employer = job.employer; if (job.section) button.dataset.section = job.section;
  const current = sameJob(jobFilter(), job);
  button.classList.toggle("empty", !count && !current);
  button.append(element("span", label), element("span", count, "folder-count"));
  if (current) button.setAttribute("aria-current", "page");
  button.addEventListener("click", () => { activeFolder = "Jobs"; activeCategory = null; activeJob = job; reload(); });
  return button;
}
function groupToggle(key, label, count, open, onToggle, className = "") {
  const toggle = element("button", "", `folder-link folder-group ${className}`); toggle.type = "button";
  toggle.dataset.folderGroup = key;
  toggle.setAttribute("aria-expanded", String(open));
  toggle.append(icon("chevron-right", "icon folder-chevron"), element("span", label), element("span", count, "folder-count"));
  toggle.classList.toggle("empty", !count);
  toggle.addEventListener("click", () => {
    onToggle(); renderFolders(libraryCatalog);
    $("folder-tree").querySelector(`[data-folder-group="${CSS.escape(key)}"]`).focus();  // The tree was rebuilt; keep keyboard focus.
  });
  return toggle;
}
function jobsGroup(catalog) {
  // Jobs: one folder per employer, each with Paystubs and Documents, as on disk (Library/Jobs/<Employer>/<Section>).
  const toggle = groupToggle("Jobs", folderLabel("Jobs"), catalog.counts.Jobs, jobsOpen, () => { jobsOpen = !jobsOpen; });
  if (!jobsOpen) return [toggle];
  const rows = [toggle, folderButton("Jobs", catalog.counts.Jobs, null, "All job documents")];
  for (const employer of catalog.jobs || []) {
    const total = employer.total, open = openEmployers.has(employer.id);
    rows.push(groupToggle(`employer-${employer.id}`, employer.name, total, open,
                          () => { if (open) openEmployers.delete(employer.id); else openEmployers.add(employer.id); }, "subfolder"));
    if (open) {
      rows.push(jobButton({employer: employer.id, name: employer.name, section: null}, total, `All ${employer.name}`, "deep"));
      for (const section of ["Paystubs", "Documents"]) rows.push(jobButton({employer: employer.id, name: employer.name, section}, employer.sections[section], section, "deep"));
    }
  }
  return rows;
}
function receiptsGroup(catalog) {
  // Receipts opens and closes like a folder in a file manager. Inside: every receipt, then one subfolder per category.
  const toggle = element("button", "", "folder-link folder-group"); toggle.type = "button";
  toggle.dataset.folderGroup = "Receipts";
  toggle.setAttribute("aria-expanded", String(receiptsOpen));
  toggle.append(icon("chevron-right", "icon folder-chevron"), element("span", folderLabel("Receipts")), element("span", catalog.counts.Receipts, "folder-count"));
  toggle.classList.toggle("empty", !catalog.counts.Receipts);
  toggle.addEventListener("click", () => {
    receiptsOpen = !receiptsOpen; renderFolders(catalog);
    $("folder-tree").querySelector('[data-folder-group="Receipts"]').focus();  // The tree was rebuilt; keep keyboard focus.
  });
  if (!receiptsOpen) return [toggle];
  return [toggle, folderButton("Receipts", catalog.counts.Receipts, null, "All receipts"),
          ...(catalog.receipt_categories || []).map(row => folderButton("Receipts", row.count, row.category))];
}
function folderButtons(catalog) {
  return ["all", ...catalog.folders, "trash"].flatMap(folder => folder === "Receipts" ? receiptsGroup(catalog)
    : folder === "Jobs" ? jobsGroup(catalog) : [folderButton(folder, catalog.counts[folder])]);
}
function setNavCount(target, count, label) {
  target.textContent = count ? String(count) : ""; target.hidden = !count;
  if (count) target.setAttribute("aria-label", `${count} ${label}`); else target.removeAttribute("aria-label");
}
async function renderNavCounts(catalog) {
  // Sidebar attention counts: Inbox/Unfiled under Documents, pending decisions on Review, the weekly check-in on Inventory.
  setNavCount($("nav-inbox").querySelector(".nav-count"), catalog.counts.Inbox, "in Inbox");
  setNavCount($("nav-unfiled").querySelector(".nav-count"), catalog.counts.Unfiled, "unfiled");
  await loadNavCounts();
}
function showFolder(folder) {
  // Inbox and Unfiled belong to Documents; switching store first keeps the chosen folder.
  libraryScope = "documents"; activeFolder = folder; activeCategory = activeJob = null; activeStatus = "all";
  if (location.hash !== "#/documents") location.hash = "#/documents";
  reload();
}
for (const id of ["nav-inbox", "nav-unfiled"]) $(id).addEventListener("click", () => showFolder($(id).dataset.folder));
function renderFolders(catalog) {
  libraryCatalog = catalog;
  renderNavCounts(catalog).catch(() => {});
  const key = JSON.stringify([catalog, libraryScope, activeFolder, receiptCategory(), jobFilter(), activeStatus, receiptsOpen, jobsOpen, [...openEmployers]]);
  if (key === renderedFolders) return;
  renderedFolders = key;
  $("folder-tree").replaceChildren(...folderButtons(catalog));
  $("work-filters").replaceChildren(...WORK_FILTERS.map(([key, label]) => {
    const count = key === "all" ? catalog.counts.all : catalog.work[key];
    const chip = element("button", "", "filter-chip"); chip.type = "button"; chip.dataset.filter = key;
    chip.append(element("span", label), element("span", count, "chip-count"));
    chip.setAttribute("aria-pressed", String(key === activeStatus));
    chip.addEventListener("click", () => { activeStatus = key; reload(); });
    return chip;
  }));
  const job = jobFilter();
  $("folder-breadcrumb").textContent = folderLabel(activeFolder) + (receiptCategory() ? ` › ${categoryLabel(receiptCategory() === "uncategorized" ? null : receiptCategory())}` : "")
    + (job ? ` › ${job.name}${job.section ? ` › ${job.section}` : ""}` : "");
  // Emptying Trash deletes both stores' trashed files, so it is offered from Documents only.
  $("empty-trash").hidden = activeFolder !== "trash" || libraryScope !== "documents";
  $("empty-trash").disabled = false;
  $("folder-description").textContent = activeFolder === "trash" && libraryScope === "money" ? "Restore receipts and statements here. Empty Trash from Documents."
    : activeFolder === "trash" ? "Restore documents or empty Trash to permanently delete them. Emptying also removes trashed receipts and statements."
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
  for (const id of ["read-selected", "combine-selected", "move-selected", "trash-selected"]) $(id).hidden = trash;
  $("restore-selected").hidden = !trash;
  $("read-selected").disabled = busy.inference || !docs.some(isReadable);
  $("combine-selected").disabled = busy.inference || docs.length < 2 || docs.length > 20 || !docs.every(isImage);
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
  if (receiptCategory()) return emptyState(`No ${receiptCategory() === "uncategorized" ? "uncategorized" : categoryLabel(receiptCategory()).toLowerCase()} receipts yet.`);
  if (activeFolder !== "all") return emptyState(`No documents in ${folderLabel(activeFolder)}.`);
  const box = emptyState("Your library is empty. Drop files into your Inbox folder.");
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
    if (isReadable(doc)) { const link = element("a", name, "doc-link"); link.href = documentHref(doc); title.appendChild(link); }
    else title.appendChild(element("span", name, "doc-link"));
    // Beneath the description: the business and the file, which the description does not repeat.
    if (doc.title) title.appendChild(element("small", fileName(doc), "source-path"));
    if (doc.description_source === "model") title.firstChild.title = "The description is the AI's. Use Edit description to change it.";
    if (doc.source_status !== "present" && doc.source_status !== "organized") title.appendChild(element("small", SOURCE_STATES[doc.source_status] || `Source ${doc.source_status}`, "item-warning"));
    if (doc.managed_error) title.appendChild(element("small", doc.managed_error, "item-warning"));
    if (doc.folder === "Unfiled" && doc.unfiled_reason && !doc.deleted_at) title.appendChild(element("small", `Unfiled: ${doc.unfiled_reason}`, "muted unfiled-reason"));
    if (doc.match) title.appendChild(matchSnippet(doc.match));  // A search matched words in the document's text.
    cell(row, folderLabel(doc.folder)).className = "secondary-cell";
    cell(row, "").appendChild(doc.document_date ? dateDisplay(doc.document_date) : element("span", "—", "muted"));
    const value = cell(row, ""); value.className = "numeric";
    if (doc.ledger_amount) value.appendChild(amount(doc.ledger_amount, {signed: false}));
    value.append(...saleBadges(doc, {block: true}));  // Return or Exchange: the amount is money back.
    const state = cell(row, ""); state.appendChild(documentStateBadge(doc));
    const matched = matchText(doc);
    if (matched) state.appendChild(element("small", matched, `match-state muted${doc.reconciliation_status === "ambiguous" ? " item-warning" : ""}`));
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
$("combine-selected").addEventListener("click", async () => {
  // Pages in file-name order (scan (1), scan (2)…); the document's page shows them and can reorder them.
  const docs = [...selection.values()].sort((a, b) => a.relative_path.localeCompare(b.relative_path, undefined, {numeric: true}));
  try {
    busy.inference = true; controls();
    await api("/api/document-groups", {method: "POST", body: JSON.stringify({document_ids: docs.map(doc => doc.id)})});
    selection.clear();
    notice(`Combined ${docs.length} images into one document. They are read as its pages; progress shows in the sidebar.`);
    await reload();
  } catch (error) { busy.inference = false; controls(); notice(error, true); }
});
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
    await loadDocuments();
    if (receipt?.doc.id === updated.id) renameInspector(updated);
    notice(updated.description_source === "user" ? "Description saved." : "Your description was removed; the AI's description is used.");
  } catch (error) { $("description-error").textContent = error.message; }
});

$("empty-trash").addEventListener("click", () => {
  pendingLibraryAction = {action: "empty", docs: []};
  $("library-action-title").textContent = "Permanently empty Trash?";
  $("library-action-document").textContent = `All ${libraryCatalog.counts.trash} documents in Trash, including those hidden by filters or on other pages.`;
  $("library-action-description").textContent = "Permanently deletes managed copies, preserved versions, extracted text and associated ledger records. Data still used by other documents is kept. This cannot be undone. Existing backups remain.";
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
    if (action === "empty") {
      const result = await api("/api/trash/empty", {method: "POST", body: JSON.stringify({confirmed: true})});
      pendingLibraryAction = null; $("library-action-dialog").close();
      closeReceipt();
      await afterLibraryChange();
      notice(`${result.deleted} documents permanently deleted.`);
      if (result.cleanup_pending) notice("Some files could not be removed. Close them in other programs and retry Empty trash, or restart the app to retry cleanup.", true);
      return;
    }
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
    loadNavCounts().catch(() => {});
  } catch (error) { $("import-status").textContent = error.message; $("confirm-import").disabled = false; }
});
