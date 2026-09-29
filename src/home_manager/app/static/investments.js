"use strict";
// Investments (docs/investments.md): accounts grouped by section, what share each section and tax treatment holds,
// and one account's values over time. The server does every sum and share; the page only arranges its text.
// The open account lives in the URL (#/investments?account=ID) so Back and reload keep it.
let investmentKinds = [], investmentsLoad = 0;
const SOURCE_LABELS = {manual: "Entered by you", statement: "Statement", ledger_statement: "Savings statement", estimated: "Estimated from purchase terms"};
const TERM_CLASSES = [["cd", "CD"], ["treasury_bill", "Treasury bill"], ["treasury_note", "Treasury note"], ["treasury_bond", "Treasury bond"],
                      ["i_bond", "I bond"], ["bond", "Bond"]];

async function loadInvestments(params = new URLSearchParams(location.hash.split("?")[1] || "")) {
  if (!configured) { $("investments-groups").replaceChildren(emptyState("Set up your library to track investments.")); return; }
  const load = ++investmentsLoad, archived = $("investments-archived").checked;
  $("investments-status").textContent = "Loading…";
  const [kinds, summary] = await Promise.all([investmentKinds.length ? investmentKinds : api("/api/investment-kinds"),
                                              api(`/api/investments${archived ? "?include_archived=true" : ""}`)]);
  if (load !== investmentsLoad) return;
  investmentKinds = kinds;
  fillKindSelect($("investment-kind"), kinds);
  if (!$("investment-as-of").value) $("investment-as-of").value = todayIso();
  $("investments-status").textContent = "";
  renderInvestmentSummary(summary);
  renderInvestmentGroups(summary);
  const selected = Number(params.get("account"));
  // Tax forms arrive early in the year for the year before, so that year is shown unless the URL names one.
  const year = Number(params.get("year")) || new Date().getFullYear() - 1;
  const taxes = api(`/api/investments/tax-years/${year}`).then(data => { if (load === investmentsLoad) renderInvestmentTaxes(data, params); })
    .catch(error => { $("investments-taxes").replaceChildren(alertBox(error.message, {tone: "error"})); });
  const rmd = api("/api/investments/rmd").then(data => { if (load === investmentsLoad) renderRequiredDistributions(data); })
    .catch(error => { $("investments-rmd").replaceChildren(alertBox(error.message, {tone: "error"})); });
  if (selected) await renderInvestmentDetail(selected, params.has("renew")).catch(error => { $("investment-detail").replaceChildren(alertBox(error.message, {tone: "error"})); });
  else $("investment-detail").replaceChildren();
  await Promise.all([taxes, rmd]);
}

function renderRequiredDistributions(data) {
  // This year's required minimum distributions from tax-deferred accounts (finance/retirement.py); nothing until there is one.
  const target = $("investments-rmd");
  if (!data.has_accounts) { target.replaceChildren(); return; }
  const panel = element("section", "", "panel");
  panel.append(element("h2", `Required minimum distributions, ${data.year}`));
  if (data.birth_year == null) {
    panel.append(emptyState("Add the year you were born in Settings to see when required minimum distributions begin and how much each tax-deferred account must pay out.",
                            homeLink("Open Settings", "#/settings")));
  } else if (data.begins_later) {
    panel.append(element("p", `They begin in ${data.first_year}, the year you turn ${data.start_age}. The first can wait until April 1, ${data.first_year + 1}.`));
  } else {
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Account"], ["Balance on Dec 31", true], ["Divisor", true], ["Required", true], ["Taken", true], ["Left", true], ["Deadline"], ["Status"]]) {
      const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th);
    }
    const body = table.createTBody();
    for (const row of data.accounts) {
      const tr = body.insertRow(), name = cell(tr, ""), link = element("a", row.name);
      link.href = `#/investments?account=${row.account_id}`; name.append(link);
      const balance = moneyCell(tr, row.balance);
      if (row.stale) balance.append(element("small", `as of ${dateText(row.balance_as_of)}`, "muted block"));
      cell(tr, row.divisor).className = "numeric";
      moneyCell(tr, row.required); moneyCell(tr, row.taken); moneyCell(tr, row.left);
      cell(tr, dateText(row.deadline));
      cell(tr, "").append(row.required ? statusBadge(row.status === "verified" ? "rmd_taken" : "due") : element("span", "No value on Dec 31", "muted"));
    }
    wrap.append(table);
    panel.append(element("p", `Age ${data.age} this year. Each tax-deferred account's balance at the end of last year is divided by the IRS Uniform Lifetime Table's `
                               + "divisor for your age. Roth accounts and HSAs have none. Not included: the still-working exception for a current employer's plan, "
                               + "inherited accounts, and a spouse more than ten years younger.", "muted small"), wrap);
  }
  target.replaceChildren(panel);
}

function renderInvestmentTaxes(data, params) {
  // One tax year: each 1099 or 5498 box beside what is recorded for its account, and realized gains in taxable accounts.
  const panel = element("section", "", "panel"), heading = element("div", "", "ledger-record-heading"), select = document.createElement("select");
  for (const year of data.years) select.add(new Option(String(year), String(year)));
  select.value = String(data.year); select.setAttribute("aria-label", "Tax year");
  select.addEventListener("change", () => { const next = new URLSearchParams(params); next.set("year", select.value); location.hash = `#/investments?${next}`; });
  heading.append(element("h2", `Taxes for ${data.year}`), select);
  panel.append(heading);
  for (const gains of data.gains) {
    const figures = element("div", "", "figure-group");
    for (const [label, value] of [["Sold for", gains.proceeds], ["Cost of what was sold", gains.cost], ["Short-term gain", gains.short], ["Long-term gain", gains.long]]) {
      const item = element("div", "", "figure-item"), figure = amount(value, {signed: label.endsWith("gain")}); figure.classList.add("figure-small");
      item.append(element("span", label, "figure-label"), figure); figures.append(item);
    }
    panel.append(element("h3", `Realized gains in taxable accounts${data.gains.length > 1 ? `, ${gains.currency}` : ""}`), figures,
                 element("p", "Sales are matched to purchase lots first in, first out; a lot held more than a year gives a long-term gain.", "muted small"));
    for (const gap of gains.missing) {
      panel.append(alertBox(`${gap.account}: ${gap.shares} shares sold on ${dateText(gap.date)} have no purchase recorded, so their gain isn't counted. Add the lot under the holding.`,
                            {tone: "warning", action: homeLink("Open the account", `#/investments?account=${gap.account_id}`)}));
    }
  }
  if (!data.checks.length) {
    panel.append(emptyState(`No 1099 or 5498 forms for ${data.year}. Add them to Receipts & statements; each box is then compared with what is recorded here.`));
  } else {
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Form"], ["Account"], ["Reports"], ["On the form", true], ["Recorded", true], ["Difference", true], ["Status"]]) {
      const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th);
    }
    const body = table.createTBody();
    for (const check of data.checks) {
      const tr = body.insertRow(), form = cell(tr, "");
      form.append(check.document_id ? homeLink(`${check.institution} ${check.forms.join(", ")}`, `#/documents/${check.document_id}`) : element("span", check.institution),
                  element("small", `Box ${check.boxes.join(", ")}`, "muted block"));
      cell(tr, check.account || "—");
      cell(tr, check.label);
      moneyCell(tr, check.form_amount); moneyCell(tr, check.recorded); moneyCell(tr, check.difference, true);
      cell(tr, "").append(statusBadge(check.review_status === "proposed" ? "proposed" : !check.recorded ? "tax_unlinked" : check.matches ? "tax_match" : "tax_differs"));
    }
    wrap.append(table);
    panel.append(element("p", "Recorded amounts are confirmed activity for the account in that year. A difference can mean a statement or pay stub isn't here yet.", "muted small"), wrap);
  }
  $("investments-taxes").replaceChildren(panel);
}

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

function renderInvestmentSummary(summary) {
  const nodes = [];
  if (summary.awaiting_review) {
    nodes.push(alertBox(`${summary.awaiting_review} statement value${summary.awaiting_review === 1 ? " or purchase waits" : "s or purchases wait"} for you. They count once you confirm them.`,
                        {tone: "info", action: homeLink("Open Review", "#/review")}));
  }
  for (const question of summary.payroll_questions) nodes.push(payrollQuestion(question));
  for (const total of summary.totals) {
    const panel = element("section", "", "panel investment-total");
    const figures = element("div", "", "figure-group"), main = element("div", "", "figure-main");
    const value = amount(total.total, {signed: false}); value.classList.add("figure-value");
    main.append(element("span", `Invested, ${total.currency}`, "figure-label"), value);
    const oldest = element("div", "", "figure-item");
    oldest.append(element("span", "Oldest value", "figure-label"), element("span", dateText(total.oldest_as_of), "figure-small"));
    figures.append(main, oldest);
    const split = element("div", "", "investment-split");
    split.append(shareTable("Section", total.sections), shareTable("Tax treatment", total.tax));
    const estimated = total.estimated_accounts
      ? ` ${total.estimated_accounts} account${total.estimated_accounts === 1 ? " is" : "s are"} estimated today from the terms of confirmed CDs and Treasuries.` : "";
    panel.append(element("h2", summary.totals.length > 1 ? `Confirmed values in ${total.currency}` : "Confirmed values"), figures,
                 element("p", `Each account counts at its newest confirmed value. Shares are of this total.${estimated}`, "muted small"), split);
    nodes.push(panel);
  }
  if (summary.maturities.length) nodes.push(maturityPanel(summary.maturities));
  $("investments-summary").replaceChildren(...nodes);
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
      notice(`${question.employer}'s ${question.label} contributions now go to ${select.selectedOptions[0].text}.`); await loadInvestments();
    } catch (error) { notice(error, true); }
  });
  return alertBox(`Pay stubs from ${question.employer} list ${question.label} contributions. Which account do they go to?`, {tone: "info", action: form});
}
function maturityPanel(maturities) {
  // CDs and Treasuries coming due in the next 90 days, and matured ones waiting for an answer: paid out, or renewed.
  const panel = element("section", "", "panel"), wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
  const head = table.createTHead().insertRow();
  for (const [title, numeric] of [["Holding"], ["Date"], ["Amount", true], ["Status"], ["What happened"]]) {
    const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th);
  }
  const body = table.createTBody();
  for (const due of maturities) {
    const tr = body.insertRow(), name = cell(tr, "");
    const link = element("a", due.name); link.href = `#/investments?account=${due.account_id}`;
    name.append(link, element("small", due.account, "muted block"));
    cell(tr, `${MATURITY_STATES[due.state === "matured" ? "matured" : due.kind]} ${dateText(due.date)}`);
    moneyCell(tr, due.amount);
    cell(tr, "").append(statusBadge(due.state));
    const actions = cell(tr, "");
    if (due.state === "matured") actions.append(...maturedButtons(due.holding_id, due.name, due.account_id));
    else actions.append(element("span", due.rollover ? "Renews itself" : "—", "muted"));
  }
  wrap.append(table);
  panel.append(element("h2", "Coming due"), element("p", "Amounts are what the terms pay at that date.", "muted small"), wrap);
  return panel;
}
function maturedButtons(holdingId, name, accountId) {
  // One answer closes the holding and records the maturity; a renewal is then added as a new CD or Treasury.
  return [["Paid out", "cash"], ["Renewed", "rollover"]].map(([label, outcome]) => asyncButton(label, async () => {
    await api(`/api/investments/holdings/${holdingId}/matured`, {method: "POST", body: JSON.stringify({outcome})});
    notice(outcome === "cash" ? `${name} recorded as paid out.` : `${name} closed. Add the renewed one to this account.`);
    const next = `#/investments?account=${accountId}${outcome === "rollover" ? `&renew=${holdingId}` : ""}`;
    if (location.hash === next) await loadInvestments(); else location.hash = next;
  }, "small"));
}

function renderInvestmentGroups(summary) {
  const groups = new Map();
  for (const account of summary.accounts) { if (!groups.has(account.section)) groups.set(account.section, []); groups.get(account.section).push(account); }
  const panels = [];
  for (const [section, label] of Object.entries(summary.sections)) {
    const members = groups.get(section);
    if (!members) continue;
    const panel = element("section", "", "panel"); panel.append(element("h2", label));
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
    const head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Account"], ["Kind"], ["Value", true], ["As of"], ["Change", true], ["Yearly rate", true], ["Status"]]) {
      const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th);
    }
    const body = table.createTBody();
    for (const account of members) body.append(investmentRow(account));
    wrap.append(table); panel.append(wrap); panels.push(panel);
  }
  $("investments-groups").replaceChildren(...(panels.length ? panels : [emptyState(
    "No investment accounts yet. Add one below, or add an investment statement to Receipts & statements and confirm its value in Review.")]));
}

function investmentRow(account) {
  const tr = document.createElement("tr");
  const name = cell(tr, ""), link = element("a", account.name);
  link.href = `#/investments?account=${account.id}`;
  name.append(link);
  if (account.institution) name.append(element("small", account.institution, "muted block"));
  cell(tr, account.kind_label);
  const value = cell(tr, ""); value.className = "numeric";
  value.append(account.current ? amount(account.current.value, {signed: false}) : element("span", "—", "muted"));
  cell(tr, account.current ? dateText(account.current.as_of) : "—");
  const change = cell(tr, ""); change.className = "numeric";
  if (account.change) { change.append(amount(account.change)); change.title = `Since ${dateText(account.change_since)}`; } else change.append(element("span", "—", "muted"));
  cell(tr, `${account.annual_rate_percent}%${account.rate_is_default ? " (default)" : ""}`).className = "numeric";
  const state = cell(tr, "");
  if (account.archived_at) state.append(statusBadge("removed"));
  else if (account.awaiting_review.length) state.append(statusBadge("value_to_confirm"));
  else if (account.current) state.append(statusBadge(account.current.source === "estimated" ? "estimated" : "verified"));
  else state.append(element("span", "No confirmed value", "muted"));
  return tr;
}

async function renderInvestmentDetail(accountId, renewing = false) {
  const account = await api(`/api/investments/${accountId}`), target = $("investment-detail");
  const panel = element("section", "", "panel investment-detail");
  const heading = element("div", "", "ledger-record-heading");
  heading.append(element("h2", account.name), homeLink("Close", "#/investments"));
  const facts = element("dl", "", "detail-list");
  for (const [label, value] of [["Kind", account.kind_label], ["Institution", account.institution || "—"], ["Section", account.section_label],
      ["Tax treatment", `${account.tax_label}${account.tax_overridden ? "" : " (from its kind)"}`],
      ["Yearly growth or interest", `${account.annual_rate_percent}% a year${account.rate_is_default ? " (its kind's default)" : ""}; the forecast grows the value at this rate`],
      ["Current value", account.current ? `${account.current.value.display} as of ${dateText(account.current.as_of)}${account.current.source === "estimated" ? ", estimated from its holdings' terms" : ""}` : "No confirmed value yet"],
      ...(account.ledger_account_id ? [["Values from", `${account.ledger_account_name} statements; they're reviewed with the statement and its balance counts here, not as cash`]] : [])]) {
    facts.append(element("dt", label), element("dd", value));
  }
  panel.append(heading, facts, investmentSettingsForm(account), investmentValueForm(account));
  if (account.holdings.length) {
    const waiting = account.holdings.some(holding => holding.review_status === "proposed");
    const estimated = account.holdings.some(holding => holding.estimated);
    const onStatement = account.holdings.some(holding => !holding.estimated);
    panel.append(element("h3", onStatement && !estimated ? `Holdings on ${dateText(account.holdings_as_of)}` : "Holdings"),
                 ...(waiting ? [element("p", "Some wait for review with their statement or purchase confirmation; they count once you confirm it.", "muted small")] : []),
                 ...(estimated ? [element("p", `Estimated values are worked out for today from each purchase's terms${onStatement ? `; the rest are from the statement of ${dateText(account.holdings_as_of)}` : ""}.`, "muted small")] : []),
                 investmentHoldings(account));
    const traded = account.holdings.filter(holding => !holding.estimated && (holding.quantity || holding.lots.length));
    if (account.tax_treatment === "taxable" && traded.length) panel.append(investmentLots(account, traded));
  }
  // A savings balance holds no CDs; any other account can (a bank's CDs, TreasuryDirect, a brokerage or IRA).
  if (!account.archived_at && account.value_model !== "cash") panel.append(investmentHoldingForm(account, renewing));
  panel.append(element("h3", "Values over time"), investmentHistory(account));
  if (account.events.length) panel.append(element("h3", "Activity"), investmentActivity(account));
  if (account.confirmations.length) panel.append(element("h3", "Purchase confirmations"), investmentConfirmations(account));
  if (!account.archived_at) {
    const remove = element("button", "Remove account", "quiet"); remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!await confirmAction({title: `Remove ${account.name}?`, message: "It is left out of totals and forecasts from now on. Its values and statements are kept.", confirmLabel: "Remove", danger: true})) return;
      try { await api(`/api/investments/${account.id}`, {method: "DELETE"}); notice(`${account.name} removed.`); location.hash = "#/investments"; } catch (error) { notice(error, true); }
    });
    panel.append(element("div", "", "button-row")); panel.lastChild.append(remove);
  }
  target.replaceChildren(panel);
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
  const save = element("button", "Save changes"); save.type = "submit";
  form.append(field("Name ", name), field("Kind ", kind), field("Institution ", institution), field("Yearly rate (%) ", rate), field("Tax treatment ", tax),
              field("Bank account ", linked), ...(account.takes_payroll ? [field("Contributions from pay at ", payroll)] : []),
              field(`You add each month (${account.currency}) `, monthly), save);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const body = {name: name.value.trim(), kind: kind.value, institution: institution.value.trim()};
    if (rate.value.trim()) body.annual_rate_percent = rate.value.trim();
    if (tax.value) body.tax_treatment = tax.value;
    if (linked.value) body.ledger_account_id = Number(linked.value);
    if (account.takes_payroll && payroll.value) body.payroll_employer_id = Number(payroll.value);
    if (monthly.value.trim()) body.monthly_contribution = monthly.value.trim();
    try { await api(`/api/investments/${account.id}`, {method: "PUT", body: JSON.stringify(body)}); notice("Saved."); await loadInvestments(); } catch (error) { notice(error, true); }
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
      notice("Value recorded."); await loadInvestments();
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
    cell(tr, "").append(statusBadge(row.source === "estimated" ? "estimated" : row.review_status));
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
  const states = has(holding => holding.estimated || holding.review_status === "proposed");
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table"), head = table.createTHead().insertRow();
  const columns = [["Holding"], ["Type"], ...(market ? [["Quantity", true], ["Price", true]] : []), ["Value", true], ...(market ? [["Cost basis", true], ["Gain", true]] : []),
                   ...(terms ? [["Rate", true], ["Matures"], ["At maturity", true]] : []), ...(states ? [["Status"]] : [])];
  for (const [title, numeric] of columns) { const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th); }
  const body = table.createTBody();
  for (const holding of account.holdings) {
    const tr = body.insertRow(), name = cell(tr, holding.name);
    if (holding.identifier) name.append(element("small", holding.identifier, "muted block mono"));
    cell(tr, holding.class_label);
    if (market) { cell(tr, holding.quantity || "—").className = "numeric"; moneyCell(tr, holding.price); }
    moneyCell(tr, holding.value);
    if (market) { moneyCell(tr, holding.cost_basis); moneyCell(tr, holding.gain, true); }
    if (terms) {
      cell(tr, holding.rate_percent != null ? `${holding.rate_percent}%` : "—").className = "numeric";
      const matures = cell(tr, holding.maturity_date ? dateText(holding.maturity_date) : "—");
      if (holding.rollover) matures.append(element("small", "Renews itself", "muted block"));
      if (holding.redeemable_date) matures.append(element("small", `Can be cashed from ${dateText(holding.redeemable_date)}`, "muted block"));
      moneyCell(tr, holding.at_maturity);
    }
    if (states) {
      const state = cell(tr, "");
      if (holding.matured) state.append(statusBadge("matured"), ...maturedButtons(holding.id, holding.name, account.id));
      else if (holding.review_status === "proposed") state.append(statusBadge("proposed"));
      else if (holding.estimated) state.append(statusBadge("estimated"));
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
    if (holding.lot_gain) section.append(element("p", `Unrealized gain by lot cost: ${holding.lot_gain.display}`, "small"));
    if (holding.lots.length) {
      const list = element("ul", "", "finance-list");
      for (const lot of holding.lots) {
        const li = element("li", `${dateText(lot.acquired_date)} · ${lot.shares} shares · cost ${lot.cost.display}${lot.source === "manual" ? " · entered by you" : ""}`);
        if (lot.id) li.append(asyncButton("Remove", async () => { await api(`/api/investments/lots/${lot.id}`, {method: "DELETE"}); notice("Lot removed."); await loadInvestments(); }, "small quiet"));
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
        notice("Lot added."); await loadInvestments();
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
      if (location.hash === next) await loadInvestments(); else location.hash = next;
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
      await loadInvestments();
    }, "small quiet"));
    moneyCell(tr, event.amount);
    cell(tr, "").append(statusBadge(event.review_status));
  }
  wrap.append(table); return wrap;
}

$("investments-archived").addEventListener("change", () => loadInvestments().catch(error => notice(error, true)));
$("investment-form").addEventListener("submit", async event => {
  event.preventDefault();
  const body = {name: $("investment-name").value.trim(), kind: $("investment-kind").value, institution: $("investment-institution").value.trim(),
                currency: $("investment-currency").value.trim().toUpperCase(), value: $("investment-value").value.trim(), as_of: $("investment-as-of").value};
  if ($("investment-rate").value.trim()) body.annual_rate_percent = $("investment-rate").value.trim();
  try {
    const account = await api("/api/investments", {method: "POST", body: JSON.stringify(body)});
    for (const id of ["investment-name", "investment-institution", "investment-value", "investment-rate"]) $(id).value = "";
    notice(`${account.name} added.`);
    location.hash = `#/investments?account=${account.id}`;
  } catch (error) { notice(error, true); }
});
