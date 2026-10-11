"use strict";
// Forecast page: the server computes every number and draws every chart; this page only collects
// assumptions, lists assets, and shows the results. Charts arrive as escaped SVG and are parsed as XML.
let forecastLoad = 0, forecastCategories = [];

function forecastField(labelText, input) {
  const field = element("div", "", "field");
  const label = element("label", labelText); label.htmlFor = input.id;
  field.append(label, input); return field;
}
function forecastInput(id, attributes = {}) {
  const input = document.createElement("input"); input.id = id;
  for (const [name, value] of Object.entries(attributes)) input.setAttribute(name, value);
  return input;
}
let forecastRowId = 0;
// focus: false when rows are rebuilt from the URL rather than added by the person. Returns the row.
function forecastRow(list, fields, {focus = true} = {}) {
  const row = element("div", "", "forecast-row forecast-item"), id = ++forecastRowId;
  for (const [key, label, attributes] of fields) {
    const input = forecastInput(`${list}-${key}-${id}`, attributes);
    input.dataset.key = key;
    row.append(forecastField(label, input));
  }
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => row.remove());
  row.append(remove); $(list).append(row);
  if (focus) row.querySelector("input").focus();
  return row;
}
function forecastItems(list) {
  return [...$(list).querySelectorAll(".forecast-item")].map(row =>
    Object.fromEntries([...row.querySelectorAll("input")].map(input => [input.dataset.key, input.value.trim()])));
}
// The field specs of each assumption list. p is the id prefix: "" for this page, "fc2-" for the redesigned one
// (forecast_v2.js), which reuses these builders on its own copies of the inputs.
function forecastLists(p = "") {
  return {
    spending: [p + "forecast-spending-changes", [["category", "Category", {list: p + "forecast-category-options", required: ""}], ["percent", "Change (%)", {inputmode: "decimal", required: "", placeholder: "10"}]]],
    income: [p + "forecast-income-changes", [["month", "From month", {type: "month", required: ""}], ["monthly_amount", "Monthly change", {inputmode: "decimal", required: "", placeholder: "500.00"}]]],
    oneoff: [p + "forecast-one-offs", [["month", "Month", {type: "month", required: ""}], ["amount", "Amount", {inputmode: "decimal", required: "", placeholder: "-3000.00"}], ["label", "What it is", {maxlength: "80"}]]],
    edu: [p + "forecast-education", [["month", "Month", {type: "month", required: ""}], ["amount", "Cost", {inputmode: "decimal", required: "", placeholder: "12000.00"}], ["label", "What it is", {maxlength: "80"}]]],
  };
}

function forecastRequest(p = "") {
  const request = {years: Number($(p + "forecast-years").value), inflation_percent: $(p + "forecast-inflation").value.trim(),
                   income_growth_percent: $(p + "forecast-income-growth").value.trim(), history_months: Number($(p + "forecast-history").value),
                   spending_changes: forecastItems(p + "forecast-spending-changes"), income_changes: forecastItems(p + "forecast-income-changes"),
                   one_offs: forecastItems(p + "forecast-one-offs").map(item => ({...item, label: item.label || ""})),
                   education_withdrawals: forecastItems(p + "forecast-education").map(item => ({...item, label: item.label || ""}))};
  // A retirement plan is one self-contained input, so a scenario can change it without touching the rest.
  if ($(p + "retire-plan").checked) {
    const fixed = $(p + "retire-mode").value === "fixed";
    request.retirement = {start_month: $(p + "retire-month").value, mode: $(p + "retire-mode").value, tax_percent: $(p + "retire-tax").value.trim() || "0",
                          ...(fixed ? {monthly_amount: $(p + "retire-amount").value.trim()} : {cash_floor: $(p + "retire-floor").value.trim() || "0"})};
  }
  return request;
}
function showRetirementFields(p = "") {
  const on = $(p + "retire-plan").checked, fixed = $(p + "retire-mode").value === "fixed";
  $(p + "retire-fields").hidden = !on;
  $(p + "retire-month").required = on;
  $(p + "retire-amount-field").hidden = !fixed; $(p + "retire-amount").required = on && fixed;
  $(p + "retire-floor-field").hidden = fixed;
}

// Investment accounts have their own page (investments.js) and join the forecast from there.
const ASSET_KINDS = {vehicle: "Vehicle", real_estate: "Home or property", other_asset: "Other asset", loan: "Loan"};
// Whichever forecast screen is showing reloads after an asset is added or removed; forecast_v2.js points this at its own.
let forecastReload = () => loadForecast();
async function loadAssets(p = "") {
  const assets = await api("/api/assets"), body = $(p + "asset-rows");
  body.replaceChildren();
  if (!assets.length) {
    const row = body.insertRow(), td = row.insertCell(); td.colSpan = 8;
    td.append(element("span", "No assets or loans yet. Add a car or home below; loan statements add theirs after review.", "muted"));
  }
  for (const asset of assets) {
    const row = body.insertRow();
    cell(row, asset.name); cell(row, ASSET_KINDS[asset.kind] || asset.kind);
    const value = cell(row, ""); value.className = "numeric"; value.append(amount(asset.value, {signed: false})); cell(row, dateText(asset.as_of));
    cell(row, `${asset.annual_rate_percent}%`).className = "numeric";
    cell(row, asset.monthly_payment ? asset.monthly_payment.display : "—").className = "numeric";
    cell(row, asset.source === "manual" ? "Entered by you" : {verified: "Statement, confirmed", rejected: "Statement, rejected (not counted)"}[asset.review_status] || "Statement, awaiting review");
    const td = row.insertCell(), remove = element("button", "Remove", "quiet"); remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${asset.name}`);
    remove.addEventListener("click", async () => {
      if (!await confirmAction({title: `Remove ${asset.name}?`, message: "It is left out of forecasts from now on. Its history is kept.", confirmLabel: "Remove"})) return;
      try { await api(`/api/assets/${asset.id}`, {method: "DELETE"}); await forecastReload(); } catch (error) { notice(error, true); }
    });
    td.append(remove);
  }
}
// The listeners on one copy of the inputs: "Add …" rows, retirement fields and the asset form.
function wireForecast(p = "") {
  const lists = forecastLists(p);
  for (const [button, key] of [["add-spending-change", "spending"], ["add-income-change", "income"], ["add-one-off", "oneoff"], ["add-education", "edu"]]) {
    $(p + button).addEventListener("click", () => forecastRow(...lists[key]));
  }
  $(p + "retire-plan").addEventListener("change", () => showRetirementFields(p));
  $(p + "retire-mode").addEventListener("change", () => showRetirementFields(p));
  $(p + "asset-kind").addEventListener("change", () => {
    const loan = $(p + "asset-kind").value === "loan";
    $(p + "asset-payment").disabled = !loan; if (!loan) $(p + "asset-payment").value = "";
    $(p + "asset-rate").placeholder = loan ? "Interest, e.g. 6.5" : $(p + "asset-kind").value === "vehicle" ? "Car: -15 if blank" : "0 if blank";
  });
  $(p + "asset-form").addEventListener("submit", async event => {
    event.preventDefault();
    const body = {name: $(p + "asset-name").value.trim(), kind: $(p + "asset-kind").value, value: $(p + "asset-value").value.trim(),
                  currency: $(p + "asset-currency").value.trim().toUpperCase(), as_of: $(p + "asset-as-of").value};
    if ($(p + "asset-rate").value.trim()) body.annual_rate_percent = $(p + "asset-rate").value.trim();
    if ($(p + "asset-payment").value.trim()) body.monthly_payment = $(p + "asset-payment").value.trim();
    try {
      await api("/api/assets", {method: "POST", body: JSON.stringify(body)});
      for (const id of ["asset-name", "asset-value", "asset-rate", "asset-payment"]) $(p + id).value = "";
      notice(`${body.name} added.`); await forecastReload();
    } catch (error) { notice(error, true); }
  });
}
wireForecast();

function forecastSvg(markup) {
  // Server-built, escaped SVG. Parsed as XML and imported: nothing in it can run.
  const parsed = new DOMParser().parseFromString(markup, "image/svg+xml").documentElement;
  if (parsed.nodeName !== "svg") throw new Error("A chart could not be drawn.");
  return document.importNode(parsed, true);
}
// columns: [label, key] pairs into each year's display text. money(year, key) draws one cell; the redesigned page
// passes one that makes traced columns into figures.
function forecastTable(result, columns, money = (year, key) => amount(year.display[key], {signed: false})) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
  const head = table.createTHead().insertRow();
  for (const [label] of [["Year"], ...columns]) { const th = document.createElement("th"); th.scope = "col"; th.textContent = label; head.append(th); }
  const body = table.createTBody();
  for (const year of result.years) {
    const row = body.insertRow(); cell(row, year.year);
    for (const [, key] of columns) { const td = cell(row, ""); td.className = "numeric"; td.append(money(year, key)); }
  }
  wrap.append(table); return wrap;
}
// Each chart's title and table columns (exact text from the server; the browser never formats money).
function forecastColumns(result) {
  return {
    net_worth: ["Net worth", [["Net worth", "end_net_worth"], ["In today's dollars", "end_net_worth_today"]]],
    cash_flow: ["Income and spending", [["Income", "income"], ["Spending", "spending"], ["Loan payments", "loan_payments"], ["One-off", "one_offs"],
      // Money drawn from investments to cash, after tax, and the part only required distributions took.
      ...(result.years.some(year => year.withdrawals) ? [["From investments", "withdrawals"], ["Tax withheld", "withdrawal_tax"], ["Required (RMD)", "rmd"]] : []),
      // Pensions pay an income (before its tax); planned education costs and the part a 529 paid.
      ...(result.years.some(year => year.pension) ? [["Pension", "pension"], ["Pension tax", "pension_tax"]] : []),
      ...(result.years.some(year => year.education) ? [["Education", "education"], ["Paid by the 529", "education_from_529"]] : [])]],
    balance_sheet: ["Cash, assets and loans", [["Cash", "end_cash"], ["Assets", "end_assets"], ["Loans owed", "end_loans"]]],
  };
}
function retirementFacts(result) {
  // What the retirement plan and required distributions assume, as the server received them.
  const plan = result.assumptions.retirement, rmd = result.assumptions.rmd_start, facts = [];
  if (plan) {
    const pay = result.starting_point.monthly_pay;
    facts.push(["Retirement", `From ${monthText(plan.start_month)}: ${pay.minor ? `take-home pay of ${pay.display} a month stops; ` : ""}`
      + (plan.mode === "fixed" ? `withdraw ${plan.monthly_amount} a month in today's dollars` : `withdraw enough to keep ${plan.cash_floor} in cash, in today's dollars`)
      + `; ${plan.tax_percent}% tax on tax-deferred withdrawals`]);
  }
  if (rmd) facts.push(["Required distributions", `From ${rmd.year} (age ${rmd.age}), each December`]);
  return facts;
}
// The Starting point block's nodes. label shows a category name (the redesigned page passes categoryLabel).
function forecastStart(result, label = name => name) {
  const start = result.starting_point, facts = element("dl", "", "forecast-facts");
  const history = result.assumptions.history;
  for (const [label, value] of [["Cash in accounts", start.cash.display], ["Monthly income", start.monthly_income.display],
      ["Averaged over", `${dateText(history.start)} to ${dateText(history.end)}`], ["Inflation", `${result.assumptions.inflation_percent}% a year`],
      ["Income growth", `${result.assumptions.income_growth_percent}% a year`], ...retirementFacts(result)]) facts.append(element("dt", label), element("dd", value));
  const spending = element("ul", "", "forecast-notes");
  for (const row of start.monthly_spending) spending.append(element("li", `${label(row.category)}: ${row.amount.display} a month`));
  // Confirmed recurring bills are projected on their due dates rather than averaged.
  const bills = element("ul", "", "finance-list");
  for (const bill of start.recurring_bills || []) {
    bills.append(element("li", `${bill.name} (${bill.kind === "subscription" ? "subscription, " : ""}${label(bill.category)}): ${bill.amount.display} ${FREQUENCY_LABELS[bill.frequency].toLowerCase()}${bill.next_due ? `, next ${dateText(bill.next_due)}` : ""}`));
  }
  const invested = start.assets.filter(asset => asset.investment), investments = element("ul", "", "finance-list");
  for (const asset of invested) {
    // Contributions each month (from pay, and from your cash), and CDs or Treasuries paid out at maturity.
    const adds = [asset.monthly_from_pay ? `${asset.monthly_from_pay.display} a month from pay` : "", asset.monthly_from_you ? `${asset.monthly_from_you.display} a month from your cash` : ""].filter(Boolean);
    const li = element("li", `${asset.name} (${asset.kind_label}): ${asset.value.display}, growing ${asset.annual_rate_percent}% a year${adds.length ? `, plus ${adds.join(" and ")}` : ""}`);
    for (const due of asset.maturing) li.append(element("small", `${due.name} ${due.to_cash ? "pays" : "renews at"} ${due.amount.display} in ${monthText(due.month)}${due.to_cash ? " to cash" : ""}`, "muted block"));
    investments.append(li);
  }
  return [facts, element("h3", "Monthly spending by category"),
    start.monthly_spending.length ? spending : element("p", "No recent counted spending.", "muted"),
    ...((start.recurring_bills || []).length ? [element("h3", "Recurring bills and subscriptions"), bills] : []),
    element("h3", "Investments"), invested.length ? investments : element("p", "No confirmed investment values.", "muted"),
    homeLink("Open Investments to add accounts or change growth rates", "#/investments")];
}
// The categories a spending change can name, as the datalist id (one per screen).
function forecastCategoryOptions(result, id) {
  const start = result.starting_point;
  forecastCategories = [...new Set([...start.monthly_spending.map(row => row.category), ...(start.recurring_bills || []).map(bill => bill.category)])];
  const options = document.getElementById(id) || Object.assign(document.createElement("datalist"), {id});
  options.replaceChildren(...forecastCategories.map(name => Object.assign(document.createElement("option"), {value: name})));
  document.body.append(options);
}
function renderForecast(result) {
  const alerts = $("forecast-alerts"); alerts.replaceChildren();
  if (result.first_month_cash_below_zero) alerts.append(alertBox(`Cash is projected to fall below zero in ${monthText(result.first_month_cash_below_zero)}.`, {tone: "warning"}));
  if (result.notes.length) {
    const list = element("ul", "", "forecast-notes"); for (const note of result.notes) list.append(element("li", note));
    const box = alertBox("About these numbers", {tone: "info"}); box.querySelector(".alert-body").append(list); alerts.append(box);
  }
  $("forecast-start").replaceChildren(...forecastStart(result));
  forecastCategoryOptions(result, "forecast-category-options");
  $("forecast-charts").replaceChildren(...Object.entries(forecastColumns(result)).map(([key, [title, columns]]) => {
    const card = element("section", "", "panel forecast-chart-card"), details = element("details");
    details.append(element("summary", "Show the numbers by year"), forecastTable(result, columns));
    card.append(element("h2", title), forecastSvg(result.charts[key]), details);
    return card;
  }));
}
function loadForecast() {
  forecastReload = () => loadForecast();
  return pageState($("forecast-state"), runForecast, {loading: "Loading the forecast …", what: "the forecast", needsLibrary: true, content: [$("forecast-charts")]});
}
async function runForecast() {
  const load = ++forecastLoad;
  if (!$("asset-as-of").value) $("asset-as-of").value = todayIso();  // Local today: toISOString is UTC, a day ahead in the evening west of it.
  await loadAssets();
  const result = await api("/api/forecast", {method: "POST", body: JSON.stringify(forecastRequest())});
  if (load === forecastLoad) renderForecast(result);
}
$("forecast-form").addEventListener("submit", event => {
  event.preventDefault();
  loadForecast();  // pageState shows any error.
});
