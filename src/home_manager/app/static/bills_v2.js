"use strict";
// Bills & subscriptions, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/money.md): what confirmed
// payments cost a month and a year, proposed ones to decide, what's coming up beside every recurring payment. Totals
// and expected amounts are the server's traced figures; the route stays #/bills.
const bills2 = {show: "all"};
const BILLS2_EVERY = {weekly: "week", monthly: "month", quarterly: "quarter", semiannual: "6 months", annual: "year"};

V2_SCREENS.bills = {title: "Bills & subscriptions", show: route => loadBillsV2(route.params)};

function loadBillsV2(params) {
  bills2.show = ["bills", "subscriptions"].includes(params?.get?.("show")) ? params.get("show") : "all";
  return pageState($("bills2-state"), renderBillsV2, {loading: "Loading bills …", what: "bills", needsLibrary: !familyMode, content: [$("bills2-body")]});
}
function reloadBills() { refreshReviewCount(); return loadBillsV2(new URLSearchParams(bills2.show === "all" ? {} : {show: bills2.show})); }
async function renderBillsV2() {
  const [upcoming, recurring] = await Promise.all([ledgerTool("get_upcoming_bills", {as_of: todayIso(), days: 120}), ledgerTool("get_recurring_obligations")]);
  const empty = !recurring.obligations.length;
  for (const id of ["bills2-tiles", "bills2-decide", "bills2-main", "bills2-about"]) $(id).hidden = empty;
  if (empty) {
    $("bills2-empty").replaceChildren(emptyState("No recurring payments yet. They're found from receipts, statements and contracts.", familyMode ? null : bills2ScanButton()));
    return;
  }
  $("bills2-empty").replaceChildren();
  bills2Tiles(recurring);
  bills2Decide(recurring);
  bills2Upcoming(upcoming);
  bills2All(recurring);
  bills2About();
}
function bills2Count(n, one, many) { return `${n} ${n === 1 ? one : many}`; }
function bills2ScanButton() {
  const button = element("button", "Look for recurring bills", "secondary"); button.type = "button";
  button.disabled = busy.inference;
  button.addEventListener("click", bills2Scan);
  return button;
}
function bills2Scan() {
  busy.inference = true; controls();  // Unavailable until the scan finishes (app.js controls, from the server's busy flags).
  api("/api/finance/recurring/scan", {method: "POST"})
    .then(() => notice("Looking for recurring bills. Any found wait in To decide; Processing shows the progress."))
    .catch(error => { notice(error, true); busy.inference = false; controls(); });
}

// Tiles: the server's totals, one set per currency, never combined --------------------------------------------------
function bills2Tiles(recurring) {
  const currencies = [...new Set((recurring.totals || []).map(total => total.currency))];
  const sets = currencies.map(currency => {
    const of = kind => recurring.totals.find(total => total.currency === currency && total.kind === kind);
    const suffix = currencies.length > 1 ? ` · ${currency}` : "";
    const tiles = [], bills = of("bill"), subscriptions = of("subscription");
    const tile = (label, fig, sub) => {
      const node = element("div", "", "figure-tile");
      node.append(element("p", label, "figure-label"), figure(fig, {size: "lg", signed: false}));
      const line = element("p", "", "figure-sub"); line.append(...[].concat(sub)); node.append(line);
      return node;
    };
    if (bills) tiles.push(tile(`Bills a month${suffix}`, bills.monthly, bills2Count(bills.count, "bill", "bills")));
    if (subscriptions) {
      tiles.push(tile(`Subscriptions a month${suffix}`, subscriptions.monthly, bills2Count(subscriptions.count, "subscription", "subscriptions")));
      tiles.push(tile(`Subscriptions a year${suffix}`, subscriptions.yearly, familyMode ? "Spread evenly over the year"
        : ["What If can show your plan with them cancelled. ", homeLink("Open What If", "#/whatif")]));
    }
    const row = element("div", "", "bills2-tiles"); row.append(...tiles);
    return fitFigures(row);
  });
  $("bills2-tiles").replaceChildren(...sets);
  $("bills2-tiles").hidden = !sets.length;
}

// To decide ----------------------------------------------------------------------------------------------------------
function bills2Why(row) {
  return {receipt_single_payment: "A receipt was read as a payment for a service billed on a schedule.",
          category_single_payment: `A ${row.category || "bill"} charge: how often it recurs can't be told from one payment.`,
          statement_model: "The local model read this payee's statement charges as an ongoing service billed on a schedule.",
          contract_terms: `Read from the document's payment terms: “${row.evidence || ""}”.`}[row.confidence_source]
    || `Payments of the same amount arrived at a steady ${(FREQUENCY_LABELS[row.frequency] || row.frequency).toLowerCase()} cadence.`;
}
function bills2Review(row, body, message) {
  return api(`/api/finance/recurring/${row.id}/review`, {method: "POST", body: JSON.stringify(body)})
    .then(() => { notice(message); return reloadBills(); });
}
function bills2Decide(recurring) {
  const proposed = familyMode ? [] : recurring.obligations.filter(row => row.status === "proposed");
  $("bills2-decide").hidden = !proposed.length;
  if (!proposed.length) { $("bills2-decide").replaceChildren(); return; }
  const heading = element("h2", "To decide"); heading.id = "bills2-decide-title";
  heading.append(element("span", String(proposed.length), "nav-count attention"));
  const list = element("ul", "", "needs-list");
  list.append(...proposed.map(row => {
    const li = element("li", "", "needs-row attention bills2-decide-row"), text = element("div");
    const meta = element("small", "", "muted");
    meta.append("About ", figure(row.expected_amount, {size: "inline", signed: false}), ` · ${FREQUENCY_LABELS[row.frequency] || row.frequency}`);
    text.append(element("strong", row.merchant), meta, element("small", bills2Why(row), "muted"));
    const actions = element("div", "", "bills2-decide-actions");
    const kind = kindSelect(row.kind, () => {}); kind.className = "kind-select"; kind.setAttribute("aria-label", `${row.merchant} counts as`);
    const confirm = asyncButton("Confirm", () => bills2Review(row, {status: "verified", kind: kind.value},
      `${row.merchant} confirmed as a ${RECURRING_KIND_LABELS[kind.value].toLowerCase()}.`), "primary");
    confirm.setAttribute("aria-label", `Confirm ${row.merchant}`);
    const reject = asyncButton("Not recurring", () => bills2Review(row, {status: "rejected"}, `${row.merchant} won't be suggested again.`), "link-button");
    reject.setAttribute("aria-label", `${row.merchant} is not recurring`);
    const label = element("label", "Counts as ", "inline-field bills2-kind"); label.append(kind);
    actions.append(label, confirm, reject);
    li.append(icon("alert", "icon needs-icon"), text, actions);
    return li;
  }));
  $("bills2-decide").replaceChildren(heading, list);
}

// Coming up ----------------------------------------------------------------------------------------------------------
function bills2Upcoming(upcoming) {
  const heading = element("h2", "Coming up"); heading.id = "bills2-upcoming-title";
  const parts = [heading];
  for (const [key, title] of [["overdue", "Overdue · no payment found"], ["this_week", "Next 7 days"], ["later", "Later"]]) {
    const bills = upcoming.bills.filter(bill => bill.group === key);
    if (!bills.length) continue;
    const kicker = element("h3", "", key === "overdue" ? "bills2-kicker overdue" : "bills2-kicker");
    if (key === "overdue") kicker.append(icon("alert"));
    kicker.append(title);
    const list = element("ul", "", "dated-list");
    list.append(...bills.map(bill => {
      const li = element("li", "", "dated-row bills2-bill"), when = element("span", "", "dated-when"), text = element("div");
      when.append(dateDisplay(bill.due_date));
      const name = element("span", bill.owner ? `${bill.provider} · ${bill.owner}` : bill.provider, "bills2-provider");
      if (bill.kind === "subscription") name.append(element("span", "Subscription", "bills2-tag"));
      const meta = [FREQUENCY_LABELS[bill.frequency] || bill.frequency, bill.last_paid_date ? `last paid ${dateText(bill.last_paid_date)}` : "no payment found yet"];
      text.append(name, element("small", meta.join(" · "), "muted"));
      const money = element("span", "", "dated-amount"); money.append(figure(bill.amount_due, {size: "inline", signed: false}));
      li.append(when, text, money, statusBadge(bill.payment_state));
      return li;
    }));
    parts.push(kicker, list);
  }
  if (parts.length === 1) parts.push(emptyState("Nothing confirmed is due in the next 120 days."));
  $("bills2-upcoming").replaceChildren(...parts);
}

// All recurring payments ---------------------------------------------------------------------------------------------
function bills2SetShow(show, focus = false) {
  bills2.show = show;
  const next = new URLSearchParams(show === "all" ? {} : {show});
  if (currentRoute?.name === "bills") currentRoute.params = next;
  history.replaceState(null, "", `#/bills${[...next].length ? `?${next}` : ""}`);
  return reloadBills().then(() => { if (focus) $(`bills2-show-${show}`)?.focus(); });
}
function bills2All(recurring) {
  const heading = element("h2", "All recurring payments"); heading.id = "bills2-all-title";
  const tabs = element("div", "", "tabs bills2-show"); tabs.id = "bills2-show"; tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Show");
  const order = ["all", "bills", "subscriptions"];
  for (const [key, label] of [["all", "All"], ["bills", "Bills"], ["subscriptions", "Subscriptions"]]) {
    const tab = element("button", label); tab.type = "button"; tab.id = `bills2-show-${key}`; tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", "bills2-all-table"); tab.setAttribute("aria-selected", String(bills2.show === key)); tab.tabIndex = bills2.show === key ? 0 : -1;
    tab.addEventListener("click", () => { if (bills2.show !== key) bills2SetShow(key); });
    tab.addEventListener("keydown", event => {
      const moves = {ArrowLeft: -1, ArrowRight: 1};
      if (!(event.key in moves)) return;
      event.preventDefault();
      bills2SetShow(order[(order.indexOf(bills2.show) + moves[event.key] + order.length) % order.length], true);
    });
    tabs.append(tab);
  }
  const head = element("div", "", "bills2-all-head"); head.append(heading, tabs);
  const kind = {bills: "bill", subscriptions: "subscription"}[bills2.show];
  // Proposed first is To decide's job: here confirmed ones lead, proposed follow without actions.
  const rows = recurring.obligations.filter(row => !kind || row.kind === kind)
    .sort((a, b) => (a.status === "proposed") - (b.status === "proposed"));
  if (!rows.length) {
    $("bills2-all").replaceChildren(head, emptyState(kind === "subscription" ? "No subscriptions. Change a payment's Counts as to Subscription." : "No bills here."));
    return;
  }
  const table = element("table", "", "data-table"); table.id = "bills2-all-table";
  const thead = document.createElement("thead"), headRow = document.createElement("tr");
  for (const [text, className] of [["Merchant", ""], ["Owner", "owner-col"], ["Expected", "numeric"], ["Every", ""], ["Next", ""], ["Counts as", ""], ["Status", ""], ["", ""]]) {
    const th = element("th", "", className); th.scope = "col";
    if (text) th.textContent = text; else th.append(element("span", "Actions", "visually-hidden"));
    headRow.append(th);
  }
  thead.append(headRow);
  const body = document.createElement("tbody");
  body.append(...rows.map(row => {
    const tr = document.createElement("tr");
    if (row.status === "proposed") tr.classList.add("bills2-proposed");
    cell(tr, row.merchant).className = "bills2-merchant";
    if (familyMode) cell(tr, row.owner || "").className = "owner-col";
    const expected = cell(tr, ""); expected.className = "numeric bills2-expected"; expected.append(figure(row.expected_amount, {size: "inline", signed: false}));
    cell(tr, BILLS2_EVERY[row.frequency] || row.frequency).className = "bills2-every";
    cell(tr, row.next_due_date ? dateText(row.next_due_date) : "—").className = "bills2-next";
    const kindCell = cell(tr, ""); kindCell.className = "bills2-kind-cell";
    if (familyMode) kindCell.textContent = RECURRING_KIND_LABELS[row.kind] || row.kind;  // Decided in the person's own profile.
    else {
      const select = kindSelect(row.kind, value => api(`/api/finance/recurring/${row.id}/kind`, {method: "POST", body: JSON.stringify({kind: value})})
        .then(() => { notice(`${row.merchant} now counts as a ${RECURRING_KIND_LABELS[value].toLowerCase()}.`); return reloadBills(); })
        .catch(error => { notice(error, true); return reloadBills(); }));
      select.className = "kind-select"; select.setAttribute("aria-label", `${row.merchant} counts as`);
      kindCell.append(select);
    }
    const status = cell(tr, ""); status.className = "bills2-status"; status.append(statusBadge(row.status));
    const actions = cell(tr, ""); actions.className = "bills2-actions";
    if (!familyMode && row.status === "verified") {
      const end = element("button", "Mark as ended…"); end.type = "button";
      end.addEventListener("click", async () => {
        // Ending is asked first: it leaves bills, budgets and the forecast.
        if (!await confirmAction({title: `Has ${row.merchant} ended?`, message: `${row.merchant} stops counting as a recurring payment: it leaves upcoming bills, budgets and the forecast. Its past payments stay recorded.`,
                                  confirmLabel: "Mark as ended"})) return;
        try { await bills2Review(row, {status: "ended"}, `${row.merchant} has ended.`); } catch (error) { notice(error, true); }
      });
      actions.append(menu(`${row.merchant} actions`, [end]));
    }
    return tr;
  }));
  table.append(thead, body);
  const wrap = element("div", "", "table-wrap"); wrap.append(table);
  $("bills2-all").replaceChildren(head, wrap);
}
function bills2About() {
  $("bills2-about").replaceChildren(element("summary", "What these numbers cover"),
    element("p", "Confirmed recurring payments only. Each matched payment moves a bill to its next due date; “no payment found” only reflects imported transactions. The amount is the average of the last three payments.", "muted small"),
    element("p", "Proposed from a steady cadence of payments, a bill payment, a statement payee the local model reads as a service, or a contract's payment terms. Each is a proposal until you confirm it. Call the ones that matter most bills and the rest subscriptions; both count in your spending and forecast.", "muted small"),
    element("p", "Payments that aren't monthly are spread evenly over the year in the totals.", "muted small"));
}

$("bills2-scan").addEventListener("click", bills2Scan);
