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
function forecastRow(list, fields) {
  const row = element("div", "", "forecast-row forecast-item"), id = ++forecastRowId;
  for (const [key, label, attributes] of fields) {
    const input = forecastInput(`${list}-${key}-${id}`, attributes);
    input.dataset.key = key;
    row.append(forecastField(label, input));
  }
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => row.remove());
  row.append(remove); $(list).append(row);
  row.querySelector("input").focus();
}
function forecastItems(list) {
  return [...$(list).querySelectorAll(".forecast-item")].map(row =>
    Object.fromEntries([...row.querySelectorAll("input")].map(input => [input.dataset.key, input.value.trim()])));
}
$("add-spending-change").addEventListener("click", () => forecastRow("forecast-spending-changes",
  [["category", "Category", {list: "forecast-category-options", required: ""}], ["percent", "Change (%)", {inputmode: "decimal", required: "", placeholder: "10"}]]));
$("add-income-change").addEventListener("click", () => forecastRow("forecast-income-changes",
  [["month", "From month", {type: "month", required: ""}], ["monthly_amount", "Monthly change", {inputmode: "decimal", required: "", placeholder: "500.00"}]]));
$("add-one-off").addEventListener("click", () => forecastRow("forecast-one-offs",
  [["month", "Month", {type: "month", required: ""}], ["amount", "Amount", {inputmode: "decimal", required: "", placeholder: "-3000.00"}], ["label", "What it is", {maxlength: "80"}]]));
$("add-education").addEventListener("click", () => forecastRow("forecast-education",
  [["month", "Month", {type: "month", required: ""}], ["amount", "Cost", {inputmode: "decimal", required: "", placeholder: "12000.00"}], ["label", "What it is", {maxlength: "80"}]]));

function forecastRequest() {
  const request = {years: Number($("forecast-years").value), inflation_percent: $("forecast-inflation").value.trim(),
                   income_growth_percent: $("forecast-income-growth").value.trim(), history_months: Number($("forecast-history").value),
                   spending_changes: forecastItems("forecast-spending-changes"), income_changes: forecastItems("forecast-income-changes"),
                   one_offs: forecastItems("forecast-one-offs").map(item => ({...item, label: item.label || ""})),
                   education_withdrawals: forecastItems("forecast-education").map(item => ({...item, label: item.label || ""}))};
  // A retirement plan is one self-contained input, so a scenario can change it without touching the rest.
  if ($("retire-plan").checked) {
    const fixed = $("retire-mode").value === "fixed";
    request.retirement = {start_month: $("retire-month").value, mode: $("retire-mode").value, tax_percent: $("retire-tax").value.trim() || "0",
                          ...(fixed ? {monthly_amount: $("retire-amount").value.trim()} : {cash_floor: $("retire-floor").value.trim() || "0"})};
  }
  return request;
}
function showRetirementFields() {
  const on = $("retire-plan").checked, fixed = $("retire-mode").value === "fixed";
  $("retire-fields").hidden = !on;
  $("retire-month").required = on;
  $("retire-amount-field").hidden = !fixed; $("retire-amount").required = on && fixed;
  $("retire-floor-field").hidden = fixed;
}
$("retire-plan").addEventListener("change", showRetirementFields);
$("retire-mode").addEventListener("change", showRetirementFields);

// Investment accounts have their own page (investments.js) and join the forecast from there.
const ASSET_KINDS = {vehicle: "Vehicle", real_estate: "Home or property", other_asset: "Other asset", loan: "Loan"};
async function loadAssets() {
  const assets = await api("/api/assets"), body = $("asset-rows");
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
      try { await api(`/api/assets/${asset.id}`, {method: "DELETE"}); await loadForecast(); } catch (error) { notice(error, true); }
    });
    td.append(remove);
  }
}
$("asset-kind").addEventListener("change", () => {
  const loan = $("asset-kind").value === "loan";
  $("asset-payment").disabled = !loan; if (!loan) $("asset-payment").value = "";
  $("asset-rate").placeholder = loan ? "Interest, e.g. 6.5" : $("asset-kind").value === "vehicle" ? "Car: -15 if blank" : "0 if blank";
});
$("asset-form").addEventListener("submit", async event => {
  event.preventDefault();
  const body = {name: $("asset-name").value.trim(), kind: $("asset-kind").value, value: $("asset-value").value.trim(),
                currency: $("asset-currency").value.trim().toUpperCase(), as_of: $("asset-as-of").value};
  if ($("asset-rate").value.trim()) body.annual_rate_percent = $("asset-rate").value.trim();
  if ($("asset-payment").value.trim()) body.monthly_payment = $("asset-payment").value.trim();
  try {
    await api("/api/assets", {method: "POST", body: JSON.stringify(body)});
    for (const id of ["asset-name", "asset-value", "asset-rate", "asset-payment"]) $(id).value = "";
    notice(`${body.name} added.`); await loadForecast();
  } catch (error) { notice(error, true); }
});

function forecastSvg(markup) {
  // Server-built, escaped SVG. Parsed as XML and imported: nothing in it can run.
  const parsed = new DOMParser().parseFromString(markup, "image/svg+xml").documentElement;
  if (parsed.nodeName !== "svg") throw new Error("A chart could not be drawn.");
  return document.importNode(parsed, true);
}
function forecastTable(result, columns) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
  const head = table.createTHead().insertRow();
  for (const [label] of [["Year"], ...columns]) { const th = document.createElement("th"); th.scope = "col"; th.textContent = label; head.append(th); }
  const body = table.createTBody();
  for (const year of result.years) {
    const row = body.insertRow(); cell(row, year.year);
    for (const [, value] of columns) { const td = cell(row, ""); td.className = "numeric"; td.append(amount(value(year), {signed: false})); }
  }
  wrap.append(table); return wrap;
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
function renderForecast(result) {
  const alerts = $("forecast-alerts"); alerts.replaceChildren();
  if (result.first_month_cash_below_zero) alerts.append(alertBox(`Cash is projected to fall below zero in ${monthText(result.first_month_cash_below_zero)}.`, {tone: "warning"}));
  if (result.notes.length) {
    const list = element("ul", "", "forecast-notes"); for (const note of result.notes) list.append(element("li", note));
    const box = alertBox("About these numbers", {tone: "info"}); box.querySelector(".alert-body").append(list); alerts.append(box);
  }
  const start = result.starting_point, facts = element("dl", "", "forecast-facts");
  const history = result.assumptions.history;
  for (const [label, value] of [["Cash in accounts", start.cash.display], ["Monthly income", start.monthly_income.display],
      ["Averaged over", `${dateText(history.start)} to ${dateText(history.end)}`], ["Inflation", `${result.assumptions.inflation_percent}% a year`],
      ["Income growth", `${result.assumptions.income_growth_percent}% a year`], ...retirementFacts(result)]) facts.append(element("dt", label), element("dd", value));
  const spending = element("ul", "", "forecast-notes");
  for (const row of start.monthly_spending) spending.append(element("li", `${row.category}: ${row.amount.display} a month`));
  // Confirmed recurring bills are projected on their due dates rather than averaged.
  const bills = element("ul", "", "finance-list");
  for (const bill of start.recurring_bills || []) {
    bills.append(element("li", `${bill.name} (${bill.kind === "subscription" ? "subscription, " : ""}${bill.category}): ${bill.amount.display} ${FREQUENCY_LABELS[bill.frequency].toLowerCase()}${bill.next_due ? `, next ${dateText(bill.next_due)}` : ""}`));
  }
  const invested = start.assets.filter(asset => asset.investment), investments = element("ul", "", "finance-list");
  for (const asset of invested) {
    // Contributions each month (from pay, and from your cash), and CDs or Treasuries paid out at maturity.
    const adds = [asset.monthly_from_pay ? `${asset.monthly_from_pay.display} a month from pay` : "", asset.monthly_from_you ? `${asset.monthly_from_you.display} a month from your cash` : ""].filter(Boolean);
    const li = element("li", `${asset.name} (${asset.kind_label}): ${asset.value.display}, growing ${asset.annual_rate_percent}% a year${adds.length ? `, plus ${adds.join(" and ")}` : ""}`);
    for (const due of asset.maturing) li.append(element("small", `${due.name} ${due.to_cash ? "pays" : "renews at"} ${due.amount.display} in ${monthText(due.month)}${due.to_cash ? " to cash" : ""}`, "muted block"));
    investments.append(li);
  }
  $("forecast-start").replaceChildren(facts, element("h3", "Monthly spending by category"),
    start.monthly_spending.length ? spending : element("p", "No recent counted spending.", "muted"),
    ...((start.recurring_bills || []).length ? [element("h3", "Recurring bills and subscriptions"), bills] : []),
    element("h3", "Investments"), invested.length ? investments : element("p", "No confirmed investment values.", "muted"),
    homeLink("Open Investments to add accounts or change growth rates", "#/investments"));
  forecastCategories = [...new Set([...start.monthly_spending.map(row => row.category), ...(start.recurring_bills || []).map(bill => bill.category)])];
  const options = document.getElementById("forecast-category-options") || Object.assign(document.createElement("datalist"), {id: "forecast-category-options"});
  options.replaceChildren(...forecastCategories.map(name => Object.assign(document.createElement("option"), {value: name})));
  document.body.append(options);
  const money = key => year => year.display[key];  // Exact text from the server; the browser never formats money.
  const charts = [
    ["Net worth", "net_worth", [["Net worth", money("end_net_worth")], ["In today's dollars", money("end_net_worth_today")]]],
    ["Income and spending", "cash_flow", [["Income", money("income")], ["Spending", money("spending")], ["Loan payments", money("loan_payments")], ["One-off", money("one_offs")],
      // Money drawn from investments to cash, after tax, and the part only required distributions took.
      ...(result.years.some(year => year.withdrawals) ? [["From investments", money("withdrawals")], ["Tax withheld", money("withdrawal_tax")], ["Required (RMD)", money("rmd")]] : []),
      // Pensions pay an income (before its tax); planned education costs and the part a 529 paid.
      ...(result.years.some(year => year.pension) ? [["Pension", money("pension")], ["Pension tax", money("pension_tax")]] : []),
      ...(result.years.some(year => year.education) ? [["Education", money("education")], ["Paid by the 529", money("education_from_529")]] : [])]],
    ["Cash, assets and loans", "balance_sheet", [["Cash", money("end_cash")], ["Assets", money("end_assets")], ["Loans owed", money("end_loans")]]]];
  $("forecast-charts").replaceChildren(...charts.map(([title, key, columns]) => {
    const card = element("section", "", "panel forecast-chart-card"), details = element("details");
    details.append(element("summary", "Show the numbers by year"), forecastTable(result, columns));
    card.append(element("h2", title), forecastSvg(result.charts[key]), details);
    return card;
  }));
}
async function loadForecast() {
  const load = ++forecastLoad;
  if (!$("asset-as-of").value) $("asset-as-of").value = todayIso();  // Local today: toISOString is UTC, a day ahead in the evening west of it.
  await loadAssets();
  const result = await api("/api/forecast", {method: "POST", body: JSON.stringify(forecastRequest())});
  if (load === forecastLoad) renderForecast(result);
}
$("forecast-form").addEventListener("submit", event => {
  event.preventDefault();
  loadForecast().catch(error => notice(error, true));
});
