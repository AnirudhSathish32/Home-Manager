"use strict";
// Application shell: hash routes select a page; the URL keeps the view across reloads and Back.
// Every route is listed here. Screens register their title and loader in V2_SCREENS (app.js) from their own scripts; the
// rest have them here. page: the [data-page] section it shows, when not its own name; nav: the sidebar link it lights.
const ROUTES = {
  home: {}, search: {}, review: {}, transactions: {}, spending: {}, bills: {}, accounts: {}, inventory: {}, forecast: {}, whatif: {},
  taxes: {}, investments: {}, processing: {},
  // Old links (#/finances?section=…) forward to the page that now holds that section.
  finances: {title: "Finances", nav: "transactions", show: route => openFinanceRoute(route.params)},
  documents: {},
  // Receipts and statements: the money store, on the same Records page with its own folders.
  receipts: {page: "documents"},
  // #/documents/ID[?version=HASH][&lines=ID,ID] opens the document page at those text lines.
  document: {nav: "documents"},
  // #/settings?tab=checks opens that tab; the default tab (Library folder) leaves the URL bare.
  settings: {title: "Settings", show: route => showSettingsTab(route.params.get("tab"))},
  // #/donate lists checks and documents; #/donate/ID is one check beside its original.
  donate: {title: "Donate documents", show: route => configured ? openDonate(route) : null},
};
const DEFAULT_ROUTE = "home";
let currentRoute = null, listScroll = 0, openedFromList = false;

for (const link of document.querySelectorAll(".nav-link[data-icon]")) {
  link.prepend(icon(link.dataset.icon, "icon nav-icon"));
  link.title = link.querySelector(".nav-label").textContent;  // Tooltip when the sidebar collapses to icons.
}
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
  if (previous === "document" && route.name !== "document") closeDocumentV2();
  if (route.name === "document") openedFromList = lists.includes(previous) || (previous === "document" && openedFromList);
  currentRoute = route;
  const screen = V2_SCREENS[route.name] || ROUTES[route.name];
  for (const section of document.querySelectorAll("[data-page]")) section.hidden = section.dataset.page !== page;
  // A document belongs to the store its list was opened from.
  const nav = route.name === "document" && libraryScope === "money" ? "receipts" : ROUTES[route.name].nav || route.name;
  for (const link of document.querySelectorAll(".nav-link[data-route]")) {
    if (link.dataset.route === nav) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  document.title = `${screen.title} · Home Manager`;
  // Returning from a document restores the list where the user left it.
  if (lists.includes(route.name) && previous === "document") requestAnimationFrame(() => window.scrollTo(0, listScroll));
  else if (moveFocus) window.scrollTo(0, 0);
  // Move focus to the new page's heading so keyboard and screen-reader users land on the content.
  if (moveFocus) document.querySelector(`[data-page="${page}"]:not([hidden]) h1`)?.focus({preventScroll: true});
  Promise.resolve().then(() => screen.show(route)).catch(error => notice(error, true));
}

function leaveDocument() {
  // Back to the list the document was opened from, keeping filters, page and scroll position.
  if (openedFromList) history.back(); else location.hash = libraryScope === "money" ? "#/receipts" : "#/documents";
}
document.addEventListener("keydown", event => {
  if (event.key !== "Escape" || currentRoute?.name !== "document" || event.defaultPrevented) return;
  if (document.querySelector("dialog[open]") || event.target.closest("input, select, textarea, .menu")) return;
  leaveDocument();
});
window.addEventListener("hashchange", () => { setNavOpen(false); showRoute(true); });
showRoute(false);
