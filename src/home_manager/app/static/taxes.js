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

// The Taxes page's shared parts (taxes_v2.js draws the page).
// The year-end CPA pack (finance/cpa_pack.py) and the exchange rates its USD values use (finance/fx.py). host: where it
// shows.
async function loadCpaPacks(year, host) {
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
// Add a return for family members on none yet (the family view). onAdded runs after it's saved.
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
function taxInput(id, value, placeholder, title = "") {
  const input = forecastInput(id, {inputmode: "decimal"}); input.value = value ?? ""; input.placeholder = placeholder || "0.00";
  if (title) input.title = title;
  return input;
}
// Tax Zen (finance/tax_zen.py): what to put on a W-4, or pay ahead, so the return comes out at $0.
// The aim (finance/tax_zen.py TaxZenPolicy), in words; the status badges are in ui.js STATUS.
const ZEN_STRATEGIES = {precision: "Come out at $0", small_refund: "A small refund", cash_retention: "Keep cash, owe a little", safe_harbor: "Owe what's allowed without a penalty"};
const ZEN_BADGES = {ZEN: "tax_zen", WATCH: "tax_watch", AT_RISK: "tax_at_risk", ACTION_RECOMMENDED: "tax_action", REVIEW_REQUIRED: "tax_review", INSUFFICIENT_DATA: "tax_insufficient", ENGINE_UNSUPPORTED: "tax_unsupported"};
// ids: the strategy and amount inputs' ids; save: how the page saves the year's inputs.
function zenPolicyForm(view, {ids, save: saveInputs}) {
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
// A warning for each of the year's tax tables that isn't confirmed, with the way to fix it.
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
// A tagged item opens where it can be checked: a receipt or one of its lines on its document page, a transaction in its drawer.
function taxItemLink(tag) {
  if (["receipt", "receipt_item"].includes(tag.target.type))
    return tag.target.document_id ? homeLink(tag.target.description, `#/documents/${tag.target.document_id}`) : element("span", tag.target.description);
  if (!tag.transaction_id) return element("span", tag.target.description);
  const button = element("button", tag.target.description, "link-button"); button.type = "button";
  button.addEventListener("click", () => openTransaction(tag.transaction_id).catch(error => notice(error, true)));
  return button;
}
function renderTaxRules(rules, setup, target, reload) {
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
