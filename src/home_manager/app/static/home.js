"use strict";
let homeLoad = 0, homeMonths = 6;
// Categorical slots 1–6 of the validated palette (forecast-charts skill); the legend and table view relieve the contrast warning.
const CHART_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];
const categoryColors = new Map();
function localMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
function homeLink(text, href, className = "") {
  // In the family view the records live in each member's profile, so links to them become plain text.
  if (!href || (familyMode && !FAMILY_ROUTES.includes(href.replace(/^#\//, "").split(/[/?]/)[0]))) return element("span", text, className);
  const link = element("a", text, className); link.href = href; return link;
}
function financeHref(data, extra = {}) {
  if (familyMode) return null;
  return `#/transactions?${new URLSearchParams({start: data.period.start, end: data.period.end, currency: data.currency, ...extra})}`;
}
function chartNode(tag, attributes = {}, text = null) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) if (value !== null && value !== undefined) node.setAttribute(name, value);
  if (text !== null) node.textContent = text;
  return node;
}
function homePanel(title, subtitle) {
  const panel = element("section", "", "panel home-card");
  panel.append(element("h2", title));
  if (subtitle) panel.append(element("p", subtitle, "muted small"));
  return panel;
}
function chartDetails(svg) {
  const note = element("p", "Focus or hover over a chart segment for details. Select it to view transactions.", "muted small chart-details");
  for (const link of svg.querySelectorAll("a")) {
    const show = () => { note.textContent = link.querySelector("title").textContent; };
    link.addEventListener("focus", show); link.addEventListener("pointerenter", show);
  }
  return note;
}
function homeTable(headings, rows) {
  const details = document.createElement("details");
  details.append(element("summary", "View data table"));
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
  const head = document.createElement("thead"), tr = document.createElement("tr"), body = document.createElement("tbody");
  for (const text of headings) { const th = element("th", text); th.scope = "col"; tr.append(th); }
  head.append(tr);
  for (const values of rows) {
    const row = document.createElement("tr");
    for (const value of values) { const td = document.createElement("td"); td.append(value instanceof Node ? value : document.createTextNode(value)); row.append(td); }
    body.append(row);
  }
  table.append(head, body); wrap.append(table); details.append(wrap); return details;
}
function homeMetric(label, amount, note, href) {
  const panel = element("section", "", "panel home-metric");
  panel.append(element("h2", label), homeLink(amount?.display || "No recorded data", href, "home-figure"), element("p", note, "muted small"));
  return panel;
}
function homeTrend(data) {
  const panel = homePanel("Spending over time", `Monthly net spending · ${data.currency}. Gaps mean no recorded spending transactions.`);
  const controls = element("div", "", "home-range"); controls.setAttribute("role", "group"); controls.setAttribute("aria-label", "Trend period");
  for (const months of [6, 12]) {
    const button = element("button", `${months} months`); button.type = "button";
    button.setAttribute("aria-pressed", String(months === homeMonths));
    button.addEventListener("click", () => { homeMonths = months; loadHome(); }); controls.append(button);
  }
  panel.append(controls);
  const values = data.series.filter(row => row.totals).map(row => row.totals.net_spending.minor);
  if (!values.length) panel.append(emptyState("No recorded spending yet. Import transactions to build your spending history."));
  else {
    const high = Math.max(0, ...values), low = Math.min(0, ...values), span = high - low || 1;
    const y = value => 28 + (high - value) / span * 185, zero = y(0), step = 560 / data.series.length;
    const svg = chartNode("svg", {viewBox: "0 0 620 260", class: "home-trend", role: "group", "aria-label": `Monthly net spending in ${data.currency}; details available in the data table`});
    svg.append(chartNode("line", {x1: 40, x2: 604, y1: zero, y2: zero, stroke: "#C9CED6"}));
    svg.append(chartNode("text", {x: 6, y: zero + 4, class: "chart-label"}, "0"));
    const highest = data.series.find(row => row.totals?.net_spending.minor === high);
    if (high > 0) svg.append(chartNode("text", {x: 40, y: 16, class: "chart-label"}, highest.totals.net_spending.display));
    const lowest = data.series.find(row => row.totals?.net_spending.minor === low);
    if (low < 0) svg.append(chartNode("text", {x: 40, y: 225, class: "chart-label"}, lowest.totals.net_spending.display));
    data.series.forEach((row, index) => {
      const x = 45 + index * step, value = row.totals?.net_spending.minor;
      const label = `${row.month}${row.partial ? " (partial)" : ""}: ${row.totals?.net_spending.display || "No recorded transactions"}`;
      if (row.totals) {
        const link = chartNode("a", {href: financeHref(data, {start: row.start, end: row.end, metric: "spending"}), "aria-label": label, tabindex: "0"});
        const rect = chartNode("rect", {x, y: Math.min(y(value), zero) - (value === 0 ? 1 : 0), width: step - 12,
          height: Math.max(2, Math.abs(y(value) - zero)), rx: 3, fill: row.partial ? "#dbe8f8" : "#2a78d6", stroke: "#2a78d6", "stroke-width": 2});
        if (row.partial) rect.setAttribute("stroke-dasharray", "4 3");
        link.append(chartNode("title", {}, `${label}; spent ${row.totals.spending.display}; refunds ${row.totals.refunds.display}; ${row.totals.transactions} transactions`), rect);
        svg.append(link);
      } else svg.append(chartNode("text", {x: x + (step - 12) / 2, y: zero - 8, "text-anchor": "middle", class: "chart-label"}, "—"));
      svg.append(chartNode("text", {x: x + (step - 12) / 2, y: 240, "text-anchor": "middle", class: "chart-label"}, new Date(row.month + "-01T12:00:00").toLocaleDateString(undefined, {month: "short"})));
      if (row.partial) svg.append(chartNode("text", {x: x + (step - 12) / 2, y: 253, "text-anchor": "middle", class: "chart-label"}, "partial"));
    });
    panel.append(svg, chartDetails(svg));
    panel.append(element("p", `${data.series[0].month} – ${data.series.at(-1).month}. Outlined bars show a partial month.`, "muted small"));
  }
  panel.append(homeTable(["Month", "Spent", "Refunded", "Net", "Transactions"], data.series.map(row => [
    homeLink(row.month + (row.partial ? " (partial)" : ""), financeHref(data, {start: row.start, end: row.end, metric: "spending"})),
    row.totals?.spending.display || "No data", row.totals?.refunds.display || "—", row.totals?.net_spending.display || "—", String(row.totals?.transactions ?? "—")])));
  return panel;
}
function categoryColor(name) {
  if (name === "uncategorized") return "#6B7480";
  if (categoryColors.has(name)) return categoryColors.get(name);
  let hash = 0; for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  let chosen = CHART_COLORS[hash % CHART_COLORS.length];
  const used = new Set(categoryColors.values());
  for (let i = 0; i < CHART_COLORS.length; i++) {
    const color = CHART_COLORS[(hash + i) % CHART_COLORS.length];
    if (!used.has(color)) { chosen = color; break; }
  }
  categoryColors.set(name, chosen); return chosen;
}
function homeCategories(data) {
  const panel = homePanel("Spending by category", `${data.month} · Before refunds`);
  const href = row => financeHref(data, {metric: "categories", categories: JSON.stringify(row.members)});
  if (data.gross.minor <= 0 || data.categories.some(row => row.spending.minor < 0)) {
    panel.append(emptyState(data.categories.length ? "Category totals include adjustments. See the exact amounts in the table below." : "No category spending recorded for this period."));
  } else {
    const svg = chartNode("svg", {viewBox: "0 0 260 230", class: "home-donut", role: "group", "aria-label": `Category spending before refunds: ${data.gross.display}`});
    let offset = 0;
    for (const row of data.categories) {
      const share = row.spending.minor / data.gross.minor * 100;
      const link = chartNode("a", {href: href(row), tabindex: "0", "aria-label": `${row.category}: ${row.spending.display}, ${row.share}%`});
      link.append(chartNode("title", {}, `${row.category}: ${row.spending.display} (${row.share}%)`),
        chartNode("circle", {cx: 130, cy: 110, r: 78, fill: "none", stroke: categoryColor(row.category), "stroke-width": 27,
          pathLength: 100, "stroke-dasharray": `${share} ${100 - share}`, "stroke-dashoffset": -offset, transform: "rotate(-90 130 110)"}));
      svg.append(link); offset += share;
    }
    svg.append(chartNode("text", {x: 130, y: 104, "text-anchor": "middle", class: "donut-total"}, data.gross.decimal),
      chartNode("text", {x: 130, y: 127, "text-anchor": "middle", class: "chart-label"}, `${data.currency} spent`));
    panel.append(svg, chartDetails(svg));
    const legend = element("ul", "", "home-legend");
    for (const row of data.categories) {
      const item = document.createElement("li"), swatch = chartNode("svg", {viewBox: "0 0 12 12", class: "chart-swatch", "aria-hidden": "true"});
      swatch.append(chartNode("circle", {cx: 6, cy: 6, r: 5, fill: categoryColor(row.category)}));
      const link = homeLink(row.category, href(row));
      item.append(swatch, link, element("span", `${row.spending.display} · ${row.share}%`, "numeric")); legend.append(item);
    }
    panel.append(legend);
  }
  if (data.totals) panel.append(element("p", `${data.totals.refunds.display} refunded; ${data.totals.net_spending.display} net spending.`, "muted small home-footer"));
  panel.append(homeTable(["Category", "Spent", "Share"], data.categories.map(row => [homeLink(row.category, href(row)), row.spending.display, `${row.share}%`])));
  return panel;
}
function renderHome(data) {
  const content = $("home-content"), metrics = element("div", "", "home-metrics");
  const compare = data.comparison;
  const note = compare ? `Previous period ${compare.first.display}; change ${compare.change.display}${compare.percent_change === null ? "" : ` (${compare.percent_change}%)`}. ${data.previous_period.start} – ${data.previous_period.end}.` : "No recorded spending in the comparison period.";
  metrics.append(homeMetric("Net spending", data.totals?.net_spending, note, financeHref(data, {metric: "spending"})),
    homeMetric("Money in", data.cashflow?.inflow, "Counted inflows for this period", financeHref(data, {metric: "inflow"})),
    homeMetric("Net cash flow", data.cashflow?.net, "Inflows less outflows · not an account balance", financeHref(data, {metric: "cashflow"})));
  const charts = element("div", "", "home-charts"); charts.append(homeTrend(data), homeCategories(data));
  const bottom = element("div", "", "home-bottom"), attention = homePanel("Needs attention", data.family
    ? "Added up across the family. Review happens in each person's own profile."
    : "Receipts count on their own until a statement charge replaces them.");
  const list = element("ul", "", "finance-list"), counts = data.attention;
  const rows = [
    [`${counts.unmatched?.receipts || 0} receipts with no matching charge${counts.unmatched ? ` · ${counts.unmatched.total.display}` : ""}`, "#/review", "Selected period · approved ones count on their own"],
    [`${counts.undated} receipts without a purchase date`, "#/review", `${data.currency} · all dates`],
    [`${counts.records} financial records awaiting review`, "#/review", "All dates and currencies"],
    [`${counts.links} proposed matches · ${counts.issues} unresolved questions`, "#/review", "All dates and currencies"],
    [`${counts.ready} documents ready to record`, "#/documents?status=ready_for_ledger", "All dates"]];
  for (const [label, href, note] of rows) { const li = document.createElement("li"); li.append(homeLink(label, href), element("small", note, "muted")); list.append(li); }
  attention.append(list);
  const bills = homePanel("Upcoming bills", `${data.bills.as_of} – ${data.bills.until} · ${data.currency}`);
  for (const [title, items] of [["Overdue", data.bills.overdue], ["Next 30 days", data.bills.upcoming]]) {
    if (!items.length) continue;
    bills.append(element("h3", title));
    const ul = element("ul", "", "finance-list");
    for (const bill of items) {
      const li = document.createElement("li");
      li.append(homeLink(bill.provider, "#/bills"), element("small", `${bill.member ? `${bill.member} · ` : ""}${bill.due_date} · ${bill.amount_due.display} · ${FREQUENCY_LABELS[bill.frequency] || bill.frequency}`));
      ul.append(li);
    }
    bills.append(ul);
  }
  if (!data.bills.total) bills.append(emptyState("No confirmed recurring bills due in the next 30 days."));
  if (data.maturities?.length) {
    // CDs and Treasuries maturing in the next 90 days, or matured and waiting for an answer (Investments).
    bills.append(element("h3", "CDs and Treasuries coming due"));
    const ul = element("ul", "", "finance-list");
    for (const due of data.maturities) {
      const li = document.createElement("li"), when = MATURITY_STATES[due.state === "matured" ? "matured" : due.kind];
      li.append(homeLink(due.name, due.member ? "#/investments" : `#/investments?account=${due.account_id}`),
                element("small", `${due.member ? `${due.member} · ` : ""}${due.account} · ${when} ${due.date} · ${due.amount.display}`));
      ul.append(li);
    }
    bills.append(ul);
    if (data.maturities_total > data.maturities.length) bills.append(homeLink(`All ${data.maturities_total} coming due`, "#/investments"));
  }
  bills.append(homeLink(`${data.family ? "Bills due or overdue across the family" : "View all bills"} (${data.bills.total})`, "#/bills", "home-footer"));
  bottom.append(attention, bills);
  const household = element("div", "", "home-bottom"); household.id = "home-extras";
  const coverage = homePanel("What these numbers cover", `${data.period.start} – ${data.period.end} · ${data.currency}`);
  coverage.append(element("p", data.coverage.map(row => `${row.display_name}: ${row.first} to ${row.last} (${row.transactions} counted transactions)`).join("; ") || "No counted account transactions in this period.", "muted small"));
  if (data.pending) coverage.append(element("p", `${data.pending.amount.display} across ${data.pending.transactions} transactions awaits review or reconciliation and is not counted.`, "item-warning"));
  coverage.append(element("p", "Totals reflect recorded transactions and approved receipts, not all household spending. A receipt counts until a card or bank charge replaces it, never both. Transfers and card payments are excluded from spending. Each currency is shown separately.", "muted small"));
  if (data.family) {
    household.hidden = true;
    content.replaceChildren(...routingNote(data), metrics, familyMembers(data), charts, bottom, familyAdjustments(data.family), coverage);
    renderNetWorth(data.currency).catch(() => {});  // Loads on its own, like the extras on a personal Home.
    return;
  }
  content.replaceChildren(metrics, charts, bottom, household, coverage);
  renderHomeExtras(data.month).catch(() => {});  // Budgets and the check-in load on their own; the dashboard never waits for them.
}
// Family view ------------------------------------------------------------------------
function routingNote(data) {
  // Uploads to the family count for nobody until someone says whose they are.
  if (!data.routing_waiting) return [];
  const count = data.routing_waiting;
  return [alertBox(`${count} document${count === 1 ? "" : "s"} uploaded to the family ${count === 1 ? "is" : "are"} waiting to be sent to a person or shared. ` +
    "They aren't counted anywhere until then.", {tone: "warning", action: homeLink("Choose who they're for", "#/review", "button")})];
}
function familyTable(headings, rows, numeric = []) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
  const head = document.createElement("thead"), tr = document.createElement("tr"), body = document.createElement("tbody");
  headings.forEach((text, index) => { const th = element("th", text, numeric.includes(index) ? "numeric" : ""); th.scope = "col"; tr.append(th); });
  head.append(tr);
  for (const values of rows) {
    const row = document.createElement("tr");
    values.forEach((value, index) => {
      const td = element("td", "", numeric.includes(index) ? "numeric" : "");
      td.append(value instanceof Node ? value : document.createTextNode(value)); row.append(td);
    });
    body.append(row);
  }
  table.append(head, body); wrap.append(table); return wrap;
}
function asOfText(iso) {
  return iso ? `${dateText(iso)} ${new Date(iso).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}` : "No data yet";
}
function familyMembers(data) {
  const panel = homePanel("Each person", `${data.month} · ${data.currency} · the family totals above are these rows added together`);
  panel.id = "family-members";
  panel.append(familyTable(["Person", "Net spending", "Money in", "Net cash flow", "Data as of"], data.members.map(row => [
    row.name, amount(row.totals?.net_spending || "—", {signed: false}), amount(row.cashflow?.inflow || "—", {signed: false}),
    amount(row.cashflow?.net || "—"), asOfText(row.as_of)]), [1, 2, 3]));
  const waiting = data.family.members.filter(member => member.status !== "current");
  if (waiting.length) panel.append(element("p", `Not included yet: ${waiting.map(member => `${member.name} (${statusLabel(member.status).toLowerCase()})`).join(", ")}.`, "item-warning"));
  return panel;
}
function familyAdjustments(family) {
  const panel = homePanel("Counted once", "Money two people both recorded is not added twice.");
  const joint = family.adjustments?.joint_accounts || [], transfers = family.adjustments?.transfers || [];
  const list = element("ul", "", "finance-list");
  for (const account of joint) {
    const li = document.createElement("li");
    li.append(element("span", `${account.account} (…${account.last_four}) is shared`),
      element("small", `Counted for ${account.counted_for}; also recorded by ${account.also_recorded_by.join(", ")}.`, "muted"));
    list.append(li);
  }
  for (const pair of transfers) {
    const li = document.createElement("li");
    li.append(element("span", `${pair.from} → ${pair.to}`), element("small", `${dateText(pair.date)} · ${pair.amount.display} · a transfer within the family, not spending or income`, "muted"));
    list.append(li);
  }
  const more = (family.adjustments?.transfer_count || 0) - transfers.length;
  if (more > 0) list.append(element("li", `${more} more transfers within the family.`, "muted small"));
  panel.append(joint.length || transfers.length ? list : emptyState("No shared accounts or transfers between family members were found."));
  return panel;
}
async function renderNetWorth(currency) {
  const target = $("family-members");
  if (!target) return;
  const worth = await api(`/api/family/net-worth?${new URLSearchParams({currency})}`);
  if (!worth || !$("family-members")) return;
  const panel = homePanel("Net worth today", `${worth.currency} · statement balances plus verified assets, less loans`);
  panel.id = "family-net-worth";
  const figure = element("p", "", "home-figure");
  figure.append(amount(worth.total.net_worth, {signed: false}));
  panel.append(figure, familyTable(["Person", "Cash", "Assets", "Loans", "Net worth"], [...worth.members.map(row => [
    row.name, amount(row.cash, {signed: false}), amount(row.assets, {signed: false}), amount(row.loans, {signed: false}), amount(row.net_worth, {signed: false})]),
    ["Family", amount(worth.total.cash, {signed: false}), amount(worth.total.assets, {signed: false}), amount(worth.total.loans, {signed: false}),
     amount(worth.total.net_worth, {signed: false})]], [1, 2, 3, 4]));
  panel.append(element("p", worth.notes.join(" "), "muted small"));
  $("family-members").after(panel);
}
async function renderHomeExtras(month = $("home-month").value) {
  const target = $("home-extras");
  if (!target) return;
  const [budgets, checkin, returns, warranties] = await Promise.all([tool("get_budgets", {month, as_of: todayIso()}), api("/api/inventory/checkin"),
    api("/api/inventory/returns"), api("/api/warranties/expiring")]);
  const cards = [];
  if (warranties.length) {
    const card = homePanel("Warranties ending soon", "Within the next 60 days");
    const list = element("ul", "", "finance-list");
    for (const warranty of warranties.slice(0, 6)) {
      const li = document.createElement("li");
      li.append(homeLink([warranty.brand, warranty.name].filter(Boolean).join(" "), `#/inventory?${new URLSearchParams({q: warranty.name})}`),
                element("small", `${statusLabel(warranty.kind)} warranty ends ${dateText(warranty.expires_on)}`, "muted"));
      list.append(li);
    }
    card.append(list); cards.push(card);
  }
  if (returns.length) {
    const card = homePanel("Return windows closing", "Unopened items you can still return in the next two weeks");
    const list = element("ul", "", "finance-list");
    for (const lot of returns.slice(0, 6)) {
      const li = document.createElement("li");
      li.append(homeLink(productName(lot), `#/inventory?${new URLSearchParams({q: lot.name})}`), element("small", `Return by ${dateText(lot.return_by)}${lot.merchant ? ` · ${lot.merchant}` : ""}`, "muted"));
      list.append(li);
    }
    card.append(list, homeLink("Inventory", "#/inventory", "home-footer")); cards.push(card);
  }
  if (budgets.budgets.length) {
    const card = homePanel("Budgets", `${month}${budgets.elapsed_days && budgets.elapsed_days < budgets.days ? ` · day ${budgets.elapsed_days} of ${budgets.days}` : ""}`);
    const list = element("ul", "", "finance-list");
    for (const row of budgets.budgets) {
      const li = element("li", "", "budget-row");
      const head = element("div", "", "budget-head"); head.append(homeLink(row.category, "#/spending"), statusBadge(row.status));
      li.append(head, meter(row), element("small", `${row.spent.display} of ${row.budget.display}`, "muted")); list.append(li);
    }
    card.append(list, homeLink("Spending & budgets", "#/spending", "home-footer")); cards.push(card);
  }
  if (checkin.lots.length) {
    const card = homePanel("Weekly check-in"), body = element("div");
    renderCheckin(body, checkin, {compact: true}); card.append(body); cards.push(card);
  }
  target.replaceChildren(...cards);
  target.hidden = !cards.length;
}
async function loadHome() {
  const load = ++homeLoad;
  $("home-month").max = localMonth();
  if (!$("home-month").value) $("home-month").value = localMonth();
  $("home-subtitle").textContent = familyMode ? "Your family, added up. Each person's records stay in their own profile." : "Your household, at a glance.";
  if (!configured && !familyMode) {
    $("home-content").replaceChildren(emptyState("Set up your library to see spending, receipts and bills.", homeLink("Set up your library", "#/settings", "button primary")));
    $("home-status").textContent = ""; return;
  }
  $("home-error").replaceChildren();
  $("home-status").textContent = "Loading your household overview…";
  $("home-content").replaceChildren(element("div", "Loading totals and charts…", "panel home-loading"));
  $("home-content").setAttribute("aria-busy", "true");
  try {
    const query = new URLSearchParams({month: $("home-month").value, months: homeMonths});
    if ($("home-currency-select").value) query.set("currency", $("home-currency-select").value);
    const data = await api(`/api/dashboard?${query}`);
    if (load !== homeLoad) return;
    if (data.family_empty) {
      $("home-content").replaceChildren(...routingNote(data), emptyState(busy.capture ? "Updating the family view…"
        : "No family member's data has arrived yet. Members appear here once their profile is set up on this computer or they share from their own.",
        homeLink("Manage family members", "#/settings", "button")));
      $("home-status").textContent = ""; return;
    }
    $("home-currency-select").replaceChildren(...data.currencies.map(code => new Option(code, code)));
    $("home-currency-select").value = data.currency;
    renderHome(data);
    $("home-status").textContent = `${data.period.start} – ${data.period.end} · Updated ${new Date(data.loaded_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}`;
  } catch (error) {
    if (load !== homeLoad) return;
    $("home-content").replaceChildren();
    const retry = element("button", "Retry"); retry.type = "button"; retry.addEventListener("click", loadHome);
    $("home-error").replaceChildren(alertBox(`Could not load your dashboard. ${error.message}`, {tone: "error", action: retry}));
    $("home-status").textContent = "";
  } finally { if (load === homeLoad) $("home-content").removeAttribute("aria-busy"); }
}
for (const id of ["home-month", "home-currency-select"]) $(id).addEventListener("change", loadHome);
$("home-refresh").addEventListener("click", loadHome);
