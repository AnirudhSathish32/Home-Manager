"use strict";
let activeFolder = "all", libraryCatalog = null, pendingLibraryAction = null;

function wireTabs(ids) {
  function activate(id) {
    for (const key of ids) {
      const tab = $(key), active = key === id;
      tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1;
      $(tab.getAttribute("aria-controls")).hidden = !active;
    }
  }
  ids.forEach((id, index) => {
    $(id).addEventListener("click", () => activate(id));
    $(id).addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? ids.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + ids.length) % ids.length;
      activate(ids[next]); $(ids[next]).focus();
    });
  });
}
wireTabs(["documents-tab", "scan-tab"]);
wireTabs(["directories-tab", "model-tab"]);
$("open-settings").addEventListener("click", () => { $("settings-notice").textContent = ""; $("settings-dialog").showModal(); });
$("close-settings").addEventListener("click", () => $("settings-dialog").close());

function folderLabel(folder) {
  return folder === "all" ? "All documents" : folder === "trash" ? "Trash" : folder;
}
function folderButton(folder, label, count) {
  const button = document.createElement("button"); button.type = "button"; button.className = "folder-link";
  button.dataset.folder = folder; button.setAttribute("aria-current", folder === activeFolder ? "page" : "false");
  const icon = document.createElement("span"); icon.className = "folder-icon"; icon.setAttribute("aria-hidden", "true"); icon.textContent = folder === "trash" ? "▤" : "▱";
  const name = document.createElement("span"); name.textContent = label;
  const badge = document.createElement("span"); badge.className = "folder-count"; badge.textContent = count;
  button.append(icon, name, badge);
  button.addEventListener("click", event => {
    event.preventDefault(); activeFolder = folder; docOffset = 0;
    loadDocuments().catch(error => notice(error.message, true));
  });
  return button;
}
function renderFolders(catalog) {
  libraryCatalog = catalog;
  const tree = $("folder-tree"), expanded = new Map([...tree.querySelectorAll("details")].map(node => [node.dataset.folder, node.open]));
  tree.replaceChildren();
  for (const folder of ["all", "Unfiled"]) tree.appendChild(folderButton(folder, folderLabel(folder), catalog.counts[folder]));
  for (const [parent, children] of Object.entries(catalog.hierarchy)) {
    const group = document.createElement("details"); group.className = "folder-group"; group.dataset.folder = parent;
    group.open = expanded.get(parent) ?? true;
    const summary = document.createElement("summary"); summary.appendChild(folderButton(parent, parent, catalog.counts[parent]));
    const list = document.createElement("div"); list.className = "folder-children";
    for (const child of children) list.appendChild(folderButton(`${parent}/${child}`, child, catalog.counts[`${parent}/${child}`]));
    group.append(summary, list); tree.appendChild(group);
  }
  tree.appendChild(folderButton("trash", "Trash", catalog.counts.trash));
  $("folder-breadcrumb").textContent = folderLabel(activeFolder).replaceAll("/", " / ");
  $("folder-description").textContent = activeFolder === "trash" ? "Deleted from the active library. Restore a document to return it to its folder. Source files and preserved bytes remain stored." : activeFolder === "Unfiled" ? "New, uncertain or unsupported documents await organization. Configure a local model in Settings or move a document yourself." : "Titles and folders assigned by the model may need correction. Source paths are shown beneath each document.";
}
function actionButton(label, callback, mutation = false) {
  const button = document.createElement("button"); button.type = "button"; button.className = "secondary"; button.textContent = label;
  if (mutation) { button.dataset.libraryAction = "true"; button.disabled = busy; }
  button.addEventListener("click", () => Promise.resolve().then(callback).catch(error => notice(error.message, true)));
  return button;
}
function renderDocuments(data) {
  $("document-count").textContent = `${data.total} document${data.total === 1 ? "" : "s"}`;
  $("empty-folder").hidden = data.items.length !== 0;
  $("documents").replaceChildren();
  for (const doc of data.items) {
    const row = document.createElement("tr"), name = cell(row, "");
    const title = document.createElement("strong"); title.textContent = doc.title || doc.relative_path.split(/[\\/]/).pop();
    const path = document.createElement("small"); path.className = "source-path"; path.textContent = doc.relative_path;
    name.append(title, path);
    cell(row, doc.folder.replaceAll("/", " / "));
    cell(row, `${doc.parse_status || "Not parsed"}${doc.source_status !== "present" ? ` · source ${doc.source_status}` : ""}`);
    cell(row, `${(doc.size / 1024).toFixed(1)} KB`);
    const actions = cell(row, ""); actions.className = "document-actions";
    if (/\.(png|jpe?g)$/i.test(doc.relative_path)) actions.appendChild(actionButton("Inspect document", () => openReceipt(doc)));
    else { const hint = document.createElement("small"); hint.textContent = "Reader planned"; actions.appendChild(hint); }
    actions.appendChild(actionButton(`Versions (${doc.version_count})`, () => showVersions(doc)));
    if (doc.deleted_at) {
      actions.appendChild(actionButton("Restore", async () => {
        await api(`/api/documents/${doc.id}/restore`, {method:"POST", body:JSON.stringify({expected_hash:doc.current_hash})});
        await loadDocuments(); notice("Document restored to the library.");
      }, true));
    } else {
      actions.appendChild(actionButton("Move", () => openLibraryAction(doc, "move"), true));
      const remove = actionButton("Delete", () => openLibraryAction(doc, "trash"), true); remove.classList.add("danger-text"); actions.appendChild(remove);
    }
    $("documents").appendChild(row);
  }
}
function openLibraryAction(doc, action) {
  pendingLibraryAction = {doc, action};
  $("library-action-title").textContent = action === "trash" ? "Delete document?" : "Move document";
  $("library-action-document").textContent = `${doc.title || doc.relative_path} — ${doc.relative_path}`;
  $("library-action-description").textContent = action === "trash" ? "This removes the document from the active library and puts it in Trash. You can restore it. Source files and preserved copies are not deleted from disk, and rescanning will not restore it automatically." : "Choose a folder in Home Manager. This overrides the model's folder for this version; the source file stays where it is.";
  $("move-folder-label").hidden = action !== "move";
  $("move-folder").replaceChildren(new Option("Unfiled", "Unfiled"));
  for (const [parent, children] of Object.entries(libraryCatalog.hierarchy)) for (const child of children) $("move-folder").add(new Option(`${parent} / ${child}`, `${parent}/${child}`));
  $("move-folder").value = doc.folder;
  $("confirm-library-action").textContent = action === "trash" ? "Delete to Trash" : "Move document";
  $("confirm-library-action").classList.toggle("danger", action === "trash");
  $("library-action-error").textContent = ""; $("library-action-dialog").showModal();
  $("cancel-library-action").focus();
}
$("cancel-library-action").addEventListener("click", () => { pendingLibraryAction = null; $("library-action-dialog").close(); });
$("library-action-dialog").addEventListener("cancel", () => { pendingLibraryAction = null; });
$("confirm-library-action").addEventListener("click", async () => {
  if (!pendingLibraryAction) return;
  const {doc, action} = pendingLibraryAction;
  try {
    $("confirm-library-action").disabled = true;
    const body = {expected_hash:doc.current_hash};
    if (action === "trash") body.confirmed = true; else body.folder = $("move-folder").value;
    await api(`/api/documents/${doc.id}/${action === "trash" ? "trash" : "folder"}`, {method:action === "trash" ? "POST" : "PUT", body:JSON.stringify(body)});
    pendingLibraryAction = null; $("library-action-dialog").close();
    await loadDocuments(); notice(action === "trash" ? "Document moved to Trash. Its source file is unchanged." : "Document moved to the selected folder.");
  } catch (error) { $("library-action-error").textContent = error.message; }
  finally { controls(); }
});
