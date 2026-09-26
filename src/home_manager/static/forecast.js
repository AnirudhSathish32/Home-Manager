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

function forecastRequest() {
  return {years: Number($("forecast-years").value), inflation_percent: $("forecast-inflation").value.trim(),
          income_growth_percent: $("forecast-income-growth").value.trim(), history_months: Number($("forecast-history").value),
          spending_changes: forecastItems("forecast-spending-changes"), income_changes: forecastItems("forecast-income-changes"),
          one_offs: forecastItems("forecast-one-offs").map(item => ({...item, label: item.label || ""}))};
}

const ASSET_KINDS = {vehicle: "Vehicle", real_estate: "Home or property", investment: "Investment", retirement: "Retirement account",
                     bond: "Bond", other_asset: "Other asset", loan: "Loan"};
async function loadAssets() {
  const assets = await api("/api/assets"), body = $("asset-rows");
  body.replaceChildren();
  if (!assets.length) {
    const row = body.insertRow(), td = row.insertCell(); td.colSpan = 8;
    td.append(element("span", "No assets or loans yet. Add a car or home below; investment and loan statements add theirs after review.", "muted"));
  }
  for (const asset of assets) {
    const row = body.insertRow();
    cell(row, asset.name); cell(row, ASSET_KINDS[asset.kind] || asset.kind);
    cell(row, asset.value.display).className = "numeric"; cell(row, asset.as_of);
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
    for (const [, value] of columns) cell(row, value(year)).className = "numeric";
  }
  wrap.append(table); return wrap;
}
function renderForecast(result) {
  const alerts = $("forecast-alerts"); alerts.replaceChildren();
  if (result.first_month_cash_below_zero) alerts.append(alertBox(`Cash is projected to fall below zero in ${result.first_month_cash_below_zero}.`, {tone: "warning"}));
  if (result.notes.length) {
    const list = element("ul", "", "forecast-notes"); for (const note of result.notes) list.append(element("li", note));
    const box = alertBox("About these numbers", {tone: "info"}); box.querySelector(".alert-body").append(list); alerts.append(box);
  }
  const start = result.starting_point, facts = element("dl", "", "forecast-facts");
  const history = result.assumptions.history;
  for (const [label, value] of [["Cash in accounts", start.cash.display], ["Monthly income", start.monthly_income.display],
      ["Averaged over", `${history.start} to ${history.end}`], ["Inflation", `${result.assumptions.inflation_percent}% a year`],
      ["Income growth", `${result.assumptions.income_growth_percent}% a year`]]) facts.append(element("dt", label), element("dd", value));
  const spending = element("ul", "", "forecast-notes");
  for (const row of start.monthly_spending) spending.append(element("li", `${row.category}: ${row.amount.display} a month`));
  $("forecast-start").replaceChildren(facts, element("h3", "Monthly spending by category"),
    start.monthly_spending.length ? spending : element("p", "No recent counted spending.", "muted"));
  forecastCategories = start.monthly_spending.map(row => row.category);
  const options = document.getElementById("forecast-category-options") || Object.assign(document.createElement("datalist"), {id: "forecast-category-options"});
  options.replaceChildren(...forecastCategories.map(name => Object.assign(document.createElement("option"), {value: name})));
  document.body.append(options);
  const money = key => year => year.display[key];  // Exact text from the server; the browser never formats money.
  const charts = [
    ["Net worth", "net_worth", [["Net worth", money("end_net_worth")], ["In today's dollars", money("end_net_worth_today")]]],
    ["Income and spending", "cash_flow", [["Income", money("income")], ["Spending", money("spending")], ["Loan payments", money("loan_payments")], ["One-off", money("one_offs")]]],
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
  if (!$("asset-as-of").value) $("asset-as-of").value = new Date().toISOString().slice(0, 10);
  await loadAssets();
  const result = await api("/api/forecast", {method: "POST", body: JSON.stringify(forecastRequest())});
  if (load === forecastLoad) renderForecast(result);
}
$("forecast-form").addEventListener("submit", event => {
  event.preventDefault();
  loadForecast().catch(error => notice(error, true));
});
