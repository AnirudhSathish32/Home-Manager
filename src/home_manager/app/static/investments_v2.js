"use strict";
// Investments, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/wealth.md): tiles, what needs you, every
// account in one table grouped by section, how the total splits, and the tax year's forms. One account opens in its own
// view (?account=ID) with Back and four tabs. investments.js keeps the builders both screens use; after a save they call
// investmentsReload, which this screen points at its own reload. Every amount, share and date is the server's.
const INV2_TABS = ["overview", "holdings", "activity", "settings"];
// account: the open account's id (0 on the list); tab: its tab; renew: a matured holding whose renewal is being added;
// removed and year: the list's controls; view: the open account's data; stale: tabs to draw on their next show;
// load: the newest render, so an older one finishing late draws nothing.
const inv2 = {load: 0, account: 0, tab: "overview", renew: 0, removed: false, year: 0, view: null, stale: new Set(INV2_TABS), currencies: [], valueForm: null};

V2_SCREENS.investments = {title: "Investments", show: route => loadInvestmentsV2(route.params)};

const activateInv2Tab = wireTabs(INV2_TABS.map(tab => `inv2-tab-${tab}`));
for (const tab of INV2_TABS) $(`inv2-tab-${tab}`).addEventListener("tabshow", () => {
  inv2.tab = tab; inv2Url();
  if (inv2.view && inv2.stale.has(tab)) inv2DrawTab(tab);
});

function inv2LastYear() { return new Date().getFullYear() - 1; }
function loadInvestmentsV2(params) {
  const account = Number(params?.get?.("account"));
  inv2.account = Number.isInteger(account) && account > 0 ? account : 0;
  inv2.tab = INV2_TABS.includes(params?.get?.("tab")) ? params.get("tab") : "overview";
  inv2.renew = Number(params?.get?.("renew")) || 0;
  if (inv2.renew) inv2.tab = "holdings";
  inv2.removed = params?.get?.("removed") === "1";
  const year = Number(params?.get?.("year"));
  inv2.year = Number.isInteger(year) && year > 1900 && year <= new Date().getFullYear() ? year : inv2LastYear();
  $("inv2-removed").checked = inv2.removed;
  investmentsReload = () => inv2Reload();
  return inv2Reload();
}
function inv2Reload() {
  return pageState($("inv2-state"), inv2.account ? renderInvestmentAccountV2 : renderInvestmentsV2,
                   {loading: inv2.account ? "Loading the account …" : "Loading investments …", what: inv2.account ? "this account" : "investments",
                    needsLibrary: !familyMode, content: [$("inv2-body")]});
}
// The controls' values into the URL (Layout rule 5): only what differs from the defaults.
function inv2Url() {
  const next = new URLSearchParams();
  if (inv2.account) {
    next.set("account", String(inv2.account));
    if (inv2.tab !== "overview") next.set("tab", inv2.tab);
    if (inv2.renew) next.set("renew", String(inv2.renew));
  } else {
    if (inv2.removed) next.set("removed", "1");
    if (inv2.year !== inv2LastYear()) next.set("year", String(inv2.year));
  }
  if (currentRoute?.name === "investments") currentRoute.params = next;
  history.replaceState(null, "", `#/investments${[...next].length ? `?${next}` : ""}`);
}
function inv2Count(n, one, many) { return `${n} ${n === 1 ? one : many}`; }
function inv2Href(accountId, tab = "") { return `#/investments?account=${accountId}${tab ? `&tab=${tab}` : ""}`; }
// The header: the list's title and actions, or the open account's.
function inv2Header(account = null) {
  $("inv2-back").hidden = !account;
  $("inv2-title").textContent = account ? account.name : "Investments";
  $("inv2-subtitle").textContent = account
    ? [account.kind_label, account.institution, account.tax_label].filter(Boolean).join(" · ")
    : "Retirement, savings, CDs and Treasuries, I bonds, brokerage, crypto and 529s.";
  $("inv2-removed-field").hidden = Boolean(account);
  $("inv2-add").hidden = Boolean(account);
  // A pension has no value to record: its primary is Save terms, inside its form.
  $("inv2-record").hidden = !account || account.is_income || Boolean(account.archived_at);
  $("inv2-list").hidden = Boolean(account);
  $("inv2-account").hidden = !account;
}

// The list ---------------------------------------------------------------------------------------------------------
async function renderInvestmentsV2() {
  const load = ++inv2.load;
  // The RMD and tax sections fail on their own, each with its own message (as v1).
  const failed = error => ({error});
  const [kinds, summary, rmd, taxes] = await Promise.all([
    investmentKinds.length ? investmentKinds : api("/api/investment-kinds"),
    api(`/api/investments${inv2.removed ? "?include_archived=true" : ""}`),
    api("/api/investments/rmd").catch(failed), api(`/api/investments/tax-years/${inv2.year}`).catch(failed)]);
  if (load !== inv2.load) return;  // A newer load (another account, or the list again) took over.
  inv2.view = null;
  investmentKinds = kinds;
  inv2.currencies = [...new Set([homeCurrency, "USD", ...summary.accounts.map(account => account.currency)].filter(Boolean))];
  inv2Header();
  inv2Url();
  const empty = !summary.accounts.length;
  $("inv2-tiles").hidden = empty;
  $("inv2-split").hidden = !summary.totals.length;
  if (!empty) investmentTilesV2(summary, rmd);
  investmentNeedsV2(summary, rmd, taxes);
  investmentAccountsV2(summary);
  inv2Split(summary);
  investmentTaxesV2(taxes);
}

function inv2Tile(label, main, sub = [], className = "") {
  const tile = element("div", "", `figure-tile ${className}`.trim());
  tile.append(element("p", label, "figure-label"), main);
  for (const line of sub) { const p = element("p", "", "figure-sub"); p.append(...[].concat(line)); tile.append(p); }
  return tile;
}
function inv2TileText(text) { return element("p", text, "inv2-tile-text"); }
function investmentTilesV2(summary, rmd) {
  const tiles = summary.totals.map(total => {
    const sub = [`oldest value ${dateText(total.oldest_as_of)}`];
    if (total.estimated_accounts > 0) {
      const line = element("span", "", "inv2-estimated");
      line.append(icon("clock"), `${total.estimated_accounts} estimated`);
      sub.push(line);
    }
    return inv2Tile(`Invested, ${total.currency}`, figure(total.total, {signed: false}), sub);
  });
  if (!tiles.length) tiles.push(inv2Tile("Invested", inv2TileText("No confirmed values yet")));
  const due = summary.maturities;
  tiles.push(inv2Tile("Coming due · 90 days", inv2TileText(due.length ? inv2Count(due.length, "CD or Treasury", "CDs and Treasuries") : "Nothing in 90 days"),
                      due.length ? [`next ${dateText(due[0].date)}`] : []));
  tiles.push(inv2RmdTile(rmd));
  $("inv2-tiles").replaceChildren(...tiles);
  fitFigures($("inv2-tiles"));
}
function inv2RmdTile(rmd) {
  const label = "Required distributions";
  if (rmd.error) return inv2Tile(label, alertBox(rmd.error.message, {tone: "error"}));
  if (!rmd.has_accounts) return inv2Tile(label, inv2TileText("None"), ["No tax-deferred accounts"]);
  if (rmd.birth_year == null) {
    const text = element("p", "", "inv2-tile-text"); text.append(homeLink("Set your birth year in Settings", "#/settings"));
    return inv2Tile(label, text);
  }
  if (rmd.begins_later) return inv2Tile(label, inv2TileText(`Begin in ${rmd.first_year}`), [`at age ${rmd.start_age}`]);
  const left = rmd.accounts.filter(row => row.left?.minor > 0);
  return inv2Tile(`${label}, ${rmd.year}`, inv2TileText(left.length ? `Left: ${inv2Count(left.length, "account", "accounts")}` : "All taken"),
                  left.length ? ["Listed under Needs you"] : []);
}

// Needs you: one row per thing to act on, each with one action.
function inv2NeedsRow(what, why, action) {
  const li = element("li", "", "needs-row attention inv2-needs-row");
  const text = element("div"), strong = element("strong");
  strong.append(...[].concat(what)); text.append(strong);
  if (why) text.append(element("small", why, "muted"));
  const actions = element("div", "", "inv2-needs-actions");
  actions.append(...[].concat(action || []));
  li.append(icon("alert", "icon needs-icon"), text, actions);
  return li;
}
function investmentNeedsV2(summary, rmd, taxes) {
  const rows = [];
  const n = summary.awaiting_review;
  if (n) rows.push(inv2NeedsRow(`${inv2Count(n, "value or purchase waits", "values or purchases wait")} in To check`, "They count once you confirm them.",
                                homeLink("Open To check", "#/review", "needs-action")));
  for (const warning of summary.ibond_warnings) {
    rows.push(inv2NeedsRow(`I bonds over the ${warning.limit.display} yearly limit (${warning.year})`, warning.message,
                           warning.account_id ? homeLink("Open account", inv2Href(warning.account_id), "needs-action") : null));
  }
  for (const due of summary.maturities.filter(row => row.state === "matured")) {
    rows.push(inv2NeedsRow(`${due.name} matured ${dateText(due.date)}`, `${due.account} · What happened to it?`, maturedButtons(due.holding_id, due.name, due.account_id)));
  }
  if (!rmd.error && !rmd.begins_later) {
    for (const row of (rmd.accounts || []).filter(item => item.left?.minor > 0)) {
      rows.push(inv2NeedsRow([`${row.name}: `, figure(row.left, {size: "inline", signed: false}), ` left to take by ${dateText(row.deadline)}`],
                             "A required minimum distribution for this year.", homeLink("Open account", inv2Href(row.account_id), "needs-action")));
    }
  }
  if (!taxes.error) {
    for (const plan of taxes.education.filter(item => item.unmarked)) {
      rows.push(inv2NeedsRow(`${plan.account}: a ${taxes.year} withdrawal isn't marked`, `${plan.unmarked.display} withdrawn isn't marked qualified or not yet.`,
                             homeLink("Open account", inv2Href(plan.account_id, "activity"), "needs-action")));
    }
    for (const gains of taxes.gains) {
      for (const gap of gains.missing) {
        rows.push(inv2NeedsRow(`${gap.account}: ${gap.shares} shares sold on ${dateText(gap.date)} have no purchase lot`, "Their gain isn't counted until the lot is added.",
                               homeLink("Open account", inv2Href(gap.account_id, "holdings"), "needs-action")));
      }
    }
  }
  for (const question of summary.payroll_questions) {
    // payrollQuestion (investments.js) builds the account choice and saves it; its form is the row's action.
    const form = payrollQuestion(question).querySelector("form");
    rows.push(form
      ? inv2NeedsRow(`Which account do ${question.employer}'s ${question.label} contributions go to?`, "Pay stubs list them, and more than one account could hold them.", form)
      : inv2NeedsRow(`Pay stubs from ${question.employer} list ${question.label} contributions`, "Add that account to follow them.", inv2AddButton("Add an account", "link-button")));
  }
  $("inv2-needs").hidden = !rows.length;
  $("inv2-needs-list").replaceChildren(...rows);
}

function inv2AddButton(label, className = "primary") {
  const button = element("button", "", className); button.type = "button";
  if (className === "primary") button.append(icon("plus"));
  button.append(label);
  button.addEventListener("click", () => openInv2AddDialog());
  return button;
}
function investmentAccountsV2(summary) {
  const host = $("inv2-accounts-body");
  if (!summary.accounts.length) {
    const box = emptyState("No investment accounts yet", inv2AddButton("Add an account"));
    box.append(element("p", "or add a statement to Receipts & statements.", "muted small"));
    host.replaceChildren(box);
    return;
  }
  const table = element("table", "", "data-table inv2-accounts-table"), head = table.createTHead().insertRow();
  for (const [title, className] of [["Account", ""], ["Kind", "inv2-col-kind"], ["Value", "numeric"], ["As of", "inv2-col-as-of"], ["Change", "numeric inv2-col-change"], ["Status", ""]]) {
    const th = element("th", title, className); th.scope = "col"; head.append(th);
  }
  for (const [section, label] of Object.entries(summary.sections)) {
    const members = summary.accounts.filter(account => account.section === section);
    if (!members.length) continue;
    const body = table.createTBody(), group = body.insertRow();
    group.className = "group-row";
    const th = element("th", label); th.scope = "colgroup"; th.colSpan = 6; group.append(th);
    for (const account of members) body.append(inv2AccountRow(account));
  }
  const wrap = element("div", "", "table-wrap"); wrap.append(table);
  host.replaceChildren(wrap);
}
function inv2AccountRow(account) {
  const tr = document.createElement("tr");
  tr.className = account.archived_at ? "inv2-row inv2-removed" : "inv2-row";
  const name = cell(tr, ""), link = element("a", account.name);
  link.href = inv2Href(account.id);
  name.append(link);
  if (account.institution) name.append(element("small", account.institution, "muted block"));
  // Under 700px the Kind and As of columns fold into this line.
  const asOf = account.is_income ? (account.pension ? `from ${monthText(account.pension.start_date)}` : "") : account.current ? dateText(account.current.as_of) : "";
  name.append(element("small", [account.kind_label, asOf].filter(Boolean).join(" · "), "muted block inv2-inline"));
  if (account.is_income) name.append(element("small", "not counted in totals", "muted block"));
  cell(tr, account.kind_label).className = "inv2-col-kind";
  const value = cell(tr, ""); value.className = "numeric";
  const when = cell(tr, ""); when.className = "inv2-col-as-of";
  const change = cell(tr, ""); change.className = "numeric inv2-col-change";
  const state = cell(tr, "");
  if (account.is_income) {
    // A pension pays a monthly benefit from its start date; it has no balance to show or add up.
    if (account.pension) value.append(amount(account.pension.monthly_benefit, {signed: false}), element("small", `a month from ${monthText(account.pension.start_date)}`, "muted block"));
    else value.append(element("span", "Add its terms", "muted"));
    when.append(element("span", "—", "muted")); change.append(element("span", "—", "muted"));
    if (account.archived_at) state.append(statusBadge("removed"));
  } else {
    value.append(account.current ? figure(account.current.value, {size: "sm", signed: false}) : element("span", "—", "muted"));
    when.textContent = account.current ? dateText(account.current.as_of) : "—";
    if (account.change) { change.append(amount(account.change)); change.title = `Since ${dateText(account.change_since)}`; } else change.append(element("span", "—", "muted"));
    if (account.archived_at) state.append(statusBadge("removed"));
    else if (account.awaiting_review.length) state.append(statusBadge("value_to_confirm"));
    else if (account.current?.source === "quote") state.append(statusBadge("quote"));
    else if (account.current?.source === "estimated") state.append(statusBadge("estimated"));
    else if (!account.current) state.append(element("span", "No confirmed value", "muted"));
  }
  // The whole row opens the account; the link stays the focus target.
  tr.addEventListener("click", event => { if (!event.target.closest("a, button, input, select")) location.hash = link.getAttribute("href"); });
  return tr;
}
function inv2Split(summary) {
  const parts = [];
  for (const total of summary.totals) {
    if (summary.totals.length > 1) parts.push(element("h3", total.currency, "inv2-currency"));
    const split = element("div", "", "inv2-split");
    split.append(shareTable("Section", total.sections), shareTable("Tax treatment", total.tax));
    parts.push(split);
  }
  $("inv2-split-title").textContent = summary.totals.length === 1 ? `How it splits, ${summary.totals[0].currency}` : "How it splits";
  $("inv2-split-body").replaceChildren(...parts);
}

// Taxes for a year: each 1099 or 5498 box beside what is recorded, and realized gains (v1's renderInvestmentTaxes).
function investmentTaxesV2(data) {
  const host = $("inv2-taxes"), heading = element("div", "", "inv2-region-head");
  const title = element("h2", `Taxes for ${inv2.year}`); title.id = "inv2-taxes-title";
  const select = document.createElement("select"); select.id = "inv2-year"; select.setAttribute("aria-label", "Tax year");
  const years = data.error ? [inv2.year] : data.years.includes(inv2.year) ? data.years : [inv2.year, ...data.years];
  for (const year of years) select.add(new Option(String(year), String(year)));
  select.value = String(inv2.year);
  select.addEventListener("change", () => { inv2.year = Number(select.value); inv2Url(); inv2Reload().then(() => $("inv2-year")?.focus()); });
  heading.append(title, select);
  if (data.error) { host.replaceChildren(heading, alertBox(data.error.message, {tone: "error"})); return; }
  const parts = [heading];
  for (const gains of data.gains) {
    const figures = element("dl", "", "inv2-gains");
    for (const [label, value, signed] of [["Sold for", gains.proceeds, false], ["Cost of what was sold", gains.cost, false], ["Short-term gain", gains.short, true], ["Long-term gain", gains.long, true]]) {
      const item = element("div"), dd = element("dd");
      dd.append(amount(value, {signed}));
      item.append(element("dt", label), dd); figures.append(item);
    }
    parts.push(element("h3", `Realized gains in taxable accounts${data.gains.length > 1 ? `, ${gains.currency}` : ""}`), figures,
               element("p", "Sales are matched to purchase lots first in, first out; a lot held more than a year gives a long-term gain.", "muted small"));
    for (const gap of gains.missing) {
      const line = element("p", "", "item-warning inv2-warning");
      line.append(icon("alert"), `${gap.account}: ${gap.shares} shares sold on ${dateText(gap.date)} have no purchase recorded, so their gain isn't counted.`);
      parts.push(line);
    }
  }
  for (const plan of data.education) {
    if (plan.nonqualified.minor) {
      parts.push(element("p", plan.taxable_earnings
        ? `${plan.account}: ${plan.nonqualified.display} withdrawn for other costs. ${plan.taxable_earnings.display} of it is earnings (${plan.earnings_share_percent}%, from the 1099-Q), taxed as income; a 10% additional tax usually applies too.`
        : `${plan.account}: ${plan.nonqualified.display} withdrawn for other costs. Its taxable earnings come from the 1099-Q; add it to Receipts & statements.`, "small"));
    }
  }
  if (!data.checks.length) {
    parts.push(element("p", `No 1099 or 5498 forms for ${data.year}. Add them to Receipts & statements; each box is then compared with what is recorded here.`, "muted small"));
  } else {
    const table = element("table", "", "data-table"), head = table.createTHead().insertRow();
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
    const wrap = element("div", "", "table-wrap"); wrap.append(table);
    parts.push(wrap, element("p", "Recorded amounts are confirmed activity for the account in that year. A difference can mean a statement or pay stub isn't here yet.", "muted small"));
  }
  host.replaceChildren(...parts);
}

// One account ------------------------------------------------------------------------------------------------------
async function renderInvestmentAccountV2() {
  const load = ++inv2.load;
  let account;
  try {
    [account] = await Promise.all([api(`/api/investments/${inv2.account}`),
      investmentKinds.length ? null : api("/api/investment-kinds").then(kinds => { investmentKinds = kinds; })]);
  } catch (error) {
    if (load !== inv2.load) return;
    if (!/not found/i.test(error.message || "")) throw error;
    inv2.view = null;
    inv2Header({name: "Investments", kind_label: "", institution: "", tax_label: "", is_income: true});
    $("inv2-tabs").hidden = true;
    for (const tab of INV2_TABS) $(`inv2-${tab}-panel`).hidden = true;
    $("inv2-account-head").replaceChildren(alertBox("That account isn't here. It may have been removed, or the link is from another profile.",
                                                    {tone: "warning", action: homeLink("Back to Investments", "#/investments")}));
    return;
  }
  if (load !== inv2.load) return;
  inv2.view = account;
  inv2Header(account);
  $("inv2-tabs").hidden = false;
  inv2AccountHead(account);
  // Activity shows only with something in it; a pension holds nothing.
  $("inv2-tab-activity").hidden = !account.events.length && !account.confirmations.length;
  $("inv2-tab-holdings").hidden = account.is_income;
  if ($(`inv2-tab-${inv2.tab}`).hidden) inv2.tab = "overview";
  inv2.stale = new Set(INV2_TABS);
  inv2Url();
  activateInv2Tab(`inv2-tab-${inv2.tab}`);  // Draws the tab (tabshow).
}
function inv2AccountHead(account) {
  const head = $("inv2-account-head"), line = element("div", "", "inv2-account-line");
  if (account.is_income) {
    const pension = account.pension;
    line.append(pension ? element("p", `${pension.monthly_benefit.display} a month from ${dateText(pension.start_date)}, before tax`, "inv2-account-text")
                        : element("p", "Add its terms in Overview", "inv2-account-text muted"),
                element("span", "Pays an income; not counted in totals", "muted small"));
  } else if (account.current) {
    const when = element("span", `as of ${dateText(account.current.as_of)}`, "muted");
    if (account.change) when.append(" · ", amount(account.change), ` since ${dateText(account.change_since)}`);
    line.append(figure(account.current.value, {signed: false}), when);
    if (account.current.source === "estimated") line.append(statusBadge("estimated", "", "Estimated from its holdings' terms"));
    else if (account.current.source === "quote") line.append(statusBadge("quote"));
  } else line.append(element("p", "No confirmed value yet", "inv2-account-text muted"));
  if (account.archived_at) line.append(statusBadge("removed"));
  else if (account.awaiting_review.length) line.append(statusBadge("value_to_confirm"));
  head.replaceChildren(line);
}
function inv2DrawTab(tab) {
  inv2.stale.delete(tab);
  const account = inv2.view, host = $(`inv2-${tab}-panel`);
  ({overview: inv2Overview, holdings: inv2Holdings, activity: inv2Activity, settings: inv2Settings})[tab](account, host);
}
function inv2Overview(account, host) {
  const facts = element("dl", "", "inv2-facts"), pension = account.pension;
  const valueFacts = account.is_income
    ? [...(pension ? [["Yearly raise", pension.cola_bp ? `${pension.cola_percent}% each January` : "None"],
                     ["Survivor benefit", pension.survivor_percent ? `${pension.survivor_percent}% to a surviving spouse` : "None"],
                     ...(pension.lump_sum ? [["Lump sum offered", `${pension.lump_sum.display} instead; shown for comparison, not counted in totals`]] : [])] : []),
       ["In the forecast", "Income from its start month; it is never drawn on and has no required distributions"]]
    : [["Yearly growth or interest", `${account.annual_rate_percent}% a year${account.rate_is_default ? " (its kind's default)" : ""}; the forecast grows the value at this rate`]];
  for (const [label, value] of [["Kind", account.kind_label], ["Institution", account.institution || "—"], ["Section", account.section_label],
      ["Tax treatment", `${account.tax_label}${account.tax_overridden ? "" : " (from its kind)"}`],
      ...(account.is_education ? [["Beneficiary", account.beneficiary || "—"], ["Plan state", account.plan_state || "—"],
                                  ["In the forecast", "Kept for education: retirement withdrawals never draw on it"]] : []),
      ...valueFacts,
      ...(account.ledger_account_id ? [["Values from", `${account.ledger_account_name} statements; they're reviewed with the statement and its balance counts here, not as cash`]] : [])]) {
    const item = element("div"); item.append(element("dt", label), element("dd", value)); facts.append(item);
  }
  const parts = [...account.ibond_warnings.map(warning => alertBox(warning.message, {tone: "warning"})), facts];
  inv2.valueForm = null;
  if (!account.archived_at) {
    if (account.is_income) parts.push(element("h2", "Pension terms", "inv2-panel-title"), pensionForm(account));
    else {
      inv2.valueForm = investmentValueForm(account);
      parts.push(element("h2", "Record a value", "inv2-panel-title"), inv2.valueForm);
    }
  }
  if (account.has_crypto || account.kind === "crypto") parts.push(cryptoTools(account));
  if (account.is_education && !account.archived_at) parts.push(educationWithdrawalForm(account));
  if (!account.is_income || account.history.length) parts.push(element("h2", "Values over time", "inv2-panel-title"), investmentHistory(account));
  host.replaceChildren(...parts);
}
function inv2Holdings(account, host) {
  const parts = [];
  if (account.holdings.length) {
    const waiting = account.holdings.some(holding => holding.review_status === "proposed");
    const estimated = account.holdings.some(holding => holding.estimated);
    const onStatement = account.holdings.some(holding => !holding.estimated);
    parts.push(element("h2", onStatement && !estimated ? `Holdings on ${dateText(account.holdings_as_of)}` : "Holdings", "inv2-panel-title"),
               ...(waiting ? [element("p", "Some wait for review with their statement or purchase confirmation; they count once you confirm it.", "muted small")] : []),
               ...(estimated ? [element("p", `Estimated values are worked out for today from each purchase's terms${onStatement ? `; the rest are from the statement of ${dateText(account.holdings_as_of)}` : ""}.`, "muted small")] : []),
               investmentHoldings(account));
    const traded = account.holdings.filter(holding => !holding.estimated && (holding.quantity || holding.lots.length));
    if (account.tax_treatment === "taxable" && traded.length) parts.push(investmentLots(account, traded));
  } else parts.push(element("p", "No holdings recorded. A statement lists them, or add a CD or Treasury below.", "muted small"));
  // A savings balance holds no CDs; any other account can (a bank's CDs, TreasuryDirect, a brokerage or IRA).
  if (!account.archived_at && !["cash", "income"].includes(account.value_model) && account.kind !== "crypto" && !account.is_education) {
    parts.push(investmentHoldingForm(account, Boolean(inv2.renew)));
  }
  if (account.has_ibonds) parts.push(ibondRates());
  host.replaceChildren(...parts);
}
function inv2Activity(account, host) {
  const parts = [];
  if (account.events.length) parts.push(element("h2", "Activity", "inv2-panel-title"), investmentActivity(account));
  if (account.confirmations.length) parts.push(element("h2", "Purchase confirmations", "inv2-panel-title"), investmentConfirmations(account));
  host.replaceChildren(...parts);
}
function inv2Settings(account, host) {
  const parts = [investmentSettingsForm(account)];
  if (!account.archived_at) {
    const remove = element("button", "Remove account…", "danger"); remove.type = "button"; remove.id = "inv2-remove";
    remove.addEventListener("click", async () => {
      if (!await confirmAction({title: `Remove ${account.name}?`, message: "It is left out of totals and forecasts from now on. Its values and statements are kept.", confirmLabel: "Remove", danger: true})) return;
      try { await api(`/api/investments/${account.id}`, {method: "DELETE"}); notice(`${account.name} removed.`); location.hash = "#/investments"; } catch (error) { notice(error, true); }
    });
    const row = element("div", "", "button-row inv2-remove-row"); row.append(remove);
    parts.push(row);
  }
  host.replaceChildren(...parts);
}

// Add an account ---------------------------------------------------------------------------------------------------
async function openInv2AddDialog() {
  money2.opener = document.activeElement;
  const form = $("inv2-add-form");
  form.reset(); clearFieldErrors(form);
  if (!investmentKinds.length) investmentKinds = await api("/api/investment-kinds");
  fillKindSelect($("inv2-add-kind"), investmentKinds, "brokerage");
  const currencies = inv2.currencies.length ? inv2.currencies : [homeCurrency || "USD"];
  $("inv2-add-currency").replaceChildren(...currencies.map(code => new Option(code, code)));
  $("inv2-add-currency").value = homeCurrency && currencies.includes(homeCurrency) ? homeCurrency : currencies[0];
  $("inv2-add-as-of").value = todayIso(); $("inv2-add-as-of").max = todayIso();
  $("inv2-add-dialog").showModal();
  $("inv2-add-name").focus();
}
$("inv2-add-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = $("inv2-add-form");
  clearFieldErrors(form);
  const body = {name: $("inv2-add-name").value.trim(), kind: $("inv2-add-kind").value, institution: $("inv2-add-institution").value.trim(),
                currency: $("inv2-add-currency").value};
  // A pension has no balance: it's added without a value and its monthly benefit is entered next.
  if ($("inv2-add-value").value.trim()) Object.assign(body, {value: $("inv2-add-value").value.trim(), as_of: $("inv2-add-as-of").value});
  if ($("inv2-add-rate").value.trim()) body.annual_rate_percent = $("inv2-add-rate").value.trim();
  $("inv2-add-save").disabled = true;
  try {
    const account = await api("/api/investments", {method: "POST", body: JSON.stringify(body)});
    $("inv2-add-dialog").close();
    notice(`${account.name} added.`);
    location.hash = inv2Href(account.id);
  } catch (error) {
    fieldError(form, errorField(error), error.message || String(error));
  } finally { $("inv2-add-save").disabled = false; }
});
$("inv2-add-cancel").addEventListener("click", () => money2Close($("inv2-add-dialog")));
$("inv2-add-dialog").addEventListener("close", () => { if (document.activeElement === document.body) money2.opener?.focus?.(); });

$("inv2-back").prepend(icon("chevron-left"));
$("inv2-add").prepend(icon("plus"));
$("inv2-add").addEventListener("click", () => openInv2AddDialog().catch(error => notice(error, true)));
$("inv2-removed").addEventListener("change", () => { inv2.removed = $("inv2-removed").checked; inv2Url(); inv2Reload(); });
$("inv2-record").addEventListener("click", () => {
  activateInv2Tab("inv2-tab-overview");
  inv2.valueForm?.querySelector("input")?.focus();
});
