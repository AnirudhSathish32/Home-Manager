"use strict";
// Taxes (docs/taxes.md). Tags on ledger items (write-offs, business income, credit spending, tax paid ahead), the
// tagging editor used in the transaction drawer and the receipt inspector, and the Taxes page. The server works out every
// amount; this only shows its text.
let taxSetup = null;
async function loadTaxSetup(force = false) {
  if (!taxSetup || force) taxSetup = await api("/api/tax/setup");
  return taxSetup;
}
function taxOptions(select, entries, value) {
  select.replaceChildren(...entries.map(([key, label]) => new Option(label, key)));
  if (value != null && entries.some(([key]) => key === value)) select.value = value;
}
const TAX_SOURCES = {user: "Tagged by you", rule: "Tagged by a tax rule", suggestion: "Suggested, confirmed by you"};

function taxTagSummary(tag) {
  const text = element("p", "", "tax-tag-summary");
  text.append(element("strong", `${tag.kind_label}: ${tag.line_label}`), document.createTextNode(tag.business ? ` · ${tag.business}` : ""),
              document.createTextNode(" · "), amount(tag.display.counted_minor, {signed: false}),
              document.createTextNode(tag.counted_minor !== tag.amount_minor ? ` counted of ${tag.display.amount_minor}` : " counted"));
  return text;
}

// The editor for one item: what it counts as now, and a form to tag it (or change the tag).
// targets: [{type, id, label, inflow, amount}] - one item, or a receipt and its lines. tags: the tags already on them.
function taxTagEditor({targets, tags, words = "", onDone}) {
  const box = element("div", "", "tax-tag-editor");
  const byTarget = key => tags.find(tag => tag[`${key.type}_id`] === key.id);
  const shown = targets.map(target => [target, byTarget(target)]).filter(([, tag]) => tag && tag.review_status !== "rejected");
  for (const [target, tag] of shown) {
    const row = element("div", "", "tax-tag-row");
    if (targets.length > 1) row.append(element("span", target.label, "figure-label"));
    row.append(taxTagSummary(tag));
    if (tag.review_status === "proposed") {
      row.append(element("small", `Suggested: ${tag.reason}`, "muted block"),
        asyncButton("Tag it", async () => { await api(`/api/tax-tags/${tag.id}/review`, {method: "POST", body: JSON.stringify({status: "verified"})}); notice("Tagged."); await onDone(); }, "small primary"),
        asyncButton("Not a write-off", async () => { await api(`/api/tax-tags/${tag.id}/review`, {method: "POST", body: JSON.stringify({status: "rejected"})}); notice("Not a write-off; this payee won't be suggested again."); await onDone(); }, "small quiet"));
    } else {
      row.append(element("small", `${TAX_SOURCES[tag.source]}${tag.source === "rule" ? ` (${tag.reason.replace("Tax rule: ", "")})` : ""}.`, "muted block"),
        asyncButton("Not a write-off", async () => { await api(`/api/tax-tags/${tag.id}/not-a-write-off`, {method: "POST"}); notice("Untagged."); await onDone(); }, "small quiet"));
    }
    box.append(row);
  }
  if (!shown.length) box.append(element("p", "Not tagged for taxes.", "muted small"));
  const open = element("button", shown.length ? "Change or add a tag…" : "Tag for taxes…", "small"); open.type = "button";
  open.addEventListener("click", async () => { open.remove(); try { box.append(await taxTagForm({targets, tags, words, onDone})); } catch (error) { notice(error, true); } });
  box.append(open);
  return box;
}
let taxFormId = 0;
async function taxTagForm({targets, tags, words, onDone}) {
  const setup = await loadTaxSetup(), id = ++taxFormId;
  const form = element("form", "", "form tax-tag-form");
  const field = (label, control) => { control.id = `tax-${id}-${label.toLowerCase().replace(/\W+/g, "-")}`; return forecastField(label, control); };
  const which = document.createElement("select"), kind = document.createElement("select"), line = document.createElement("select"), business = document.createElement("select");
  const newBusiness = document.createElement("input"), amountInput = document.createElement("input"), note = document.createElement("input");
  newBusiness.maxLength = 60; newBusiness.placeholder = "e.g. Contract work"; amountInput.inputMode = "decimal"; note.maxLength = 200;
  taxOptions(which, targets.map((target, index) => [String(index), target.label]), "0");
  const newField = field("New business name", newBusiness);
  const refresh = () => {
    const target = targets[Number(which.value)], current = tags.find(tag => tag[`${target.type}_id`] === target.id && tag.review_status !== "rejected");
    // Money in can only be business income; money out is any other kind.
    const kinds = Object.entries(setup.kinds).filter(([key]) => setup.income_kinds.includes(key) === Boolean(target.inflow));
    taxOptions(kind, kinds, current?.kind ?? kind.value);
    taxOptions(line, (setup.lines[kind.value] || []).map(entry => [entry.key, `${entry.label} (${entry.form_line})`]), current?.line ?? line.value);
    const needsBusiness = setup.business_kinds.includes(kind.value);
    business.closest(".field").hidden = !needsBusiness;
    taxOptions(business, [...setup.businesses.map(item => [String(item.id), item.name]), ["new", "A new business…"]], current?.business_id != null ? String(current.business_id) : business.value);
    newField.hidden = !needsBusiness || business.value !== "new";
    amountInput.placeholder = target.amount ? `All of it: ${target.amount}` : "";
  };
  const rule = element("label", "", "compact-check"), always = document.createElement("input"), ruleText = document.createElement("input");
  always.type = "checkbox"; ruleText.value = words; ruleText.maxLength = 120; ruleText.setAttribute("aria-label", "Words the rule matches");
  rule.append(always, document.createTextNode(" Always for bank lines containing "), ruleText);
  const fields = element("div", "", "forecast-row");
  if (targets.length > 1) fields.append(field("Which part", which));
  fields.append(field("Counts as", kind), field("Line", line), field("Business", business), newField, field("Amount that counts", amountInput));
  const save = element("button", "Save tag", "primary small"); save.type = "submit";
  const cancel = element("button", "Cancel", "quiet small"); cancel.type = "button"; cancel.addEventListener("click", () => onDone());
  form.append(fields, field("Note (optional)", note), ...(words && targets[0].type === "transaction" ? [rule] : []), element("div", "", "button-row"));
  form.lastElementChild.append(save, cancel);
  for (const control of [which, kind, business]) control.addEventListener("change", refresh);
  refresh();
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const target = targets[Number(which.value)];
    try {
      let businessId = null;
      if (setup.business_kinds.includes(kind.value)) {
        if (business.value === "new") {
          if (!newBusiness.value.trim()) { notice("Name the business first.", true); newBusiness.focus(); return; }
          businessId = (await api("/api/tax/businesses", {method: "POST", body: JSON.stringify({name: newBusiness.value.trim()})})).id;
          await loadTaxSetup(true);
        } else businessId = Number(business.value);
      }
      if (always.checked && target.type === "transaction") {
        const made = await api("/api/tax/rules", {method: "POST", body: JSON.stringify({pattern: ruleText.value.trim(), kind: kind.value, line: line.value, business_id: businessId})});
        notice(`Tax rule saved: “${made.pattern}”. ${made.changed} bank line${made.changed === 1 ? "" : "s"} tagged.`);
      }
      if (!always.checked || amountInput.value.trim() || note.value.trim()) {
        await api("/api/tax-tags", {method: "POST", body: JSON.stringify({target_type: target.type, target_id: target.id, kind: kind.value, line: line.value,
          business_id: businessId, amount: amountInput.value.trim() || null, note: note.value.trim()})});
        notice("Tagged for taxes.");
      }
      await onDone();
    } catch (error) { notice(error, true); }
  });
  kind.focus();
  return form;
}
// The receipt inspector: tag the whole receipt, or one of its lines (a charity item on a store receipt).
function taxReceiptSection(record, onDone) {
  const section = element("section", "", "paystub-taxes tax-receipt");
  section.append(element("h3", "Taxes"));
  const load = async () => {
    const {tags} = await api(`/api/tax-tags?receipt_id=${record.id}`);
    const targets = [{type: "receipt", id: record.id, label: "The whole receipt", inflow: false, amount: record.display?.total_minor},
                     ...(record.items || []).map(item => ({type: "receipt_item", id: item.id, label: item.description, inflow: false, amount: item.display?.line_total_minor}))];
    section.replaceChildren(element("h3", "Taxes"), taxTagEditor({targets, tags, onDone: async () => { await load(); await onDone?.(); }}));
  };
  load().catch(error => section.append(alertBox(error.message, {tone: "error"})));
  return section;
}

// The Taxes page: the year's return, estimated; tagged write-offs and payments; tax rules; businesses.
function taxYear() { return Number(currentRoute?.params?.get?.("year")) || new Date().getFullYear(); }
function loadTaxes() {
  return pageState($("taxes-state"), renderTaxes, {loading: "Loading this year's taxes …", what: "this year's taxes", needsLibrary: true, content: [$("taxes-body")]});
}
async function renderTaxes() {
  const year = taxYear();
  const select = $("taxes-year");
  if (!select.options.length) {
    const now = new Date().getFullYear();
    for (let value = now + 1; value >= now - 5; value--) select.add(new Option(String(value), String(value)));
  }
  select.value = String(year);
  $("taxes-family-panel").hidden = !familyMode;
  for (const panel of document.querySelectorAll(".taxes-personal")) panel.hidden = familyMode;
  if (familyMode) { await loadFamilyTaxes(year); return; }
  taxUnit = null;
  $("taxes-return-panel").hidden = false; $("taxes-return-title").textContent = "The return, estimated";
  const setup = await loadTaxSetup(true);
  const [view, summary, {tags}, {rules}] = await Promise.all([api(`/api/tax/year/${year}`), api(`/api/tax/write-offs/${year}?currency=USD`),
    api(`/api/tax-tags?year=${year}`), api("/api/tax/rules")]);
  renderTaxYear(view);
  renderWriteOffs(summary, tags.filter(tag => tag.review_status !== "rejected"));
  renderTaxRules(rules, setup);
  renderBusinesses(setup);
  await loadCpaPacks(year);
}

// The year-end CPA pack (finance/cpa_pack.py) and the exchange rates its USD values use (finance/fx.py). host: where it
// shows (Taxes v2 passes its own).
async function loadCpaPacks(year, host = $("taxes-pack")) {
  const [{packs}, rates] = await Promise.all([api(`/api/tax/cpa-packs?year=${year}`), api("/api/rates")]);
  const parts = [];
  if (rates.needed) {
    const state = !rates.enabled ? "Exchange-rate downloads are off in Settings, so foreign amounts stay unconverted."
      : rates.downloaded ? `Foreign amounts are converted at ECB reference rates, downloaded through ${dateText(rates.last_rate_date)}.`
      : "Foreign amounts need ECB reference rates, which haven't been downloaded yet.";
    const line = element("p", state, "muted small");
    if (rates.enabled) line.append(" ", asyncButton("Refresh rates", async () => { await api("/api/rates/refresh", {method: "POST"}); notice("Exchange rates updated."); await loadCpaPacks(year, host); }, "small quiet"));
    parts.push(line);
  }
  const actions = element("p");
  parts.push(actions);
  actions.append(asyncButton(`Build the ${year} CPA pack`, async () => {
    const pack = await api(`/api/tax/cpa-packs/${year}`, {method: "POST"});
    notice(pack.reused ? "Nothing changed since the last pack; it's ready to download." : "CPA pack built.");
    await loadCpaPacks(year, host);
  }, ""));
  if (packs.length) {
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Made", false], ["Records as of", false], ["Needs review", true], ["", false]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
    const body = table.createTBody();
    for (const pack of packs) {
      const tr = body.insertRow();
      tr.appendChild(element("td")).append(dateDisplay(pack.created_at.slice(0, 10)));
      tr.appendChild(element("td")).append(dateDisplay(pack.as_of));
      cell(tr, pack.needs_review ? String(pack.needs_review) : "Nothing").className = "numeric";
      tr.insertCell().append(asyncButton("Download", () => downloadCpaPack(pack), "small"));
    }
    wrap.append(table); parts.push(wrap);
  }
  host.replaceChildren(...parts);
}
async function downloadCpaPack(pack) {
  const response = await fetch(`/api/tax/cpa-packs/${pack.id}/file`, {headers: {"Authorization": `Bearer ${token}`}});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "The pack could not be downloaded."); }
  const url = URL.createObjectURL(await response.blob());
  const link = element("a"); link.href = url; link.download = pack.name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// The return, estimated (finance/tax_return.py): the result, every line with how it was worked out, and what it is built from.
const RETURN_FIELDS = [
  ["Income", [["interest", "Taxable interest"], ["us_obligation_interest", "Of it, I bond and Treasury interest (state-exempt)"], ["tax_exempt_interest", "Tax-exempt interest"], ["ordinary_dividends", "Ordinary dividends (1099-DIV 1a)"],
              ["qualified_dividends", "Qualified dividends (1099-DIV 1b)"], ["short_term_gain", "Short-term gain or loss"], ["long_term_gain", "Long-term gain or loss"],
              ["capital_loss_carryover", "Capital loss carried from last year"], ["retirement_distributions", "Taxable retirement distributions"],
              ["early_distributions", "…taken early (before 59½)"], ["social_security_benefits", "Social Security benefits"], ["unemployment", "Unemployment"],
              ["hsa_nonqualified", "HSA money not spent on medical care"], ["other_income", "Other income"]]],
  ["Adjustments", [["educator_expenses", "Educator expenses"], ["hsa_contributions", "HSA contributions (not through payroll)"],
                   ["se_health_insurance", "Self-employed health insurance"], ["ira_deduction", "Deductible IRA contributions"],
                   ["student_loan_interest", "Student-loan interest"], ["other_adjustments", "Other adjustments"]]],
  ["Deductions", [["medical", "Medical and dental"], ["state_local_tax", "State and local income tax"], ["property_tax", "Property tax"],
                  ["mortgage_interest", "Mortgage interest"], ["mortgage_average_balance", "Mortgage's average balance this year"],
                  ["charity", "Charity (cash)"], ["charity_noncash", "Charity (goods)"], ["other_itemized", "Other itemized"],
                  ["qualified_tips", "Qualified tips (below the line)"], ["qualified_overtime", "Overtime premium (the extra half of time-and-a-half)"]]],
  ["Credits", [["qualifying_children", "Qualifying children (under 17)", true], ["other_dependents", "Other dependents", true],
               ["dependent_care_expenses", "Child and dependent care costs"], ["dependent_care_people", "People those costs were for", true],
               ["energy_home_expenses", "Energy-efficient home improvements"], ["other_credits", "Other credits"], ["other_refundable_credits", "Other refundable credits"]]],
  ["Payments", [["federal_estimated_paid", "Federal estimated tax paid"], ["other_federal_withholding", "Other federal withholding (1099 box 4)"]]],
  ["State", [["state_deduction", "State deduction or exemption"], ["state_credits", "State credits"], ["state_estimated_paid", "State estimated tax paid"]]]];
const RETURN_SECTIONS = {income: "Income", adjustments: "Adjustments", deductions: "Deductions", tax: "Tax", credits: "Credits", other_taxes: "Other taxes", payments: "Payments"};
let taxView = null, taxUnit = null;  // taxUnit: the family return shown, in the family view.
// Typed but not saved yet: a reload of the page (the app's own start-up, another tab's change) redraws everything but the
// editor, so nothing typed is lost.
let taxInputsDirty = null;
$("taxes-inputs").addEventListener("input", () => { taxInputsDirty = `${taxView?.year}:${taxUnit}`; });
async function saveTaxInputs(inputs) {
  // A person's own year, or one of the family's returns.
  taxInputsDirty = null;
  if (taxUnit == null) return renderTaxYear(await api(`/api/tax/year/${taxView.year}`, {method: "PUT", body: JSON.stringify(inputs)}));
  renderFamilyTaxes(await api(`/api/tax/family/${taxView.year}/${taxUnit}`, {method: "PUT", body: JSON.stringify(inputs)}));
}

// The family view: every return, each with its result and Tax Zen; one is open below for its details.
async function loadFamilyTaxes(year) { renderFamilyTaxes(await api(`/api/tax/family/${year}`)); }
function renderFamilyTaxes(family) {
  const target = $("taxes-family"), parts = [];
  if (family.returns.length) parts.push(element("p", family.zen ? "The family is Tax Zen: every return comes out within a dollar of $0." : "Not every return is at $0 yet.", "taxes-zen-headline"));
  for (const item of family.returns) {
    const card = element("div", "", "taxes-return-card"), view = item.view, result = view.return, zen = view.zen;
    card.append(element("strong", `${item.name} · ${view.filing_status_name}`, "block"));
    card.append(element("p", result.result_minor == null ? (result.notes[0] || "")
      : zen.zen ? "Tax Zen: within a dollar of $0." : `${result.result.refund ? "Refund of" : "Owes"} ${result.result.display}.`
        + (zen.job?.rest?.amount != null ? ` Tax Zen: ${zen.job.name}'s W-4 ${zen.job.rest.field} ${zen.job.rest.display.amount}.` : ""), "small"));
    const open = element("button", taxUnit === item.id ? "Shown below" : "Open", "small"); open.type = "button"; open.disabled = taxUnit === item.id;
    open.addEventListener("click", () => { taxUnit = item.id; renderFamilyTaxes(family); });
    const remove = asyncButton("Remove", async () => {
      if (!await confirmAction({title: `Remove the return “${item.name}”?`, message: "Its typed values go with it; members' records aren't changed.", confirmLabel: "Remove", danger: true})) return;
      await api(`/api/tax/units/${item.id}`, {method: "DELETE"}); if (taxUnit === item.id) taxUnit = null; await loadFamilyTaxes(family.year);
    }, "small quiet");
    card.append(open, remove);
    parts.push(card);
  }
  // A return for the people on none yet.
  const free = family.members.filter(member => !member.on_a_return);
  if (free.length) parts.push(element("h3", "Add a return"), familyUnitForm(family, () => loadFamilyTaxes(family.year)));
  if (!family.returns.length && !free.length) parts.push(emptyState("No one in the family has shared records yet."));
  target.replaceChildren(...parts);
  const shown = family.returns.find(item => item.id === taxUnit) || family.returns[0];
  $("taxes-return-panel").hidden = !shown;
  if (shown) { taxUnit = shown.id; $("taxes-return-title").textContent = `${shown.name}: the return, estimated`; renderTaxYear(shown.view); }
}
// Add a return for family members on none yet (the family view, v1 and v2). onAdded runs after it's saved.
function familyUnitForm(family, onAdded) {
  const free = family.members.filter(member => !member.on_a_return);
  const form = element("form", "", "inline taxes-unit-form"), who = element("div", "", "button-row");
  for (const member of free) {
    const label = element("label", "", "check-field"), box = Object.assign(document.createElement("input"), {type: "checkbox", value: member.member_id});
    label.append(box, ` ${member.name}`); who.append(label);
  }
  const status = planSelect(`taxes-unit-status`, {single: "Single", married_joint: "Married filing jointly", head_of_household: "Head of household"});
  const add = element("button", "Add a return", ""); add.type = "submit";
  form.append(forecastField("Who", who), forecastField("Filing", status), add);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const members = [...who.querySelectorAll("input:checked")].map(box => box.value);
    try { await api("/api/tax/units", {method: "POST", body: JSON.stringify({members, filing_status: status.value})}); await onAdded(); }
    catch (error) { notice(error, true); }
  });
  return form;
}
// What kind of value a field holds (finance/tax_year.py KIND_ORDER; §35), in words beside it with where it came from.
const VALUE_KINDS = {record: "From records", worked_out: "Worked out from records", projected: "Projected to Dec 31", to_enter: "Enter it", typed: "You typed"};
// [kind, words] for a field, or null when the records say nothing about it.
function valueKindText(typedValue, gathered, key) {
  const typedHere = typedValue !== undefined && typedValue !== null && typedValue !== "";
  const kind = typedHere ? "typed" : gathered.kinds?.[key];
  if (!kind) return null;
  const source = typedHere ? "used instead of your records" : gathered.sources?.[key];
  return [kind, source ? `${VALUE_KINDS[kind]}: ${source}` : VALUE_KINDS[kind]];
}
function valueKind(field, typedValue, gathered, key) {
  const found = valueKindText(typedValue, gathered, key);
  if (found) field.append(element("small", found[1], `value-kind value-kind-${found[0]}`));
  return field;
}
function taxInput(id, value, placeholder, title = "") {
  const input = forecastInput(id, {inputmode: "decimal"}); input.value = value ?? ""; input.placeholder = placeholder || "0.00";
  if (title) input.title = title;
  return input;
}
// Tax Zen (finance/tax_zen.py): what to put on a W-4, or pay ahead, so the return comes out at $0.
// The aim (finance/tax_zen.py TaxZenPolicy), in words; the status badges are in ui.js STATUS.
const ZEN_STRATEGIES = {precision: "Come out at $0", small_refund: "A small refund", cash_retention: "Keep cash, owe a little", safe_harbor: "Owe what's allowed without a penalty"};
const ZEN_BADGES = {ZEN: "tax_zen", WATCH: "tax_watch", AT_RISK: "tax_at_risk", ACTION_RECOMMENDED: "tax_action", REVIEW_REQUIRED: "tax_review", INSUFFICIENT_DATA: "tax_insufficient", ENGINE_UNSUPPORTED: "tax_unsupported"};
// ids and save: Taxes v2 gives its own ids, and saves through its own draft.
function zenPolicyForm(view, {ids = {strategy: "taxes-zen-strategy", amount: "taxes-zen-amount"}, save: saveInputs = saveTaxInputs} = {}) {
  const zen = view.zen, saved = view.inputs.zen_policy || {}, row = element("div", "", "forecast-row");
  const strategy = planSelect(ids.strategy, ZEN_STRATEGIES, zen.policy?.strategy || "precision");
  row.append(forecastField("Aim for", strategy));
  const amountFor = {small_refund: ["refund", "Refund to aim for (USD)", "refund_minor"], cash_retention: ["max_owed", "Most you'd owe in April (USD)", "max_owed_minor"]}[strategy.value];
  let typed = null;
  if (amountFor) { typed = taxInput(ids.amount, saved[amountFor[0]], zen.display?.[amountFor[2]] || "", "Whole dollars"); row.append(forecastField(amountFor[1], typed)); }
  const save = async () => {
    const policy = {strategy: strategy.value};
    if (typed && typed.value.trim() && amountFor && strategy.value === zen.policy?.strategy) policy[amountFor[0]] = typed.value.trim();
    try { await saveInputs({...view.inputs, zen_policy: policy}); } catch (error) { notice(error, true); }
  };
  strategy.addEventListener("change", save); typed?.addEventListener("change", save);
  return row;
}
function renderTaxZen(view) {
  const zen = view.zen, target = $("taxes-zen"), title = element("h3", "Tax Zen ", ""), parts = [title];
  title.id = "taxes-zen-title";
  if (zen?.status) title.append(statusBadge(ZEN_BADGES[zen.status]));
  if (!zen?.ready) { target.replaceChildren(...parts, element("p", zen?.note || "", "muted small")); return; }
  parts.push(zenPolicyForm(view));
  if (zen.zen) parts.push(element("p", `You're Tax Zen for ${view.year}: the return comes out at your aim (${zen.display.aim}).`, "taxes-zen-headline"));
  else parts.push(element("p", zen.reason, "small"));
  // §23: the likely range, with the projected pay and interest moved down and up; and what changed since last time (§43).
  if (zen.range && zen.range.low_minor !== zen.range.high_minor) parts.push(element("p", `Likely between ${zen.range.display.low_minor} and `
    + `${zen.range.display.high_minor} (${zen.range.confidence} confidence: ${{high: "little of it is projected", medium: "some of it is projected", low: "much of it is projected"}[zen.range.confidence]}).`, "muted small"));
  if (zen.changed?.texts?.length) {
    const changed = element("details"), list = element("ul", "", "small");
    changed.append(element("summary", "What changed since Tax Zen last looked"));
    for (const text of zen.changed.texts) list.append(element("li", text));
    changed.append(list); parts.push(changed);
  }
  const job = zen.job;
  if (zen.cushion) parts.push(element("p", zen.cushion.text, "taxes-zen-headline"));
  if (job?.steady && !["ZEN", "WATCH", "AT_RISK"].includes(zen.status)) parts.push(element("p", job.steady.text, "small"));
  if (job && !["ZEN", "WATCH", "AT_RISK"].includes(zen.status)) {
    // Why (§43): where the year ends, the aim, and the paychecks left to get there; when a new W-4 takes effect (§21).
    const payroll = job.payroll || {};
    const timing = payroll.delay_checks ? ` A W-4 handed in now takes effect after ${payroll.delay_checks === 1 ? "the next paycheck" : `the next ${payroll.delay_checks} paychecks`}`
      + `${payroll.next_pay_date ? ` (${dateText(payroll.next_pay_date)})` : ""}, so it changes ${job.paychecks_left} of the ${payroll.paychecks_left} left.` : "";
    parts.push(element("p", `Why: at today's withholding the year ends ${zen.result_minor >= 0 ? "with a refund of" : "owing"} ${zen.display.result_minor}; `
      + `your aim is ${zen.display.aim}, with ${job.paychecks_left} paychecks to change at ${job.name}.${timing}`, "small"));
    const rest = job.rest, entry = rest.field === "4(a)" ? "Step 4(a), other income" : "Step 4(b), deductions";
    const checked = part => part.checked ? " Checked: working the return out again with it ends the year there." : part.checked === false ? " It couldn't be checked against the return; treat it as approximate." : "";
    const extraLine = job.extra && element("p", "", job.primary === "extra" ? "taxes-zen-headline" : "small");
    if (job.extra) {
      if (job.primary === "extra") extraLine.append(`On ${job.name}'s W-4, add `, element("strong", job.extra.display.per_check_minor), ` of extra withholding a paycheck (Step 4(c): ${job.extra.display.total_4c_minor} in all). `
        + `The year then ends at ${job.extra.year_end_minor >= 0 ? "a refund of" : "owing"} ${job.extra.display.year_end_minor.replace("-", "")}.${checked(job.extra)}`);
      else extraLine.textContent = `Or keep the W-4 as it is and add ${job.extra.display.per_check_minor} of extra withholding a paycheck (Step 4(c): ${job.extra.display.total_4c_minor} in all).`;
    }
    if (job.primary === "extra") parts.push(extraLine);
    const headline = element("p", "", job.primary === "extra" ? "small" : "taxes-zen-headline");
    if (rest.unreachable) headline.textContent = `No W-4 entry at ${job.name} can close this with ${job.paychecks_left} paychecks left: withholding can't go below zero. `
      + "The rest comes back as a refund; see January below.";
    else if (job.primary === "extra") headline.textContent = `Or put ${rest.display.amount} in ${entry} instead.`;
    else headline.append(`On ${job.name}'s W-4, put `, element("strong", `${rest.display.amount}`), ` in ${entry}, for the ${job.paychecks_left} paychecks it changes this year.`);
    parts.push(headline);
    if (!rest.unreachable && job.primary !== "extra") parts.push(element("p", `Withholding becomes ${rest.display.per_check} a paycheck (now ${job.display.per_check_now_minor}), and the year ends at `
      + `${rest.year_end_minor >= 0 ? "a refund of" : "owing"} ${rest.display.year_end_minor.replace("-", "")}. The amount replaces what's in that box now; leave the other boxes as they are.${checked(rest)}`, "small"));
    if (job.extra && job.primary !== "extra") parts.push(extraLine);
    if (job.step3) parts.push(element("p", `Or, since the W-4 claims dependents, raise Step 3 to ${job.step3.display.amount}: withholding becomes `
      + `${job.step3.display.per_check} a paycheck and the year ends at ${job.step3.year_end_minor >= 0 ? "a refund of" : "owing"} ${job.step3.display.year_end_minor.replace("-", "")}.`, "small"));
    const january = job.january;
    if (january.field && january.amount != null) parts.push(element("p", `From January, for a full year at this pay: ${january.field === "4(a)" ? "Step 4(a)" : "Step 4(b)"} ${january.display.amount}. `
      + `Check again when ${view.year + 1}'s tax tables are confirmed.`, "small"));
    else if (!january.field) parts.push(element("p", "From January, at this pay, the W-4 as it is comes out even.", "small"));
    if (zen.choices?.length > 1) {
      const pick = planSelect("taxes-zen-job", Object.fromEntries(zen.choices.map(choice => [choice.key, choice.name])), job.key);
      pick.addEventListener("change", async () => {
        try { await saveTaxInputs({...view.inputs, zen_job: pick.value}); } catch (error) { notice(error, true); }
      });
      parts.push(forecastField("Change the W-4 at", pick));
    }
  }
  if (zen.advance && (!job || zen.advance.left_minor)) {
    // Advance tax: the answer when no paycheck can take it (1099 work), else an alternative to the W-4 change, folded away.
    const advance = zen.advance, holder = job && !zen.zen ? element("details") : element("div");
    const title = job && !zen.zen ? "Or pay it as estimated tax instead (quarterly, 1040-ES)" : "Advance tax (quarterly estimated payments)";
    holder.append(job && !zen.zen ? element("summary", title) : element("h4", title),
      element("p", `Estimated payments need to cover ${advance.display.needed_minor}; ${advance.display.paid_minor} is paid so far (tagged IRS payments).`
        + (advance.safe_harbor_minor != null ? ` To avoid a penalty, at least ${advance.display.safe_harbor_minor} over the year.` : ""), "small"),
      trackTable([["Quarter", false], ["Due", false], ["Paid", true], ["Pay", true], ["Safe harbor by then", true]], advance.quarters, (tr, row) => {
        cell(tr, `Q${row.quarter}`); tr.insertCell().append(dateDisplay(row.due)); trackMoney(tr, row.display.paid_minor); trackMoney(tr, row.display.pay_minor);
        trackMoney(tr, row.display.safe_by_now_minor || "—");
      }), ...advance.notes.map(note => element("p", note, "muted small")));
    parts.push(holder);
  }
  if (zen.state) parts.push(element("p", zen.state.text, "small"));
  parts.push(...zen.notes.map(note => element("p", note, "muted small")));
  target.replaceChildren(...parts);
}
// A warning for each of the year's tax tables that isn't confirmed, with the way to fix it (v1 and v2).
function taxTableLookup(view, code) {
  const name = code === "US" ? "federal" : code;
  return asyncButton(`Look up the ${view.year} ${name} table`, async () => {
    await api("/api/tax-tables/lookup", {method: "POST", body: JSON.stringify({jurisdiction: code, year: view.year, filing_status: view.filing_status})});
    notice("Looking it up. The table will wait for you in Review.");
  });
}
function taxTableAlerts(view) {
  const found = [];
  for (const [code, status] of Object.entries(view.tables)) if (status !== "verified") {
    const name = code === "US" ? "federal" : code;
    found.push(alertBox(status === "proposed" ? `The ${view.year} ${name} tax table waits for you in Review.` : `The ${view.year} ${name} tax table hasn't been looked up yet.`,
      {tone: "warning", action: status === "proposed" ? homeLink("Open Review", "#/review") : taxTableLookup(view, code)}));
  }
  return found;
}
function renderTaxYear(view) {
  taxView = view;
  renderTaxZen(view);
  const result = view.return;
  $("taxes-alerts").replaceChildren(...taxTableAlerts(view));
  const target = $("taxes-return");
  if (result.result_minor == null) { target.replaceChildren(emptyState(result.notes[0])); renderTaxInputs(view); return; }
  const headline = element("dl", "", "plan-headline");
  const zero = result.result_minor === 0;
  for (const [label, value, big] of [[zero ? "Tax Zen" : result.result.refund ? "Refund" : "You'd owe", result.result.display, true],
      ["Total tax", result.lines.find(line => line.key === "total_tax").display], ["Paid and credited", result.lines.find(line => line.key === "total_payments").display]]) {
    const dd = element("dd", "", big ? "plan-figure" : ""); dd.append(amount(value, {signed: false})); headline.append(element("dt", label), dd);
  }
  // Which engine slot worked it out (finance/tax_engine.py): "Engine 1", never an engine's own name.
  const engine = result.engine?.label || "the tax engine";
  const parts = [headline, element("p", `${view.year} · filing ${view.filing_status_name}`
    + (result.marginal_percent != null ? ` · top federal bracket ${result.marginal_percent}%` : "") + ` · worked out by ${engine}. `
    + "Withholding and pay are projected to Dec 31 from your pay stubs; change anything on the right.", "muted small")];
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "ledger-rows paystub-table");
  let section = null, body = null;
  for (const line of result.lines) {
    if (!line.amount_minor && line.section !== "total" && !["wages", "tax"].includes(line.key)) continue;  // Nothing there: left out to keep the return readable.
    if (line.section !== section && line.section !== "total") {
      section = line.section; body = table.appendChild(document.createElement("tbody"));
      const title = body.insertRow().appendChild(element("th", RETURN_SECTIONS[section] || section, "paystub-group")); title.colSpan = 2; title.scope = "rowgroup";
    }
    body = body || table.appendChild(document.createElement("tbody"));
    const tr = body.insertRow(); if (line.section === "total") tr.className = "paystub-total";
    const th = tr.appendChild(element("th", line.label)); th.scope = "row";
    if (line.how) th.append(element("small", line.how, "muted block"));
    tr.appendChild(element("td", "", "numeric")).append(amount(line.display, {signed: false}));
  }
  wrap.append(table); parts.push(wrap);
  // Another engine slot's answer, when there is one and Settings asks for it (finance/tax_engine.py compare): lines more than a dollar apart.
  const comparison = result.comparison;
  if (comparison) {
    const other = comparison.engine?.label || "The other engine";
    if (!comparison.ready) parts.push(alertBox(`${other} gave no estimate to compare: ${comparison.note}`, {tone: "info"}));
    else if (comparison.agree) parts.push(alertBox(`${other} checked it and agrees on every line it works out (within ${comparison.display.within}).`, {tone: "info"}));
    else {
      const box = alertBox(`The engines disagree: ${other} has ${comparison.other_refund ? "a refund of" : "you owing"} ${comparison.display.other_result}`
        + ` (${comparison.display.difference} apart). Check the lines below before relying on either.`, {tone: "warning"});
      const diffWrap = element("div", "", "table-wrap"), diff = element("table", "", "ledger-rows");
      const head = diff.createTHead().insertRow();
      for (const [title, numeric] of [["Line", false], [engine, true], [other, true], ["Difference", true]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
      const rows = diff.createTBody();
      for (const line of comparison.lines) {
        const tr = rows.insertRow(); const th = tr.appendChild(element("th", line.label)); th.scope = "row";
        for (const key of ["this", "other", "difference"]) tr.appendChild(element("td", "", "numeric")).append(amount(line.display[key], {signed: key === "difference"}));
      }
      diffWrap.append(diff); box.querySelector(".alert-body").append(diffWrap); parts.push(box);
    }
  }
  if (result.state) parts.push(element("p", result.state.complete
    ? `${result.state.state} (simplified): tax ${result.state.display.tax_minor}, paid ${result.state.display.payments_minor}: ${result.state.result_minor >= 0 ? "refund" : "owed"} ${result.state.display.result_minor}. ${result.state.note}`
    : `${result.state.state}: ${result.state.note}`, "small"));
  const notes = element("ul", "", "forecast-notes"); for (const note of [...result.notes, ...view.gathered.notes]) notes.append(element("li", note));
  parts.push(element("h3", "About these numbers"), notes);
  target.replaceChildren(...parts);
  renderTaxInputs(view);
}
function renderTaxInputs(view) {
  if (taxInputsDirty === `${view.year}:${taxUnit}`) return;  // Unsaved typing stays; Save sends it.
  taxInputsDirty = null;
  const form = $("taxes-inputs"), typed = view.inputs.fields || {}, gathered = view.gathered;
  const parts = [element("h3", "What it's built from"), element("p", "Blank fields use your records (shown in grey). Type over any of them; typed values are saved for this year.", "muted small")];
  // Jobs from pay stubs, and jobs typed in (a spouse's).
  for (const job of gathered.jobs) {
    const set = element("fieldset", "", "taxes-job"), jobTyped = view.inputs.jobs?.[job.key] || {};
    const unrecorded = job.paydays_without_stub;
    set.append(element("legend", job.name), element("p", `${VALUE_KINDS[job.kind] || VALUE_KINDS.record}: ${job.stubs} pay stub${job.stubs === 1 ? "" : "s"} through ${dateText(job.last_pay_date)}; `
      + (unrecorded ? `${unrecorded} payday${unrecorded === 1 ? "" : "s"} since then without a stub here, counted like the last one; ` : "")
      + `${job.paychecks_left} paycheck${job.paychecks_left === 1 ? "" : "s"} still ahead this year, ${job.per_check_display.federal} federal withheld from each.`
      + `${job.ytd_printed ? "" : " Year-to-date figures weren't printed, so the stubs are added up."}`, "muted small"));
    const row = element("div", "", "forecast-row");
    for (const [key, label] of [["wages", "Wages for the year"], ["federal_withheld", "Federal withheld, year"], ["state_withheld", "State withheld, year"], ["medicare_wages", "Medicare wages"]]) {
      const input = taxInput(`tax-job-${job.key}-${key}`, jobTyped[key], job.display[key]); input.dataset.job = job.key; input.dataset.key = key;
      row.append(forecastField(label, input));
    }
    // The W-4 on file there now: Tax Zen works out from it (a W-4 you leave blank here is taken as blank).
    const w4 = view.inputs.w4?.[job.key] || {}, w4Row = element("div", "", "forecast-row");
    const step2 = element("label", "", "check-field"), box = document.createElement("input"); box.type = "checkbox"; box.checked = Boolean(w4.step2);
    box.dataset.w4 = job.key; box.dataset.key = "step2"; step2.append(box, " Step 2 checked");
    for (const [key, label] of [["credits", "Step 3 credits"], ["other_income", "Step 4(a) other income"], ["deductions", "Step 4(b) deductions"], ["extra", "Step 4(c) extra a paycheck"]]) {
      const input = taxInput(`tax-w4-${job.key}-${key}`, w4[key], "0"); input.dataset.w4 = job.key; input.dataset.key = key;
      w4Row.append(forecastField(label, input));
    }
    set.append(row, element("p", "Your W-4 there now:", "small"), step2, w4Row); parts.push(set);
  }
  const prior = view.inputs.prior_year_tax || {}, priorSet = element("fieldset"), priorRow = element("div", "", "forecast-row");
  priorSet.append(element("legend", "Last year's return (for the estimated-tax safe harbor)"));
  priorRow.append(forecastField("Total tax", taxInput("tax-prior-tax", prior.tax, "Form 1040 line 24")), forecastField("AGI", taxInput("tax-prior-agi", prior.agi, "Form 1040 line 11")));
  priorSet.append(priorRow);
  if (view.prior_year?.source) priorSet.append(element("p", view.prior_year.source, "muted small"));  // Filled from last year's return here.
  const extra = element("div", "", "forecast-list"); extra.id = "taxes-extra-jobs";
  const addExtra = (job = {}) => {
    const row = element("div", "", "forecast-row forecast-item taxes-extra-job"), id = ++taxFormId;
    for (const [key, label] of [["name", "Job (e.g. your spouse's)"], ["wages", "Wages for the year"], ["federal_withheld", "Federal withheld"], ["state_withheld", "State withheld"]]) {
      const input = key === "name" ? forecastInput(`tax-extra-${id}-${key}`, {maxlength: "60"}) : taxInput(`tax-extra-${id}-${key}`, job[key], "0.00");
      if (key === "name") input.value = job.name || "";
      input.dataset.key = key; row.append(forecastField(label, input));
    }
    const remove = element("button", "Remove", "quiet"); remove.type = "button"; remove.addEventListener("click", () => row.remove()); row.append(remove);
    extra.append(row);
  };
  for (const job of view.inputs.extra_jobs || []) addExtra(job);
  const addJob = element("button", "Add a job not in your pay stubs", "quiet"); addJob.type = "button"; addJob.addEventListener("click", () => addExtra());
  parts.push(extra, addJob);
  // Businesses from tags.
  for (const business of gathered.businesses) {
    const set = element("fieldset"), mine = view.inputs.businesses?.[business.key] || {};
    set.append(element("legend", `${business.name} (Schedule C)`));
    const row = element("div", "", "forecast-row");
    for (const [key, label] of [["income", "Income for the year"], ["expenses", "Expenses that count"]]) {
      const input = taxInput(`tax-business-${business.key}-${key}`, mine[key], business.display[key]); input.dataset.business = business.key; input.dataset.key = key;
      row.append(forecastField(label, input));
    }
    set.append(row); parts.push(set);
  }
  // Every other field, grouped as on the return.
  for (const [title, fields] of RETURN_FIELDS) {
    const set = element("fieldset"), row = element("div", "", "forecast-row");
    set.append(element("legend", title));
    for (const [key, label, count] of fields) {
      const input = count ? forecastInput(`tax-field-${key}`, {type: "number", min: "0", max: "20", placeholder: String(view.input[key] ?? 0)}) : taxInput(`tax-field-${key}`, typed[key], gathered.display[key], gathered.sources[key]);
      if (count) input.value = typed[key] ?? "";
      input.dataset.field = key; row.append(valueKind(forecastField(label, input), typed[key], gathered, key));
    }
    if (title === "Adjustments") {
      // Blank: what the records say (finance/tax_year.py works it out from the year's HSA contributions).
      const recorded = {self: "Self-only", family: "Family"}[gathered.values.hsa_coverage];
      const coverage = planSelect("tax-field-hsa_coverage", {"": recorded ? `From records: ${recorded}` : "Not said", self: "Self-only", family: "Family"}, typed.hsa_coverage || "");
      if (gathered.sources.hsa_coverage) coverage.title = gathered.sources.hsa_coverage;
      row.append(valueKind(forecastField("HSA coverage", coverage), typed.hsa_coverage, gathered, "hsa_coverage"));
    }
    if (title === "Deductions") {
      const choose = planSelect("tax-field-itemize", {auto: "Whichever is larger", yes: "Itemize"}, typed.itemize === true ? "yes" : "auto");
      const jobs = Object.fromEntries([["", "Not said"], ...view.tipped_occupations.map(slug => [slug, slug === "other" ? "Not on the list" : slug.replaceAll("-", " ")])]);
      const occupation = planSelect("tax-field-tipped_occupation", jobs, typed.tipped_occupation || "");
      row.append(forecastField("Deduction", choose), forecastField("Tipped occupation (Treasury list)", occupation));
    }
    set.append(row); parts.push(set);
  }
  // People on the return (a spouse's birth year counts for 65 or older), and students.
  const spouse = (view.inputs.people || [])[0] || {};
  const people = element("fieldset"); people.append(element("legend", "Your spouse on this return"));
  const peopleRow = element("div", "", "forecast-row");
  const spouseName = forecastInput("tax-spouse-name", {maxlength: "60", placeholder: "Only when filing jointly"}); spouseName.value = spouse.name || "";
  const spouseYear = forecastInput("tax-spouse-year", {type: "number", min: "1900", max: "2100"}); spouseYear.value = spouse.birth_year || "";
  peopleRow.append(forecastField("Name", spouseName), forecastField("Birth year", spouseYear)); people.append(peopleRow); parts.push(people, priorSet);
  const save = element("button", "Save and estimate again", "primary"); save.type = "submit";
  parts.push(element("div", "", "button-row")); parts[parts.length - 1].append(save);
  form.replaceChildren(...parts);
}
function taxInputsRequest() {
  const form = $("taxes-inputs"), fields = {}, jobs = {}, businesses = {};
  for (const input of form.querySelectorAll("[data-field]")) if (input.value.trim() !== "") fields[input.dataset.field] = input.value.trim();
  const itemize = $("tax-field-itemize").value; if (itemize === "yes") fields.itemize = true;
  const occupation = $("tax-field-tipped_occupation").value; if (occupation) fields.tipped_occupation = occupation;
  const coverage = $("tax-field-hsa_coverage").value; if (coverage) fields.hsa_coverage = coverage;
  for (const input of form.querySelectorAll("[data-job]")) if (input.value.trim() !== "") (jobs[input.dataset.job] ||= {})[input.dataset.key] = input.value.trim();
  for (const input of form.querySelectorAll("[data-business]")) if (input.value.trim() !== "") (businesses[input.dataset.business] ||= {})[input.dataset.key] = input.value.trim();
  const extra_jobs = [...form.querySelectorAll(".taxes-extra-job")].map(row => Object.fromEntries([...row.querySelectorAll("input")].map(input => [input.dataset.key, input.value.trim()])))
    .filter(job => job.wages || job.federal_withheld);
  const people = $("tax-spouse-name").value.trim() || $("tax-spouse-year").value ? [{name: $("tax-spouse-name").value.trim() || "Spouse", birth_year: Number($("tax-spouse-year").value) || null}] : [];
  const w4 = {};
  for (const input of form.querySelectorAll("[data-w4]")) {
    const entry = (w4[input.dataset.w4] ||= {});
    if (input.type === "checkbox") entry.step2 = input.checked; else if (input.value.trim() !== "") entry[input.dataset.key] = input.value.trim();
  }
  const prior_year_tax = $("tax-prior-tax").value.trim() ? {tax: $("tax-prior-tax").value.trim(), agi: $("tax-prior-agi").value.trim() || null} : null;
  return {...taxView.inputs, fields, jobs, businesses, extra_jobs, people, w4, prior_year_tax};
}
$("taxes-inputs").addEventListener("submit", async event => {
  event.preventDefault();
  try { await saveTaxInputs(taxInputsRequest()); notice("Saved; the return is estimated again."); }
  catch (error) { notice(error, true); }
});
$("taxes-year").addEventListener("change", () => { location.hash = `#/taxes?year=${$("taxes-year").value}`; });
function renderWriteOffs(summary, tags) {
  const target = $("taxes-write-offs"), parts = [];
  const waiting = tags.filter(tag => tag.review_status === "proposed").length;
  if (!summary.lines.length) parts.push(emptyState(waiting
    ? `Nothing counts for ${summary.year} yet: ${waiting} suggestion${waiting === 1 ? " waits" : "s wait"} in Review.`
    : `Nothing tagged for ${summary.year} yet. Tag a transaction from its drawer, a receipt from its page, or add a tax rule below.`));
  else {
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Counts as", false], ["Line", false], ["Business", false], ["Items", true], ["Amount", true], ["Counts", true]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
    const body = table.createTBody();
    for (const line of summary.lines) {
      const tr = body.insertRow(); cell(tr, line.kind_label); cell(tr, line.line_label); cell(tr, line.business || "—"); cell(tr, line.items).className = "numeric";
      for (const value of [line.amount, line.counted]) tr.appendChild(element("td", "", "numeric")).appendChild(amount(value, {signed: false}));
    }
    wrap.append(table); parts.push(wrap);
  }
  parts.push(...summary.notes.map(note => element("p", note, "muted small")));
  if (tags.length) {
    const details = element("details", "", "tax-items"), wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
    const head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Date", false], ["Item", false], ["Counts as", false], ["Amount", true], ["", false]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
    const body = table.createTBody();
    for (const tag of tags) {
      const tr = body.insertRow(); tr.appendChild(element("td")).append(dateDisplay(tag.tax_date));
      const item = tr.insertCell();
      item.append(tag.transaction_id ? taxItemLink(tag) : element("span", tag.target.description), element("small", tag.target.detail || "", "muted block"));
      const what = tr.insertCell(); what.append(element("span", `${tag.kind_label}: ${tag.line_label}`), element("small", tag.review_status === "proposed" ? "Waiting in Review" : TAX_SOURCES[tag.source], "muted block"));
      tr.appendChild(element("td", "", "numeric")).appendChild(amount(tag.display.counted_minor, {signed: false}));
      tr.insertCell().append(asyncButton("Not a write-off", async () => { await api(`/api/tax-tags/${tag.id}/not-a-write-off`, {method: "POST"}); notice("Untagged."); await loadTaxes(); }, "small quiet"));
    }
    wrap.append(table); details.append(element("summary", `Every tagged item in ${summary.year} (${tags.length})`), wrap); parts.push(details);
  }
  target.replaceChildren(...parts);
}
function taxItemLink(tag) {
  const button = element("button", tag.target.description, "link-button"); button.type = "button";
  button.addEventListener("click", () => openTransaction(tag.transaction_id).catch(error => notice(error, true)));
  return button;
}
function renderTaxRules(rules, setup, target = $("taxes-rules"), reload = loadTaxes) {
  const parts = [];
  if (rules.length) {
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Bank lines containing", false], ["Count as", false], ["Business", false], ["Tagged", true], ["", false]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
    const body = table.createTBody();
    for (const rule of rules) {
      const tr = body.insertRow(); cell(tr, rule.pattern, true); cell(tr, `${rule.kind_label}: ${rule.line_label}`); cell(tr, rule.business || "—"); cell(tr, rule.tagged).className = "numeric";
      tr.insertCell().append(asyncButton("Delete", async () => {
        if (!await confirmAction({title: `Delete the rule “${rule.pattern}”?`, message: "Its tags are removed from bank lines not tagged by hand; those payees may be suggested again.", confirmLabel: "Delete", danger: true})) return;
        await api(`/api/tax/rules/${rule.id}`, {method: "DELETE"}); notice("Rule deleted."); await reload();
      }, "small quiet"));
    }
    wrap.append(table); parts.push(wrap);
  } else parts.push(element("p", "No tax rules yet. Tick “Always for bank lines containing…” when tagging a transaction, or confirm a suggestion with a rule.", "muted small"));
  target.replaceChildren(...parts);
}
function renderBusinesses(setup) {
  const list = $("taxes-businesses");
  list.replaceChildren(...(setup.businesses.length ? setup.businesses.map(item => element("li", item.name)) : [element("li", "None yet. Contract (1099) work counts as a business: add one to tag its income and expenses.", "muted")]));
}
$("taxes-business-form").addEventListener("submit", async event => {
  event.preventDefault();
  const name = $("taxes-business-name").value.trim();
  if (!name) return;
  try { await api("/api/tax/businesses", {method: "POST", body: JSON.stringify({name})}); $("taxes-business-name").value = ""; notice(`${name} added.`); await loadTaxes(); }
  catch (error) { notice(error, true); }
});
