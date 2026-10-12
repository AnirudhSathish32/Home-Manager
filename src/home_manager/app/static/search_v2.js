"use strict";
// Search, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/search-ask.md): one query across documents,
// transactions, household items and accounts, with a chip per kind. "All" shows the first six of each kind; a kind
// shows up to 50 and keeps the reader on this page. q and kind are in the URL. search.js keeps the global box, the
// Ctrl+K and "/" shortcuts, and the snippet and document-link helpers this screen calls.
const SE2_KINDS = [["all", "All"], ["documents", "Documents"], ["transactions", "Transactions"], ["items", "Items"], ["accounts", "Accounts"]];
// The server's group for each kind, and the group's heading.
const SE2_GROUPS = {documents: ["documents", "Documents"], transactions: ["transactions", "Transactions"], items: ["inventory", "Household items"],
                    accounts: ["accounts", "Accounts"]};
// q and kind: the view (in the URL). found: the last answer, for the chips' counts. load: the newest search, so an older
// reply arriving late draws nothing.
const se2 = {q: "", kind: "all", found: null, load: 0};

V2_SCREENS.search = {title: "Search", show: route => loadSearchV2(route.params)};

function loadSearchV2(params) {
  se2.q = (params.get("q") || "").trim();
  const kind = params.get("kind");
  se2.kind = SE2_GROUPS[kind] ? kind : "all";
  $("se2-input").value = se2.q;
  $("global-search").value = se2.q;
  return pageState($("se2-state"), se2Render, {loading: "Searching …", what: "search", needsLibrary: true, content: [$("se2-body")]});
}
function se2Href(q, kind) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (kind !== "all") params.set("kind", kind);
  return `#/search${[...params].length ? `?${params}` : ""}`;
}
function se2WriteUrl() {
  const href = se2Href(se2.q, se2.kind);
  currentRoute.params = new URLSearchParams(href.split("?")[1] || "");
  history.replaceState(null, "", href);
}
function se2SetKind(kind) {
  se2.kind = kind; se2WriteUrl();
  return se2Render().then(() => $("se2-kinds").querySelector(`[data-kind="${kind}"]`)?.focus());
}

// Fetches and draws. A failed search shows its error in the results, with Retry, so the query stays editable.
async function se2Render() {
  const {q, kind} = se2, load = ++se2.load;
  if (!q) {
    se2.found = null;
    $("se2-status").textContent = ""; $("se2-kinds").replaceChildren();
    $("se2-results").replaceChildren(emptyState("Search names, merchants, items, accounts and the words inside your documents."));
    $("se2-input").focus();
    return;
  }
  $("se2-status").textContent = "Searching…";
  let found;
  try { found = await api(`/api/search?${new URLSearchParams({q, limit: kind === "all" ? 6 : 50})}`); }
  catch (error) {
    if (load !== se2.load) return;
    $("se2-status").textContent = "";
    const retry = element("button", "Retry", "secondary"); retry.type = "button";
    retry.addEventListener("click", () => se2Render().catch(failure => notice(failure, true)));
    $("se2-results").replaceChildren(alertBox(`Couldn't search. ${error.message}`, {tone: "error", action: retry}));
    return;
  }
  if (load !== se2.load) return;
  se2.found = found;
  $("se2-status").textContent = found.total ? `${found.total} match${found.total === 1 ? "" : "es"} for “${found.query}”.` : "";
  se2Chips(found);
  if (!found.total) { $("se2-results").replaceChildren(se2Empty(found.query)); return; }
  const kinds = kind === "all" ? Object.keys(SE2_GROUPS) : [kind];
  const groups = kinds.map(name => se2Group(name, found)).filter(Boolean);
  if (!groups.length) {
    const all = element("button", "Show every kind", "link-button"); all.type = "button";
    all.addEventListener("click", () => se2SetKind("all").catch(error => notice(error, true)));
    groups.push(emptyState(`No ${SE2_GROUPS[kind][1].toLowerCase()} match “${found.query}”.`, all));
  }
  $("se2-results").replaceChildren(...groups);
}
function se2Chips(found) {
  $("se2-kinds").replaceChildren(...SE2_KINDS.map(([kind, label]) => {
    const total = kind === "all" ? found.total : found[SE2_GROUPS[kind][0]].total;
    const chip = element("button", "", "chip"); chip.type = "button"; chip.dataset.kind = kind;
    chip.append(element("span", label), element("span", String(total), "chip-count"));
    chip.setAttribute("aria-pressed", String(kind === se2.kind));
    chip.disabled = !total && kind !== se2.kind;
    chip.addEventListener("click", () => { if (kind !== se2.kind) se2SetKind(kind).catch(error => notice(error, true)); });
    return chip;
  }));
}
// One kind's results: a region with its heading, "Show all" when the server has more, and a divided list.
function se2Group(kind, found) {
  const [key, title] = SE2_GROUPS[kind], group = found[key];
  if (!group.total) return null;
  const region = element("section", "", "today-region se2-group"); region.dataset.kind = kind;
  const heading = element("h2", `${title} · ${group.total}`); heading.id = `se2-heading-${kind}`;
  region.setAttribute("aria-labelledby", heading.id);
  if (group.total > group.items.length && se2.kind === "all") {
    const more = element("button", `Show all ${group.total}`, "link-button se2-more"); more.type = "button";
    more.addEventListener("click", () => se2SetKind(kind).catch(error => notice(error, true)));
    heading.append(more);
  }
  const rows = {documents: se2DocumentRow, transactions: se2TransactionRow, items: se2ItemRow, accounts: se2AccountRow}[kind];
  const list = element("ul", "", "se2-list");
  for (const record of group.items) list.append(rows(record));
  region.append(heading, list);
  // A single kind shows 50; past that, the kind's own page has the full list.
  const q = found.query;
  if (se2.kind !== "all" && group.total > group.items.length) {
    if (kind === "documents") region.append(homeLink("Open these in Documents", `#/documents?${new URLSearchParams({q})}`, "se2-onward"));
    if (kind === "transactions") region.append(homeLink("Open in Transactions", `#/transactions?${new URLSearchParams({q, period: "all"})}`, "se2-onward"));
  }
  return region;
}
function se2Row(link, detail, right = null, extra = null) {
  const row = element("li", "", "se2-row"), main = element("div", "", "se2-main");
  main.append(link, element("p", detail, "se2-detail muted"));
  if (extra) main.append(extra);
  row.append(main);
  if (right) { const side = element("div", "", "se2-side"); side.append(right); row.append(side); }
  return row;
}
function se2DocumentRow(doc) {
  let snippet = null;
  if (doc.match) { snippet = matchSnippet(doc.match); snippet.title = snippet.textContent; }
  return se2Row(homeLink(documentName(doc), documentHref(doc), "se2-title"),
                [folderLabel(doc.folder), doc.document_date && dateText(doc.document_date)].filter(Boolean).join(" · "),
                doc.ledger_amount ? amount(doc.ledger_amount, {signed: false}) : null, snippet);
}
function se2TransactionRow(row) {
  const open = element("button", row.merchant || row.description_raw, "link-button se2-title"); open.type = "button";
  open.addEventListener("click", () => openTransaction(row.id));
  return se2Row(open, [dateText(row.posted_date), row.account, categoryLabel(row.category)].filter(Boolean).join(" · "), amount(row.amount));
}
function se2ItemRow(lot) {
  return se2Row(homeLink(productName(lot), `#/inventory?${new URLSearchParams({q: lot.name})}`, "se2-title"),
                [lot.category, lot.bought_on && `bought ${dateText(lot.bought_on)}`].filter(Boolean).join(" · "),
                lot.status ? statusBadge(lot.status) : null);
}
function se2AccountRow(account) {
  return se2Row(homeLink(account.display_name, `#/transactions?${new URLSearchParams({account: account.id, period: "all"})}`, "se2-title"),
                `${account.institution} · ${account.currency}`);
}
// Nothing found: the next step is a search of one store's own page, which matches more loosely.
function se2Empty(query) {
  const box = emptyState(`Nothing matches “${query}”.`), next = element("p", "", "muted small");
  next.append("Try fewer words, or search ", homeLink("the text of your documents", `#/documents?${new URLSearchParams({q: query})}`),
              " or ", homeLink("your transactions", `#/transactions?${new URLSearchParams({q: query, period: "all"})}`), ".");
  box.append(next);
  return box;
}

$("se2-submit").prepend(icon("search"));
$("se2-form").addEventListener("submit", event => {
  event.preventDefault();
  const q = $("se2-input").value.trim(), target = se2Href(q, q ? se2.kind : "all");
  if (location.hash === target) se2Render().catch(error => notice(error, true)); else location.hash = target;
});
