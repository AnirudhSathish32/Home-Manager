"use strict";
// Investments (docs/planning.md "Investments"): accounts grouped by section, what share each section and tax treatment holds,
// and one account's values over time. The server does every sum and share; the page only arranges its text.
// The open account lives in the URL (#/investments?account=ID) so Back and reload keep it.
let investmentKinds = [];
const SOURCE_LABELS = {manual: "Entered by you", statement: "Statement", ledger_statement: "Savings statement", estimated: "Estimated from purchase terms",
                       quote: "Market price"};
const TERM_CLASSES = [["cd", "CD"], ["treasury_bill", "Treasury bill"], ["treasury_note", "Treasury note"], ["treasury_bond", "Treasury bond"],
                      ["i_bond", "I bond"], ["bond", "Bond"]];

function fillKindSelect(select, kinds, chosen = select.value) {
  const groups = new Map();
  for (const kind of kinds) { if (!groups.has(kind.section_label)) groups.set(kind.section_label, []); groups.get(kind.section_label).push(kind); }
  select.replaceChildren(...[...groups].map(([label, members]) => {
    const group = document.createElement("optgroup"); group.label = label;
    group.append(...members.map(kind => new Option(kind.label, kind.key)));
    return group;
  }));
  select.value = chosen || "brokerage";
}

function shareTable(title, rows) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
  const caption = element("caption", title, "visually-hidden"), head = table.createTHead().insertRow();
  for (const [label, numeric] of [[title, false], ["Value", true], ["Share", true]]) {
    const th = element("th", label, numeric ? "numeric" : ""); th.scope = "col"; head.append(th);
  }
  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow(); cell(tr, row.label);
    cell(tr, "").append(amount(row.total, {signed: false})); tr.lastChild.className = "numeric";
    cell(tr, `${row.share_percent}%`).className = "numeric";
  }
  table.prepend(caption); wrap.append(table); return wrap;
}

function payrollQuestion(question) {
  // Pay stubs list contributions the documents can't place: several accounts could hold them, or there is none yet.
  if (!question.accounts.length) {
    return alertBox(`Pay stubs from ${question.employer} list ${question.label} contributions. Add that account below to follow them.`, {tone: "info"});
  }
  const form = element("form", "", "inline-form"), select = document.createElement("select");
  for (const account of question.accounts) select.add(new Option(account.name, String(account.id)));
  const save = element("button", "Save"); save.type = "submit";
  form.append(field("Account ", select), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api(`/api/investments/${select.value}/payroll`, {method: "POST", body: JSON.stringify({employer_id: question.employer_id})});
      notice(`${question.employer}'s ${question.label} contributions now go to ${select.selectedOptions[0].text}.`); await inv2Reload();
    } catch (error) { notice(error, true); }
  });
  return alertBox(`Pay stubs from ${question.employer} list ${question.label} contributions. Which account do they go to?`, {tone: "info", action: form});
}
function maturedButtons(holdingId, name, accountId) {
  // One answer closes the holding and records the maturity; a renewal is then added as a new CD or Treasury.
  return [["Paid out", "cash"], ["Renewed", "rollover"]].map(([label, outcome]) => asyncButton(label, async () => {
    await api(`/api/investments/holdings/${holdingId}/matured`, {method: "POST", body: JSON.stringify({outcome})});
    notice(outcome === "cash" ? `${name} recorded as paid out.` : `${name} closed. Add the renewed one to this account.`);
    const next = `#/investments?account=${accountId}${outcome === "rollover" ? `&renew=${holdingId}` : ""}`;
    if (location.hash === next) await inv2Reload(); else location.hash = next;
  }, "small"));
}

function field(label, control) {
  const wrap = element("label", label, "inline-field"); wrap.append(control); return wrap;
}
function investmentSettingsForm(account) {
  const form = element("form", "", "inline-form"), name = document.createElement("input"), kind = document.createElement("select");
  const institution = document.createElement("input"), rate = document.createElement("input"), tax = document.createElement("select");
  name.required = true; name.maxLength = 80; name.value = account.name;
  institution.maxLength = 80; institution.value = account.institution;
  rate.inputMode = "decimal"; rate.value = account.rate_is_default ? "" : account.annual_rate_percent; rate.placeholder = "Kind's default";
  fillKindSelect(kind, investmentKinds, account.kind);
  tax.add(new Option("Same as its kind", ""));
  for (const [key, label] of [["taxable", "Taxable"], ["tax_deferred", "Tax-deferred"], ["tax_free", "Tax-free"], ["hsa", "HSA"]]) tax.add(new Option(label, key));
  tax.value = account.tax_overridden ? account.tax_treatment : "";
  // A savings account already in Accounts (a HYSA): its statements become this account's values.
  const linked = document.createElement("select");
  linked.add(new Option("None", ""));
  for (const option of account.linkable_accounts) linked.add(new Option(option.display_name, String(option.id)));
  linked.value = account.ledger_account_id ? String(account.ledger_account_id) : "";
  // Whose pay stub 401(k) or HSA lines go here: matched from the documents unless you choose.
  const payroll = document.createElement("select");
  payroll.add(new Option(account.payroll_link === "auto" && account.payroll_employer ? `${account.payroll_employer} (matched automatically)` : "Match automatically", ""));
  payroll.add(new Option("No employer", "0"));
  for (const employer of account.payroll_employers) payroll.add(new Option(employer.name, String(employer.id)));
  payroll.value = account.payroll_link === "user" ? String(account.payroll_merchant_id) : account.payroll_link === "none" ? "0" : "";
  const monthly = document.createElement("input");
  monthly.inputMode = "decimal"; monthly.placeholder = "From recent activity";
  monthly.value = account.monthly_contribution ? account.monthly_contribution.display.replace(/\s[A-Z]{3}$/, "") : "";
  // A 529's beneficiary (a profile's name or anyone's) and the state whose plan it is.
  const beneficiary = document.createElement("input"), planState = document.createElement("input");
  beneficiary.maxLength = 80; beneficiary.value = account.beneficiary || "";
  planState.maxLength = 2; planState.size = 3; planState.placeholder = "UT"; planState.value = account.plan_state || ""; planState.autocapitalize = "characters";
  const save = element("button", "Save changes"); save.type = "submit";
  form.append(field("Name ", name), field("Kind ", kind), field("Institution ", institution), field("Yearly rate (%) ", rate), field("Tax treatment ", tax),
              field("Bank account ", linked), ...(account.takes_payroll ? [field("Contributions from pay at ", payroll)] : []),
              ...(account.is_education ? [field("Beneficiary ", beneficiary), field("Plan state ", planState)] : []),
              field(`You add each month (${account.currency}) `, monthly), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const body = {name: name.value.trim(), kind: kind.value, institution: institution.value.trim()};
    if (account.is_education && beneficiary.value.trim()) body.beneficiary = beneficiary.value.trim();
    if (account.is_education && planState.value.trim()) body.plan_state = planState.value.trim().toUpperCase();
    if (rate.value.trim()) body.annual_rate_percent = rate.value.trim();
    if (tax.value) body.tax_treatment = tax.value;
    if (linked.value) body.ledger_account_id = Number(linked.value);
    if (account.takes_payroll && payroll.value) body.payroll_employer_id = Number(payroll.value);
    if (monthly.value.trim()) body.monthly_contribution = monthly.value.trim();
    try { await api(`/api/investments/${account.id}`, {method: "PUT", body: JSON.stringify(body)}); notice("Saved."); await inv2Reload(); } catch (error) { notice(error, true); }
  });
  return form;
}
function investmentValueForm(account) {
  const form = element("form", "", "inline-form"), value = document.createElement("input"), asOf = document.createElement("input");
  value.required = true; value.inputMode = "decimal"; value.placeholder = "25000.00";
  asOf.type = "date"; asOf.required = true; asOf.value = todayIso();
  const save = element("button", "Record value"); save.type = "submit";
  form.append(field(`Value (${account.currency}) `, value), field("As of ", asOf), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api(`/api/investments/${account.id}/values`, {method: "POST", body: JSON.stringify({value: value.value.trim(), as_of: asOf.value})});
      notice("Value recorded."); await inv2Reload();
    } catch (error) { notice(error, true); }
  });
  return form;
}
function investmentHistory(account) {
  if (!account.history.length) return element("p", "No values recorded.", "muted");
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  for (const [title, numeric] of [["As of"], ["Value", true], ["Source"], ["Status"]]) { const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th); }
  const body = table.createTBody();
  for (const row of account.history) {
    const tr = body.insertRow(); cell(tr, dateText(row.as_of));
    const value = cell(tr, ""); value.className = "numeric"; value.append(amount(row.value, {signed: false}));
    const source = cell(tr, "");
    source.append(row.document_id ? homeLink("Statement", `#/documents/${row.document_id}`) : element("span", SOURCE_LABELS[row.source] || row.source));
    cell(tr, "").append(statusBadge(row.source === "estimated" ? "estimated" : row.source === "quote" ? "quote" : row.review_status));
  }
  wrap.append(table); return wrap;
}
function moneyCell(tr, value, signed = false) {
  const td = cell(tr, ""); td.className = "numeric";
  td.append(value ? amount(value, {signed}) : element("span", "—", "muted"));
  return td;
}
function investmentHoldings(account) {
  // Columns appear only when a holding has them: market details for funds and stocks, terms for CDs, bonds and Treasuries.
  const has = test => account.holdings.some(test);
  const market = has(holding => holding.quantity || holding.price || holding.cost_basis);
  const terms = has(holding => holding.rate_percent != null || holding.maturity_date);
  const states = has(holding => holding.estimated || holding.review_status === "proposed" || holding.value_source === "quote");
  // An I bond: what it pays if cashed today (nothing in its first year; three months' interest less before five years).
  const ibonds = has(holding => holding.penalty_until);
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  const columns = [["Holding"], ["Type"], ...(market ? [["Quantity", true], ["Price", true]] : []), ["Value", true], ...(market ? [["Cost basis", true], ["Gain", true]] : []),
                   ...(terms ? [["Rate", true], ["Matures"], ["At maturity", true]] : []), ...(ibonds ? [["If cashed today", true]] : []), ...(states ? [["Status"]] : [])];
  for (const [title, numeric] of columns) { const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th); }
  const body = table.createTBody();
  for (const holding of account.holdings) {
    const tr = body.insertRow(), name = cell(tr, holding.name);
    if (holding.identifier) name.append(element("small", holding.identifier, "muted block mono"));
    cell(tr, holding.class_label);
    if (market) { cell(tr, holding.quantity || "—").className = "numeric"; moneyCell(tr, holding.price); }
    // An estimated holding's value is traced: its figure opens how the terms give it.
    if (holding.value?.trace) { const value = cell(tr, ""); value.className = "numeric"; value.append(figure(holding.value, {size: "sm", signed: false})); }
    else moneyCell(tr, holding.value);
    if (market) { moneyCell(tr, holding.cost_basis); moneyCell(tr, holding.gain, true); }
    if (terms) {
      cell(tr, holding.rate_percent != null ? `${holding.rate_percent}%` : "—").className = "numeric";
      const matures = cell(tr, holding.maturity_date ? dateText(holding.maturity_date) : "—");
      if (holding.rollover) matures.append(element("small", "Renews itself", "muted block"));
      if (holding.redeemable_date) matures.append(element("small", `Can be cashed from ${dateText(holding.redeemable_date)}`, "muted block"));
      moneyCell(tr, holding.at_maturity);
    }
    if (ibonds) {
      const cashOut = moneyCell(tr, holding.cash_out);
      if (holding.penalty_until && !holding.cash_out) cashOut.append(element("small", "Not yet", "muted block"));
      else if (holding.penalty_until && holding.penalty_until > todayIso()) cashOut.append(element("small", `3 months' interest less until ${dateText(holding.penalty_until)}`, "muted block"));
    }
    if (states) {
      const state = cell(tr, "");
      if (holding.matured) state.append(statusBadge("matured"), ...maturedButtons(holding.id, holding.name, account.id));
      else if (holding.review_status === "proposed") state.append(statusBadge("proposed"));
      else if (holding.estimated) state.append(statusBadge("estimated"));
      else if (holding.value_source === "quote") state.append(statusBadge("quote"));
    }
  }
  wrap.append(table); return wrap;
}
function investmentLots(account, holdings) {
  // Purchase lots behind each holding: from confirmed buys, or entered for shares bought before the documents here begin.
  const details = element("details", "", "investment-add-holding");
  const missing = holdings.some(holding => holding.lots_missing.length);
  details.append(element("summary", `Tax lots${missing ? " (some sales have no purchase)" : ""}`));
  details.open = missing;
  for (const holding of holdings) {
    const section = element("div", "", "investment-lots");
    section.append(element("h4", holding.name));
    if (holding.lot_gain) { const gain = element("p", "Unrealized gain by lot cost: ", "small"); gain.append(figure(holding.lot_gain, {size: "sm"})); section.append(gain); }
    if (holding.lots.length) {
      const list = element("ul", "", "finance-list");
      for (const lot of holding.lots) {
        const li = element("li", `${dateText(lot.acquired_date)} · ${lot.shares} shares · cost ${lot.cost.display}${lot.source === "manual" ? " · entered by you" : ""}`);
        if (lot.id) li.append(asyncButton("Remove", async () => { await api(`/api/investments/lots/${lot.id}`, {method: "DELETE"}); notice("Lot removed."); await inv2Reload(); }, "small quiet"));
        list.append(li);
      }
      section.append(list);
    } else section.append(element("p", "No purchase lots recorded.", "muted small"));
    for (const gap of holding.lots_missing) section.append(element("p", `${gap.shares} shares sold on ${dateText(gap.date)} have no purchase lot.`, "item-warning"));
    const form = element("form", "", "inline-form"), acquired = document.createElement("input"), quantity = document.createElement("input"), cost = document.createElement("input");
    acquired.type = "date"; acquired.required = true; quantity.required = true; quantity.inputMode = "decimal"; cost.required = true; cost.inputMode = "decimal";
    const save = element("button", "Add lot", "small"); save.type = "submit";
    form.append(field("Bought ", acquired), field("Shares ", quantity), field(`Cost (${account.currency}) `, cost), save);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      try {
        await api(`/api/investments/holdings/${holding.id}/lots`, {method: "POST", body: JSON.stringify({acquired_date: acquired.value, quantity: quantity.value.trim(), cost: cost.value.trim()})});
        notice("Lot added."); await inv2Reload();
      } catch (error) { notice(error, true); }
    });
    section.append(form);
    details.append(section);
  }
  return details;
}
function investmentHoldingForm(account, renewing) {
  // A CD, Treasury or bond with no confirmation to read: its terms are enough to estimate it until a statement arrives.
  const details = element("details", "", "investment-add-holding"), form = element("form", "", "inline-form");
  details.append(element("summary", "Add a CD or Treasury"));
  details.open = renewing;
  const name = document.createElement("input"), kind = document.createElement("select"), principal = document.createElement("input");
  const issued = document.createElement("input"), rate = document.createElement("input"), matures = document.createElement("input");
  const face = document.createElement("input"), renews = document.createElement("input");
  name.required = true; name.maxLength = 200; name.placeholder = "12-month CD";
  for (const [key, label] of TERM_CLASSES) kind.add(new Option(label, key));
  principal.required = true; principal.inputMode = "decimal"; principal.placeholder = "10000.00";
  issued.type = "date"; issued.required = true; issued.value = todayIso();
  rate.inputMode = "decimal"; rate.placeholder = "4.10";
  matures.type = "date"; face.inputMode = "decimal"; face.placeholder = "Treasury bills";
  renews.type = "checkbox";
  const renewLabel = element("label", "", "inline-field"); renewLabel.append(renews, document.createTextNode(" Renews itself at maturity"));
  const save = element("button", "Add holding"); save.type = "submit";
  form.append(field(`Name `, name), field("Type ", kind), field(`Paid (${account.currency}) `, principal), field("Issued ", issued), field("Yearly rate or APY (%) ", rate),
              field("Matures ", matures), field(`Face value (${account.currency}) `, face), renewLabel, save);
  if (renewing) details.append(element("p", "Add the renewed CD or Treasury with its new terms.", "muted small"));
  details.append(form);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const body = {name: name.value.trim(), instrument_class: kind.value, principal: principal.value.trim(), issue_date: issued.value, rollover: renews.checked};
    if (rate.value.trim()) body.annual_rate_percent = rate.value.trim();
    if (matures.value) body.maturity_date = matures.value;
    if (face.value.trim()) body.face_value = face.value.trim();
    try {
      await api(`/api/investments/${account.id}/holdings`, {method: "POST", body: JSON.stringify(body)});
      notice(`${body.name} added.`);
      const next = `#/investments?account=${account.id}`;
      if (location.hash === next) await inv2Reload(); else location.hash = next;
    } catch (error) { notice(error, true); }
  });
  return details;
}
function investmentConfirmations(account) {
  // Each confirmation beside its document; its trades count once it's confirmed in Review.
  const list = element("ul", "", "finance-list");
  for (const confirmation of account.confirmations) {
    const li = document.createElement("li");
    li.append(element("strong", `${dateText(confirmation.trade_date)} · ${confirmation.trades.map(trade => `${trade.type_label} ${trade.name} ${trade.amount.display}`).join("; ")}`),
              document.createTextNode(" "), statusBadge(confirmation.review_status));
    if (confirmation.document_id) li.append(homeLink("Confirmation", `#/documents/${confirmation.document_id}`, "block small"));
    list.append(li);
  }
  return list;
}
function investmentActivity(account) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  for (const [title, numeric] of [["Date"], ["Activity"], ["Amount", true], ["Status"]]) { const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th); }
  const body = table.createTBody();
  for (const event of account.events) {
    const tr = body.insertRow(); cell(tr, dateText(event.event_date));
    const what = cell(tr, event.source_label ? `${event.type_label} · ${event.source_label}` : event.type_label);
    // The document's own wording, unless it only repeats the type; where it came from, and the bank line that paid it.
    if (event.note && event.note.toLowerCase() !== event.type_label.toLowerCase()) what.append(element("small", event.note, "muted block"));
    const origin = [event.source === "paystub" ? `Pay stub${event.also_on_statement ? ", also on a statement" : ""}` : "",
                    event.paid_from ? `Paid from ${event.paid_from}` : ""].filter(Boolean).join(" · ");
    if (origin) what.append(element("small", origin, "muted block"));
    if (event.paid_from && event.id) what.append(asyncButton("Not this payment", async () => {
      if (!await confirmAction({title: "Not this payment?", confirmLabel: "Not this payment",
                                message: `The ${event.paid_from} line counts as it did before. Review will ask which payment it was if others could match.`})) return;
      const result = await api(`/api/investments/events/${event.id}/unlink`, {method: "POST"});
      notice(result.question ? "Unmatched. Review asks which payment it was." : "Unmatched; no other payment matches, so it's left unmatched.");
      await inv2Reload();
    }, "small quiet"));
    moneyCell(tr, event.amount);
    const state = cell(tr, "");
    if (account.is_education && event.id && ["withdrawal", "qualified_withdrawal", "nonqualified_withdrawal"].includes(event.event_type)) {
      // A 529 withdrawal's earnings are taxed only when it didn't pay for qualified education costs.
      if (event.event_type === "withdrawal") state.append(statusBadge("unmarked"));
      for (const [label, qualified, current] of [["Qualified", true, "qualified_withdrawal"], ["Not qualified", false, "nonqualified_withdrawal"]]) {
        if (event.event_type === current) continue;
        state.append(asyncButton(label, async () => {
          await api(`/api/investments/events/${event.id}/qualified`, {method: "POST", body: JSON.stringify({qualified})});
          notice(`Marked ${label.toLowerCase()}.`); await inv2Reload();
        }, "small quiet"));
      }
    } else state.append(statusBadge(event.review_status));
  }
  wrap.append(table); return wrap;
}

function pensionForm(account) {
  // A pension's terms, from its benefit statement: what it pays a month, from when, its yearly raise and the survivor's share.
  const pension = account.pension || {}, form = element("form", "", "inline-form");
  const benefit = document.createElement("input"), start = document.createElement("input"), cola = document.createElement("input");
  const survivor = document.createElement("input"), lump = document.createElement("input");
  benefit.required = true; benefit.inputMode = "decimal"; benefit.placeholder = "2400.00"; benefit.value = pension.monthly_benefit ? pension.monthly_benefit.decimal : "";
  start.type = "date"; start.required = true; start.value = pension.start_date || "";
  cola.inputMode = "decimal"; cola.placeholder = "0"; cola.value = pension.cola_bp ? pension.cola_percent : "";
  survivor.type = "number"; survivor.min = "0"; survivor.max = "100"; survivor.step = "1"; survivor.placeholder = "0"; survivor.value = pension.survivor_percent || "";
  lump.inputMode = "decimal"; lump.placeholder = "If offered"; lump.value = pension.lump_sum ? pension.lump_sum.decimal : "";
  const save = element("button", "Save terms"); save.type = "submit";
  form.append(field(`A month (${account.currency}) `, benefit), field("Starts ", start), field("Yearly raise (%) ", cola), field("Survivor (%) ", survivor),
              field(`Lump sum instead (${account.currency}) `, lump), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const body = {monthly_benefit: benefit.value.trim(), start_date: start.value, cola_percent: cola.value.trim() || "0", survivor_percent: Number(survivor.value || 0)};
    if (lump.value.trim()) body.lump_sum = lump.value.trim();
    try { await api(`/api/investments/${account.id}/pension`, {method: "PUT", body: JSON.stringify(body)}); notice("Pension terms saved."); await inv2Reload(); }
    catch (error) { notice(error, true); }
  });
  return form;
}

function educationWithdrawalForm(account) {
  // A 529 withdrawal the statement doesn't show yet, marked qualified (tuition, books, room and board) or not.
  const details = element("details", "", "investment-add-holding"), form = element("form", "", "inline-form");
  details.append(element("summary", "Record a withdrawal"));
  const day = document.createElement("input"), paid = document.createElement("input"), kind = document.createElement("select"), note = document.createElement("input");
  day.type = "date"; day.required = true; day.value = todayIso();
  paid.required = true; paid.inputMode = "decimal"; paid.placeholder = "6000.00";
  kind.add(new Option("Qualified education costs", "qualified_withdrawal")); kind.add(new Option("Not qualified", "nonqualified_withdrawal"));
  note.maxLength = 200; note.placeholder = "Fall tuition";
  const save = element("button", "Record withdrawal"); save.type = "submit";
  form.append(field("Date ", day), field(`Amount (${account.currency}) `, paid), field("Paid for ", kind), field("Note ", note), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api(`/api/investments/${account.id}/events`, {method: "POST", body: JSON.stringify({event_type: kind.value, event_date: day.value, amount: paid.value.trim(), note: note.value.trim()})});
      notice("Withdrawal recorded."); await inv2Reload();
    } catch (error) { notice(error, true); }
  });
  details.append(element("p", "Only the earnings part of a non-qualified withdrawal is taxed; the 1099-Q gives that share.", "muted small"), form);
  return details;
}

function ibondRates() {
  // The published I bond rates the values follow. TreasuryDirect announces new ones each May 1 and November 1.
  const details = element("details", "", "investment-add-holding");
  details.append(element("summary", "I bond rates"));
  const body = element("div");
  details.addEventListener("toggle", async () => {
    if (!details.open || body.childElementCount) return;
    try { body.replaceChildren(ibondRateTable(await api("/api/investments/ibond-rates"))); } catch (error) { body.replaceChildren(alertBox(error.message, {tone: "error"})); }
  });
  details.append(element("p", "Values are worked out from these rates as TreasuryDirect does: per $25, compounding every six months. Add each new rate when it's announced.",
                         "muted small"), body);
  return details;
}

function ibondRateTable(rates) {
  const holder = element("div"), wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  for (const [title, numeric] of [["From"], ["Fixed", true], ["Inflation, six months", true], ["Composite for new bonds", true]]) {
    const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th);
  }
  const tbody = table.createTBody();
  for (const rate of rates.slice(0, 6)) {
    const tr = tbody.insertRow(); cell(tr, dateText(rate.period_start));
    for (const value of [rate.fixed_percent, rate.inflation_percent, rate.composite_percent]) cell(tr, `${value}%`).className = "numeric";
  }
  wrap.append(table);
  const form = element("form", "", "inline-form"), from = document.createElement("select"), fixed = document.createElement("input"), inflation = document.createElement("input");
  const year = new Date().getFullYear();
  for (const day of [`${year}-11-01`, `${year}-05-01`, `${year + 1}-05-01`]) from.add(new Option(dateText(day), day));
  fixed.required = true; fixed.inputMode = "decimal"; fixed.placeholder = "0.90";
  inflation.required = true; inflation.inputMode = "decimal"; inflation.placeholder = "1.67";
  const save = element("button", "Save rate", "small"); save.type = "submit";
  form.append(field("From ", from), field("Fixed (%) ", fixed), field("Inflation (%) ", inflation), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await api("/api/investments/ibond-rates", {method: "PUT", body: JSON.stringify({period_start: from.value, fixed_percent: fixed.value.trim(), inflation_percent: inflation.value.trim()})});
      notice("Rate saved; I bond values follow it."); await inv2Reload();
    } catch (error) { notice(error, true); }
  });
  holder.append(wrap, form);
  return holder;
}

function cryptoTools(account) {
  // Market prices (only when Settings allows them) and an exchange's transaction history read into this account.
  const box = element("div", "", "investment-crypto"), row = element("div", "", "button-row"), status = element("p", "", "muted small");
  api("/api/prices").then(state => {
    status.textContent = !state.enabled ? "Market prices are off. Turn them on in Settings to value coins between statements."
      : state.fetched_at ? `Prices from ${state.source}, ${dateText(state.as_of)}. They never replace a statement's value for the same day or later.`
      : "No prices fetched yet.";
    if (state.unpriced.length) status.textContent += ` No price source here for ${state.unpriced.join(", ")}.`;
    if (state.enabled) row.prepend(asyncButton("Refresh prices", async () => {
      const result = await api("/api/prices/refresh", {method: "POST"});
      notice(result.valued ? `Prices updated for ${result.valued} account${result.valued === 1 ? "" : "s"}.` : result.skipped[0] || "Nothing to price.");
      await inv2Reload();
    }, "small"));
  }).catch(() => { status.textContent = ""; });
  const details = element("details", "", "investment-add-holding"), form = element("form", "", "inline-form"), file = document.createElement("select");
  details.append(element("summary", "Import a Coinbase export"));
  details.addEventListener("toggle", async () => {
    if (!details.open || file.options.length) return;
    const found = await Promise.all(["csv", "xlsx"].map(q => api(`/api/documents?limit=200&q=${q}`))).catch(() => []);
    const documents = found.flatMap(page => page.items || []).filter(doc => /\.(csv|xlsx)$/i.test(doc.relative_path));
    for (const doc of documents) file.add(new Option(doc.relative_path.split("/").pop(), String(doc.id)));
    if (!documents.length) form.replaceChildren(element("p", "Add the CSV from Coinbase's transaction history to Receipts & statements first.", "muted small"));
  });
  const save = element("button", "Import", "small"); save.type = "submit";
  form.append(field("File ", file), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const result = await api(`/api/investments/${account.id}/crypto-import`, {method: "POST", body: JSON.stringify({document_id: Number(file.value)})});
      notice(`${result.added} entr${result.added === 1 ? "y" : "ies"} imported${result.duplicates ? `, ${result.duplicates} already here` : ""}${result.issues.length ? `; ${result.issues.length} skipped` : ""}.`);
      await inv2Reload();
    } catch (error) { notice(error, true); }
  });
  details.append(element("p", "Buys, sells, sends, receives, conversions and rewards become this account's activity; buys open tax lots.", "muted small"), form);
  box.append(element("h3", "Prices and imports"), status, row, details);
  return box;
}
