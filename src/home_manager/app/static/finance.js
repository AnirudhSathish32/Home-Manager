"use strict";
// The Money pages' shared parts (docs/money.md "Money pages"; the pages are month_v2.js, transactions_v2.js, bills_v2.js
// and accounts_v2.js): the ledger tools, the transaction drawer, record summaries and the statement reconciliation prompt.
// Every figure comes from a deterministic server tool as exact display text; the browser does no money arithmetic.
const tool = (name, args = {}) => api(`/api/finance/tools/${name}`, {method: "POST", body: JSON.stringify(args)});
// The ledger pages (Transactions, Spending, Bills, Accounts): in the family view, every member's records, each row with
// its owner (docs/family.md "Family ledger"); otherwise this profile's own.
const ledgerTool = (name, args = {}) => familyMode
  ? api(`/api/finance/tools/${name}?members=true`, {method: "POST", body: JSON.stringify(args)}) : tool(name, args);
// A record in the drawer: in the family view it's read from its owner's copy.
const recordUrl = (type, id, member) => `/api/finance/records/${type}/${id}${member ? `?member=${member}` : ""}`;
// In the family view an account is "<member id>:<account id>": ids are only unique within one person's library.
const accountOption = account => familyMode ? new Option(`${account.owner} · ${account.display_name}`, `${account.member_id}:${account.id}`)
  : new Option(account.display_name, account.id);
function accountArgs(args, value) {
  if (!value) return args;
  if (familyMode) { const [member, id] = value.split(":"); return Object.assign(args, {member, account_id: Number(id)}); }
  return Object.assign(args, {account_id: Number(value)});
}
const pad = value => String(value).padStart(2, "0");
function isoDay(day) { return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`; }
function todayIso() { return isoDay(new Date()); }
function monthRange(value) {
  const [year, month] = value.split("-").map(Number);
  return {start: `${value}-01`, end: `${value}-${pad(new Date(year, month, 0).getDate())}`};
}
function shiftMonth(value, delta) {
  const [year, month] = value.split("-").map(Number), day = new Date(year, month - 1 + delta, 1);
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}`;
}
function refreshReviewCount() { if (typeof loadNavCounts === "function") loadNavCounts().catch(() => {}); }
function tableMessage(target, columns, message) {
  const row = document.createElement("tr"), td = element("td", message, "muted"); td.colSpan = columns; row.append(td); target.replaceChildren(row);
}
let categoryCache = null;
async function loadCategoryOptions() {
  categoryCache = (await ledgerTool("get_categories")).categories.map(row => row.category);
  $("category-options").replaceChildren(...categoryCache.map(name => new Option(name)));
  return categoryCache;
}

// Old links: #/finances?section=… goes to the page that now holds that section, keeping the filters.
function openFinanceRoute(params) {
  const section = params.get("section");
  params.delete("section");
  const target = section === "review" || section === "unmatched" ? "review" : section === "bills" ? "bills" : "transactions";
  if (target === "bills") { params.delete("as_of"); }
  location.replace(`#/${target}${[...params].length ? `?${params}` : ""}`);
}

// Transactions -----------------------------------------------------------------------------------------------

const TX_PAGE = 200;
// A member's original, from the family computer (it opens while their app is stopped): fetched with this session's token,
// then shown in a new tab.
function originalButton(content, member, documentId, label) {
  const button = element("button", "", "link-button"); button.type = "button"; button.append(content);
  if (label) { button.title = label; button.setAttribute("aria-label", label); }
  button.addEventListener("click", async () => {
    const view = window.open("", "_blank");
    try {
      const response = await fetch(`/api/documents/${documentId}/image?member=${member}`, {headers: {"Authorization": `Bearer ${token}`}});
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "The document couldn't be opened.");
      const url = URL.createObjectURL(await response.blob());
      if (view) view.location = url; else window.location.assign(url);
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { if (view) view.close(); notice(error, true); }
  });
  return button;
}
function chargeCategorySelect(row, onDone) {
  // A charge with no itemised receipt has one category for all of it: the same choice as in the transaction drawer.
  const select = document.createElement("select"); select.setAttribute("aria-label", `Category of ${row.merchant}`);
  const names = [...new Set([...(categoryCache || []), ...(receiptCategoryCache || []), ...(row.category !== "uncategorized" ? [row.category] : [])])].sort();
  select.add(new Option("Uncategorized", ""));
  for (const name of names) select.add(new Option(categoryLabel(name), name));
  select.add(new Option("New category…", "__new"));
  select.value = row.category === "uncategorized" ? "" : row.category;
  select.title = row.category_source === "rule" ? "Set by a category rule" : row.category_source === "user" ? "Set by you" : "";
  select.addEventListener("change", async () => {
    if (select.value === "__new") { select.value = row.category === "uncategorized" ? "" : row.category; openTransaction(row.transaction_id, null, {onChange: onDone}); return; }
    select.disabled = true;
    try {
      await api(`/api/finance/transactions/${row.transaction_id}/category`, {method: "PUT", body: JSON.stringify({category: select.value || null})});
      notice(select.value ? `${row.merchant} is now ${categoryLabel(select.value)}.` : `Category cleared; any matching rule applies again.`);
      await onDone();
    } catch (error) { notice(error, true); } finally { select.disabled = false; }
  });
  return select;
}
function receiptLink(row) {
  // Opens the receipt matched to this transaction; a proposed match says so until it is confirmed.
  const link = element("a", "", "receipt-link"); link.href = `#/documents/${row.receipt_document_id}`;
  const proposed = row.receipt_link_status === "proposed", kind = row.transaction_type === "refund" ? "Return receipt" : "Receipt";
  link.append(icon("paperclip"), element("span", proposed ? `${kind} (proposed)` : kind, "visually-hidden-narrow"));
  link.title = `Matched ${kind.toLowerCase()}${proposed ? ", awaiting your confirmation in Review" : ""}`;
  return link;
}

// Transaction drawer: the record with its evidence, links, category and history.
const LINK_NAMES = {receipt: "Matched receipt", transfer: "Transfer between your accounts", refund: "Refund link", income: "Pay stub"};
function drawerSection(title, ...children) {
  const section = element("section", "", "drawer-section"); section.append(element("h3", title), ...children); return section;
}
function ruleWords(record) {
  // A starting suggestion only: the server normalizes the words the same way it matches them.
  return (record.merchant || record.description_raw || "").toUpperCase().replace(/#\s*\d+|\b\d+\b|[^\w\s&]/g, " ").split(/\s+/).filter(Boolean).slice(0, 3).join(" ");
}
// onChange reloads the list the drawer was opened from, if it was opened from one.
async function openTransaction(id, member = null, {onChange = null} = {}) {
  if (familyMode) return openFamilyTransaction(id, member, {onChange});
  const reload = () => onChange?.(), reopen = () => openTransaction(id, member, {onChange});
  const [record, {tag: taxTag}] = await Promise.all([api(`/api/finance/records/transaction/${id}`), api(`/api/tax-tags/on/transaction/${id}`).catch(() => ({tag: null}))]);
  await loadCategoryOptions().catch(() => {});
  const body = $("tx-drawer-body");
  $("tx-drawer-title").textContent = record.merchant || record.description_raw;
  const head = element("div", "", "drawer-head");
  const big = amount(record.display.amount_minor); big.classList.add("drawer-amount");
  head.append(big, element("p", `${dateText(record.posted_date)} · ${record.account}${record.transaction_date && record.transaction_date !== record.posted_date ? ` · purchased ${dateText(record.transaction_date)}` : ""}`, "muted"));
  if (record.merchant) head.append(element("p", record.description_raw, "muted small"));
  // Imports count unless rejected; extracted rows count once verified (automatically or by you).
  const counted = record.review_status !== "rejected" && (record.origin !== "extraction" || record.review_status === "verified");
  // The decision is the shared Confirm/Reject (trace.js, with an 8-second undo); the Category form below is the correction.
  const state = element("div", "", "drawer-status");
  state.append(confirmCorrect({recordType: "transaction", recordId: id, reviewStatus: record.review_status, reviewSource: record.review_source,
                               correctable: [], onChange: () => Promise.all([reopen(), reload(), refreshReviewCount()])}).el,
               element("p", counted ? "Counted in your totals." : record.review_status === "rejected" ? "Not counted." : "Not counted until you decide.", "muted small"));
  // Category: the user's own choice, or a rule for every transaction like this one.
  const form = element("form", "", "drawer-category");
  const input = document.createElement("input"); input.setAttribute("list", "category-options"); input.value = record.category || ""; input.maxLength = 60;
  input.id = "tx-drawer-category"; input.setAttribute("aria-label", "Category"); input.placeholder = "e.g. groceries";
  const always = document.createElement("input"); always.type = "checkbox"; always.id = "tx-drawer-always";
  const words = document.createElement("input"); words.value = ruleWords(record); words.id = "tx-drawer-words"; words.setAttribute("aria-label", "Words the rule matches"); words.maxLength = 120;
  const ruleRow = element("label", "", "compact-check"); ruleRow.append(always, document.createTextNode(" Always use for transactions containing "), words);
  const save = element("button", "Save category", "small primary"); save.type = "submit";
  const source = element("small", record.category_source === "rule" ? "Set by a category rule. Saving here overrides it for this transaction only." :
                                  record.category_source === "user" ? "Set by you." : "No category yet.", "muted block");
  form.append(input, save, ruleRow, source);
  if (record.category_source === "user") form.append(asyncButton("Clear my category", async () => {
    await api(`/api/finance/transactions/${id}/category`, {method: "PUT", body: JSON.stringify({category: null})});
    notice("Category cleared; any matching rule applies again."); await Promise.all([reopen(), reload()]);
  }, "small quiet"));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const category = input.value.trim();
    if (!category) { notice("Enter a category, or use Clear my category.", true); return; }
    if (!always.checked && record.splits?.length && !await confirmAction({title: "Replace the item categories?",
      message: "Saving this category puts the whole charge in it instead of splitting it by the receipt's items.", confirmLabel: "Use for whole charge"})) return;
    try {
      if (always.checked) {
        const rule = await api("/api/finance/category-rules", {method: "POST", body: JSON.stringify({pattern: words.value.trim(), category})});
        if (record.category_source === "user") await api(`/api/finance/transactions/${id}/category`, {method: "PUT", body: JSON.stringify({category: null})});
        notice(`Rule saved: “${rule.pattern}” → ${rule.category}. ${rule.changed} transaction${rule.changed === 1 ? "" : "s"} updated.`);
      } else {
        await api(`/api/finance/transactions/${id}/category`, {method: "PUT", body: JSON.stringify({category})});
        notice(`Category saved for ${record.description_raw}.`);
      }
      await Promise.all([reopen(), reload()]);
    } catch (error) { notice(error, true); }
  });
  const evidence = element("ul", "", "finance-list");
  for (const item of record.evidence) {
    const li = document.createElement("li");
    li.append(homeLink(item.relative_path, `#/documents/${item.document_id}`), element("small", item.locator?.rows ? `Row ${item.locator.rows.join(", ")}` : item.locator?.line_ids ? "Statement line" : "", "muted"));
    evidence.append(li);
  }
  for (const link of record.links) {
    const li = document.createElement("li"), other = link.counterpart;
    li.append(element("strong", `${LINK_NAMES[link.kind] || link.kind}${link.review_status === "proposed" ? " (proposed)" : ""}`),
              element("span", describe(other), "block"), element("small", `Why: ${link.match_signals.map(signal => SIGNALS[signal] || signal.replaceAll("_", " ")).join(", ")}`, "muted"));
    if (other?.document_id) li.append(homeLink("Open document", `#/documents/${other.document_id}`));
    evidence.append(li);
  }
  if (!evidence.children.length) evidence.append(element("li", "No linked receipt or source document.", "muted"));
  const history = element("ul", "", "finance-list");
  for (const event of record.review_history) history.append(element("li", `${new Date(event.created_at).toLocaleString()}: ${statusLabel(event.previous_status)} → ${statusLabel(event.new_status)}${event.note ? ` · ${event.note}` : ""}`));
  // Changes the family made here (docs/family.md "Family corrections"): each can be rejected, which puts the value back.
  for (const change of record.family_corrections || []) {
    const li = element("li", `${new Date(change.created_at).toLocaleString()}: ${change.field.replaceAll("_", " ")} changed by ${change.actor.replace(/^Family · /, "family (")}${change.actor.startsWith("Family · ") ? ")" : ""}`
                            + ` from ${change.previous ?? "nothing"} to ${change.value ?? "nothing"}`);
    if (change.status === "applied") li.append(document.createTextNode(" "), asyncButton("Reject", async () => {
      await api(`/api/finance/family-corrections/${change.key}/reject`, {method: "POST", body: "{}"});
      notice(`Put back ${change.previous ?? "the earlier value"}.`); await Promise.all([reopen(), reload()]);
    }, "small quiet"));
    else li.append(element("small", ` · ${statusLabel(change.status)}`, "muted"));
    history.append(li);
  }
  if (!history.children.length) history.append(element("li", "No decisions yet.", "muted"));
  const details = element("details", "", "technical-detail");
  details.append(element("summary", "Details"), element("p", `Type: ${statusLabel(record.transaction_type)} · Origin: ${record.origin} · Currency: ${record.currency}`, "small"),
                 element("p", `Fingerprint: ${record.source_fingerprint}`, "small mono"));
  // A charge with an itemised receipt counts by its items' categories; the category above then covers none of it unless set by you.
  const sections = [head, state];
  if (record.splits?.length) {
    const split = element("ul", "", "finance-list");
    for (const row of record.splits) {
      const li = document.createElement("li"); li.append(element("span", categoryLabel(row.category)), document.createTextNode(" "), amount(row.display.amount_minor, {signed: false}));
      split.append(li);
    }
    sections.push(drawerSection("Split by the receipt's items", split,
                                element("small", "Change an item's category in the Items view or on the receipt. Saving a category below puts the whole charge in it instead.", "muted block")));
  }
  // Taxes (taxes.js): a write-off, business income or a tax payment made ahead.
  const taxes = taxTagEditor({targets: [{type: "transaction", id, label: record.description_raw, inflow: record.amount_minor > 0,
                                         amount: record.display.amount_minor.replace(/^-/, "")}],
                              tags: taxTag ? [taxTag] : [], words: ruleWords(record), onDone: reopen});
  body.replaceChildren(...sections, drawerSection("Category", form), drawerSection("Taxes", taxes), drawerSection("Evidence", evidence),
                       drawerSection("History", history), details);
  if (!$("tx-drawer").open) $("tx-drawer").showModal();
}
// The family ledger's drawer: a member's transaction as their latest copy has it, with its evidence opening from the
// family computer.
async function openFamilyTransaction(id, member, {onChange = null} = {}) {
  const record = await api(recordUrl("transaction", id, member));
  $("tx-drawer-title").textContent = record.merchant || record.description_raw;
  const head = element("div", "", "drawer-head");
  const big = amount(record.display.amount_minor); big.classList.add("drawer-amount");
  head.append(big, element("p", `${record.owner} · ${dateText(record.posted_date)} · ${record.account}`, "muted"));
  if (record.merchant) head.append(element("p", record.description_raw, "muted small"));
  const state = element("div", "", "drawer-status");
  state.append(statusBadge(record.review_status));
  if (record.pending_fields.length) state.append(element("span", ` Waiting for ${record.owner}: ${record.pending_fields.map(field => field.replaceAll("_", " ")).join(", ")}`, "muted small"));
  // A correction travels to the person and applies in their own records (docs/family.md "Family corrections").
  const form = element("form", "", "form family-correction");
  const fields = [["category", "Category", record.category || "", "text"], ["merchant", "Merchant", record.merchant || record.description_raw, "text"],
                  ["posted_date", "Date", record.posted_date, "date"]];
  for (const [field, label, value, type] of fields) {
    const wrap = element("div", "", "field"), name = element("label", label), input = element("input");
    input.id = `family-fix-${field}`; input.type = type; input.value = value; input.maxLength = 120; input.dataset.field = field; input.dataset.original = value;
    if (field === "category") input.setAttribute("list", "category-options");
    name.htmlFor = input.id; wrap.append(name, input);
    if (record.pending_fields.includes(field)) wrap.append(element("small", `Waiting for ${record.owner}`, "muted"));
    form.append(wrap);
  }
  const save = element("button", "Send correction", "small primary"); save.type = "submit";
  form.append(save, element("small", `${record.owner} sees it in their own records, marked as changed by the family, and can reject it.`, "muted block"));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const changes = {};
    for (const input of form.querySelectorAll("input[data-field]")) if (input.value.trim() !== input.dataset.original) changes[input.dataset.field] = input.value.trim() || null;
    if (!Object.keys(changes).length) { notice("Change a field first.", true); return; }
    save.disabled = true;
    try {
      await api(recordUrl("transaction", id, member), {method: "PATCH", body: JSON.stringify({changes})});
      notice(`Sent to ${record.owner}.`);
      await Promise.all([openFamilyTransaction(id, member, {onChange}), onChange?.()]);
    } catch (error) { notice(error, true); } finally { save.disabled = false; }
  });
  const evidence = element("ul", "", "finance-list");
  for (const item of record.evidence) {
    const li = document.createElement("li");
    li.append(originalButton(document.createTextNode(item.relative_path), member, item.document_id));
    evidence.append(li);
  }
  if (!evidence.children.length) evidence.append(element("li", "No linked receipt or source document.", "muted"));
  const history = element("ul", "", "finance-list");
  for (const event of record.review_history) history.append(element("li", `${new Date(event.created_at).toLocaleString()}: ${statusLabel(event.previous_status)} → ${statusLabel(event.new_status)}${event.note ? ` · ${event.note}` : ""}`));
  if (!history.children.length) history.append(element("li", "No decisions yet.", "muted"));
  $("tx-drawer-body").replaceChildren(head, state, drawerSection("Correct", form), drawerSection("Evidence", evidence), drawerSection("History", history),
    element("p", `${record.owner}'s records stay in their own profile; this is their latest copy.`, "muted small"));
  if (!$("tx-drawer").open) $("tx-drawer").showModal();
}
$("close-tx-drawer").addEventListener("click", () => $("tx-drawer").close());
$("tx-drawer").addEventListener("click", event => { if (event.target === $("tx-drawer")) $("tx-drawer").close(); });

// Shared with Review: record summaries in words.
const RECORD_KINDS = {statement: "Statement", receipt: "Receipt", bill: "Bill", income_record: "Pay stub", transaction: "Transaction"};
const SIGNALS = {amount: "same amount", same_day: "same day", date: "within two days", merchant: "merchant matches", opposite_amount: "opposite amounts",
                 date_window: "within five days", exact_amount: "exact amount", partial_amount: "partial amount", user_choice: "your choice"};
function describe(summary, {named = true} = {}) {
  // "Costco Wholesale · 163.82 USD · Sep 15, 2026 · Fidelity credit card 7314", from a server-side record summary.
  if (!summary) return "Record no longer available";
  return [named && (summary.name || summary.description || RECORD_KINDS[summary.record_type]), summary.amount?.display,
          summary.date && dateText(summary.date), summary.account].filter(Boolean).join(" · ");
}

// Budgets ---------------------------------------------------------------------------------------------

function meter(row) {
  // Share of the budget used; the fill carries the status and is always paired with its icon and label.
  const track = element("div", "", "meter"); track.dataset.status = row.status;
  const fill = element("div", "", "meter-fill"); fill.style.width = `${row.meter_percent}%`;
  track.append(fill); track.setAttribute("role", "img"); track.setAttribute("aria-label", `${row.percent_used}% of the budget used`);
  return track;
}
function txHref(extra) { return `#/transactions?${new URLSearchParams(extra)}`; }

// Accounts -----------------------------------------------------------------------------------------------

const ACCOUNT_GROUPS = [["Cash", ["checking", "savings"]], ["Credit cards", ["credit_card"]], ["Investments", ["brokerage"]], ["Loans", ["loan"]], ["Other", ["other"]]];

// Statement reconciliation prompt ---------------------------------------------------------------------------
// A newly recorded bank or card statement asks before its charges replace the receipts already counted.
// Until the user says yes, its charges are not counted, so no purchase is counted twice.

const STATEMENT_KINDS = {bank: "Bank statement", credit_card: "Credit card statement"};
const declinedStatements = new Set();  // "No" for this visit: the prompt becomes a reminder.
let reconcileResults = [];
function statementName(row) {
  const period = row.period_start ? `${dateText(row.period_start)} – ${dateText(row.period_end)}` : `ending ${dateText(row.period_end)}`;
  return `${row.account || row.institution}, ${period}`;
}
async function reconcileStatement(row) {
  const result = await api(`/api/finance/statements/${row.id}/reconcile`, {method: "POST"});
  declinedStatements.delete(row.id);
  const parts = [`${result.matched_receipts} of ${result.charges} charges matched to your receipts`];
  if (result.questions) parts.push(`${result.questions} ${result.questions === 1 ? "needs" : "need"} you to pick the right charge`);
  reconcileResults = [{row, message: `Reconciled ${STATEMENT_KINDS[row.statement_type].toLowerCase()} (${statementName(row)}): ${parts.join("; ")}. `
                       + "Matched receipts are now counted through their charge; the rest still count on their own.", review: result.questions > 0}];
  refreshReviewCount();
  await loadReconcilePrompt();
  // The page on screen shows totals from before the statement's charges counted.
  if (currentRoute) Promise.resolve().then(() => (V2_SCREENS[currentRoute.name] || ROUTES[currentRoute.name]).show(currentRoute))
    .catch(error => notice(error, true));
}
function reconcilePromptBox(row) {
  const kind = STATEMENT_KINDS[row.statement_type];
  const actions = element("div", "", "button-row");
  if (declinedStatements.has(row.id)) {
    actions.append(asyncButton("Reconcile now", () => reconcileStatement(row)));
    return alertBox(`${kind} (${statementName(row)}) is waiting to be reconciled. Its ${row.lines} charges aren't counted until you do.`, {action: actions});
  }
  const question = element("p", "Begin reconciling receipts?", "reconcile-question");
  actions.append(asyncButton("Yes", () => reconcileStatement(row), "primary"),
                 asyncButton("No", async () => { declinedStatements.add(row.id); await loadReconcilePrompt(); }));
  const detail = element("div");
  detail.append(question, element("p", `${row.lines} charges on this statement; ${row.receipts} receipts from the period have no matching charge yet.`, "muted small"), actions);
  return alertBox(`${kind} recorded: ${statementName(row)}.`, {action: detail});
}
async function loadReconcilePrompt() {
  if (!configured) { $("reconcile-prompt").replaceChildren(); return; }
  const waiting = await api("/api/finance/statements/awaiting-reconciliation");
  const results = reconcileResults.map(({message, review}) => {
    const actions = element("div", "", "button-row");
    if (review) actions.append(homeLink("Open Review", "#/review"));
    actions.append(asyncButton("Dismiss", async () => { reconcileResults = []; await loadReconcilePrompt(); }, "small quiet"));
    return alertBox(message, {action: actions});
  });
  $("reconcile-prompt").replaceChildren(...results, ...waiting.map(reconcilePromptBox));
}
