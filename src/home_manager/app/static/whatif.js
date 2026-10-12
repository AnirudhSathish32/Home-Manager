"use strict";
// What If (docs/planning.md "What If"): the paycheck planner. The server works out every line from gross to net
// (finance/paycheck.py); this page only collects the inputs and shows the server's exact text.
// whatif_v2.js draws the page; these builders work on its inputs, which carry the "wi2-" prefix. whatif_v2.js answers
// wi2ShowTab(name), renderAgainstNowV2(result, error), wi2FollowChanged(shown) and wi2Href(plan).
const wi = {opened: false, follow: false, paychecksRun: null};
const w$ = id => $("wi2-" + id);
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
let planTimer = 0, planLoad = 0, planRowId = 0;
let planReady = false;  // Whether the planner has its states and year filled in.

function planSelect(id, options, value = "") {
  const select = document.createElement("select"); select.id = id;
  for (const [key, label] of Object.entries(options)) select.append(Object.assign(document.createElement("option"), {value: key, textContent: label}));
  if (value) select.value = value;
  return select;
}
function planRow(list, line = {}) {
  // One deduction or earnings line: what it is, a name, and an amount per paycheck or a percent of gross pay.
  const row = element("div", "", "forecast-row forecast-item plan-line"), id = ++planRowId, p = "wi2-";
  const category = planSelect(`${p}${list}-category-${id}`, PLAN_CATEGORIES[list], line.category);
  const label = forecastInput(`${p}${list}-label-${id}`, {maxlength: "60", placeholder: "Optional"}); label.value = line.label || "";
  const kind = planSelect(`${p}${list}-kind-${id}`, list === "earnings" ? {amount: "$ a check"} : {amount: "$ a check", percent: "% of gross"},
    line.percent != null ? "percent" : "amount");
  const value = forecastInput(`${p}${list}-value-${id}`, {inputmode: "decimal", required: ""}); value.value = line.percent ?? line.amount ?? "";
  category.dataset.key = "category"; label.dataset.key = "label"; kind.dataset.key = "kind"; value.dataset.key = "value";
  row.append(forecastField("What", category), forecastField("Name", label), forecastField("As", kind), forecastField("Amount", value));
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => { row.remove(); schedulePaycheck(); });
  row.append(remove); w$(`plan-${list}`).append(row);
  return row;
}
function planLines(list) {
  return [...w$(`plan-${list}`).querySelectorAll(".plan-line")].map(row => {
    const read = key => row.querySelector(`[data-key="${key}"]`).value.trim();
    return {category: read("category"), label: read("label"), [read("kind")]: read("value")};
  }).filter(line => (line.amount ?? line.percent) !== "");
}
const MONTH_OPTIONS = Object.fromEntries(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
  .map((name, index) => [String(index + 1), name]));
function bonusRow(bonus = {}) {
  // A bonus: a name, the amount, and the month it's paid (with that month's first paycheck).
  const row = element("div", "", "forecast-row forecast-item plan-bonus"), id = ++planRowId, p = "wi2-";
  const label = forecastInput(`${p}bonus-label-${id}`, {maxlength: "60", placeholder: "Year-end bonus"}); label.value = bonus.label || "";
  const value = forecastInput(`${p}bonus-amount-${id}`, {inputmode: "decimal", required: ""}); value.value = bonus.amount || "";
  const month = planSelect(`${p}bonus-month-${id}`, MONTH_OPTIONS, String(bonus.month || 12));
  label.dataset.key = "label"; value.dataset.key = "amount"; month.dataset.key = "month";
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => { row.remove(); schedulePaycheck(); });
  row.append(forecastField("Name", label), forecastField("Amount", value), forecastField("Paid in", month), remove);
  w$("plan-bonuses").append(row);
  return row;
}
function planBonuses() {
  return [...w$("plan-bonuses").querySelectorAll(".plan-bonus")].map(row => {
    const read = key => row.querySelector(`[data-key="${key}"]`).value.trim();
    return {label: read("label"), amount: read("amount"), month: Number(read("month"))};
  }).filter(bonus => bonus.amount !== "");
}

function planText(id) { const value = w$(id).value.trim(); return value === "" ? null : value; }
function paycheckRequest() {
  const pay = planText("plan-pay"), local = w$("plan-local-kind").value;
  const request = {
    year: Number(w$("plan-year").value), filing_status: w$("plan-status").value, work_state: w$("plan-state").value || null,
    pay_frequency: Number(w$("plan-frequency").value),
    annual_salary: w$("plan-pay-kind").value === "annual" ? pay : null, gross_per_check: w$("plan-pay-kind").value === "check" ? pay : null,
    earnings: planLines("earnings"), pre_tax: planLines("pre_tax"), post_tax: planLines("post_tax"), employer: planLines("employer"),
    match_percent: planText("plan-match"), match_limit_percent: planText("plan-match-limit"),
    federal_deduction: planText("plan-fed-deduction"), federal_credits: planText("plan-fed-credits") || "0",
    federal_other_income: planText("plan-fed-other-income") || "0", federal_deductions: planText("plan-fed-deductions") || "0",
    federal_extra_withholding: planText("plan-fed-extra") || "0", federal_step2: w$("plan-fed-step2").checked, bonuses: planBonuses(),
    state_deduction: planText("plan-state-deduction"), state_rate_percent: planText("plan-state-rate"),
    state_extra_withholding: planText("plan-state-extra") || "0", state_credits: planText("plan-state-credits") || "0",
    state_supplemental_percent: planText("plan-state-supplemental"),
    state_disability_percent: planText("plan-sdi"), state_disability_wage_limit: planText("plan-sdi-limit"),
    local_tax_percent: local === "percent" ? planText("plan-local-value") : null, local_tax_amount: local === "amount" ? planText("plan-local-value") : null,
    local_tax_wages: w$("plan-local-wages").value};
  return request;
}
function fillPaycheck(value) {
  // A planner input (from a pay stub or a saved plan): every field, then the lines, so updating it keeps what it had.
  w$("plan-year").value = value.year; w$("plan-status").value = value.filing_status; w$("plan-state").value = value.work_state || "";
  w$("plan-frequency").value = String(value.pay_frequency);
  w$("plan-pay-kind").value = value.annual_salary != null ? "annual" : "check"; w$("plan-pay").value = value.annual_salary ?? value.gross_per_check ?? "";
  const zero = text => text == null || text === "0" ? "" : text;  // Zero defaults show as the placeholder.
  for (const [id, key, blankIsZero] of [["plan-match", "match_percent"], ["plan-match-limit", "match_limit_percent"], ["plan-fed-deduction", "federal_deduction"],
      ["plan-fed-credits", "federal_credits", true], ["plan-fed-other-income", "federal_other_income", true], ["plan-fed-deductions", "federal_deductions", true],
      ["plan-fed-extra", "federal_extra_withholding", true], ["plan-state-deduction", "state_deduction"], ["plan-state-rate", "state_rate_percent"],
      ["plan-state-extra", "state_extra_withholding", true], ["plan-state-credits", "state_credits", true], ["plan-state-supplemental", "state_supplemental_percent"],
      ["plan-sdi", "state_disability_percent"], ["plan-sdi-limit", "state_disability_wage_limit"]])
    w$(id).value = blankIsZero ? zero(value[key]) : value[key] ?? "";
  w$("plan-fed-step2").checked = Boolean(value.federal_step2);
  w$("plan-local-kind").value = value.local_tax_percent != null ? "percent" : value.local_tax_amount != null ? "amount" : "none";
  w$("plan-local-value").value = value.local_tax_percent ?? value.local_tax_amount ?? "";
  w$("plan-local-wages").value = value.local_tax_wages || "taxable";
  w$("plan-local-kind").dispatchEvent(new Event("change"));
  for (const list of Object.keys(PLAN_CATEGORIES)) {
    w$(`plan-${list}`).replaceChildren();
    for (const line of value[list] || []) planRow(list, line);
  }
  w$("plan-bonuses").replaceChildren();
  for (const bonus of value.bonuses || []) bonusRow(bonus);
}

const planRate = percent => percent == null ? "—" : `${percent}%`;  // The server's *_percent text.
// perCheck and perYear: the server's display text, or a figure ({display, trace}) for a traced line.
function planTableRow(body, label, how, perCheck, perYear, className = "") {
  const tr = body.insertRow(); if (className) tr.className = className;
  const th = tr.appendChild(element("th", label)); th.scope = "row";
  if (how) th.appendChild(element("small", how, "muted block"));
  for (const value of [perCheck, perYear]) tr.appendChild(element("td", "", "numeric")).appendChild(figure(value || "—", {size: "sm", signed: false}));
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
    // Each tax line's per-paycheck amount carries its breakdown (paycheck.line).
    for (const line of group.lines) planTableRow(body, line.label, line.how, line.trace ? {display: line.display.per_check_minor, trace: line.trace} : line.display.per_check_minor,
                                                 line.display.annual_minor);
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
        result.traces ? {display: result.net.display.per_check_minor, trace: result.traces.net_per_check} : result.net.display.per_check_minor,
        result.net.display.annual_minor, "paystub-total");
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
      if (part.status === "missing") block.appendChild(asyncButton(`Look up the ${result.year} ${part.name} table`, () =>
        api("/api/tax-tables/lookup", {method: "POST", body: JSON.stringify({jurisdiction: part.jurisdiction, year: result.year, filing_status: result.filing_status})})
          .then(() => notice("Looking it up. The table will wait for you in Review.")), ""));
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
    block.appendChild(element("p", `A year's tax: ${d.annual_tax_minor}${part.credits_minor ? ` after ${d.credits_minor} of credits` : ""} (${planRate(part.effective_rate_percent)} of wages; `
      + `top bucket ${planRate(part.top_rate_percent)}). Each paycheck: ${d.estimate_minor}${part.extra_withholding_minor ? ` plus ${d.extra_withholding_minor} extra withholding` : ""}.`));
    section.appendChild(block);
  }
  return section;
}
function taxTimeText(zen, lead) {
  // Tax Zen for a paycheck or a plan (finance/tax_zen.py): where the year ends, and the W-4 entry that brings it to $0.
  if (zen.zen) return `${lead}, you'd be Tax Zen in ${zen.year}: within a dollar of $0 at tax time.`;
  const where = zen.result_minor > 0 ? `a refund of ${zen.display.result_minor}` : `owing ${zen.display.result_minor}`;
  return `${lead}, ${zen.year}'s return ends at ${where}.${taxTimeFix(zen)}`;
}
function taxTimeFix(zen) {
  return zen.w4?.amount != null ? ` To reach $0, put ${zen.w4.display.amount} in W-4 Step ${zen.w4.field === "4(a)" ? "4(a), other income" : "4(b), deductions"}`
    + `${zen.job ? ` for ${zen.job}` : ""}.` : zen.w4?.unreachable ? " No W-4 entry can bring it to $0." : "";
}
// The same sentence with the year's result as a figure that opens its breakdown.
function taxTimeNodes(zen, lead) {
  const line = element("p", "", "small");
  if (zen.zen || !zen.trace) { line.textContent = taxTimeText(zen, lead); return line; }
  line.append(`${lead}, ${zen.year}'s return ends at ${zen.result_minor > 0 ? "a refund of " : "owing "}`,
              figure({display: zen.display.result_minor, trace: zen.trace}, {size: "inline", magnitude: true}), `.${taxTimeFix(zen)}`);
  return line;
}
function renderPaycheck(result) {
  const target = w$("paycheck-result");
  const headline = element("dl", "", "plan-headline");
  // The take-home figures open their breakdown (paycheck.net).
  const traced = (display, key) => result.traces?.[key] ? {display, trace: result.traces[key]} : display;
  for (const [label, value, big] of [["Take-home per paycheck", traced(result.net.display.per_check_minor, "net_per_check"), true],
      ["A month, on average", traced(result.net.display.monthly_minor, "net_monthly")], ["A year", result.net.display.annual_minor]]) {
    const dd = element("dd", "", big ? "plan-figure" : ""); dd.appendChild(figure(value, {size: big ? "lg" : "sm", signed: false}));
    headline.append(element("dt", label), dd);
  }
  fitFigures(headline);
  const rates = element("p", `Taxes take ${planRate(result.rates.total_tax_percent)} of gross pay; you keep ${planRate(result.rates.take_home_percent)}.`
    + (result.rates.federal_marginal_percent != null ? ` Top federal bucket ${planRate(result.rates.federal_marginal_percent)}` : "")
    + (result.rates.state_marginal_percent != null ? `, top ${result.state_name} bucket ${planRate(result.rates.state_marginal_percent)}.` : result.rates.federal_marginal_percent != null ? "." : ""), "muted small");
  const parts = [element("h2", "From gross pay to net pay"), headline, rates];
  const taxTime = result.tax_time;
  if (taxTime?.ready) parts.push(taxTimeNodes(taxTime, "With this paycheck alone for a full year"));
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
    w$(id).placeholder = part?.display?.table_deduction_minor ? `Table: ${part.display.table_deduction_minor}` : "";
}
async function runPaycheck() {
  if (!planText("plan-pay")) {
    w$("paycheck-result").replaceChildren(element("h2", "From gross pay to net pay"), emptyState("Enter a salary or the gross pay per paycheck to see every line from gross to net."));
    return;
  }
  const load = ++planLoad;
  try {
    const result = await api("/api/paycheck", {method: "POST", body: JSON.stringify(paycheckRequest())});
    if (load === planLoad) { renderPaycheck(result); w$("paycheck-error").replaceChildren(); }
  } catch (error) {
    if (load !== planLoad) return;
    // A tax table waiting to be confirmed is in To check.
    const action = /table/i.test(error.message) ? homeLink("Check the tax tables", "#/review") : null;
    w$("paycheck-error").replaceChildren(alertBox(error.message, {tone: "error", action}));
  }
}
function schedulePaycheck() { clearTimeout(planTimer); planTimer = setTimeout(runPaycheck, 400); }

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
    const input = forecastInput(`wi2-${list}-${key}-${id}`, attributes);
    input.dataset.key = key; if (values[key] != null) input.value = values[key];
    row.append(forecastField(label, input));
  }
  const remove = element("button", "Remove", "quiet"); remove.type = "button";
  remove.addEventListener("click", () => row.remove());
  row.append(remove); w$(list).append(row);
  return row;
}
const SCENARIO_LISTS = {
  "scenario-amounts": [["category", "Category", {list: "fc2-forecast-category-options", required: ""}], ["monthly_amount", "A month, today's $", {inputmode: "decimal", required: "", placeholder: "2100.00"}],
                       ["from_month", "From month", {type: "month", required: ""}]],
  "scenario-changes": [["category", "Category", {list: "fc2-forecast-category-options", required: ""}], ["percent", "Change (%)", {inputmode: "decimal", required: "", placeholder: "-20"}]],
  "scenario-one-offs": [["month", "Month", {type: "month", required: ""}], ["amount", "Amount", {inputmode: "decimal", required: "", placeholder: "-3000.00"}], ["label", "What it is", {maxlength: "80"}]]};

function accountOptions(select, treatments, chosen) {
  select.replaceChildren(Object.assign(document.createElement("option"), {value: "", textContent: "A new planned account"}));
  for (const account of scenarioView.accounts.filter(account => treatments.includes(account.tax_treatment)))
    select.append(Object.assign(document.createElement("option"), {value: String(account.id), textContent: `${account.name} (${account.kind_label})`}));
  select.value = chosen == null ? "" : String(chosen);
}
function paycheckFacts(paycheck) {
  return `${paycheck.work_state ? PLAN_STATES[paycheck.work_state] : "no state tax"} · ${paycheck.pre_tax.length} pre-tax, ${paycheck.post_tax.length} post-tax lines · tax year ${paycheck.year}`;
}
// A paycheck's line: the server's take-home per paycheck once the plan has been tried, never the raw input.
function paycheckSummaryNodes(plan, index) {
  const line = element("p", "", "muted small"), run = wi.paychecksRun?.[index];
  if (run) line.append(figure(run.net_per_check, {size: "inline", signed: false}), ` take-home ${run.frequency_name} · ${paycheckFacts(plan.paycheck)}`);
  else line.append(`Try the plan to see its take-home · ${paycheckFacts(plan.paycheck)}`);
  return line;
}
function renderScenarioPaychecks() {
  const list = w$("scenario-paychecks"); list.replaceChildren();
  scenarioPaychecks.forEach((plan, index) => {
    const row = element("div", "", "scenario-paycheck"), id = `wi2-plan-${index}`;
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
    const open = element("button", "Open in planner", "quiet"); open.type = "button";
    open.addEventListener("click", () => {
      editingPaycheck = index; fillPaycheck(plan.paycheck); planButtons(); renderScenarioPaychecks(); runPaycheck();
      wi2ShowTab("planner");
      w$("paycheck-form").scrollIntoView({block: "start"}); w$("plan-pay").focus();
    });
    const remove = element("button", "Remove", "quiet"); remove.type = "button";
    remove.addEventListener("click", () => {
      scenarioPaychecks.splice(index, 1); if (editingPaycheck === index) editingPaycheck = null; else if (editingPaycheck > index) editingPaycheck--;
      wi.paychecksRun = null;
      planButtons(); renderScenarioPaychecks();
    });
    actions.append(open, remove);
    row.append(fields, paycheckSummaryNodes(plan, index), actions);
    list.append(row);
  });
  if (!scenarioPaychecks.length) list.append(element("p", "No paychecks in this plan yet: income stays as recorded.", "muted small"));
  list.dispatchEvent(new CustomEvent("paycheckschange", {bubbles: true}));
}
function planButtons() {
  // The planner adds a new paycheck to the plan, or updates the one opened from it.
  w$("paycheck-to-plan").textContent = editingPaycheck == null ? "Add to plan" : `Update “${scenarioPaychecks[editingPaycheck].label}” in the plan`;
}

function showScenarioRetirement() {
  const on = w$("scenario-retire").checked, fixed = w$("scenario-retire-mode").value === "fixed";
  w$("scenario-retire-fields").hidden = !on;
  w$("scenario-retire-amount-field").hidden = !fixed; w$("scenario-retire-floor-field").hidden = fixed;
}
function scenarioRetirement() {
  // The same self-contained retirement input as the Forecast page (forecast.js forecastRequest).
  if (!w$("scenario-retire").checked) return null;
  const fixed = w$("scenario-retire-mode").value === "fixed";
  return {start_month: w$("scenario-retire-month").value, mode: w$("scenario-retire-mode").value, tax_percent: planText("scenario-retire-tax") || "0",
          ...(fixed ? {monthly_amount: planText("scenario-retire-amount")} : {cash_floor: planText("scenario-retire-floor") || "0"})};
}
function fillScenarioRetirement(plan) {
  w$("scenario-retire").checked = Boolean(plan);
  w$("scenario-retire-month").value = plan?.start_month || ""; w$("scenario-retire-mode").value = plan?.mode || "shortfall";
  w$("scenario-retire-amount").value = plan?.monthly_amount || ""; w$("scenario-retire-floor").value = plan?.cash_floor ?? "0";
  w$("scenario-retire-tax").value = plan?.tax_percent ?? "0";
  showScenarioRetirement();
}
function scenarioRequest() {
  const basis = w$("scenario-basis").value;
  return {name: w$("scenario-name").value.trim(), basis, starting_cash: basis === "blank" ? (planText("scenario-cash") || "0") : "0",
          paychecks: scenarioPaychecks.map(plan => ({...plan, label: (plan.label || "").trim() || "Paycheck", to_month: plan.to_month || null})),
          forecast: {years: Number(w$("scenario-years").value) || 10, inflation_percent: planText("scenario-inflation") || "0",
                     income_growth_percent: planText("scenario-income-growth") || "0",
                     category_amounts: forecastItems("wi2-scenario-amounts"), spending_changes: forecastItems("wi2-scenario-changes"),
                     one_offs: forecastItems("wi2-scenario-one-offs").map(item => ({...item, label: item.label || ""})),
                     retirement: scenarioRetirement(),
                     cut_subscriptions_from: w$("scenario-cut-subscriptions").checked ? w$("scenario-cut-month").value || null : null}};
}
function fillScenario(scenario) {
  const inputs = scenario?.inputs || {name: "", basis: scenarioView.bases[0], starting_cash: "0", paychecks: [], forecast: {}};
  scenarioId = scenario?.id ?? null;
  w$("scenario-name").value = inputs.name; w$("scenario-basis").value = inputs.basis; w$("scenario-cash").value = inputs.starting_cash;
  const forecast = inputs.forecast || {};
  w$("scenario-years").value = forecast.years ?? 10; w$("scenario-inflation").value = forecast.inflation_percent ?? "2"; w$("scenario-income-growth").value = forecast.income_growth_percent ?? "0";
  for (const [list, key] of [["scenario-amounts", "category_amounts"], ["scenario-changes", "spending_changes"], ["scenario-one-offs", "one_offs"]]) {
    w$(list).replaceChildren();
    for (const item of forecast[key] || []) scenarioRow(list, SCENARIO_LISTS[list], item);
  }
  fillScenarioRetirement(forecast.retirement);
  w$("scenario-cut-subscriptions").checked = Boolean(forecast.cut_subscriptions_from);
  w$("scenario-cut-month").value = forecast.cut_subscriptions_from || "";
  w$("scenario-cut-fields").hidden = !forecast.cut_subscriptions_from;
  scenarioPaychecks = structuredClone(inputs.paychecks); editingPaycheck = null; wi.paychecksRun = null;
  w$("scenario-cash-field").hidden = w$("scenario-basis").value !== "blank";
  w$("scenario-duplicate").disabled = w$("scenario-delete").disabled = scenarioId == null;
  w$("scenario-select").value = scenarioId == null ? "" : String(scenarioId);
  // The plan opened joins the comparison while there is room.
  const box = scenarioId == null ? null : w$(`compare-${scenarioId}`);
  if (box && !box.checked && !box.disabled) { box.checked = true; limitCompare(); }
  planButtons(); renderScenarioPaychecks();
  w$("track-month").value = ""; w$("track-actual").replaceChildren();
  if (renderTracking()) loadActual();
}

function renderScenarioChoices() {
  const select = w$("scenario-select");
  select.replaceChildren(Object.assign(document.createElement("option"), {value: "", textContent: "New plan"}),
    ...scenarioView.scenarios.map(scenario => Object.assign(document.createElement("option"), {value: String(scenario.id), textContent: scenario.name})));
  select.value = scenarioId == null ? "" : String(scenarioId);
  w$("scenario-basis").replaceChildren(...scenarioView.bases.map(key => Object.assign(document.createElement("option"), {value: key, textContent: BASIS_NAMES[key]})));
  // Compare: Now and every saved plan; at most three at once (the chart's three validated colors).
  const options = w$("compare-options"), checked = new Set([...options.querySelectorAll("input:checked")].map(input => input.value));
  options.replaceChildren();
  for (const [value, label] of [["now", "Now"], ...scenarioView.scenarios.map(scenario => [String(scenario.id), scenario.name])]) {
    const box = Object.assign(document.createElement("input"), {type: "checkbox", value, id: `wi2-compare-${value}`});
    box.checked = checked.size ? checked.has(value) : value === "now" || value === String(scenarioId);
    box.addEventListener("change", limitCompare);
    const wrap = element("label", "", "check-field"); wrap.append(box, ` ${label}`); options.append(wrap);
  }
  limitCompare();
}
function limitCompare() {
  const boxes = [...w$("compare-options").querySelectorAll("input")], chosen = boxes.filter(box => box.checked).length, full = chosen >= 3;
  for (const box of boxes) box.disabled = full && !box.checked;
  // Nothing can't be compared: the button waits for a choice.
  w$("compare-run").disabled = !chosen; w$("compare-note").hidden = Boolean(chosen);
}
async function loadScenarios() {
  scenarioView = await api("/api/scenarios");
  renderScenarioChoices();
}

function compareTable(result) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  for (const [title, numeric] of [["Year", false], ...result.runs.map(run => [run.name, true])]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const body = table.createTBody();
  result.runs[0].years.forEach((year, index) => {
    const row = body.insertRow(); cell(row, year.year);
    for (const run of result.runs) row.appendChild(element("td", "", "numeric")).appendChild(figure(yearFigure(run.years[index], "end_net_worth"), {size: "sm", signed: false}));
  });
  wrap.append(table); return wrap;
}
// A year's traced amount as a figure ({display, trace}); the display text alone where it isn't traced.
function yearFigure(year, key) { return year.traces?.[key] ? {display: year.display[key], trace: year.traces[key]} : year.display[key]; }
function payLine(pay) {
  // One paycheck as the plan worked it out; the take-home amounts open their breakdown.
  const rest = ` from ${pay.from_month}${pay.to_month ? ` to ${pay.to_month}` : ""}, ${pay.mode === "replace_pay" ? "replacing pay" : "added to income"}`
    + (pay.bonuses || []).map(bonus => `; ${bonus.label} ${bonus.net.display} after tax each ${MONTH_OPTIONS[bonus.month]}`).join("")
    + `${pay.complete ? "" : "; some tax tables are missing"}`;
  const li = element("li");
  li.append(`${pay.label}: `, figure(pay.net_per_check, {size: "inline", signed: false}), ` take-home ${pay.frequency_name} (`,
            figure(pay.net_monthly, {size: "inline", signed: false}), ` a month)${rest}`);
  return li;
}
function compareRun(run) {
  // One plan's details: its paychecks as worked out, each year's money, and what the numbers assume.
  const details = element("details", "", "compare-run");
  details.append(element("summary", `${run.name}: details`));
  if (run.paychecks.length) {
    const list = element("ul", "", "finance-list");
    for (const pay of run.paychecks) list.append(payLine(pay));
    details.append(element("h3", "Paychecks"), list);
  }
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  const columns = [["Income", "income"], ["Spending", "spending"], ["One-off", "one_offs"], ["Into investments", "contributions"],
    // Money drawn from investments to cash, after tax, and the part only required distributions took (as on the Forecast page).
    ...(run.years.some(year => year.withdrawals) ? [["From investments", "withdrawals"], ["Tax withheld", "withdrawal_tax"], ["Required (RMD)", "rmd"]] : []),
    ...(run.years.some(year => year.pension) ? [["Pension", "pension"], ["Pension tax", "pension_tax"]] : []),
    ...(run.years.some(year => year.education) ? [["Education", "education"], ["Paid by the 529", "education_from_529"]] : []),
    ["Cash at the end", "end_cash"], ["Net worth", "end_net_worth"]];
  for (const [title, numeric] of [["Year", false], ...columns.map(([name]) => [name, true])]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const body = table.createTBody();
  for (const year of run.years) {
    const row = body.insertRow(); cell(row, year.year);
    for (const [, key] of columns) row.appendChild(element("td", "", "numeric")).appendChild(figure(yearFigure(year, key), {size: "sm", signed: false}));
  }
  wrap.append(table);
  const notes = element("ul", "", "forecast-notes"); for (const note of run.notes) notes.append(element("li", note));
  details.append(element("h3", "By year"), wrap, element("h3", "About these numbers"), notes);
  return details;
}
function renderCompare(result) {
  const parts = [];
  for (const run of result.runs) if (run.first_month_cash_below_zero)
    parts.push(alertBox(`${run.name}: cash falls below zero in ${monthText(run.first_month_cash_below_zero)}.`, {tone: "warning"}));
  // Tax Zen for each: where this year's return ends at the plan's pay, and the W-4 entry that brings it to $0.
  const taxes = result.runs.filter(run => run.tax_zen?.ready);
  if (taxes.length) {
    const list = element("ul", "", "finance-list compare-taxes");
    for (const run of taxes) {
      const lead = run.name === "Now" ? "Now" : `${run.name}, a full year at its pay`;
      const li = element("li"); li.append(...taxTimeNodes(run.tax_zen, lead).childNodes); list.append(li);
    }
    parts.push(element("h3", `Tax Zen in ${taxes[0].tax_zen.year}`), list);
  }
  const figure = element("figure", "", "compare-chart"), svg = forecastSvg(result.chart); figure.append(svg);
  const table = element("details", "", "fc2-fold");
  table.append(element("summary", "View data table"), compareTable(result));
  // What the chart shows in words, under it (the chart's own description).
  parts.push(figure, element("p", svg.querySelector("desc")?.textContent || "", "muted small wi2-chart-desc"), table, ...result.runs.map(compareRun));
  w$("compare-result").replaceChildren(...parts);
}
// tried: the plan on screen against Now ("Try it"), which also shows beside the plan.
async function runCompare(body, {tried = false} = {}) {
  const button = w$("compare-run"), tryButton = w$("scenario-try");
  button.disabled = tryButton.disabled = true;
  try {
    const result = await api("/api/scenarios/compare", {method: "POST", body: JSON.stringify(body)});
    renderCompare(result);
    if (tried) renderAgainstNowV2(result, null);
    else w$("compare-result").scrollIntoView({block: "nearest"});
  } catch (error) {
    w$("compare-result").replaceChildren(alertBox(error.message, {tone: "error"}));
    if (tried) renderAgainstNowV2(null, error);
  } finally {
    button.disabled = tryButton.disabled = false;
    limitCompare();
  }
}

// Following a plan (finance/plan_tracking.py): its set spending as budgets, then planned pay and spending against what happened.
function thisMonth() { const today = new Date(); return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`; }
// columns: [title, numeric] pairs; fill(tr, row) draws each row into its table (it may add rows before it).
function trackTable(columns, rows, fill) {
  const wrap = dataTable(columns.map(([title, numeric]) => [title, numeric ? "numeric" : ""]), []), body = wrap.querySelector("tbody");
  for (const row of rows) fill(body.insertRow(), row);
  return wrap;
}
const trackMoney = (tr, value) => tr.appendChild(element("td", "", "numeric")).appendChild(figure(value || "—", {size: "sm", signed: false}));
function renderTracking() {
  // Follow this plan: for a saved plan in a personal profile only.
  const scenario = scenarioView.scenarios.find(item => item.id === scenarioId);
  wi.follow = Boolean(scenario) && !scenarioView.family;
  wi2FollowChanged(wi.follow);
  if (!wi.follow) return false;
  w$("track-status").textContent = scenario.adopted_month
    ? `Followed since ${monthText(scenario.adopted_month)}: its set spending became budgets, and what happened is compared below.`
    : "Use the plan's set spending as your monthly budgets, and see how pay and spending compare with it.";
  w$("track-stop").hidden = !scenario.adopted_month;
  if (!w$("track-month").value) w$("track-month").value = scenario.adopted_month || thisMonth();
  w$("track-budgets").replaceChildren();
  return true;
}
async function previewTracking() {
  const month = w$("track-month").value;
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
    const cancel = element("button", "Cancel", "quiet"); cancel.type = "button"; cancel.addEventListener("click", () => w$("track-budgets").replaceChildren());
    const changing = preview.rows.filter(row => row.change !== "same").length;
    const apply = asyncButton(changing ? `Set ${changing} budget${changing === 1 ? "" : "s"} and follow this plan` : "Follow this plan", async () => {
      const result = await api(`/api/scenarios/${scenarioId}/adopt`, {method: "POST", body: JSON.stringify({month})});
      notice(result.applied ? `${result.applied} budget${result.applied === 1 ? "" : "s"} set. The plan is followed from ${monthText(month)}.` : `The plan is followed from ${monthText(month)}.`);
      await loadScenarios(); renderTracking(); await loadActual();
    }, "primary");
    actions.append(apply, cancel); parts.push(actions);
    w$("track-budgets").replaceChildren(...parts);
    apply.focus();
  } catch (error) { notice(error, true); }
}
async function stopTracking() {
  if (!await confirmAction({title: "Stop following this plan?", message: "The budgets it set stay as they are; the plan is kept and can be followed again.", confirmLabel: "Stop following"})) return;
  try { await api(`/api/scenarios/${scenarioId}/stop`, {method: "POST"}); await loadScenarios(); renderTracking(); await loadActual(); }
  catch (error) { notice(error, true); }
}
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
      const line = element("p", "", "small");
      line.append(`${monthText(month.month)}${month.partial ? " (so far)" : ""}: `, figure(month.actual, {size: "inline", signed: false}), " spent of ",
                  figure(month.planned, {size: "inline", signed: false}), " planned.");
      parts.push(line);
      parts.push(trackTable([["Category", false], ["Planned", true], ["Spent", true], ["Difference", true], ["", false]], month.rows, (tr, row) => {
        cell(tr, row.category); trackMoney(tr, row.planned); trackMoney(tr, row.actual); trackMoney(tr, row.difference);
        tr.insertCell().append(statusBadge(row.status === "over" ? "over_plan" : "within_plan"));
      }));
    }
  } else parts.push(element("p", "The plan sets no spending for the months so far, so there's no spending to compare yet.", "muted small"));
  const notes = element("ul", "", "forecast-notes"); for (const note of result.notes) notes.append(element("li", note));
  parts.push(notes);
  w$("track-actual").replaceChildren(...parts);
}
async function loadActual() {
  if (!wi.follow) return;
  const loading = scenarioId;
  try {
    const result = await api(`/api/scenarios/${scenarioId}/actual`);
    if (loading === scenarioId) renderActual(result);
  } catch (error) { w$("track-actual").replaceChildren(alertBox(error.message, {tone: "error"})); }
}

// The listeners on the page's inputs.
function wireWhatIf() {
  const on = (id, event, handler) => w$(id).addEventListener(event, handler);
  for (const list of Object.keys(PLAN_CATEGORIES)) on(`add-plan-${list}`, "click", () => planRow(list).querySelector("select").focus());
  on("add-plan-bonus", "click", () => bonusRow().querySelector("input").focus());
  on("paycheck-form", "input", schedulePaycheck);
  on("paycheck-form", "change", schedulePaycheck);
  on("paycheck-form", "submit", event => { event.preventDefault(); clearTimeout(planTimer); runPaycheck(); });
  on("plan-local-kind", "change", () => {
    const kind = w$("plan-local-kind").value;
    w$("plan-local-value-field").hidden = kind === "none"; w$("plan-local-wages-field").hidden = kind !== "percent";
    w$("plan-local-value").previousElementSibling.textContent = kind === "amount" ? "Local tax per paycheck" : "Local tax rate (%)";
  });
  on("add-scenario-amount", "click", () => scenarioRow("scenario-amounts", SCENARIO_LISTS["scenario-amounts"], {from_month: nextMonth()}).querySelector("input").focus());
  on("add-scenario-change", "click", () => scenarioRow("scenario-changes", SCENARIO_LISTS["scenario-changes"]).querySelector("input").focus());
  on("add-scenario-one-off", "click", () => scenarioRow("scenario-one-offs", SCENARIO_LISTS["scenario-one-offs"]).querySelector("input").focus());
  on("paycheck-to-plan", "click", () => {
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
    wi.paychecksRun = null;
    planButtons(); renderScenarioPaychecks();
    wi2ShowTab("plan");
    const list = w$("scenario-paychecks"), group = list.closest("details");
    if (group) group.open = true;
    list.scrollIntoView({block: "center"});
  });
  on("scenario-retire", "change", showScenarioRetirement);
  on("scenario-retire-mode", "change", showScenarioRetirement);
  on("scenario-cut-subscriptions", "change", () => { w$("scenario-cut-fields").hidden = !w$("scenario-cut-subscriptions").checked; });
  on("scenario-basis", "change", () => { w$("scenario-cash-field").hidden = w$("scenario-basis").value !== "blank"; });
  on("scenario-select", "change", () => {
    const value = w$("scenario-select").value;
    location.hash = wi2Href(value || "new");
  });
  on("scenario-form", "submit", async event => {
    event.preventDefault();
    if (!w$("scenario-name").value.trim()) { notice("Name the plan first.", true); wi2ShowTab("plan"); w$("scenario-name").focus(); return; }
    try {
      const body = JSON.stringify(scenarioRequest());
      const saved = scenarioId == null ? await api("/api/scenarios", {method: "POST", body}) : await api(`/api/scenarios/${scenarioId}`, {method: "PUT", body});
      scenarioId = saved.id; notice(`${saved.name} saved.`);
      await loadScenarios(); fillScenario(saved);
      const href = wi2Href(saved.id);
      history.replaceState(null, "", href);
      if (currentRoute?.name === "whatif") currentRoute.params = new URLSearchParams(href.split("?")[1] || "");
    } catch (error) { notice(error, true); }
  });
  on("scenario-duplicate", "click", async () => {
    try { const copy = await api(`/api/scenarios/${scenarioId}/duplicate`, {method: "POST"}); await loadScenarios(); location.hash = wi2Href(copy.id); }
    catch (error) { notice(error, true); }
  });
  on("scenario-delete", "click", async () => {
    const name = w$("scenario-name").value || "this plan";
    if (!await confirmAction({title: `Delete ${name}?`, message: "The plan and its paychecks are removed. Your records aren't changed.", confirmLabel: "Delete", danger: true})) return;
    try { await api(`/api/scenarios/${scenarioId}`, {method: "DELETE"}); scenarioId = null; await loadScenarios(); location.hash = wi2Href("new"); }
    catch (error) { notice(error, true); }
  });
  on("compare-run", "click", () => {
    const chosen = [...w$("compare-options").querySelectorAll("input:checked")].map(input => input.value);
    if (!chosen.length) { notice("Choose Now or a plan to compare.", true); return; }
    runCompare({scenarios: chosen.filter(value => value !== "now").map(Number), include_now: chosen.includes("now"), years: Number(w$("compare-years").value) || 10});
  });
  on("scenario-try", "click", () => {
    // The plan as it is on screen, saved or not, beside Now.
    const draft = scenarioRequest();
    draft.name = draft.name || "This plan";
    w$("compare-years").value = draft.forecast.years;
    runCompare({draft, include_now: true, years: draft.forecast.years}, {tried: true});
  });
  on("track-preview", "click", previewTracking);
  on("track-stop", "click", stopTracking);
}

// Opens the page: the plan named in the URL, then the planner. wi.opened: the form has been filled once.
async function openWhatIf(params = new URLSearchParams()) {
  const first = !wi.opened;
  wi.opened = true;
  try { await loadScenarios(); } catch (error) { notice(error, true); }
  const wanted = params.get?.("plan");
  if (wanted === "new" && (scenarioId != null || first)) fillScenario(null);
  else if (wanted && wanted !== "new" && String(scenarioId) !== wanted) {
    const found = scenarioView.scenarios.find(scenario => String(scenario.id) === wanted);
    if (found) fillScenario(found); else { notice("That plan no longer exists.", true); fillScenario(null); }
  } else if (!wanted && scenarioId == null && (first || !w$("scenario-name").value)) fillScenario(null);
  else renderScenarioChoices();
  await loadPlanner(params);
}
async function loadPlanner(params) {
  if (!planReady) {
    planReady = true;
    const state = w$("plan-state");
    state.append(Object.assign(document.createElement("option"), {value: "", textContent: "No state tax / not set"}));
    for (const [code, name] of Object.entries(PLAN_STATES)) state.append(Object.assign(document.createElement("option"), {value: code, textContent: name}));
    w$("plan-year").value = new Date().getFullYear();
    try { const status = (await api("/api/settings")).household.filing_status || "single"; w$("plan-status").value = status; } catch { /* The default stays. */ }
  }
  const stub = params.get?.("stub");
  if (stub) {
    try {
      const value = await api(`/api/paycheck/from-stub/${Number(stub)}`);
      fillPaycheck(value); notice("Started from the pay stub. Remove one-time lines to see a steady paycheck.");
    } catch (error) { notice(error, true); }
  }
  await runPaycheck();
}
