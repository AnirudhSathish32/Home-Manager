"use strict";
// What If (docs/what-if.md): the paycheck planner. The server works out every line from gross to net
// (finance/paycheck.py); this page only collects the inputs and shows the server's exact text.
const PLAN_STATES = {AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware",
  DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
  MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island",
  SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington",
  WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming"};
const PLAN_CATEGORIES = {
  earnings: {overtime: "Overtime", bonus: "Bonus", commission: "Commission", other_earnings: "Other earnings"},
  pre_tax: {retirement_pretax: "401(k)", hsa: "HSA", fsa: "FSA", health: "Health insurance", dental: "Dental insurance", vision: "Vision insurance", other: "Other"},
  post_tax: {retirement_roth: "Roth 401(k)", life_insurance: "Life insurance", other: "Other"},
  employer: {hsa: "HSA", retirement_pretax: "401(k)", health: "Health insurance", dental: "Dental insurance", vision: "Vision insurance",
             life_insurance: "Life insurance", other: "Other"}};
let planTimer = 0, planLoad = 0, planRowId = 0, planReady = false;

function planSelect(id, options, value = "") {
  const select = document.createElement("select"); select.id = id;
  for (const [key, label] of Object.entries(options)) select.append(Object.assign(document.createElement("option"), {value: key, textContent: label}));
  if (value) select.value = value;
  return select;
}
function planRow(list, line = {}) {
  // One deduction or earnings line: what it is, a name, and an amount per paycheck or a percent of gross pay.
  const row = element("div", "", "forecast-row forecast-item plan-line"), id = ++planRowId;
  const category = planSelect(`${list}-category-${id}`, PLAN_CATEGORIES[list], line.category);
  const label = forecastInput(`${list}-label-${id}`, {maxlength: "60", placeholder: "Optional"}); label.value = line.label || "";
  const kind = planSelect(`${list}-kind-${id}`, list === "earnings" ? {amount: "$ a check"} : {amount: "$ a check", percent: "% of gross"},
    line.percent != null ? "percent" : "amount");
  const value = forecastInput(`${list}-value-${id}`, {inputmode: "decimal", required: ""}); value.value = line.percent ?? line.amount ?? "";
  category.dataset.key = "category"; label.dataset.key = "label"; kind.dataset.key = "kind"; value.dataset.key = "value";
  row.append(forecastField("What", category), forecastField("Name", label), forecastField("As", kind), forecastField("Amount", value));
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => { row.remove(); schedulePaycheck(); });
  row.append(remove); $(`plan-${list}`).append(row);
  return row;
}
function planLines(list) {
  return [...$(`plan-${list}`).querySelectorAll(".plan-line")].map(row => {
    const read = key => row.querySelector(`[data-key="${key}"]`).value.trim();
    return {category: read("category"), label: read("label"), [read("kind")]: read("value")};
  }).filter(line => (line.amount ?? line.percent) !== "");
}
for (const list of Object.keys(PLAN_CATEGORIES)) {
  $(`add-plan-${list}`).addEventListener("click", () => planRow(list).querySelector("select").focus());
}
const MONTH_OPTIONS = Object.fromEntries(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
  .map((name, index) => [String(index + 1), name]));
function bonusRow(bonus = {}) {
  // A bonus: a name, the amount, and the month it's paid (with that month's first paycheck).
  const row = element("div", "", "forecast-row forecast-item plan-bonus"), id = ++planRowId;
  const label = forecastInput(`bonus-label-${id}`, {maxlength: "60", placeholder: "Year-end bonus"}); label.value = bonus.label || "";
  const value = forecastInput(`bonus-amount-${id}`, {inputmode: "decimal", required: ""}); value.value = bonus.amount || "";
  const month = planSelect(`bonus-month-${id}`, MONTH_OPTIONS, String(bonus.month || 12));
  label.dataset.key = "label"; value.dataset.key = "amount"; month.dataset.key = "month";
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => { row.remove(); schedulePaycheck(); });
  row.append(forecastField("Name", label), forecastField("Amount", value), forecastField("Paid in", month), remove);
  $("plan-bonuses").append(row);
  return row;
}
$("add-plan-bonus").addEventListener("click", () => bonusRow().querySelector("input").focus());
function planBonuses() {
  return [...$("plan-bonuses").querySelectorAll(".plan-bonus")].map(row => {
    const read = key => row.querySelector(`[data-key="${key}"]`).value.trim();
    return {label: read("label"), amount: read("amount"), month: Number(read("month"))};
  }).filter(bonus => bonus.amount !== "");
}

function planText(id) { const value = $(id).value.trim(); return value === "" ? null : value; }
function paycheckRequest() {
  const pay = planText("plan-pay"), local = $("plan-local-kind").value;
  const request = {
    year: Number($("plan-year").value), filing_status: $("plan-status").value, work_state: $("plan-state").value || null,
    pay_frequency: Number($("plan-frequency").value),
    annual_salary: $("plan-pay-kind").value === "annual" ? pay : null, gross_per_check: $("plan-pay-kind").value === "check" ? pay : null,
    earnings: planLines("earnings"), pre_tax: planLines("pre_tax"), post_tax: planLines("post_tax"), employer: planLines("employer"),
    match_percent: planText("plan-match"), match_limit_percent: planText("plan-match-limit"),
    federal_deduction: planText("plan-fed-deduction"), federal_credits: planText("plan-fed-credits") || "0",
    federal_other_income: planText("plan-fed-other-income") || "0", federal_deductions: planText("plan-fed-deductions") || "0",
    federal_extra_withholding: planText("plan-fed-extra") || "0", federal_step2: $("plan-fed-step2").checked, bonuses: planBonuses(),
    state_deduction: planText("plan-state-deduction"), state_rate_percent: planText("plan-state-rate"),
    state_extra_withholding: planText("plan-state-extra") || "0", state_credits: planText("plan-state-credits") || "0",
    state_supplemental_percent: planText("plan-state-supplemental"),
    state_disability_percent: planText("plan-sdi"), state_disability_wage_limit: planText("plan-sdi-limit"),
    local_tax_percent: local === "percent" ? planText("plan-local-value") : null, local_tax_amount: local === "amount" ? planText("plan-local-value") : null,
    local_tax_wages: $("plan-local-wages").value};
  return request;
}
function fillPaycheck(value) {
  // A planner input (from a pay stub or a saved plan): every field, then the lines, so updating it keeps what it had.
  $("plan-year").value = value.year; $("plan-status").value = value.filing_status; $("plan-state").value = value.work_state || "";
  $("plan-frequency").value = String(value.pay_frequency);
  $("plan-pay-kind").value = value.annual_salary != null ? "annual" : "check"; $("plan-pay").value = value.annual_salary ?? value.gross_per_check ?? "";
  const zero = text => text == null || text === "0" ? "" : text;  // Zero defaults show as the placeholder.
  for (const [id, key, blankIsZero] of [["plan-match", "match_percent"], ["plan-match-limit", "match_limit_percent"], ["plan-fed-deduction", "federal_deduction"],
      ["plan-fed-credits", "federal_credits", true], ["plan-fed-other-income", "federal_other_income", true], ["plan-fed-deductions", "federal_deductions", true],
      ["plan-fed-extra", "federal_extra_withholding", true], ["plan-state-deduction", "state_deduction"], ["plan-state-rate", "state_rate_percent"],
      ["plan-state-extra", "state_extra_withholding", true], ["plan-state-credits", "state_credits", true], ["plan-state-supplemental", "state_supplemental_percent"],
      ["plan-sdi", "state_disability_percent"], ["plan-sdi-limit", "state_disability_wage_limit"]])
    $(id).value = blankIsZero ? zero(value[key]) : value[key] ?? "";
  $("plan-fed-step2").checked = Boolean(value.federal_step2);
  $("plan-local-kind").value = value.local_tax_percent != null ? "percent" : value.local_tax_amount != null ? "amount" : "none";
  $("plan-local-value").value = value.local_tax_percent ?? value.local_tax_amount ?? "";
  $("plan-local-wages").value = value.local_tax_wages || "taxable";
  $("plan-local-kind").dispatchEvent(new Event("change"));
  for (const list of Object.keys(PLAN_CATEGORIES)) {
    $(`plan-${list}`).replaceChildren();
    for (const line of value[list] || []) planRow(list, line);
  }
  $("plan-bonuses").replaceChildren();
  for (const bonus of value.bonuses || []) bonusRow(bonus);
}

const planRate = points => points == null ? "—" : `${(points / 100).toFixed(2).replace(/\.?0+$/, "")}%`;
function planTableRow(body, label, how, perCheck, perYear, className = "") {
  const tr = body.insertRow(); if (className) tr.className = className;
  const th = tr.appendChild(element("th", label)); th.scope = "row";
  if (how) th.appendChild(element("small", how, "muted block"));
  for (const value of [perCheck, perYear]) tr.appendChild(element("td", "", "numeric")).appendChild(amount(value || "—", {signed: false}));
}
function paycheckTable(result) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "ledger-rows paystub-table");
  const head = table.createTHead().insertRow();
  for (const [title, numeric] of [["", false], ["Per paycheck", true], ["Per year", true]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const byGroup = Object.fromEntries(result.groups.map(group => [group.group, group]));
  const total = (body, group, label) => planTableRow(body, label, "", group.display.per_check_minor, group.display.annual_minor, "paystub-subtotal");
  for (const group of result.groups) {
    const body = table.appendChild(document.createElement("tbody"));
    const title = body.insertRow().appendChild(element("th", group.title, "paystub-group")); title.colSpan = 3; title.scope = "rowgroup";
    for (const line of group.lines) planTableRow(body, line.label, line.how, line.display.per_check_minor, line.display.annual_minor);
    if (group.group === "tax" && !group.lines.length) body.insertRow().appendChild(element("td", "No taxes can be worked out until the federal table is confirmed.", "muted")).colSpan = 3;
    if (group.group === "earnings") planTableRow(body, "Gross pay", "", group.display.per_check_minor, group.display.annual_minor, "paystub-total");
    if (group.group === "pre_tax") {
      total(body, group, "Total pre-tax deductions");
      const wages = result.wages;
      planTableRow(body, "Wages for income tax", "Gross pay less every pre-tax deduction", wages.income_tax.display.per_check_minor, wages.income_tax.display.annual_minor, "paystub-subtotal");
      planTableRow(body, "Wages for Social Security and Medicare", "Gross pay less health, dental, vision, HSA and FSA; a 401(k) doesn't lower these",
        wages.fica.display.per_check_minor, wages.fica.display.annual_minor, "paystub-subtotal");
    }
    if (group.group === "tax") {
      if (group.fica) planTableRow(body, "FICA (Social Security + Medicare)", "", group.fica.display.per_check_minor, group.fica.display.annual_minor, "paystub-subtotal");
      total(body, group, "Total taxes");
    }
    if (group.group === "post_tax") total(body, group, "Total post-tax deductions");
    if (group.group === (byGroup.post_tax ? "post_tax" : "tax"))
      planTableRow(body, "Net pay", result.schedule.length > 1 ? "The first paycheck; see the schedule for the ones that differ" : "",
        result.net.display.per_check_minor, result.net.display.annual_minor, "paystub-total");
    if (group.group === "employer_paid") total(body, group, "Total paid by your employer");
  }
  wrap.appendChild(table); return wrap;
}
function paycheckSchedule(result) {
  const section = element("section", "", "paystub-taxes");
  section.append(element("h3", "Paychecks through the year"),
    element("p", "A bonus rides with its month's first paycheck, and Social Security stops at its yearly wage limit (state disability insurance at its own), so some paychecks differ.", "muted small"));
  const keys = [["bonus_minor", "Bonus"], ["social_security_minor", "Social Security"], ["medicare_minor", "Medicare"], ["state_disability_minor", "State disability"]]
    .filter(([key]) => result.schedule.some(part => key in part));
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  for (const [title, numeric] of [["Paychecks", false], ...keys.map(([, name]) => [name, true]), ["Net pay", true]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const body = table.createTBody();
  for (const part of result.schedule) {
    const tr = body.insertRow();
    cell(tr, part.from_check === part.to_check ? `Paycheck ${part.from_check}` : `Paychecks ${part.from_check} to ${part.to_check}`);
    for (const [key] of [...keys, ["net_minor"]]) tr.appendChild(element("td", "", "numeric")).appendChild(amount(part.display[key], {signed: false}));
  }
  wrap.appendChild(table); section.appendChild(wrap); return section;
}
function paycheckJurisdictions(result) {
  const section = element("section", "", "paystub-taxes");
  section.appendChild(element("h3", "How the income taxes are figured"));
  section.appendChild(element("p", `Tax year ${result.year} · filing ${result.filing_status_name} · ${result.paychecks} paychecks a year (${result.frequency_name}).`, "muted small"));
  for (const part of result.jurisdictions) {
    const block = element("div", "", "tax-jurisdiction");
    block.appendChild(element("h4", `${part.name} income tax`));
    if (part.status !== "verified") {
      block.appendChild(element("p", part.message, "muted"));
      if (part.status === "missing") block.appendChild(actionButton(`Look up the ${result.year} ${part.name} table`, () =>
        api("/api/tax-tables/lookup", {method: "POST", body: JSON.stringify({jurisdiction: part.jurisdiction, year: result.year, filing_status: result.filing_status})})
          .then(() => notice("Looking it up. The table will wait for you in Review."))));
      if (part.status === "proposed") block.appendChild(homeLink("Review the table", "#/review"));
      if (part.jurisdiction !== "US") block.appendChild(element("p", "Or enter the state's flat rate under State to work it out now.", "muted small"));
      section.appendChild(block); continue;
    }
    const d = part.display;
    const whose = part.source === "typed" ? "the deduction you entered" : part.deduction_overridden ? `the deduction you entered (the table's is ${d.table_deduction_minor})` : `the ${result.year} standard deduction`;
    block.appendChild(element("p", `${d.period_wages_minor} a paycheck is ${d.annual_wages_minor} a year${part.other_income_minor ? `, with ${d.other_income_minor} of other income` : ""}. `
      + `The first ${d.standard_deduction_minor} (${whose}) isn't taxed${part.extra_deductions_minor ? `, nor the next ${d.extra_deductions_minor} of W-4 deductions` : ""}; `
      + `each bucket above it is taxed only at its own rate.`));
    if (part.chart_svg) { const figure = element("figure", "", "tax-chart"); figure.appendChild(forecastSvg(part.chart_svg)); block.appendChild(figure); }
    const details = element("details"), wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
    const head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Bucket", false], ["Wages a year", true], ["Tax a year", true], ["Tax a paycheck", true]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
    const body = table.createTBody();
    for (const bucket of part.buckets) {
      const tr = body.insertRow(), th = tr.appendChild(element("th", bucket.label)); th.scope = "row";
      th.appendChild(element("small", bucket.display.to_minor ? `wages ${bucket.display.from_minor} to ${bucket.display.to_minor}` : `wages over ${bucket.display.from_minor}`, "muted block"));
      for (const key of ["income_minor", "tax_minor", "per_paycheck_tax_minor"]) tr.appendChild(element("td", "", "numeric")).appendChild(amount(bucket.display[key], {signed: false}));
    }
    wrap.appendChild(table); details.append(element("summary", "Show every bucket"), wrap); block.appendChild(details);
    block.appendChild(element("p", `A year's tax: ${d.annual_tax_minor}${part.credits_minor ? ` after ${d.credits_minor} of credits` : ""} (${planRate(part.effective_rate_bp)} of wages; `
      + `top bucket ${planRate(part.top_rate_bp)}). Each paycheck: ${d.estimate_minor}${part.extra_withholding_minor ? ` plus ${d.extra_withholding_minor} extra withholding` : ""}.`));
    section.appendChild(block);
  }
  return section;
}
function taxTimeText(zen, lead) {
  // Tax Zen for a paycheck or a plan (finance/tax_zen.py): where the year ends, and the W-4 entry that brings it to $0.
  if (zen.zen) return `${lead}, you'd be Tax Zen in ${zen.year}: within a dollar of $0 at tax time.`;
  const where = zen.result_minor > 0 ? `a refund of ${zen.display.result_minor}` : `owing ${zen.display.result_minor}`;
  const fix = zen.w4?.amount != null ? ` To reach $0, put ${zen.w4.display.amount} in W-4 Step ${zen.w4.field === "4(a)" ? "4(a), other income" : "4(b), deductions"}`
    + `${zen.job ? ` for ${zen.job}` : ""}.` : zen.w4?.unreachable ? " No W-4 entry can bring it to $0." : "";
  return `${lead}, ${zen.year}'s return ends at ${where}.${fix}`;
}
function renderPaycheck(result) {
  const target = $("paycheck-result");
  const headline = element("dl", "", "plan-headline");
  for (const [label, value, big] of [["Take-home pay", result.net.display.per_check_minor, true], ["A month, on average", result.net.display.monthly_minor],
      ["A year", result.net.display.annual_minor]]) {
    const dd = element("dd", "", big ? "plan-figure" : ""); dd.appendChild(amount(value, {signed: false}));
    headline.append(element("dt", label), dd);
  }
  const rates = element("p", `Taxes take ${planRate(result.rates.total_tax_bp)} of gross pay; you keep ${planRate(result.rates.take_home_bp)}.`
    + (result.rates.federal_marginal_bp != null ? ` Top federal bucket ${planRate(result.rates.federal_marginal_bp)}` : "")
    + (result.rates.state_marginal_bp != null ? `, top ${result.state_name} bucket ${planRate(result.rates.state_marginal_bp)}.` : result.rates.federal_marginal_bp != null ? "." : ""), "muted small");
  const parts = [element("h2", "From gross pay to net pay"), headline, rates];
  const taxTime = result.tax_time;
  if (taxTime?.ready) parts.push(element("p", taxTimeText(taxTime, "With this paycheck alone for a full year"), "small"));
  if (!result.complete) parts.push(alertBox("Some tax tables are missing, so taxes are left out and take-home pay is too high. See below.", {tone: "warning"}));
  parts.push(paycheckTable(result));
  if (result.schedule.length > 1) parts.push(paycheckSchedule(result));
  parts.push(paycheckJurisdictions(result));
  if (result.notes.length) {
    const list = element("ul", "", "forecast-notes"); for (const note of result.notes) list.append(element("li", note));
    parts.push(element("h3", "About these numbers"), list);
  }
  target.replaceChildren(...parts);
  // The table's deductions show where yours would replace them.
  for (const [id, part] of [["plan-fed-deduction", result.jurisdictions.find(part => part.jurisdiction === "US")],
                            ["plan-state-deduction", result.jurisdictions.find(part => part.jurisdiction === result.state)]])
    $(id).placeholder = part?.display?.table_deduction_minor ? `Table: ${part.display.table_deduction_minor}` : "";
}
async function runPaycheck() {
  if (!planText("plan-pay")) {
    $("paycheck-result").replaceChildren(element("h2", "From gross pay to net pay"), emptyState("Enter a salary or the gross pay per paycheck to see every line from gross to net."));
    return;
  }
  const load = ++planLoad;
  try {
    const result = await api("/api/paycheck", {method: "POST", body: JSON.stringify(paycheckRequest())});
    if (load === planLoad) { renderPaycheck(result); $("paycheck-error").replaceChildren(); }
  } catch (error) {
    if (load === planLoad) $("paycheck-error").replaceChildren(alertBox(error.message, {tone: "error"}));
  }
}
function schedulePaycheck() { clearTimeout(planTimer); planTimer = setTimeout(runPaycheck, 400); }
$("paycheck-form").addEventListener("input", schedulePaycheck);
$("paycheck-form").addEventListener("change", schedulePaycheck);
$("paycheck-form").addEventListener("submit", event => { event.preventDefault(); clearTimeout(planTimer); runPaycheck(); });
$("plan-local-kind").addEventListener("change", () => {
  const kind = $("plan-local-kind").value;
  $("plan-local-value-field").hidden = kind === "none"; $("plan-local-wages-field").hidden = kind !== "percent";
  $("plan-local-value").previousElementSibling.textContent = kind === "amount" ? "Local tax per paycheck" : "Local tax rate (%)";
});

// Plans (finance/scenarios.py): saved inputs only; every comparison is worked out again by the server.
const BASIS_NAMES = {profile: "My records", family: "The family's records", blank: "A blank slate"};
let scenarioView = {scenarios: [], accounts: [], bases: ["profile", "blank"], family: false};
let scenarioId = null, scenarioPaychecks = [], editingPaycheck = null;

function nextMonth() {
  // Local calendar month, not UTC (toISOString would give the month before east of UTC).
  const today = new Date(), next = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
}
function scenarioRow(list, fields, values = {}) {
  // Like the Forecast page's rows (forecastItems reads both), filled from a saved plan without moving focus.
  const row = element("div", "", "forecast-row forecast-item"), id = ++forecastRowId;
  for (const [key, label, attributes] of fields) {
    const input = forecastInput(`${list}-${key}-${id}`, attributes);
    input.dataset.key = key; if (values[key] != null) input.value = values[key];
    row.append(forecastField(label, input));
  }
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => row.remove());
  row.append(remove); $(list).append(row);
  return row;
}
const SCENARIO_LISTS = {
  "scenario-amounts": [["category", "Category", {list: "forecast-category-options", required: ""}], ["monthly_amount", "A month, today's $", {inputmode: "decimal", required: "", placeholder: "2100.00"}],
                       ["from_month", "From month", {type: "month", required: ""}]],
  "scenario-changes": [["category", "Category", {list: "forecast-category-options", required: ""}], ["percent", "Change (%)", {inputmode: "decimal", required: "", placeholder: "-20"}]],
  "scenario-one-offs": [["month", "Month", {type: "month", required: ""}], ["amount", "Amount", {inputmode: "decimal", required: "", placeholder: "-3000.00"}], ["label", "What it is", {maxlength: "80"}]]};
$("add-scenario-amount").addEventListener("click", () => scenarioRow("scenario-amounts", SCENARIO_LISTS["scenario-amounts"], {from_month: nextMonth()}).querySelector("input").focus());
$("add-scenario-change").addEventListener("click", () => scenarioRow("scenario-changes", SCENARIO_LISTS["scenario-changes"]).querySelector("input").focus());
$("add-scenario-one-off").addEventListener("click", () => scenarioRow("scenario-one-offs", SCENARIO_LISTS["scenario-one-offs"]).querySelector("input").focus());

function accountOptions(select, treatments, chosen) {
  select.replaceChildren(Object.assign(document.createElement("option"), {value: "", textContent: "A new planned account"}));
  for (const account of scenarioView.accounts.filter(account => treatments.includes(account.tax_treatment)))
    select.append(Object.assign(document.createElement("option"), {value: String(account.id), textContent: `${account.name} (${account.kind_label})`}));
  select.value = chosen == null ? "" : String(chosen);
}
function paycheckSummary(paycheck) {
  const pay = paycheck.annual_salary != null ? `${paycheck.annual_salary} a year` : `${paycheck.gross_per_check} a paycheck`;
  return `${pay} · ${paycheck.work_state ? PLAN_STATES[paycheck.work_state] : "no state tax"} · ${paycheck.pre_tax.length} pre-tax, ${paycheck.post_tax.length} post-tax lines · tax year ${paycheck.year}`;
}
function renderScenarioPaychecks() {
  const list = $("scenario-paychecks"); list.replaceChildren();
  scenarioPaychecks.forEach((plan, index) => {
    const row = element("div", "", "scenario-paycheck"), id = `plan-${index}`;
    const fields = element("div", "", "forecast-row");
    const text = (key, label, attributes = {}) => { const input = forecastInput(`${id}-${key}`, attributes); input.value = plan[key] ?? ""; input.addEventListener("input", () => { plan[key] = input.value.trim() || null; }); return forecastField(label, input); };
    const mode = planSelect(`${id}-mode`, {replace_pay: "Replaces pay", add: "Adds to income"}, plan.mode);
    mode.addEventListener("change", () => { plan.mode = mode.value; });
    fields.append(text("label", "Name", {maxlength: "60", required: ""}), text("from_month", "From month", {type: "month", required: ""}),
      text("to_month", "Last month (optional)", {type: "month"}), forecastField("This paycheck", mode));
    if (!scenarioView.family) {
      const retirement = document.createElement("select"), hsa = document.createElement("select");
      retirement.id = `${id}-retirement`; hsa.id = `${id}-hsa`;
      accountOptions(retirement, ["tax_deferred", "tax_free"], plan.retirement_account_id); accountOptions(hsa, ["hsa"], plan.hsa_account_id);
      retirement.addEventListener("change", () => { plan.retirement_account_id = retirement.value ? Number(retirement.value) : null; });
      hsa.addEventListener("change", () => { plan.hsa_account_id = hsa.value ? Number(hsa.value) : null; });
      fields.append(forecastField("401(k) goes into", retirement), forecastField("HSA goes into", hsa));
    }
    const actions = element("div", "", "button-row");
    const open = element("button", editingPaycheck === index ? "Open in the planner below" : "Open in planner", "quiet"); open.type = "button";
    open.addEventListener("click", () => {
      editingPaycheck = index; fillPaycheck(plan.paycheck); planButtons(); renderScenarioPaychecks(); runPaycheck();
      $("paycheck-form").scrollIntoView({block: "start"}); $("plan-pay").focus();
    });
    const remove = element("button", "Remove", "quiet"); remove.type = "button";
    remove.addEventListener("click", () => {
      scenarioPaychecks.splice(index, 1); if (editingPaycheck === index) editingPaycheck = null; else if (editingPaycheck > index) editingPaycheck--;
      planButtons(); renderScenarioPaychecks();
    });
    actions.append(open, remove);
    row.append(fields, element("p", paycheckSummary(plan.paycheck), "muted small"), actions);
    list.append(row);
  });
  if (!scenarioPaychecks.length) list.append(element("p", "No paychecks in this plan yet: income stays as recorded.", "muted small"));
}
function planButtons() {
  // The planner adds a new paycheck to the plan, or updates the one opened from it.
  $("paycheck-to-plan").textContent = editingPaycheck == null ? "Add to plan" : `Update “${scenarioPaychecks[editingPaycheck].label}” in the plan`;
}
$("paycheck-to-plan").addEventListener("click", () => {
  if (!planText("plan-pay")) { notice("Enter the pay first.", true); return; }
  const paycheck = paycheckRequest();
  if (editingPaycheck != null) {
    scenarioPaychecks[editingPaycheck].paycheck = paycheck;
    notice(`${scenarioPaychecks[editingPaycheck].label} updated in the plan. Save the plan to keep it.`);
  } else {
    scenarioPaychecks.push({label: `Paycheck ${scenarioPaychecks.length + 1}`, paycheck, from_month: nextMonth(), to_month: null, mode: "replace_pay",
                            retirement_account_id: null, hsa_account_id: null, contribution_growth_percent: "0"});
    editingPaycheck = scenarioPaychecks.length - 1;
    notice("Added to the plan. Name it and choose its months above, then save the plan.");
  }
  planButtons(); renderScenarioPaychecks();
  $("scenario-paychecks").scrollIntoView({block: "center"});
});

function showScenarioRetirement() {
  const on = $("scenario-retire").checked, fixed = $("scenario-retire-mode").value === "fixed";
  $("scenario-retire-fields").hidden = !on;
  $("scenario-retire-amount-field").hidden = !fixed; $("scenario-retire-floor-field").hidden = fixed;
}
$("scenario-retire").addEventListener("change", showScenarioRetirement);
$("scenario-retire-mode").addEventListener("change", showScenarioRetirement);
function scenarioRetirement() {
  // The same self-contained retirement input as the Forecast page (forecast.js forecastRequest).
  if (!$("scenario-retire").checked) return null;
  const fixed = $("scenario-retire-mode").value === "fixed";
  return {start_month: $("scenario-retire-month").value, mode: $("scenario-retire-mode").value, tax_percent: planText("scenario-retire-tax") || "0",
          ...(fixed ? {monthly_amount: planText("scenario-retire-amount")} : {cash_floor: planText("scenario-retire-floor") || "0"})};
}
function fillScenarioRetirement(plan) {
  $("scenario-retire").checked = Boolean(plan);
  $("scenario-retire-month").value = plan?.start_month || ""; $("scenario-retire-mode").value = plan?.mode || "shortfall";
  $("scenario-retire-amount").value = plan?.monthly_amount || ""; $("scenario-retire-floor").value = plan?.cash_floor ?? "0";
  $("scenario-retire-tax").value = plan?.tax_percent ?? "0";
  showScenarioRetirement();
}
function scenarioRequest() {
  const basis = $("scenario-basis").value;
  return {name: $("scenario-name").value.trim(), basis, starting_cash: basis === "blank" ? (planText("scenario-cash") || "0") : "0",
          paychecks: scenarioPaychecks.map(plan => ({...plan, label: (plan.label || "").trim() || "Paycheck", to_month: plan.to_month || null})),
          forecast: {years: Number($("scenario-years").value) || 10, inflation_percent: planText("scenario-inflation") || "0",
                     income_growth_percent: planText("scenario-income-growth") || "0",
                     category_amounts: forecastItems("scenario-amounts"), spending_changes: forecastItems("scenario-changes"),
                     one_offs: forecastItems("scenario-one-offs").map(item => ({...item, label: item.label || ""})),
                     retirement: scenarioRetirement(),
                     cut_subscriptions_from: $("scenario-cut-subscriptions").checked ? $("scenario-cut-month").value || null : null}};
}
$("scenario-cut-subscriptions").addEventListener("change", () => { $("scenario-cut-fields").hidden = !$("scenario-cut-subscriptions").checked; });
function fillScenario(scenario) {
  const inputs = scenario?.inputs || {name: "", basis: scenarioView.bases[0], starting_cash: "0", paychecks: [], forecast: {}};
  scenarioId = scenario?.id ?? null;
  $("scenario-name").value = inputs.name; $("scenario-basis").value = inputs.basis; $("scenario-cash").value = inputs.starting_cash;
  const forecast = inputs.forecast || {};
  $("scenario-years").value = forecast.years ?? 10; $("scenario-inflation").value = forecast.inflation_percent ?? "2"; $("scenario-income-growth").value = forecast.income_growth_percent ?? "0";
  for (const [list, key] of [["scenario-amounts", "category_amounts"], ["scenario-changes", "spending_changes"], ["scenario-one-offs", "one_offs"]]) {
    $(list).replaceChildren();
    for (const item of forecast[key] || []) scenarioRow(list, SCENARIO_LISTS[list], item);
  }
  fillScenarioRetirement(forecast.retirement);
  $("scenario-cut-subscriptions").checked = Boolean(forecast.cut_subscriptions_from);
  $("scenario-cut-month").value = forecast.cut_subscriptions_from || "";
  $("scenario-cut-fields").hidden = !forecast.cut_subscriptions_from;
  scenarioPaychecks = structuredClone(inputs.paychecks); editingPaycheck = null;
  $("scenario-cash-field").hidden = $("scenario-basis").value !== "blank";
  $("scenario-duplicate").disabled = $("scenario-delete").disabled = scenarioId == null;
  $("scenario-select").value = scenarioId == null ? "" : String(scenarioId);
  // The plan opened joins the comparison while there is room.
  const box = scenarioId == null ? null : $(`compare-${scenarioId}`);
  if (box && !box.checked && !box.disabled) { box.checked = true; limitCompare(); }
  planButtons(); renderScenarioPaychecks();
  $("track-month").value = ""; $("track-actual").replaceChildren();
  if (renderTracking()) loadActual();
}
$("scenario-basis").addEventListener("change", () => { $("scenario-cash-field").hidden = $("scenario-basis").value !== "blank"; });

function renderScenarioChoices() {
  const select = $("scenario-select");
  select.replaceChildren(Object.assign(document.createElement("option"), {value: "", textContent: "New plan"}),
    ...scenarioView.scenarios.map(scenario => Object.assign(document.createElement("option"), {value: String(scenario.id), textContent: scenario.name})));
  select.value = scenarioId == null ? "" : String(scenarioId);
  $("scenario-basis").replaceChildren(...scenarioView.bases.map(key => Object.assign(document.createElement("option"), {value: key, textContent: BASIS_NAMES[key]})));
  // Compare: Now and every saved plan; at most three at once (the chart's three validated colors).
  const options = $("compare-options"), checked = new Set([...options.querySelectorAll("input:checked")].map(input => input.value));
  options.replaceChildren();
  for (const [value, label] of [["now", "Now"], ...scenarioView.scenarios.map(scenario => [String(scenario.id), scenario.name])]) {
    const box = Object.assign(document.createElement("input"), {type: "checkbox", value, id: `compare-${value}`});
    box.checked = checked.size ? checked.has(value) : value === "now" || value === String(scenarioId);
    box.addEventListener("change", limitCompare);
    const wrap = element("label", "", "check-field"); wrap.append(box, ` ${label}`); options.append(wrap);
  }
  limitCompare();
}
function limitCompare() {
  const boxes = [...$("compare-options").querySelectorAll("input")], full = boxes.filter(box => box.checked).length >= 3;
  for (const box of boxes) box.disabled = full && !box.checked;
}
async function loadScenarios() {
  scenarioView = await api("/api/scenarios");
  renderScenarioChoices();
}
$("scenario-select").addEventListener("change", () => {
  const value = $("scenario-select").value;
  location.hash = value ? `#/whatif?plan=${value}` : "#/whatif?plan=new";
});
$("scenario-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!$("scenario-name").value.trim()) { notice("Name the plan first.", true); $("scenario-name").focus(); return; }
  try {
    const body = JSON.stringify(scenarioRequest());
    const saved = scenarioId == null ? await api("/api/scenarios", {method: "POST", body}) : await api(`/api/scenarios/${scenarioId}`, {method: "PUT", body});
    scenarioId = saved.id; notice(`${saved.name} saved.`);
    await loadScenarios(); fillScenario(saved);
    history.replaceState(null, "", `#/whatif?plan=${saved.id}`);
  } catch (error) { notice(error, true); }
});
$("scenario-duplicate").addEventListener("click", async () => {
  try { const copy = await api(`/api/scenarios/${scenarioId}/duplicate`, {method: "POST"}); await loadScenarios(); location.hash = `#/whatif?plan=${copy.id}`; }
  catch (error) { notice(error, true); }
});
$("scenario-delete").addEventListener("click", async () => {
  const name = $("scenario-name").value || "this plan";
  if (!await confirmAction({title: `Delete ${name}?`, message: "The plan and its paychecks are removed. Your records aren't changed.", confirmLabel: "Delete", danger: true})) return;
  try { await api(`/api/scenarios/${scenarioId}`, {method: "DELETE"}); scenarioId = null; await loadScenarios(); location.hash = "#/whatif?plan=new"; }
  catch (error) { notice(error, true); }
});

function compareTable(result) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  for (const [title, numeric] of [["Year", false], ...result.runs.map(run => [run.name, true])]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const body = table.createTBody();
  result.runs[0].years.forEach((year, index) => {
    const row = body.insertRow(); cell(row, year.year);
    for (const run of result.runs) row.appendChild(element("td", "", "numeric")).appendChild(amount(run.years[index].display.end_net_worth, {signed: false}));
  });
  wrap.append(table); return wrap;
}
function compareRun(run) {
  // One plan's details: its paychecks as worked out, each year's money, and what the numbers assume.
  const details = element("details", "", "compare-run");
  details.append(element("summary", `${run.name}: details`));
  if (run.paychecks.length) {
    const list = element("ul", "", "finance-list");
    for (const pay of run.paychecks)
      list.append(element("li", `${pay.label}: ${pay.net_per_check.display} take-home ${pay.frequency_name} (${pay.net_monthly.display} a month) from ${pay.from_month}`
        + `${pay.to_month ? ` to ${pay.to_month}` : ""}, ${pay.mode === "replace_pay" ? "replacing pay" : "added to income"}`
        + (pay.bonuses || []).map(bonus => `; ${bonus.label} ${bonus.net.display} after tax each ${MONTH_OPTIONS[bonus.month]}`).join("")
        + `${pay.complete ? "" : "; some tax tables are missing"}`));
    details.append(element("h3", "Paychecks"), list);
  }
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  const columns = [["Income", "income"], ["Spending", "spending"], ["One-off", "one_offs"], ["Into investments", "contributions"],
    // Money drawn from investments to cash, after tax, and the part only required distributions took (as on the Forecast page).
    ...(run.years.some(year => year.withdrawals) ? [["From investments", "withdrawals"], ["Tax withheld", "withdrawal_tax"], ["Required (RMD)", "rmd"]] : []),
    ["Cash at the end", "end_cash"], ["Net worth", "end_net_worth"]];
  for (const [title, numeric] of [["Year", false], ...columns.map(([name]) => [name, true])]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const body = table.createTBody();
  for (const year of run.years) {
    const row = body.insertRow(); cell(row, year.year);
    for (const [, key] of columns) row.appendChild(element("td", "", "numeric")).appendChild(amount(year.display[key], {signed: false}));
  }
  wrap.append(table);
  const notes = element("ul", "", "forecast-notes"); for (const note of run.notes) notes.append(element("li", note));
  details.append(element("h3", "By year"), wrap, element("h3", "About these numbers"), notes);
  return details;
}
function renderCompare(result) {
  const parts = [];
  for (const run of result.runs) if (run.first_month_cash_below_zero)
    parts.push(alertBox(`${run.name}: cash falls below zero in ${run.first_month_cash_below_zero}.`, {tone: "warning"}));
  // Tax Zen for each: where this year's return ends at the plan's pay, and the W-4 entry that brings it to $0.
  const taxes = result.runs.filter(run => run.tax_zen?.ready);
  if (taxes.length) {
    const list = element("ul", "", "finance-list compare-taxes");
    for (const run of taxes) list.append(element("li", taxTimeText(run.tax_zen, run.name === "Now" ? "Now" : `${run.name}, a full year at its pay`)));
    parts.push(element("h3", `Tax Zen in ${taxes[0].tax_zen.year}`), list);
  }
  const figure = element("figure", "", "compare-chart"); figure.append(forecastSvg(result.chart));
  const table = element("details"); table.append(element("summary", "Show net worth by year"), compareTable(result));
  parts.push(figure, table, ...result.runs.map(compareRun));
  $("compare-result").replaceChildren(...parts);
}
async function runCompare(body) {
  const button = $("compare-run"); button.disabled = $("scenario-try").disabled = true;
  try {
    renderCompare(await api("/api/scenarios/compare", {method: "POST", body: JSON.stringify(body)}));
    $("compare-result").scrollIntoView({block: "nearest"});
  } catch (error) { $("compare-result").replaceChildren(alertBox(error.message, {tone: "error"})); }
  finally { button.disabled = $("scenario-try").disabled = false; }
}
$("compare-run").addEventListener("click", () => {
  const chosen = [...$("compare-options").querySelectorAll("input:checked")].map(input => input.value);
  if (!chosen.length) { notice("Choose Now or a plan to compare.", true); return; }
  runCompare({scenarios: chosen.filter(value => value !== "now").map(Number), include_now: chosen.includes("now"), years: Number($("compare-years").value) || 10});
});
$("scenario-try").addEventListener("click", () => {
  // The plan as it is on screen, saved or not, beside Now.
  const draft = scenarioRequest();
  draft.name = draft.name || "This plan";
  $("compare-years").value = draft.forecast.years;
  runCompare({draft, include_now: true, years: draft.forecast.years});
});

// Following a plan (finance/plan_tracking.py): its set spending as budgets, then planned pay and spending against what happened.
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const monthText = month => `${MONTH_NAMES[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;
function thisMonth() { const today = new Date(); return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`; }
function trackTable(columns, rows, fill) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  columns.forEach(([title, numeric]) => { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; });
  const body = table.createTBody();
  for (const row of rows) fill(body.insertRow(), row);
  wrap.append(table); return wrap;
}
const trackMoney = (tr, value) => tr.appendChild(element("td", "", "numeric")).appendChild(amount(value || "—", {signed: false}));
function renderTracking() {
  const scenario = scenarioView.scenarios.find(item => item.id === scenarioId);
  $("track-panel").hidden = !scenario || scenarioView.family;
  if ($("track-panel").hidden) return false;
  $("track-status").textContent = scenario.adopted_month
    ? `Followed since ${monthText(scenario.adopted_month)}: its set spending became budgets, and what happened is compared below.`
    : "Use the plan's set spending as your monthly budgets, and see how pay and spending compare with it.";
  $("track-stop").hidden = !scenario.adopted_month;
  if (!$("track-month").value) $("track-month").value = scenario.adopted_month || thisMonth();
  $("track-budgets").replaceChildren();
  return true;
}
$("track-preview").addEventListener("click", async () => {
  const month = $("track-month").value;
  if (!month) { notice("Choose the month the budgets start.", true); return; }
  try {
    const preview = await api(`/api/scenarios/${scenarioId}/budgets?month=${month}`);
    const labels = {new: "New budget", changed: "Changes", same: "Already set"};
    const parts = [element("h3", `Budgets from ${monthText(month)}`)];
    if (preview.rows.length) parts.push(trackTable([["Category", false], ["Budget now", true], ["From the plan", true], ["", false]], preview.rows, (tr, row) => {
      cell(tr, row.category); trackMoney(tr, row.current); trackMoney(tr, row.planned); cell(tr, labels[row.change]);
    }));
    if (preview.untouched.length) parts.push(element("p", `Left as they are: ${preview.untouched.map(row => `${row.category} (${row.amount.display})`).join(", ")}.`, "muted small"));
    parts.push(...preview.notes.map(note => element("p", note, "muted small")));
    const actions = element("div", "", "button-row");
    const cancel = element("button", "Cancel", "quiet"); cancel.type = "button"; cancel.addEventListener("click", () => $("track-budgets").replaceChildren());
    const changing = preview.rows.filter(row => row.change !== "same").length;
    const apply = asyncButton(changing ? `Set ${changing} budget${changing === 1 ? "" : "s"} and follow this plan` : "Follow this plan", async () => {
      const result = await api(`/api/scenarios/${scenarioId}/adopt`, {method: "POST", body: JSON.stringify({month})});
      notice(result.applied ? `${result.applied} budget${result.applied === 1 ? "" : "s"} set. The plan is followed from ${monthText(month)}.` : `The plan is followed from ${monthText(month)}.`);
      await loadScenarios(); renderTracking(); await loadActual();
    }, "primary");
    actions.append(apply, cancel); parts.push(actions);
    $("track-budgets").replaceChildren(...parts);
    apply.focus();
  } catch (error) { notice(error, true); }
});
$("track-stop").addEventListener("click", async () => {
  if (!await confirmAction({title: "Stop following this plan?", message: "The budgets it set stay as they are; the plan is kept and can be followed again.", confirmLabel: "Stop following"})) return;
  try { await api(`/api/scenarios/${scenarioId}/stop`, {method: "POST"}); await loadScenarios(); renderTracking(); await loadActual(); }
  catch (error) { notice(error, true); }
});
function renderActual(result) {
  const parts = [element("h3", "Plan and actual")];
  for (const pay of result.pay) {
    parts.push(element("h4", `${pay.label}: planned paycheck and pay stubs`));
    if (pay.message) { parts.push(element("p", pay.message, "muted small")); continue; }
    const latest = pay.stubs[0].pay_date;
    parts.push(element("p", `The latest stub is from ${dateText(latest)}; the average is over ${pay.stubs.length} stub${pay.stubs.length === 1 ? "" : "s"} since ${monthText(pay.from_month)}.`, "muted small"));
    const groups = {earnings: "", pre_tax: "Pre-tax deductions", tax: "Taxes", post_tax: "Post-tax deductions", net: ""};
    let group = null;
    parts.push(trackTable([["", false], ["Planned", true], ["Latest stub", true], ["Average", true], ["Difference", true]], pay.rows, (tr, row) => {
      if (row.group !== group && groups[row.group]) {
        const title = tr.parentElement.insertBefore(document.createElement("tr"), tr).appendChild(element("th", groups[row.group], "paystub-group"));
        title.colSpan = 5; title.scope = "rowgroup";
      }
      group = row.group;
      if (row.total) tr.className = "paystub-total";
      const th = tr.appendChild(element("th", row.label)); th.scope = "row";
      for (const key of ["planned", "latest", "average", "difference"]) trackMoney(tr, row[key]);
    }));
    parts[parts.length - 1].querySelector("table").classList.add("paystub-table");
  }
  if (result.spending.length) {
    parts.push(element("h4", "Set spending and what was spent"));
    for (const month of result.spending) {
      parts.push(element("p", `${monthText(month.month)}${month.partial ? " (so far)" : ""}: ${month.actual.display} spent of ${month.planned.display} planned.`, "small"));
      parts.push(trackTable([["Category", false], ["Planned", true], ["Spent", true], ["Difference", true], ["", false]], month.rows, (tr, row) => {
        cell(tr, row.category); trackMoney(tr, row.planned); trackMoney(tr, row.actual); trackMoney(tr, row.difference);
        tr.insertCell().append(statusBadge(row.status === "over" ? "over_plan" : "within_plan"));
      }));
    }
  } else parts.push(element("p", "The plan sets no spending for the months so far, so there's no spending to compare yet.", "muted small"));
  const notes = element("ul", "", "forecast-notes"); for (const note of result.notes) notes.append(element("li", note));
  parts.push(notes);
  $("track-actual").replaceChildren(...parts);
}
async function loadActual() {
  if ($("track-panel").hidden) return;
  const loading = scenarioId;
  try {
    const result = await api(`/api/scenarios/${scenarioId}/actual`);
    if (loading === scenarioId) renderActual(result);
  } catch (error) { $("track-actual").replaceChildren(alertBox(error.message, {tone: "error"})); }
}

async function loadWhatIf(params = new URLSearchParams()) {
  try { await loadScenarios(); } catch (error) { notice(error, true); }
  const wanted = params.get?.("plan");
  if (wanted === "new" && scenarioId != null) fillScenario(null);
  else if (wanted && wanted !== "new" && String(scenarioId) !== wanted) {
    const found = scenarioView.scenarios.find(scenario => String(scenario.id) === wanted);
    if (found) fillScenario(found); else { notice("That plan no longer exists.", true); fillScenario(null); }
  } else if (!wanted && scenarioId == null && !$("scenario-name").value) fillScenario(null);
  else renderScenarioChoices();
  await loadPlanner(params);
}
async function loadPlanner(params) {
  if (!planReady) {
    planReady = true;
    const state = $("plan-state");
    state.append(Object.assign(document.createElement("option"), {value: "", textContent: "No state tax / not set"}));
    for (const [code, name] of Object.entries(PLAN_STATES)) state.append(Object.assign(document.createElement("option"), {value: code, textContent: name}));
    $("plan-year").value = new Date().getFullYear();
    try { $("plan-status").value = (await api("/api/settings")).household.filing_status || "single"; } catch { /* The default stays. */ }
  }
  const stub = params.get?.("stub");
  if (stub) {
    try { fillPaycheck(await api(`/api/paycheck/from-stub/${Number(stub)}`)); notice("Started from the pay stub. Remove one-time lines to see a steady paycheck."); }
    catch (error) { notice(error, true); }
  }
  await runPaycheck();
}
