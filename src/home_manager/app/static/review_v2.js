"use strict";
// To check, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/review.md): the queue, the item's source
// beside it, and the item with its decision bar pinned at the bottom of its column. It shares review.js's data and
// wording; a record's decision is Confirm, Reject or Correct (trace.js confirmCorrect). Keys: J/K move, V confirms,
// R rejects. The route keeps the item: #/review?item=<kind>:<id>.
const review2 = {entries: [], index: 0, catalog: {}, counts: null, people: [], viewer: null, shown: 0, wanted: null, fallback: 0, moves: 0};

V2_SCREENS.review = {title: "To check", show: route => loadReviewV2(route.params)};

// review.js's groups, then images that may be one document, and receipts with no matching charge (or, in the family
// view, who each upload is for).
const review2Groups = () => [...REVIEW_GROUPS, ["group", "Images that look like one document"],
                             familyMode ? ["routing", "Who is it for?"] : ["unmatched", "Receipts with no matching charge"]];

function loadReviewV2(params) {
  review2.wanted = params?.get?.("item") || null; review2.fallback = 0;
  return review2Load();
}
// Loads again keeping the item; when it was decided and left the queue, the one after it takes its place.
function reloadReviewV2() {
  const item = review2.entries[review2.index];
  review2.wanted = item ? reviewKey(item) : null; review2.fallback = review2.index;
  return review2Load();
}
function review2Load() {
  return pageState($("review2-state"), renderReviewV2, {loading: "Loading what needs you …", what: "what needs you", needsLibrary: true, content: [$("review2-body")]});
}
async function renderReviewV2() {
  const moves = review2.moves;
  const [data, groups, routing] = await Promise.all([reviewData(), familyMode ? [] : api("/api/document-groups"), familyMode ? api("/api/family/routing") : null]);
  // An item the user chose while this loaded wins over the one asked for when it started.
  if (review2.moves !== moves && review2.entries[review2.index]) { review2.wanted = reviewKey(review2.entries[review2.index]); review2.fallback = review2.index; }
  const last = familyMode ? routing.records.map(value => ({kind: "routing", id: `${value.record_type}-${value.id}`, value}))
    : [...data.unmatched.receipts, ...data.unmatched.undated].map(value => ({kind: "unmatched", id: `receipt-${value.id}`, value}));
  review2.entries = [...data.items, ...groups.map(value => ({kind: "group", id: value.id, value})), ...last];
  review2.catalog = data.catalog; review2.counts = data.counts; review2.people = routing?.people || [];
  const found = review2.wanted ? review2.entries.findIndex(item => reviewKey(item) === review2.wanted) : -1;
  review2.index = found >= 0 ? found : Math.min(review2.fallback, Math.max(0, review2.entries.length - 1));
  const total = data.counts.total;
  $("review2-status").textContent = total ? `${total} item${total === 1 ? "" : "s"} need you · checked ${new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}` : "";
  showReviewCounts(data.counts);
  renderReview2Queue();
  renderReview2Item();
  review2Url();
}
function review2Url() {
  if (currentRoute?.name !== "review") return;
  const item = review2.entries[review2.index], params = new URLSearchParams();
  if (item) params.set("item", reviewKey(item));
  currentRoute.params = params;
  history.replaceState(null, "", `#/review${item ? `?${params}` : ""}`);
}
function review2Title(item) {
  const value = item.value;
  if (item.kind === "group") return `${value.pages.length} images · ${value.pages[0]?.relative_path.split("/").pop() || ""}`;
  if (item.kind === "unmatched") return `${value.name || "Receipt"} · ${describe(value, {named: false})}`;
  if (item.kind === "routing") return `${RECORD_KINDS[value.record_type] || statusLabel(value.record_type)} · ${value.name || "Name not found"}`;
  return reviewTitle(item);
}

// The queue: one list of buttons per group at 1180px and up, a select with Previous and Next below it.
function renderReview2Queue() {
  const nodes = [], picker = $("review2-picker");
  picker.replaceChildren();
  for (const [kind, label] of review2Groups()) {
    const members = review2.entries.map((item, index) => [item, index]).filter(([item]) => item.kind === kind);
    if (!members.length) continue;
    const count = review2.counts?.groups?.[kind] ?? members.length;
    const group = element("div", "", "review2-group"), title = element("h2", label, "review2-group-title");
    title.append(element("span", String(count), "review2-count"));
    group.append(title);
    if (count > members.length) group.append(element("p", `The first ${members.length} are listed; decide on them to see the rest.`, "muted small"));
    const list = element("ul", "", "review2-list"), options = document.createElement("optgroup");
    options.label = `${label} (${count})`;
    for (const [item, index] of members) {
      const text = review2Title(item), entry = element("li"), button = element("button", "", "review2-entry");
      button.type = "button"; button.title = text; button.dataset.index = String(index);
      button.append(element("span", text, "review2-entry-text"));
      if (index === review2.index) button.setAttribute("aria-current", "true");
      button.addEventListener("click", () => review2Select(index));
      entry.append(button); list.append(entry);
      options.append(new Option(text, String(index)));
    }
    group.append(list); nodes.push(group); picker.append(options);
  }
  const other = [], catalog = review2.catalog;
  if (catalog.work?.failed) other.push(homeLink(`${catalog.work.failed} documents couldn't be processed`, "#/documents?status=failed"));
  if (catalog.counts?.Unfiled) {
    const unfiled = element("button", `${catalog.counts.Unfiled} unfiled documents`, "link-button"); unfiled.type = "button";
    unfiled.addEventListener("click", () => showFolder("Unfiled")); other.push(unfiled);
  }
  if (other.length) { const foot = element("div", "", "review2-other"); foot.append(...other); nodes.push(foot); }
  $("review2-queue").replaceChildren(...nodes);
  picker.value = String(review2.index);
  picker.disabled = !review2.entries.length;
  $("review2-prev").disabled = $("review2-next").disabled = review2.entries.length < 2;
}
function review2Select(index) {
  review2.index = index; review2.moves++;
  for (const button of $("review2-queue").querySelectorAll(".review2-entry")) button.removeAttribute("aria-current");
  const button = $("review2-queue").querySelector(`.review2-entry[data-index="${index}"]`);
  button?.setAttribute("aria-current", "true");
  button?.scrollIntoView({block: "nearest"});
  $("review2-picker").value = String(index);
  review2Url();
  renderReview2Item();
}
function review2Move(step) {
  if (review2.entries.length) review2Select((review2.index + step + review2.entries.length) % review2.entries.length);
}

// One item: its position, what and why, the evidence, and the decision bar; the source column beside it.
function renderReview2Item() {
  const item = review2.entries[review2.index], shown = ++review2.shown;
  review2.viewer?.destroy(); review2.viewer = null;
  for (const id of ["review2-why", "review2-evidence", "review2-form", "review2-alert", "review2-bar", "review2-source"]) $(id).replaceChildren();
  const empty = !item;
  $("review2-empty").hidden = !empty; $("review2-source").hidden = empty; $("review2-item").hidden = empty;
  $("review2-empty").replaceChildren(...(empty ? [emptyState("Nothing needs you. New documents show here after they're read.")] : []));
  if (empty) return;
  const parts = review2Parts(item);
  $("review2-position").textContent = `${review2.index + 1} of ${review2.entries.length}`;
  $("review2-what").textContent = parts.what || reviewTitle(item);
  if (parts.issues?.length) {
    const row = element("div", "", "needs-row attention review2-why-row"), text = element("div");
    text.append(element("strong", parts.issues[0]), element("small", parts.issues.slice(1).join(" ") || parts.why, "muted"));
    row.append(icon("alert", "icon needs-icon"), text);
    $("review2-why").append(row);
  } else if (parts.why) $("review2-why").append(element("p", parts.why, "review2-why"));
  $("review2-evidence").append(...parts.evidence, ...(parts.extra || []));
  review2Bar(parts, shown).catch(error => { if (shown === review2.shown) $("review2-alert").replaceChildren(alertBox(error.message, {tone: "error"})); });
  review2Source(parts.source, shown);
}
async function review2Bar(parts, shown) {
  const bar = $("review2-bar"), nodes = [];
  if (parts.cc) {
    const options = await parts.cc();
    if (shown !== review2.shown) return;
    const cc = confirmCorrect({labels: {confirm: "Confirm (V)", reject: "Reject (R)"}, ...options, preview: !familyMode, onChange: () => reloadReviewV2()});
    if (cc.confirmButton) cc.confirmButton.id = "review2-confirm";
    if (cc.rejectButton) cc.rejectButton.id = "review2-reject";
    if (cc.correctButton) cc.correctButton.id = "review2-correct";
    // The Correct form opens in the item's scrolling part and a failed decision shows above the bar; the buttons stay in it.
    $("review2-form").replaceChildren(cc.el.querySelector(".cc-form"));
    $("review2-alert").replaceChildren(cc.el.querySelector(".cc-state"));
    const actions = cc.el.querySelector(".cc-actions");  // The bar is the Decision group already.
    actions.removeAttribute("role"); actions.removeAttribute("aria-label");
    nodes.push(cc.el);
  }
  if (parts.confirm) { const button = asyncButton(`${parts.confirm.label} (V)`, parts.confirm.run, "primary"); button.id = "review2-confirm"; nodes.push(button); }
  if (parts.reject) { const button = asyncButton(`${parts.reject.label} (R)`, parts.reject.run, ""); button.id = "review2-reject"; nodes.push(button); }
  nodes.push(...(parts.bar || []));
  if (parts.document) { const open = homeLink("Open document", `#/documents/${parts.document}`, "review2-open"); open.id = "review2-open"; nodes.push(open); }
  bar.replaceChildren(...nodes);
}
// A decision that isn't a record's: posted, then a toast (with Undo where it can be undone), then the next item.
// A failure shows above the bar and the item stays.
function review2Decide(path, body, message, {undo = null, method = "POST"} = {}) {
  return async () => {
    $("review2-alert").replaceChildren();
    try { await api(path, {method, body: JSON.stringify(body)}); }
    catch (error) { $("review2-alert").replaceChildren(alertBox(error.message, {tone: "error"})); return; }
    const shown = toast(typeof message === "function" ? message() : message, {timeout: undo ? 8000 : 6000});
    if (undo) {
      const button = element("button", "Undo", "small"); button.type = "button";
      button.addEventListener("click", async () => {
        try { await undo(); shown.remove(); notice("Undone; the item is back in the queue."); await reloadReviewV2(); } catch (error) { notice(error, true); }
      });
      shown.querySelector(".toast-body").append(button);
    }
    await reloadReviewV2();
  };
}

// The source column: the item's document with its evidence lit, chips when there is more than one, or a card for what
// was found online.
async function review2Source(source, shown) {
  const host = $("review2-source");
  let found;
  try { found = (typeof source === "function" ? await source() : source) || {}; } catch { found = {}; }
  if (shown !== review2.shown) return;
  if (found.card) { host.replaceChildren(found.card); return; }
  const chips = (found.chips || []).filter((chip, index, all) => chip.document && all.findIndex(other => other.document === chip.document) === index);
  const first = chips[0] || (found.document && {document: found.document, lines: found.lines});
  if (!first) { host.replaceChildren(emptyState("This has no document.")); return; }
  let head = null;
  if (chips.length > 1) {
    head = element("div", "", "work-filters review2-chips"); head.setAttribute("aria-label", "Documents");
    for (const chip of chips) {
      const button = element("button", chip.label, "filter-chip"); button.type = "button";
      button.setAttribute("aria-pressed", String(chip === first));
      button.addEventListener("click", () => {
        for (const other of head.children) other.setAttribute("aria-pressed", String(other === button));
        review2Document(chip, shown, head);
      });
      head.append(button);
    }
  }
  await review2Document(first, shown, head);
}
async function review2Document({document: documentId, lines}, shown, head) {
  const host = $("review2-source");
  let reading;
  try { reading = await loadReading(documentId); }
  catch (error) {
    if (shown === review2.shown) host.replaceChildren(...(head ? [head] : []), alertBox(`The document couldn't be shown. ${error.message}`, {tone: "error"}));
    return;
  }
  if (shown !== review2.shown) return;
  review2.viewer?.destroy();
  const viewer = sourceViewer(reading.doc, reading, {runId: reading.run?.id || null});
  review2.viewer = viewer;
  host.replaceChildren(...(head ? [head] : []), viewer.el);
  const ids = typeof lines === "function" ? await lines() : lines;
  if (shown === review2.shown && review2.viewer === viewer && ids?.length) viewer.highlight(ids);
}
// A record's cited source lines (finance/provenance.py), or none.
async function review2Lines(type, id) {
  try { return (await api(`/api/provenance/${type}/${id}`)).provenance.document?.lines || []; } catch { return []; }
}
function review2Card(title, ...children) {
  const card = element("section", "", "source-card"); card.setAttribute("aria-label", title);
  card.append(element("h3", title), ...children);
  return card;
}
function review2Quote(text) { return element("blockquote", `“${text}”`); }
// A web address shown as text, never a link (the page it names wasn't checked by Home Manager).
function review2Address(text) { return element("p", text, "mono small muted source-url"); }

// Each kind: {what, why, issues, evidence, extra, source, document, cc | confirm/reject, bar}. The why gives the reason
// only (never the title again), and decisions keep this page current.
function review2Parts(item) {
  const value = item.value;
  if (item.kind === "issue" && value.issue_type === "family_correction") {
    const path = `/api/finance/issues/${value.id}/resolve`, changes = element("ul", "", "review-issues");
    for (const change of value.detail.corrections) {
      changes.append(element("li", `${change.field.replaceAll("_", " ")}: yours is ${change.current ?? "empty"}; ${change.actor.replace(/^Family · /, "")} `
                                   + `changed it from ${change.previous ?? "empty"} to ${change.value ?? "empty"}.`));
    }
    return {why: "Your family corrected this record, but you had already changed the same field. Choose which to keep.",
            evidence: [changes, summaryBlock(RECORD_KINDS[value.record_type] || "Record", value.record, {link: false})],
            source: review2RecordSource(value.record_type, value.record_id, value.record?.document_id), document: value.record?.document_id,
            confirm: {label: "Use family's", run: review2Decide(path, {family: "family"}, "Used your family's change.")},
            reject: {label: "Keep mine", run: review2Decide(path, {family: "mine"}, "Kept yours.")}};
  }
  if (item.kind === "issue") {
    const path = `/api/finance/issues/${value.id}/resolve`, candidates = element("div", "", "review2-pair");
    candidates.append(...value.candidates.map(candidate => {
      const box = summaryBlock("Candidate", {...candidate, record_type: "transaction"}, {link: false});
      box.append(asyncButton("This one", review2Decide(path, {transaction_id: candidate.id}, "Linked.")));
      return box;
    }));
    return {why: "Several transactions are equally likely, so nothing was linked. Choose the right one or leave it unmatched.",
            evidence: [summaryBlock("This record", value.record, {link: false}), candidates],
            source: review2RecordSource(value.record_type, value.record_id, value.record?.document_id), document: value.record?.document_id,
            reject: {label: "Leave unmatched", run: review2Decide(path, {transaction_id: null}, "Left unmatched; it won't be asked again.")}};
  }
  if (item.kind === "link") {
    const path = `/api/finance/links/${value.kind}/${value.id}/review`, pair = element("div", "", "review2-pair");
    const sides = value.kind === "receipt" ? [["Charge", value.from], ["Receipt", value.to]] : [["From", value.from], ["To", value.to]];
    pair.append(...sides.map(([label, summary]) => summaryBlock(label, summary, {link: false})));
    const signals = value.match_signals.map(signal => SIGNALS[signal] || signal.replaceAll("_", " "));
    // The receipt first, then the statement the charge is on.
    const chips = (value.kind === "receipt" ? [["Receipt", value.to], ["Charge's statement", value.from]] : [["From", value.from], ["To", value.to]])
      .filter(([, summary]) => summary?.document_id)
      .map(([label, summary]) => ({label, document: summary.document_id, lines: () => review2Lines(summary.record_type || "transaction", summary.id)}));
    return {what: LINK_KINDS[value.kind], why: `Matched because: ${signals.join(", ")}.`, evidence: [pair], source: {chips},
            document: value.to?.document_id || value.from?.document_id,
            confirm: {label: "Confirm match", run: review2Decide(path, {status: "verified"}, "Match confirmed.")},
            reject: {label: "Not a match", run: review2Decide(path, {status: "rejected"}, "Marked not a match; it won't be proposed again.")}};
  }
  if (item.kind === "record") {
    const record = `/api/finance/records/${value.record_type}/${value.id}`;
    return {why: value.issues.length ? "It isn't counted until you decide." : "Extracted by a model and not yet checked by you.", issues: value.issues,
            evidence: [summaryBlock(RECORD_KINDS[value.record_type], value.summary, {link: false})],
            source: review2RecordSource(value.record_type, value.id, value.summary?.document_id), document: value.summary?.document_id,
            cc: async () => {
              const view = await api(record);
              return {recordType: value.record_type, recordId: value.id, reviewStatus: view.review_status, reviewSource: view.review_source, correctable: view.correctable || []};
            }};
  }
  if (item.kind === "asset") {
    // Statement values, purchase confirmations and tax forms: review.js assetParts' evidence, with this page's decision.
    const parts = assetParts(item), path = value.review_path || `/api/assets/${value.id}/review`;
    return {why: parts.why, issues: value.issues || [], evidence: parts.evidence.filter(node => !node.classList?.contains("review-issues")),
            source: {document: value.document_id}, document: value.document_id,
            cc: () => ({recordType: value.record_type || "asset", recordId: value.id, reviewStatus: "proposed", reviewSource: null, correctable: [],
                        reviewPath: path, undoBody: {status: "proposed"}, labels: {confirm: `${parts.confirmLabel} (V)`, reject: "Reject (R)"}})};
  }
  if (item.kind === "warranty") {
    const path = `/api/warranties/${value.id}/review`, length = element("div", "", "review-side");
    length.append(element("span", "Warranty", "figure-label"),
                  element("strong", value.lifetime ? "Lifetime warranty" : `${value.months} months, until ${dateText(value.expires_on)}`, "block"));
    const card = review2Card("Found online", review2Quote(value.quote), ...(value.source_title ? [element("p", value.source_title, "small")] : []),
                             ...(value.source_url ? [review2Address(value.source_url)] : []));
    return {why: "Home Manager found this on the web. It counts once you confirm it; check the page if the model or version differs.",
            evidence: [summaryBlock("Item", {name: [value.brand, value.name].filter(Boolean).join(" "), date: value.starts_on, account: value.merchant}, {link: false}), length],
            source: {card},
            confirm: {label: "Confirm warranty", run: review2Decide(path, {status: "verified"}, "Warranty confirmed.")},
            reject: {label: "Reject", run: review2Decide(path, {status: "rejected"}, "Rejected.")}};
  }
  if (item.kind === "tax_table") {
    const path = `/api/tax-tables/${value.id}/review`, box = element("div", "", "review-side");
    box.append(element("span", `${value.year} · filing ${value.filing_status.replaceAll("_", " ")}`, "figure-label"),
               element("strong", `Standard deduction ${value.display.standard_deduction_minor}`, "block"));
    if (value.ss_rate_percent != null) box.append(element("small", `Social Security ${value.ss_rate_percent}% up to ${value.display.ss_wage_base_minor || "?"} · `
      + `Medicare ${value.medicare_rate_percent}%${value.additional_medicare_rate_bp ? ` + ${value.additional_medicare_rate_percent}% over ${value.display.additional_medicare_threshold_minor}` : ""}`, "block"));
    const table = element("table", "", "source-table"), head = element("thead"), body = element("tbody"), top = element("tr");
    top.append(element("th", "Rate"), element("th", "On taxable income over"));
    head.append(top);
    for (const bracket of value.brackets) { const row = element("tr"); row.append(element("td", bracket.display.rate), element("td", bracket.display.from)); body.append(row); }
    table.append(head, body);
    const sources = value.sources.flatMap(source => [review2Quote(source.quote), review2Address(source.url)]);
    return {why: "The local model looked this table up to explain your pay stub's taxes. Every number is quoted from its source; pay stubs use it once you confirm it.",
            evidence: [box], source: {card: review2Card("Quoted sources", ...sources, table)},
            confirm: {label: "Confirm table", run: review2Decide(path, {status: "verified"}, "Tax table confirmed.")},
            reject: {label: "Reject", run: review2Decide(path, {status: "rejected"}, "Rejected; it can be looked up again from the pay stub.")}};
  }
  if (item.kind === "tax_tag") {
    // A suggested tax tag: the bank line, what it would count as, and why it was suggested. Confirming can make a rule too.
    const path = `/api/tax-tags/${value.id}/review`, body = {status: "verified", rule_words: null}, target = value.target;
    const line = () => {
      const box = element("div", "", "review-side");
      box.append(element("span", target.detail || "Bank line", "figure-label"), element("strong", target.description, "block"),
                 element("span", `${dateText(value.tax_date)} · `, ""), amount(value.display.amount_minor, {signed: false}));
      return box;
    };
    const proposal = element("div", "", "review-side");
    proposal.append(element("span", "Would count as", "figure-label"), element("strong", `${value.kind_label}: ${value.line_label}`, "block"),
                    ...(value.business ? [element("span", value.business, "block")] : []),
                    ...(value.counted_minor !== value.amount_minor ? [element("small", `${value.display.counted_minor} counts on the return.`, "muted block")] : []));
    const rule = element("label", "", "compact-check"), check = document.createElement("input"), words = document.createElement("input");
    check.type = "checkbox"; words.maxLength = 120; words.value = ruleWords({description_raw: target.description}); words.setAttribute("aria-label", "Words the rule matches");
    const sync = () => { body.rule_words = check.checked ? words.value.trim() || null : null; };
    check.addEventListener("change", sync); words.addEventListener("input", sync);
    rule.append(check, document.createTextNode(" Also tag every bank line containing "), words);
    // The target's document, found when the item opens; a bank line without one shows as a card.
    const source = async () => {
      const type = target.type === "receipt_item" ? "receipt" : target.type, id = target.type === "receipt_item" ? target.receipt_id : target.id;
      const record = id ? await api(`/api/finance/records/${type}/${id}`).catch(() => null) : null;
      const documentId = record?.document_id || record?.source_document_id;
      return documentId ? {document: documentId, lines: () => review2Lines(type, id)} : {card: review2Card("Bank line", line())};
    };
    return {why: `${value.reason} Confirm it to count it in this year's taxes.`, evidence: [line(), proposal], extra: [rule], source,
            confirm: {label: "Tag it", run: review2Decide(path, body, "Tagged; it counts in this year's taxes.")},
            reject: {label: "Not a write-off", run: review2Decide(path, {status: "rejected"}, "Not a write-off; this payee won't be suggested again.")}};
  }
  if (item.kind === "recurring") {
    const path = `/api/finance/recurring/${value.id}/review`;
    const next = value.next_due_date ? dateText(value.next_due_date) : "unknown";
    const why = {receipt_single_payment: "A receipt was read as a payment for a service billed on a schedule.",
                 category_single_payment: `A ${value.category || "bill"} charge: how often it recurs can't be told from one payment, so check it below.`,
                 statement_model: "The local model read this payee's statement charges as an ongoing service billed on a schedule. Check how often below.",
                 contract_terms: `Read from the document's payment terms: “${value.evidence || ""}”.`
                }[value.confidence_source] || `Payments of the same amount arrived at a steady ${FREQUENCY_LABELS[value.frequency]} cadence.`;
    // Confirming sends the chosen frequency and kind: the body is read when the button is pressed.
    const body = {status: "verified", frequency: value.frequency, kind: value.kind};
    const often = element("label", "How often ", "inline-field"), select = document.createElement("select");
    for (const [key, label] of Object.entries(FREQUENCY_LABELS)) select.add(new Option(label, key));
    select.value = value.frequency; select.addEventListener("change", () => { body.frequency = select.value; });
    often.append(select);
    const kindField = element("label", "Counts as ", "inline-field");
    kindField.append(kindSelect(value.kind, kind => { body.kind = kind; }));
    const note = value.category ? `Counts under ${categoryLabel(value.category)} in your forecast and budgets once confirmed.` : "Counts in your forecast once confirmed.";
    return {why: `${why} Next expected about ${next}. ${note}`,
            evidence: [summaryBlock("Recurring payment", {name: value.merchant, amount: value.expected_amount, date: value.next_due_date}, {link: false})],
            extra: [often, kindField], source: {document: value.source_document_id}, document: value.source_document_id,
            confirm: {label: "Confirm recurring", run: review2Decide(path, body, () => `Confirmed as a ${RECURRING_KIND_LABELS[body.kind].toLowerCase()}.`)},
            reject: {label: "Not recurring", run: review2Decide(path, {status: "rejected"}, "Marked not recurring; it won't be proposed again.")}};
  }
  if (item.kind === "item") {
    const path = `/api/items/resolutions/${value.id}/review`, proposal = element("div", "", "review-side");
    proposal.append(element("span", "Proposed product", "figure-label"), element("strong", [value.brand, value.name, value.size_text].filter(Boolean).join(" · "), "block"),
                    element("span", `${value.category}${value.consumable ? " · runs out" : ""} · ${value.confidence} confidence · from ${value.method}`, "muted small block"));
    for (const source of value.sources.slice(0, 3)) if (source.url) proposal.append(review2Address(source.url));
    const line = summaryBlock("Printed on the receipt", {name: value.line.description, amount: null, date: value.line.purchase_date, account: value.line.merchant}, {link: false});
    const edit = element("button", "Edit and approve…"); edit.type = "button"; edit.addEventListener("click", () => openItemDialog(value, () => reloadReviewV2()));
    return {why: "Every product name from a receipt line waits for your approval before it joins your inventory.", evidence: [line, proposal],
            source: {document: value.line.document_id, lines: value.line_ids}, document: value.line.document_id, bar: [edit],
            confirm: {label: "Approve", run: review2Decide(path, {status: "verified"}, "Approved; the item joined your inventory.")},
            reject: {label: "Reject", run: review2Decide(path, {status: "rejected"}, "Rejected; this product won't be proposed for this line again.")}};
  }
  if (item.kind === "group") {
    const path = `/api/document-groups/${value.id}`, pages = element("ol", "", "group-pages");
    for (const page of value.pages) pages.append(element("li", page.relative_path.split("/").pop()));
    return {what: `Combine ${value.pages.length} images into one document?`, why: value.reason, evidence: [pages],
            source: {chips: value.pages.map((page, index) => ({label: `Page ${index + 1}`, document: page.document_id}))}, document: value.pages[0]?.document_id,
            confirm: {label: "Combine", run: review2Decide(path, {status: "confirmed"}, "Combined. The images are read as one document's pages; progress shows in the sidebar.", {method: "PATCH"})},
            reject: {label: "Keep separate", run: review2Decide(path, {status: "dismissed"}, "Kept as separate documents.", {method: "PATCH"})}};
  }
  if (item.kind === "unmatched") {
    const why = value.reason === "several_possible_charges" ? "Several possible charges: answer it in Questions."
      : value.date ? "No matching card or bank charge yet. Approved, it counts as spending on its own until a charge matches it."
      : "No purchase date, so it can't be placed in a period. Correct the date to match it.";
    return {what: value.name ? `Receipt from ${value.name}` : "Receipt", why, evidence: [summaryBlock("Receipt", value, {link: false})],
            source: review2RecordSource("receipt", value.id, value.document_id), document: value.document_id,
            cc: async () => {
              const view = await api(`/api/finance/records/receipt/${value.id}`);
              return {recordType: "receipt", recordId: value.id, decision: false, correctable: (view.correctable || []).filter(field => field.field === "purchase_date")};
            }};
  }
  // routing: who an upload to the family is for; routingRow's form is the decision.
  const row = routingRow(value, review2.people, () => reloadReviewV2(), "review2-route");
  row.querySelector(".routing-what a")?.remove();  // The bar opens the document.
  return {what: `Who is ${value.name || "this"} for?`, why: "Documents uploaded to the family count for nobody until you send them to a person or share them.",
          evidence: [row.querySelector(".routing-what")], source: {document: value.document_id}, document: value.document_id,
          bar: [row.querySelector(".routing-decision")]};
}
function review2RecordSource(type, id, documentId) {
  return {document: documentId, lines: ["statement", "transaction", "receipt", "bill", "income_record"].includes(type) ? () => review2Lines(type, id) : null};
}

$("review2-refresh").addEventListener("click", () => reloadReviewV2());
$("review2-reconcile").addEventListener("click", () => api("/api/finance/reconcile", {method: "POST", body: "{}"})
  .then(result => { notice(`Reconciliation proposed ${result.receipt_links} receipt links, ${result.transfers} transfers and ${result.refunds} refunds; ${result.open_issues} ambiguous cases need you.`); return reloadReviewV2(); })
  .catch(error => notice(error, true)));
$("review2-picker").addEventListener("change", () => review2Select(Number($("review2-picker").value)));
$("review2-prev").addEventListener("click", () => review2Move(-1));
$("review2-next").addEventListener("click", () => review2Move(1));
document.addEventListener("keydown", event => {
  if (currentRoute?.name !== "review" || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
  if (document.querySelector("dialog[open]") || event.target.closest("input, select, textarea, .menu")) return;
  if ($("review2-form").querySelector(".cc-form:not([hidden])")) return;  // Never while a correction is open.
  const key = event.key.toLowerCase(), press = id => { const button = $(id); if (button && !button.disabled) { event.preventDefault(); button.click(); } };
  if ((key === "j" || key === "k") && review2.entries.length) { event.preventDefault(); review2Move(key === "j" ? 1 : -1); }
  else if (key === "v") press("review2-confirm");
  else if (key === "r") press("review2-reject");
});
