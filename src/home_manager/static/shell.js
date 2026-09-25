"use strict";
// Application shell: hash routes select a page; the URL keeps the view across reloads and Back.
const ROUTES = {
  home: {title: "Home", show: () => loadHome()},
  finances: {title: "Finances", show: route => openFinanceRoute(route.params)},
  documents: {title: "Documents", show: route => {
    if (route.params.get("status")) { activeStatus = route.params.get("status"); activeFolder = "all"; docOffset = 0; selection.clear(); }
    return configured ? loadDocuments() : null;
  }},
  // #/documents/ID[?version=HASH] opens the inspector over the preserved list state.
  document: {title: "Document", nav: "documents", show: route => configured ? openDocument(route.id, route.params.get("version")) : null},
  processing: {title: "Processing", show: () => configured ? Promise.all([loadJobs().then(loadEvents), loadModelHistory()]) : null},
  settings: {title: "Settings", show: () => null},
};
const DEFAULT_ROUTE = "home";
let currentRoute = null, listScroll = 0, openedFromList = false;

for (const link of document.querySelectorAll(".nav-link[data-icon]")) {
  link.prepend(icon(link.dataset.icon, "icon nav-icon"));
  link.title = link.querySelector(".nav-label").textContent;  // Tooltip when the sidebar collapses to icons.
}
$("close-receipt").prepend(icon("arrow-left"));
wireTabs(["directories-tab", "preferences-tab", "model-tab", "checks-tab", "privacy-tab"]);

function parseRoute() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, id] = path.split("/");
  if (name === "documents" && /^\d+$/.test(id || "")) return {name: "document", id: Number(id), params: new URLSearchParams(query)};
  return {name: name in ROUTES ? name : DEFAULT_ROUTE, params: new URLSearchParams(query)};
}
function showRoute(moveFocus) {
  const route = parseRoute(), previous = currentRoute?.name;
  if (previous === "documents" && route.name !== "documents") listScroll = window.scrollY;
  if (previous === "document" && route.name !== "document") closeReceipt();
  if (route.name === "document") openedFromList = previous === "documents" || (previous === "document" && openedFromList);
  currentRoute = route;
  for (const page of document.querySelectorAll("[data-page]")) page.hidden = page.dataset.page !== route.name;
  const nav = ROUTES[route.name].nav || route.name;
  for (const link of document.querySelectorAll(".nav-link[data-route]")) {
    if (link.dataset.route === nav) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  document.title = `${ROUTES[route.name].title} · Home Manager`;
  // Returning from a document restores the list where the user left it.
  if (route.name === "documents" && previous === "document") requestAnimationFrame(() => window.scrollTo(0, listScroll));
  else if (moveFocus) window.scrollTo(0, 0);
  // Move focus to the new page's heading so keyboard and screen-reader users land on the content.
  if (moveFocus) document.querySelector(`[data-page="${route.name}"] h1`)?.focus({preventScroll: true});
  Promise.resolve().then(() => ROUTES[route.name].show(route)).catch(error => notice(error, true));
}
function leaveDocument() {
  // Back to the list the document was opened from, keeping filters, page and scroll position.
  if (openedFromList) history.back(); else location.hash = "#/documents";
}
$("close-receipt").addEventListener("click", event => { event.preventDefault(); leaveDocument(); });
document.addEventListener("keydown", event => {
  if (event.key !== "Escape" || currentRoute?.name !== "document" || event.defaultPrevented) return;
  if (document.querySelector("dialog[open]") || event.target.closest("input, select, textarea, .menu")) return;
  leaveDocument();
});
window.addEventListener("hashchange", () => showRoute(true));
showRoute(false);
