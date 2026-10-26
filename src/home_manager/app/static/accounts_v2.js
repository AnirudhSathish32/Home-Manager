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
  // Accounts a statement made that wait for its Confirm are in none of the groups above (docs/money.md "New statements wait for you").
  const waiting = familyMode ? [] : await api("/api/finance/accounts/waiting");
  if (!groups.length) {
    const action = familyMode ? null : accounts2ImportButton("Import an export");
    groups.push(emptyState("No accounts yet.", action));
  }
  if (waiting.length) groups.push(accounts2Waiting(waiting, $("accounts2-waiting")?.open));
  $("accounts2-groups").replaceChildren(...groups);
}
// "Waiting for confirm" (OD-5): collapsed at the bottom, so an account can be deleted without confirming it. Each entry opens the
// statement that made it, where Confirm is.
function accounts2Waiting(waiting, open = false) {
  const group = element("details", "", "accounts2-waiting"); group.id = "accounts2-waiting"; group.open = Boolean(open);
  group.append(element("summary", `Waiting for confirm (${waiting.length})`));
  group.append(element("p", "A statement made these accounts. They are added to Accounts when you confirm the statement, or you can delete them.", "muted small"));
  const list = element("ul", "", "accounts2-list");
  for (const account of waiting) {
    const li = element("li", "", "accounts2-row accounts2-waiting-row");
    const name = element("div", "", "accounts2-name");
    name.append(element("strong", account.display_name), element("small",
      `${account.institution}${account.account_last_four ? ` ··${account.account_last_four}` : ""} · ${account.currency}`, "muted"));
    const actions = element("div", "", "accounts2-row-actions");
    if (account.statement_document_id) {
      const open = homeLink("Open statement", `#/documents/${account.statement_document_id}`, "accounts2-link");
      open.setAttribute("aria-label", `Open the statement for ${account.display_name}`);
      actions.append(open);
    }
    actions.append(accounts2DeleteButton(account));
    li.append(name, actions);
    list.append(li);
  }
  group.append(list);
  return group;
}
function accounts2DeleteButton(account) {
  const button = element("button", "Delete…", "link-button danger-text accounts2-delete"); button.type = "button";
  button.dataset.account = String(account.id);
  button.setAttribute("aria-label", `Delete ${account.display_name}…`);
  button.addEventListener("click", () => openAccountDelete(account.id, {opener: button}));
  return button;
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
    const actions = element("div", "", "accounts2-row-actions");
    actions.append(rename, accounts2DeleteButton(account));
    name.append(actions);
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

// Delete account (FR-09 – FR-15; docs/money.md "Deleting an account"). The dialog shows what the server says will go (counts, and the
// family's copy), and Delete account sends the preview's token back, so an account that changed since the preview is refused
// (409) and the dialog shows the counts again. Opened from an account's row, from "Waiting for confirm" and from a waiting
// statement's page (document_v2.js, review_v2.js). Focus starts on Cancel and returns to the opener on close.
const ACCOUNT_DELETE_COUNTS = [  // [key, one, many, always shown]; the other lines show only when the account has some.
  ["statements", "statement", "statements", true], ["transactions", "transaction", "transactions", true], ["imports", "import record", "import records", true],
  ["receipts", "receipt linked to its transactions", "receipts linked to its transactions", false],
  ["pay_stubs", "pay stub linked to its transactions", "pay stubs linked to its transactions", false],
  ["transfer_links", "transfer link", "transfer links", false], ["refund_links", "refund link", "refund links", false],
  ["recurring_payments", "recurring payment tied to it", "recurring payments tied to it", false],
  ["recurring_bills", "recurring bill tied to it", "recurring bills tied to it", false],
  ["category_rules", "category rule for it", "category rules for it", false]];
function accountDeleteLines(counts) {
  return ACCOUNT_DELETE_COUNTS.filter(([key, , , always]) => always || counts[key]).map(([key, one, many]) => {
    const li = element("li", "", "account-delete-count"); li.dataset.count = key;
    li.append(element("strong", String(counts[key] || 0)), ` ${counts[key] === 1 ? one : many}`);
    return li;
  });
}
// What the delete leaves, said only when the account has some of it (FR-12, OD-4).
function accountDeleteStays(counts) {
  const kept = [];
  if (counts.receipts || counts.pay_stubs) kept.push("Linked receipts and pay stubs stay and count on their own again.");
  if (counts.recurring_payments || counts.recurring_bills) kept.push("Recurring payments and bills stay, with no account.");
  return kept.join(" ");
}
function accountDeleteFamily(family) {
  const copy = family.copy && (family.copy.statements || family.copy.transactions)
    ? `Your family's copy has ${family.copy.statements} ${family.copy.statements === 1 ? "statement" : "statements"} and ${family.copy.transactions} ${family.copy.transactions === 1 ? "transaction" : "transactions"} of this account; it drops them at your next share.` : "";
  const rows = family.rows ? `${family.rows} ${family.rows === 1 ? "family record" : "family records"} in this library about them ${family.rows === 1 ? "is" : "are"} deleted too.` : "";
  return [copy, rows].filter(Boolean).join(" ");
}
// What every screen shows after a delete: the page on screen is drawn again (Accounts, Today, Review), and the document page
// shows its statement as not recorded, so its next step is Record it (FR-13).
async function afterAccountDelete() {
  if (currentRoute?.name === "document" && doc2) {
    const state = doc2;
    state.renderedKey = "";
    await Promise.all([doc2Extraction(state, state.runId), refreshDocumentV2(state)]);
  } else if (currentRoute) await (V2_SCREENS[currentRoute.name] || ROUTES[currentRoute.name]).show(currentRoute);
  renderNavCounts().catch(() => {});
}
let accountDeleteOpens = 0;  // Counts openings, so a preview that arrives after the dialog was closed and opened again is dropped.
async function openAccountDelete(accountId, {opener = document.activeElement, onDeleted = afterAccountDelete} = {}) {
  const dialog = $("account-delete-dialog"), cancel = $("account-delete-cancel"), accept = $("account-delete-accept");
  const mine = ++accountDeleteOpens;
  let preview = null, deleted = false;
  const error = $("account-delete-error"), body = $("account-delete-body");
  const show = message => { error.textContent = message || ""; error.hidden = !message; };
  const load = async () => {
    accept.disabled = true;
    let found;
    try {
      found = await api(`/api/finance/accounts/${accountId}/delete-preview`);
    } catch (failure) {
      if (mine !== accountDeleteOpens) return false;
      preview = null; body.hidden = true; show(failure.message || String(failure)); return false;
    }
    if (mine !== accountDeleteOpens) return false;
    preview = found;
    $("account-delete-name").textContent = preview.account.display_name;
    $("account-delete-counts").replaceChildren(...accountDeleteLines(preview.counts));
    const stays = accountDeleteStays(preview.counts);
    $("account-delete-stay").textContent = stays; $("account-delete-stay").hidden = !stays;
    const family = accountDeleteFamily(preview.family);
    $("account-delete-family").textContent = family; $("account-delete-family").hidden = !family;
    body.hidden = false; accept.disabled = false;
    return true;
  };
  $("account-delete-name").textContent = ""; $("account-delete-counts").replaceChildren(); $("account-delete-family").hidden = true; $("account-delete-stay").hidden = true;
  body.hidden = true; show(""); accept.disabled = true;
  $("account-delete-title").textContent = "Delete account";
  // The opener can have been redrawn while the dialog was open (a reload of the list or the queue); focus then goes to the page's heading.
  const heading = () => ["accounts2-title", "doc2-title", "review2-title"].map($).find(node => node?.offsetParent);
  dialog.onclose = () => { if (!deleted) (opener?.isConnected ? opener : heading())?.focus({preventScroll: true}); };
  cancel.onclick = () => dialog.close();
  accept.onclick = async () => {
    if (!preview) return;
    accept.disabled = true; show("");
    let done;
    try {
      done = await api(`/api/finance/accounts/${accountId}/delete`, {method: "POST", body: JSON.stringify({token: preview.token})});
    } catch (failure) {
      if (failure.status === 409) { if (await load()) show(failure.message); }  // Changed since the preview: the counts above are the current ones.
      else { show(failure.message || String(failure)); accept.disabled = failure.status === 404; }
      return;
    }
    deleted = true; dialog.close();
    notice(`Deleted ${preview.account.display_name}. Its documents are still in your library.`);
    try { await onDeleted(done); } catch (failure) { notice(failure, true); }
    // The opener is gone with the row or the note; focus goes to the page's heading.
    heading()?.focus({preventScroll: true});
  };
  dialog.showModal(); cancel.focus();
  await load();
}

$("accounts2-import").prepend(icon("upload"));
$("accounts2-import").addEventListener("click", () => importPicker({onImported: reloadAccounts}));
