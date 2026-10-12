"use strict";
// Transactions, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/money.md): search and the Items/Charges
// view, period chips and filters, then one table that stacks into rows on a phone. Add a payment and Import open the
// shared dialogs (money_v2.js). The URL keys are the ones every deep link uses (q, start, end, account, category, types,
// status, receipt, sort, period, view, currency, metric, categories).
const TX2_FIELDS = {q: "tx2-search", start: "tx2-from", end: "tx2-to", account: "tx2-account", category: "tx2-category",
                    types: "tx2-type", status: "tx2-status", receipt: "tx2-receipt", sort: "tx2-sort"};
const TX2_PERIODS = ["this_month", "last_month", "last_90", "year", "all", "custom"];
const tx2 = {params: new URLSearchParams(), view: "items", period: "last_90", load: 0, newId: null, selected: null};

V2_SCREENS.transactions = {title: "Transactions", show: route => loadTransactionsV2(route.params)};

// A period's dates: [start, end], or null for a custom range.
function tx2Range(period) {
  const now = new Date(), month = todayIso().slice(0, 7);
  return {this_month: [`${month}-01`, todayIso()], last_month: Object.values(monthRange(shiftMonth(month, -1))),
          last_90: [isoDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 89)), todayIso()],
          year: [`${now.getFullYear()}-01-01`, todayIso()], all: ["", ""]}[period] || null;
}
async function tx2Options() {
  const [{accounts}, categories] = await Promise.all([ledgerTool("get_accounts"), loadCategoryOptions()]);
  $("tx2-account").replaceChildren(new Option("All accounts", ""), ...accounts.map(accountOption));
  $("tx2-category").replaceChildren(new Option("All categories", ""), new Option("Uncategorized", "uncategorized"),
    ...categories.filter(name => name !== "uncategorized").map(name => new Option(categoryLabel(name), name)));
}
function loadTransactionsV2(params) {
  tx2.params = new URLSearchParams(params);
  if (!tx2.params.has("start") && !tx2.params.has("end") && !tx2.params.has("period")) tx2.params.set("period", "last_90");
  // Items lists spending only: a drill-down to money in or cash flow opens the charges, where those rows are.
  if (["inflow", "cashflow"].includes(tx2.params.get("metric")) && !tx2.params.has("view")) tx2.params.set("view", "charges");
  return pageState($("tx2-state"), async () => {
    await tx2Options();
    tx2.view = tx2.params.get("view") === "charges" ? "charges" : "items";
    for (const [key, id] of Object.entries(TX2_FIELDS)) {
      const value = tx2.params.get(key) || (key === "sort" ? "date_desc" : "");
      // A deep link's value the options don't list yet (an account or category) is still applied.
      if ($(id).tagName === "SELECT" && value && ![...$(id).options].some(option => option.value === value)) $(id).add(new Option(value, value));
      $(id).value = value;
    }
    tx2.period = TX2_PERIODS.includes(tx2.params.get("period")) ? tx2.params.get("period") : "custom";
    const range = tx2Range(tx2.period);
    if (range) [$("tx2-from").value, $("tx2-to").value] = range;
    tx2Controls();
    await tx2Table();
  }, {loading: "Loading transactions …", what: "transactions", needsLibrary: !familyMode, content: [$("tx2-body")]});
}
function tx2Controls() {
  for (const tab of document.querySelectorAll("#tx2-view [role=tab]")) {
    const active = tab.id === `tx2-view-${tx2.view}`;
    tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1;
  }
  for (const chip of document.querySelectorAll("#tx2-periods .chip")) chip.setAttribute("aria-pressed", String(chip.dataset.period === tx2.period));
  $("tx2-dates").hidden = tx2.period !== "custom";
  // Type, status, receipt and sort apply to charges only.
  const items = tx2.view === "items";
  for (const id of ["tx2-type", "tx2-status", "tx2-receipt", "tx2-sort"]) $(id).disabled = items;
  $("tx2-more-hint").hidden = !items;
}
// The controls into the URL, then the table again. Hidden filters from a drill-down (currency, metric, categories) stay.
function tx2Changed(period = tx2.period) {
  const next = new URLSearchParams();
  for (const key of ["currency", "metric", "categories"]) if (tx2.params.get(key)) next.set(key, tx2.params.get(key));
  if (tx2.view === "charges") next.set("view", "charges");
  for (const [key, id] of Object.entries(TX2_FIELDS)) {
    if (!$(id).value || (key === "sort" && $(id).value === "date_desc")) continue;
    if (["start", "end"].includes(key) && period !== "custom") continue;
    next.set(key, $(id).value);
  }
  if (period !== "custom") next.set("period", period);
  tx2.period = period; tx2.params = next;
  tx2WriteUrl();
  tx2Controls();
  return tx2Table();
}
function tx2WriteUrl() {
  if (currentRoute?.name === "transactions") currentRoute.params = tx2.params;
  history.replaceState(null, "", `#/transactions${[...tx2.params].length ? `?${tx2.params}` : ""}`);
}
// The tool's arguments from plain values.
function tx2Query(items) {
  const args = {limit: TX_PAGE, offset: Number(tx2.params.get("offset") || 0)};
  if ($("tx2-from").value) args.start = $("tx2-from").value;
  if ($("tx2-to").value) args.end = $("tx2-to").value;
  if ($("tx2-search").value.trim()) args.query = $("tx2-search").value.trim();
  accountArgs(args, $("tx2-account").value);
  if ($("tx2-category").value) args.category = $("tx2-category").value;
  if (tx2.params.get("currency")) args.currency = tx2.params.get("currency");
  if (tx2.params.get("categories")) {
    try { const values = JSON.parse(tx2.params.get("categories")); if (Array.isArray(values) && values.every(value => typeof value === "string")) args.categories = values; } catch {}
  }
  if (items) return args;
  args.sort = $("tx2-sort").value || "date_desc";
  if ($("tx2-type").value) args.transaction_types = $("tx2-type").value.split(",");
  if ($("tx2-receipt").value) args.has_receipt = $("tx2-receipt").value === "true";
  if ($("tx2-status").value) args.statuses = [$("tx2-status").value];
  else args.include_pending = !tx2.params.get("metric");
  if (tx2.params.get("metric")) args.metric = tx2.params.get("metric");
  return args;
}
function tx2Describe(args) {
  const parts = [args.start || args.end ? `${args.start ? dateText(args.start) : "any date"} – ${args.end ? dateText(args.end) : "today"}` : "All dates"];
  if ($("tx2-account").value) parts.push($("tx2-account").selectedOptions[0]?.textContent || "");
  if (args.category) parts.push(categoryLabel(args.category));
  if (args.currency) parts.push(args.currency);
  if (args.metric) parts.push({spending: "spending only", inflow: "money in only", cashflow: "cash flow only", categories: "category spending only"}[args.metric]);
  if (args.categories) parts.push(args.categories.map(categoryLabel).join(", "));
  return parts.filter(Boolean).join(" · ");
}
const tx2Filtered = () => [...tx2.params].some(([key]) => !["period", "view", "sort", "offset"].includes(key)) || tx2.period !== "last_90";
function reloadTx2() { return tx2Table().catch(error => notice(error, true)); }

async function tx2Table() {
  const load = ++tx2.load, items = tx2.view === "items", args = tx2Query(items);
  $("tx2-error").replaceChildren();
  let result, categories = [];
  try {
    [result, categories] = await Promise.all([ledgerTool(items ? "get_spending_items" : "get_transactions", args), items ? receiptCategories() : []]);
  } catch (error) {
    if (load !== tx2.load) return;
    // After the first render a failed reload keeps the page, with the reason and a Retry above the table.
    $("tx2-error").replaceChildren(alertBox(`Couldn't load ${items ? "spending" : "transactions"}. ${error.message}`, {tone: "error", action: asyncButton("Retry", tx2Table, "secondary")}));
    return;
  }
  if (load !== tx2.load) return;
  if (items && !familyMode) tx2Backfill().catch(() => {}); else $("tx2-backfill").replaceChildren();
  const rows = items ? result.items : result.transactions, first = result.total_matching ? args.offset + 1 : 0;
  $("tx2-summary").replaceChildren(`${result.total_matching.toLocaleString()} ${items ? (result.total_matching === 1 ? "item" : "items") : (result.total_matching === 1 ? "transaction" : "transactions")} · ${tx2Describe(args)}`);
  if (tx2Filtered()) $("tx2-summary").append(" · ", homeLink("Clear filters", "#/transactions"));
  $("tx2-page").textContent = result.total_matching ? `${first}–${args.offset + rows.length} of ${result.total_matching}` : "";
  $("tx2-prev").disabled = !args.offset;
  $("tx2-next").disabled = args.offset + rows.length >= result.total_matching;
  $("tx2-prev").parentElement.hidden = result.total_matching <= TX_PAGE;
  if (!rows.length) { $("tx2-results").replaceChildren(tx2Empty()); return; }
  const table = element("table", "", "data-table"); table.id = "tx2-table";
  table.dataset.view = tx2.view;
  const head = element("thead", "", ""), headRow = document.createElement("tr");
  const columns = items ? [["Date", "tx2-date"], ["Owner", "owner-col"], ["Item", ""], ["Account", "tx2-col-account"], ["Category", ""], ["Status", ""], ["Paid", "numeric"]]
    : [["Date", "tx2-date"], ["Owner", "owner-col"], ["Description", ""], ["Account", "tx2-col-account"], ["Category", ""], ["Receipt", ""], ["Status", ""], ["Amount", "numeric"]];
  for (const [text, className] of columns) {
    const th = element("th", "", className); th.scope = "col";
    if (text === "Receipt") th.append(element("span", text, "visually-hidden")); else th.textContent = text;
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  body.append(...rows.map(row => items ? tx2ItemRow(row, categories) : tx2ChargeRow(row)));
  table.append(head, body);
  const wrap = element("div", "", "table-wrap"); wrap.append(table);
  $("tx2-results").replaceChildren(wrap);
  // A payment just added: marked for this visit and scrolled into view (no animation).
  if (tx2.newId) {
    const added = body.querySelector(`tr[data-transaction-id="${tx2.newId}"]`);
    if (added) { added.classList.add("tx2-new"); added.scrollIntoView({block: "center"}); }
  }
}
function tx2Empty() {
  if (tx2Filtered()) return emptyState("No transactions match these filters.", homeLink("Clear filters", "#/transactions"));
  if (familyMode) return emptyState("No transactions yet. They arrive from each person's own profile.");
  const actions = element("div", "", "button-row tx2-empty-actions");
  const importButton = element("button", "Import an export", "secondary"); importButton.type = "button";
  importButton.addEventListener("click", () => importPicker({onImported: reloadTx2}));
  const add = element("button", "Add a payment", "primary"); add.type = "button";
  add.addEventListener("click", () => tx2Add());
  actions.append(importButton, add);
  return emptyState("No transactions yet.", actions);
}
async function tx2Backfill() {
  // Receipts recorded before items had categories: offer the model's sort once.
  const {receipts} = await api("/api/finance/item-categories");
  if (!receipts || tx2.view !== "items") { $("tx2-backfill").replaceChildren(); return; }
  const row = needsRow("info", `${receipts} receipt${receipts === 1 ? " has" : "s have"} items to sort into the current categories`, "The local model sorts them; you can change any.", null, null, false);
  row.append(asyncButton("Categorise their items", async () => {
    const started = await api("/api/finance/item-categories/backfill", {method: "POST"});
    notice(started.started ? `Categorising items on ${started.receipts} receipts. Follow it in Processing.` : "Nothing left to categorise.");
    $("tx2-backfill").replaceChildren();
  }, "link-button needs-action"));
  $("tx2-backfill").replaceChildren(row);
}

// Rows -------------------------------------------------------------------------------------------------------------
function tx2Cell(tr, className) { const td = cell(tr, ""); td.className = className; return td; }
function tx2Open(tr, id, member) {
  if (!id) return;
  tr.dataset.transactionId = id;
  tr.classList.add("clickable-row");
  tr.addEventListener("click", event => { if (!event.target.closest("a, button, select, input")) tx2Drawer(tr, id, member); });
}
function tx2Drawer(tr, id, member) {
  document.querySelector('#tx2-table tr[aria-selected="true"]')?.removeAttribute("aria-selected");
  tr.setAttribute("aria-selected", "true");
  tx2.selected = tr;
  return openTransaction(id, member, {onChange: reloadTx2}).catch(error => notice(error, true));
}
function tx2Name(tr, row, name, detail) {
  const described = tx2Cell(tr, "tx2-name");
  if (row.transaction_id || row.id) {
    const open = element("button", name, "link-button"); open.type = "button";
    open.addEventListener("click", () => tx2Drawer(tr, row.transaction_id || row.id, row.member_id));
    described.append(open);
  } else if (row.receipt_document_id && familyMode) described.append(originalButton(document.createTextNode(name), row.member_id, row.receipt_document_id));
  else described.append(row.receipt_document_id ? homeLink(name, `#/documents/${row.receipt_document_id}`) : element("span", name));
  const small = element("small", "", "muted block");
  // The account joins the name's line where its column is hidden (768–899px).
  const account = element("span", row.account || "Receipt", "tx2-account-inline");
  small.append(account, ...(detail ? [element("span", detail, "tx2-detail")] : []));
  described.append(small);
  return described;
}
function tx2ItemRow(row, categories) {
  const tr = document.createElement("tr");
  tr.append(tx2When(row.date));
  if (familyMode) tx2Cell(tr, "owner-col").textContent = row.owner || "";
  const name = row.kind === "item" ? row.item : row.kind === "extra" ? (row.category === "dining" ? "Tip" : "Other charges") : row.merchant;
  const detail = [row.kind === "charge" ? (row.merchant !== row.description ? row.description : "") : row.merchant,
                  row.line_total && row.line_total.display !== row.amount.display ? `price ${row.line_total.display}` : ""].filter(Boolean).join(" · ");
  tx2Name(tr, {...row, id: null}, name, detail);
  tx2Cell(tr, "tx2-col-account").textContent = row.account || "Receipt";
  const category = tx2Cell(tr, "tx2-category");
  if (familyMode) category.textContent = categoryLabel(row.category === "uncategorized" ? null : row.category);
  else if (row.kind === "item") category.append(itemCategorySelect(row.receipt_id, {item: row.item, position: row.position, category: row.category,
                                                                                    category_source: row.item_category_source}, categories, reloadTx2));
  else if (row.source === "transaction") category.append(chargeCategorySelect(row, reloadTx2));
  else category.textContent = categoryLabel(row.category === "uncategorized" ? null : row.category);
  const status = tx2Cell(tr, "tx2-status"); status.append(statusBadge(row.status));
  if (row.pending_fields?.length) status.append(element("small", `Waiting for ${row.owner}`, "muted block pending-tag"));
  tx2Cell(tr, "numeric tx2-amount").append(amount(row.amount, {signed: false}));
  tx2Open(tr, row.transaction_id, row.member_id);
  return tr;
}
function tx2ChargeRow(row) {
  const tr = document.createElement("tr");
  const notSpending = ["transfer", "payment"].includes(row.transaction_type);
  tr.append(tx2When(row.posted_date));
  if (familyMode) tx2Cell(tr, "owner-col").textContent = row.owner || "";
  const name = tx2Name(tr, {...row, transaction_id: row.id}, row.merchant || row.description_raw,
    row.merchant && row.merchant !== row.description_raw ? row.description_raw : "");
  if (notSpending) { name.classList.add("muted"); name.prepend(icon("transfer", "icon tx2-transfer")); }
  tx2Cell(tr, "tx2-col-account").textContent = row.account;
  const category = tx2Cell(tr, "tx2-category");
  if (notSpending) category.append(element("span", "—", "muted"));
  else if (familyMode) category.textContent = categoryLabel(row.category);
  else category.append(chargeCategorySelect({...row, transaction_id: row.id, merchant: row.merchant || row.description_raw, category: row.category || "uncategorized"}, reloadTx2));
  const evidence = tx2Cell(tr, "receipt-cell tx2-receipt");
  if (row.receipt_document_id) evidence.append(familyMode ? originalButton(icon("paperclip"), row.member_id, row.receipt_document_id, "Open the matched receipt") : receiptLink(row));
  const status = tx2Cell(tr, "tx2-status");
  if (row.origin === "manual") status.append(statusBadge("prov_manual"));
  else if (!row.counted) status.append(statusBadge(row.review_status));
  if (row.pending_fields?.length) status.append(element("small", `Waiting for ${row.owner}`, "muted block pending-tag"));
  if (notSpending) status.append(element("small", "Not spending", "muted block"));
  if (row.shared_part) status.append(element("small", `Shared expense · your part ${row.shared_part.display} counted`, "muted block"));
  const value = tx2Cell(tr, "numeric tx2-amount"); value.append(amount(row.amount));
  if (notSpending) value.classList.add("muted");
  tx2Open(tr, row.id, row.member_id);
  return tr;
}
function tx2When(day) { const td = element("td", "", "tx2-date"); td.append(dateDisplay(day)); return td; }

function tx2Add() {
  return addTransactionDialog({onSaved: record => { tx2.newId = record?.id || null; return tx2Changed(); }}).catch(error => notice(error, true));
}

// Controls -----------------------------------------------------------------------------------------------------------
function tx2SetView(view, focus = false) {
  if (tx2.view === view) return;
  tx2.view = view;
  tx2.params.delete("offset");
  if (focus) $(`tx2-view-${view}`).focus();
  tx2Changed().catch(error => notice(error, true));
}
for (const tab of document.querySelectorAll("#tx2-view [role=tab]")) {
  tab.addEventListener("click", () => tx2SetView(tab.id.replace("tx2-view-", "")));
  tab.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    tx2SetView(["ArrowLeft", "Home"].includes(event.key) ? "items" : "charges", true);
  });
}
for (const chip of document.querySelectorAll("#tx2-periods .chip")) chip.addEventListener("click", () => {
  const period = chip.dataset.period;
  tx2.params.delete("offset");
  if (period === "custom") { tx2.period = "custom"; tx2Controls(); $("tx2-from").focus(); return; }
  [$("tx2-from").value, $("tx2-to").value] = tx2Range(period);
  tx2Changed(period).catch(error => notice(error, true));
});
for (const id of ["tx2-from", "tx2-to"]) $(id).addEventListener("change", () => { tx2.params.delete("offset"); tx2Changed("custom").catch(error => notice(error, true)); });
for (const id of ["tx2-account", "tx2-category", "tx2-type", "tx2-status", "tx2-receipt", "tx2-sort"]) {
  $(id).addEventListener("change", () => { tx2.params.delete("offset"); tx2Changed().catch(error => notice(error, true)); });
}
$("tx2-search").addEventListener("search", () => { tx2.params.delete("offset"); tx2Changed().catch(error => notice(error, true)); });
$("tx2-search").addEventListener("keydown", event => { if (event.key === "Enter") { tx2.params.delete("offset"); tx2Changed().catch(error => notice(error, true)); } });
for (const [id, direction] of [["tx2-prev", -1], ["tx2-next", 1]]) $(id).addEventListener("click", () => {
  const offset = Math.max(0, Number(tx2.params.get("offset") || 0) + direction * TX_PAGE);
  if (offset) tx2.params.set("offset", offset); else tx2.params.delete("offset");
  tx2WriteUrl();
  tx2Table().then(() => $("tx2-title").scrollIntoView()).catch(error => notice(error, true));
});
$("tx2-import").prepend(icon("upload"));
$("tx2-add").prepend(icon("plus"));
$("tx2-import").addEventListener("click", () => importPicker({onImported: reloadTx2}));
$("tx2-add").addEventListener("click", () => tx2Add());
$("tx-drawer").addEventListener("close", () => { tx2.selected?.removeAttribute("aria-selected"); tx2.selected = null; });
