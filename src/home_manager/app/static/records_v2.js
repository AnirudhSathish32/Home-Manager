"use strict";
// Records, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/records.md): the library for #/documents and
// #/receipts. A work strip names the backlog with the page's only primary (Read all), then search, state chips, dates and
// sort, then the folder tree beside one quiet table whose rows carry their next step as a text link. Every filter is in
// the URL. library.js keeps the shared dialogs (move/delete, description, import, versions) and the document helpers;
// this screen sets libraryScope (the shell and leaveDocument read it) and libraryCatalog (the move dialog's folders).
const RC2_PAGE = 50;
const RC2_SORTS = ["date", "name", "added", "path"];
const RC2_SECTIONS = ["Paystubs", "Documents"];
// The strip's words for each count, in WORK_FILTERS order.
const RC2_WORK = {needs_text: () => "not read yet", ready_for_ledger: () => "ready to record",
                  needs_review: n => n === 1 ? "needs review" : "need review", failed: () => "couldn't process"};
// The view (in the URL): folder, category (in Receipts), employer and section (in Jobs), status, q, from, to, sort and
// offset. catalog and data: the last /api/folders and /api/documents answers; key: both as drawn, so a poll that changes
// nothing draws nothing. open: the folder groups expanded. load: the newest load, so an older one finishing late draws
// nothing. deferred: a quiet redraw waiting for an open row menu to close.
const rc2 = {scope: "documents", folder: "all", category: "", employer: 0, section: "", status: "all", q: "", from: "", to: "", sort: "date", offset: 0,
             catalog: null, data: null, key: "", open: new Set(), selection: new Map(), load: 0, deferred: false, stripError: ""};

V2_SCREENS.documents = {title: "Documents", show: route => loadRecordsV2("documents", route.params)};
V2_SCREENS.receipts = {title: "Receipts & statements", show: route => loadRecordsV2("money", route.params)};

const rc2Showing = () => ["documents", "receipts"].includes(currentRoute?.name);
const rc2Route = () => rc2.scope === "money" ? "receipts" : "documents";

// The page's fixed parts, drawn once: the strip host, the toolbar, the summary line, then the folders beside the list.
function rc2Button(text, className, onClick) {
  const button = element("button", text, className); button.type = "button";
  if (onClick) button.addEventListener("click", () => Promise.resolve().then(onClick).catch(error => notice(error, true)));
  return button;
}
(function rc2Skeleton() {
  const strip = element("div", "", "rc2-strip-host"); strip.id = "rc2-strip";
  const toolbar = element("div", "", "rc2-toolbar");
  const search = document.createElement("input");
  Object.assign(search, {id: "rc2-search", type: "search", placeholder: "Search names, files or words in documents", autocomplete: "off"});
  search.setAttribute("aria-label", "Search documents");
  const chips = element("div", "", "rc2-chips"); chips.id = "rc2-chips";
  chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "Filter by state");
  const more = element("details", "", "rc2-more"); more.id = "rc2-more";
  more.append(element("summary", "More filters"));
  const fields = element("div", "", "rc2-more-fields");
  for (const [id, label, aria] of [["rc2-from", "From", "Document date from"], ["rc2-to", "To", "Document date to"]]) {
    const field = element("label", label, "inline-field"), input = document.createElement("input");
    input.id = id; input.type = "date"; input.setAttribute("aria-label", aria);
    field.append(input); fields.append(field);
  }
  const sortField = element("label", "Sort", "inline-field"), sort = document.createElement("select"); sort.id = "rc2-sort";
  sort.append(new Option("Document date", "date"), new Option("Name", "name"), new Option("Recently added", "added"), new Option("File path", "path"));
  sortField.append(sort); fields.append(sortField);
  more.append(fields);
  toolbar.append(search, chips, more);
  const summary = element("p", "", "rc2-summary muted"); summary.id = "rc2-summary"; summary.setAttribute("aria-live", "polite");
  const error = element("div", "", "rc2-error"); error.id = "rc2-error";

  const browser = element("div", "", "rc2-browser");
  const tree = element("nav", "", "rc2-tree"); tree.id = "rc2-tree"; tree.setAttribute("aria-label", "Folders");
  const pane = element("div", "", "rc2-pane");
  const folderField = element("label", "Folder", "inline-field rc2-folder-field"), folderSelect = document.createElement("select"); folderSelect.id = "rc2-folder";
  folderField.append(folderSelect);
  const head = element("div", "", "rc2-head"), crumbs = element("div", "", "rc2-head-text");
  const breadcrumb = element("h2", "All documents"); breadcrumb.id = "rc2-breadcrumb";
  const count = element("span", "", "rc2-count muted"); count.id = "rc2-count";
  crumbs.append(breadcrumb, count);
  const emptyTrash = rc2Button("Empty trash…", "secondary rc2-empty-trash", rc2EmptyTrash); emptyTrash.id = "rc2-empty-trash";
  emptyTrash.prepend(icon("trash-2")); emptyTrash.hidden = true;
  head.append(crumbs, emptyTrash);
  const description = element("p", "", "rc2-description muted small"); description.id = "rc2-description";
  const selection = element("div", "", "rc2-selection"); selection.id = "rc2-selection";
  selection.setAttribute("role", "region"); selection.setAttribute("aria-label", "Selected documents"); selection.hidden = true;
  const list = element("div", "", "rc2-list"); list.id = "rc2-list";
  const pager = element("div", "", "pager rc2-pager"); pager.id = "rc2-pager";
  pane.append(folderField, head, description, selection, list, pager);
  browser.append(tree, pane);
  $("rc2-body").append(strip, toolbar, summary, error, browser);
})();
$("rc2-refresh").prepend(icon("refresh"));
$("rc2-refresh").addEventListener("click", () => rc2Draw().catch(error => notice(error, true)));
// Dates and sort sit in the toolbar from 600px; below that they fold into More filters.
const rc2Wide = matchMedia("(min-width: 600px)");
function rc2MoreOpen() { if (rc2Wide.matches) $("rc2-more").open = true; }
rc2Wide.addEventListener("change", () => { $("rc2-more").open = rc2Wide.matches; });
rc2MoreOpen();

// Loading and the URL ---------------------------------------------------------------------------------------------------
function loadRecordsV2(scope, params) {
  if (scope !== rc2.scope) { $("rc2-list").replaceChildren(); $("rc2-strip").replaceChildren(); rc2.key = ""; }
  rc2.scope = libraryScope = scope;
  const view = LIBRARY_SCOPES[scope];
  $("rc2-title").textContent = view.title; $("rc2-subtitle").textContent = view.subtitle;
  rc2ReadUrl(params);
  rc2.selection.clear(); rc2.stripError = "";
  return pageState($("rc2-state"), () => rc2Draw({initial: true}), {loading: `Loading ${view.title.toLowerCase()} …`,
    what: scope === "money" ? "receipts and statements" : "documents", needsLibrary: true, content: [$("rc2-body")]});
}
// Raw values from the URL; rc2Validate checks them against the folder list once it has arrived.
function rc2ReadUrl(params) {
  const get = key => params?.get?.(key) || "";
  Object.assign(rc2, {folder: get("folder") || "all", category: get("category"), employer: Number(get("employer")) || 0, section: get("section"),
                      status: get("status") || "all", q: get("q").slice(0, 200), from: get("from"), to: get("to"), sort: get("sort") || "date",
                      offset: Math.max(0, Math.floor(Number(get("offset")) || 0))});
  $("rc2-search").value = rc2.q;
}
function rc2Validate(catalog) {
  if (!["all", "trash", ...catalog.folders].includes(rc2.folder)) rc2.folder = "all";
  if (rc2.folder !== "Receipts" || !catalog.receipt_categories.some(row => row.category === rc2.category)) rc2.category = "";
  if (rc2.folder !== "Jobs" || !(catalog.jobs || []).some(job => job.id === rc2.employer)) rc2.employer = 0;
  if (!rc2.employer || !RC2_SECTIONS.includes(rc2.section)) rc2.section = "";
  if (!WORK_FILTERS.some(([key]) => key === rc2.status)) rc2.status = "all";
  if (!RC2_SORTS.includes(rc2.sort)) rc2.sort = "date";
  for (const key of ["from", "to"]) if (!/^\d{4}-\d{2}-\d{2}$/.test(rc2[key])) rc2[key] = "";
  // A deep link into a group opens it.
  if (rc2.category) rc2.open.add("Receipts");
  if (rc2.employer) { rc2.open.add("Jobs"); rc2.open.add(`employer-${rc2.employer}`); }
}
// The view into the URL (Layout rule 5): non-default values only. Never while another page shows (a load that finishes
// after the user opened a document leaves its URL alone).
function rc2WriteUrl() {
  if (!rc2Showing()) return;
  const next = new URLSearchParams();
  if (rc2.folder !== "all") next.set("folder", rc2.folder);
  if (rc2.category) next.set("category", rc2.category);
  if (rc2.employer) next.set("employer", rc2.employer);
  if (rc2.section) next.set("section", rc2.section);
  if (rc2.status !== "all") next.set("status", rc2.status);
  if (rc2.q) next.set("q", rc2.q);
  if (rc2.from) next.set("from", rc2.from);
  if (rc2.to) next.set("to", rc2.to);
  if (rc2.sort !== "date") next.set("sort", rc2.sort);
  if (rc2.offset) next.set("offset", rc2.offset);
  currentRoute.params = next;
  history.replaceState(null, "", `#/${rc2Route()}${[...next].length ? `?${next}` : ""}`);
}
function rc2Query() {
  const query = new URLSearchParams({scope: rc2.scope, folder: rc2.folder, status: rc2.status, sort: rc2.sort, offset: rc2.offset, limit: RC2_PAGE});
  if (rc2.q) query.set("q", rc2.q);
  if (rc2.from) query.set("date_from", rc2.from);
  if (rc2.to) query.set("date_to", rc2.to);
  if (rc2.category) query.set("category", rc2.category);
  if (rc2.employer) query.set("employer", rc2.employer);
  if (rc2.section) query.set("section", rc2.section);
  return query;
}
// One load: the folders (to check the URL against), then the page of documents. initial: the screen's first draw, whose
// failure pageState shows; later failures show above the list with Retry and keep the page. quiet: a poll's redraw.
async function rc2Draw({initial = false, quiet = false} = {}) {
  const load = ++rc2.load;
  try {
    const catalog = await api(`/api/folders?scope=${rc2.scope}`);
    if (load !== rc2.load) return;
    rc2Validate(catalog);
    let data = await api(`/api/documents?${rc2Query()}`);
    // Keep a just-read Inbox row visible under Not read yet until a manual refresh or filter change.
    if (quiet && rc2.folder === "Inbox" && rc2.status === "needs_text" && rc2.data?.items) {
      const missing = rc2.data.items.filter(old => !data.items.some(item => item.id === old.id));
      const changed = await Promise.all(missing.map(old => api(`/api/documents/${old.id}`).catch(() => null)));
      for (const doc of changed) {
        if (doc?.folder !== "Inbox" || !doc.text_run_id || doc.ledger_status || doc.deleted_at) continue;
        data.items.push(doc); data.total++;
        if (!rc2.data.items.find(old => old.id === doc.id)?.text_run_id) notice(`${documentName(doc)} is ready to record and still in Inbox. Refresh to apply Not read yet.`);
      }
    }
    // A page past the end (a reload after documents moved, or a hand-made link) falls back to the first.
    if (!data.items.length && rc2.offset) { rc2.offset = 0; data = await api(`/api/documents?${rc2Query()}`); }
    if (load !== rc2.load) return;
    rc2WriteUrl();
    rc2.catalog = libraryCatalog = catalog;
    $("rc2-error").replaceChildren();
    const key = JSON.stringify([catalog, data, rc2.scope, rc2.folder, rc2.category, rc2.employer, rc2.section, rc2.status, rc2.q, rc2.from, rc2.to, rc2.sort, rc2.offset, rc2.stripError]);
    if (quiet && key === rc2.key) return;
    if (quiet && $("rc2-list").querySelector(".menu-list:not([hidden])")) { rc2.deferred = true; return; }  // Drawn when the menu closes.
    rc2.key = key; rc2.data = data; rc2.deferred = false;
    rc2Render();
  } catch (error) {
    if (initial) throw error;
    if (load !== rc2.load) return;
    $("rc2-error").replaceChildren(alertBox(`Couldn't load documents. ${error.message}`, {tone: "error", detail: error.detail || "",
      action: rc2Button("Retry", "secondary", () => rc2Draw())}));
  }
}
// A filter, folder or page changed: back to the first page with nothing selected, then load.
function rc2Change(apply, {keepOffset = false} = {}) {
  apply();
  if (!keepOffset) rc2.offset = 0;
  rc2.selection.clear();
  rc2WriteUrl();
  return rc2Draw();
}
// While work runs or just finished (app.js poll), and after a dialog changed documents.
function rc2Refresh() { return rc2Showing() ? rc2Draw({quiet: true}) : Promise.resolve(); }

function rc2Render() {
  // The parts are redrawn together; keyboard focus returns to the same control when it is redrawn.
  const focused = document.activeElement?.closest?.("#rc2-panel [data-rc2-key]")?.dataset.rc2Key;
  rc2Strip(); rc2Toolbar(); rc2Folders(); rc2FolderSelect(); rc2Head(); rc2Table(); rc2Selection(); rc2Pager();
  if (focused) $("rc2-panel").querySelector(`[data-rc2-key="${CSS.escape(focused)}"]`)?.focus();
}
function rc2Breadcrumb() {
  const job = rc2.employer ? (rc2.catalog.jobs || []).find(row => row.id === rc2.employer) : null;
  return folderLabel(rc2.folder) + (rc2.category ? ` › ${categoryLabel(rc2.category === "uncategorized" ? null : rc2.category)}` : "")
    + (job ? ` › ${job.name}${rc2.section ? ` › ${rc2.section}` : ""}` : "");
}
const rc2Filtered = () => rc2.status !== "all" || rc2.q || rc2.from || rc2.to;

// The work strip ------------------------------------------------------------------------------------------------------
function rc2Strip() {
  const work = rc2.catalog.work, counts = WORK_FILTERS.filter(([key]) => key !== "all" && work[key] > 0);
  if (!counts.length) {
    const done = element("p", "", "rc2-done");
    done.append(icon("check-circle"), "Everything here has been read.");
    $("rc2-strip").replaceChildren(done);
    return;
  }
  const strip = element("section", "", "needs-row attention rc2-strip"); strip.setAttribute("aria-label", "Work to do");
  const text = element("div", "", "rc2-strip-text");
  counts.forEach(([key], index) => {
    if (index) text.append(element("span", " · ", "rc2-strip-sep"));
    const link = rc2Button(`${work[key]} ${RC2_WORK[key](work[key])}`, "link-button rc2-strip-count", () => rc2Change(() => { rc2.status = key; }));
    link.dataset.status = key; link.dataset.rc2Key = `strip-${key}`;
    text.append(link);
  });
  if (rc2.stripError) text.append(alertBox(rc2.stripError, {tone: "warning"}));
  strip.append(icon("alert", "icon needs-icon"), text);
  if (work.needs_text > 0) {
    const read = rc2Button(`Read all ${work.needs_text}`, "primary rc2-read-all", () => rc2ReadAll(read));
    read.id = "rc2-read-all"; read.dataset.rc2Key = "read-all"; read.prepend(icon("book-open"));
    strip.append(read);
  }
  $("rc2-strip").replaceChildren(strip);
}
// Read all: every not-read document in this store (up to 500), as one batch.
async function rc2ReadAll(button) {
  button.disabled = true;
  try {
    const ids = [];
    for (let offset = 0, total = 1; offset < total && ids.length < 500; offset += 200) {
      const page = await api(`/api/documents?${new URLSearchParams({scope: rc2.scope, status: "needs_text", sort: "path", offset, limit: 200})}`);
      total = page.total; ids.push(...page.items.map(doc => doc.id));
      if (!page.items.length) break;
    }
    const chosen = ids.slice(0, 500);
    if (!chosen.length) { await rc2Draw(); return; }
    try {
      await api("/api/receipt-batches", {method: "POST", body: JSON.stringify({document_ids: chosen})});
    } catch (error) {
      // Model work is already running: the reason stays in the strip and the button can be tried again.
      if (error.status !== 409) throw error;
      rc2.stripError = error.message;
      await rc2Draw();
      return;
    }
    busy.inference = true; controls();
    rc2.stripError = "";
    const item = toast(`Reading ${chosen.length} document${chosen.length === 1 ? "" : "s"}. Follow it on Processing.`);
    item.querySelector(".toast-body")?.append(homeLink("Open Processing", "#/processing"));
    await rc2Draw();
  } finally { if (button.isConnected) button.disabled = false; }
}

// The toolbar: search, the state chips with counts, dates and sort ----------------------------------------------------
function rc2Toolbar() {
  const catalog = rc2.catalog;
  $("rc2-chips").replaceChildren(...WORK_FILTERS.map(([key, label]) => {
    const chip = rc2Button("", "chip", () => rc2Change(() => { rc2.status = key; }));
    chip.dataset.status = key; chip.dataset.rc2Key = `chip-${key}`;
    chip.append(element("span", label), element("span", key === "all" ? catalog.counts.all : catalog.work[key], "chip-count"));
    chip.setAttribute("aria-pressed", String(key === rc2.status));
    return chip;
  }));
  $("rc2-from").value = rc2.from; $("rc2-to").value = rc2.to; $("rc2-sort").value = rc2.sort;
  if (document.activeElement !== $("rc2-search")) $("rc2-search").value = rc2.q;
  const summary = $("rc2-summary");
  if (rc2.folder === "all" && !rc2Filtered()) { summary.replaceChildren(); summary.hidden = true; return; }
  const status = WORK_FILTERS.find(([key]) => key === rc2.status)[1];
  const parts = [rc2Breadcrumb(), ...(rc2.status !== "all" ? [status] : []), ...(rc2.q ? [`“${rc2.q}”`] : []),
                 ...(rc2.from || rc2.to ? [`${rc2.from ? dateText(rc2.from) : "any date"} – ${rc2.to ? dateText(rc2.to) : "today"}`] : [])];
  const clear = rc2Button("Clear filters", "link-button", rc2ClearFilters); clear.dataset.rc2Key = "clear-summary";
  summary.replaceChildren(`Showing ${parts.join(" · ")} — `, clear);
  summary.hidden = false;
}
function rc2ClearFilters() {
  $("rc2-search").value = "";
  return rc2Change(() => Object.assign(rc2, {folder: "all", category: "", employer: 0, section: "", status: "all", q: "", from: "", to: "", sort: "date"}));
}
let rc2SearchTimer = null;
$("rc2-search").addEventListener("input", () => {
  clearTimeout(rc2SearchTimer);
  rc2SearchTimer = setTimeout(() => rc2Change(() => { rc2.q = $("rc2-search").value.trim().slice(0, 200); }).catch(error => notice(error, true)), 250);
});
for (const [id, key] of [["rc2-from", "from"], ["rc2-to", "to"], ["rc2-sort", "sort"]])
  $(id).addEventListener("change", () => rc2Change(() => { rc2[key] = $(id).value; }).catch(error => notice(error, true)));

// Folders: a tree from 1100px, a select below ---------------------------------------------------------------------------
const RC2_FOLDER_ICONS = {all: "file", Inbox: "inbox", trash: "trash-2"};
function rc2Current(folder, category = "", employer = 0, section = "") {
  return rc2.folder === folder && rc2.category === category && rc2.employer === employer && rc2.section === section;
}
function rc2FolderRow({folder, category = "", employer = 0, section = "", label, count, depth = 0}) {
  const button = rc2Button("", `rc2-folder${depth ? ` rc2-depth-${depth}` : ""}`, () => rc2Change(() => Object.assign(rc2, {folder, category, employer, section})));
  button.dataset.folder = folder;
  if (category) button.dataset.category = category;
  if (employer) button.dataset.employer = employer;
  if (section) button.dataset.section = section;
  button.dataset.rc2Key = `folder-${folder}-${category}-${employer}-${section}`;
  const current = rc2Current(folder, category, employer, section);
  button.classList.toggle("empty", !count && !current);
  if (current) button.setAttribute("aria-current", "page");
  button.append(depth ? element("span", "", "rc2-folder-icon") : icon(RC2_FOLDER_ICONS[folder] || "folder", "icon rc2-folder-icon"),
                element("span", label, "rc2-folder-label"), element("span", count ?? 0, "rc2-folder-count"));
  return button;
}
function rc2GroupRow(key, label, count, depth = 0) {
  const open = rc2.open.has(key);
  const button = rc2Button("", `rc2-folder rc2-group${depth ? ` rc2-depth-${depth}` : ""}`, () => {
    if (open) rc2.open.delete(key); else rc2.open.add(key);
    rc2Folders();
    $("rc2-tree").querySelector(`[data-rc2-key="${CSS.escape(`group-${key}`)}"]`)?.focus();  // The tree was rebuilt; keep keyboard focus.
  });
  button.dataset.folderGroup = key; button.dataset.rc2Key = `group-${key}`;
  button.setAttribute("aria-expanded", String(open));
  button.classList.toggle("empty", !count);
  button.append(icon("chevron-right", "icon rc2-folder-icon rc2-chevron"), element("span", label, "rc2-folder-label"), element("span", count ?? 0, "rc2-folder-count"));
  return button;
}
// The tree's rows: Receipts → categories, Jobs → employer → Paystubs/Documents, Trash last.
function rc2FolderEntries() {
  const catalog = rc2.catalog, rows = [];
  for (const folder of ["all", ...catalog.folders, "trash"]) {
    const count = catalog.counts[folder];
    if (folder === "Receipts") {
      rows.push({group: "Receipts", label: folderLabel(folder), count, depth: 0});
      rows.push({folder, label: "All receipts", count, depth: 1, parent: ["Receipts"]});
      for (const row of catalog.receipt_categories || [])
        rows.push({folder, category: row.category, label: categoryLabel(row.category === "uncategorized" ? null : row.category), count: row.count, depth: 1, parent: ["Receipts"]});
    } else if (folder === "Jobs") {
      rows.push({group: "Jobs", label: folderLabel(folder), count, depth: 0});
      rows.push({folder, label: "All job documents", count, depth: 1, parent: ["Jobs"]});
      for (const job of catalog.jobs || []) {
        const key = `employer-${job.id}`;
        rows.push({group: key, label: job.name, count: job.total, depth: 1, parent: ["Jobs"]});
        rows.push({folder, employer: job.id, label: `All ${job.name}`, count: job.total, depth: 2, parent: ["Jobs", key]});
        for (const section of RC2_SECTIONS) rows.push({folder, employer: job.id, section, label: section, count: job.sections[section], depth: 2, parent: ["Jobs", key]});
      }
    } else rows.push({folder, label: folderLabel(folder), count, depth: 0});
  }
  return rows;
}
function rc2Folders() {
  const items = rc2FolderEntries().filter(row => (row.parent || []).every(key => rc2.open.has(key))).map(row => {
    const li = document.createElement("li");
    li.append(row.group ? rc2GroupRow(row.group, row.label, row.count, row.depth) : rc2FolderRow(row));
    return li;
  });
  const list = element("ul", "", "rc2-folder-list"); list.append(...items);
  $("rc2-tree").replaceChildren(list);
}
function rc2FolderSelect() {
  const select = $("rc2-folder"), indent = depth => "   ".repeat(depth);
  select.replaceChildren(...rc2FolderEntries().filter(row => !row.group || row.depth).map(row => {
    // A group's own row (Receipts, Jobs) isn't a choice; its "All …" row is. An employer is a heading inside Jobs.
    if (row.group) { const heading = new Option(`${indent(row.depth)}${row.label}`, ""); heading.disabled = true; return heading; }
    return new Option(`${indent(row.depth)}${row.label} (${row.count ?? 0})`, JSON.stringify([row.folder, row.category || "", row.employer || 0, row.section || ""]));
  }));
  select.value = JSON.stringify([rc2.folder, rc2.category, rc2.employer, rc2.section]);
}
$("rc2-folder").addEventListener("change", () => {
  const [folder, category, employer, section] = JSON.parse($("rc2-folder").value);
  rc2Change(() => Object.assign(rc2, {folder, category, employer, section})).catch(error => notice(error, true));
});

// The list ------------------------------------------------------------------------------------------------------------
function rc2Head() {
  const total = rc2.data.total;
  $("rc2-breadcrumb").textContent = rc2Breadcrumb();
  $("rc2-count").textContent = `${total} document${total === 1 ? "" : "s"}`;
  // Emptying Trash deletes both stores' trashed files, so it is offered from Documents only.
  $("rc2-empty-trash").hidden = rc2.folder !== "trash" || rc2.scope !== "documents" || !rc2.catalog.counts.trash;
  $("rc2-description").textContent = rc2.folder === "trash" && rc2.scope === "money" ? "Restore receipts and statements here. Empty Trash from Documents."
    : rc2.folder === "trash" ? "Restore documents or empty Trash to permanently delete them. Emptying also removes trashed receipts and statements."
    : rc2.folder === "Inbox" ? "Newly dropped files waiting to be read and filed."
    : rc2.folder === "Unfiled" ? "Documents whose type, merchant or date could not be confirmed. Record them or use Move." : "";
}
function rc2Empty() {
  if (rc2Filtered()) return emptyState("No documents match.", rc2Button("Clear filters", "link-button", rc2ClearFilters));
  if (rc2.folder === "Inbox" || rc2.folder === "all") {
    const box = emptyState(rc2.folder === "all" ? "Nothing here yet. Drop files into your Inbox folder." : "Nothing in Inbox. Drop files into your Inbox folder.");
    if (inboxDirectory) box.append(element("code", inboxDirectory), copyButton(inboxDirectory, "Copy Inbox path"));
    return box;
  }
  return emptyState(`Nothing in ${rc2Breadcrumb()}.`);
}
function rc2Table() {
  const docs = rc2.data.items;
  for (const id of [...rc2.selection.keys()]) {
    const doc = docs.find(row => row.id === id);
    if (doc) rc2.selection.set(id, doc); else rc2.selection.delete(id);
  }
  if (!docs.length) { $("rc2-list").replaceChildren(rc2Empty()); return; }
  const table = element("table", "", "data-table rc2-table"); table.id = "rc2-table";
  const head = table.createTHead().insertRow();
  const all = document.createElement("input"); all.type = "checkbox"; all.id = "rc2-select-all";
  all.setAttribute("aria-label", "Select all documents on this page");
  all.addEventListener("change", () => rc2SelectAll(all.checked));
  for (const [title, className] of [["", "rc2-pick"], ["Name", "rc2-name-col"], ["Folder", "rc2-folder-col"], ["Date", "rc2-date"],
                                    ["Amount", "numeric rc2-amount"], ["State", "rc2-state"], ["", "rc2-actions"]]) {
    const th = element("th", title, className); th.scope = "col";
    if (className === "rc2-pick") th.append(all);
    else if (!title) th.append(element("span", "Actions", "visually-hidden"));
    head.append(th);
  }
  const body = table.createTBody();
  body.append(...docs.map(rc2Row));
  const wrap = element("div", "", "table-wrap"); wrap.append(table);
  $("rc2-list").replaceChildren(wrap);
}
function rc2Row(doc) {
  const tr = document.createElement("tr"), name = documentName(doc);
  tr.dataset.documentId = doc.id;
  const pick = cell(tr, ""); pick.className = "rc2-pick";
  const box = document.createElement("input"); box.type = "checkbox"; box.dataset.select = doc.id;
  box.setAttribute("aria-label", `Select ${name}`); box.checked = rc2.selection.has(doc.id);
  box.addEventListener("change", () => { if (box.checked) rc2.selection.set(doc.id, doc); else rc2.selection.delete(doc.id); rc2Selection(); });
  pick.append(box);
  const title = cell(tr, ""); title.className = "rc2-name-cell";
  if (isReadable(doc)) { const link = element("a", name, "rc2-name"); link.href = documentHref(doc); title.append(link); }
  else title.append(element("span", name, "rc2-name"));
  if (doc.description_source === "model") title.firstChild.title = "The description is the AI's. Use Edit description to change it.";
  if (doc.title) title.append(element("small", fileName(doc), "rc2-file"));
  if (doc.match) title.append(matchSnippet(doc.match));  // A search matched words in the document's text.
  if (doc.source_status !== "present" && doc.source_status !== "organized") title.append(element("small", SOURCE_STATES[doc.source_status] || `Source ${doc.source_status}`, "rc2-note"));
  if (doc.managed_error) title.append(element("small", doc.managed_error, "rc2-note"));
  if (doc.folder === "Unfiled" && doc.unfiled_reason && !doc.deleted_at) title.append(element("small", `Unfiled: ${doc.unfiled_reason}`, "rc2-note"));
  cell(tr, folderLabel(doc.folder)).className = "rc2-folder-col";
  const day = cell(tr, ""); day.className = "rc2-date";
  day.append(doc.document_date ? dateDisplay(doc.document_date) : element("span", "—", "muted"));
  if (doc.ledger_kind === "bill") {  // A bill counts on its due date (docs/money.md "Bills and their lines").
    day.prepend(element("small", "Due", "muted block"));
    if (doc.bill_period_start && doc.bill_period_end) day.append(element("small", `For ${dateText(doc.bill_period_start)} – ${dateText(doc.bill_period_end)}`, "muted block"));
  }
  const value = cell(tr, ""); value.className = "numeric rc2-amount";
  if (doc.ledger_amount) value.append(amount(doc.ledger_amount, {signed: false}));
  value.append(...saleBadges(doc, {block: true}));  // Return or Exchange: the amount is money back.
  const state = cell(tr, ""); state.className = "rc2-state";
  state.append(documentStateBadge(doc));
  const matched = matchText(doc);
  if (matched) state.append(element("small", matched, "rc2-match"));
  const actions = cell(tr, ""); actions.className = "rc2-actions";
  const wrap = element("div", "", "rc2-row-actions"), step = rc2Step(doc, state);
  if (step) wrap.append(step);
  wrap.append(rc2Menu(doc));
  actions.append(wrap);
  return tr;
}
// The one most useful action for the document, as a text link: Restore, Import, Read or Record.
function rc2Step(doc, stateCell) {
  const name = documentName(doc);
  let label = "", run = null, model = false;
  if (doc.deleted_at) { label = "Restore"; run = async () => { await restoreDocuments([doc]); await rc2Draw(); }; }
  else if (isTable(doc)) { label = "Import"; run = () => openImport(doc, {onDone: () => rc2Draw()}); }
  else if (!doc.text_run_id && !PENDING.includes(doc.parse_status)) {
    label = "Read"; model = true;
    run = () => rc2Start(`/api/documents/${doc.id}/receipt-runs`, {blob_hash: doc.current_hash}, "Reading started. Follow it on Processing.");
  } else if (doc.text_run_id && !doc.ledger_status && !PENDING.includes(doc.extraction_status)) {
    label = "Record"; model = true;
    run = () => rc2Start(`/api/documents/${doc.id}/extraction-runs`, {parse_run_id: doc.text_run_id}, "Recording started. Follow it on Processing.");
  }
  if (!run) return null;
  const button = element("button", label, "link-button rc2-step"); button.type = "button";
  button.dataset.rc2Key = `step-${doc.id}`;
  button.setAttribute("aria-label", `${label} ${name}`);
  if (model) { button.dataset.step = "true"; button.disabled = busy.inference; }  // controls() keeps model steps off while model work runs.
  button.addEventListener("click", async () => {
    button.disabled = true; button.textContent = "Starting…";
    stateCell.querySelector(".alert")?.remove();
    try { await run(); }
    catch (error) {
      stateCell.append(alertBox(error.message, {tone: "error", detail: error.detail || ""}));
      if (model) { busy.inference = false; controls(); }
    } finally {
      if (button.isConnected) { button.textContent = label; button.disabled = model && busy.inference; }
    }
  });
  return button;
}
async function rc2Start(path, body, message) {
  busy.inference = true; controls();
  await api(path, {method: "POST", body: JSON.stringify(body)});
  notice(message);
  await rc2Draw({quiet: true});
}
function rc2Menu(doc) {
  const name = documentName(doc);
  const items = [rc2Button("Edit description…", "", () => openDescription(doc)), rc2Button(`Versions (${doc.version_count})`, "", () => showVersions(doc))];
  if (!doc.deleted_at) {
    items.push(rc2Button("Move", "", () => openLibraryAction([doc], "move")));
    items.push(rc2Button("Delete", "danger-text", () => openLibraryAction([doc], "trash")));
  }
  items.push(element("small", doc.managed_path ? `Library/${doc.managed_path}` : "Managed copy pending", "managed-path"));
  const wrap = menu(`More actions for ${name}`, items);
  wrap.querySelector(".menu-trigger").dataset.rc2Key = `menu-${doc.id}`;
  return wrap;
}
$("rc2-list").addEventListener("menuclose", () => { if (rc2.deferred) setTimeout(() => rc2.deferred && rc2Draw({quiet: true})); });
// The shared dialogs (library.js) change documents; the list catches up when one closes.
for (const id of ["library-action-dialog", "description-dialog"]) $(id).addEventListener("close", () => { rc2Refresh().catch(() => {}); });

// Selection -------------------------------------------------------------------------------------------------------------
function rc2SelectAll(checked) {
  if (checked) for (const doc of rc2.data?.items || []) rc2.selection.set(doc.id, doc); else rc2.selection.clear();
  for (const box of $("rc2-list").querySelectorAll("input[data-select]")) box.checked = checked;
  rc2Selection();
}
function rc2Selection() {
  const docs = [...rc2.selection.values()], bar = $("rc2-selection"), trash = rc2.folder === "trash";
  const boxes = [...$("rc2-list").querySelectorAll("input[data-select]")];
  const allChecked = boxes.length > 0 && boxes.every(box => box.checked);
  if ($("rc2-select-all")) { $("rc2-select-all").checked = allChecked; $("rc2-select-all").indeterminate = docs.length > 0 && !allChecked; }
  bar.hidden = !docs.length;
  if (!docs.length) { bar.replaceChildren(); return; }
  // Below 820px the table's head is hidden, so select-all moves into this bar.
  const allLabel = element("label", "", "rc2-bar-all"), all = document.createElement("input");
  all.type = "checkbox"; all.checked = allChecked; all.indeterminate = !allChecked;
  all.setAttribute("aria-label", "Select all documents on this page");
  all.addEventListener("change", () => rc2SelectAll(all.checked));
  allLabel.append(all);
  const buttons = [];
  if (trash) buttons.push(rc2Button("Restore", "secondary", async () => { await restoreDocuments(docs); rc2.selection.clear(); await rc2Draw(); }));
  else {
    const read = rc2Button("Read", "secondary", () => rc2ReadSelected(docs));
    const record = rc2Button("Record", "secondary", () => rc2ReadSelected(docs, true));
    record.disabled = busy.inference || !docs.some(isReadable);
    read.disabled = busy.inference || !docs.some(isReadable);
    const combine = rc2Button("Combine", "secondary", () => rc2Combine(docs));
    const combinable = docs.length >= 2 && docs.length <= 20 && docs.every(isImage);
    combine.disabled = busy.inference || !combinable;
    if (!combinable) combine.title = "Combine 2 to 20 images into one document's pages.";
    buttons.push(read, record, combine, rc2Button("Move", "secondary", () => openLibraryAction(docs, "move")),
                 rc2Button("Delete", "secondary", () => openLibraryAction(docs, "trash")));
  }
  bar.replaceChildren(allLabel, element("span", `${docs.length} selected`, "rc2-selected"), ...buttons,
                      rc2Button("Clear", "link-button", () => rc2SelectAll(false)));
}
async function rc2ReadSelected(docs, record = false) {
  const ids = docs.filter(isReadable).map(doc => doc.id);
  busy.inference = true; controls();
  try {
    await api("/api/receipt-batches", {method: "POST", body: JSON.stringify({document_ids: ids, record})});
  } catch (error) { busy.inference = false; controls(); throw error; }
  notice(`${record ? "Recording" : "Reading"} ${ids.length} document${ids.length === 1 ? "" : "s"}. Follow it on Processing.`);
  rc2.selection.clear(); await rc2Draw({quiet: !record});
}
async function rc2Combine(docs) {
  // Pages in file-name order (scan (1), scan (2)…); the document's page shows them and can reorder them.
  const ordered = [...docs].sort((a, b) => a.relative_path.localeCompare(b.relative_path, undefined, {numeric: true}));
  busy.inference = true; controls();
  try {
    await api("/api/document-groups", {method: "POST", body: JSON.stringify({document_ids: ordered.map(doc => doc.id)})});
  } catch (error) { busy.inference = false; controls(); throw error; }
  notice(`Combined ${ordered.length} images into one document. They are read as its pages; follow it on Processing.`);
  rc2.selection.clear(); await rc2Draw();
}

// Pager and Trash -------------------------------------------------------------------------------------------------------
function rc2Pager() {
  const {total, items} = rc2.data, pager = $("rc2-pager");
  pager.hidden = total <= RC2_PAGE;
  if (pager.hidden) { pager.replaceChildren(); return; }
  const previous = rc2Button("Previous", "secondary", () => rc2Page(-1)), next = rc2Button("Next", "secondary", () => rc2Page(1));
  previous.prepend(icon("chevron-left")); next.append(icon("chevron-right"));
  previous.id = "rc2-prev"; next.id = "rc2-next";
  previous.dataset.rc2Key = "prev"; next.dataset.rc2Key = "next";
  previous.disabled = rc2.offset === 0; next.disabled = rc2.offset + items.length >= total;
  pager.replaceChildren(previous, element("span", `${rc2.offset + 1}–${rc2.offset + items.length} of ${total}`), next);
}
function rc2Page(direction) {
  return rc2Change(() => { rc2.offset = Math.max(0, rc2.offset + direction * RC2_PAGE); }, {keepOffset: true}).then(() => $("rc2-breadcrumb").scrollIntoView());
}
async function rc2EmptyTrash() {
  const count = rc2.catalog.counts.trash;
  if (!await confirmAction({title: "Permanently empty Trash?", danger: true, confirmLabel: "Permanently empty Trash",
                            message: `All ${count} document${count === 1 ? "" : "s"} in Trash, including those hidden by filters or on other pages. Permanently deletes managed copies, preserved versions, extracted text and associated ledger records. Data still used by other documents is kept. This cannot be undone. Existing backups remain.`})) return;
  const result = await api("/api/trash/empty", {method: "POST", body: JSON.stringify({confirmed: true})});
  notice(`${result.deleted} documents permanently deleted.`);
  if (result.cleanup_pending) notice("Some files could not be removed. Close them in other programs and retry Empty trash, or restart the app to retry cleanup.", true);
  rc2.selection.clear();
  await rc2Draw();
}
