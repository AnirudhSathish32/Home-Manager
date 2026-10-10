"use strict";
// Taxes, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/taxes.md): six tabs over one tax year. This year
// is the answer, what to do and the return line by line; Built from and Jobs & pay stubs edit one shared draft of what the
// estimate is built from. Every amount and figure is the server's (finance/tax_traces.py refs); taxes.js keeps the shared
// pieces (Tax Zen's words, the field lists, the write-off and rule tables).
const TAXES2_TABS = ["year", "built", "writeoffs", "jobs", "pack", "rules"];
const TAXES2_SECTIONS = [["jobs", "Jobs"], ["income", "Income"], ["adjustments", "Adjustments"], ["deductions", "Deductions"], ["credits", "Credits"],
                         ["payments", "Payments"], ["state", "State"], ["people", "People"], ["last-year", "Last year"], ["businesses", "Businesses"]];
const TAXES2_JOB_FIELDS = [["wages", "Wages for the year"], ["federal_withheld", "Federal withheld, year"], ["state_withheld", "State withheld, year"], ["medicare_wages", "Medicare wages"]];
const TAXES2_W4 = [["credits", "Step 3 credits"], ["other_income", "Step 4(a) other income"], ["deductions", "Step 4(b) deductions"], ["extra", "Step 4(c) extra a paycheck"]];
// view: the shown return's tax view; family: the family's returns (family profile); draft: what Built from and Jobs edit,
// shaped like the PUT body; baseline: the draft as loaded, flattened, to count changes; stale: tabs to draw on their next show.
const taxes2 = {year: null, tab: "year", section: "income", unit: null, view: null, family: null, setup: null, summary: null, tags: [], rules: [],
                sources: null, draft: null, baseline: null, draftKey: null, stale: new Set(TAXES2_TABS)};

V2_SCREENS.taxes = {title: "Taxes", show: route => loadTaxesV2(route.params)};

const activateTaxes2Tab = wireTabs(TAXES2_TABS.map(tab => `taxes2-tab-${tab}`));
for (const tab of TAXES2_TABS) $(`taxes2-tab-${tab}`).addEventListener("tabshow", () => {
  taxes2.tab = tab; taxes2Url();
  if (taxes2.loaded && taxes2.stale.has(tab)) renderTaxes2Tab(tab);
});

function loadTaxesV2(params) {
  const now = new Date().getFullYear(), year = Number(params?.get?.("year")) || now;
  const select = $("taxes2-year");
  if (!select.options.length) for (let value = now + 1; value >= now - 5; value--) select.add(new Option(String(value), String(value)));
  select.value = String(year);
  taxes2.year = year;
  taxes2.tab = TAXES2_TABS.includes(params?.get?.("tab")) ? params.get("tab") : "year";
  if (TAXES2_SECTIONS.some(([key]) => key === params?.get?.("section"))) taxes2.section = params.get("section");
  if (params?.get?.("unit")) taxes2.unit = Number(params.get("unit"));
  taxes2.loaded = false;
  return pageState($("taxes2-state"), renderTaxesV2, {loading: "Loading this year's taxes …", what: "this year's taxes", needsLibrary: true, content: [$("taxes2-body")]});
}
async function renderTaxesV2() {
  const year = taxes2.year;
  for (const tab of ["writeoffs", "pack", "rules"]) $(`taxes2-tab-${tab}`).hidden = familyMode;
  $("taxes2-family-note").hidden = !familyMode;
  $("taxes2-unit-field").hidden = !familyMode;
  if (familyMode) {
    taxes2.family = await api(`/api/tax/family/${year}`);
    if (!["year", "built", "jobs"].includes(taxes2.tab)) taxes2.tab = "year";
    taxes2Family(taxes2.family);
  } else {
    taxes2.family = null; taxes2.unit = null;
    const [setup, view, summary, {tags}, {rules}] = await Promise.all([loadTaxSetup(true), api(`/api/tax/year/${year}`), api(`/api/tax/write-offs/${year}?currency=USD`),
      api(`/api/tax-tags?year=${year}`), api("/api/tax/rules")]);
    Object.assign(taxes2, {setup, summary, tags: tags.filter(tag => tag.review_status !== "rejected"), rules});
    taxes2Shown(view);
  }
}
// The family's returns: the unit select, and the shown return's view.
function taxes2Family(family) {
  const unit = $("taxes2-unit");
  unit.replaceChildren(...family.returns.map(item => new Option(`${item.name} · ${item.view.filing_status_name}`, String(item.id))));
  const shown = family.returns.find(item => item.id === taxes2.unit) || family.returns[0];
  taxes2.unit = shown?.id ?? null;
  unit.disabled = !shown;
  if (shown) unit.value = String(shown.id);
  taxes2Shown(shown ? shown.view : null);
}
// A view arrived (load or save): keep unsaved typing for the same return, else start the draft from what's saved.
function taxes2Shown(view) {
  taxes2.view = view;
  const key = `${taxes2.year}:${taxes2.unit}`;
  if (!view) taxes2.draft = null;
  else if (!(taxes2.draft && taxes2.draftKey === key && taxes2Changes())) taxes2ResetDraft();
  taxes2.draftKey = key;
  taxes2.stale = new Set(TAXES2_TABS); taxes2.loaded = true;
  taxes2Url();
  activateTaxes2Tab(`taxes2-tab-${taxes2.tab}`);  // Draws the tab (tabshow).
}
function taxes2Url() {
  const next = new URLSearchParams();
  if (taxes2.year !== new Date().getFullYear()) next.set("year", String(taxes2.year));
  if (taxes2.tab !== "year") next.set("tab", taxes2.tab);
  if (taxes2.tab === "built") next.set("section", taxes2.section);
  if (familyMode && taxes2.unit != null) next.set("unit", String(taxes2.unit));
  if (currentRoute?.name === "taxes") currentRoute.params = next;
  history.replaceState(null, "", `#/taxes${[...next].length ? `?${next}` : ""}`);
}
function renderTaxes2Tab(tab) {
  taxes2.stale.delete(tab);
  const host = $(`taxes2-${tab}-panel`);
  if (!taxes2.view && ["year", "built", "jobs"].includes(tab)) {
    host.replaceChildren(...(familyMode ? [taxes2FamilyList()] : []), emptyState(familyMode ? "Add a return to see its estimate." : "There's no estimate for this year yet."));
    return;
  }
  ({year: taxes2YearTab, built: taxes2BuiltTab, writeoffs: taxes2WriteOffsTab, jobs: taxes2JobsTab, pack: taxes2PackTab, rules: taxes2RulesTab})[tab](host);
}
async function taxes2Discard(message) {
  const count = taxes2Changes();
  if (!count) return true;
  return confirmAction({title: `Discard ${count} unsaved change${count === 1 ? "" : "s"}?`, message, confirmLabel: "Discard", danger: true});
}
$("taxes2-year").addEventListener("change", async () => {
  const select = $("taxes2-year");
  if (!await taxes2Discard("The values typed for this year haven't been saved.")) { select.value = String(taxes2.year); return; }
  taxes2.draft = null;
  const params = new URLSearchParams({year: select.value, tab: taxes2.tab});
  await loadTaxesV2(params);
});
$("taxes2-unit").addEventListener("change", async () => {
  const select = $("taxes2-unit");
  if (!await taxes2Discard("The values typed for this return haven't been saved.")) { select.value = String(taxes2.unit); return; }
  taxes2.draft = null; taxes2.unit = Number(select.value);
  taxes2Family(taxes2.family);
});

// The draft: what Built from and Jobs & pay stubs edit, shaped like the PUT body ---------------------------------
function taxes2ResetDraft() {
  const inputs = taxes2.view.inputs, w4 = {};
  for (const job of taxes2.view.gathered.jobs) {
    const saved = inputs.w4?.[job.key] || {};
    w4[job.key] = {...Object.fromEntries(Object.entries(saved).map(([key, value]) => [key, key === "step2" ? Boolean(value) : String(value ?? "")])), step2: Boolean(saved.step2)};
  }
  const strings = object => Object.fromEntries(Object.entries(object || {}).map(([key, value]) => [key, typeof value === "boolean" ? value : String(value ?? "")]));
  const nested = object => Object.fromEntries(Object.entries(object || {}).map(([key, value]) => [key, strings(value)]));
  const spouse = (inputs.people || [])[0];
  taxes2.draft = {...inputs, fields: strings(inputs.fields), jobs: nested(inputs.jobs), businesses: nested(inputs.businesses),
                  extra_jobs: (inputs.extra_jobs || []).map(strings), w4,
                  spouse: {name: spouse?.name || "", birth_year: spouse?.birth_year ? String(spouse.birth_year) : ""},
                  prior: {tax: String(inputs.prior_year_tax?.tax ?? ""), agi: String(inputs.prior_year_tax?.agi ?? "")}};
  taxes2.baseline = taxes2Flat(taxes2Request());
}
// The PUT body from the draft, trimmed as v1's taxInputsRequest trims the form.
function taxes2Request() {
  const draft = taxes2.draft, filled = value => typeof value === "string" ? value.trim() !== "" : value != null;
  const kept = object => Object.fromEntries(Object.entries(object || {}).filter(([, value]) => filled(value)).map(([key, value]) => [key, typeof value === "string" ? value.trim() : value]));
  const fields = kept(draft.fields);
  if (fields.itemize !== true) delete fields.itemize;
  const nested = object => Object.fromEntries(Object.entries(object || {}).map(([key, value]) => [key, kept(value)]).filter(([, value]) => Object.keys(value).length));
  const w4 = Object.fromEntries(Object.entries(draft.w4 || {}).map(([key, entry]) => [key, {...kept(Object.fromEntries(Object.entries(entry).filter(([name]) => name !== "step2"))), step2: Boolean(entry.step2)}]));
  const extra_jobs = (draft.extra_jobs || []).map(job => Object.fromEntries(["name", "wages", "federal_withheld", "state_withheld"].map(key => [key, (job[key] || "").trim()])))
    .filter(job => job.wages || job.federal_withheld);
  const spouse = draft.spouse, prior = draft.prior;
  const people = spouse.name.trim() || spouse.birth_year ? [{name: spouse.name.trim() || "Spouse", birth_year: Number(spouse.birth_year) || null}] : [];
  const prior_year_tax = prior.tax.trim() ? {tax: prior.tax.trim(), agi: prior.agi.trim() || null} : null;
  const {spouse: _spouse, prior: _prior, ...rest} = draft;
  return {...rest, fields, jobs: nested(draft.jobs), businesses: nested(draft.businesses), extra_jobs, people, w4, prior_year_tax};
}
function taxes2Flat(value, path = "", out = {}) {
  if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) taxes2Flat(item, path ? `${path}.${key}` : key, out);
  else out[path] = String(value ?? "");
  return out;
}
// How many values differ from what's saved.
function taxes2Changes() {
  if (!taxes2.draft || !taxes2.baseline) return 0;
  const now = taxes2Flat(taxes2Request()), before = taxes2.baseline;
  return [...new Set([...Object.keys(now), ...Object.keys(before)])].filter(key => now[key] !== before[key]).length;
}
// One delegated listener per editing panel writes each control into the draft by its data attributes.
function taxes2Edit(event) {
  const input = event.target, draft = taxes2.draft, data = input.dataset;
  if (!draft || !input.matches("input, select")) return;
  const value = input.type === "checkbox" ? input.checked : input.value;
  if (data.field === "itemize") draft.fields.itemize = value === "yes";
  else if (data.field) draft.fields[data.field] = value;
  else if (data.job) (draft.jobs[data.job] ||= {})[data.key] = value;
  else if (data.business) (draft.businesses[data.business] ||= {})[data.key] = value;
  else if (data.w4) (draft.w4[data.w4] ||= {step2: false})[data.key] = value;
  else if (data.extra != null) draft.extra_jobs[Number(data.extra)][data.key] = value;
  else if (data.spouse) draft.spouse[data.spouse] = value;
  else if (data.prior) draft.prior[data.prior] = value;
  else return;
  taxes2SaveBars();
  taxes2SectionCounts();
}
for (const id of ["taxes2-built-panel", "taxes2-jobs-panel"]) for (const kind of ["input", "change"]) $(id).addEventListener(kind, taxes2Edit);

function taxes2SaveBar() {
  const bar = element("div", "", "taxes2-savebar"), count = element("span", "", "taxes2-savebar-count");
  count.setAttribute("aria-live", "polite");
  const discard = element("button", "Discard", "secondary"), save = element("button", "Save and estimate again", "primary");
  discard.type = save.type = "button";
  discard.addEventListener("click", () => { taxes2ResetDraft(); taxes2.stale = new Set(TAXES2_TABS); renderTaxes2Tab(taxes2.tab); });
  save.addEventListener("click", async () => {
    bar.querySelector(".alert")?.remove();
    save.disabled = discard.disabled = true;
    try {
      await taxes2Save(taxes2Request());
      notice("Saved; the return is estimated again.");
    } catch (error) {
      bar.append(alertBox(`Couldn't save. ${error.message || error}`, {tone: "error", detail: error.detail || ""}));
      taxes2SaveBars();
    }
  });
  bar.append(count, discard, save);
  return bar;
}
function taxes2SaveBars() {
  const count = taxes2Changes();
  for (const bar of document.querySelectorAll(".taxes2-savebar")) {
    bar.querySelector(".taxes2-savebar-count").textContent = count ? `${count} unsaved change${count === 1 ? "" : "s"}` : "No changes";
    for (const button of bar.querySelectorAll("button")) button.disabled = !count;
  }
}
// Saves the inputs (a person's year, or the family return shown) and shows the return worked out again. keepDraft: a
// save from This year (the aim, the job) keeps unsaved typing in Built from.
async function taxes2Save(inputs, {keepDraft = false} = {}) {
  const year = taxes2.view.year;
  if (taxes2.unit == null) {
    const view = await api(`/api/tax/year/${year}`, {method: "PUT", body: JSON.stringify(inputs)});
    if (!keepDraft) taxes2.draft = null;
    taxes2Shown(view);
  } else {
    taxes2.family = await api(`/api/tax/family/${year}/${taxes2.unit}`, {method: "PUT", body: JSON.stringify(inputs)});
    if (!keepDraft) taxes2.draft = null;
    taxes2Family(taxes2.family);
  }
}

// This year ------------------------------------------------------------------------------------------------------
function taxes2Tile(label, fig, options, sub) {
  const tile = element("div", "", "figure-tile");
  tile.append(element("p", label, "figure-label"), figure(fig, {size: "lg", ...options}));
  if (sub) { const line = element("p", "", "figure-sub"); line.append(...[].concat(sub)); tile.append(line); }
  return tile;
}
// A Tax Zen year-end amount in words: "a refund of 12.00 USD" / "owing 12.00 USD" (the label carries the direction).
function taxes2Ends(minor, fig) {
  const words = minor >= 0 ? "a refund of " : "owing ";
  return fig?.trace ? [words, figure(fig, {size: "inline", magnitude: true})] : [words + (fig?.display || "").replace("-", "")];
}
function taxes2YearTab(host) {
  const view = taxes2.view, result = view.return, zen = view.zen, parts = [];
  if (familyMode) parts.push(taxes2FamilyList());
  const alerts = taxTableAlerts(view);
  if (alerts.length) { const box = element("div", "", "taxes2-alerts"); box.append(...alerts); parts.push(box); }
  if (result.result_minor == null) {
    const fix = element("button", "Fill in what's missing", "link-button"); fix.type = "button";
    fix.addEventListener("click", () => activateTaxes2Tab("taxes2-tab-built"));
    const action = element("p", "", "button-row"); action.append(fix);
    if (zen?.status === "INSUFFICIENT_DATA") action.append(homeLink("Open Settings", "#/settings"));
    parts.push(emptyState(result.notes[0] || "There's no estimate for this year yet.", action));
    if (zen?.note && zen.note !== result.notes[0]) parts.push(element("p", zen.note, "muted small"));
    host.replaceChildren(...parts);
    return;
  }
  // The answer: where the year ends, the year's tax, and what's paid against it.
  const refund = result.result.refund, zero = result.result_minor === 0;
  const tiles = element("div", "", "taxes2-answer");
  let sub = null;
  const range = zen?.range;
  if (range?.figures && range.low_minor !== range.high_minor) {
    // Unsigned when both ends fall the same way as the result; signed when the range crosses $0.
    const same = Math.sign(range.low_minor) === Math.sign(range.high_minor);
    const end = fig => figure(fig, {size: "inline", signed: true, magnitude: same});
    sub = ["Likely ", end(range.figures.low), " – ", end(range.figures.high), ` · ${range.confidence} confidence`];
  }
  tiles.append(taxes2Tile(zero ? "Tax Zen" : refund ? "Refund" : "You'd owe", result.result_figure, {signed: refund, magnitude: !refund}, sub));
  const line = key => result.lines.find(item => item.key === key);
  tiles.append(taxes2Tile("Total tax", line("total_tax").figure, {magnitude: true}, result.marginal_percent != null ? `Top federal bracket ${result.marginal_percent}%` : ""),
               taxes2Tile("Paid and credited", line("total_payments").figure, {magnitude: true}, "Withholding projected to Dec 31"));
  parts.push(tiles);
  // Which engine slot worked it out (finance/tax_engine.py): "Engine 1", never an engine's own name.
  const engine = result.engine?.label || "the tax engine", comparison = result.comparison;
  const other = comparison?.engine?.label || "The other engine";
  parts.push(element("p", `${view.year} · filing ${view.filing_status_name} · worked out by ${engine}` + (comparison?.ready && comparison.agree ? ` · ${other} agrees ✓` : ""), "muted small taxes2-meta"));
  parts.push(taxes2Advice(view));
  // The return, line by line.
  const title = element("h2", "The return, line by line"); title.id = "taxes2-return-title";
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table taxes2-return");
  table.setAttribute("aria-labelledby", "taxes2-return-title");
  let section = null, body = null;
  for (const item of result.lines) {
    if (!item.amount_minor && item.section !== "total" && !["wages", "tax"].includes(item.key)) continue;  // Nothing there: left out, as v1.
    if (item.section !== section && item.section !== "total") {
      section = item.section; body = table.appendChild(document.createElement("tbody"));
      const head = body.insertRow().appendChild(element("th", RETURN_SECTIONS[section] || section, "taxes2-group")); head.colSpan = 2; head.scope = "rowgroup";
    }
    body = body || table.appendChild(document.createElement("tbody"));
    const tr = body.insertRow(); if (item.section === "total") tr.className = "total";
    const th = tr.appendChild(element("th", item.label)); th.scope = "row";
    if (item.how) th.append(element("small", item.how, "muted block"));
    tr.appendChild(element("td", "", "numeric")).append(figure(item.figure, {size: "inline", signed: false}));
  }
  wrap.append(table); parts.push(title, wrap);
  if (comparison && !comparison.ready) parts.push(alertBox(`${other} gave no estimate to compare: ${comparison.note}`, {tone: "info"}));
  else if (comparison && !comparison.agree) {
    const box = alertBox(`The engines disagree: ${other} has ${comparison.other_refund ? "a refund of" : "you owing"} ${comparison.display.other_result}`
      + ` (${comparison.display.difference} apart). Check the lines above before relying on either.`, {tone: "warning"});
    const diffWrap = element("div", "", "table-wrap"), diff = element("table", "", "data-table"), head = diff.createTHead().insertRow();
    for (const [name, numeric] of [["Line", false], [engine, true], [other, true], ["Difference", true]]) { const th = head.appendChild(element("th", name, numeric ? "numeric" : "")); th.scope = "col"; }
    const rows = diff.createTBody();
    for (const item of comparison.lines) {
      const tr = rows.insertRow(); const th = tr.appendChild(element("th", item.label)); th.scope = "row";
      for (const key of ["this", "other", "difference"]) tr.appendChild(element("td", "", "numeric")).append(amount(item.display[key], {signed: key === "difference"}));
    }
    diffWrap.append(diff); box.querySelector(".alert-body").append(diffWrap); parts.push(box);
  }
  if (result.state) parts.push(element("p", result.state.complete
    ? `${result.state.state} (simplified): tax ${result.state.display.tax_minor}, paid ${result.state.display.payments_minor}: ${result.state.result_minor >= 0 ? "refund" : "owed"} ${result.state.display.result_minor}. ${result.state.note}`
    : `${result.state.state}: ${result.state.note}`, "small"));
  const about = element("details", "", "taxes2-about"), notes = element("ul", "", "forecast-notes");
  for (const note of [...result.notes, ...view.gathered.notes]) notes.append(element("li", note));
  about.append(element("summary", "About these numbers"), notes); parts.push(about);
  host.replaceChildren(...parts);
}
// What to do: Tax Zen's one action first, its reason and timing, then the other ways folded away.
function taxes2Advice(view) {
  const zen = view.zen, region = element("section", "", "panel taxes2-advice"), head = element("div", "", "taxes2-advice-head");
  region.setAttribute("aria-labelledby", "taxes2-advice-title");
  const title = element("h2", "What to do"); title.id = "taxes2-advice-title";
  head.append(title);
  if (zen?.status) head.append(statusBadge(ZEN_BADGES[zen.status]));
  region.append(head);
  if (!zen?.ready) { region.append(element("p", zen?.note || "", "muted small")); return region; }
  const aim = zenPolicyForm(view, {ids: {strategy: "taxes2-zen-strategy", amount: "taxes2-zen-amount"}, save: inputs => taxes2Save(inputs, {keepDraft: true})});
  aim.className = "taxes2-aim"; head.append(aim);
  const job = zen.job, acting = job && !["ZEN", "WATCH", "AT_RISK", "REVIEW_REQUIRED"].includes(zen.status);
  const lead = element("p", "", "taxes2-advice-lead"), second = element("p", "", "small muted");
  const entry = job?.rest?.field === "4(a)" ? "Step 4(a), other income" : "Step 4(b), deductions";
  const checked = part => part.checked ? " Checked: working the return out again with it ends the year there." : part.checked === false ? " It couldn't be checked against the return; treat it as approximate." : "";
  if (zen.zen) lead.textContent = `You're Tax Zen for ${view.year}: the return comes out at your aim (${zen.display.aim}).`;
  else if (acting && job.rest.unreachable) lead.textContent = `No W-4 entry at ${job.name} can close this with ${job.paychecks_left} paychecks left: withholding can't go below zero. `
    + "The rest comes back as a refund; see January below.";
  else if (acting && job.primary === "extra") {
    lead.append(`On ${job.name}'s W-4, add `, figure(job.extra.figure, {size: "inline", magnitude: true}), " of extra withholding a paycheck (Step 4(c)).");
    second.append(`That's ${job.extra.display.total_4c_minor} in Step 4(c) in all. The year then ends at `, ...taxes2Ends(job.extra.year_end_minor, {display: job.extra.display.year_end_minor}), `.${checked(job.extra)}`);
  } else if (acting) {
    lead.append(`On ${job.name}'s W-4, put `, element("strong", job.rest.display.amount), ` in ${entry}, for the ${job.paychecks_left} paychecks it changes this year.`);
    second.append("Withholding becomes ", figure(job.rest.figures.per_check, {size: "inline", signed: false}), ` a paycheck (now ${job.display.per_check_now_minor}), and the year then ends at `,
                  ...taxes2Ends(job.rest.year_end_minor, job.rest.figures.year_end), `. The amount replaces what's in that box now; leave the other boxes as they are.${checked(job.rest)}`);
  } else if (!job && zen.advance && !zen.zen) lead.append("Pay ", figure(zen.advance.figure, {size: "inline", signed: false}), " as estimated tax (1040-ES); quarters below.");
  else lead.textContent = zen.reason;
  region.append(lead);
  if (acting) {
    // When a new W-4 takes effect (§21).
    const payroll = job.payroll || {};
    if (payroll.delay_checks) second.append(` A W-4 handed in now takes effect after ${payroll.delay_checks === 1 ? "the next paycheck" : `the next ${payroll.delay_checks} paychecks`}`
      + `${payroll.next_pay_date ? ` (${dateText(payroll.next_pay_date)})` : ""}, so it changes ${job.paychecks_left} of the ${payroll.paychecks_left} left.`);
  }
  if (second.hasChildNodes()) region.append(second);
  if (zen.cushion) region.append(element("p", zen.cushion.text, "small"));
  if (job?.steady && acting) region.append(element("p", job.steady.text, "small muted"));
  // Other ways: the other W-4 entry, Step 3, January, another job, or estimated tax instead.
  const ways = [];
  if (acting) {
    if (job.primary === "extra" && !job.rest.unreachable) ways.push(element("p", `Or put ${job.rest.display.amount} in ${entry} instead.`, "small"));
    else if (job.extra && job.primary !== "extra") {
      const line = element("p", "", "small");
      line.append("Or keep the W-4 as it is and add ", figure(job.extra.figure, {size: "inline", magnitude: true}), ` of extra withholding a paycheck (Step 4(c): ${job.extra.display.total_4c_minor} in all).`);
      ways.push(line);
    }
    if (job.step3) {
      const line = element("p", "", "small");
      line.append(`Or, since the W-4 claims dependents, raise Step 3 to ${job.step3.display.amount}: withholding becomes `, figure(job.step3.figures.per_check, {size: "inline", signed: false}),
                  " a paycheck and the year ends at ", ...taxes2Ends(job.step3.year_end_minor, job.step3.figures.year_end), ".");
      ways.push(line);
    }
    const january = job.january;
    if (january.field && january.amount != null) ways.push(element("p", `From January, for a full year at this pay: ${january.field === "4(a)" ? "Step 4(a)" : "Step 4(b)"} ${january.display.amount}. `
      + `Check again when ${view.year + 1}'s tax tables are confirmed.`, "small"));
    else if (!january.field) ways.push(element("p", "From January, at this pay, the W-4 as it is comes out even.", "small"));
    if (zen.choices?.length > 1) {
      const pick = planSelect("taxes2-zen-job", Object.fromEntries(zen.choices.map(choice => [choice.key, choice.name])), job.key);
      pick.addEventListener("change", async () => { try { await taxes2Save({...view.inputs, zen_job: pick.value}, {keepDraft: true}); } catch (error) { notice(error, true); } });
      ways.push(forecastField("Change the W-4 at", pick));
    }
  }
  const advance = zen.advance;
  if (advance && (!job || advance.left_minor)) {
    const block = element("div", "", "taxes2-advance");
    block.append(element("h3", job && !zen.zen ? "Or pay it as estimated tax instead (quarterly, 1040-ES)" : "Advance tax (quarterly estimated payments)"));
    const needs = element("p", "", "small");
    needs.append("Estimated payments need to cover ", figure(advance.figure, {size: "inline", signed: false}), `; ${advance.display.paid_minor} is paid so far (tagged IRS payments).`
      + (advance.safe_harbor_minor != null ? ` To avoid a penalty, at least ${advance.display.safe_harbor_minor} over the year.` : ""));
    block.append(needs, trackTable([["Quarter", false], ["Due", false], ["Paid", true], ["Pay", true], ["Safe harbor by then", true]], advance.quarters, (tr, row) => {
      cell(tr, `Q${row.quarter}`); tr.insertCell().append(dateDisplay(row.due)); trackMoney(tr, row.display.paid_minor); trackMoney(tr, row.display.pay_minor);
      trackMoney(tr, row.display.safe_by_now_minor || "—");
    }), ...advance.notes.map(note => element("p", note, "muted small")));
    if (job && !zen.zen) ways.push(block); else region.append(block);
  }
  if (ways.length) {
    const details = element("details", "", "taxes2-ways");
    details.append(element("summary", "Other ways"), ...ways); region.append(details);
  }
  if (zen.changed?.texts?.length) {
    const changed = element("details"), list = element("ul", "", "small");
    changed.append(element("summary", "What changed since Tax Zen last looked"));
    for (const text of zen.changed.texts) list.append(element("li", text));
    changed.append(list); region.append(changed);
  }
  if (zen.state) region.append(element("p", zen.state.text, "muted small"));
  region.append(...zen.notes.map(note => element("p", note, "muted small")));
  return region;
}
// The family view's returns, above the shown one's answer.
function taxes2FamilyList() {
  const family = taxes2.family, box = element("div", "", "taxes2-family");
  if (family.returns.length) box.append(element("p", family.zen ? "The family is Tax Zen: every return comes out within a dollar of $0." : "Not every return is at $0 yet.", "taxes2-family-zen"));
  if (family.returns.length) {
    box.append(trackTable([["Name", false], ["Filing", false], ["Result", true], ["", false]], family.returns, (tr, item) => {
      const result = item.view.return;
      cell(tr, item.name); cell(tr, item.view.filing_status_name);
      const shown = tr.appendChild(element("td", "", "numeric"));
      if (result.result_minor == null) shown.append(result.notes[0] || "—");
      else shown.append(result.result_minor === 0 ? "Tax Zen " : result.result.refund ? "Refund " : "Owes ",
                        figure(result.result_figure, {size: "inline", signed: result.result.refund, magnitude: !result.result.refund}));
      const actions = tr.insertCell();
      const open = element("button", taxes2.unit === item.id ? "Shown" : "Open", "small"); open.type = "button"; open.disabled = taxes2.unit === item.id;
      open.addEventListener("click", async () => {
        if (!await taxes2Discard("The values typed for this return haven't been saved.")) return;
        taxes2.draft = null; taxes2.unit = item.id; taxes2Family(family);
      });
      actions.append(open, asyncButton("Remove", async () => {
        if (!await confirmAction({title: `Remove the return “${item.name}”?`, message: "Its typed values go with it; members' records aren't changed.", confirmLabel: "Remove", danger: true})) return;
        await api(`/api/tax/units/${item.id}`, {method: "DELETE"});
        if (taxes2.unit === item.id) { taxes2.unit = null; taxes2.draft = null; }
        await loadTaxesV2(new URLSearchParams({year: String(taxes2.year)}));
      }, "small quiet"));
    }));
  }
  if (family.members.some(member => !member.on_a_return)) {
    box.append(element("h2", "Add a return"), familyUnitForm(family, () => loadTaxesV2(new URLSearchParams({year: String(taxes2.year)}))));
  } else if (!family.returns.length) box.append(emptyState("No one in the family has shared records yet."));
  return box;
}

// Built from -----------------------------------------------------------------------------------------------------
let taxes2RowId = 0;
// One row: what the box is (with the kind of value), what the records give, and what you typed.
function taxes2Row(label, kind, records, control) {
  const row = element("div", "", "taxes2-row"), box = element("div", "", "taxes2-box"), name = element("span", label, "taxes2-box-label");
  name.id = `taxes2-row-${++taxes2RowId}`;
  box.append(name);
  if (kind) box.append(element("small", kind[1], `block value-kind value-kind-${kind[0]}`));
  const from = element("div", "", "taxes2-records"), yours = element("div", "", "taxes2-yours");
  from.append(...[].concat(records ?? element("span", "—", "muted")));
  if (control) { control.setAttribute("aria-labelledby", name.id); yours.append(control); }
  row.append(box, from, yours);
  return row;
}
function taxes2Rows(rows) {
  const grid = element("div", "", "taxes2-rows"), head = element("div", "", "taxes2-row taxes2-row-head");
  head.setAttribute("aria-hidden", "true");
  head.append(element("span", "Box"), element("span", "From records", "taxes2-records"), element("span", "Yours"));
  grid.append(head, ...rows);
  return grid;
}
function taxes2Money(value, placeholder = "0.00") {
  const input = document.createElement("input"); input.inputMode = "decimal"; input.value = value ?? ""; input.placeholder = placeholder;
  return input;
}
// Typed values in a section, for its count.
function taxes2Typed(section) {
  const draft = taxes2.draft, typed = value => typeof value === "string" ? value.trim() !== "" : value === true;
  if (!draft) return 0;
  const group = RETURN_FIELDS.find(([title]) => title.toLowerCase() === section);
  if (group) {
    const keys = group[1].map(([key]) => key).concat(section === "adjustments" ? ["hsa_coverage"] : section === "deductions" ? ["itemize", "tipped_occupation"] : []);
    return keys.filter(key => typed(draft.fields[key])).length;
  }
  const count = object => Object.values(object || {}).reduce((total, entry) => total + Object.values(entry).filter(typed).length, 0);
  if (section === "jobs") return count(draft.jobs) + (draft.extra_jobs || []).filter(job => typed(job.wages || "") || typed(job.federal_withheld || "")).length;
  if (section === "businesses") return count(draft.businesses);
  if (section === "people") return [draft.spouse.name, draft.spouse.birth_year].filter(typed).length;
  if (section === "last-year") return [draft.prior.tax, draft.prior.agi].filter(typed).length;
  return 0;
}
function taxes2SectionCounts() {
  for (const [key] of TAXES2_SECTIONS) {
    const count = $(`taxes2-sec-${key}`)?.querySelector(".nav-count");
    if (count) count.textContent = taxes2Typed(key) ? String(taxes2Typed(key)) : "";
  }
  const typed = $("taxes2-section-typed");
  if (typed) typed.textContent = `${taxes2Typed(taxes2.section)} typed`;
}
function taxes2BuiltTab(host) {
  const layout = element("div", "", "taxes2-built"), list = element("div", "", "taxes2-sections");
  list.setAttribute("role", "tablist"); list.setAttribute("aria-label", "What it's built from"); list.setAttribute("aria-orientation", "vertical");
  const picker = planSelect("taxes2-section", Object.fromEntries(TAXES2_SECTIONS), taxes2.section);
  picker.setAttribute("aria-label", "Section");
  const body = element("section", "", "taxes2-section-body"); body.id = "taxes2-section-body";
  for (const [key, label] of TAXES2_SECTIONS) {
    const button = element("button", "", ""); button.type = "button"; button.id = `taxes2-sec-${key}`;
    button.setAttribute("role", "tab"); button.setAttribute("aria-controls", `taxes2-secpanel-${key}`);
    button.append(element("span", label), element("span", "", "nav-count"));
    list.append(button);
    const panel = element("div", "", "taxes2-secpanel"); panel.id = `taxes2-secpanel-${key}`;
    panel.setAttribute("role", "tabpanel"); panel.setAttribute("aria-labelledby", button.id); panel.hidden = true;
    body.append(panel);
  }
  const intro = element("p", "Blank values use your records. Type over any of them; typed values are saved for this year.", "muted small taxes2-built-intro");
  layout.append(list, element("div", "", "taxes2-built-main"));
  layout.lastElementChild.append(picker, intro, body);
  host.replaceChildren(layout, taxes2SaveBar());
  const activate = wireTabs(TAXES2_SECTIONS.map(([key]) => `taxes2-sec-${key}`));
  for (const [key] of TAXES2_SECTIONS) $(`taxes2-sec-${key}`).addEventListener("tabshow", () => {
    taxes2.section = key; picker.value = key; taxes2Url();
    taxes2Section(key);
  });
  picker.addEventListener("change", () => activate(`taxes2-sec-${picker.value}`));
  activate(`taxes2-sec-${taxes2.section}`);
  taxes2SaveBars();
}
function taxes2Section(key) {
  const panel = $(`taxes2-secpanel-${key}`), view = taxes2.view, draft = taxes2.draft, gathered = view.gathered;
  const label = TAXES2_SECTIONS.find(([name]) => name === key)[1];
  const heading = element("div", "", "taxes2-section-head"), title = element("h2", label), typed = element("span", "", "muted small");
  typed.id = "taxes2-section-typed";
  for (const other of document.querySelectorAll("#taxes2-section-typed")) other.removeAttribute("id");
  heading.append(title, typed);
  const parts = [heading];
  const money = (data, value, placeholder) => { const input = taxes2Money(value, placeholder); Object.assign(input.dataset, data); return input; };
  const group = RETURN_FIELDS.find(([name]) => name.toLowerCase() === key);
  if (group) {
    const rows = [];
    for (const [field, name, count] of group[1]) {
      let control;
      if (count) { control = document.createElement("input"); control.type = "number"; control.min = "0"; control.max = "20"; control.placeholder = String(view.input[field] ?? 0); control.value = draft.fields[field] ?? ""; control.dataset.field = field; }
      else control = money({field}, draft.fields[field], "");
      const records = gathered.kinds?.[field] === "to_enter" ? element("span", "Enter it", "muted") : gathered.figures?.[field] ? figure(gathered.figures[field], {size: "inline", signed: false}) : null;
      rows.push(taxes2Row(name, valueKindText(draft.fields[field], gathered, field), records, control));
    }
    if (key === "adjustments") {
      const recorded = {self: "Self-only", family: "Family"}[gathered.values.hsa_coverage];
      const coverage = planSelect("taxes2-field-hsa_coverage", {"": recorded ? `From records: ${recorded}` : "Not said", self: "Self-only", family: "Family"}, draft.fields.hsa_coverage || "");
      coverage.dataset.field = "hsa_coverage";
      rows.push(taxes2Row("HSA coverage", valueKindText(draft.fields.hsa_coverage, gathered, "hsa_coverage"), recorded ? element("span", recorded) : null, coverage));
    }
    if (key === "deductions") {
      const choose = planSelect("taxes2-field-itemize", {auto: "Whichever is larger", yes: "Itemize"}, draft.fields.itemize === true ? "yes" : "auto"); choose.dataset.field = "itemize";
      const jobs = Object.fromEntries([["", "Not said"], ...view.tipped_occupations.map(slug => [slug, slug === "other" ? "Not on the list" : slug.replaceAll("-", " ")])]);
      const occupation = planSelect("taxes2-field-tipped_occupation", jobs, draft.fields.tipped_occupation || ""); occupation.dataset.field = "tipped_occupation";
      rows.push(taxes2Row("Deduction", null, null, choose), taxes2Row("Tipped occupation (Treasury list)", null, null, occupation));
    }
    parts.push(taxes2Rows(rows));
  } else if (key === "jobs") {
    for (const job of gathered.jobs) {
      const unrecorded = job.paydays_without_stub;
      parts.push(element("h3", job.name, "taxes2-job-name"), element("p", `${VALUE_KINDS[job.kind] || VALUE_KINDS.record}: ${job.stubs} pay stub${job.stubs === 1 ? "" : "s"} through ${dateText(job.last_pay_date)}`
        + (unrecorded ? `; ${unrecorded} payday${unrecorded === 1 ? "" : "s"} since then without a stub here, counted like the last one` : "")
        + `${job.ytd_printed ? "" : ". Year-to-date figures weren't printed, so the stubs are added up"}.`, "muted small"));
      parts.push(taxes2Rows(TAXES2_JOB_FIELDS.map(([field, name]) => taxes2Row(name, null, figure(job.figures?.[field], {size: "inline", signed: false}),
        money({job: job.key, key: field}, draft.jobs[job.key]?.[field], job.display[field])))));
    }
    const extra = element("div", "", "taxes2-extra-jobs");
    (draft.extra_jobs || []).forEach((job, index) => {
      const set = element("div", "", "taxes2-extra-job"), head = element("div", "", "taxes2-section-head");
      const remove = element("button", "Remove", "quiet small"); remove.type = "button";
      remove.addEventListener("click", () => { draft.extra_jobs.splice(index, 1); taxes2Section("jobs"); taxes2SaveBars(); taxes2SectionCounts(); });
      head.append(element("h3", job.name?.trim() || "A job not in your pay stubs"), remove);
      const name = document.createElement("input"); name.maxLength = 60; name.value = job.name || ""; name.dataset.extra = String(index); name.dataset.key = "name";
      set.append(head, taxes2Rows([taxes2Row("Job (e.g. your spouse's)", null, null, name),
        ...[["wages", "Wages for the year"], ["federal_withheld", "Federal withheld"], ["state_withheld", "State withheld"]].map(([field, label]) => taxes2Row(label, null, null,
          money({extra: String(index), key: field}, job[field], "0.00")))]));
      extra.append(set);
    });
    const add = element("button", "Add a job not in your pay stubs", "secondary"); add.type = "button";
    add.addEventListener("click", () => { draft.extra_jobs = [...(draft.extra_jobs || []), {name: "", wages: "", federal_withheld: "", state_withheld: ""}]; taxes2Section("jobs"); $(`taxes2-secpanel-jobs`).querySelector(".taxes2-extra-job:last-child input")?.focus(); });
    if (!gathered.jobs.length && !(draft.extra_jobs || []).length) parts.push(element("p", "No confirmed pay stubs for this year. Add a job by hand, or add pay stubs in Documents › Jobs.", "muted small"));
    parts.push(extra, add);
  } else if (key === "people") {
    const name = document.createElement("input"); name.maxLength = 60; name.placeholder = "Only when filing jointly"; name.value = draft.spouse.name; name.dataset.spouse = "name";
    const year = document.createElement("input"); year.type = "number"; year.min = "1900"; year.max = "2100"; year.value = draft.spouse.birth_year; year.dataset.spouse = "birth_year";
    parts.push(element("p", "Your spouse on this return. A birth year of 65 or more years ago counts for the larger standard deduction.", "muted small"),
               taxes2Rows([taxes2Row("Spouse's name", null, null, name), taxes2Row("Spouse's birth year", null, null, year)]));
  } else if (key === "last-year") {
    parts.push(element("p", "Last year's return, for the estimated-tax safe harbor.", "muted small"),
               taxes2Rows([taxes2Row("Total tax (Form 1040 line 24)", null, null, money({prior: "tax"}, draft.prior.tax, "Form 1040 line 24")),
                           taxes2Row("AGI (Form 1040 line 11)", null, null, money({prior: "agi"}, draft.prior.agi, "Form 1040 line 11"))]));
    if (view.prior_year?.source) parts.push(element("p", view.prior_year.source, "muted small"));
  } else if (key === "businesses") parts.push(...taxes2Businesses());
  else parts.push(element("p", "Nothing here.", "muted small"));
  panel.replaceChildren(...parts);
  taxes2SectionCounts();
}
// Businesses (Schedule C): each one's income and expenses from tagged items, typed over; rename, remove, add.
function taxes2Businesses() {
  const view = taxes2.view, draft = taxes2.draft, parts = [element("p", "Each business gets its own Schedule C. Contract (1099) work is a business to the IRS even without a company.", "muted small")];
  const reload = async () => { await loadTaxSetup(true); await loadTaxesV2(new URLSearchParams({year: String(taxes2.year), tab: "built", section: "businesses"})); };
  const businesses = taxes2.setup?.businesses || [];
  for (const business of businesses) {
    const key = `business-${business.id}`, found = view.gathered.businesses.find(item => item.key === key);
    const set = element("div", "", "taxes2-business"), head = element("div", "", "taxes2-section-head"), name = element("h3", business.name);
    const rename = element("button", "Rename", "link-button"); rename.type = "button";
    rename.addEventListener("click", () => {
      const form = element("form", "", "inline taxes2-rename"), input = document.createElement("input"); input.maxLength = 60; input.value = business.name;
      input.setAttribute("aria-label", "Business name");
      const save = element("button", "Save", "small primary"); save.type = "submit";
      const cancel = element("button", "Cancel", "small quiet"); cancel.type = "button"; cancel.addEventListener("click", () => form.replaceWith(head));
      form.append(input, save, cancel);
      form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!input.value.trim()) return;
        try { await api(`/api/tax/businesses/${business.id}`, {method: "PUT", body: JSON.stringify({name: input.value.trim()})}); notice("Renamed."); await reload(); }
        catch (error) { notice(error, true); }
      });
      head.replaceWith(form); input.focus();
    });
    const remove = asyncButton("Remove", async () => {
      if (!await confirmAction({title: `Remove the business “${business.name}”?`, message: "Its tags stay on their items; it no longer gets a Schedule C.", confirmLabel: "Remove", danger: true})) return;
      await api(`/api/tax/businesses/${business.id}`, {method: "DELETE"}); notice(`${business.name} removed.`); await reload();
    }, "small quiet");
    head.append(name, rename, remove);
    const mine = draft.businesses[key] || {};
    const row = (field, label) => {
      const input = taxes2Money(mine[field], found?.display?.[field] || "0.00"); input.dataset.business = key; input.dataset.key = field;
      return taxes2Row(label, null, found ? element("span", found.display[field], "amount") : null, input);
    };
    set.append(head, taxes2Rows([row("income", "Income for the year"), row("expenses", "Expenses that count")]));
    parts.push(set);
  }
  if (!businesses.length) parts.push(element("p", "None yet. Contract (1099) work counts as a business: add one to tag its income and expenses.", "muted small"));
  const form = element("form", "", "inline taxes2-business-form"), input = document.createElement("input");
  input.id = "taxes2-business-name"; input.maxLength = 60; input.placeholder = "Contract work";
  const add = element("button", "Add", ""); add.type = "submit";
  form.append(forecastField("Add a business", input), add);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const name = input.value.trim();
    if (!name) return;
    try { await api("/api/tax/businesses", {method: "POST", body: JSON.stringify({name})}); notice(`${name} added.`); await reload(); }
    catch (error) { notice(error, true); }
  });
  parts.push(form);
  return parts;
}

// Jobs & pay stubs -----------------------------------------------------------------------------------------------
function taxes2JobsTab(host) {
  const view = taxes2.view, zen = view.zen, draft = taxes2.draft, parts = [];
  for (const job of view.gathered.jobs) {
    const region = element("section", "", "panel taxes2-job"), title = element("h2", job.name);
    title.id = `taxes2-job-${job.key.replace(/\W+/g, "-")}`; region.setAttribute("aria-labelledby", title.id);
    const unrecorded = job.paydays_without_stub;
    region.append(title, element("p", `${job.stubs} pay stub${job.stubs === 1 ? "" : "s"} through ${dateText(job.last_pay_date)}`
      + (unrecorded ? ` · ${unrecorded} payday${unrecorded === 1 ? "" : "s"} since without a stub, counted like the last one` : "")
      + (job.next_pay_date ? ` · next payday ${dateText(job.next_pay_date)}` : "") + ` · ${job.paychecks_left} paycheck${job.paychecks_left === 1 ? "" : "s"} left`, "muted small"));
    const grid = element("div", "", "taxes2-job-grid"), year = element("div"), facts = element("dl", "", "taxes2-job-facts");
    year.append(element("h3", "This year"));
    for (const [field, label] of [["wages", "Wages"], ["federal_withheld", "Federal withheld"], ["state_withheld", "State withheld"]]) {
      const dd = element("dd"); dd.append(figure(job.figures?.[field], {size: "inline", signed: false})); facts.append(element("dt", label), dd);
    }
    year.append(facts, element("p", `Per paycheck now: federal ${job.per_check_display.federal} · state ${job.per_check_display.state}`, "small muted"));
    const w4 = element("div", "", "taxes2-w4"), entries = draft.w4[job.key] || {step2: false};
    w4.append(element("h3", "W-4 on file"));
    const step2 = element("label", "", "check-field"), box = document.createElement("input"); box.type = "checkbox"; box.checked = Boolean(entries.step2);
    box.dataset.w4 = job.key; box.dataset.key = "step2"; step2.append(box, " Step 2 checked");
    const row = element("div", "", "forecast-row");
    for (const [key, label] of TAXES2_W4) {
      const input = taxInput(`taxes2-w4-${job.key}-${key}`, entries[key], "0"); input.dataset.w4 = job.key; input.dataset.key = key;
      row.append(forecastField(label, input));
    }
    w4.append(step2, row);
    if (zen?.job?.key === job.key && !["ZEN", "WATCH", "AT_RISK", "REVIEW_REQUIRED"].includes(zen.status)) {
      const advice = zen.job, line = element("p", "", "small taxes2-suggests");
      if (advice.primary === "extra") line.append("Tax Zen suggests: Step 4(c) ", figure(advice.extra.figure, {size: "inline", magnitude: true}), " a paycheck. ");
      else if (!advice.rest.unreachable) line.append(`Tax Zen suggests: ${advice.rest.field === "4(a)" ? "Step 4(a)" : "Step 4(b)"} ${advice.rest.display.amount}. `);
      const why = element("button", "Why", "link-button"); why.type = "button"; why.addEventListener("click", () => activateTaxes2Tab("taxes2-tab-year"));
      if (line.hasChildNodes()) { line.append(why); w4.append(line); }
    }
    grid.append(year, w4);
    region.append(grid, element("h3", "Pay stubs this year"));
    region.append(trackTable([["Pay date", false], ["Gross", true], ["Federal withheld", true], ["Net", true]], job.stub_list || [], (tr, item) => {
      const date = tr.insertCell(), link = homeLink("", `#/documents/${item.document_id}`);
      link.append(dateDisplay(item.pay_date)); date.append(link);
      for (const key of ["gross", "federal", "net"]) tr.appendChild(element("td", "", "numeric")).append(amount(item[key], {signed: false}));
    }));
    parts.push(region);
  }
  if (!view.gathered.jobs.length) parts.push(emptyState(`No confirmed pay stubs for ${view.year} yet. Pay stubs you add go in Documents › Jobs.`));
  host.replaceChildren(...parts, ...(view.gathered.jobs.length ? [taxes2SaveBar()] : []));
  taxes2SaveBars();
}

// Write-offs, CPA pack, Rules & sources --------------------------------------------------------------------------
const taxes2Reload = () => loadTaxesV2(new URLSearchParams({year: String(taxes2.year), tab: taxes2.tab}));
function taxes2WriteOffsTab(host) {
  const summary = taxes2.summary, tags = taxes2.tags, parts = [element("h2", "Write-offs and tax payments")];
  const waiting = tags.filter(tag => tag.review_status === "proposed").length;
  if (!summary.lines.length) parts.push(emptyState(waiting
    ? `Nothing counts for ${summary.year} yet: ${waiting} suggestion${waiting === 1 ? " waits" : "s wait"} in Review.`
    : `Nothing tagged for ${summary.year} yet. Tag a transaction from its drawer, a receipt from its page, or add a tax rule in Rules & sources.`));
  else parts.push(trackTable([["Counts as", false], ["Line", false], ["Business", false], ["Items", true], ["Amount", true], ["Counts", true]], summary.lines, (tr, line) => {
    cell(tr, line.kind_label); cell(tr, line.line_label); cell(tr, line.business || "—"); cell(tr, line.items).className = "numeric";
    tr.appendChild(element("td", "", "numeric")).append(amount(line.amount, {signed: false}));
    tr.appendChild(element("td", "", "numeric")).append(figure(line.counted, {size: "inline", signed: false}));
  }));
  parts.push(...summary.notes.map(note => element("p", note, "muted small")));
  if (tags.length) {
    const details = element("details", "", "tax-items");
    details.append(element("summary", `Every tagged item in ${summary.year} (${tags.length})`),
      trackTable([["Date", false], ["Item", false], ["Counts as", false], ["Amount", true], ["", false]], tags, (tr, tag) => {
        tr.appendChild(element("td")).append(dateDisplay(tag.tax_date));
        tr.insertCell().append(tag.transaction_id ? taxItemLink(tag) : element("span", tag.target.description), element("small", tag.target.detail || "", "muted block"));
        tr.insertCell().append(element("span", `${tag.kind_label}: ${tag.line_label}`), element("small", tag.review_status === "proposed" ? "Waiting in Review" : TAX_SOURCES[tag.source], "muted block"));
        tr.appendChild(element("td", "", "numeric")).append(amount(tag.display.counted_minor, {signed: false}));
        tr.insertCell().append(asyncButton("Not a write-off", async () => { await api(`/api/tax-tags/${tag.id}/not-a-write-off`, {method: "POST"}); notice("Untagged."); await taxes2Reload(); }, "small quiet"));
      }));
    parts.push(details);
  }
  host.replaceChildren(...parts);
}
function taxes2PackTab(host) {
  const body = element("div"); body.id = "taxes2-pack-body";
  host.replaceChildren(element("h2", "For your accountant"),
    element("p", "The CPA pack is one Excel workbook for the year: the estimate, income, write-offs, investments, tax forms and every transaction, with foreign amounts "
      + "in USD and the rate used. A Needs review sheet lists anything unfinished. Each pack is kept as made; building again after changes makes a new one.", "muted"), body);
  loadCpaPacks(taxes2.year, body).catch(error => body.replaceChildren(alertBox(`Couldn't load the CPA packs. ${error.message || error}`, {tone: "error"})));
}
async function taxes2RulesTab(host) {
  const view = taxes2.view, rulesHost = element("div"), tables = element("div", "", "taxes2-tables"), sources = element("div", "", "taxes2-sources");
  renderTaxRules(taxes2.rules, taxes2.setup, rulesHost, taxes2Reload);
  for (const [code, status] of Object.entries(view.tables)) {
    const row = element("div", "", "taxes2-table-row");
    row.append(element("span", code === "US" ? "Federal" : code, "taxes2-table-name"));
    if (status === "verified") row.append(element("span", "Confirmed", "muted"));
    else if (status === "proposed") row.append(statusBadge("needs_review"), homeLink("Open Review", "#/review"));
    else row.append(element("span", "Not looked up yet", "muted"), taxTableLookup(view, code));
    tables.append(row);
  }
  if (!Object.keys(view.tables).length) tables.append(element("p", "No tax tables apply yet.", "muted small"));
  host.replaceChildren(element("h2", "Tax rules"), element("p", "A rule tags every bank line containing its words, now and as new lines arrive. A tag you set by hand always wins.", "muted small"),
    rulesHost, element("h2", `Tax tables for ${view.year}`), tables, element("h2", "Rules and sources"), sources);
  try {
    taxes2.sources ||= await api("/api/rule-sources");
    sources.replaceChildren(...(taxes2.sources.length ? taxes2.sources.map(ruleCard) : [element("p", "No rule sets recorded yet.", "muted small")]));
  } catch (error) { sources.replaceChildren(alertBox(`Couldn't load the rules and sources. ${error.message || error}`, {tone: "error"})); }
}
