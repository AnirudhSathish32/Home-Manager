"use strict";
// Money pages (docs/money-review-inventory.md §1): Transactions, Spending & budgets, Bills & recurring, Accounts.
// Every figure comes from a deterministic server tool as exact display text; the browser does no money arithmetic.
const tool = (name, args = {}) => api(`/api/finance/tools/${name}`, {method: "POST", body: JSON.stringify(args)});
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
  categoryCache = (await tool("get_categories")).categories.map(row => row.category);
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
const TX_FIELDS = {q: "tx-search", start: "tx-from", end: "tx-to", account: "tx-account", category: "tx-category", types: "tx-type",
                   status: "tx-status", receipt: "tx-receipt", sort: "tx-sort"};
let txParams = new URLSearchParams(), txLoad = 0;
async function loadTransactionOptions() {
  const [{accounts}, categories] = await Promise.all([tool("get_accounts"), loadCategoryOptions()]);
  for (const [id, label] of [["tx-account", "All accounts"], ["rule-account", "Any account"]]) {
    const chosen = $(id).value;
    $(id).replaceChildren(new Option(label, ""), ...accounts.map(account => new Option(account.display_name, account.id)));
    $(id).value = chosen;
  }
  const chosen = $("tx-category").value;
  $("tx-category").replaceChildren(new Option("All categories", ""), new Option("Uncategorized", "uncategorized"), ...categories.map(name => new Option(name)));
  $("tx-category").value = chosen;
}
async function openTransactions(params) {
  txParams = new URLSearchParams(params);
  if (!txParams.has("start") && !txParams.has("end") && !txParams.has("period")) txParams.set("period", "last_90");
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
  if ($("tx-account").value) args.account_id = Number($("tx-account").value);
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
  const load = ++txLoad, args = transactionQuery();
  let result;
  try { result = await tool("get_transactions", args); }
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
  const described = cell(tr, ""), open = element("button", row.merchant || row.description_raw, "link-button");
  open.type = "button"; open.addEventListener("click", () => openTransaction(row.id));
  described.append(open);
  if (row.merchant && row.merchant !== row.description_raw) described.append(element("small", row.description_raw, "muted block"));
  cell(tr, row.account);
  const category = cell(tr, row.category || "—");
  if (!row.category) category.className = "muted";
  else if (row.category_source === "rule") category.title = "Set by a category rule";
  const evidence = cell(tr, ""); evidence.className = "receipt-cell";
  if (row.receipt_document_id) evidence.appendChild(receiptLink(row));
  const status = cell(tr, "");
  if (!row.counted) status.append(statusBadge(row.review_status));
  if (["transfer", "payment"].includes(row.transaction_type)) status.append(element("small", "Not spending", "muted block"));
  const value = cell(tr, ""); value.className = "numeric"; value.appendChild(amount(row.amount));
  if (["transfer", "payment"].includes(row.transaction_type)) value.classList.add("muted");
  tr.addEventListener("click", event => { if (!event.target.closest("a, button")) openTransaction(row.id); });
  return tr;
}
function receiptLink(row) {
  // Opens the receipt matched to this transaction; a proposed match says so until it is confirmed.
  const link = element("a", "", "receipt-link"); link.href = `#/documents/${row.receipt_document_id}`;
  const proposed = row.receipt_link_status === "proposed";
  link.append(icon("paperclip"), element("span", proposed ? "Receipt (proposed)" : "Receipt", "visually-hidden-narrow"));
  link.title = proposed ? "Matched receipt, awaiting your confirmation in Review" : "Matched receipt";
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
async function openTransaction(id) {
  const record = await api(`/api/finance/records/transaction/${id}`);
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
  if (!history.children.length) history.append(element("li", "No decisions yet.", "muted"));
  const details = element("details", "", "technical-detail");
  details.append(element("summary", "Details"), element("p", `Type: ${statusLabel(record.transaction_type)} · Origin: ${record.origin} · Currency: ${record.currency}`, "small"),
                 element("p", `Fingerprint: ${record.source_fingerprint}`, "small mono"));
  body.replaceChildren(head, state, drawerSection("Category", form), drawerSection("Evidence", evidence), drawerSection("History", history), details);
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
  const fill = element("div", "", "meter-fill"); fill.style.width = `${Math.min(100, Number(row.percent_used))}%`;
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
    data = await Promise.all([tool("get_spending", period), tool("compare_categories", {first: monthRange(compareMonth), second: period}),
      tool("get_spending_by_category", period), tool("get_refunds"), tool("get_budgets", {month, as_of: todayIso()}),
      api("/api/finance/category-rules"), loadTransactionOptions()]);
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
    const main = element("div", "", "figure-main"); main.append(element("span", "Net spending", "figure-label"), homeLink(row.net_spending.display, txHref({start: period.start, end: period.end, currency: row.currency, metric: "spending"}), "figure-value"));
    group.append(main);
    for (const [label, value] of [["Spent", row.spending.display], ["Refunded", row.refunds.display], ["Transactions", String(row.transactions)]]) {
      const item = element("div", "", "figure-item"); item.append(element("span", label, "figure-label"), element("span", value, "figure-small")); group.append(item);
    }
    figures.push(group);
  }
  if (!figures.length) figures.push(emptyState("No counted spending in this month."));
  for (const pending of spending.pending_review) figures.push(element("p", `${pending.amount.display} across ${pending.transactions} extracted transactions awaits review and isn't counted.`, "item-warning"));
  $("spend-figures").replaceChildren(...figures);
  $("spend-coverage").textContent = `${spending.excluded_transfers_and_card_payments} transfers and card payments excluded. Covers: ` +
    (spending.coverage.map(item => `${item.display_name} ${item.transactions ? `${dateText(item.first)} – ${dateText(item.last)}` : "(no data this month)"}`).join("; ") || "no accounts yet") + ". " + spending.notes.join(" ");
  // Budgets.
  const budgetOf = new Map(budgets.budgets.map(row => [`${row.currency}|${row.category}`, row]));
  const budgetRows = budgets.budgets.map(row => {
    const item = element("div", "", "budget-row");
    const head = element("div", "", "budget-head");
    head.append(homeLink(row.category, txHref({start: period.start, end: period.end, category: row.category, currency: row.currency})), statusBadge(row.status));
    const text = `${row.spent.display} of ${row.budget.display} · ${row.remaining.minor < 0 ? `${row.remaining.display.replace("-", "")} over` : `${row.remaining.display} left`} · ${row.percent_used}% used`;
    const actions = element("div", "", "budget-actions");
    actions.append(asyncButton("Change", async () => {
      $("budget-category").value = row.category; $("budget-currency").value = row.currency; $("budget-amount").value = row.budget.decimal; $("budget-amount").focus();
    }, "small quiet"), asyncButton("Remove", async () => {
      if (!await confirmAction({title: "Remove this budget?", message: `The ${row.category} budget of ${row.budget.display} a month will be removed. Transactions are not affected.`, confirmLabel: "Remove budget"})) return;
      await api(`/api/finance/budgets/${row.id}`, {method: "DELETE"}); notice("Budget removed."); await loadSpending();
    }, "small quiet"));
    item.append(head, meter(row), element("p", text, "small"), actions);
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
    const li = element("li", `${dateText(row.posted_date)} · ${row.description_raw}`); li.append(amount(row.amount), element("small", row.purchase_id ? "Linked to its purchase" : "Credit posted", "muted block")); return li; }),
    ...refunds.refund_evidence.filter(row => !row.purchase_date || inMonth(row.purchase_date)).map(row => {
      const li = element("li", `${row.merchant || "Refund receipt"}${row.purchase_date ? ` · ${dateText(row.purchase_date)}` : ""}`); li.append(amount(row.amount), statusBadge(row.settlement)); return li; })];
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
  const today = todayIso(), [year, month, day] = today.split("-").map(Number);
  const earlier = isoDay(new Date(year, month - 1, day - 90)), week = isoDay(new Date(year, month - 1, day + 7));
  const [ahead, recent, recurring] = await Promise.all([tool("get_upcoming_bills", {as_of: today, days: 120}), tool("get_upcoming_bills", {as_of: earlier, days: 90}),
                                                        tool("get_recurring_obligations")]);
  const settled = bill => ["paid", "payment_found"].includes(bill.payment_state);
  const groups = [["Past due, no payment found", ahead.bills.filter(bill => bill.due_date < today && !settled(bill))],
                  ["Due in the next 7 days", ahead.bills.filter(bill => bill.due_date >= today && bill.due_date <= week && !settled(bill))],
                  ["Later", ahead.bills.filter(bill => bill.due_date > week && !settled(bill))],
                  ["Paid", [...recent.bills.filter(bill => bill.due_date < today && settled(bill)), ...ahead.bills.filter(bill => bill.due_date >= today && settled(bill))]]];
  const sections = [];
  for (const [title, bills] of groups) {
    if (!bills.length) continue;
    const wrap = title === "Paid" ? element("details", "", "bill-group") : element("div", "", "bill-group");
    wrap.append(title === "Paid" ? element("summary", `${title} (${bills.length}, last 90 days and ahead)`) : element("h3", title));
    const list = element("ul", "", "finance-list");
    for (const bill of bills) {
      const li = element("li", "", "bill-row");
      const main = element("div", "", "bill-main");
      main.append(homeLink(bill.provider || "Bill", `#/documents/${bill.document_id}`), element("span", ` due ${dateText(bill.due_date)}`, "muted"));
      const value = bill.amount_due ? amount(bill.amount_due, {signed: false}) : element("span", "amount unresolved", "muted");
      const actions = element("div", "", "bill-actions");
      const pay = status => api(`/api/finance/bills/${bill.id}/payment`, {method: "POST", body: JSON.stringify({status})}).then(() => { notice("Payment state saved."); return loadBills(); });
      if (bill.payment_state !== "paid") actions.append(asyncButton("Mark paid", () => pay("paid")));
      if (bill.payment_source === "user") actions.append(asyncButton("Reset", () => pay("unknown"), "small quiet"));
      else if (!settled(bill)) actions.append(asyncButton("Mark unpaid", () => pay("unpaid"), "small quiet"));
      li.append(main, value, statusBadge(bill.payment_state), actions);
      if (bill.payment_source === "matched") li.append(element("small", "A matching payment was found in your transactions.", "muted block"));
      if (bill.review_status !== "verified") li.append(element("small", `Bill details: ${statusLabel(bill.review_status)}`, "muted block"));
      list.append(li);
    }
    wrap.append(list); sections.push(wrap);
  }
  $("bill-groups").replaceChildren(...(sections.length ? sections : [emptyState("No bills yet. Bills appear here after a bill document is recorded.")]));
  const decide = (row, status) => api(`/api/finance/recurring/${row.id}/review`, {method: "POST", body: JSON.stringify({status})})
    .then(() => { notice("Saved."); refreshReviewCount(); return loadBills(); });
  const rows = recurring.obligations.map(row => {
    const tr = document.createElement("tr");
    cell(tr, row.merchant); cell(tr, "").append(amount(row.expected_amount, {signed: false})); tr.lastChild.className = "numeric";
    cell(tr, {weekly: "week", monthly: "month", quarterly: "quarter", annual: "year"}[row.frequency] || row.frequency); cell(tr, row.next_due_date ? dateText(row.next_due_date) : "—");
    cell(tr, "").append(statusBadge(row.status));
    const actions = cell(tr, "");
    if (row.status === "proposed") actions.append(asyncButton("Confirm", () => decide(row, "verified"), "small primary"), asyncButton("Not recurring", () => decide(row, "rejected")));
    else actions.append(asyncButton("Ended", () => decide(row, "ended"), "small quiet"));
    return tr;
  });
  if (rows.length) $("recurring-rows").replaceChildren(...rows); else tableMessage($("recurring-rows"), 6, "No recurring payments detected yet.");
}

// Accounts -----------------------------------------------------------------------------------------------

const ACCOUNT_GROUPS = [["Cash", ["checking", "savings"]], ["Credit cards", ["credit_card"]], ["Investments", ["brokerage"]], ["Loans", ["loan"]], ["Other", ["other"]]];
async function loadAccounts() {
  if (!configured) return;
  const {accounts} = await tool("get_accounts");
  const groups = [];
  for (const [title, types] of ACCOUNT_GROUPS) {
    const members = accounts.filter(account => types.includes(account.account_type));
    if (!members.length) continue;
    const panel = element("section", "", "panel"); panel.append(element("h2", title));
    const list = element("ul", "", "finance-list account-list");
    for (const account of members) {
      const li = element("li", "", "account-row");
      const name = element("div", "", "account-name");
      name.append(element("strong", account.display_name), element("small", `${account.institution}${account.account_last_four ? ` ··${account.account_last_four}` : ""} · ${account.currency}`, "muted block"));
      const balance = element("div", "", "account-balance");
      if (account.balance) {
        balance.append(element("span", account.balance.meaning === "amount owed" ? "Amount owed" : "Statement balance", "figure-label"), amount(account.balance.display, {signed: false}),
                       element("small", `as of ${dateText(account.balance.as_of)}`, "muted block"));
        if (account.balance.days_old > 35) balance.append(statusBadge("needs_review", "Stale · "));
      } else balance.append(element("small", "No statement balance yet. Balances aren't estimated from partial transaction history.", "muted"));
      const coverage = element("div", "", "account-coverage");
      coverage.append(element("small", account.coverage.transactions ? `${account.coverage.transactions} counted transactions, ${dateText(account.coverage.first)} – ${dateText(account.coverage.last)}` : "No counted transactions yet.", "muted"),
                      homeLink("View transactions", txHref({account: account.id, period: "all"})));
      li.append(name, balance, coverage); list.append(li);
    }
    panel.append(list); groups.push(panel);
  }
  $("account-groups").replaceChildren(...(groups.length ? groups : [emptyState("No accounts yet. Import a CSV or XLSX export from your bank, or record a statement.")]));
}
