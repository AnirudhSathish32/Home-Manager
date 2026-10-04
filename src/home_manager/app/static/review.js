"use strict";
// Review (docs/ui-design-plan.md §3.2, Phase D): one queue of everything awaiting a decision.
// Left: groups with counts. Right: what the item is, why it needs you, the evidence and the decision.
// Keys: J/K move, V confirms, R rejects; a decision advances to the next item.
const ISSUE_KINDS = {ambiguous_receipt_match: "Which charge is this receipt?", ambiguous_transfer: "Which account received this transfer?",
                     ambiguous_refund: "Which purchase was refunded?", ambiguous_investment_transfer: "Which payment went into this investment?"};
const LINK_KINDS = {receipt: "Does this receipt match this charge?", transfer: "Is this a transfer between your accounts?", refund: "Is this a refund of that purchase?"};
const ITEM_CATEGORIES = ["produce", "dairy & eggs", "meat & seafood", "bakery", "pantry", "frozen", "snacks", "beverages", "household cleaning",
                         "paper & disposables", "personal care", "health", "baby", "pet", "home maintenance", "other"];
const REVIEW_GROUPS = [["issue", "Questions"], ["link", "Proposed matches"], ["record", "Records to verify"], ["asset", "Investment and loan documents to confirm"], ["warranty", "Warranties to confirm"],
                       ["tax_table", "Tax tables to confirm"], ["tax_tag", "Possible write-offs and tax payments"], ["recurring", "Recurring payments"],
                       ["item", "Receipt items to identify"]];
const STATEMENT_ASSET_LABELS = {loan: "Loan"};
let reviewItems = [], reviewIndex = 0, reviewLoad = 0, reviewThumb = null;

// Loan balances (assets) and investment values (investments.js) read from statements share one review group.
const proposedAssets = (assets, investments = []) => [
  ...assets.filter(asset => asset.source === "statement" && asset.review_status === "proposed").map(value => ({kind: "asset", id: value.id, value})),
  // Investment statement values and purchase confirmations; the server names each one's review path.
  ...investments.map(value => ({kind: "asset", id: `${value.record_type}-${value.id}`, value}))];
function reviewCount(queue, recurring, items, assets, warranties = [], taxTables = [], investments = [], taxTags = []) {
  return queue.records.length + queue.links.length + queue.issues.length + recurring.obligations.filter(row => row.status === "proposed").length
    + items.length + proposedAssets(assets, investments).length + warranties.length + taxTables.length + taxTags.length;
}
async function loadNavCounts() {
  const [queue, recurring, items, assets, checkin, warranties, taxTables, investments, taxTags] = await Promise.all([tool("review_queue"), tool("get_recurring_obligations"),
    api("/api/items/resolutions?status=proposed&limit=1000"), api("/api/assets"), api("/api/inventory/checkin").catch(() => null), api("/api/warranties?status=proposed"),
    api("/api/tax-tables?status=proposed"), api("/api/investments/review"), api("/api/tax-tags?status=proposed")]);
  setNavCount($("nav-review-count"), reviewCount(queue, recurring, items, assets, warranties, taxTables.tables, investments, taxTags.tags), "need review");
  if (checkin) setNavCount($("nav-checkin-count"), checkin.lots.length + checkin.waiting, "to check in");
}

function reviewKey(item) { return `${item.kind}:${item.id}`; }
// Images that look like pages of one document (documents/grouping.py): combined only when the user says so.
async function loadGroupSuggestions() {
  const groups = await api("/api/document-groups");
  $("group-suggestions-panel").hidden = !groups.length;
  $("group-suggestions").replaceChildren(...groups.map(group => {
    const item = element("li", "", "routing-item"), pages = element("ol", "", "group-pages");
    for (const page of group.pages) {
      const entry = document.createElement("li"), link = element("a", page.relative_path.split("/").pop());
      link.href = `#/documents/${page.document_id}`;
      entry.append(link); pages.append(entry);
    }
    const decide = async status => {
      await api(`/api/document-groups/${group.id}`, {method: "PATCH", body: JSON.stringify({status})});
      notice(status === "confirmed" ? "Combined. The images are read as one document's pages; progress shows in the sidebar." : "Kept as separate documents.");
      await loadGroupSuggestions();
    };
    const actions = element("div", "", "button-row");
    actions.append(asyncButton(`Combine ${group.pages.length} images`, () => decide("confirmed"), "primary"), asyncButton("Keep separate", () => decide("dismissed")));
    item.append(element("p", group.reason, "muted small"), pages, actions);
    return item;
  }));
}
async function loadReview(keep = true) {
  if (!configured) { $("review-detail").replaceChildren(emptyState("Set up your library to review records.")); return; }
  // The family's inbox is sent to people, not reconciled against cards: unmatched receipts belong to each person's Review.
  $("family-routing-panel").hidden = !familyMode; $("review-unmatched-panel").hidden = familyMode;
  if (familyMode) loadFamilyRouting().catch(error => notice(error, true));  // Loads on its own beside the review queue.
  else loadGroupSuggestions().catch(error => notice(error, true));
  const load = ++reviewLoad, previous = reviewItems[reviewIndex] ? reviewKey(reviewItems[reviewIndex]) : null;
  $("review-status").textContent = "Loading…";
  let queue, recurring, items, catalog, unmatched, assets, warranties, taxTables, investments, taxTags;
  try {
    [queue, recurring, items, catalog, unmatched, assets, warranties, {tables: taxTables}, investments, {tags: taxTags}] = await Promise.all([
      tool("review_queue"), tool("get_recurring_obligations"),
      api("/api/items/resolutions?status=proposed&limit=200"), api("/api/folders"), tool("get_unmatched_receipts", {start: "1900-01-01", end: todayIso()}),
      api("/api/assets"), api("/api/warranties?status=proposed"), api("/api/tax-tables?status=proposed"), api("/api/investments/review"),
      api("/api/tax-tags?status=proposed")]);
  } catch (error) {
    if (load === reviewLoad) { $("review-status").textContent = ""; $("review-detail").replaceChildren(alertBox(`Couldn't load the review queue. ${error.message}`, {tone: "error", action: asyncButton("Retry", () => loadReview())})); }
    return;
  }
  if (load !== reviewLoad) return;
  reviewItems = [...queue.issues.map(value => ({kind: "issue", id: value.id, value})), ...queue.links.map(value => ({kind: "link", id: `${value.kind}-${value.id}`, value})),
                 ...queue.records.map(value => ({kind: "record", id: `${value.record_type}-${value.id}`, value})),
                 ...proposedAssets(assets, investments),
                 ...warranties.map(value => ({kind: "warranty", id: value.id, value})),
                 ...taxTables.map(value => ({kind: "tax_table", id: value.id, value})),
                 ...taxTags.map(value => ({kind: "tax_tag", id: value.id, value})),
                 ...recurring.obligations.filter(row => row.status === "proposed").map(value => ({kind: "recurring", id: value.id, value})),
                 ...items.map(value => ({kind: "item", id: value.id, value}))];
  const kept = keep && previous ? reviewItems.findIndex(item => reviewKey(item) === previous) : -1;
  reviewIndex = kept >= 0 ? kept : Math.min(reviewIndex, Math.max(0, reviewItems.length - 1));
  $("review-status").textContent = reviewItems.length ? `${reviewItems.length} item${reviewItems.length === 1 ? "" : "s"} need you · checked ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}` : "";
  renderReviewQueue(catalog);
  renderReviewDetail();
  renderUnmatched(unmatched);
  setNavCount($("nav-review-count"), reviewCount(queue, recurring, items, assets, warranties, taxTables, investments, taxTags), "need review");
}
function reviewTitle(item) {
  const value = item.value;
  if (item.kind === "issue") return ISSUE_KINDS[value.issue_type] || statusLabel(value.issue_type);
  if (item.kind === "link") return describe(value.to);
  if (item.kind === "record") return `${RECORD_KINDS[value.record_type]}: ${value.summary?.name || "name not found"}`;
  if (item.kind === "recurring") return `${value.merchant} · ${value.expected_amount.display} ${value.frequency}`;
  if (item.kind === "asset") return value.name;
  if (item.kind === "warranty") return `Warranty: ${[value.brand, value.name].filter(Boolean).join(" ")}`;
  if (item.kind === "tax_table") return `${value.year} ${value.name} income tax table`;
  if (item.kind === "tax_tag") return `${value.target.description} · ${value.line_label}`;
  return value.line.description;
}
function renderReviewQueue(catalog) {
  const nav = $("review-queue"), nodes = [];
  const other = [];
  if (catalog.work?.failed) other.push(homeLink(`${catalog.work.failed} documents couldn't be processed`, "#/documents?status=failed"));
  if (catalog.counts?.Unfiled) {
    const unfiled = element("button", `${catalog.counts.Unfiled} unfiled documents`, "link-button"); unfiled.type = "button";
    unfiled.addEventListener("click", () => showFolder("Unfiled")); other.push(unfiled);
  }
  if (other.length) { const box = element("div", "", "review-other"); box.append(...other); nodes.push(box); }
  if (!reviewItems.length) nodes.push(element("p", "Nothing needs your review.", "muted"));
  for (const [kind, label] of REVIEW_GROUPS) {
    const members = reviewItems.map((item, index) => [item, index]).filter(([item]) => item.kind === kind);
    if (!members.length) continue;
    const group = element("div", "", "review-group");
    group.append(element("h2", `${label} (${members.length})`, "review-group-title"));
    const list = element("ul", "", "review-list");
    for (const [item, index] of members) {
      const li = document.createElement("li"), button = element("button", reviewTitle(item), "review-entry"); button.type = "button";
      if (index === reviewIndex) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => { reviewIndex = index; renderReviewQueue(catalog); renderReviewDetail(true); });
      li.append(button); list.append(li);
    }
    group.append(list); nodes.push(group);
  }
  nav.replaceChildren(...nodes);
  nav.dataset.catalog = JSON.stringify({work: catalog.work, counts: catalog.counts});
}
function currentCatalog() { try { return JSON.parse($("review-queue").dataset.catalog || "{}"); } catch { return {}; } }
async function thumbnail(documentId) {
  // Image evidence at a glance; PDFs open in the document inspector instead.
  const box = element("div", "", "review-thumb");
  if (!documentId) return box;
  try {
    const response = await fetch(`/api/documents/${documentId}/preview`, {headers: {"Authorization": `Bearer ${token}`}});
    if (!response.ok) return box;
    const blob = await response.blob();
    if (!blob.type.startsWith("image/")) return box;
    if (reviewThumb) URL.revokeObjectURL(reviewThumb);
    reviewThumb = URL.createObjectURL(blob);
    const image = document.createElement("img"); image.alt = "Source document";
    image.addEventListener("error", () => box.remove());  // An unreadable image shows nothing rather than a broken icon.
    image.src = reviewThumb; box.append(image);
  } catch {}
  return box;
}
function summaryBlock(label, summary, {link = true} = {}) {
  const box = element("div", "", "review-side");
  box.append(element("span", label, "figure-label"), element("strong", summary?.name || summary?.description || RECORD_KINDS[summary?.record_type] || "Record", "block"));
  // Only a transaction's sign means money in or out; a receipt or bill total is shown as printed.
  if (summary?.amount) box.append(amount(summary.amount, {signed: summary.record_type === "transaction"}));
  box.append(element("span", [summary?.date && dateText(summary.date), summary?.account].filter(Boolean).join(" · "), "muted small block"));
  if (link && summary?.document_id) box.append(homeLink("Open document", `#/documents/${summary.document_id}`));
  return box;
}
// Each kind: [evidence nodes, confirm action, reject action, other buttons].
function decide(path, body, message, undo = null) {
  return async () => {
    await api(path, {method: "POST", body: JSON.stringify(body)});
    const shown = toast(typeof message === "function" ? message() : message, {timeout: undo ? 8000 : 6000});
    if (undo) {
      const button = element("button", "Undo", "small"); button.type = "button";
      button.addEventListener("click", async () => {
        try { await undo(); shown.remove(); notice("Undone; the item is back in the queue."); await loadReview(false); } catch (error) { notice(error, true); }
      });
      shown.querySelector(".toast-body").append(button);
    }
    reviewIndex = Math.min(reviewIndex, Math.max(0, reviewItems.length - 2));
    await loadReview(false);
  };
}
function reviewParts(item) {
  const value = item.value;
  if (item.kind === "issue") {
    const path = `/api/finance/issues/${value.id}/resolve`;
    const candidates = element("div", "", "review-candidates");
    const choices = value.candidates.map(candidate => {
      const box = summaryBlock("Candidate", {...candidate, record_type: "transaction"});
      box.append(asyncButton("This one", decide(path, {transaction_id: candidate.id}, "Linked."), "small primary"));
      return box;
    });
    candidates.append(...choices);
    return {why: "Several transactions are equally likely, so nothing was linked. Choose the right one or leave it unmatched.",
            evidence: [summaryBlock("This record", value.record), candidates], document: value.record?.document_id,
            reject: decide(path, {transaction_id: null}, "Left unmatched; it won't be asked again."), rejectLabel: "Leave unmatched"};
  }
  if (item.kind === "link") {
    const path = `/api/finance/links/${value.kind}/${value.id}/review`;
    const pair = element("div", "", "review-candidates");
    pair.append(summaryBlock(value.kind === "receipt" ? "Charge" : "From", value.from), summaryBlock(value.kind === "receipt" ? "Receipt" : "To", value.to));
    return {why: `${LINK_KINDS[value.kind]} Matched because: ${value.match_signals.map(signal => SIGNALS[signal] || signal.replaceAll("_", " ")).join(", ")}.`,
            evidence: [pair], document: value.to?.document_id || value.from?.document_id,
            confirm: decide(path, {status: "verified"}, "Match confirmed."), confirmLabel: "Confirm match",
            reject: decide(path, {status: "rejected"}, "Marked not a match; it won't be proposed again."), rejectLabel: "Not a match"};
  }
  if (item.kind === "record") {
    const path = `/api/finance/records/${value.record_type}/${value.id}/review`;
    const undo = () => api(path, {method: "POST", body: JSON.stringify({status: "needs_review"})});
    const issues = element("ul", "", "review-issues");
    for (const issue of value.issues) issues.append(element("li", issue, "item-warning"));
    return {why: value.issues.length ? "A check didn't pass, so this record isn't counted until you decide:" : "Extracted by a model and not yet checked by you.",
            evidence: [issues, summaryBlock(RECORD_KINDS[value.record_type], value.summary, {link: false})], document: value.summary?.document_id,
            confirm: decide(path, {status: "verified"}, "Counted.", undo), confirmLabel: "Count it",
            reject: decide(path, {status: "rejected"}, "Rejected; it won't be counted.", undo), rejectLabel: "Reject"};
  }
  if (item.kind === "warranty") {
    const path = `/api/warranties/${value.id}/review`;
    const box = element("div", "", "review-side");
    box.append(element("span", "Found online", "figure-label"),
               element("strong", value.lifetime ? "Lifetime warranty" : `${value.months} months, until ${dateText(value.expires_on)}`, "block"),
               element("span", `“${value.quote}”`, "block"), element("small", value.source_title || "", "muted block"));
    if (value.source_url) box.append(element("small", value.source_url, "muted block mono"));
    const item = summaryBlock("Item", {name: [value.brand, value.name].filter(Boolean).join(" "), date: value.starts_on, account: value.merchant});
    return {why: "Home Manager found this on the web. It counts once you confirm it; check the page if the model or version differs.",
            evidence: [item, box], document: null,
            confirm: decide(path, {status: "verified"}, "Warranty confirmed."), confirmLabel: "Confirm warranty",
            reject: decide(path, {status: "rejected"}, "Rejected."), rejectLabel: "Reject"};
  }
  if (item.kind === "tax_table") {
    const path = `/api/tax-tables/${value.id}/review`;
    const box = element("div", "", "review-side");
    box.append(element("span", `${value.year} · filing ${value.filing_status.replaceAll("_", " ")}`, "figure-label"),
               element("strong", `Standard deduction ${value.display.standard_deduction_minor}`, "block"));
    const brackets = element("ul", "", "tax-brackets");
    for (const bracket of value.brackets) brackets.appendChild(element("li", `${bracket.display.rate} on taxable income over ${bracket.display.from}`));
    box.appendChild(brackets);
    if (value.ss_rate_bp != null) box.appendChild(element("small", `Social Security ${value.ss_rate_bp / 100}% up to ${value.display.ss_wage_base_minor || "?"} · `
      + `Medicare ${value.medicare_rate_bp / 100}%${value.additional_medicare_rate_bp ? ` + ${value.additional_medicare_rate_bp / 100}% over ${value.display.additional_medicare_threshold_minor}` : ""}`, "block"));
    const sources = element("div", "", "review-side");
    sources.appendChild(element("span", "Quoted from", "figure-label"));
    for (const source of value.sources) sources.append(element("span", `“${source.quote}”`, "block"), element("small", source.url, "muted block mono"));
    return {why: "The local model looked this table up to explain your pay stub's taxes. Every number is quoted from the page below; pay stubs use it once you confirm it.",
            evidence: [box, sources], document: null,
            confirm: decide(path, {status: "verified"}, "Tax table confirmed."), confirmLabel: "Confirm table",
            reject: decide(path, {status: "rejected"}, "Rejected; it can be looked up again from the pay stub."), rejectLabel: "Reject"};
  }
  if (item.kind === "tax_tag") {
    // A suggested tax tag: the bank line, what it would count as, and why it was suggested. Confirming can make a rule too.
    const path = `/api/tax-tags/${value.id}/review`, body = {status: "verified", rule_words: null};
    const box = element("div", "", "review-side");
    box.append(element("span", value.target.detail || "Bank line", "figure-label"), element("strong", value.target.description, "block"),
               element("span", `${dateText(value.tax_date)} · `, ""), amount(value.display.amount_minor, {signed: false}));
    const proposal = element("div", "", "review-side");
    proposal.append(element("span", "Would count as", "figure-label"), element("strong", `${value.kind_label}: ${value.line_label}`, "block"),
                    ...(value.business ? [element("span", value.business, "block")] : []),
                    ...(value.counted_minor !== value.amount_minor ? [element("small", `${value.display.counted_minor} counts on the return.`, "muted block")] : []));
    const rule = element("label", "", "compact-check"), check = document.createElement("input"), words = document.createElement("input");
    check.type = "checkbox"; words.maxLength = 120; words.value = ruleWords({description_raw: value.target.description}); words.setAttribute("aria-label", "Words the rule matches");
    const sync = () => { body.rule_words = check.checked ? words.value.trim() || null : null; };
    check.addEventListener("change", sync); words.addEventListener("input", sync);
    rule.append(check, document.createTextNode(" Also tag every bank line containing "), words);
    return {why: `${value.reason} Confirm it to count it in this year's taxes.`, evidence: [box, proposal], extra: [rule], document: null,
            confirm: decide(path, body, "Tagged; it counts in this year's taxes."), confirmLabel: "Tag it",
            reject: decide(path, {status: "rejected"}, "Not a write-off; this payee won't be suggested again."), rejectLabel: "Not a write-off"};
  }
  if (item.kind === "asset" && value.record_type === "tax_form") {
    // A 1099 or 5498: its boxes, which Investments → Taxes compares with what is recorded for the account.
    const path = value.review_path, undo = () => api(path, {method: "POST", body: JSON.stringify({status: "proposed"})});
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
            evidence: [issues, box], document: value.document_id,
            confirm: decide(path, {status: "verified"}, "Confirmed; compare it under Investments → Taxes.", undo), confirmLabel: "Confirm form",
            reject: decide(path, {status: "rejected"}, "Rejected; it is left out.", undo), rejectLabel: "Reject"};
  }
  if (item.kind === "asset" && value.record_type === "investment_confirmation") {
    // A trade, CD or Treasury purchase: what was bought or sold, with the terms its value will be estimated from.
    const path = value.review_path, undo = () => api(path, {method: "POST", body: JSON.stringify({status: "proposed"})});
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
            evidence: [issues, box], document: value.document_id,
            confirm: decide(path, {status: "verified"}, "Confirmed; its holdings now count.", undo), confirmLabel: "Confirm purchase",
            reject: decide(path, {status: "rejected"}, "Rejected; nothing from it counts.", undo), rejectLabel: "Reject"};
  }
  if (item.kind === "asset") {
    const path = value.review_path || `/api/assets/${value.id}/review`;
    const undo = () => api(path, {method: "POST", body: JSON.stringify({status: "proposed"})});
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
            evidence: [issues, box], document: value.document_id,
            confirm: decide(path, {status: "verified"}, "Confirmed; it now counts in your forecast.", undo), confirmLabel: "Confirm value",
            reject: decide(path, {status: "rejected"}, "Rejected; the forecast leaves it out.", undo), rejectLabel: "Reject"};
  }
  if (item.kind === "recurring") {
    const path = `/api/finance/recurring/${value.id}/review`;
    const next = value.next_due_date ? dateText(value.next_due_date) : "unknown";
    const why = {receipt_single_payment: "A receipt was read as a payment for a service billed on a schedule.",
                 category_single_payment: `A ${value.category || "bill"} charge: how often it recurs can't be told from one payment, so check it below.`,
                 statement_model: "The local model read this payee's statement charges as an ongoing service billed on a schedule. Check how often below.",
                 contract_terms: `Read from the document's payment terms: “${value.evidence || ""}”.`
                }[value.confidence_source] || `Payments of the same amount arrived at a steady ${FREQUENCY_LABELS[value.frequency]} cadence.`;
    // Confirming sends the chosen frequency: the body is read when the button is pressed.
    const body = {status: "verified", frequency: value.frequency, kind: value.kind};
    const often = element("label", "How often ", "inline-field");
    const select = document.createElement("select");
    for (const [key, label] of Object.entries(FREQUENCY_LABELS)) select.add(new Option(label, key));
    select.value = value.frequency; select.addEventListener("change", () => { body.frequency = select.value; });
    often.append(select);
    // Bill or subscription is the user's call; the suggestion comes from the category.
    const kindField = element("label", "Counts as ", "inline-field");
    kindField.append(kindSelect(value.kind, kind => { body.kind = kind; }));
    const note = value.category ? `Counts under ${categoryLabel(value.category)} in your forecast and budgets once confirmed.` : "Counts in your forecast once confirmed.";
    return {why: `${why} Next expected about ${next}. ${note}`,
            evidence: [summaryBlock("Recurring payment", {name: value.merchant, amount: value.expected_amount, date: value.next_due_date})], extra: [often, kindField],
            document: value.source_document_id,
            confirm: decide(path, body, () => `Confirmed as a ${RECURRING_KIND_LABELS[body.kind].toLowerCase()}.`), confirmLabel: "Confirm recurring",
            reject: decide(path, {status: "rejected"}, "Marked not recurring; it won't be proposed again."), rejectLabel: "Not recurring"};
  }
  const path = `/api/items/resolutions/${value.id}/review`;
  const proposal = element("div", "", "review-side");
  proposal.append(element("span", "Proposed product", "figure-label"), element("strong", [value.brand, value.name, value.size_text].filter(Boolean).join(" · "), "block"),
                  element("span", `${value.category}${value.consumable ? " · runs out" : ""} · ${value.confidence} confidence · from ${value.method}`, "muted small block"));
  for (const source of value.sources.slice(0, 3)) if (source.url) proposal.append(element("small", source.url, "muted block mono"));
  const line = summaryBlock("Printed on the receipt", {name: value.line.description, amount: null, date: value.line.purchase_date, account: value.line.merchant});
  const edit = element("button", "Edit and approve…", "small"); edit.type = "button"; edit.addEventListener("click", () => openItemDialog(value));
  return {why: "Every product name from a receipt line waits for your approval before it joins your inventory.",
          evidence: [line, proposal], document: null, extra: [edit],
          confirm: decide(path, {status: "verified"}, "Approved; the item joined your inventory."), confirmLabel: "Approve",
          reject: decide(path, {status: "rejected"}, "Rejected; this product won't be proposed for this line again."), rejectLabel: "Reject"};
}
async function renderReviewDetail(focus = false) {
  const detail = $("review-detail"), item = reviewItems[reviewIndex];
  if (!item) { detail.replaceChildren(emptyState("Nothing needs your review. New documents and imports appear here when Home Manager is unsure about them.")); return; }
  const parts = reviewParts(item);
  const actions = element("div", "", "review-actions");
  if (parts.confirm) { const button = asyncButton(`${parts.confirmLabel} (V)`, parts.confirm, "primary"); button.id = "review-confirm"; actions.append(button); }
  if (parts.reject) { const button = asyncButton(`${parts.rejectLabel} (R)`, parts.reject, ""); button.id = "review-reject"; actions.append(button); }
  actions.append(...(parts.extra || []));
  if (parts.document) actions.append(homeLink("Open document", `#/documents/${parts.document}`, "review-open"));
  const position = element("p", `${reviewIndex + 1} of ${reviewItems.length}`, "muted small");
  const heading = element("h2", item.kind === "link" ? LINK_KINDS[item.value.kind] : reviewTitle(item));
  detail.replaceChildren(position, heading, element("p", parts.why, "review-why"), ...parts.evidence, actions);
  if (parts.document) thumbnail(parts.document).then(box => { if (reviewItems[reviewIndex] === item && box.children.length) detail.insertBefore(box, actions); });
  if (focus) detail.focus();
}
function renderUnmatched(unmatched) {
  const rows = [...unmatched.receipts, ...unmatched.undated].map(receipt => {
    const li = element("li", "", "review-item");
    li.append(element("strong", receipt.name || "Receipt"), element("span", describe(receipt, {named: false}), "block"));
    li.append(element("small", receipt.reason === "several_possible_charges" ? "Several possible charges: answer it in Questions above." :
                               receipt.date ? "No matching card or bank charge yet." : "No purchase date: add one with Edit details.", "muted block"));
    li.append(homeLink("Open document", `#/documents/${receipt.document_id}`));
    return li;
  });
  $("review-unmatched").replaceChildren(...(rows.length ? rows : [element("li", "Every dated receipt matches a charge.", "muted")]));
  $("review-unmatched-note").textContent = unmatched.by_currency.map(row => `${row.total.display} in ${row.receipts} receipt${row.receipts === 1 ? "" : "s"}`).join("; ");
}
document.addEventListener("keydown", event => {
  if (currentRoute?.name !== "review" || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
  if (document.querySelector("dialog[open]") || event.target.closest("input, select, textarea, .menu")) return;
  const key = event.key.toLowerCase();
  if ((key === "j" || key === "k") && reviewItems.length) {
    event.preventDefault();
    reviewIndex = (reviewIndex + (key === "j" ? 1 : -1) + reviewItems.length) % reviewItems.length;
    renderReviewQueue(currentCatalog()); renderReviewDetail();
    $("review-queue").querySelector('[aria-current="true"]')?.scrollIntoView({block: "nearest"});
  } else if (key === "v" && $("review-confirm")) { event.preventDefault(); $("review-confirm").click(); }
  else if (key === "r" && $("review-reject")) { event.preventDefault(); $("review-reject").click(); }
});
$("review-refresh").addEventListener("click", () => loadReview());
$("reconcile").addEventListener("click", () => api("/api/finance/reconcile", {method: "POST", body: "{}"})
  .then(result => { notice(`Reconciliation proposed ${result.receipt_links} receipt links, ${result.transfers} transfers and ${result.refunds} refunds; ${result.open_issues} ambiguous cases need you.`); return loadReview(); })
  .catch(error => notice(error, true)));

// Approve an item resolution with the user's corrections.
let editingResolution = null;
$("item-category").replaceChildren(...ITEM_CATEGORIES.map(name => new Option(name)));
function openItemDialog(resolution) {
  editingResolution = resolution;
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
    $("item-dialog").close(); notice("Approved with your changes; the item joined your inventory."); await loadReview(false);
  } catch (error) { $("item-dialog-error").textContent = error.message; }
});
