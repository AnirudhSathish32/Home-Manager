"use strict";
// To check's shared parts (review_v2.js draws the page; docs/ui.md "Review"): the queue's data and titles, the sidebar
// counts, summaries of records, and the item dialog.
const ISSUE_KINDS = {ambiguous_receipt_match: "Which charge is this receipt?", ambiguous_transfer: "Which account received this transfer?",
                     ambiguous_refund: "Which purchase was refunded?", ambiguous_investment_transfer: "Which payment went into this investment?",
                     family_correction: "Your family changed something you changed too"};
const LINK_KINDS = {receipt: "Does this receipt match this charge?", transfer: "Is this a transfer between your accounts?", refund: "Is this a refund of that purchase?"};
const ITEM_CATEGORIES = ["produce", "dairy & eggs", "meat & seafood", "bakery", "pantry", "frozen", "snacks", "beverages", "household cleaning",
                         "paper & disposables", "personal care", "health", "baby", "pet", "home maintenance", "other"];
const REVIEW_GROUPS = [["issue", "Questions"], ["link", "Proposed matches"], ["record", "Records to verify"], ["asset", "Investment and loan documents to confirm"], ["warranty", "Warranties to confirm"],
                       ["tax_table", "Tax tables to confirm"], ["tax_tag", "Possible write-offs and tax payments"], ["recurring", "Recurring payments"],
                       ["item", "Receipt items to identify"]];
const STATEMENT_ASSET_LABELS = {loan: "Loan"};

// Loan balances (assets) and investment values (investments.js) read from statements share one review group.
const proposedAssets = (assets, investments = []) => [
  ...assets.filter(asset => asset.source === "statement" && asset.review_status === "proposed").map(value => ({kind: "asset", id: value.id, value})),
  // Investment statement values and purchase confirmations; the server names each one's review path.
  ...investments.map(value => ({kind: "asset", id: `${value.record_type}-${value.id}`, value}))];
// The badge and each group's count come from the server (/api/review/counts), uncapped, so they always agree.
function showReviewCounts(counts) {
  setNavCount($("nav-review-count"), counts.total, "need review");
  if (counts.checkin != null) setNavCount($("nav-checkin-count"), counts.checkin, "to check in");
}
async function loadNavCounts() {
  showReviewCounts(await api("/api/review/counts"));
}

function reviewKey(item) { return `${item.kind}:${item.id}`; }
// Everything awaiting a decision, as one list of {kind, id, value} in REVIEW_GROUPS order (review_v2.js draws it).
async function reviewData() {
  const [queue, recurring, resolutions, catalog, unmatched, assets, warranties, {tables: taxTables}, investments, {tags: taxTags}, counts] = await Promise.all([
    tool("review_queue"), tool("get_recurring_obligations"),
    api("/api/items/resolutions?status=proposed&limit=200"), api("/api/folders"), tool("get_unmatched_receipts", {start: "1900-01-01", end: todayIso()}),
    api("/api/assets"), api("/api/warranties?status=proposed"), api("/api/tax-tables?status=proposed"), api("/api/investments/review"),
    api("/api/tax-tags?status=proposed"), api("/api/review/counts")]);
  const items = [...queue.issues.map(value => ({kind: "issue", id: value.id, value})), ...queue.links.map(value => ({kind: "link", id: `${value.kind}-${value.id}`, value})),
                 ...queue.records.map(value => ({kind: "record", id: `${value.record_type}-${value.id}`, value})),
                 ...proposedAssets(assets, investments),
                 ...warranties.map(value => ({kind: "warranty", id: value.id, value})),
                 ...taxTables.map(value => ({kind: "tax_table", id: value.id, value})),
                 ...taxTags.map(value => ({kind: "tax_tag", id: value.id, value})),
                 ...recurring.obligations.filter(row => row.status === "proposed").map(value => ({kind: "recurring", id: value.id, value})),
                 ...resolutions.map(value => ({kind: "item", id: value.id, value}))];
  return {items, catalog, unmatched, counts};
}
function reviewTitle(item) {
  const value = item.value;
  if (item.kind === "issue") return ISSUE_KINDS[value.issue_type] || statusLabel(value.issue_type);
  if (item.kind === "link") return describe(value.to);
  if (item.kind === "record") return `${value.summary?.sale_label || RECORD_KINDS[value.record_type]}: ${value.summary?.name || "name not found"}`;
  if (item.kind === "recurring") return `${value.merchant} · ${value.expected_amount.display} ${value.frequency}`;
  if (item.kind === "asset") return value.name;
  if (item.kind === "warranty") return `Warranty: ${[value.brand, value.name].filter(Boolean).join(" ")}`;
  if (item.kind === "tax_table") return `${value.year} ${value.name} income tax table`;
  if (item.kind === "tax_tag") return `${value.target.description} · ${value.line_label}`;
  return value.line.description;
}
function summaryBlock(label, summary, {link = true} = {}) {
  const box = element("div", "", "review-side");
  box.append(element("span", label, "figure-label"), element("strong", summary?.name || summary?.description || RECORD_KINDS[summary?.record_type] || "Record", "block"),
             ...saleBadges(summary));
  // Only a transaction's sign means money in or out; a receipt or bill total is shown as printed (a return's is negative).
  if (summary?.amount) box.append(amount(summary.amount, {signed: summary.record_type === "transaction"}));
  box.append(element("span", [summary?.date && dateText(summary.date), summary?.account].filter(Boolean).join(" · "), "muted small block"));
  if (link && summary?.document_id) box.append(homeLink("Open document", `#/documents/${summary.document_id}`));
  return box;
}
// A statement value, purchase confirmation or tax form (To check's asset kind, review_v2.js review2Parts): why it waits,
// its evidence and the confirm button's label. The decision itself is To check's.
function assetParts(item) {
  const value = item.value;
  if (value.record_type === "tax_form") {
    // A 1099 or 5498: its boxes, which Investments → Taxes compares with what is recorded for the account.
    const box = element("div", "", "review-side");
    box.append(element("span", `Tax form · ${value.tax_year}`, "figure-label"), element("strong", value.name, "block"),
               element("span", value.account_name ? `For ${value.account_name}` : "No investment account here matches it; it is kept on its own.", "muted small block"));
    const boxes = element("ul", "", "finance-list");
    for (const row of value.boxes) {
      const li = document.createElement("li");
      li.append(element("span", `${row.form} box ${row.box}: ${row.label} `), amount(row.amount, {signed: false}));
      boxes.append(li);
    }
    box.append(boxes);
    const issues = element("ul", "", "review-issues");
    for (const issue of value.issues) issues.append(element("li", issue, "item-warning"));
    return {why: "Read from a tax form. Once you confirm it, Investments compares its boxes with the interest, dividends, sales and contributions recorded for the account.",
            evidence: [issues, box], confirmLabel: "Confirm form"};
  }
  if (value.record_type === "investment_confirmation") {
    // A trade, CD or Treasury purchase: what was bought or sold, with the terms its value will be estimated from.
    const box = element("div", "", "review-side");
    box.append(element("span", `${value.kind_label} · purchase confirmation`, "figure-label"), element("strong", value.name, "block"),
               element("span", `Traded ${dateText(value.trade_date)}`, "muted small block"));
    const trades = element("ul", "", "finance-list");
    for (const trade of value.trades) {
      const terms = [trade.rate_percent != null ? `${trade.rate_percent}%` : "", trade.face ? `face ${trade.face.display}` : "",
                     trade.maturity_date ? `matures ${dateText(trade.maturity_date)}` : "", trade.quantity ? `${trade.quantity} shares` : ""].filter(Boolean).join(" · ");
      const li = document.createElement("li");
      li.append(element("strong", `${trade.type_label} ${trade.name}`), document.createTextNode(" "), amount(trade.amount, {signed: false}));
      if (terms) li.append(element("small", terms, "muted block"));
      trades.append(li);
    }
    box.append(trades, homeLink("Wrong kind of account? Change it in Investments", `#/investments?account=${value.account_id}`));
    const issues = element("ul", "", "review-issues");
    for (const issue of value.issues) issues.append(element("li", issue, "item-warning"));
    return {why: "Read from a purchase confirmation. Its trades are recorded, and CDs and Treasuries count at their estimated value, only after you confirm it.",
            evidence: [issues, box], confirmLabel: "Confirm purchase"};
  }
  const box = element("div", "", "review-side");
  box.append(element("span", value.kind_label || STATEMENT_ASSET_LABELS[value.kind] || statusLabel(value.kind), "figure-label"), element("strong", value.name, "block"),
             amount(value.value, {signed: false}), element("span", `${value.kind === "loan" ? "Owed" : "Value"} as of ${dateText(value.as_of)}`, "muted small block"));
  if (value.kind === "loan") box.append(element("span", `Rate ${value.annual_rate_percent}% a year${value.monthly_payment ? ` · payment ${value.monthly_payment.display} a month` : ""}`, "muted small block"));
  const issues = element("ul", "", "review-issues");
  for (const issue of value.issues) issues.append(element("li", issue, "item-warning"));
  if (value.holding_count || value.activity_count) {
    const listed = [value.holding_count ? `${value.holding_count} holding${value.holding_count === 1 ? "" : "s"}` : "",
                    value.activity_count ? `${value.activity_count} activity entr${value.activity_count === 1 ? "y" : "ies"}` : ""].filter(Boolean).join(" and ");
    box.append(element("span", `The statement also lists ${listed}; your decision applies to them too.`, "muted small block"));
  }
  if (value.review_path) box.append(homeLink("Wrong kind of account? Change it in Investments", `#/investments?account=${value.account_id}`));
  return {why: "Read from a statement. Statement values count in your forecast only after you confirm them.",
          evidence: [issues, box], confirmLabel: "Confirm value"};
}

// Approve an item resolution with the user's corrections.
let editingResolution = null, itemDialogDone = null;
$("item-category").replaceChildren(...ITEM_CATEGORIES.map(name => new Option(name)));
function openItemDialog(resolution, onDone) {
  editingResolution = resolution; itemDialogDone = onDone;
  $("item-dialog-line").textContent = `Printed: ${resolution.line.description}${resolution.line.merchant ? ` at ${resolution.line.merchant}` : ""}`;
  $("item-name").value = resolution.name; $("item-brand").value = resolution.brand || ""; $("item-size").value = resolution.size_text || "";
  $("item-category").value = resolution.category; $("item-consumable").checked = resolution.consumable; $("item-dialog-error").textContent = "";
  $("item-dialog").showModal(); $("item-name").focus();
}
$("cancel-item").addEventListener("click", () => $("item-dialog").close());
$("item-form").addEventListener("submit", async event => {
  event.preventDefault();
  const edits = {name: $("item-name").value.trim(), brand: $("item-brand").value.trim() || null, size_text: $("item-size").value.trim() || null,
                 category: $("item-category").value, consumable: $("item-consumable").checked, barcode: editingResolution.barcode || null};
  try {
    await api(`/api/items/resolutions/${editingResolution.id}/review`, {method: "POST", body: JSON.stringify({status: "verified", edits})});
    $("item-dialog").close(); notice("Approved with your changes; the item joined your inventory."); await itemDialogDone();
  } catch (error) { $("item-dialog-error").textContent = error.message; }
});
