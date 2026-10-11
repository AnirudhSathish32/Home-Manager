"use strict";
// Accounts, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/money.md): each account's latest statement
// balance as a traced figure with its date and age, and what transactions cover it. Balances aren't added up here;
// Today shows Cash and Net worth. Import opens the shared picker (money_v2.js).
V2_SCREENS.accounts = {title: "Accounts", show: () => loadAccountsV2()};

function loadAccountsV2() {
  return pageState($("accounts2-state"), renderAccountsV2, {loading: "Loading accounts …", what: "accounts", needsLibrary: !familyMode, content: [$("accounts2-body")]});
}
function reloadAccounts() { return loadAccountsV2(); }
async function renderAccountsV2() {
  const {accounts} = await ledgerTool("get_accounts");
  const groups = [];
  for (const [title, types] of ACCOUNT_GROUPS) {
    const members = accounts.filter(account => types.includes(account.account_type));
    if (!members.length) continue;
    const section = element("section", "", "today-region"), heading = element("h2", title);
    heading.id = `accounts2-group-${groups.length + 1}`; section.setAttribute("aria-labelledby", heading.id);
    const list = element("ul", "", "accounts2-list");
    list.append(...members.map(accounts2Row));
    section.append(heading, list);
    groups.push(section);
  }
  if (!groups.length) {
    const action = familyMode ? null : accounts2ImportButton("Import an export");
    groups.push(emptyState("No accounts yet.", action));
  }
  $("accounts2-groups").replaceChildren(...groups);
}
function accounts2ImportButton(label) {
  const button = element("button", "", "secondary"); button.type = "button";
  button.append(icon("upload"), label);
  button.addEventListener("click", () => importPicker({onImported: reloadAccounts}));
  return button;
}
function accounts2Row(account) {
  const li = element("li", "", "accounts2-row");
  const name = element("div", "", "accounts2-name");
  name.append(element("strong", account.display_name), element("small",
    `${account.owner ? `${account.owner} · ` : ""}${account.institution}${account.account_last_four ? ` ··${account.account_last_four}` : ""} · ${account.currency}`, "muted"));
  const balance = element("div", "", "accounts2-balance");
  if (account.balance) {
    const line = element("div", "", "accounts2-figure");
    line.append(element("span", account.balance.meaning === "amount owed" ? "Amount owed" : "Statement balance", "figure-label"),
      figure(account.balance, {size: "inline", signed: false}));
    const age = element("small", `as of ${dateText(account.balance.as_of)}`, "muted");
    balance.append(line, age);
    if (account.balance.days_old > 35) balance.append(statusBadge("needs_review", "", "Over 35 days old"));
  } else balance.append(element("span", "No statement yet", "muted"));
  const coverage = element("small", account.coverage.transactions
    ? `${account.coverage.transactions} counted ${account.coverage.transactions === 1 ? "transaction" : "transactions"} · ${dateText(account.coverage.first)} – ${dateText(account.coverage.last)}`
    : "No counted transactions yet", "muted accounts2-coverage");
  const link = homeLink("", txHref({account: familyMode ? `${account.member_id}:${account.id}` : account.id, period: "all"}), "accounts2-link");
  link.append("Transactions", icon("chevron-right"));
  link.setAttribute("aria-label", `Transactions for ${account.display_name}`);
  li.append(name, balance, link, coverage);
  return li;
}

$("accounts2-import").prepend(icon("upload"));
$("accounts2-import").addEventListener("click", () => importPicker({onImported: reloadAccounts}));
