"use strict";
// Finances workspace: every figure comes from deterministic server tools as exact display text.
const tool = (name, args = {}) => api(`/api/finance/tools/${name}`, {method:"POST", body:JSON.stringify(args)});
let financeScope = {}, financeOffset = 0;
async function openFinanceRoute(params) {
  financeScope = {}; financeOffset = 0;
  for (const key of ["start", "end", "currency", "metric", "as_of"]) if (params.get(key)) financeScope[key] = params.get(key);
  if (params.get("categories")) {
    try { const values = JSON.parse(params.get("categories")); if (Array.isArray(values) && values.every(value => typeof value === "string")) financeScope.categories = values; } catch {}
  }
  if (financeScope.start) $("finance-month").value = financeScope.start.slice(0, 7);
  await loadFinance();
  const target = {transactions: "finance-transaction-panel", unmatched: "finance-unmatched", review: "finance-queue", bills: "finance-bills"}[params.get("section")];
  if (target) { $(target).scrollIntoView({block: "start"}); $(target).setAttribute("tabindex", "-1"); $(target).focus({preventScroll: true}); }
}

function monthRange(value) {
  const [year, month] = value.split("-").map(Number);
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return {start: `${value}-01`, end: `${value}-${String(last).padStart(2, "0")}`};
}
function previousMonth(value) {
  const [year, month] = value.split("-").map(Number);
  return month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, "0")}`;
}
function financeList(id, items, render, empty) {
  const target = $(id); target.replaceChildren();
  if (!items.length) target.appendChild(element("li", empty, "muted"));
  for (const item of items) target.appendChild(render(item));
}
// Review items: what it is, the details that identify it, why it needs you, and the decision buttons in one row.
const RECORD_KINDS = {statement: "Statement", receipt: "Receipt", bill: "Bill", income_record: "Pay stub"};
const LINK_KINDS = {receipt: "Receipt matches a charge", transfer: "Transfer between your accounts", refund: "Refund of a purchase"};
const ISSUE_KINDS = {ambiguous_receipt_match: "Which charge is this receipt?", ambiguous_transfer: "Which account received this transfer?",
                     ambiguous_refund: "Which purchase was refunded?"};
const SIGNALS = {amount: "same amount", same_day: "same day", date: "within two days", merchant: "merchant matches", opposite_amount: "opposite amounts",
                 date_window: "within five days", exact_amount: "exact amount", partial_amount: "partial amount", user_choice: "your choice"};
function receiptLink(row) {
  // Opens the receipt matched to this transaction; a proposed match says so until it is confirmed.
  const link = element("a", "", "receipt-link"); link.href = `#/documents/${row.receipt_document_id}`;
  const proposed = row.receipt_link_status === "proposed";
  link.append(icon("paperclip"), element("span", proposed ? "Receipt (proposed)" : "Receipt"));
  link.title = proposed ? "Matched receipt, awaiting your confirmation in Needs review" : "Matched receipt";
  return link;
}
function unmatchedItem(receipt) {
  const item = element("li", "", "review-item");
  item.appendChild(element("strong", receipt.name || "Receipt", "review-title"));
  item.appendChild(element("span", describe(receipt, {named: false}), "review-detail"));
  if (receipt.reason === "several_possible_charges") item.appendChild(element("small", "Several possible charges: choose one in Needs review.", "item-warning"));
  else if (receipt.reason === "no_matching_charge") item.appendChild(element("small", "No matching card or bank charge yet.", "muted"));
  const row = element("div", "", "review-actions");
  const open = element("a", "Open document", "review-open"); open.href = `#/documents/${receipt.document_id}`; row.appendChild(open);
  item.appendChild(row);
  return item;
}
function describe(summary, {named = true} = {}) {
  // "Costco Wholesale · 163.82 USD · Sep 15, 2026 · Fidelity credit card 7314", from a server-side record summary.
  if (!summary) return "Record no longer available";
  return [named && (summary.name || summary.description || RECORD_KINDS[summary.record_type]), summary.amount?.display,
          summary.date && dateText(summary.date), summary.account].filter(Boolean).join(" · ");
}
function decision(label, path, body, primary = false) {
  const button = element("button", label, primary ? "small primary" : "small"); button.type = "button";
  button.addEventListener("click", () => api(path, {method: "POST", body: JSON.stringify(body)})
    .then(() => { notice("Saved."); return loadFinance(); }).catch(error => notice(error, true)));
  return button;
}
function reviewItem(title, details, actions, reasons = [], documentId = null) {
  const item = element("li", "", "review-item");
  item.appendChild(element("strong", title, "review-title"));
  for (const line of details) item.appendChild(element("span", line, "review-detail"));
  for (const reason of reasons) item.appendChild(element("small", reason, "item-warning"));
  const row = element("div", "", "review-actions");
  row.append(...actions);
  if (documentId) { const open = element("a", "Open document", "review-open"); open.href = `#/documents/${documentId}`; row.appendChild(open); }
  item.appendChild(row);
  return item;
}
function renderReviewEntry(item) {
  if (item.entry === "record") {
    const path = `/api/finance/records/${item.record_type}/${item.id}/review`;
    return reviewItem(`${RECORD_KINDS[item.record_type]}: ${item.summary?.name || "name not found"}`, [describe(item.summary, {named: false})],
                      [decision("Count it", path, {status: "verified"}, true), decision("Reject", path, {status: "rejected"})], item.issues, item.summary?.document_id);
  }
  if (item.entry === "link") {
    const path = `/api/finance/links/${item.kind}/${item.id}/review`;
    return reviewItem(LINK_KINDS[item.kind], [describe(item.from), describe(item.to), "Why: " + item.match_signals.map(signal => SIGNALS[signal] || signal.replaceAll("_", " ")).join(", ")],
                      [decision("Confirm", path, {status: "verified"}, true), decision("Not a match", path, {status: "rejected"})], [], item.to?.document_id);
  }
  const path = `/api/finance/issues/${item.id}/resolve`;
  return reviewItem(ISSUE_KINDS[item.issue_type] || item.issue_type.replaceAll("_", " "), [describe(item.record), "Equally likely candidates; choose one or leave it unmatched."],
                    [...item.candidates.map(candidate => decision(`${candidate.description || candidate.name} · ${dateText(candidate.date)}`, path, {transaction_id: candidate.id})),
                     decision("Leave unmatched", path, {transaction_id: null})], [], item.record?.document_id);
}
let financeLoad = 0;
async function loadFinance() {
  if (!configured) return;
  if (!$("finance-month").value) $("finance-month").value = new Date().toISOString().slice(0, 7);
  const load = ++financeLoad;  // A newer month selection supersedes slower in-flight requests.
  const period = financeScope.start && financeScope.end ? {start: financeScope.start, end: financeScope.end} : monthRange($("finance-month").value), before = monthRange(previousMonth($("finance-month").value));
  const transactionScope = {...period, include_pending: !financeScope.metric, limit: 200, offset: financeOffset};
  for (const key of ["currency", "metric", "categories"]) if (financeScope[key]) transactionScope[key] = financeScope[key];
  const inCurrency = row => !financeScope.currency || row.currency === financeScope.currency;
  const [spending, categories, comparison, cashflow, accounts, queue, bills, recurring, refunds, transactions, unmatched] = await Promise.all([
    tool("get_spending", period), tool("get_spending_by_category", period), tool("compare_periods", {first: before, second: period}),
    tool("calculate_cashflow", period), tool("get_accounts"), tool("review_queue"), tool("get_upcoming_bills", {as_of: financeScope.as_of || period.start, days: financeScope.as_of ? 30 : 45}),
    tool("get_recurring_obligations"), tool("get_refunds"), tool("get_transactions", transactionScope),
    tool("get_unmatched_receipts", period)]);
  if (load !== financeLoad) return;
  financeList("finance-spending", spending.by_currency.filter(inCurrency), row => {
    const change = comparison.by_currency.find(item => item.currency === row.currency);
    const flow = cashflow.by_currency.find(item => item.currency === row.currency);
    const li = element("li", `${row.net_spending.display} net spending (${row.spending.display} spent, ${row.refunds.display} refunded, ${row.transactions} transactions)`);
    if (change) li.appendChild(element("small", `Previous month ${change.first.display}; change ${change.change.display}${change.percent_change === null ? "" : ` (${change.percent_change}%)`}.`));
    if (flow) li.appendChild(element("small", `Cash flow: in ${flow.inflow.display}, out ${flow.outflow.display}, net ${flow.net.display}.`));
    return li;
  }, "No counted spending in this month.");
  for (const pending of spending.pending_review.filter(inCurrency)) $("finance-spending").appendChild(element("li", `${pending.amount.display} across ${pending.transactions} extracted transactions awaits your review and is not counted.`, "item-warning"));
  $("finance-coverage").textContent = `${spending.excluded_transfers_and_card_payments} transfers and card payments excluded. Coverage: ` +
    (spending.coverage.map(item => `${item.display_name} ${item.transactions ? `${item.first} to ${item.last}` : "no data this month"}`).join("; ") || "no accounts yet") + ". " + spending.notes.join(" ");
  financeList("finance-categories", categories.categories.filter(inCurrency), row => element("li", `${row.category}: ${row.spending.display} (${row.transactions})`), "No categorized spending.");
  financeList("finance-accounts", accounts.accounts, account => {
    const li = element("li", `${account.display_name} · ${account.currency}`);
    li.appendChild(element("small", account.balance ? `${account.balance.meaning} ${account.balance.display} as of ${account.balance.as_of} (${account.balance.days_old} days old)` : "No statement balance; a current balance is not estimated."));
    li.appendChild(element("small", account.coverage.transactions ? `${account.coverage.transactions} counted transactions, ${account.coverage.first} to ${account.coverage.last}` : "No counted transactions yet."));
    return li;
  }, "No accounts yet. Import a CSV/XLSX export or extract a statement.");
  // "entry" tags the list; links keep their own "kind" (receipt, transfer or refund).
  const queueItems = [...queue.records.map(record => ({entry: "record", ...record})), ...queue.links.map(link => ({entry: "link", ...link})),
                      ...queue.issues.map(issue => ({entry: "issue", ...issue}))];
  financeList("finance-queue", queueItems, renderReviewEntry, "Nothing needs review.");
  financeList("finance-unmatched", unmatched.receipts.filter(inCurrency), unmatchedItem, "No unmatched dated receipts in this period.");
  if (unmatched.undated.filter(inCurrency).length) {
    $("finance-unmatched").appendChild(element("li", "Without a purchase date (add one with Edit details):", "muted small"));
    for (const receipt of unmatched.undated.filter(inCurrency)) $("finance-unmatched").appendChild(unmatchedItem(receipt));
  }
  $("finance-unmatched-note").textContent = (unmatched.by_currency.filter(inCurrency).length ? `${unmatched.by_currency.filter(inCurrency).map(row => `${row.total.display} in ${row.receipts} receipt${row.receipts === 1 ? "" : "s"}`).join("; ")}. ` : "")
    + "Not counted in spending: a receipt counts through the transaction it matches.";
  financeList("finance-bills", bills.bills.filter(inCurrency), bill => element("li", `${bill.provider || "Bill"} due ${bill.due_date}: ${bill.amount_due ? bill.amount_due.display : "amount unresolved"} · ${bill.payment_state.replaceAll("_", " ")}`), "No bills due soon.");
  financeList("finance-recurring", recurring.obligations, row => element("li", `${row.merchant}: ${row.expected_amount.display} ${row.frequency}, next about ${row.next_due_date} (${row.status})`), "No recurring payments detected.");
  financeList("finance-refunds", [...refunds.posted_credits.map(row => `${row.posted_date} ${row.description_raw}: ${row.amount.display}${row.purchase_id ? " · linked to its purchase" : ""}`),
                                  ...refunds.refund_evidence.map(row => `${row.merchant || "Refund receipt"} ${row.purchase_date || ""}: ${row.amount.display} · ${row.settlement.replaceAll("_", " ")}`)],
              text => element("li", text), "No refunds.");
  $("finance-transactions").replaceChildren();
  $("finance-filter-note").replaceChildren(document.createTextNode([`${period.start} – ${period.end}`, financeScope.currency, financeScope.metric,
    financeScope.categories?.join(", ")].filter(Boolean).join(" · ") + ". "), homeLink("Clear filters", "#/finances"));
  $("finance-page-count").textContent = `${transactions.total_matching ? financeOffset + 1 : 0}–${financeOffset + transactions.transactions.length} of ${transactions.total_matching}`;
  $("finance-previous").disabled = !financeOffset;
  $("finance-next").disabled = financeOffset + transactions.transactions.length >= transactions.total_matching;
  for (const row of transactions.transactions) {
    const tr = document.createElement("tr");
    cell(tr, "").appendChild(dateDisplay(row.posted_date)); cell(tr, row.account); cell(tr, row.description_raw); cell(tr, statusLabel(row.transaction_type));
    const value = cell(tr, ""); value.className = "numeric"; value.appendChild(amount(row.amount));
    const evidence = cell(tr, ""); evidence.className = "receipt-cell";
    if (row.receipt_document_id) evidence.appendChild(receiptLink(row));
    // Counted rows need no status; only rows that are not counted say why.
    const review = cell(tr, "");
    if (!row.counted) review.append(statusBadge(row.review_status), element("small", "Not counted", "muted"));
    const category = document.createElement("input"); category.value = row.category || ""; category.placeholder = "Category"; category.setAttribute("aria-label", `Category for ${row.description_raw}`);
    category.addEventListener("change", () => api(`/api/finance/transactions/${row.id}/category`, {method:"PUT", body:JSON.stringify({category: category.value.trim() || null})})
      .then(() => { notice(`Category saved for ${row.description_raw}.`); return loadFinance(); }).catch(error => notice(error, true)));
    const td = document.createElement("td"); td.appendChild(category); tr.appendChild(td);
    $("finance-transactions").appendChild(tr);
  }
}
$("finance-month").addEventListener("change", () => {
  if (!$("finance-month").value) return;
  const next = `#/finances?${new URLSearchParams(monthRange($("finance-month").value))}`;
  if (location.hash === next) { financeScope = {}; financeOffset = 0; loadFinance().catch(error => notice(error, true)); }
  else location.hash = next;
});
for (const [id, delta] of [["finance-previous", -200], ["finance-next", 200]]) $(id).addEventListener("click", () => {
  financeOffset = Math.max(0, financeOffset + delta); loadFinance().catch(error => notice(error, true));
});
$("reconcile").addEventListener("click", () => api("/api/finance/reconcile", {method:"POST", body:"{}"})
  .then(result => { notice(`Reconciliation proposed ${result.receipt_links} receipt links, ${result.transfers} transfers and ${result.refunds} refunds; ${result.open_issues} ambiguous cases need you.`); return loadFinance(); })
  .catch(error => notice(error, true)));
