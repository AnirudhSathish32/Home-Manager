"use strict";
// Today's chart and family builders (today_v2.js draws the page), and homeLink, which every page uses.
let homeMonths = 6;
// Categorical slots 1–6 of the validated chart palette, colored by the --chart-cat-* tokens (docs/ui.md "Conventions").
const CHART_SLOTS = ["cat-1", "cat-2", "cat-3", "cat-4", "cat-5", "cat-6"];
const categorySlots = new Map();
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
// A chart's numbers as a table, folded under it.
function homeTable(headings, rows) {
  const details = document.createElement("details");
  details.append(element("summary", "View data table"), dataTable(headings.map(text => [text]), rows));
  return details;
}
// reload: what the 6/12 buttons run after setting homeMonths (Today's reloadToday).
function homeTrend(data, reload) {
  const panel = homePanel("Spending over time", `Monthly net spending · ${data.currency}. Gaps mean no recorded spending transactions.`);
  const controls = element("div", "", "home-range"); controls.setAttribute("role", "group"); controls.setAttribute("aria-label", "Trend period");
  for (const months of [6, 12]) {
    const button = element("button", `${months} months`); button.type = "button";
    button.setAttribute("aria-pressed", String(months === homeMonths));
    button.addEventListener("click", () => { homeMonths = months; reload(); }); controls.append(button);
  }
  panel.append(controls);
  const values = data.series.filter(row => row.totals).map(row => row.totals.net_spending.minor);
  if (!values.length) panel.append(emptyState("No recorded spending yet. Import transactions to build your spending history."));
  else {
    const high = Math.max(0, ...values), low = Math.min(0, ...values), span = high - low || 1;
    const y = value => 28 + (high - value) / span * 185, zero = y(0), step = 560 / data.series.length;
    const svg = chartNode("svg", {viewBox: "0 0 620 260", class: "home-trend", role: "group", "aria-label": `Monthly net spending in ${data.currency}; details available in the data table`});
    svg.append(chartNode("line", {x1: 40, x2: 604, y1: zero, y2: zero, class: "chart-axis"}));
    svg.append(chartNode("text", {x: 6, y: zero + 4, class: "chart-label"}, "0"));
    const highest = data.series.find(row => row.totals?.net_spending.minor === high);
    if (high > 0) svg.append(chartNode("text", {x: 40, y: 16, class: "chart-label"}, highest.totals.net_spending.display));
    const lowest = data.series.find(row => row.totals?.net_spending.minor === low);
    if (low < 0) svg.append(chartNode("text", {x: 40, y: 225, class: "chart-label"}, lowest.totals.net_spending.display));
    data.series.forEach((row, index) => {
      const x = 45 + index * step, value = row.totals?.net_spending.minor;
      const label = `${monthText(row.month)}${row.partial ? " (partial)" : ""}: ${row.totals?.net_spending.display || "No recorded transactions"}`;
      if (row.totals) {
        const link = chartNode("a", {href: financeHref(data, {start: row.start, end: row.end, metric: "spending"}), "aria-label": label, tabindex: "0"});
        const rect = chartNode("rect", {x, y: Math.min(y(value), zero) - (value === 0 ? 1 : 0), width: step - 12,
          height: Math.max(2, Math.abs(y(value) - zero)), rx: 3, class: row.partial ? "chart-bar partial" : "chart-bar", "stroke-width": 2});
        if (row.partial) rect.setAttribute("stroke-dasharray", "4 3");
        link.append(chartNode("title", {}, `${label}; spent ${row.totals.spending.display}; refunds ${row.totals.refunds.display}; ${row.totals.transactions} transactions`), rect);
        svg.append(link);
      } else svg.append(chartNode("text", {x: x + (step - 12) / 2, y: zero - 8, "text-anchor": "middle", class: "chart-label"}, "—"));
      svg.append(chartNode("text", {x: x + (step - 12) / 2, y: 240, "text-anchor": "middle", class: "chart-label"}, new Date(row.month + "-01T12:00:00").toLocaleDateString(undefined, {month: "short"})));
      if (row.partial) svg.append(chartNode("text", {x: x + (step - 12) / 2, y: 253, "text-anchor": "middle", class: "chart-label"}, "partial"));
    });
    panel.append(svg, chartDetails(svg));
    panel.append(element("p", `${monthText(data.series[0].month)} – ${monthText(data.series.at(-1).month)}. Outlined bars show a partial month.`, "muted small"));
  }
  const money = value => value ? amount(value, {signed: false}) : "—";
  panel.append(homeTable(["Month", "Spent", "Refunded", "Net", "Transactions"], data.series.map(row => [
    homeLink(monthText(row.month) + (row.partial ? " (partial)" : ""), financeHref(data, {start: row.start, end: row.end, metric: "spending"})),
    row.totals ? money(row.totals.spending) : "No data", money(row.totals?.refunds), money(row.totals?.net_spending), String(row.totals?.transactions ?? "—")])));
  return panel;
}
// A category's chart slot (cat-1..6); the colors are the --chart-cat-* tokens in style.css.
function categorySlot(name) {
  if (name === "uncategorized") return "cat-none";
  if (categorySlots.has(name)) return categorySlots.get(name);
  let hash = 0; for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  let chosen = CHART_SLOTS[hash % CHART_SLOTS.length];
  const used = new Set(categorySlots.values());
  for (let i = 0; i < CHART_SLOTS.length; i++) {
    const slot = CHART_SLOTS[(hash + i) % CHART_SLOTS.length];
    if (!used.has(slot)) { chosen = slot; break; }
  }
  categorySlots.set(name, chosen); return chosen;
}
function homeCategories(data) {
  const panel = homePanel("Spending by category", `${monthText(data.month)} · After refunds`);
  const href = row => financeHref(data, {metric: "categories", categories: JSON.stringify(row.members)});
  if (!data.categories_chartable) {
    panel.append(emptyState(data.categories.length ? "Category totals include adjustments. See the exact amounts in the table below." : "No category spending recorded for this period."));
  } else {
    const svg = chartNode("svg", {viewBox: "0 0 260 230", class: "home-donut", role: "group", "aria-label": `Category spending after refunds: ${data.gross.display}`});
    let offset = 0;
    for (const row of data.categories) {
      const share = row.share_bp;  // The server's share (basis points summing to 10,000) is the slice's length.
      const link = chartNode("a", {href: href(row), tabindex: "0", "aria-label": `${row.category}: ${row.spending.display}, ${row.share}%`});
      link.append(chartNode("title", {}, `${row.category}: ${row.spending.display} (${row.share}%)`),
        chartNode("circle", {cx: 130, cy: 110, r: 78, fill: "none", class: categorySlot(row.category), "stroke-width": 27,
          pathLength: 10000, "stroke-dasharray": `${share} ${10000 - share}`, "stroke-dashoffset": -offset, transform: "rotate(-90 130 110)"}));
      svg.append(link); offset += share;
    }
    svg.append(chartNode("text", {x: 130, y: 104, "text-anchor": "middle", class: "donut-total"}, data.gross.decimal),
      chartNode("text", {x: 130, y: 127, "text-anchor": "middle", class: "chart-label"}, `${data.currency} spent`));
    panel.append(svg, chartDetails(svg));
    const legend = element("ul", "", "home-legend");
    for (const row of data.categories) {
      const item = document.createElement("li"), swatch = chartNode("svg", {viewBox: "0 0 12 12", class: "chart-swatch", "aria-hidden": "true"});
      swatch.append(chartNode("circle", {cx: 6, cy: 6, r: 5, class: categorySlot(row.category)}));
      const link = homeLink(row.category, href(row));
      item.append(swatch, link, element("span", `${row.spending.display} · ${row.share}%`, "numeric")); legend.append(item);
    }
    panel.append(legend);
  }
  if (data.totals) panel.append(element("p", `${data.totals.refunds.display} refunded; ${data.totals.net_spending.display} net spending.`, "muted small home-footer"));
  panel.append(homeTable(["Category", "Spent", "Share"], data.categories.map(row => [homeLink(row.category, href(row)), amount(row.spending, {signed: false}), `${row.share}%`])));
  return panel;
}
// Family view ------------------------------------------------------------------------
// numeric: the indexes of the columns that hold amounts.
function familyTable(headings, rows, numeric = []) {
  return dataTable(headings.map((text, index) => [text, numeric.includes(index) ? "numeric" : ""]), rows);
}
function asOfText(iso) {
  return iso ? `${dateText(iso)} ${new Date(iso).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}` : "No data yet";
}
function familyMembers(data) {
  const panel = homePanel("Each person", `${monthText(data.month)} · ${data.currency} · the family totals above are these rows added together`);
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
  const more = family.adjustments?.transfers_not_listed || 0;
  if (more) list.append(element("li", `${more} more transfers within the family.`, "muted small"));
  panel.append(joint.length || transfers.length ? list : emptyState("No shared accounts or transfers between family members were found."));
  return panel;
}
// The family's net worth today, each person's row and the family's (Today).
function familyWorthPanel(worth) {
  const panel = homePanel("Net worth today", `${worth.currency} · statement balances plus verified assets, less loans`);
  const figure = element("p", "", "home-figure");
  figure.append(amount(worth.total.net_worth, {signed: false}));
  panel.append(figure, familyTable(["Person", "Cash", "Assets", "Loans", "Net worth"], [...worth.members.map(row => [
    row.name, amount(row.cash, {signed: false}), amount(row.assets, {signed: false}), amount(row.loans, {signed: false}), amount(row.net_worth, {signed: false})]),
    ["Family", amount(worth.total.cash, {signed: false}), amount(worth.total.assets, {signed: false}), amount(worth.total.loans, {signed: false}),
     amount(worth.total.net_worth, {signed: false})]], [1, 2, 3, 4]));
  panel.append(element("p", worth.notes.join(" "), "muted small"));
  return panel;
}
