"use strict";
// This month, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/money.md): four tiles, the month by
// category beside its budgets, top merchants and refunds, then category rules and what the numbers cover. Every amount
// is the server's; the comparison month's figures come from the same tools called for that month. The route stays #/spending.
const month2 = {month: null, compare: "previous", currency: null, rules: false, budgetForm: null, allMerchants: false};

V2_SCREENS.spending = {title: "This month", show: route => loadMonthV2(route.params)};

function loadMonthV2(params) {
  const month = params?.get?.("month") || "";
  month2.month = /^\d{4}-\d{2}$/.test(month) && month <= localMonth() ? month : localMonth();
  month2.compare = params?.get?.("compare") === "last_year" ? "last_year" : "previous";
  month2.currency = /^[A-Z]{3}$/.test(params?.get?.("currency") || "") ? params.get("currency") : null;
  month2.rules = params?.get?.("rules") === "1";
  $("month2-month").max = localMonth();
  $("month2-month").value = month2.month;
  $("month2-next").disabled = month2.month >= localMonth();
  $("month2-compare").value = month2.compare;
  const name = month2.month.slice(0, 4) === localMonth().slice(0, 4) ? MONTH_NAMES[Number(month2.month.slice(5)) - 1] : monthText(month2.month);
  $("month2-subtitle").textContent = familyMode ? `Where ${name}'s money went, added up across the family.` : `Where ${name}'s money went, and how each budget is doing.`;
  return pageState($("month2-state"), renderMonthV2, {loading: "Loading this month …", what: "spending", needsLibrary: !familyMode, content: [$("month2-body")]});
}
// The controls' values into the URL (Layout rule 5): only what differs from the defaults.
function month2Params() {
  const next = new URLSearchParams();
  if (month2.month !== localMonth()) next.set("month", month2.month);
  if (month2.compare !== "previous") next.set("compare", month2.compare);
  if (month2.currency) next.set("currency", month2.currency);
  if (month2.rules) next.set("rules", "1");
  if (currentRoute?.name === "spending") currentRoute.params = next;
  history.replaceState(null, "", `#/spending${[...next].length ? `?${next}` : ""}`);
  return next;
}
function reloadMonth() {
  month2.month = $("month2-month").value || localMonth();
  month2.compare = $("month2-compare").value;
  return loadMonthV2(month2Params());
}
function month2CompareMonth() { return shiftMonth(month2.month, month2.compare === "last_year" ? -12 : -1); }
// "September", or "October 2025" for the same month last year.
function month2CompareLabel() {
  const other = month2CompareMonth();
  return month2.compare === "last_year" ? monthText(other) : MONTH_NAMES[Number(other.slice(5)) - 1];
}

async function renderMonthV2() {
  const period = monthRange(month2.month), compareMonth = month2CompareMonth(), comparePeriod = monthRange(compareMonth);
  const [spending, before, categories, beforeCategories, comparison, refunds, budgets, rules, accounts] = await Promise.all([
    ledgerTool("get_spending", period), ledgerTool("get_spending", comparePeriod),
    ledgerTool("get_spending_by_category", period), ledgerTool("get_spending_by_category", comparePeriod),
    ledgerTool("compare_categories", {first: comparePeriod, second: period}), ledgerTool("get_refunds"),
    // Budgets and rules are each person's own: the family view adds up spending only.
    familyMode ? null : tool("get_budgets", {month: month2.month, as_of: todayIso()}),
    familyMode ? [] : api("/api/finance/category-rules"),
    familyMode ? {accounts: []} : ledgerTool("get_accounts"), familyMode ? null : loadCategoryOptions()]);
  // One currency at a time; figures are never combined across currencies.
  const currencies = [...new Set([...spending.by_currency, ...before.by_currency, ...categories.categories, ...beforeCategories.categories]
    .map(row => row.currency))].sort();
  const currency = [month2.currency, homeCurrency, "USD"].find(code => code && currencies.includes(code)) || currencies[0] || homeCurrency || "USD";
  $("month2-currency").replaceChildren(...currencies.map(code => new Option(code, code)));
  $("month2-currency").value = currency;
  $("month2-currency-field").hidden = currencies.length < 2;
  const data = {period, currency, spending, before, categories, beforeCategories, comparison, refunds, budgets, rules, accounts: accounts.accounts};
  month2Tiles(data);
  month2Pending(data);
  month2Categories(data);
  $("month2-main").classList.toggle("no-aside", familyMode);
  if (familyMode) $("month2-budgets").replaceChildren(); else month2Budgets(data);
  month2Pair(data);
  if (familyMode) $("month2-rules").replaceChildren(); else month2Rules(data);
  month2About(data);
}

// Tiles ------------------------------------------------------------------------------------------------------------
function month2Tile(label, main, sub) {
  const tile = element("div", "", "figure-tile");
  tile.append(element("p", label, "figure-label"), main);
  for (const line of sub) { const p = element("p", "", "figure-sub"); p.append(...[].concat(line)); tile.append(p); }
  return tile;
}
function month2Count(n, one, many) { return `${n} ${n === 1 ? one : many}`; }
function month2Tiles({period, currency, spending, before, refunds, budgets}) {
  const now = spending.by_currency.find(row => row.currency === currency), then = before.by_currency.find(row => row.currency === currency);
  const zero = `0.00 ${currency}`;
  const netSub = [month2Count(now?.transactions || 0, "transaction", "transactions")];
  if (now?.receipts) netSub.push(["Includes ", amount(now.from_receipts, {signed: false}), ` from ${month2Count(now.receipts, "receipt", "receipts")} no charge has replaced yet`]);
  const credits = refunds.posted_credits.filter(row => row.currency === currency && row.posted_date >= period.start && row.posted_date <= period.end).length;
  const tiles = [
    month2Tile("Net spending", now ? figure(now.net_spending, {size: "lg", signed: false}) : amount(zero, {signed: false}), netSub),
    month2Tile(month2CompareLabel(), then ? figure(then.net_spending, {size: "lg", signed: false}) : amount(zero, {signed: false}),
      [month2Count(then?.transactions || 0, "transaction", "transactions")]),
    month2Tile("Refunded", amount(now?.refunds || zero, {signed: false}), [month2Count(credits, "credit posted", "credits posted")])];
  if (budgets) {
    const counts = {over: 0, ahead_of_pace: 0, on_track: 0};
    for (const row of budgets.budgets.filter(row => row.currency === currency)) counts[row.status in counts ? row.status : "on_track"] += 1;
    const parts = [counts.over ? `${counts.over} over` : "", counts.ahead_of_pace ? `${counts.ahead_of_pace} ahead of pace` : "", counts.on_track ? `${counts.on_track} on track` : ""].filter(Boolean);
    const pace = budgets.elapsed_days && budgets.elapsed_days < budgets.days ? [`Day ${budgets.elapsed_days} of ${budgets.days}`] : [];
    tiles.push(month2Tile("Budgets", element("p", parts.join(" · ") || "No budgets yet", "month2-tile-text"), pace));
  }
  $("month2-tiles").classList.toggle("three", !budgets);
  $("month2-tiles").replaceChildren(...tiles);
}
function month2Pending({currency, spending}) {
  const pending = spending.pending_review.find(row => row.currency === currency);
  $("month2-pending").replaceChildren(...(pending ? [needsRow("alert", `${pending.amount.display} across ${month2Count(pending.transactions, "line", "lines")} isn't counted yet`,
    "They wait for review or for their statement to be reconciled.", "Open To check", "#/review", true)] : []));
}

// By category ------------------------------------------------------------------------------------------------------
function month2Categories({period, currency, categories, beforeCategories, comparison, budgets}) {
  const monthName = MONTH_NAMES[Number(month2.month.slice(5)) - 1], other = month2CompareLabel();
  const heading = element("h2", "By category"); heading.id = "month2-categories-title";
  const key = row => `${row.currency}|${row.category}`;
  const now = new Map(categories.categories.map(row => [key(row), row])), then = new Map(beforeCategories.categories.map(row => [key(row), row]));
  const budgetOf = new Map((budgets?.budgets || []).map(row => [key(row), row]));
  const rows = comparison.categories.filter(row => row.currency === currency && (now.has(key(row)) || then.has(key(row)))).map(row => {
    const tr = document.createElement("tr"), name = cell(tr, "");
    name.append(homeLink(categoryLabel(row.category), txHref({start: period.start, end: period.end, category: row.category, currency, metric: "categories"})));
    const budget = budgetOf.get(key(row));
    if (budget) { const bar = meter(budget); bar.classList.add("month2-inline-meter"); name.append(bar); }
    for (const source of [now, then]) {
      const td = cell(tr, ""); td.className = "numeric";
      const found = source.get(key(row));
      td.append(found ? figure(found.spending, {size: "inline", signed: false}) : element("span", "—", "muted"));
    }
    const change = cell(tr, ""); change.className = "numeric month2-change";
    if (!row.change.minor) change.append(element("span", "—", "muted"));
    else {
      const up = row.change.minor > 0;
      change.append(icon(up ? "arrow-up" : "arrow-down", "icon month2-arrow"), element("span", up ? "more " : "less ", "visually-hidden"),
        amount(row.change, {magnitude: true}), row.percent_change === null ? "" : ` (${String(row.percent_change).replace(/^-/, "")}%)`);
    }
    return tr;
  });
  if (!rows.length) {
    $("month2-categories").replaceChildren(heading, emptyState(`No counted spending in ${monthText(month2.month)} or ${monthText(month2CompareMonth())}.`));
    return;
  }
  const table = element("table", "", "data-table"), head = element("thead", "", "");
  const headRow = document.createElement("tr");
  for (const [text, numeric] of [["Category", false], [monthName, true], [other, true], ["Change", true]]) {
    const th = element("th", text, numeric ? "numeric" : ""); th.scope = "col"; headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody"); body.append(...rows);
  table.append(head, body);
  const wrap = element("div", "", "table-wrap"); wrap.append(table);
  $("month2-categories").replaceChildren(heading, wrap);
}

// Budgets ----------------------------------------------------------------------------------------------------------
function month2Budgets({period, currency, budgets, spending, before}) {
  const heading = element("h2", "Budgets"); heading.id = "month2-budgets-title";
  if (budgets.elapsed_days && budgets.elapsed_days < budgets.days) heading.append(element("small", `Day ${budgets.elapsed_days} of ${budgets.days}`, "muted today-day"));
  const parts = [heading];
  const add = element("button", "", "secondary"); add.type = "button"; add.id = "month2-budget-add";
  add.append(icon("plus"), "Add a budget");
  add.addEventListener("click", () => { month2.budgetForm = {category: "", currency, amount: ""}; month2ShowBudgetForm(); });
  const rows = budgets.budgets.filter(row => row.currency === currency);
  for (const row of rows) {
    const item = element("div", "", "today-budget month2-budget"), head = element("div", "", "today-budget-head");
    head.append(homeLink(categoryLabel(row.category), txHref({start: period.start, end: period.end, category: row.category, currency: row.currency})));
    // Over budget is amber with the alert icon, never red (MASTER.md "Budget meter").
    if (row.status === "ahead_of_pace") head.append(statusBadge("ahead_of_pace"));
    if (row.status === "over") head.append(statusBadge("ahead_of_pace", "", "Over budget"));
    const left = element("span", "", row.remaining_state === "over" ? "today-budget-left over" : "today-budget-left");
    if (row.remaining_state === "over") left.append("Over by ", amount(row.over, {magnitude: true}));
    else left.append(figure(row.remaining, {size: "inline", magnitude: true}), " left");
    const change = element("button", "Change…"); change.type = "button";
    change.addEventListener("click", () => { month2.budgetForm = {category: row.category, currency: row.currency, amount: row.budget.decimal ?? ""}; month2ShowBudgetForm(); });
    const remove = element("button", "Remove…", "danger-text"); remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!await confirmAction({title: "Remove this budget?", message: `The ${categoryLabel(row.category)} budget of ${row.budget.display} a month will be removed. Transactions are not affected.`, confirmLabel: "Remove budget"})) return;
      try { await api(`/api/finance/budgets/${row.id}`, {method: "DELETE"}); notice("Budget removed."); await reloadMonth(); } catch (error) { notice(error, true); }
    });
    head.append(left, menu(`${categoryLabel(row.category)} budget actions`, [change, remove]));
    const line = element("small", "", "muted");
    line.append(figure(row.spent, {size: "inline", magnitude: true}), " of ", amount(row.budget, {magnitude: true}));
    if (row.recurring_due.minor > 0) line.append(" · expected ", figure(row.projected, {size: "inline", magnitude: true}), " by month end");
    item.append(head, meter(row), line);
    parts.push(item);
  }
  if (rows.length) {
    const unbudgeted = budgets.unbudgeted.find(row => row.currency === currency);
    const footer = element("div", "", "month2-budget-footer");
    if (unbudgeted) footer.append(element("p", `${unbudgeted.spent.display} in categories without a budget (${month2Count(unbudgeted.transactions, "transaction", "transactions")})`, "muted small"));
    footer.append(add);
    parts.push(footer);
  } else parts.push(emptyState("No budgets yet.", add));
  parts.push(month2BudgetForm([...new Set([currency, ...spending.by_currency.map(row => row.currency), ...before.by_currency.map(row => row.currency)])]));
  $("month2-budgets").replaceChildren(...parts);
  if (month2.budgetForm) month2ShowBudgetForm(false);
}
function month2Field(label, control) {
  const field = element("div", "", "field"), name = element("label", label);
  name.htmlFor = control.id; field.append(name, control);
  return field;
}
function month2BudgetForm(currencies) {
  const form = element("form", "", "month2-form"); form.id = "month2-budget-form"; form.hidden = true; form.noValidate = true;
  const category = document.createElement("input"); category.id = "month2-budget-category";
  Object.assign(category, {required: true, maxLength: 60, autocomplete: "off"}); category.setAttribute("list", "category-options");
  const currency = document.createElement("select"); currency.id = "month2-budget-currency";
  currency.append(...currencies.map(code => new Option(code, code)));
  const amountInput = document.createElement("input"); amountInput.id = "month2-budget-amount";
  Object.assign(amountInput, {required: true, inputMode: "decimal", placeholder: "450.00", autocomplete: "off"});
  amountInput.setAttribute("aria-describedby", "month2-budget-error");
  const error = element("p", "", "field-error"); error.id = "month2-budget-error"; error.setAttribute("role", "alert");
  const save = element("button", "Save budget", "primary"); save.type = "submit";
  const cancel = element("button", "Cancel", "link-button"); cancel.type = "button";
  cancel.addEventListener("click", () => { month2.budgetForm = null; form.hidden = true; $("month2-budget-add")?.focus(); });
  const actions = element("div", "", "button-row"); actions.append(save, cancel);
  form.append(month2Field("Category", category), month2Field("Currency", currency), month2Field("Monthly amount", amountInput), actions, error);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    error.replaceChildren();
    save.disabled = true;
    try {
      const budget = await api("/api/finance/budgets", {method: "PUT", body: JSON.stringify({category: category.value, currency: currency.value, amount: amountInput.value.trim()})});
      month2.budgetForm = null;
      notice(`Budget saved: ${categoryLabel(budget.category)}, ${budget.amount.display} a month.`);
      await reloadMonth();
    } catch (problem) {
      error.append(icon("alert"), problem.message || String(problem));
      amountInput.focus();
    } finally { save.disabled = false; }
  });
  return form;
}
function month2ShowBudgetForm(focus = true) {
  const form = $("month2-budget-form"), values = month2.budgetForm;
  if (!form || !values) return;
  form.hidden = false;
  $("month2-budget-category").value = values.category;
  if ([...$("month2-budget-currency").options].some(option => option.value === values.currency)) $("month2-budget-currency").value = values.currency;
  $("month2-budget-amount").value = values.amount;
  if (focus) (values.category ? $("month2-budget-amount") : $("month2-budget-category")).focus();
}

// Top merchants and refunds -----------------------------------------------------------------------------------------
function month2Section(id, title) {
  const heading = element("h2", title); heading.id = `${id}-title`;
  $(id).setAttribute("aria-labelledby", heading.id);
  return heading;
}
function month2Pair({period, currency, categories, refunds}) {
  const merchants = categories.top_merchants.filter(row => row.currency === currency);
  const merchantParts = [month2Section("month2-merchants", "Top merchants")];
  if (merchants.length) {
    const list = element("ul", "", "dated-list");
    list.append(...merchants.map((row, index) => {
      const li = element("li", "", "dated-row month2-merchant");
      li.hidden = index >= 8 && !month2.allMerchants;
      li.append(element("span", row.merchant, "month2-merchant-name"), element("span", `${row.transactions}×`, "muted small"));
      const money = element("span", "", "dated-amount"); money.append(amount(row.spending, {signed: false})); li.append(money);
      return li;
    }));
    merchantParts.push(list);
    if (merchants.length > 8) {
      const toggle = element("button", month2.allMerchants ? "Show the top 8" : `Show all ${merchants.length}`, "link-button today-footer"); toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(month2.allMerchants));
      toggle.addEventListener("click", () => {
        month2.allMerchants = !month2.allMerchants;
        list.querySelectorAll("li").forEach((li, index) => { li.hidden = index >= 8 && !month2.allMerchants; });
        toggle.textContent = month2.allMerchants ? "Show the top 8" : `Show all ${merchants.length}`;
        toggle.setAttribute("aria-expanded", String(month2.allMerchants));
      });
      merchantParts.push(toggle);
    }
  } else merchantParts.push(element("p", `No merchants in ${MONTH_NAMES[Number(month2.month.slice(5)) - 1]}.`, "muted small"));
  $("month2-merchants").replaceChildren(...merchantParts);

  const inMonth = value => value && value >= period.start && value <= period.end;
  const refundRow = (day, name, meta, money) => {
    const li = element("li", "", "dated-row"), when = element("span", "", "dated-when"), text = element("div");
    if (day) when.append(dateDisplay(day));
    text.append(element("span", name), element("small", "", "muted"));
    text.lastChild.append(...[].concat(meta));
    const cellNode = element("span", "", "dated-amount"); cellNode.append(money);
    li.append(when, text, cellNode);
    return li;
  };
  const rows = [
    ...refunds.posted_credits.filter(row => inMonth(row.posted_date)).map(row => refundRow(row.posted_date,
      `${row.owner ? `${row.owner} · ` : ""}${row.description_raw}`, row.purchase_id ? "Linked to its purchase" : "Credit posted", amount(row.amount))),
    ...refunds.refund_evidence.filter(row => !row.purchase_date || inMonth(row.purchase_date)).map(row => refundRow(row.purchase_date,
      `${row.owner ? `${row.owner} · ` : ""}${row.merchant || "Return receipt"}`, statusBadge(row.settlement), amount(row.amount)))];
  const refundParts = [month2Section("month2-refunds", "Refunds")];
  if (rows.length) { const list = element("ul", "", "dated-list"); list.append(...rows); refundParts.push(list); }
  else refundParts.push(element("p", `No refunds in ${MONTH_NAMES[Number(month2.month.slice(5)) - 1]}.`, "muted small"));
  $("month2-refunds").replaceChildren(...refundParts);
}

// Category rules and what the numbers cover -------------------------------------------------------------------------
function month2Rules({rules, accounts}) {
  const details = $("month2-rules");
  details.open = month2.rules;
  const parts = [element("summary", `Category rules (${rules.length})`),
    element("p", "Transactions whose merchant or description contain every word get the category, now and when new ones arrive. The most specific rule wins; a category you set by hand on a transaction is never changed.", "muted small")];
  if (rules.length) {
    const table = element("table", "", "data-table"), head = document.createElement("thead"), headRow = document.createElement("tr");
    for (const [text, className] of [["Words", ""], ["Category", ""], ["Account", ""], ["Transactions", "numeric"], ["", ""]]) {
      const th = element("th", "", className); th.scope = "col";
      if (text) th.textContent = text; else th.append(element("span", "Actions", "visually-hidden"));
      headRow.append(th);
    }
    head.append(headRow);
    const body = document.createElement("tbody");
    body.append(...rules.map(rule => {
      const tr = document.createElement("tr");
      cell(tr, rule.pattern, true); cell(tr, categoryLabel(rule.category)); cell(tr, rule.account || "Any account"); cell(tr, rule.transactions).className = "numeric";
      const remove = element("button", "Delete", "link-button"); remove.type = "button"; remove.setAttribute("aria-label", `Delete the rule ${rule.pattern}`);
      remove.addEventListener("click", async () => {
        if (!await confirmAction({title: "Delete this rule?", message: `Transactions it categorized as ${categoryLabel(rule.category)} go to the next matching rule, or back to uncategorized. Categories you set by hand stay.`, confirmLabel: "Delete rule", danger: true})) return;
        try {
          const result = await api(`/api/finance/category-rules/${rule.id}`, {method: "DELETE"});
          notice(`Rule deleted; ${month2Count(result.changed, "transaction", "transactions")} updated.`); await reloadMonth();
        } catch (error) { notice(error, true); }
      });
      cell(tr, "").append(remove);
      return tr;
    }));
    table.append(head, body);
    const wrap = element("div", "", "table-wrap"); wrap.append(table);
    parts.push(wrap);
  } else parts.push(element("p", "No rules yet.", "muted small"));
  const form = element("form", "", "month2-form"); form.id = "month2-rule-form"; form.noValidate = true;
  const pattern = document.createElement("input"); pattern.id = "month2-rule-pattern";
  Object.assign(pattern, {required: true, maxLength: 120, placeholder: "COSTCO", autocomplete: "off"});
  const category = document.createElement("input"); category.id = "month2-rule-category";
  Object.assign(category, {required: true, maxLength: 60, autocomplete: "off"}); category.setAttribute("list", "category-options");
  const account = document.createElement("select"); account.id = "month2-rule-account";
  account.append(new Option("Any account", ""), ...accounts.map(accountOption));
  const error = element("p", "", "field-error"); error.id = "month2-rule-error"; error.setAttribute("role", "alert");
  pattern.setAttribute("aria-describedby", error.id);
  const add = element("button", "Add rule", "secondary"); add.type = "submit";
  const actions = element("div", "", "button-row"); actions.append(add);
  form.append(month2Field("Words", pattern), month2Field("Category", category), month2Field("Account", account), actions, error);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    error.replaceChildren();
    add.disabled = true;
    try {
      const body = {pattern: pattern.value, category: category.value};
      if (account.value) body.account_id = Number(account.value);
      const rule = await api("/api/finance/category-rules", {method: "POST", body: JSON.stringify(body)});
      notice(`Rule saved: “${rule.pattern}” → ${categoryLabel(rule.category)}. ${month2Count(rule.changed, "transaction", "transactions")} updated.`);
      await reloadMonth();
    } catch (problem) {
      error.append(icon("alert"), problem.message || String(problem));
      pattern.focus();
    } finally { add.disabled = false; }
  });
  parts.push(form);
  details.replaceChildren(...parts);
}
function month2About({spending}) {
  const parts = [element("summary", "What these numbers cover"),
    element("p", `${month2Count(spending.excluded_transfers_and_card_payments, "transfer or card payment", "transfers and card payments")} excluded.`, "small")];
  const coverage = element("ul", "", "month2-coverage small");
  coverage.append(...spending.coverage.map(row => element("li",
    `${row.display_name}: ${row.transactions ? `${dateText(row.first)} – ${dateText(row.last)}` : "no data this month"}`)));
  if (spending.coverage.length) parts.push(coverage); else parts.push(element("p", "No accounts yet.", "muted small"));
  parts.push(...spending.notes.map(note => element("p", note, "muted small")));
  $("month2-about").replaceChildren(...parts);
}

$("month2-prev").prepend(icon("chevron-left"));
$("month2-next").prepend(icon("chevron-right"));
$("month2-prev").addEventListener("click", () => { $("month2-month").value = shiftMonth(month2.month, -1); reloadMonth(); });
$("month2-next").addEventListener("click", () => { if (month2.month < localMonth()) { $("month2-month").value = shiftMonth(month2.month, 1); reloadMonth(); } });
$("month2-month").addEventListener("change", () => { if ($("month2-month").value) reloadMonth(); });
$("month2-compare").addEventListener("change", () => reloadMonth());
$("month2-currency").addEventListener("change", () => { month2.currency = $("month2-currency").value || null; reloadMonth(); });
$("month2-rules").addEventListener("toggle", () => {
  if (month2.rules === $("month2-rules").open) return;
  month2.rules = $("month2-rules").open; month2Params();
});
