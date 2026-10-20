"use strict";
// The document page's record builders (document_v2.js draws the page): details, readings' telemetry, the ledger
// record's fields and rows, pay stubs, rewards and investment records. Every amount is the server's text.
const PENDING_RUN = ["queued", "running"];

function copyButton(text, label = "Copy") {
  const button = element("button", label, "small"); button.type = "button";
  button.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); button.textContent = "Copied"; }
    catch { notice("Copying isn't available here. Select the text and press Ctrl+C.", true); }
  });
  return button;
}
function detailRow(list, label, ...values) {
  const value = document.createElement("dd");
  value.append(...values.map(item => item instanceof Node ? item : document.createTextNode(String(item))));
  list.append(element("dt", label), value);
}
const SOURCE_STATES = {present: "In Inbox, unchanged", missing: "No longer in Inbox", organized: "Moved from Inbox into the library"};
// A watched folder's file is copied, never moved: its state describes the folder.
const WATCHED_STATES = {present: "In the watched folder, unchanged", missing: "No longer in the watched folder; the library copy stays", organized: "Copied into the library"};
const LINK_REASONS = {same_bytes: "Same file", same_record: "Same purchase"};
function sourcePath(doc) { return doc.source_kind === "inbox" ? doc.relative_path : `${doc.source_root}\\${doc.relative_path.replaceAll("/", "\\")}`; }
function modelNote(text) {
  const note = element("p", `${text} `, "muted small"), link = element("a", "Set one up in Settings"); link.href = "#/settings";
  note.appendChild(link); return note;
}
const METHODS = {vision_model: "Local vision model", pdf_pages: "PDF pages (embedded text, vision for scanned pages)"};
function runTelemetry(run) {
  if (!run.model_runs?.length) return "No model requests recorded for this run.";
  const workflow = run.status === "queued" || run.status === "running" ? "in progress" : seconds(new Date(run.updated_at) - new Date(run.created_at));
  return `Model requests: ${run.model_runs.map(telemetryText).join("; ")}. Total workflow time (queued to finished): ${workflow}. Model identity: ${run.model_identity || "unavailable (results are not reused)"}.`;
}
const RECORD_FIELDS = {
  receipt: [["Record as", "document_kind"], ["Merchant", "merchant"], ["Location", "location"], ["Purchase date", "purchase_date"], ["Categories", "category"], ["Billed", "recurrence"],
            ["Sale or return", "direction"], ["Subtotal", "subtotal_minor"], ["Tax", "tax_minor"], ["Tip", "tip_minor"], ["Total", "total_minor"]],
  statement: [["Period", "period_start", "period_end"], ["Opening balance", "opening_balance_minor"], ["Closing balance", "closing_balance_minor"],
              ["Statement balance", "statement_balance_minor"], ["Minimum payment", "minimum_payment_minor"], ["Due", "due_date"]],
  // A bill is a receipt with document_kind 'bill' (docs/money.md "Bills and their lines"); it counts on its due date.
  bill: [["Record as", "document_kind"], ["Provider", "merchant"], ["Issued", "issue_date"], ["Due", "due_date"], ["Period", "period_start", "period_end"], ["Categories", "category"],
         ["Billed", "recurrence"], ["New charges", "total_minor"], ["Amount due", "amount_due_minor"]],
  income_record: [["Employer", "merchant"], ["Pay date", "pay_date"], ["Pay period", "period_start", "period_end"], ["Paid", "pay_frequency"],
                  ["Work state", "work_state"], ["Gross pay this period", "gross_pay_minor"], ["Net pay this period", "net_pay_minor"],
                  ["Gross pay year to date", "gross_pay_ytd_minor"], ["Net pay year to date", "net_pay_ytd_minor"],
                  ["Taxes this period", "taxes_minor"], ["Pre-tax deductions this period", "deductions_minor"],
                  ["Total deductions this period", "total_deductions_minor"]],
};
const PAY_FREQUENCIES = {52: "Weekly", 26: "Every two weeks", 24: "Twice a month", 12: "Monthly"};
const DOCUMENT_KIND_LABELS = {receipt: "Purchase", bill: "Bill"};
const isDateField = field => field.endsWith("_date");
// A receipt is a sale or a return (docs/money.md "Returns"); an exchange is a return whose lines also buy something.
const DIRECTIONS = {sale: "Sale", return: "Return"};
const directionText = record => record.sale_label === "Exchange" ? "Exchange" : DIRECTIONS[record.direction] || record.direction;
function decisionPanel(check, extractedType) {
  // Advisory only: shown beside the record, never used to approve, reject or file it.
  // Extractions from before decision models carry Laya's result in the same shape, without a model.
  const name = check.model ? check.model.model : "Laya";
  const panel = element("details", "", "decision-panel");
  if (check.error) { panel.append(element("summary", `Independent check (${name}) unavailable`), element("p", check.error, "muted")); return panel; }
  // Counts and percents are the server's (documents/extraction.py check_counts).
  const doubted = check.checks.filter(item => item.supported === false), unscored = check.unscored, shadow = check.classification;
  panel.appendChild(element("summary", `Independent check (${name}): ${check.confirmed} of ${check.scored} values confirmed`));
  if (shadow.document_type) {
    panel.appendChild(element("p", `${name} classifies this as ${shadow.document_type.replaceAll("_", " ")} (${shadow.confidence_percent}%)` +
      (shadow.agrees ? ", matching the extraction." : `; the extraction says ${(extractedType || "unknown").replaceAll("_", " ")}.`), shadow.agrees ? "muted" : "item-warning"));
  }
  const list = element("ul", "", "analysis-limitations");
  for (const item of doubted) list.appendChild(element("li", `${item.field.replaceAll("_", " ")}: not confirmed from its cited text (${item.probability_percent}%)`));
  if (doubted.length) panel.appendChild(list);
  if (unscored) panel.appendChild(element("p", `${unscored} ${unscored === 1 ? "value" : "values"} could not be scored.`, "muted"));
  const calibration = check.model && check.model.calibrated ? "" : " Its scores are not yet calibrated on your documents.";
  panel.appendChild(element("p", `${name} checks every extraction. A value it cannot confirm sends the record to review; it never approves one, and its document type is shown only for reference.${calibration}`, "muted"));
  return panel;
}
// A file holding several receipts (docs/documents.md): one receipt's lines of the reading.
function segmentLines(segment, lines) {
  lines = (lines || []).filter(line => line.text.trim());
  const first = lines.findIndex(line => line.id === segment.first_line_id), last = lines.findIndex(line => line.id === segment.last_line_id);
  return first < 0 || last < first ? [] : lines.slice(first, last + 1);
}
const RECORD_LABELS = {receipt: "receipt", statement: "statement", bill: "bill", income_record: "pay stub"};
function ledgerTitle(type, record) {
  // Same naming rule as documents: Merchant - Location - Description; dates and amounts are fields below. A pay stub is named by its date.
  const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(record.pay_date || "");
  if (type === "income_record" && date) return `Paystub ${date[2]}/${date[3]}/${date[1]}`;
  const parts = [record.merchant || record.institution, record.location, record.description].filter(Boolean);
  return parts.length ? parts.join(" - ") : RECORD_LABELS[type].replace(/^./, character => character.toUpperCase());
}
// find: how the row's source lines are shown; the document page passes its source viewer's (document_v2.js).
function sourceButton(lineIds, find) {
  const button = element("button", "Find", "source-link"); button.type = "button";
  button.setAttribute("aria-label", "Find this row in the transcription");
  button.addEventListener("click", () => find(lineIds));
  return button;
}
const REWARD_KINDS = {earned: "Earned", redeemed: "Redeemed", balance: "Balance", offer: "Offer", survey: "Survey", membership: "Member savings"};
function rewardsList(rewards, find) {
  // Rewards, perks and offers printed on the receipt or in its QR codes. Links are shown as text, never opened:
  // they come from a document, not from Home Manager.
  const section = element("section", "", "receipt-rewards");
  const list = element("ul", "", "finance-list");
  for (const reward of rewards) {
    const li = document.createElement("li");
    li.append(element("strong", REWARD_KINDS[reward.kind] || reward.kind), document.createTextNode(` ${reward.description}`));
    if (reward.amount_text) li.append(document.createTextNode(` · ${reward.amount_text}`));
    if (reward.expires_on) li.append(element("small", ` · ${reward.expires_on < todayIso() ? "expired" : "expires"} ${dateText(reward.expires_on)}`, "muted"));
    if (reward.link) li.append(element("small", reward.link, "muted block mono"));
    if (reward.line_ids?.length) li.append(sourceButton(reward.line_ids, find));
    list.append(li);
  }
  section.append(element("h3", "Rewards & offers"), list);
  return section;
}
let receiptCategoryCache = null;
async function receiptCategories() {
  // The server's fixed list, the same one the Receipts subfolders use.
  // Retired categories (legacy) are listed as folders until re-sorted, never offered as a choice.
  receiptCategoryCache ??= (await api("/api/folders")).receipt_categories.filter(row => !row.legacy && row.category !== "uncategorized").map(row => row.category);
  return receiptCategoryCache;
}
function itemCategorySelect(receiptId, row, categories, onSaved) {
  // Each item has its own spending category; the choice is remembered for this item from this seller.
  const select = document.createElement("select"), current = row.category === "uncategorized" ? null : row.category;
  select.setAttribute("aria-label", `Category of ${row.description || row.item || "this item"}`);
  if (!current) select.add(new Option("Choose…", ""));
  for (const name of categories) select.add(new Option(categoryLabel(name), name));
  select.value = current || "";
  select.title = {user: "Chosen by you", memory: "Your earlier choice for this item", receipt: "From the receipt's category", model: "Suggested by the model"}[row.category_source] || "";
  select.addEventListener("change", async () => {
    select.disabled = true;
    try {
      await api(`/api/receipts/${receiptId}/items/${row.position}/category`, {method: "PUT", body: JSON.stringify({category: select.value})});
      notice(`${row.description || row.item} is now ${categoryLabel(select.value)}.`);
      await onSaved?.();
    } catch (error) { notice(error, true); select.value = current || ""; }
    finally { select.disabled = false; }
  });
  return select;
}
// What a bill's line is (docs/money.md "Bills and their lines"); core/categories.py LINE_KINDS.
const LINE_KIND_LABELS = {service: "Service", usage: "Usage", subscription: "Subscription", device: "Device", tax_fee: "Tax or fee", credit: "Credit", other: "Other"};
// A rent bill's line types (specs/bill-kinds FR-44; core/categories.py RENT_LINE_TYPES).
const RENT_TYPE_LABELS = {rent: "Rent", parking: "Parking", pet: "Pet", utility: "Utility", fee: "Fee", credit: "Credit", other: "Other"};
// A rent line's printed period (or its one date) and usage under its description, each with Find on its cited line.
function billLineFacts(row, find) {
  const facts = [], details = row.details || {};
  const fact = (text, detail, what) => {
    const small = element("small", text, "muted block bill-line-fact");
    const ids = detail.locator?.line_ids?.length ? detail.locator.line_ids : row.line_ids;
    if (ids?.length) { const button = sourceButton(ids, find); button.setAttribute("aria-label", `Find the ${what} of ${row.description}`); small.append(" ", button); }
    facts.push(small);
  };
  if (details.period?.start && details.period?.end) fact(dateRangeText(details.period.start, details.period.end), details.period, "period");
  else if (details.date?.value) fact(dateText(details.date.value), details.date, "date");
  if (details.usage?.text) fact(details.usage.text, details.usage, "usage");
  return facts;
}
// A kinded bill's rows under its lines (Ledger.bill_summary): carried amounts, the earlier balance or what isn't
// accounted for, then the amount due last under a rule. Every amount is the server's.
function billSummaryRows(foot, record, find, correctField) {
  const summary = record.bill_summary;
  const row = (label, value, className = "", note = null) => {
    const tr = element("tr", "", className), name = element("th", label); name.scope = "row";
    const cell = element("td", "", "numeric"); cell.append(amount(value?.display || "—", {signed: false}));
    // The note sits in the wide cell beside the amount, where it wraps (a row header doesn't).
    const actions = element("td"); actions.colSpan = 5;
    if (note) actions.append(element("small", note, "muted block bill-row-note"));
    tr.append(name, cell, actions); foot.append(tr);
    return actions;
  };
  for (const item of summary.carried) {
    const actions = row(item.label, item);
    if (item.line_ids?.length) actions.append(sourceButton(item.line_ids, find));
  }
  if (summary.earlier_balance) row("Earlier balance", summary.earlier_balance, "bill-earlier", "Worked out: the amount due less the new charges");
  if (summary.gap) row("Not accounted for", summary.gap, "bill-gap", summary.gap.reason);
  const actions = row("Amount due", summary.amount_due, "bill-total");
  if (summary.amount_due.line_ids?.length) {
    const button = sourceButton(summary.amount_due.line_ids, find); button.setAttribute("aria-label", "Find the amount due in the source"); actions.append(button);
  }
  if (correctField) {
    const button = element("button", "Correct", "link-button"); button.type = "button"; button.setAttribute("aria-label", "Correct amount due");
    button.addEventListener("click", () => correctField("amount_due")); actions.append(button);
  }
}
// A bill's lines: each line's price, category, type and person, then its new charges and amount due. The person is chosen
// from the family where its people are known (the family's inbox); elsewhere it shows who the line is for as printed.
function invoiceDetails(record, find) {
  const wrap = element("div");
  if (record.invoice) {
    const invoice = record.invoice, details = element("dl", "", "invoice-details");
    for (const [label, field] of [["Invoice number", "number"], ["Bill to", "bill_to"], ["Printed payment status", "payment_status"],
      ["Invoice subtotal", "subtotal_minor"], ["Invoice tax", "tax_minor"], ["Printed invoice total", "total_minor"],
      ["Payments / deposits", "payments_received_minor"], ["Remaining balance", "balance_due_minor"]]) {
      if (invoice[field] != null) detailRow(details, label, invoice.display?.[field] ?? invoice[field]);
    }
    wrap.append(details);
    if (invoice.locator?.line_ids?.length) wrap.append(sourceButton(invoice.locator.line_ids, find));
  }
  return wrap;
}
function billLines(record, categories, onSaved, find, correctField = null) {
  const people = familyMode ? (familyView?.members || []) : [];
  const nameOf = id => people.find(person => person.member_id === id)?.name;
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "ledger-rows bill-lines");
  const rent = record.bill_kind === "rent" && Boolean(record.bill_summary);
  if (record.invoice) wrap.append(invoiceDetails(record, find));
  const head = document.createElement("tr");
  for (const [title, className] of [["Line", ""], ["Price", "numeric"], ["Category", ""], ["Type", ""], ["Person", ""], ["Paid", "numeric"], ["", ""]]) {
    const th = head.appendChild(element("th", title, className)); th.scope = "col";
  }
  table.appendChild(document.createElement("thead")).appendChild(head);
  const body = table.appendChild(document.createElement("tbody"));
  const save = async (row, field, value, select) => {
    select.disabled = true;
    try {
      await api(`/api/receipts/${record.id}/lines/${row.position}`, {method: "PATCH", body: JSON.stringify({field, value: value || null})});
      await onSaved?.();
    } catch (error) { notice(error, true); select.disabled = false; }
  };
  for (const row of record.items.slice(0, 200)) {
    const tr = document.createElement("tr");
    if (row.line_ids?.length) tr.dataset.lines = row.line_ids.join(" ");
    const line = element("td"); line.append(element("span", row.description));
    if (row.quantity != null || row.unit_price_minor != null) line.append(element("small",
      `Quantity: ${row.quantity ?? "not printed"} · Unit price: ${row.display.unit_price_minor ?? "not printed"}`, "muted block"));
    if (row.line_holder) line.append(element("small", row.line_holder, "muted block"));
    if (rent) line.append(...billLineFacts(row, find));
    const price = element("td", "", "numeric"); price.append(amount(row.display.line_total_minor || "—", {signed: false}));
    const category = element("td");
    category.append(categories.length ? itemCategorySelect(record.id, row, categories, onSaved) : document.createTextNode(row.category ? categoryLabel(row.category) : "—"));
    const kind = element("td"), person = element("td");
    if (rent) {  // A rent type, which sets the line's kind; a line from before it was read as rent shows its kind until one is chosen.
      if (categories.length) {
        const types = document.createElement("select"); types.setAttribute("aria-label", `Type of ${row.description}`);
        types.append(new Option("Not set", ""), ...Object.entries(RENT_TYPE_LABELS).map(([key, label]) => new Option(label, key)));
        types.value = row.line_type || "";
        types.addEventListener("change", () => save(row, "line_type", types.value, types));
        kind.append(types);
      } else kind.textContent = RENT_TYPE_LABELS[row.line_type] || "Not set";
      if (!row.line_type && row.line_kind) kind.append(element("small", LINE_KIND_LABELS[row.line_kind] || row.line_kind, "muted block"));
    } else if (categories.length) {
      const kinds = document.createElement("select"); kinds.setAttribute("aria-label", `Type of ${row.description}`);
      kinds.append(new Option("Not set", ""), ...Object.entries(LINE_KIND_LABELS).map(([key, label]) => new Option(label, key)));
      kinds.value = row.line_kind || "";
      kinds.addEventListener("change", () => save(row, "line_kind", kinds.value, kinds));
      kind.append(kinds);
    } else kind.textContent = LINE_KIND_LABELS[row.line_kind] || "—";
    if (people.length && categories.length) {
      const who = document.createElement("select"); who.setAttribute("aria-label", `Whose ${row.description} is`);
      who.append(new Option("Shared (taxes, fees)", ""), ...people.map(member => new Option(member.name, member.member_id)));
      who.value = row.member_id || "";
      who.addEventListener("change", () => save(row, "member", who.value, who));
      person.append(who);
    } else person.textContent = nameOf(row.member_id) || (row.member_id ? "Someone in the family" : row.line_holder ? row.line_holder.replace(/[\d()\-\s]+$/, "") || "—" : "Shared");
    const paid = element("td", "", "numeric");
    if (row.display.share_minor && row.share_minor !== row.line_total_minor) { paid.append(amount(row.display.share_minor, {signed: false}), element("small", "with taxes and fees", "muted block")); }
    else paid.append(element("span", "—", "muted"));
    const source = document.createElement("td"); if (row.line_ids?.length) source.appendChild(sourceButton(row.line_ids, find));
    tr.append(line, price, category, kind, person, paid, source);
    body.appendChild(tr);
  }
  const foot = table.appendChild(element("tfoot"));
  if (record.bill_summary) billSummaryRows(foot, record, find, correctField);
  else for (const [label, field] of [[record.invoice ? "Invoice total" : "New charges", "total"], [record.invoice ? "Remaining balance" : "Amount due", "amount_due"]]) {
    const tr = element("tr"), name = element("th", label); name.scope = "row";
    const value = element("td", "", "numeric"); value.append(amount(record.display[`${field}_minor`] || "—", {signed: false}));
    const actions = element("td"); actions.colSpan = 5;
    if (correctField) {
      const button = element("button", "Correct", "link-button"); button.type = "button"; button.setAttribute("aria-label", `Correct ${label.toLowerCase()}`);
      button.addEventListener("click", () => correctField(field)); actions.append(button);
    }
    tr.append(name, value, actions); foot.append(tr);
  }
  wrap.appendChild(table);
  if (!record.bill_summary && record.amount_due_minor != null && record.total_minor != null && record.amount_due_minor !== record.total_minor) {
    wrap.append(element("p", record.invoice ? "The full invoice charge and its remaining balance are recorded separately. Payments do not reduce the purchase total."
      : "Only the new charges count; the rest of the amount due is from an earlier bill.", "muted small"));
  }
  if (record.includes?.length) wrap.append(element("p", `Includes: ${record.includes.join(", ")}. These are part of this bill, not separate subscriptions.`, "muted small"));
  if (record.share) wrap.append(element("p", record.share.member_id ? "Shared by line in the family: your own lines and your part of the taxes and fees count."
                                                                   : "Shared by the family: only your part counts.", "muted small"));
  if (record.splits?.length) {
    const split = element("p", "", "receipt-splits small");
    split.append(element("strong", "By category: "), document.createTextNode(record.splits.map(row => `${categoryLabel(row.category)} ${row.display.amount_minor}`).join(" · ")),
                 document.createTextNode(" "), statusBadge(record.reconciled ? "reconciled" : "bill"));
    wrap.appendChild(split);
  }
  return wrap;
}
function ledgerRows(record, categories, onSaved, find, correctField = null) {
  if (record.document_kind === "bill" && record.items) return billLines(record, categories, onSaved, find, correctField);
  // Items or transactions exactly as recorded, each linked to its source line. Receipt items carry their own category
  // and their share of what was paid (the price with its part of tax and receipt-wide discounts).
  const rows = record.items || record.transactions || [];
  if (!rows.length && !record.items) return null;
  const wrap = element("div", "", "table-wrap");
  if (record.invoice) wrap.append(invoiceDetails(record, find));
  const table = element("table", "", "ledger-rows");
  // Product codes are printed on shop receipts, not restaurant bills: the column appears only when a row has one.
  const codes = Boolean(record.items?.some(row => row.product_code));
  const shares = Boolean(record.items?.some(row => row.display.share_minor));
  const columns = record.items ? ["Item", "Code", "Price", "Category", "Paid", ""] : ["Posted", "Description", "Amount", ""];
  const shown = index => !record.items || !((index === 1 && !codes) || (index === 4 && !shares));
  const head = document.createElement("tr");
  columns.forEach((title, index) => {
    if (!shown(index)) return;
    const th = head.appendChild(element("th", title, index === 2 || index === 4 ? "numeric" : "")); th.scope = "col";
  });
  table.appendChild(document.createElement("thead")).appendChild(head);
  const body = table.appendChild(document.createElement("tbody"));
  for (const row of rows.slice(0, 200)) {
    const tr = document.createElement("tr");
    if (row.line_ids?.length) tr.dataset.lines = row.line_ids.join(" ");  // For reverse lookup from the image.
    const paid = row.line_total_minor == null ? "—" : row.share_minor !== row.line_total_minor && row.display.share_minor ? row.display.share_minor : "—";
    const values = record.items ? [row.description, row.product_code || "", row.display.line_total_minor || "—", "", paid]
      : [row.posted_date, row.description_raw, row.display.amount_minor];
    values.forEach((value, index) => {
      if (!shown(index)) return;
      const money = index === 2 || index === 4;
      const td = tr.appendChild(element("td", money || index === 3 ? "" : value, money ? "numeric" : ""));
      if (money) td.appendChild(amount(value, {signed: !record.items}));  // Statement rows carry a direction; item prices don't.
      if (record.items && index === 4 && paid !== "—") td.append(element("small", "with tax", "muted block"));
      if (index === 3) td.appendChild(categories.length ? itemCategorySelect(record.id, row, categories, onSaved)
                                                        : document.createTextNode(row.category ? categoryLabel(row.category) : "—"));
    });
    const cell = row.cell_evidence?.line_total || row.cell_evidence?.amount;
    const sourceIds = cell?.source === "pdf_text" ? [cell.cell_id] : row.line_ids;
    const source = document.createElement("td"); if (sourceIds?.length) source.appendChild(sourceButton(sourceIds, find)); tr.appendChild(source);
    body.appendChild(tr);
  }
  if (record.items) {
    const foot = table.appendChild(element("tfoot"));
    for (const [label, field] of [["Subtotal", "subtotal"], ["Tax", "tax"], ["Tip", "tip"], ["Not matched to an item", "unmatched"], ["Total", "total"]]) {
      if (field === "unmatched" && !record.unmatched_minor) continue;
      const tr = element("tr"), name = element("th", label); name.scope = "row"; name.colSpan = codes ? 2 : 1;
      // A receipt paid partly by gift card: its printed total here, what was paid in its Paid line (document_v2.js doc2Paid).
      const shown = field === "total" && record.paid_summary ? record.printed_total?.display : record.display[`${field}_minor`];
      const value = element("td", "", "numeric"); value.append(amount(shown || "—", {signed: false}));
      const actions = element("td"); actions.colSpan = shares ? 3 : 2;
      if (correctField && field !== "unmatched") {
        const button = element("button", "Correct", "link-button"); button.type = "button"; button.setAttribute("aria-label", `Correct ${field}`);
        button.addEventListener("click", () => correctField(field)); actions.append(button);
      }
      tr.append(name, value, actions); foot.append(tr);
    }
  }
  wrap.appendChild(table);
  if (record.totals_mismatch) wrap.append(element("p", "Doesn't add up: subtotal + tax + tip differs from total by more than one cent.", "item-warning"));
  if (rows.length > 200) wrap.appendChild(element("p", `Showing 200 of ${rows.length} rows.`, "muted"));
  if (record.splits?.length) {
    // What this receipt counts as, by category, and whether a statement line confirms it.
    const split = element("p", "", "receipt-splits small");
    split.append(element("strong", "By category: "), document.createTextNode(record.splits.map(row => `${categoryLabel(row.category)} ${row.display.amount_minor}`).join(" · ")),
                 document.createTextNode(" "), statusBadge(record.reconciled ? "reconciled" : "receipt"));
    wrap.appendChild(split);
  }
  return wrap;
}
async function renderAssetRecord(target, publication) {
  // Investment and loan statements feed the forecast's assets; their values wait for review (docs/planning.md "Assets and loans").
  const asset = (await api("/api/assets?include_archived=true")).find(row => row.id === publication.id);
  // Investment values recorded before they had their own page moved there, keeping the old asset's number.
  if (!asset) { await renderInvestmentRecord(target, publication, `/api/investments/valuations/by-asset/${publication.id}`); return; }
  const heading = element("div", "", "ledger-record-heading");
  heading.append(element("strong", asset.name), statusBadge(asset.review_status));
  const facts = element("dl", "", "detail-list");
  for (const [label, value] of [[asset.kind === "loan" ? "Amount owed" : "Value", asset.value.display], ["As of", dateText(asset.as_of)],
                                ...(asset.kind === "loan" ? [["Yearly rate", `${asset.annual_rate_percent}%`], ["Monthly payment", asset.monthly_payment?.display || "Not printed"]] : [])]) {
    facts.append(element("dt", label), element("dd", value));
  }
  const notes = [];
  if (publication.status === "kept_newer") notes.push(element("p", "A newer statement for this account is already recorded, so this one didn't change it.", "muted"));
  if (publication.status === "kept_reviewed") notes.push(element("p", "You already reviewed this value, so the new extraction did not change it.", "muted"));
  for (const issue of asset.issues) notes.push(element("p", issue, "item-warning"));
  const next = asset.review_status === "proposed" ? homeLink("Confirm it in Review", "#/review") : homeLink("See it in Forecast", "#/forecast");
  target.replaceChildren(heading, facts, ...notes, element("p", "Statement values count in your forecast once you confirm them.", "muted small"), next);
}
async function renderInvestmentRecord(target, publication, path) {
  // An investment statement's value for its account (docs/planning.md "Investments"); it waits for review like other statement values.
  let valuation;
  try { valuation = await api(path); } catch { target.replaceChildren(element("p", "The value recorded from this statement was removed.", "muted")); return; }
  const heading = element("div", "", "ledger-record-heading");
  heading.append(element("strong", valuation.account.name), statusBadge(valuation.review_status));
  const facts = element("dl", "", "detail-list");
  for (const [label, value] of [["Kind", valuation.account.kind_label], ["Value", valuation.value.display], ["As of", dateText(valuation.as_of)],
                                ...(valuation.holding_count ? [["Holdings", String(valuation.holding_count)]] : []),
                                ...(valuation.activity_count ? [["Activity entries", String(valuation.activity_count)]] : [])]) {
    facts.append(element("dt", label), element("dd", value));
  }
  const notes = [];
  if (publication.status === "history") notes.push(element("p", "A newer statement for this account is already recorded, so this one is kept as history.", "muted"));
  if (publication.status === "kept_newer") notes.push(element("p", "A newer statement for this account is already recorded, so this one didn't change it.", "muted"));
  if (publication.status === "kept_reviewed") notes.push(element("p", "You already reviewed this value, so the new extraction did not change it.", "muted"));
  for (const issue of valuation.issues) notes.push(element("p", issue, "item-warning"));
  const next = valuation.review_status === "proposed" ? homeLink("Confirm it in Review", "#/review") : homeLink("See it in Investments", `#/investments?account=${valuation.account.id}`);
  target.replaceChildren(heading, facts, ...notes, element("p", "Statement values count once you confirm them.", "muted small"), next);
}
async function renderConfirmationRecord(target, publication) {
  // A trade, CD or Treasury purchase confirmation (docs/planning.md "Purchase confirmations, estimates and maturities"); it waits for review like statement values.
  let confirmation;
  try { confirmation = await api(`/api/investments/confirmations/${publication.id}`); } catch { target.replaceChildren(element("p", "The purchase recorded from this confirmation was removed.", "muted")); return; }
  const heading = element("div", "", "ledger-record-heading");
  heading.append(element("strong", confirmation.account.name), statusBadge(confirmation.review_status));
  const facts = element("dl", "", "detail-list");
  facts.append(element("dt", "Kind"), element("dd", confirmation.account.kind_label), element("dt", "Traded"), element("dd", dateText(confirmation.trade_date)));
  for (const trade of confirmation.trades) {
    const terms = [trade.amount.display, trade.rate_percent != null ? `${trade.rate_percent}%` : "", trade.maturity_date ? `matures ${dateText(trade.maturity_date)}` : ""].filter(Boolean);
    facts.append(element("dt", `${trade.type_label} ${trade.name}`), element("dd", terms.join(" · ")));
  }
  const notes = [];
  if (publication.status === "kept_reviewed") notes.push(element("p", "You already reviewed this confirmation, so the new extraction did not change it.", "muted"));
  for (const issue of confirmation.issues) notes.push(element("p", issue, "item-warning"));
  const next = confirmation.review_status === "proposed" ? homeLink("Confirm it in Review", "#/review") : homeLink("See it in Investments", `#/investments?account=${confirmation.account.id}`);
  target.replaceChildren(heading, facts, ...notes, element("p", "Purchases count once you confirm them.", "muted small"), next);
}
async function renderTaxFormRecord(target, publication) {
  // A 1099 or 5498 (docs/planning.md "Tax lots, gains and tax forms"): its boxes, checked against the account's records in Investments → Taxes.
  let form;
  try { form = await api(`/api/investments/tax-forms/${publication.id}`); } catch { target.replaceChildren(element("p", "The tax form recorded from this document was removed.", "muted")); return; }
  const heading = element("div", "", "ledger-record-heading");
  heading.append(element("strong", form.name), statusBadge(form.review_status));
  const facts = element("dl", "", "detail-list");
  facts.append(element("dt", "Account"), element("dd", form.account_name || "No account here matches it"));
  for (const box of form.boxes) facts.append(element("dt", `${box.form} box ${box.box}: ${box.label}`), element("dd", box.amount.display));
  const notes = [];
  if (publication.status === "kept_reviewed") notes.push(element("p", "You already reviewed this form, so the new extraction did not change it.", "muted"));
  for (const issue of form.issues) notes.push(element("p", issue, "item-warning"));
  const next = form.review_status === "proposed" ? homeLink("Confirm it in Review", "#/review") : homeLink("Compare it in Investments", `#/investments?year=${form.tax_year}`);
  target.replaceChildren(heading, facts, ...notes, next);
}

// Pay stubs (docs/taxes.md "Jobs and pay stubs"): gross to net, then how the taxes were figured. Every amount is the server's text.
function paystubRow(body, cells, className = "", lineIds = null, find = null) {
  const tr = body.insertRow(); if (className) tr.className = className;
  cells.forEach((value, index) => {
    const td = tr.appendChild(element(index ? "td" : "th", index ? "" : value, index ? "numeric" : ""));
    if (!index) td.scope = "row"; else td.appendChild(amount(value || "—", {signed: false}));
  });
  const source = tr.insertCell(); if (lineIds?.length) source.appendChild(sourceButton(lineIds, find));
  if (lineIds?.length) tr.dataset.lines = lineIds.join(" ");
  return tr;
}
function paystubBreakdown(record, find, onChange = null) {
  const {groups, checks} = record.breakdown;
  if (!record.lines.length) return [element("p", "The stub's individual lines weren't read, so only its totals are shown.", "muted")];
  const section = element("section", "", "paystub-breakdown");
  section.appendChild(element("h3", "From gross pay to net pay"));
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "ledger-rows paystub-table");
  const head = table.createTHead().insertRow();
  for (const [title, numeric] of [["", false], ["This period", true], ["Year to date", true], ["", false]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
  const byGroup = Object.fromEntries(groups.map(group => [group.group, group]));
  const total = (group, label) => byGroup[group] && paystubRow(body, [label, byGroup[group].display?.current_minor, byGroup[group].display?.ytd_minor], "paystub-subtotal");
  let body;
  for (const group of groups) {
    body = table.appendChild(document.createElement("tbody"));
    const title = body.insertRow().appendChild(element("th", group.title, "paystub-group")); title.colSpan = 4; title.scope = "rowgroup";
    for (const line of group.lines) {
      const tr = paystubRow(body, [line.description, line.display.current_minor, line.display.ytd_minor], "", line.line_ids, find);
      for (const [index, name] of [[1, "current"], [2, "ytd"]]) {
        const cell = line.cell_evidence?.[name];
        if (cell) {
          tr.children[index].dataset.sourceCellId = cell.cell_id;
          tr.children[index].title = `Reported source cell: ${cell.quote} (${cell.line_id})`;
          if (cell.source === "pdf_text") {
            const source = element("button", tr.children[index].textContent, "link-button"); source.type = "button";
            source.setAttribute("aria-label", `Find ${line.description} ${name === "current" ? "this period" : "year to date"} on the PDF`);
            source.addEventListener("click", () => find([cell.cell_id])); tr.children[index].replaceChildren(source);
          }
        }
      }
      if (onChange && record.review_status !== "rejected") {
        const edit = element("button", "Correct", "link-button"); edit.type = "button";
        edit.setAttribute("aria-label", `Correct ${line.description}`); edit.setAttribute("aria-expanded", "false");
        edit.addEventListener("click", () => {
          const shown = tr.nextElementSibling?.classList.contains("doc2-row-form");
          table.querySelectorAll(".doc2-row-form").forEach(node => node.remove());
          table.querySelectorAll("button[aria-expanded]").forEach(node => node.setAttribute("aria-expanded", "false"));
          if (shown) return;
          const formRow = element("tr", "", "doc2-row-form"), cell = element("td"); cell.colSpan = tr.children.length;
          const cc = confirmCorrect({recordType: "income_record", recordId: record.id, decision: false, preview: false,
            correctable: line.correctable, onChange, onClose: () => { formRow.remove(); edit.setAttribute("aria-expanded", "false"); edit.focus(); },
            saveCorrection: body => api(`/api/paystubs/${record.id}/lines/${line.position}`, {method: "PATCH", body: JSON.stringify(body)})});
          cc.el.querySelector(".cc-actions").hidden = true;
          cell.append(cc.el); formRow.append(cell); tr.after(formRow);
          edit.setAttribute("aria-expanded", "true"); cc.openCorrect();
        });
        tr.lastElementChild.append(edit);
      }
    }
    if (group.group === "earnings") paystubRow(body, ["Gross pay", record.display.gross_pay_minor, record.display.gross_pay_ytd_minor], "paystub-total");
    if (group.group === "pre_tax") total("pre_tax", "Total pre-tax deductions");
    if (group.group === "tax") {
      if (group.fica) paystubRow(body, ["FICA (Social Security + Medicare)", group.fica.display?.current_minor, group.fica.display?.ytd_minor], "paystub-subtotal");
      total("tax", "Total taxes");
    }
    if (group.group === "post_tax") total("post_tax", "Total post-tax deductions");
    if (group.group === (byGroup.post_tax ? "post_tax" : byGroup.tax ? "tax" : byGroup.pre_tax ? "pre_tax" : "earnings"))
      paystubRow(body, ["Net pay", record.display.net_pay_minor, record.display.net_pay_ytd_minor], "paystub-total");
    if (group.group === "employer_paid") total("employer_paid", "Total paid by your employer");
  }
  wrap.appendChild(table); section.appendChild(wrap);
  for (const check of checks) {
    section.appendChild(check.matches
      ? element("p", `${check.label}: gross pay ${check.display.gross_minor} less ${check.display.taken_minor} of deductions and taxes is the printed net pay, ${check.display.net_minor}.`, "muted small")
      : element("p", `${check.label}: gross pay less deductions and taxes is ${check.display.computed_net_minor}, but the stub prints ${check.display.net_minor} (a difference of ${check.display.difference_minor}). A line may be missing or misread.`, "item-warning"));
  }
  return [section];
}
function withholdingSection(record) {
  const plan = record.withholding;
  const section = element("section", "", "paystub-taxes");
  section.appendChild(element("h3", "How your taxes were figured"));
  if (!plan.year || !record.lines.length) { section.append(...plan.notes.map(note => element("p", note, "muted"))); return [section]; }
  const settings = element("p", `Tax year ${plan.year} · filing ${plan.filing_status_name} · ${plan.paychecks ? `${plan.paychecks} paychecks a year` : "pay frequency unknown"}. `, "muted small");
  settings.appendChild(homeLink("Change filing status", "#/settings"));
  // What If: start a planned paycheck from this one, e.g. to drop a new job's one-time onboarding lines.
  settings.append(" · ", homeLink("Plan a paycheck from this stub", `#/whatif?stub=${record.id}`));
  section.appendChild(settings);
  if (plan.display?.income_tax_wages_minor)
    section.appendChild(element("p", `Taxable wages this paycheck: ${plan.display.income_tax_wages_minor} for income tax (gross pay less pre-tax deductions such as 401(k) and health), `
      + `${plan.display.fica_wages_minor} for Social Security and Medicare (a 401(k) doesn't lower these).`));
  for (const part of plan.jurisdictions) {
    const block = element("div", "", "tax-jurisdiction");
    block.appendChild(element("h4", `${part.name} income tax`));
    if (part.status !== "verified") {
      block.appendChild(element("p", part.message, "muted"));
      if (part.status === "missing") block.appendChild(asyncButton(`Look up the ${plan.year} ${part.name} table`, () =>
        api("/api/tax-tables/lookup", {method: "POST", body: JSON.stringify({jurisdiction: part.jurisdiction, year: plan.year})})
          .then(() => notice("Looking it up. The table will wait for you in Review.")), ""));
      if (part.status === "proposed") block.appendChild(homeLink("Review the table", "#/review"));
      if (part.display?.actual_minor) block.appendChild(element("p", `Withheld this paycheck: ${part.display.actual_minor}.`, "muted small"));
      section.appendChild(block); continue;
    }
    const d = part.display;
    block.appendChild(element("p", `Over ${plan.paychecks} paychecks, ${d.period_wages_minor} a paycheck is ${d.annual_wages_minor} a year. The first `
      + `${d.standard_deduction_minor} (the standard deduction, ${d.standard_deduction_per_paycheck_minor} of each paycheck) isn't taxed; each bucket above it is taxed only at its own rate.`));
    if (part.chart_svg) { const figure = element("figure", "", "tax-chart"); figure.appendChild(forecastSvg(part.chart_svg)); block.appendChild(figure); }
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
    const head = table.createTHead().insertRow();
    for (const [title, numeric] of [["Bucket", false], ["Wages a year", true], ["Tax a year", true], ["Tax a paycheck", true]]) {
      const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col";
    }
    const body = table.createTBody();
    for (const bucket of part.buckets) {
      const tr = body.insertRow();
      const range = bucket.display.to_minor ? `${bucket.display.from_minor} to ${bucket.display.to_minor}` : `over ${bucket.display.from_minor}`;
      const th = tr.appendChild(element("th", bucket.label)); th.scope = "row";
      th.appendChild(element("small", `wages ${range}`, "muted"));
      for (const key of ["income_minor", "tax_minor", "per_paycheck_tax_minor"]) tr.appendChild(element("td", "", "numeric")).appendChild(amount(bucket.display[key], {signed: false}));
    }
    wrap.appendChild(table); block.appendChild(wrap);
    block.appendChild(element("p", `A year's tax: ${d.annual_tax_minor} (${part.effective_rate_percent}% of wages; your top bucket is ${part.top_rate_percent}%). `
      + `Spread over ${plan.paychecks} paychecks: about ${d.estimate_minor}. Withheld: ${d.actual_minor || "not on this stub"}`
      + (part.difference_word ? `, ${part.difference_word} than the estimate by ${d.difference_size_minor}.` : ".")));
    const sources = element("p", "Table: ", "muted small");
    // Addresses the model read from the web are shown as text, never live links (docs/ui.md "Conventions").
    part.sources.forEach((source, index) => sources.append(index ? ", " : "", ...(source.title ? [`${source.title} `] : []), element("span", source.url, "mono")));
    if (part.sources.length) block.appendChild(sources);
    section.appendChild(block);
  }
  if (plan.fica.length) {
    const block = element("div", "", "tax-jurisdiction");
    block.appendChild(element("h4", "Social Security and Medicare (FICA)"));
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
    const head = table.createTHead().insertRow();
    for (const [title, numeric] of [["", false], ["Wages", true], ["Estimated", true], ["Withheld", true], ["Difference", true]]) { const th = head.appendChild(element("th", title, numeric ? "numeric" : "")); th.scope = "col"; }
    const body = table.createTBody();
    for (const row of plan.fica) {
      const tr = body.insertRow(); const th = tr.appendChild(element("th", row.name)); th.scope = "row";
      th.appendChild(element("small", `${row.rate_percent}%${row.additional_wages_minor ? ` + ${row.additional_rate_percent}%` : ""} of wages`, "muted"));
      for (const key of ["wages_minor", "estimate_minor", "actual_minor", "difference_minor"]) tr.appendChild(element("td", "", "numeric")).appendChild(amount(row.display[key] || "—", {signed: key === "difference_minor"}));
    }
    wrap.appendChild(table); block.appendChild(wrap);
    const capped = plan.fica.find(row => row.name === "Social Security" && row.display.limit_minor);
    if (capped) block.appendChild(element("p", `Social Security stops once the year's wages reach ${capped.display.limit_minor}.`, "muted small"));
    section.appendChild(block);
  }
  for (const note of plan.notes) section.appendChild(element("p", note, "muted small"));
  return [section];
}
