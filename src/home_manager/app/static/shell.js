"use strict";
// Application shell: hash routes select a page; the URL keeps the view across reloads and Back.
const ROUTES = {
  home: {title: "Home", show: () => loadHome()},
  search: {title: "Search", show: route => openSearch(route.params)},
  review: {title: "Review", show: () => loadReview()},
  transactions: {title: "Transactions", show: route => configured ? openTransactions(route.params) : null},
  spending: {title: "Spending & budgets", show: route => configured ? openSpending(route.params) : null},
  // Bills, Accounts, Forecast, Taxes and Investments show their own "Set up your library" state (ui.js pageState).
  bills: {title: "Bills & recurring", show: () => loadBills()},
  accounts: {title: "Accounts", show: () => loadAccounts()},
  inventory: {title: "Inventory", show: route => { if (route.params.has("q")) $("inventory-search").value = route.params.get("q"); return loadInventory(); }},
  // Old links (#/finances?section=…) forward to the page that now holds that section.
  finances: {title: "Finances", nav: "transactions", show: route => openFinanceRoute(route.params)},
  forecast: {title: "Forecast", show: () => loadForecast()},
  whatif: {title: "What If", show: route => configured ? loadWhatIf(route.params) : null},
  taxes: {title: "Taxes", show: () => loadTaxes()},
  investments: {title: "Investments", show: route => loadInvestments(route.params)},
  documents: {title: "Documents", show: route => showLibrary("documents", route)},
  // Receipts and statements: the money store, on the same library page with its own folders.
  receipts: {title: "Receipts & statements", page: "documents", show: route => showLibrary("money", route)},
  // #/documents/ID[?version=HASH][&lines=ID,ID] opens the inspector over the preserved list state, at those text lines.
  document: {title: "Document", nav: "documents", show: route => configured ? openDocument(route.id, route.params.get("version"), route.params.get("lines")) : null},
  processing: {title: "Processing", show: () => configured ? Promise.all([loadJobs().then(loadEvents), loadModelHistory(), loadProcessing()]) : null},
  // #/settings?tab=checks opens that tab; the default tab (Library folder) leaves the URL bare.
  settings: {title: "Settings", show: route => showSettingsTab(route.params.get("tab"))},
  // #/donate lists checks and documents; #/donate/ID is one check beside its original.
  donate: {title: "Donate documents", show: route => configured ? openDonate(route) : null},
};
// V2_SCREENS (app.js): route → {title, show}, filled by each Phase 2 screen's script; it wins over ROUTES.
const DEFAULT_ROUTE = "home";
let currentRoute = null, listScroll = 0, openedFromList = false;

for (const link of document.querySelectorAll(".nav-link[data-icon]")) {
  link.prepend(icon(link.dataset.icon, "icon nav-icon"));
  link.title = link.querySelector(".nav-label").textContent;  // Tooltip when the sidebar collapses to icons.
}
$("close-receipt").prepend(icon("arrow-left"));
// Settings tabs by their ?tab= name. Donate comes after Privacy & security so the arrow order of the others is unchanged.
const SETTINGS_TABS = {library: "directories-tab", profiles: "profiles-tab", preferences: "preferences-tab", appearance: "appearance-tab",
                       models: "model-tab", checks: "checks-tab", backup: "backup-tab", sharing: "sharing-tab", privacy: "privacy-tab", donate: "donate-tab"};
const activateSettingsTab = wireTabs(Object.values(SETTINGS_TABS));
for (const [name, id] of Object.entries(SETTINGS_TABS)) $(id).addEventListener("tabshow", () => {
  // In the scrolling row (below 800px) the selected tab stays in sight.
  const nav = document.querySelector(".settings-nav"), tab = $(id);
  if (!settingsColumn.matches) nav.scrollLeft = tab.offsetLeft - nav.offsetLeft - (nav.clientWidth - tab.offsetWidth) / 2;
  if (currentRoute?.name !== "settings") return;
  const next = new URLSearchParams(name === "library" ? {} : {tab: name});
  currentRoute.params = next;
  history.replaceState(null, "", `#/settings${name === "library" ? "" : `?${next}`}`);
});
function showSettingsTab(name) {
  const id = SETTINGS_TABS[name] || SETTINGS_TABS.library;
  if ($(id).getAttribute("aria-selected") !== "true") activateSettingsTab(id);
  else if (id === SETTINGS_TABS.donate) loadDonateSettings();
}
// The tablist is a column beside the content from 800px, and a scrolling row above it below that.
const settingsColumn = matchMedia("(min-width: 801px)");
function settingsOrientation() { document.querySelector(".settings-nav").setAttribute("aria-orientation", settingsColumn.matches ? "vertical" : "horizontal"); }
settingsColumn.addEventListener("change", settingsOrientation); settingsOrientation();

// Settings › Appearance: System, Light or Dark, saved in this browser (theme.js).
const themeChoice = $(`theme-${storedTheme()}`) || $("theme-system");
themeChoice.checked = true;
for (const radio of document.querySelectorAll('input[name="theme"]')) radio.addEventListener("change", () => setTheme(radio.value));

// Under 820px the sidebar is a top bar and the menu button opens its contents as a sheet (docs/ui.md "Accessibility").
const shell = document.querySelector(".app-shell"), navToggle = $("nav-toggle");
navToggle.prepend(icon("menu"));
navToggle.hidden = false;
function setNavOpen(open, returnFocus = false) {
  shell.classList.toggle("nav-open", open);
  navToggle.setAttribute("aria-expanded", String(open));
  if (open) [...$("sidebar-sheet").querySelectorAll(".nav-link")].find(link => link.getClientRects().length)?.focus();
  else if (returnFocus) navToggle.focus();
}
navToggle.addEventListener("click", () => setNavOpen(!shell.classList.contains("nav-open")));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && shell.classList.contains("nav-open")) { event.preventDefault(); setNavOpen(false, true); }
});
document.addEventListener("click", event => {
  if (shell.classList.contains("nav-open") && !event.target.closest(".sidebar")) setNavOpen(false);
});

function parseRoute() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const [name, id] = path.split("/");
  if (name === "documents" && /^\d+$/.test(id || "")) return {name: "document", id: Number(id), params: new URLSearchParams(query)};
  if (name === "donate" && /^\d+$/.test(id || "")) return {name, id: Number(id), params: new URLSearchParams(query)};
  return {name: name in ROUTES ? name : DEFAULT_ROUTE, params: new URLSearchParams(query)};
}
// A family profile's own library is only its inbox: uploads are read, reviewed and routed to people from these pages.
// Everything else (transactions, budgets, bills, inventory) belongs to each person's profile.
// The family ledger pages (transactions, spending, bills, accounts) read every member's copy (finance.js ledgerTool).
const FAMILY_ROUTES = ["home", "settings", "review", "receipts", "documents", "document", "processing", "whatif", "taxes",
                       "transactions", "spending", "bills", "accounts"];
function showRoute(moveFocus) {
  const route = parseRoute(), previous = currentRoute?.name;
  if (familyMode && !FAMILY_ROUTES.includes(route.name)) { location.replace("#/home"); return; }
  const lists = ["documents", "receipts"], page = ROUTES[route.name].page || route.name;
  if (lists.includes(previous) && !lists.includes(route.name)) listScroll = window.scrollY;
  if (previous === "document" && route.name !== "document") { closeReceipt(); closeDocumentV2(); }
  if (route.name === "document") openedFromList = lists.includes(previous) || (previous === "document" && openedFromList);
  currentRoute = route;
  // A redesigned screen is a data-ui="v2" section for the same page; pages without one show their plain section.
  const v2 = V2_SCREENS[route.name], ui = v2 ? "v2" : "v1";
  for (const section of document.querySelectorAll("[data-page]")) section.hidden = !(section.dataset.page === page && (section.dataset.ui || "v1") === ui);
  // A document belongs to the store its list was opened from.
  const nav = route.name === "document" && libraryScope === "money" ? "receipts" : ROUTES[route.name].nav || route.name;
  for (const link of document.querySelectorAll(".nav-link[data-route]")) {
    if (link.dataset.route === nav) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  document.title = `${(v2 || ROUTES[route.name]).title} · Home Manager`;
  // Returning from a document restores the list where the user left it.
  if (lists.includes(route.name) && previous === "document") requestAnimationFrame(() => window.scrollTo(0, listScroll));
  else if (moveFocus) window.scrollTo(0, 0);
  // Move focus to the new page's heading so keyboard and screen-reader users land on the content.
  if (moveFocus) document.querySelector(`[data-page="${page}"]:not([hidden]) h1`)?.focus({preventScroll: true});
  Promise.resolve().then(() => (v2 || ROUTES[route.name]).show(route)).catch(error => notice(error, true));
}

function leaveDocument() {
  // Back to the list the document was opened from, keeping filters, page and scroll position.
  if (openedFromList) history.back(); else location.hash = libraryScope === "money" ? "#/receipts" : "#/documents";
}
$("close-receipt").addEventListener("click", event => { event.preventDefault(); leaveDocument(); });
document.addEventListener("keydown", event => {
  if (event.key !== "Escape" || currentRoute?.name !== "document" || event.defaultPrevented) return;
  if (document.querySelector("dialog[open]") || event.target.closest("input, select, textarea, .menu")) return;
  leaveDocument();
});
window.addEventListener("hashchange", () => { setNavOpen(false); showRoute(true); });
showRoute(false);
