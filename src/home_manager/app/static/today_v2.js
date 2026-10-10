"use strict";
// Today, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/today.md): four figure tiles, then what needs
// the user beside this month's budgets, the dated sections, the charts (home.js) and what the numbers cover. Every amount
// and date is the server's; the route stays #/home.
const today = {month: null, currency: null, months: 6};

V2_SCREENS.home = {title: "Today", show: route => loadTodayV2(route.params)};

function loadTodayV2(params) {
  const month = params?.get?.("month") || "", months = Number(params?.get?.("months"));
  today.month = /^\d{4}-\d{2}$/.test(month) && month <= localMonth() ? month : localMonth();
  today.currency = /^[A-Z]{3}$/.test(params?.get?.("currency") || "") ? params.get("currency") : null;
  today.months = months === 12 ? 12 : 6;
  homeMonths = today.months;
  $("today-month").max = localMonth();
  $("today-month").value = today.month;
  $("today-subtitle").textContent = familyMode ? "Your family, added up. Each person's records stay in their own profile." : "Your household this month.";
  return pageState($("today-state"), renderTodayV2, {loading: "Loading today …", what: "your household", needsLibrary: !familyMode, content: [$("today-body")]});
}
// The controls' values into the URL (Layout rule 5), then load again.
function reloadToday() {
  today.month = $("today-month").value || localMonth();
  today.months = homeMonths;
  const next = new URLSearchParams();
  if (today.month !== localMonth()) next.set("month", today.month);
  if (today.currency) next.set("currency", today.currency);
  if (today.months === 12) next.set("months", "12");
  if (currentRoute?.name === "home") currentRoute.params = next;
  history.replaceState(null, "", `#/home${[...next].length ? `?${next}` : ""}`);
  return loadTodayV2(next);
}
async function renderTodayV2() {
  const query = new URLSearchParams({month: today.month, months: today.months});
  if (today.currency) query.set("currency", today.currency);
  const data = await api(`/api/dashboard?${query}`);
  const worthQuery = new URLSearchParams(data.family_empty ? {} : {currency: data.currency});
  const [worth, budgets, checkin, returns, warranties] = familyMode
    ? [data.family_empty ? null : await api(`/api/family/net-worth?${worthQuery}`), null, null, [], []]
    : await Promise.all([null, tool("get_budgets", {month: today.month, as_of: todayIso()}), api("/api/inventory/checkin"),
      api("/api/inventory/returns"), api("/api/warranties/expiring")]);
  const empty = Boolean(data.family_empty);
  for (const id of ["today-tiles", "today-dated", "today-budgets", "today-charts", "today-family", "today-about"]) $(id).hidden = empty;
  $("today-main").classList.toggle("no-aside", familyMode || empty);
  if (empty) {
    $("today-status").textContent = "";
    todayNeeds(data, null, emptyState(busy.capture ? "Updating the family view…"
      : "No family member's data has arrived yet. Members appear here once their profile is set up on this computer or they share from their own.",
      homeLink("Manage family members", "#/settings", "button")));
    return;
  }
  $("today-currency").replaceChildren(...data.currencies.map(code => new Option(code, code)));
  $("today-currency").value = data.currency;
  todayTiles(data, familyMode ? worth : data.worth);
  todayNeeds(data, checkin);
  todayDated(data, {checkin, returns, warranties});
  if (!familyMode) todayBudgets(budgets, today.month, data.currency);
  else $("today-budgets").replaceChildren();
  const charts = element("div", "", "home-charts"); charts.append(homeTrend(data, reloadToday), homeCategories(data));
  $("today-charts").replaceChildren(charts);
  todayFamily(data, worth);
  todayAbout(data);
  $("today-status").textContent = `${dateText(data.period.start)} – ${dateText(data.period.end)} · Updated ${new Date(data.loaded_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}`;
}

// Tiles ------------------------------------------------------------------------------------------------------------
function todayTile(label, fig, options, sub) {
  const tile = element("div", "", "figure-tile");
  tile.append(element("p", label, "figure-label"), fig ? figure(fig, {size: "lg", ...options}) : element("p", "No recorded data", "muted"));
  for (const line of sub) { const p = element("p", "", "figure-sub"); p.append(...[].concat(line)); tile.append(p); }
  return tile;
}
function todayTiles(data, worth) {
  // worth: the dashboard's (personal: cash and net_worth figures) or the family net worth (total.cash, total.net_worth).
  const cash = worth?.cash || worth?.total?.cash, netWorth = worth?.net_worth || worth?.total?.net_worth, dates = worth?.dates;
  const cashSub = [];
  if (dates?.first) {
    cashSub.push(`As of ${dateText(dates.first)}${dates.last !== dates.first ? ` – ${dateText(dates.last)}` : ""}`);
    if (dates.stale.length) cashSub.push(statusBadge("stale", "", "Some balances are old"));
  } else cashSub.push(["No statement balances yet · ", homeLink("Accounts", "#/accounts")]);
  const month = MONTH_NAMES[Number(data.month.slice(5)) - 1];
  const before = data.comparison
    ? `${dateText(data.previous_period.start)} – ${dateText(data.previous_period.end)}: ${data.comparison.first.display}` : "Nothing recorded the month before";
  const net = data.cashflow?.net ? ["Net cash flow ", figure(data.cashflow.net, {size: "inline"})] : "Net cash flow: no recorded data";
  $("today-tiles").replaceChildren(
    todayTile("Cash", cash, {}, cashSub),
    todayTile("Net worth", netWorth, {}, ["Cash + assets − loans"]),
    todayTile(`Spent in ${month}`, data.totals?.net_spending, {magnitude: true}, [before]),
    todayTile("Money in", data.cashflow?.inflow, {}, [net]));
}

// Needs you ------------------------------------------------------------------------------------------------------
function plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }
function needsRow(iconName, what, why, action, href, attention) {
  const li = element("li", "", attention ? "needs-row attention" : "needs-row");
  const text = element("div"); text.append(element("strong", what));
  if (why) text.append(element("small", why, "muted"));
  li.append(icon(iconName, "icon needs-icon"), text);
  if (action) li.append(homeLink(action, href, "needs-action"));
  return li;
}
function todayNeeds(data, checkin, extra = null) {
  const counts = data.attention || {}, family = "Added up across the family. Review happens in each person's own profile.";
  const why = text => familyMode ? family : text;
  const rows = [];
  if (data.routing_waiting) rows.push(needsRow("users", `${plural(data.routing_waiting, "document", "documents")} waiting for a person`,
    "They count for nobody until you say whose they are.", "Choose who", "#/review", true));
  if (counts.tax) rows.push(needsRow("receipt-tax", `Taxes: ${counts.tax.status_text}`,
    counts.tax.trigger ? `What changed: ${counts.tax.trigger}` : `${counts.tax.year} return`, "Open Taxes", "#/taxes", true));
  if (counts.records) rows.push(needsRow("list-checks", `${plural(counts.records, "record", "records")} to check`,
    why("Read from your documents, waiting for you"), "Review", "#/review", true));
  if (counts.links || counts.issues) {
    const parts = [counts.links ? plural(counts.links, "proposed match", "proposed matches") : "", counts.issues ? plural(counts.issues, "open question", "open questions") : ""];
    rows.push(needsRow("list-checks", parts.filter(Boolean).join(" · "), why(""), "Review", "#/review", true));
  }
  if (counts.unmatched?.receipts) rows.push(needsRow("receipt-tax",
    `${plural(counts.unmatched.receipts, "receipt", "receipts")} with no matching charge · ${counts.unmatched.total.display}`,
    why("They count on their own until a card or bank charge replaces them."), "Review", "#/review", false));
  if (counts.undated) rows.push(needsRow("calendar", `${plural(counts.undated, "receipt", "receipts")} without a purchase date`, why(""), "Review", "#/review", false));
  if (counts.ready) rows.push(needsRow("file", `${plural(counts.ready, "document", "documents")} ready to record`, why(""), "Open",
    "#/documents?status=ready_for_ledger", false));
  const waiting = rows.filter(row => row.classList.contains("attention")).length;
  const heading = element("h2", "Needs you"); heading.id = "today-needs-title";
  if (waiting) heading.append(element("span", String(waiting), "nav-count attention"));
  const list = element("ul", "", "needs-list");
  if (rows.length) list.append(...rows);
  else if (!extra) { const done = needsRow("check-circle", "Nothing needs you right now.", "", null, null, false); done.classList.add("muted"); list.append(done); }
  $("today-needs").replaceChildren(heading, ...(rows.length || !extra ? [list] : []), ...(extra ? [extra] : []));
}

// Dated sections -------------------------------------------------------------------------------------------------
let todaySectionId = 0;
function datedSection(title, rows, footer = null) {
  const section = element("section", "", "today-region today-section"), heading = element("h2", title);
  heading.id = `today-section-${++todaySectionId}`; section.setAttribute("aria-labelledby", heading.id);
  const list = element("ul", "", "dated-list"); list.append(...rows);
  section.append(heading, list);
  if (footer) section.append(footer);
  return section;
}
function datedRow(when, name, meta, money) {
  const li = element("li", "", "dated-row"), text = element("div");
  text.append(name, element("small", "", "muted"));
  text.lastChild.append(...[].concat(meta));
  const cell = element("span", "", "dated-amount");
  if (money) cell.append(money);
  li.append(element("span", when, "dated-when"), text, cell);
  return li;
}
function todayDated(data, {checkin, returns, warranties}) {
  const sections = [];
  const bill = row => datedRow(dateText(row.due_date), homeLink(row.provider, "#/bills"),
    [...(row.member ? [`${row.member} · `] : []), ...(row.payment_state === "overdue" ? [statusBadge("overdue"), " "] : []), FREQUENCY_LABELS[row.frequency] || row.frequency],
    figure(row.amount_due, {size: "inline", signed: false}));
  if (data.bills.total) sections.push(datedSection("Bills", [...data.bills.overdue, ...data.bills.upcoming].map(bill),
    homeLink(`All bills (${data.bills.total})`, "#/bills", "today-footer")));
  if (data.maturities?.length) {
    const rows = data.maturities.map(due => datedRow(dateText(due.date), homeLink(due.name, due.member ? "#/investments" : `#/investments?account=${due.account_id}`),
      `${due.member ? `${due.member} · ` : ""}${due.account} · ${MATURITY_STATES[due.state === "matured" ? "matured" : due.kind]} ${dateText(due.date)}`,
      amount(due.amount, {signed: false})));
    sections.push(datedSection("CDs and Treasuries coming due", rows,
      data.maturities_total > data.maturities.length ? homeLink(`All ${data.maturities_total} coming due`, "#/investments", "today-footer") : null));
  }
  if (!familyMode && checkin?.lots?.length) {
    const section = datedSection("Weekly check-in", []), body = element("div");
    section.querySelector(".dated-list").replaceWith(body);
    renderCheckin(body, checkin, {compact: true}); sections.push(section);
  }
  if (!familyMode && returns?.length) sections.push(datedSection("Return windows closing", returns.slice(0, 6).map(lot =>
    datedRow(dateText(lot.return_by), homeLink(productName(lot), `#/inventory?${new URLSearchParams({q: lot.name})}`),
      `Return by ${dateText(lot.return_by)}${lot.merchant ? ` · ${lot.merchant}` : ""}`, null))));
  if (!familyMode && warranties?.length) sections.push(datedSection("Warranties ending soon", warranties.slice(0, 6).map(warranty =>
    datedRow(dateText(warranty.expires_on), homeLink([warranty.brand, warranty.name].filter(Boolean).join(" "), `#/inventory?${new URLSearchParams({q: warranty.name})}`),
      `${statusLabel(warranty.kind)} warranty ends ${dateText(warranty.expires_on)}`, null))));
  $("today-dated").replaceChildren(...sections);
}

// Budgets --------------------------------------------------------------------------------------------------------
function todayBudgets(budgets, month, currency) {
  const heading = element("h2", `${MONTH_NAMES[Number(month.slice(5)) - 1]} budgets`); heading.id = "today-budgets-title";
  if (budgets.elapsed_days && budgets.elapsed_days < budgets.days) heading.append(element("small", `Day ${budgets.elapsed_days} of ${budgets.days}`, "muted today-day"));
  const parts = [heading];
  if (!budgets.budgets.length) parts.push(emptyState("No budgets for this month yet.", homeLink("Set a budget", "#/spending")));
  for (const row of budgets.budgets) {
    const item = element("div", "", "today-budget"), head = element("div", "", "today-budget-head");
    head.append(homeLink(row.category, `#/spending?month=${month}`));
    // Over budget is amber with the alert icon, never red (MASTER.md "Budget meter").
    if (row.status === "ahead_of_pace") head.append(statusBadge("ahead_of_pace"));
    if (row.status === "over") head.append(statusBadge("ahead_of_pace", "", "Over budget"));
    const left = element("span", "", row.remaining_state === "over" ? "today-budget-left over" : "today-budget-left");
    if (row.remaining_state === "over") left.append("Over by ", amount(row.over, {magnitude: true}));
    else left.append(figure(row.remaining, {size: "inline", magnitude: true}), " left");
    head.append(left);
    const line = element("small", "", "muted");
    line.append(figure(row.spent, {size: "inline", magnitude: true}), " of ", amount(row.budget, {magnitude: true}));
    if (row.recurring_due.minor > 0) line.append(" · expected ", figure(row.projected, {size: "inline", magnitude: true}));
    item.append(head, meter(row), line);
    parts.push(item);
  }
  const unbudgeted = budgets.unbudgeted.find(row => row.currency === currency);
  const footer = element("p", "", "today-footer muted small");
  if (unbudgeted) footer.append(`Not budgeted: ${unbudgeted.spent.display} · ${plural(unbudgeted.transactions, "transaction", "transactions")} · `);
  if (budgets.budgets.length) { footer.append(homeLink("Set budgets", "#/spending")); parts.push(footer); }
  else if (unbudgeted) parts.push(footer);
  $("today-budgets").replaceChildren(...parts);
}

// Family and about -----------------------------------------------------------------------------------------------
function todayFamily(data, worth) {
  if (!familyMode || !data.family) { $("today-family").replaceChildren(); return; }
  const members = familyMembers(data); members.id = "today-family-members";
  const parts = [members];
  if (worth) { const panel = familyWorthPanel(worth); panel.id = "today-family-worth"; parts.push(panel); }
  parts.push(familyAdjustments(data.family));
  $("today-family").replaceChildren(...parts);
}
function todayAbout(data) {
  const about = $("today-about");
  about.replaceChildren(element("summary", "What these numbers cover"),
    element("p", data.coverage.map(row => `${row.display_name}: ${dateText(row.first)} to ${dateText(row.last)} (${row.transactions} counted transactions)`).join("; ")
      || "No counted account transactions in this period.", "muted small"));
  if (data.pending) about.append(element("p", `${data.pending.amount.display} across ${data.pending.transactions} transactions awaits review or reconciliation and is not counted.`, "item-warning"));
  about.append(element("p", "Totals reflect recorded transactions and approved receipts, not all household spending. A receipt counts until a card or bank charge replaces it, never both. Transfers and card payments are excluded from spending. Each currency is shown separately.", "muted small"));
}

$("today-month").addEventListener("change", () => reloadToday());
$("today-currency").addEventListener("change", () => { today.currency = $("today-currency").value || null; reloadToday(); });
$("today-refresh").addEventListener("click", () => reloadToday());
