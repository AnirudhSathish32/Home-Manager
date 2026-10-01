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
async function loadTaxes() {
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

// The year-end CPA pack (finance/cpa_pack.py) and the exchange rates its USD values use (finance/fx.py).
async function loadCpaPacks(year) {
  const [{packs}, rates] = await Promise.all([api(`/api/tax/cpa-packs?year=${year}`), api("/api/rates")]);
  const parts = [];
  if (rates.needed) {
    const state = !rates.enabled ? "Exchange-rate downloads are off in Settings, so foreign amounts stay unconverted."
      : rates.downloaded ? `Foreign amounts are converted at ECB reference rates, downloaded through ${rates.last_rate_date}.`
      : "Foreign amounts need ECB reference rates, which haven't been downloaded yet.";
    const line = element("p", state, "muted small");
    if (rates.enabled) line.append(" ", asyncButton("Refresh rates", async () => { await api("/api/rates/refresh", {method: "POST"}); notice("Exchange rates updated."); await loadCpaPacks(year); }, "small quiet"));
    parts.push(line);
  }
  const actions = element("p");
  parts.push(actions);
  actions.append(asyncButton(`Build the ${year} CPA pack`, async () => {
    const pack = await api(`/api/tax/cpa-packs/${year}`, {method: "POST"});
    notice(pack.reused ? "Nothing changed since the last pack; it's ready to download." : "CPA pack built.");
    await loadCpaPacks(year);
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
  $("taxes-pack").replaceChildren(...parts);
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
  ["Income", [["interest", "Taxable interest"], ["tax_exempt_interest", "Tax-exempt interest"], ["ordinary_dividends", "Ordinary dividends (1099-DIV 1a)"],
              ["qualified_dividends", "Qualified dividends (1099-DIV 1b)"], ["short_term_gain", "Short-term gain or loss"], ["long_term_gain", "Long-term gain or loss"],
              ["capital_loss_carryover", "Capital loss carried from last year"], ["retirement_distributions", "Taxable retirement distributions"],
              ["early_distributions", "…taken early (before 59½)"], ["social_security_benefits", "Social Security benefits"], ["unemployment", "Unemployment"],
              ["hsa_nonqualified", "HSA money not spent on medical care"], ["other_income", "Other income"]]],
  ["Adjustments", [["educator_expenses", "Educator expenses"], ["hsa_contributions", "HSA contributions (not through payroll)"],
                   ["se_health_insurance", "Self-employed health insurance"], ["ira_deduction", "Deductible IRA contributions"],
                   ["student_loan_interest", "Student-loan interest"], ["other_adjustments", "Other adjustments"]]],
  ["Deductions", [["medical", "Medical and dental"], ["state_local_tax", "State and local income tax"], ["property_tax", "Property tax"],
                  ["mortgage_interest", "Mortgage interest"], ["charity", "Charity"], ["other_itemized", "Other itemized"],
                  ["other_deductions", "Other deductions (e.g. tips, overtime, car-loan interest)"]]],
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
  if (free.length) {
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
      try { await api("/api/tax/units", {method: "POST", body: JSON.stringify({members, filing_status: status.value})}); await loadFamilyTaxes(family.year); }
      catch (error) { notice(error, true); }
    });
    parts.push(element("h3", "Add a return"), form);
  }
  if (!family.returns.length && !free.length) parts.push(emptyState("No one in the family has shared records yet."));
  target.replaceChildren(...parts);
  const shown = family.returns.find(item => item.id === taxUnit) || family.returns[0];
  $("taxes-return-panel").hidden = !shown;
  if (shown) { taxUnit = shown.id; $("taxes-return-title").textContent = `${shown.name}: the return, estimated`; renderTaxYear(shown.view); }
}
function taxInput(id, value, placeholder, title = "") {
  const input = forecastInput(id, {inputmode: "decimal"}); input.value = value ?? ""; input.placeholder = placeholder || "0.00";
  if (title) input.title = title;
  return input;
}
// Tax Zen (finance/tax_zen.py): what to put on a W-4, or pay ahead, so the return comes out at $0.
function renderTaxZen(view) {
  const zen = view.zen, target = $("taxes-zen"), parts = [element("h3", "Tax Zen", "")];
  parts[0].id = "taxes-zen-title";
  if (!zen?.ready) { target.replaceChildren(...parts, element("p", zen?.note || "", "muted small")); return; }
  if (zen.zen) parts.push(element("p", `You're Tax Zen for ${view.year}: the return comes out within a dollar of $0.`, "taxes-zen-headline"));
  const job = zen.job;
  if (job && !zen.zen) {
    const rest = job.rest, entry = rest.field === "4(a)" ? "Step 4(a), other income" : "Step 4(b), deductions";
    const headline = element("p", "", "taxes-zen-headline");
    if (rest.unreachable) headline.textContent = `No W-4 entry at ${job.name} can close this with ${job.paychecks_left} paychecks left: withholding can't go below zero. `
      + "The rest comes back as a refund; see January below.";
    else headline.append(`On ${job.name}'s W-4, put `, element("strong", `${rest.display.amount}`), ` in ${entry}, for the ${job.paychecks_left} paychecks left this year.`);
    parts.push(headline);
    if (!rest.unreachable) parts.push(element("p", `Withholding becomes ${rest.display.per_check} a paycheck (now ${job.display.per_check_now_minor}), and the year ends at `
      + `${rest.year_end_minor >= 0 ? "a refund of" : "owing"} ${rest.display.year_end_minor.replace("-", "")}. The amount replaces what's in that box now; leave the other boxes as they are.`, "small"));
    if (job.extra) parts.push(element("p", `Or keep the W-4 as it is and add ${job.extra.display.per_check_minor} of extra withholding a paycheck (Step 4(c): ${job.extra.display.total_4c_minor} in all).`, "small"));
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
function renderTaxYear(view) {
  taxView = view;
  renderTaxZen(view);
  $("taxes-figures-box").replaceChildren(taxFiguresEditor(view));  // Saved on its own, apart from the editor's typed values.
  const result = view.return, alerts = $("taxes-alerts");
  alerts.replaceChildren();
  for (const [code, status] of Object.entries(view.tables)) if (status !== "verified") {
    const name = code === "US" ? "federal" : code;
    alerts.append(alertBox(status === "proposed" ? `The ${view.year} ${name} tax table waits for you in Review.` : `The ${view.year} ${name} tax table hasn't been looked up yet.`,
      {tone: "warning", action: status === "proposed" ? homeLink("Open Review", "#/review") : asyncButton(`Look up the ${view.year} ${name} table`, async () => {
        await api("/api/tax-tables/lookup", {method: "POST", body: JSON.stringify({jurisdiction: code, year: view.year, filing_status: view.filing_status})});
        notice("Looking it up. The table will wait for you in Review.");
      })}));
  }
  const figuresMissing = (result.missing || []).filter(key => key !== "federal_table");
  if (figuresMissing.length) alerts.append(alertBox(`Some of the ${view.year} tax figures this return needs are missing: ${figuresMissing.map(key => view.figures.labels[key] || key).join("; ")}.`,
    {tone: "warning", action: view.figures.waiting ? homeLink("They wait in Review", "#/review") : asyncButton(`Look up the ${view.year} figures`, async () => {
      await api(`/api/tax/figures/${view.year}/lookup`, {method: "POST", body: JSON.stringify({})}); notice("Looking them up. They will wait for you in Review.");
    })}));
  const target = $("taxes-return");
  if (result.result_minor == null) { target.replaceChildren(emptyState(result.notes[0])); renderTaxInputs(view); return; }
  const headline = element("dl", "", "plan-headline");
  const zero = result.result_minor === 0;
  for (const [label, value, big] of [[zero ? "Tax Zen" : result.result.refund ? "Refund" : "You'd owe", zero ? "0.00 USD" : result.result.display, true],
      ["Total tax", result.lines.find(line => line.key === "total_tax").display], ["Paid and credited", result.lines.find(line => line.key === "total_payments").display]]) {
    const dd = element("dd", "", big ? "plan-figure" : ""); dd.append(amount(value, {signed: false})); headline.append(element("dt", label), dd);
  }
  const parts = [headline, element("p", `${view.year} · filing ${view.filing_status_name} · top federal bracket ${(result.marginal_bp / 100).toFixed(0)}%. `
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
    const unrecorded = job.paychecks_projected - job.paychecks_left;
    set.append(element("legend", job.name), element("p", `${job.stubs} pay stub${job.stubs === 1 ? "" : "s"} through ${dateText(job.last_pay_date)}; `
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
      input.dataset.field = key; row.append(forecastField(label, input));
    }
    if (title === "Deductions") {
      const choose = planSelect("tax-field-itemize", {auto: "Whichever is larger", yes: "Itemize", no: "Standard deduction"}, typed.itemize === true ? "yes" : typed.itemize === false ? "no" : "auto");
      row.append(forecastField("Deduction", choose));
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
  const itemize = $("tax-field-itemize").value; if (itemize !== "auto") fields.itemize = itemize === "yes";
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
function taxFiguresEditor(view) {
  // The year's figures: confirmed from a lookup, typed by you, or missing. Typing one counts at once.
  const figures = view.figures, details = element("details", "", "taxes-figures");
  details.open = (view.return.missing || []).some(key => key !== "federal_table");
  details.append(element("summary", `Tax figures for ${view.year} (${Object.keys(figures.values).length} of ${Object.keys(figures.labels).length} known)`));
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  for (const [title, numeric] of [["Figure", false], ["Value", true], ["From", false], ["Type your own", false]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const body = table.createTBody();
  for (const [key, label] of Object.entries(figures.labels)) {
    const tr = body.insertRow(); cell(tr, label);
    tr.appendChild(element("td", figures.display[key] || "—", "numeric"));
    cell(tr, {lookup: "Looked up, confirmed", typed: "Typed by you"}[figures.sources[key]] || (figures.waiting ? "Waiting in Review" : "Missing"));
    const input = forecastInput(`tax-figure-${key}`, {maxlength: "20", placeholder: figures.kinds[key] === "rate" ? "e.g. 35%" : "e.g. 48,350"});
    input.value = figures.typed?.figures?.[key] ? figures.typed.figures[key].display.replace(" USD", "") : ""; input.dataset.figure = key;
    input.setAttribute("aria-label", `Your figure: ${label}`); tr.insertCell().append(input);
  }
  wrap.append(table);
  const save = element("button", "Save figures", "small"); save.type = "button"; save.dataset.figures = "1";
  save.addEventListener("click", async () => {
    const values = Object.fromEntries([...details.querySelectorAll("[data-figure]")].map(input => [input.dataset.figure, input.value.trim() || null]));
    try {
      await api(`/api/tax/figures/${view.year}`, {method: "PUT", body: JSON.stringify({figures: values, filing_status: view.filing_status})}); notice("Figures saved.");
      if (taxUnit == null) renderTaxYear(await api(`/api/tax/year/${view.year}`)); else await loadFamilyTaxes(view.year);
    }
    catch (error) { notice(error, true); }
  });
  details.append(element("p", "Figures come from the year's IRS inflation adjustments and form instructions. A looked-up set waits for you in Review; a figure you type counts at once.", "muted small"), wrap, save);
  return details;
}
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
function renderTaxRules(rules, setup) {
  const target = $("taxes-rules"), parts = [];
  if (rules.length) {
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Bank lines containing", false], ["Count as", false], ["Business", false], ["Tagged", true], ["", false]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
    const body = table.createTBody();
    for (const rule of rules) {
      const tr = body.insertRow(); cell(tr, rule.pattern, true); cell(tr, `${rule.kind_label}: ${rule.line_label}`); cell(tr, rule.business || "—"); cell(tr, rule.tagged).className = "numeric";
      tr.insertCell().append(asyncButton("Delete", async () => {
        if (!await confirmAction({title: `Delete the rule “${rule.pattern}”?`, message: "Its tags are removed from bank lines not tagged by hand; those payees may be suggested again.", confirmLabel: "Delete", danger: true})) return;
        await api(`/api/tax/rules/${rule.id}`, {method: "DELETE"}); notice("Rule deleted."); await loadTaxes();
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
