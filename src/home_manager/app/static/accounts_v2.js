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
  if (!familyMode) {
    const rename = element("button", "Rename", "link-button accounts2-rename"); rename.type = "button";
    rename.dataset.account = String(account.id);
    rename.setAttribute("aria-label", `Rename ${account.display_name}`);
    rename.addEventListener("click", () => accounts2RenameForm(account, name));
    name.append(rename);
  }
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

// Rename: the name, in place of the row's name. Statements find an account by institution, type and last four, so the
// institution is offered only when another such account has it in another case (institution_clash), to settle which one
// a statement belongs to (docs/money.md "New statements wait for you").
function accounts2RenameForm(account, name) {
  const form = element("form", "", "accounts2-rename-form");
  form.setAttribute("aria-label", `Rename ${account.display_name}`);
  const field = (label, value, maxLength) => {
    const wrap = element("label", "", "accounts2-rename-field"), input = document.createElement("input");
    input.value = value; input.maxLength = maxLength; input.required = true;
    wrap.append(element("span", label), input);
    return [wrap, input];
  };
  const [institutionField, institution] = field("Institution", account.institution, 120);
  const [nameField, displayName] = field("Name", account.display_name, 160);
  const first = account.institution_clash ? institution : displayName;
  const error = element("p", "", "field-error"); error.id = `accounts2-rename-error-${account.id}`; error.hidden = true; error.setAttribute("role", "alert");
  first.setAttribute("aria-describedby", error.id);
  const note = element("small", "Another account has this institution in a different case, so statements can't tell them apart. Change one of them.", "muted");
  const save = element("button", "Save", "small primary"); save.type = "submit";
  const cancel = element("button", "Cancel", "small quiet"); cancel.type = "button";
  const actions = element("div", "", "accounts2-rename-actions"); actions.append(save, cancel);
  const close = () => { form.replaceWith(name); name.querySelector(".accounts2-rename")?.focus(); };
  cancel.addEventListener("click", close);
  form.addEventListener("keydown", event => { if (event.key === "Escape") { event.preventDefault(); close(); } });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    error.hidden = true; save.disabled = true;
    try {
      await api(`/api/finance/accounts/${account.id}`, {method: "PUT", body: JSON.stringify({institution: institution.value.trim(), display_name: displayName.value.trim()})});
      notice("Account renamed.");
      await reloadAccounts();
      $("accounts2-groups").querySelector(`.accounts2-rename[data-account="${account.id}"]`)?.focus();  // The list was redrawn.
    } catch (failure) {
      error.textContent = failure.message || String(failure); error.hidden = false; first.focus();
    } finally { save.disabled = false; }
  });
  form.append(...(account.institution_clash ? [institutionField, note] : []), nameField, error, actions);
  name.replaceWith(form);
  first.focus();
}

$("accounts2-import").prepend(icon("upload"));
$("accounts2-import").addEventListener("click", () => importPicker({onImported: reloadAccounts}));
