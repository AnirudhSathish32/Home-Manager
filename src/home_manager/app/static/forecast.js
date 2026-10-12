"use strict";
// Forecast builders (forecast_v2.js draws the page): the server computes every number and draws every chart; these
// collect assumptions, list assets and shape the results. Charts arrive as escaped SVG and are parsed as XML.

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
// The field specs of each assumption list, on the page's "fc2-" inputs.
function forecastLists() {
  return {
    spending: ["fc2-forecast-spending-changes", [["category", "Category", {list: "fc2-forecast-category-options", required: ""}], ["percent", "Change (%)", {inputmode: "decimal", required: "", placeholder: "10"}]]],
    income: ["fc2-forecast-income-changes", [["month", "From month", {type: "month", required: ""}], ["monthly_amount", "Monthly change", {inputmode: "decimal", required: "", placeholder: "500.00"}]]],
    oneoff: ["fc2-forecast-one-offs", [["month", "Month", {type: "month", required: ""}], ["amount", "Amount", {inputmode: "decimal", required: "", placeholder: "-3000.00"}], ["label", "What it is", {maxlength: "80"}]]],
    edu: ["fc2-forecast-education", [["month", "Month", {type: "month", required: ""}], ["amount", "Cost", {inputmode: "decimal", required: "", placeholder: "12000.00"}], ["label", "What it is", {maxlength: "80"}]]],
  };
}

function forecastRequest() {
  const request = {years: Number($("fc2-forecast-years").value), inflation_percent: $("fc2-forecast-inflation").value.trim(),
                   income_growth_percent: $("fc2-forecast-income-growth").value.trim(), history_months: Number($("fc2-forecast-history").value),
                   spending_changes: forecastItems("fc2-forecast-spending-changes"), income_changes: forecastItems("fc2-forecast-income-changes"),
                   one_offs: forecastItems("fc2-forecast-one-offs").map(item => ({...item, label: item.label || ""})),
                   education_withdrawals: forecastItems("fc2-forecast-education").map(item => ({...item, label: item.label || ""}))};
  // A retirement plan is one self-contained input, so a scenario can change it without touching the rest.
  if ($("fc2-retire-plan").checked) {
    const fixed = $("fc2-retire-mode").value === "fixed";
    request.retirement = {start_month: $("fc2-retire-month").value, mode: $("fc2-retire-mode").value, tax_percent: $("fc2-retire-tax").value.trim() || "0",
                          ...(fixed ? {monthly_amount: $("fc2-retire-amount").value.trim()} : {cash_floor: $("fc2-retire-floor").value.trim() || "0"})};
  }
  return request;
}
function showRetirementFields() {
  const on = $("fc2-retire-plan").checked, fixed = $("fc2-retire-mode").value === "fixed";
  $("fc2-retire-fields").hidden = !on;
  $("fc2-retire-month").required = on;
  $("fc2-retire-amount-field").hidden = !fixed; $("fc2-retire-amount").required = on && fixed;
  $("fc2-retire-floor-field").hidden = fixed;
}

// Investment accounts have their own page (investments_v2.js) and join the forecast from there.
const ASSET_KINDS = {vehicle: "Vehicle", real_estate: "Home or property", other_asset: "Other asset", loan: "Loan"};
async function loadAssets() {
  const assets = await api("/api/assets"), body = $("fc2-asset-rows");
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
      try { await api(`/api/assets/${asset.id}`, {method: "DELETE"}); await fc2Reload(); } catch (error) { notice(error, true); }
    });
    td.append(remove);
  }
}
// The listeners on the inputs: "Add …" rows, retirement fields and the asset form.
function wireForecast() {
  const lists = forecastLists();
  for (const [button, key] of [["add-spending-change", "spending"], ["add-income-change", "income"], ["add-one-off", "oneoff"], ["add-education", "edu"]]) {
    $("fc2-" + button).addEventListener("click", () => forecastRow(...lists[key]));
  }
  $("fc2-retire-plan").addEventListener("change", showRetirementFields);
  $("fc2-retire-mode").addEventListener("change", showRetirementFields);
  $("fc2-asset-kind").addEventListener("change", () => {
    const loan = $("fc2-asset-kind").value === "loan";
    $("fc2-asset-payment").disabled = !loan; if (!loan) $("fc2-asset-payment").value = "";
    $("fc2-asset-rate").placeholder = loan ? "Interest, e.g. 6.5" : $("fc2-asset-kind").value === "vehicle" ? "Car: -15 if blank" : "0 if blank";
  });
  $("fc2-asset-form").addEventListener("submit", async event => {
    event.preventDefault();
    const body = {name: $("fc2-asset-name").value.trim(), kind: $("fc2-asset-kind").value, value: $("fc2-asset-value").value.trim(),
                  currency: $("fc2-asset-currency").value.trim().toUpperCase(), as_of: $("fc2-asset-as-of").value};
    if ($("fc2-asset-rate").value.trim()) body.annual_rate_percent = $("fc2-asset-rate").value.trim();
    if ($("fc2-asset-payment").value.trim()) body.monthly_payment = $("fc2-asset-payment").value.trim();
    try {
      await api("/api/assets", {method: "POST", body: JSON.stringify(body)});
      for (const id of ["asset-name", "asset-value", "asset-rate", "asset-payment"]) $("fc2-" + id).value = "";
      notice(`${body.name} added.`); await fc2Reload();
    } catch (error) { notice(error, true); }
  });
}

function forecastSvg(markup) {
  // Server-built, escaped SVG. Parsed as XML and imported: nothing in it can run.
  const parsed = new DOMParser().parseFromString(markup, "image/svg+xml").documentElement;
  if (parsed.nodeName !== "svg") throw new Error("A chart could not be drawn.");
  return document.importNode(parsed, true);
}
// columns: [label, key] pairs into each year's display text. money(year, key) draws one cell; the page passes one that
// makes traced columns into figures.
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
// The Starting point block's nodes. label shows a category name (the page passes categoryLabel).
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
// The categories a spending change can name, as a datalist.
function forecastCategoryOptions(result) {
  const start = result.starting_point, id = "fc2-forecast-category-options";
  const categories = new Set([...start.monthly_spending.map(row => row.category), ...(start.recurring_bills || []).map(bill => bill.category)]);
  const options = document.getElementById(id) || Object.assign(document.createElement("datalist"), {id});
  options.replaceChildren(...[...categories].map(name => Object.assign(document.createElement("option"), {value: name})));
  document.body.append(options);
}
