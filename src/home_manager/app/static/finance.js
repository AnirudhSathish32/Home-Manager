"use strict";
// Money pages (docs/money.md "Money pages"): Transactions, Spending & budgets, Bills & recurring, Accounts.
// Every figure comes from a deterministic server tool as exact display text; the browser does no money arithmetic.
const tool = (name, args = {}) => api(`/api/finance/tools/${name}`, {method: "POST", body: JSON.stringify(args)});
// The ledger pages (Transactions, Spending, Bills, Accounts): in the family view, every member's records, each row with
// its owner (docs/family.md "Family ledger"); otherwise this profile's own.
const ledgerTool = (name, args = {}) => familyMode
  ? api(`/api/finance/tools/${name}?members=true`, {method: "POST", body: JSON.stringify(args)}) : tool(name, args);
// A record in the drawer: in the family view it's read from its owner's copy.
const recordUrl = (type, id, member) => `/api/finance/records/${type}/${id}${member ? `?member=${member}` : ""}`;
// In the family view an account is "<member id>:<account id>": ids are only unique within one person's library.
const accountOption = account => familyMode ? new Option(`${account.owner} · ${account.display_name}`, `${account.member_id}:${account.id}`)
  : new Option(account.display_name, account.id);
function accountArgs(args, value) {
  if (!value) return args;
  if (familyMode) { const [member, id] = value.split(":"); return Object.assign(args, {member, account_id: Number(id)}); }
  return Object.assign(args, {account_id: Number(value)});
}
function ownerCell(tr, row) { if (familyMode) cell(tr, row.owner || "").className = "owner-col"; }
const pad = value => String(value).padStart(2, "0");
function isoDay(day) { return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`; }
function todayIso() { return isoDay(new Date()); }
function monthRange(value) {
  const [year, month] = value.split("-").map(Number);
  return {start: `${value}-01`, end: `${value}-${pad(new Date(year, month, 0).getDate())}`};
}
function shiftMonth(value, delta) {
  const [year, month] = value.split("-").map(Number), day = new Date(year, month - 1 + delta, 1);
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}`;
}
function refreshReviewCount() { if (typeof loadNavCounts === "function") loadNavCounts().catch(() => {}); }
function asyncButton(label, onClick, className = "small") {
  const button = element("button", label, className); button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await onClick(); } catch (error) { notice(error, true); } finally { button.disabled = false; }
  });
  return button;
}
function tableMessage(target, columns, message) {
  const row = document.createElement("tr"), td = element("td", message, "muted"); td.colSpan = columns; row.append(td); target.replaceChildren(row);
}
let categoryCache = null;
async function loadCategoryOptions() {
  categoryCache = (await ledgerTool("get_categories")).categories.map(row => row.category);
  $("category-options").replaceChildren(...categoryCache.map(name => new Option(name)));
  return categoryCache;
}

// Old links: #/finances?section=… goes to the page that now holds that section, keeping the filters.
function openFinanceRoute(params) {
  const section = params.get("section");
  params.delete("section");
  const target = section === "review" || section === "unmatched" ? "review" : section === "bills" ? "bills" : "transactions";
  if (target === "bills") { params.delete("as_of"); }
  location.replace(`#/${target}${[...params].length ? `?${params}` : ""}`);
}

// Transactions -----------------------------------------------------------------------------------------------

const TX_PAGE = 200;
const TX_FIELDS = {view: "tx-view", q: "tx-search", start: "tx-from", end: "tx-to", account: "tx-account", category: "tx-category", types: "tx-type",
                   status: "tx-status", receipt: "tx-receipt", sort: "tx-sort"};
// Items (the default) lists spending item by item; Charges lists each card or bank line once.
const itemView = () => $("tx-view").value !== "charges";
let txParams = new URLSearchParams(), txLoad = 0;
async function loadTransactionOptions() {
  const [{accounts}, categories] = await Promise.all([ledgerTool("get_accounts"), loadCategoryOptions()]);
  for (const [id, label] of [["tx-account", "All accounts"], ["rule-account", "Any account"]]) {
    const chosen = $(id).value;
    $(id).replaceChildren(new Option(label, ""), ...accounts.map(accountOption));
    $(id).value = chosen;
  }
  const chosen = $("tx-category").value;
  $("tx-category").replaceChildren(new Option("All categories", ""), new Option("Uncategorized", "uncategorized"), ...categories.map(name => new Option(name)));
  $("tx-category").value = chosen;
}
async function openTransactions(params) {
  txParams = new URLSearchParams(params);
  if (!txParams.has("start") && !txParams.has("end") && !txParams.has("period")) txParams.set("period", "last_90");
  // Items lists spending only: a drill-down to money in or cash flow opens the charges, where those rows are.
  if (["inflow", "cashflow"].includes(txParams.get("metric")) && !txParams.has("view")) txParams.set("view", "charges");
  await loadTransactionOptions();
  for (const [key, id] of Object.entries(TX_FIELDS)) $(id).value = txParams.get(key) || (key === "sort" ? "date_desc" : "");
  $("tx-period").value = txParams.get("period") || "custom";
  if (txParams.get("period")) applyPeriod(txParams.get("period"), false);
  await loadTransactions();
}
function applyPeriod(period, write = true) {
  const today = new Date(), month = todayIso().slice(0, 7);
  const ranges = {this_month: [`${month}-01`, todayIso()], last_month: Object.values(monthRange(shiftMonth(month, -1))),
                  last_90: [isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 89)), todayIso()],
                  year: [`${today.getFullYear()}-01-01`, todayIso()], all: ["", ""]};
  if (!ranges[period]) return;
  [$("tx-from").value, $("tx-to").value] = ranges[period];
  if (write) txChanged(period);
}
function txChanged(period = "custom") {
  // Filters live in the URL so Back and reload keep them. Hidden filters from Home (currency, metric, categories) stay until cleared.
  const next = new URLSearchParams();
  for (const key of ["currency", "metric", "categories"]) if (txParams.get(key)) next.set(key, txParams.get(key));
  for (const [key, id] of Object.entries(TX_FIELDS)) if ($(id).value && !(key === "sort" && $(id).value === "date_desc")) next.set(key, $(id).value);
  if (period !== "custom") { next.set("period", period); next.delete("start"); next.delete("end"); }
  $("tx-period").value = period;
  txParams = next;
  history.replaceState(null, "", `#/transactions${[...next].length ? `?${next}` : ""}`);
  loadTransactions().catch(error => notice(error, true));
}
function transactionQuery() {
  const args = {limit: TX_PAGE, offset: Number(txParams.get("offset") || 0), sort: $("tx-sort").value || "date_desc"};
  if ($("tx-from").value) args.start = $("tx-from").value;
  if ($("tx-to").value) args.end = $("tx-to").value;
  if ($("tx-search").value.trim()) args.query = $("tx-search").value.trim();
  accountArgs(args, $("tx-account").value);
  if ($("tx-category").value) args.category = $("tx-category").value;
  if ($("tx-type").value) args.transaction_types = $("tx-type").value.split(",");
  if ($("tx-receipt").value) args.has_receipt = $("tx-receipt").value === "true";
  if ($("tx-status").value) args.statuses = [$("tx-status").value];
  else args.include_pending = !txParams.get("metric");
  if (txParams.get("currency")) args.currency = txParams.get("currency");
  if (txParams.get("metric")) args.metric = txParams.get("metric");
  if (txParams.get("categories")) {
    try { const values = JSON.parse(txParams.get("categories")); if (Array.isArray(values) && values.every(value => typeof value === "string")) args.categories = values; } catch {}
  }
  return args;
}
function describeFilters(args) {
  const parts = [args.start || args.end ? `${args.start ? dateText(args.start) : "any date"} – ${args.end ? dateText(args.end) : "today"}` : "All dates"];
  if (args.account_id) parts.push($("tx-account").selectedOptions[0].textContent);
  if (args.category) parts.push(args.category);
  if (args.currency) parts.push(args.currency);
  if (args.metric) parts.push({spending: "spending only", inflow: "money in only", cashflow: "cash flow only", categories: "category spending only"}[args.metric]);
  if (args.categories) parts.push(args.categories.join(", "));
  return parts.join(" · ");
}
async function loadTransactions() {
  if (!configured) return;
  const items = itemView();
  $("item-table").hidden = !items; $("charge-table").hidden = items;
  for (const field of document.querySelectorAll("#transactions-panel .charges-only")) field.hidden = items;
  if (!items) $("item-backfill").hidden = true;
  if (items) return loadItems();
  const load = ++txLoad, args = transactionQuery();
  let result;
  try { result = await ledgerTool("get_transactions", args); }
  catch (error) { if (load === txLoad) tableMessage($("tx-rows"), 7, `Couldn't load transactions. ${error.message}`); throw error; }
  if (load !== txLoad) return;
  const rows = result.transactions, first = result.total_matching ? args.offset + 1 : 0;
  $("tx-summary").replaceChildren(document.createTextNode(`${result.total_matching.toLocaleString()} transactions · ${describeFilters(args)}. `));
  if ([...txParams].some(([key]) => !["period", "sort"].includes(key))) $("tx-summary").append(homeLink("Clear filters", "#/transactions"));
  $("tx-page").textContent = result.total_matching ? `${first}–${args.offset + rows.length} of ${result.total_matching}` : "";
  $("tx-prev").disabled = !args.offset;
  $("tx-next").disabled = args.offset + rows.length >= result.total_matching;
  if (!rows.length) { tableMessage($("tx-rows"), 7, [...txParams].length > 1 ? "No transactions match these filters." : "No transactions yet. Import a bank or card export, or extract a statement."); return; }
  $("tx-rows").replaceChildren(...rows.map(transactionRow));
}
function transactionRow(row) {
  const tr = document.createElement("tr"); tr.className = "clickable-row";
  cell(tr, "").appendChild(dateDisplay(row.posted_date));
  ownerCell(tr, row);
  const described = cell(tr, ""), open = element("button", row.merchant || row.description_raw, "link-button");
  open.type = "button"; open.addEventListener("click", () => openTransaction(row.id, row.member_id));
  described.append(open);
  if (row.merchant && row.merchant !== row.description_raw) described.append(element("small", row.description_raw, "muted block"));
  cell(tr, row.account);
  const category = cell(tr, row.category || "—");
  if (!row.category) category.className = "muted";
  else if (row.category_source === "rule") category.title = "Set by a category rule";
  const evidence = cell(tr, ""); evidence.className = "receipt-cell";
  if (row.receipt_document_id) evidence.appendChild(familyMode ? originalButton(icon("paperclip"), row.member_id, row.receipt_document_id, "Open the matched receipt") : receiptLink(row));
  const status = cell(tr, "");
  if (!row.counted) status.append(statusBadge(row.review_status));
  if (row.pending_fields?.length) status.append(element("small", `Waiting for ${row.owner}`, "muted block pending-tag"));
  if (["transfer", "payment"].includes(row.transaction_type)) status.append(element("small", "Not spending", "muted block"));
  // A charge for a cost the family shared: the bank shows all of it, this profile counts its own part.
  if (row.shared_part) status.append(element("small", `Shared expense · your part ${row.shared_part.display} counted`, "muted block"));
  const value = cell(tr, ""); value.className = "numeric"; value.appendChild(amount(row.amount));
  if (["transfer", "payment"].includes(row.transaction_type)) value.classList.add("muted");
  tr.addEventListener("click", event => { if (!event.target.closest("a, button")) openTransaction(row.id, row.member_id); });
  return tr;
}
// A member's original, from the family computer (it opens while their app is stopped): fetched with this session's token,
// then shown in a new tab.
function originalButton(content, member, documentId, label) {
  const button = element("button", "", "link-button"); button.type = "button"; button.append(content);
  if (label) { button.title = label; button.setAttribute("aria-label", label); }
  button.addEventListener("click", async () => {
    const view = window.open("", "_blank");
    try {
      const response = await fetch(`/api/documents/${documentId}/image?member=${member}`, {headers: {"Authorization": `Bearer ${token}`}});
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "The document couldn't be opened.");
      const url = URL.createObjectURL(await response.blob());
      if (view) view.location = url; else window.location.assign(url);
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { if (view) view.close(); notice(error, true); }
  });
  return button;
}
// Items: every counted charge and receipt, one row per item with its share of what was paid (docs/money.md).
function itemQuery() {
  const args = {limit: TX_PAGE, offset: Number(txParams.get("offset") || 0)};
  if ($("tx-from").value) args.start = $("tx-from").value;
  if ($("tx-to").value) args.end = $("tx-to").value;
  if ($("tx-search").value.trim()) args.query = $("tx-search").value.trim();
  accountArgs(args, $("tx-account").value);
  if ($("tx-category").value) args.category = $("tx-category").value;
  // A drill-down from Home or Spending: its category group and currency (items are spending, so the metric is implied).
  const {categories, currency} = transactionQuery();
  if (categories) args.categories = categories;
  if (currency) args.currency = currency;
  return args;
}
async function loadItems() {
  const load = ++txLoad, args = itemQuery();
  let result, categories;
  try { [result, categories] = await Promise.all([ledgerTool("get_spending_items", args), receiptCategories()]); }
  catch (error) { if (load === txLoad) tableMessage($("item-rows"), 6, `Couldn't load spending. ${error.message}`); throw error; }
  if (load !== txLoad) return;
  if (!familyMode) showItemBackfill().catch(() => {});
  const rows = result.items, first = result.total_matching ? args.offset + 1 : 0;
  $("tx-summary").replaceChildren(document.createTextNode(`${result.total_matching.toLocaleString()} items · ${describeFilters(args)}. `));
  if ([...txParams].some(([key]) => !["period", "view"].includes(key))) $("tx-summary").append(homeLink("Clear filters", "#/transactions"));
  $("tx-page").textContent = result.total_matching ? `${first}–${args.offset + rows.length} of ${result.total_matching}` : "";
  $("tx-prev").disabled = !args.offset;
  $("tx-next").disabled = args.offset + rows.length >= result.total_matching;
  if (!rows.length) { tableMessage($("item-rows"), 6, [...txParams].length > 1 ? "No spending matches these filters." : "No spending yet. Add receipts, import a bank or card export, or extract a statement."); return; }
  $("item-rows").replaceChildren(...rows.map(row => itemRow(row, categories)));
}
async function showItemBackfill() {
  // Receipts recorded before items had categories, or with items under a retired category: offer the model's sort once.
  const {receipts} = await api("/api/finance/item-categories"), target = $("item-backfill");
  target.hidden = !receipts || !itemView();
  if (target.hidden) return;
  target.replaceChildren(document.createTextNode(`${receipts} receipt${receipts === 1 ? " has" : "s have"} items to sort into the current categories. `),
                         asyncButton("Categorise their items", async () => {
                           const started = await api("/api/finance/item-categories/backfill", {method: "POST"});
                           notice(started.started ? `Categorising items on ${started.receipts} receipts. Follow it in Processing.` : "Nothing left to categorise.");
                           target.hidden = true;
                         }));
}
function itemRow(row, categories) {
  const tr = document.createElement("tr");
  cell(tr, "").appendChild(dateDisplay(row.date));
  ownerCell(tr, row);
  const described = cell(tr, "");
  const name = row.kind === "item" ? row.item : row.kind === "extra" ? (row.category === "dining" ? "Tip" : "Other charges") : row.merchant;
  if (row.source === "transaction") {
    const open = element("button", name, "link-button"); open.type = "button"; open.addEventListener("click", () => openTransaction(row.transaction_id, row.member_id));
    described.append(open);
  } else if (row.receipt_document_id && familyMode) described.append(originalButton(document.createTextNode(name), row.member_id, row.receipt_document_id));
  else described.append(row.receipt_document_id ? homeLink(name, `#/documents/${row.receipt_document_id}`) : document.createTextNode(name));
  const detail = [row.kind === "charge" ? (row.merchant !== row.description ? row.description : "") : row.merchant,
                  row.line_total && row.line_total.display !== row.amount.display ? `price ${row.line_total.display}` : ""].filter(Boolean).join(" · ");
  if (detail) described.append(element("small", detail, "muted block"));
  cell(tr, row.account || "Receipt");
  const category = cell(tr, "");
  if (familyMode) {
    category.textContent = categoryLabel(row.category === "uncategorized" ? null : row.category);  // Changed in the person's own profile.
  } else if (row.kind === "item") {
    category.append(itemCategorySelect(row.receipt_id, {item: row.item, position: row.position, category: row.category, category_source: row.item_category_source},
                                       categories, () => loadTransactions()));
  } else if (row.source === "transaction") {
    category.append(chargeCategorySelect(row));
  } else {
    category.textContent = categoryLabel(row.category === "uncategorized" ? null : row.category);
    if (row.kind === "extra") category.title = "Tax, tip or amounts the receipt doesn't list by item";
  }
  const status = cell(tr, ""); status.append(statusBadge(row.status));
  if (row.pending_fields?.length) status.append(element("small", `Waiting for ${row.owner}`, "muted block pending-tag"));
  const value = cell(tr, ""); value.className = "numeric"; value.appendChild(amount(row.amount, {signed: false}));
  return tr;
}
function chargeCategorySelect(row) {
  // A charge with no itemised receipt has one category for all of it: the same choice as in the transaction drawer.
  const select = document.createElement("select"); select.setAttribute("aria-label", `Category of ${row.merchant}`);
  const names = [...new Set([...(categoryCache || []), ...(receiptCategoryCache || []), ...(row.category !== "uncategorized" ? [row.category] : [])])].sort();
  select.add(new Option("Uncategorized", ""));
  for (const name of names) select.add(new Option(categoryLabel(name), name));
  select.add(new Option("New category…", "__new"));
  select.value = row.category === "uncategorized" ? "" : row.category;
  select.title = row.category_source === "rule" ? "Set by a category rule" : row.category_source === "user" ? "Set by you" : "";
  select.addEventListener("change", async () => {
    if (select.value === "__new") { select.value = row.category === "uncategorized" ? "" : row.category; openTransaction(row.transaction_id); return; }
    select.disabled = true;
    try {
      await api(`/api/finance/transactions/${row.transaction_id}/category`, {method: "PUT", body: JSON.stringify({category: select.value || null})});
      notice(select.value ? `${row.merchant} is now ${categoryLabel(select.value)}.` : `Category cleared; any matching rule applies again.`);
      await loadTransactions();
    } catch (error) { notice(error, true); } finally { select.disabled = false; }
  });
  return select;
}
function receiptLink(row) {
  // Opens the receipt matched to this transaction; a proposed match says so until it is confirmed.
  const link = element("a", "", "receipt-link"); link.href = `#/documents/${row.receipt_document_id}`;
  const proposed = row.receipt_link_status === "proposed", kind = row.transaction_type === "refund" ? "Return receipt" : "Receipt";
  link.append(icon("paperclip"), element("span", proposed ? `${kind} (proposed)` : kind, "visually-hidden-narrow"));
  link.title = `Matched ${kind.toLowerCase()}${proposed ? ", awaiting your confirmation in Review" : ""}`;
  return link;
}
for (const id of Object.values(TX_FIELDS)) $(id).addEventListener(id === "tx-search" ? "search" : "change", () => txChanged());
$("tx-search").addEventListener("keydown", event => { if (event.key === "Enter") txChanged(); });
$("tx-period").addEventListener("change", () => applyPeriod($("tx-period").value));
$("tx-clear").addEventListener("click", () => { location.hash = "#/transactions"; });
for (const [id, direction] of [["tx-prev", -1], ["tx-next", 1]]) $(id).addEventListener("click", () => {
  txParams.set("offset", Math.max(0, Number(txParams.get("offset") || 0) + direction * TX_PAGE));
  history.replaceState(null, "", `#/transactions?${txParams}`);
  loadTransactions().then(() => $("transactions-title").scrollIntoView()).catch(error => notice(error, true));
});

// Transaction drawer: the record with its evidence, links, category and history.
const LINK_NAMES = {receipt: "Matched receipt", transfer: "Transfer between your accounts", refund: "Refund link"};
function drawerSection(title, ...children) {
  const section = element("section", "", "drawer-section"); section.append(element("h3", title), ...children); return section;
}
function ruleWords(record) {
  // A starting suggestion only: the server normalizes the words the same way it matches them.
  return (record.merchant || record.description_raw || "").toUpperCase().replace(/#\s*\d+|\b\d+\b|[^\w\s&]/g, " ").split(/\s+/).filter(Boolean).slice(0, 3).join(" ");
}
async function openTransaction(id, member = null) {
  if (familyMode) return openFamilyTransaction(id, member);
  const [record, {tag: taxTag}] = await Promise.all([api(`/api/finance/records/transaction/${id}`), api(`/api/tax-tags/on/transaction/${id}`).catch(() => ({tag: null}))]);
  await loadCategoryOptions().catch(() => {});
  const body = $("tx-drawer-body");
  $("tx-drawer-title").textContent = record.merchant || record.description_raw;
  const head = element("div", "", "drawer-head");
  const big = amount(record.display.amount_minor); big.classList.add("drawer-amount");
  head.append(big, element("p", `${dateText(record.posted_date)} · ${record.account}${record.transaction_date && record.transaction_date !== record.posted_date ? ` · purchased ${dateText(record.transaction_date)}` : ""}`, "muted"));
  if (record.merchant) head.append(element("p", record.description_raw, "muted small"));
  // Imports count unless rejected; extracted rows count once verified (automatically or by you).
  const counted = record.review_status !== "rejected" && (record.origin !== "extraction" || record.review_status === "verified");
  const badge = record.review_status === "rejected" ? "rejected" : !counted ? record.review_status : record.review_status !== "verified" ? "imported"
    : record.review_source === "automatic" ? "checked" : "verified";
  const state = element("div", "", "drawer-status");
  state.append(statusBadge(badge), element("span", counted ? " Counted in your totals." : record.review_status === "rejected" ? " Not counted." : " Not counted until you decide.", "muted small"));
  const review = status => api(`/api/finance/records/transaction/${id}/review`, {method: "POST", body: JSON.stringify({status})})
    .then(() => { notice(status === "needs_review" ? "Returned to review." : "Saved."); refreshReviewCount(); return Promise.all([openTransaction(id), loadTransactions()]); });
  if (!counted && record.review_status !== "rejected") state.append(asyncButton("Count it", () => review("verified"), "small primary"), asyncButton("Reject", () => review("rejected")));
  else if (record.review_source === "user") state.append(asyncButton(record.review_status === "rejected" ? "Undo rejection" : "Undo verification", () => review("needs_review"), "small quiet"));
  else if (counted) state.append(asyncButton("Reject (not a real transaction)", () => review("rejected"), "small quiet"));
  // Category: the user's own choice, or a rule for every transaction like this one.
  const form = element("form", "", "drawer-category");
  const input = document.createElement("input"); input.setAttribute("list", "category-options"); input.value = record.category || ""; input.maxLength = 60;
  input.id = "tx-drawer-category"; input.setAttribute("aria-label", "Category"); input.placeholder = "e.g. groceries";
  const always = document.createElement("input"); always.type = "checkbox"; always.id = "tx-drawer-always";
  const words = document.createElement("input"); words.value = ruleWords(record); words.id = "tx-drawer-words"; words.setAttribute("aria-label", "Words the rule matches"); words.maxLength = 120;
  const ruleRow = element("label", "", "compact-check"); ruleRow.append(always, document.createTextNode(" Always use for transactions containing "), words);
  const save = element("button", "Save category", "small primary"); save.type = "submit";
  const source = element("small", record.category_source === "rule" ? "Set by a category rule. Saving here overrides it for this transaction only." :
                                  record.category_source === "user" ? "Set by you." : "No category yet.", "muted block");
  form.append(input, save, ruleRow, source);
  if (record.category_source === "user") form.append(asyncButton("Clear my category", async () => {
    await api(`/api/finance/transactions/${id}/category`, {method: "PUT", body: JSON.stringify({category: null})});
    notice("Category cleared; any matching rule applies again."); await Promise.all([openTransaction(id), loadTransactions()]);
  }, "small quiet"));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const category = input.value.trim();
    if (!category) { notice("Enter a category, or use Clear my category.", true); return; }
    try {
      if (always.checked) {
        const rule = await api("/api/finance/category-rules", {method: "POST", body: JSON.stringify({pattern: words.value.trim(), category})});
        if (record.category_source === "user") await api(`/api/finance/transactions/${id}/category`, {method: "PUT", body: JSON.stringify({category: null})});
        notice(`Rule saved: “${rule.pattern}” → ${rule.category}. ${rule.changed} transaction${rule.changed === 1 ? "" : "s"} updated.`);
      } else {
        await api(`/api/finance/transactions/${id}/category`, {method: "PUT", body: JSON.stringify({category})});
        notice(`Category saved for ${record.description_raw}.`);
      }
      await Promise.all([openTransaction(id), loadTransactions()]);
    } catch (error) { notice(error, true); }
  });
  const evidence = element("ul", "", "finance-list");
  for (const item of record.evidence) {
    const li = document.createElement("li");
    li.append(homeLink(item.relative_path, `#/documents/${item.document_id}`), element("small", item.locator?.rows ? `Row ${item.locator.rows.join(", ")}` : item.locator?.line_ids ? "Statement line" : "", "muted"));
    evidence.append(li);
  }
  for (const link of record.links) {
    const li = document.createElement("li"), other = link.counterpart;
    li.append(element("strong", `${LINK_NAMES[link.kind] || link.kind}${link.review_status === "proposed" ? " (proposed)" : ""}`),
              element("span", describe(other), "block"), element("small", `Why: ${link.match_signals.map(signal => SIGNALS[signal] || signal.replaceAll("_", " ")).join(", ")}`, "muted"));
    if (other?.document_id) li.append(homeLink("Open document", `#/documents/${other.document_id}`));
    evidence.append(li);
  }
  if (!evidence.children.length) evidence.append(element("li", "No linked receipt or source document.", "muted"));
  const history = element("ul", "", "finance-list");
  for (const event of record.review_history) history.append(element("li", `${new Date(event.created_at).toLocaleString()}: ${statusLabel(event.previous_status)} → ${statusLabel(event.new_status)}${event.note ? ` · ${event.note}` : ""}`));
  // Changes the family made here (docs/family.md "Family corrections"): each can be rejected, which puts the value back.
  for (const change of record.family_corrections || []) {
    const li = element("li", `${new Date(change.created_at).toLocaleString()}: ${change.field.replaceAll("_", " ")} changed by ${change.actor.replace(/^Family · /, "family (")}${change.actor.startsWith("Family · ") ? ")" : ""}`
                            + ` from ${change.previous ?? "nothing"} to ${change.value ?? "nothing"}`);
    if (change.status === "applied") li.append(document.createTextNode(" "), asyncButton("Reject", async () => {
      await api(`/api/finance/family-corrections/${change.key}/reject`, {method: "POST", body: "{}"});
      notice(`Put back ${change.previous ?? "the earlier value"}.`); await Promise.all([openTransaction(id), loadTransactions()]);
    }, "small quiet"));
    else li.append(element("small", ` · ${statusLabel(change.status)}`, "muted"));
    history.append(li);
  }
  if (!history.children.length) history.append(element("li", "No decisions yet.", "muted"));
  const details = element("details", "", "technical-detail");
  details.append(element("summary", "Details"), element("p", `Type: ${statusLabel(record.transaction_type)} · Origin: ${record.origin} · Currency: ${record.currency}`, "small"),
                 element("p", `Fingerprint: ${record.source_fingerprint}`, "small mono"));
  // A charge with an itemised receipt counts by its items' categories; the category above then covers none of it unless set by you.
  const sections = [head, state];
  if (record.splits?.length) {
    const split = element("ul", "", "finance-list");
    for (const row of record.splits) {
      const li = document.createElement("li"); li.append(element("span", categoryLabel(row.category)), document.createTextNode(" "), amount(row.display.amount_minor, {signed: false}));
      split.append(li);
    }
    sections.push(drawerSection("Split by the receipt's items", split,
                                element("small", "Change an item's category in the Items view or on the receipt. Saving a category below puts the whole charge in it instead.", "muted block")));
  }
  // Taxes (taxes.js): a write-off, business income or a tax payment made ahead.
  const taxes = taxTagEditor({targets: [{type: "transaction", id, label: record.description_raw, inflow: record.amount_minor > 0,
                                         amount: record.display.amount_minor.replace(/^-/, "")}],
                              tags: taxTag ? [taxTag] : [], words: ruleWords(record), onDone: () => openTransaction(id)});
  body.replaceChildren(...sections, drawerSection("Category", form), drawerSection("Taxes", taxes), drawerSection("Evidence", evidence),
                       drawerSection("History", history), details);
  if (!$("tx-drawer").open) $("tx-drawer").showModal();
}
// The family ledger's drawer: a member's transaction as their latest copy has it, with its evidence opening from the
// family computer.
async function openFamilyTransaction(id, member) {
  const record = await api(recordUrl("transaction", id, member));
  $("tx-drawer-title").textContent = record.merchant || record.description_raw;
  const head = element("div", "", "drawer-head");
  const big = amount(record.display.amount_minor); big.classList.add("drawer-amount");
  head.append(big, element("p", `${record.owner} · ${dateText(record.posted_date)} · ${record.account}`, "muted"));
  if (record.merchant) head.append(element("p", record.description_raw, "muted small"));
  const state = element("div", "", "drawer-status");
  state.append(statusBadge(record.review_status));
  if (record.pending_fields.length) state.append(element("span", ` Waiting for ${record.owner}: ${record.pending_fields.map(field => field.replaceAll("_", " ")).join(", ")}`, "muted small"));
  // A correction travels to the person and applies in their own records (docs/family.md "Family corrections").
  const form = element("form", "", "form family-correction");
  const fields = [["category", "Category", record.category || "", "text"], ["merchant", "Merchant", record.merchant || record.description_raw, "text"],
                  ["posted_date", "Date", record.posted_date, "date"]];
  for (const [field, label, value, type] of fields) {
    const wrap = element("div", "", "field"), name = element("label", label), input = element("input");
    input.id = `family-fix-${field}`; input.type = type; input.value = value; input.maxLength = 120; input.dataset.field = field; input.dataset.original = value;
    if (field === "category") input.setAttribute("list", "category-options");
    name.htmlFor = input.id; wrap.append(name, input);
    if (record.pending_fields.includes(field)) wrap.append(element("small", `Waiting for ${record.owner}`, "muted"));
    form.append(wrap);
  }
  const save = element("button", "Send correction", "small primary"); save.type = "submit";
  form.append(save, element("small", `${record.owner} sees it in their own records, marked as changed by the family, and can reject it.`, "muted block"));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const changes = {};
    for (const input of form.querySelectorAll("input[data-field]")) if (input.value.trim() !== input.dataset.original) changes[input.dataset.field] = input.value.trim() || null;
    if (!Object.keys(changes).length) { notice("Change a field first.", true); return; }
    save.disabled = true;
    try {
      await api(recordUrl("transaction", id, member), {method: "PATCH", body: JSON.stringify({changes})});
      notice(`Sent to ${record.owner}.`);
      await Promise.all([openFamilyTransaction(id, member), loadTransactions()]);
    } catch (error) { notice(error, true); } finally { save.disabled = false; }
  });
  const evidence = element("ul", "", "finance-list");
  for (const item of record.evidence) {
    const li = document.createElement("li");
    li.append(originalButton(document.createTextNode(item.relative_path), member, item.document_id));
    evidence.append(li);
  }
  if (!evidence.children.length) evidence.append(element("li", "No linked receipt or source document.", "muted"));
  const history = element("ul", "", "finance-list");
  for (const event of record.review_history) history.append(element("li", `${new Date(event.created_at).toLocaleString()}: ${statusLabel(event.previous_status)} → ${statusLabel(event.new_status)}${event.note ? ` · ${event.note}` : ""}`));
  if (!history.children.length) history.append(element("li", "No decisions yet.", "muted"));
  $("tx-drawer-body").replaceChildren(head, state, drawerSection("Correct", form), drawerSection("Evidence", evidence), drawerSection("History", history),
    element("p", `${record.owner}'s records stay in their own profile; this is their latest copy.`, "muted small"));
  if (!$("tx-drawer").open) $("tx-drawer").showModal();
}
$("close-tx-drawer").addEventListener("click", () => $("tx-drawer").close());
$("tx-drawer").addEventListener("click", event => { if (event.target === $("tx-drawer")) $("tx-drawer").close(); });

// Shared with Review: record summaries in words.
const RECORD_KINDS = {statement: "Statement", receipt: "Receipt", bill: "Bill", income_record: "Pay stub", transaction: "Transaction"};
const SIGNALS = {amount: "same amount", same_day: "same day", date: "within two days", merchant: "merchant matches", opposite_amount: "opposite amounts",
                 date_window: "within five days", exact_amount: "exact amount", partial_amount: "partial amount", user_choice: "your choice"};
function describe(summary, {named = true} = {}) {
  // "Costco Wholesale · 163.82 USD · Sep 15, 2026 · Fidelity credit card 7314", from a server-side record summary.
  if (!summary) return "Record no longer available";
  return [named && (summary.name || summary.description || RECORD_KINDS[summary.record_type]), summary.amount?.display,
          summary.date && dateText(summary.date), summary.account].filter(Boolean).join(" · ");
}

// Spending & budgets ---------------------------------------------------------------------------------------------

let spendLoad = 0;
function openSpending(params) {
  if (params.get("month")) $("spend-month").value = params.get("month");
  if (!$("spend-month").value) $("spend-month").value = todayIso().slice(0, 7);
  return loadSpending();
}
function meter(row) {
  // Share of the budget used; the fill carries the status and is always paired with its icon and label.
  const track = element("div", "", "meter"); track.dataset.status = row.status;
  const fill = element("div", "", "meter-fill"); fill.style.width = `${row.meter_percent}%`;
  track.append(fill); track.setAttribute("role", "img"); track.setAttribute("aria-label", `${row.percent_used}% of the budget used`);
  return track;
}
function txHref(extra) { return `#/transactions?${new URLSearchParams(extra)}`; }
async function loadSpending() {
  if (!configured) return;
  const load = ++spendLoad, month = $("spend-month").value, period = monthRange(month);
  const compareMonth = $("spend-compare").value === "last_year" ? shiftMonth(month, -12) : shiftMonth(month, -1);
  $("spend-compare-heading").textContent = $("spend-compare").value === "last_year" ? "Same month last year" : "Previous month";
  $("spend-error").replaceChildren();
  let data;
  try {
    // Budgets and rules are each person's own: the family view adds up spending only.
    data = await Promise.all([ledgerTool("get_spending", period), ledgerTool("compare_categories", {first: monthRange(compareMonth), second: period}),
      ledgerTool("get_spending_by_category", period), ledgerTool("get_refunds"),
      familyMode ? {budgets: [], unbudgeted: [], days: 0, elapsed_days: 0} : tool("get_budgets", {month, as_of: todayIso()}),
      familyMode ? [] : api("/api/finance/category-rules"), loadTransactionOptions()]);
  } catch (error) {
    if (load === spendLoad) $("spend-error").replaceChildren(alertBox(`Couldn't load spending. ${error.message}`, {tone: "error", action: asyncButton("Retry", loadSpending)}));
    return;
  }
  if (load !== spendLoad) return;
  const [spending, comparison, breakdown, refunds, budgets, rules] = data;
  // Figures, one row per currency: never summed across currencies.
  const figures = [];
  for (const row of spending.by_currency) {
    const group = element("div", "", "figure-group");
    const main = element("div", "", "figure-main"), net = homeLink("", txHref({start: period.start, end: period.end, currency: row.currency, metric: "spending"}), "figure-value");
    net.append(amount(row.net_spending, {signed: false}));
    main.append(element("span", "Net spending", "figure-label"), net);
    group.append(main);
    // Spent includes receipts no card or bank charge has replaced yet, shown separately so the source is clear.
    const money = value => amount(value, {signed: false});
    for (const [label, value] of [["Spent", money(row.spending)], ["Refunded", money(row.refunds)], ["Transactions", String(row.transactions)],
                                  ...(row.receipts ? [["From receipts only", [money(row.from_receipts), ` · ${row.receipts} ${row.receipts === 1 ? "receipt" : "receipts"}`]]] : [])]) {
      const figure = element("span", "", "figure-small"); figure.append(...[value].flat());
      const item = element("div", "", "figure-item"); item.append(element("span", label, "figure-label"), figure); group.append(item);
    }
    figures.push(group);
  }
  if (!figures.length) figures.push(emptyState("No counted spending in this month."));
  for (const pending of spending.pending_review) figures.push(element("p", `${pending.amount.display} across ${pending.transactions} statement or extracted transactions awaits review or reconciliation and isn't counted.`, "item-warning"));
  $("spend-figures").replaceChildren(...figures);
  $("spend-coverage").textContent = `${spending.excluded_transfers_and_card_payments} transfers and card payments excluded. Covers: ` +
    (spending.coverage.map(item => `${item.display_name} ${item.transactions ? `${dateText(item.first)} – ${dateText(item.last)}` : "(no data this month)"}`).join("; ") || "no accounts yet") + ". " + spending.notes.join(" ");
  // Budgets.
  const budgetOf = new Map(budgets.budgets.map(row => [`${row.currency}|${row.category}`, row]));
  const budgetRows = budgets.budgets.map(row => {
    const item = element("div", "", "budget-row");
    const head = element("div", "", "budget-head");
    head.append(homeLink(row.category, txHref({start: period.start, end: period.end, category: row.category, currency: row.currency})), statusBadge(row.status));
    const text = `${row.spent.display} of ${row.budget.display} · ${row.remaining_state === "over" ? `${row.over.display} over` : `${row.remaining.display} left`} · ${row.percent_used}% used`;
    const actions = element("div", "", "budget-actions");
    actions.append(asyncButton("Change", async () => {
      $("budget-category").value = row.category; $("budget-currency").value = row.currency; $("budget-amount").value = row.budget.decimal; $("budget-amount").focus();
    }, "small quiet"), asyncButton("Remove", async () => {
      if (!await confirmAction({title: "Remove this budget?", message: `The ${row.category} budget of ${row.budget.display} a month will be removed. Transactions are not affected.`, confirmLabel: "Remove budget"})) return;
      await api(`/api/finance/budgets/${row.id}`, {method: "DELETE"}); notice("Budget removed."); await loadSpending();
    }, "small quiet"));
    item.append(head, meter(row), element("p", text, "small"));
    if (row.recurring_due.minor) item.append(element("p", `${row.recurring_due.display} still due from ${row.recurring_payees.join(", ")} · about ${row.projected.display} by month end`, "muted small"));
    item.append(actions);
    return item;
  });
  const pace = budgets.elapsed_days && budgets.elapsed_days < budgets.days ? `Day ${budgets.elapsed_days} of ${budgets.days}. ` : "";
  $("budget-rows").replaceChildren(...(budgetRows.length ? [element("p", `${pace}“Ahead of pace” means a larger share of the budget is spent than of the month.`, "muted small"), ...budgetRows]
    : [emptyState("No budgets yet. Add one below, for example groceries 450.00 a month.")]));
  for (const row of budgets.unbudgeted) $("budget-rows").append(element("p", `${row.spent.display} spent this month in categories without a budget (${row.transactions} transactions).`, "muted small"));
  // By category, with the comparison and budget.
  const categoryRows = comparison.categories.filter(row => row.second.minor || row.first.minor).map(row => {
    const tr = document.createElement("tr");
    cell(tr, "").append(homeLink(row.category, txHref({start: period.start, end: period.end, category: row.category, currency: row.currency, metric: "categories"})));
    for (const value of [row.second.display, row.first.display]) cell(tr, value).className = "numeric";
    cell(tr, `${row.change.display}${row.percent_change === null ? "" : ` (${row.percent_change}%)`}`).className = "numeric";
    const budget = budgetOf.get(`${row.currency}|${row.category}`), budgetCell = cell(tr, "");
    if (budget) budgetCell.append(meter(budget), element("small", `${budget.percent_used}% of ${budget.budget.display}`, "muted block"));
    return tr;
  });
  if (categoryRows.length) $("spend-categories").replaceChildren(...categoryRows); else tableMessage($("spend-categories"), 5, "No category spending in either month.");
  const merchants = breakdown.top_merchants.map(row => { const tr = document.createElement("tr"); cell(tr, row.merchant); cell(tr, row.spending.display).className = "numeric"; cell(tr, row.transactions).className = "numeric"; return tr; });
  if (merchants.length) $("spend-merchants").replaceChildren(...merchants); else tableMessage($("spend-merchants"), 3, "No merchants this month.");
  const inMonth = value => value && value >= period.start && value <= period.end;
  const refundItems = [...refunds.posted_credits.filter(row => inMonth(row.posted_date)).map(row => {
    const li = element("li", `${row.owner ? `${row.owner} · ` : ""}${dateText(row.posted_date)} · ${row.description_raw}`); li.append(amount(row.amount), element("small", row.purchase_id ? "Linked to its purchase" : "Credit posted", "muted block")); return li; }),
    ...refunds.refund_evidence.filter(row => !row.purchase_date || inMonth(row.purchase_date)).map(row => {
      const li = element("li", `${row.owner ? `${row.owner} · ` : ""}${row.merchant || "Return receipt"}${row.purchase_date ? ` · ${dateText(row.purchase_date)}` : ""}`); li.append(amount(row.amount), statusBadge(row.settlement)); return li; })];
  $("spend-refunds").replaceChildren(...(refundItems.length ? refundItems : [element("li", "No refunds this month.", "muted")]));
  // Rules.
  const ruleRows = rules.map(rule => {
    const tr = document.createElement("tr");
    cell(tr, rule.pattern, true); cell(tr, rule.category); cell(tr, rule.account || "Any"); cell(tr, rule.transactions).className = "numeric";
    cell(tr, "").append(asyncButton("Delete", async () => {
      if (!await confirmAction({title: "Delete this rule?", message: `Transactions it categorized as ${rule.category} go to the next matching rule, or back to uncategorized. Categories you set by hand stay.`, confirmLabel: "Delete rule", danger: true})) return;
      const result = await api(`/api/finance/category-rules/${rule.id}`, {method: "DELETE"});
      notice(`Rule deleted; ${result.changed} transaction${result.changed === 1 ? "" : "s"} updated.`); await loadSpending();
    }, "small quiet"));
    return tr;
  });
  if (ruleRows.length) $("rule-rows").replaceChildren(...ruleRows); else tableMessage($("rule-rows"), 5, "No rules yet.");
}
$("spend-month").addEventListener("change", () => { if ($("spend-month").value) loadSpending(); });
$("spend-compare").addEventListener("change", () => loadSpending());
$("budget-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const budget = await api("/api/finance/budgets", {method: "PUT", body: JSON.stringify({category: $("budget-category").value, currency: $("budget-currency").value.trim(), amount: $("budget-amount").value.trim()})});
    notice(`Budget saved: ${budget.category}, ${budget.amount.display} a month.`);
    $("budget-category").value = $("budget-amount").value = "";
    await loadSpending();
  } catch (error) { notice(error, true); }
});
$("rule-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const body = {pattern: $("rule-pattern").value, category: $("rule-category").value};
    if ($("rule-account").value) body.account_id = Number($("rule-account").value);
    const rule = await api("/api/finance/category-rules", {method: "POST", body: JSON.stringify(body)});
    notice(`Rule saved: “${rule.pattern}” → ${rule.category}. ${rule.changed} transaction${rule.changed === 1 ? "" : "s"} updated.`);
    $("rule-pattern").value = $("rule-category").value = "";
    await loadSpending();
  } catch (error) { notice(error, true); }
});

// Bills & recurring -----------------------------------------------------------------------------------------------

async function loadBills() {
  if (!configured) return;
  const [upcoming, recurring] = await Promise.all([ledgerTool("get_upcoming_bills", {as_of: todayIso(), days: 120}), ledgerTool("get_recurring_obligations")]);
  // The server groups each bill (overdue, this_week, later).
  const groups = [["Overdue, no payment found yet", "overdue"], ["Due in the next 7 days", "this_week"], ["Later", "later"]]
    .map(([title, key]) => [title, upcoming.bills.filter(bill => bill.group === key)]);
  const sections = [];
  for (const [title, bills] of groups) {
    if (!bills.length) continue;
    const wrap = element("div", "", "bill-group");
    wrap.append(element("h3", title));
    const list = element("ul", "", "finance-list");
    for (const bill of bills) {
      const li = element("li", "", "bill-row");
      const main = element("div", "", "bill-main");
      main.append(element("strong", bill.owner ? `${bill.provider} · ${bill.owner}` : bill.provider), element("span", ` due ${dateText(bill.due_date)} · ${FREQUENCY_LABELS[bill.frequency] || bill.frequency}`
                                                             + (bill.kind === "subscription" ? " · Subscription" : ""), "muted"));
      li.append(main, amount(bill.amount_due, {signed: false}), statusBadge(bill.payment_state));
      if (bill.last_paid_date) li.append(element("small", `Last paid ${dateText(bill.last_paid_date)}`, "muted block"));
      list.append(li);
    }
    wrap.append(list); sections.push(wrap);
  }
  $("bill-groups").replaceChildren(...(sections.length ? sections : [emptyState("No confirmed recurring payments due soon. Confirm proposed ones below or in Review.")]));
  // Subscriptions: each confirmed one, and what they cost together (the server's totals; the browser does no arithmetic).
  const subscriptions = recurring.obligations.filter(row => row.status === "verified" && row.kind === "subscription");
  const summary = [];
  if (subscriptions.length) {
    const list = element("ul", "", "finance-list");
    for (const row of subscriptions) {
      const li = element("li", "", "bill-row"), main = element("div", "", "bill-main");
      main.append(element("strong", row.owner ? `${row.merchant} · ${row.owner}` : row.merchant), element("span", ` ${FREQUENCY_LABELS[row.frequency] || row.frequency}`, "muted"));
      li.append(main, amount(row.expected_amount, {signed: false})); list.append(li);
    }
    summary.push(list);
    for (const total of recurring.totals.filter(total => total.kind === "subscription")) {
      const line = element("p", "", "subscription-total");
      line.append(element("span", `${total.count} ${total.count === 1 ? "subscription" : "subscriptions"}: about `), amount(total.monthly, {signed: false}),
                  element("span", " a month, "), amount(total.yearly, {signed: false}), element("span", " a year"));
      summary.push(line);
    }
    summary.push(element("p", "Payments that aren't monthly are spread evenly over the year. What If can show your plan with them cancelled.", "muted small"));
  } else summary.push(emptyState("No confirmed subscriptions. Mark a recurring payment as a subscription below."));
  $("subscription-summary").replaceChildren(...summary);
  const decide = (row, status) => api(`/api/finance/recurring/${row.id}/review`, {method: "POST", body: JSON.stringify({status})})
    .then(() => { notice("Saved."); refreshReviewCount(); return loadBills(); });
  const setKind = (row, kind) => api(`/api/finance/recurring/${row.id}/kind`, {method: "POST", body: JSON.stringify({kind})})
    .then(() => { notice(`${row.merchant} now counts as a ${RECURRING_KIND_LABELS[kind].toLowerCase()}.`); return loadBills(); })
    .catch(error => { notice(error, true); return loadBills(); });
  const rows = recurring.obligations.map(row => {
    const tr = document.createElement("tr");
    cell(tr, row.merchant); ownerCell(tr, row); cell(tr, "").append(amount(row.expected_amount, {signed: false})); tr.lastChild.className = "numeric";
    cell(tr, {weekly: "week", monthly: "month", quarterly: "quarter", semiannual: "6 months", annual: "year"}[row.frequency] || row.frequency); cell(tr, row.next_due_date ? dateText(row.next_due_date) : "—");
    if (familyMode) cell(tr, RECURRING_KIND_LABELS[row.kind] || row.kind);  // Decided in the person's own profile.
    else {
      const kind = kindSelect(row.kind, value => setKind(row, value));
      kind.setAttribute("aria-label", `${row.merchant} counts as`); kind.className = "kind-select";
      cell(tr, "").append(kind);
    }
    cell(tr, "").append(statusBadge(row.status));
    const actions = cell(tr, "");
    if (familyMode) return tr;
    if (row.status === "proposed") actions.append(asyncButton("Confirm", () => decide(row, "verified"), "small primary"), asyncButton("Not recurring", () => decide(row, "rejected")));
    // Only a confirmed payment can end, and ending it is asked first: it leaves bills, budgets and the forecast.
    else if (row.status === "verified") actions.append(asyncButton("Ended", async () => {
      if (!await confirmAction({title: `Has ${row.merchant} ended?`, message: `${row.merchant} stops counting as a recurring payment: it leaves upcoming bills, budgets and the forecast. Its past payments stay recorded.`,
                                confirmLabel: "Mark as ended"})) return;
      await decide(row, "ended");
    }, "small quiet"));
    return tr;
  });
  if (rows.length) $("recurring-rows").replaceChildren(...rows); else tableMessage($("recurring-rows"), 7, "No recurring payments detected yet.");
}
$("recurring-scan").addEventListener("click", () => {
  busy.inference = true; controls();  // Unavailable until the scan finishes (app.js controls, from the server's busy flags).
  api("/api/finance/recurring/scan", {method: "POST"})
    .then(() => notice("Looking for recurring bills. Any found wait in Review; Processing shows the progress."))
    .catch(error => { notice(error, true); busy.inference = false; controls(); });
});

// Accounts -----------------------------------------------------------------------------------------------

const ACCOUNT_GROUPS = [["Cash", ["checking", "savings"]], ["Credit cards", ["credit_card"]], ["Investments", ["brokerage"]], ["Loans", ["loan"]], ["Other", ["other"]]];
async function loadAccounts() {
  if (!configured) return;
  const {accounts} = await ledgerTool("get_accounts");
  const groups = [];
  for (const [title, types] of ACCOUNT_GROUPS) {
    const members = accounts.filter(account => types.includes(account.account_type));
    if (!members.length) continue;
    const panel = element("section", "", "panel"); panel.append(element("h2", title));
    const list = element("ul", "", "finance-list account-list");
    for (const account of members) {
      const li = element("li", "", "account-row");
      const name = element("div", "", "account-name");
      name.append(element("strong", account.display_name), element("small", `${account.owner ? `${account.owner} · ` : ""}${account.institution}${account.account_last_four ? ` ··${account.account_last_four}` : ""} · ${account.currency}`, "muted block"));
      const balance = element("div", "", "account-balance");
      if (account.balance) {
        balance.append(element("span", account.balance.meaning === "amount owed" ? "Amount owed" : "Statement balance", "figure-label"), amount(account.balance.display, {signed: false}),
                       element("small", `as of ${dateText(account.balance.as_of)}`, "muted block"));
        if (account.balance.days_old > 35) balance.append(statusBadge("needs_review", "Stale · "));
      } else balance.append(element("small", "No statement balance yet. Balances aren't estimated from partial transaction history.", "muted"));
      const coverage = element("div", "", "account-coverage");
      coverage.append(element("small", account.coverage.transactions ? `${account.coverage.transactions} counted transactions, ${dateText(account.coverage.first)} – ${dateText(account.coverage.last)}` : "No counted transactions yet.", "muted"),
                      homeLink("View transactions", txHref({account: familyMode ? `${account.member_id}:${account.id}` : account.id, period: "all"})));
      li.append(name, balance, coverage); list.append(li);
    }
    panel.append(list); groups.push(panel);
  }
  $("account-groups").replaceChildren(...(groups.length ? groups : [emptyState("No accounts yet. Import a CSV or XLSX export from your bank, or record a statement.")]));
}

// Statement reconciliation prompt ---------------------------------------------------------------------------
// A newly recorded bank or card statement asks before its charges replace the receipts already counted.
// Until the user says yes, its charges are not counted, so no purchase is counted twice.

const STATEMENT_KINDS = {bank: "Bank statement", credit_card: "Credit card statement"};
const declinedStatements = new Set();  // "No" for this visit: the prompt becomes a reminder.
let reconcileResults = [];
function statementName(row) {
  const period = row.period_start ? `${dateText(row.period_start)} – ${dateText(row.period_end)}` : `ending ${dateText(row.period_end)}`;
  return `${row.account || row.institution}, ${period}`;
}
async function reconcileStatement(row) {
  const result = await api(`/api/finance/statements/${row.id}/reconcile`, {method: "POST"});
  declinedStatements.delete(row.id);
  const parts = [`${result.matched_receipts} of ${result.charges} charges matched to your receipts`];
  if (result.questions) parts.push(`${result.questions} ${result.questions === 1 ? "needs" : "need"} you to pick the right charge`);
  reconcileResults = [{row, message: `Reconciled ${STATEMENT_KINDS[row.statement_type].toLowerCase()} (${statementName(row)}): ${parts.join("; ")}. `
                       + "Matched receipts are now counted through their charge; the rest still count on their own.", review: result.questions > 0}];
  refreshReviewCount();
  await loadReconcilePrompt();
  // The page on screen shows totals from before the statement's charges counted.
  if (currentRoute) Promise.resolve().then(() => ROUTES[currentRoute.name].show(currentRoute)).catch(error => notice(error, true));
}
function reconcilePromptBox(row) {
  const kind = STATEMENT_KINDS[row.statement_type];
  const actions = element("div", "", "button-row");
  if (declinedStatements.has(row.id)) {
    actions.append(asyncButton("Reconcile now", () => reconcileStatement(row)));
    return alertBox(`${kind} (${statementName(row)}) is waiting to be reconciled. Its ${row.lines} charges aren't counted until you do.`, {action: actions});
  }
  const question = element("p", "Begin reconciling receipts?", "reconcile-question");
  actions.append(asyncButton("Yes", () => reconcileStatement(row), "primary"),
                 asyncButton("No", async () => { declinedStatements.add(row.id); await loadReconcilePrompt(); }));
  const detail = element("div");
  detail.append(question, element("p", `${row.lines} charges on this statement; ${row.receipts} receipts from the period have no matching charge yet.`, "muted small"), actions);
  return alertBox(`${kind} recorded: ${statementName(row)}.`, {action: detail});
}
async function loadReconcilePrompt() {
  if (!configured) { $("reconcile-prompt").replaceChildren(); return; }
  const waiting = await api("/api/finance/statements/awaiting-reconciliation");
  const results = reconcileResults.map(({message, review}) => {
    const actions = element("div", "", "button-row");
    if (review) actions.append(homeLink("Open Review", "#/review"));
    actions.append(asyncButton("Dismiss", async () => { reconcileResults = []; await loadReconcilePrompt(); }, "small quiet"));
    return alertBox(message, {action: actions});
  });
  $("reconcile-prompt").replaceChildren(...results, ...waiting.map(reconcilePromptBox));
}
