"use strict";
// Global search (docs/items-assets-search.md §2): one query across documents, transactions, items and accounts.
// Ctrl+K or "/" focuses the search box; results link into each page's own filtered view.
let searchLoad = 0;

function searchHref(query) { return `#/search?${new URLSearchParams({q: query})}`; }
function searchGroup(title, total, allHref, rows) {
  const panel = element("section", "", "panel"), heading = element("h2", `${title} (${total})`);
  if (total > rows.length && allHref) heading.append(homeLink(`View all ${total}`, allHref));
  const list = element("ul", "", "finance-list");
  for (const row of rows) list.append(row);
  panel.append(heading, list);
  return panel;
}
function searchHit(link, detail, right = null) {
  const li = element("li", "", "search-hit"), main = element("div");
  main.append(link, element("small", detail, "muted"));
  li.append(main);
  if (right) li.append(right);
  return li;
}
async function openSearch(params) {
  const query = (params.get("q") || "").trim();
  $("search-page-input").value = query;
  $("global-search").value = query;
  if (!configured) { $("search-results").replaceChildren(emptyState("Set up your library to search it.")); return; }
  if (!query) { $("search-status").textContent = ""; $("search-results").replaceChildren(emptyState("Type a merchant, description, product or file name.")); $("search-page-input").focus(); return; }
  const load = ++searchLoad;
  $("search-status").textContent = "Searching…";
  let found;
  try { found = await api(`/api/search?${new URLSearchParams({q: query})}`); }
  catch (error) { if (load === searchLoad) { $("search-status").textContent = ""; $("search-results").replaceChildren(alertBox(error.message, {tone: "error"})); } return; }
  if (load !== searchLoad) return;
  const groups = [];
  const {documents, transactions, inventory, accounts} = found;
  if (documents.total) groups.push(searchGroup("Documents", documents.total, `#/documents?${new URLSearchParams({q: query})}`, documents.items.map(doc =>
    searchHit(homeLink(doc.title || doc.relative_path.split(/[\\/]/).pop(), `#/documents/${doc.id}`),
              [folderLabel(doc.folder), doc.document_date && dateText(doc.document_date)].filter(Boolean).join(" · "),
              doc.ledger_amount ? amount(doc.ledger_amount, {signed: false}) : null))));
  if (transactions.total) groups.push(searchGroup("Transactions", transactions.total, `#/transactions?${new URLSearchParams({q: query, period: "all"})}`, transactions.items.map(row => {
    const link = element("button", row.merchant || row.description_raw, "link-button"); link.type = "button";
    link.addEventListener("click", () => openTransaction(row.id));
    return searchHit(link, [dateText(row.posted_date), row.account, row.category].filter(Boolean).join(" · "), amount(row.amount));
  })));
  if (inventory.total) groups.push(searchGroup("Household items", inventory.total, `#/inventory?${new URLSearchParams({q: query})}`, inventory.items.map(lot =>
    searchHit(homeLink(productName(lot), `#/inventory?${new URLSearchParams({q: lot.name})}`),
              [lot.category, lot.bought_on && `bought ${dateText(lot.bought_on)}`, statusLabel(lot.status)].filter(Boolean).join(" · ")))));
  if (accounts.total) groups.push(searchGroup("Accounts", accounts.total, "#/accounts", accounts.items.map(account =>
    searchHit(homeLink(account.display_name, `#/transactions?${new URLSearchParams({account: account.id, period: "all"})}`), `${account.institution} · ${account.currency}`))));
  const total = documents.total + transactions.total + inventory.total + accounts.total;
  $("search-status").textContent = total ? `${total} match${total === 1 ? "" : "es"} for “${found.query}”.` : "";
  $("search-results").replaceChildren(...(groups.length ? groups : [emptyState(`Nothing matches “${found.query}”. Try fewer or different words.`)]));
}
for (const [form, input] of [["global-search-form", "global-search"], ["search-page-form", "search-page-input"]]) {
  $(form).addEventListener("submit", event => {
    event.preventDefault();
    const query = $(input).value.trim();
    if (!query && form === "global-search-form") return;
    const target = searchHref(query);
    if (location.hash === target) openSearch(new URLSearchParams({q: query})).catch(error => notice(error, true)); else location.hash = target;
  });
}
document.addEventListener("keydown", event => {
  const typing = event.target.closest("input, select, textarea, [contenteditable]");
  if (((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") || (event.key === "/" && !typing && !document.querySelector("dialog[open]"))) {
    event.preventDefault();
    const box = getComputedStyle($("global-search-form")).display !== "none" ? $("global-search") : null;
    if (box) { box.focus(); box.select(); } else location.hash = "#/search";
  }
});
