"use strict";
// Inventory, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/inventory.md): five tabs (Check-in, Items,
// Warranties, Returns, Item insights), each drawn on its first show. inventory.js keeps the builders both screens use
// (renderCheckin, lotMenu, returnedRow, the warranty dialog); after a change they call afterInventoryChange, which runs
// inventoryReload, pointed here while this screen shows. Every amount, date and percentage is the server's.
const IT2_TABS = ["checkin", "items", "warranties", "returns", "insights"];
const IT2_PERIODS = ["30", "90", "365", "year"];
const IT2_WARRANTY_KINDS = {manufacturer: "Manufacturer", store: "Store", extended: "Extended or protection plan"};
// tab, q, closed, period: the view (in the URL); stale: tabs to draw on their next show; generation: each tab's newest
// draw, so an older one finishing late draws nothing; checkin and returned: the header's counts' data.
const it2 = {tab: "items", q: "", closed: false, period: "90", stale: new Set(IT2_TABS), generation: {}, checkin: null, returned: [], opener: null, policy: null};

V2_SCREENS.inventory = {title: "Inventory", show: route => loadInventoryV2(route.params)};

const activateIt2Tab = wireTabs(IT2_TABS.map(tab => `it2-tab-${tab}`));
for (const tab of IT2_TABS) $(`it2-tab-${tab}`).addEventListener("tabshow", () => {
  it2.tab = tab; it2Url(); it2Action();
  if (it2.stale.has(tab)) it2Draw(tab);
});

function loadInventoryV2(params) {
  const tab = params?.get?.("tab");
  it2.q = (params?.get?.("q") || "").trim();
  // A search (from Today, Search or the assistant) always lands on Items.
  it2.tab = it2.q ? "items" : IT2_TABS.includes(tab) ? tab : "items";
  it2.closed = params?.get?.("closed") === "1";
  it2.period = IT2_PERIODS.includes(params?.get?.("period")) ? params.get("period") : "90";
  $("it2-search").value = it2.q;
  $("it2-closed").checked = it2.closed;
  for (const chip of document.querySelectorAll("#it2-insights-panel [data-period]")) chip.setAttribute("aria-pressed", String(chip.dataset.period === it2.period));
  inventoryReload = () => it2Reload();
  return it2Reload();
}
function it2Reload() {
  it2.stale = new Set(IT2_TABS);
  return pageState($("it2-state"), renderInventoryV2, {loading: "Loading inventory …", what: "inventory", needsLibrary: true, content: [$("it2-body")]});
}
async function renderInventoryV2() {
  const [checkin, returned] = await Promise.all([api("/api/inventory/checkin"), api("/api/inventory/returned")]);
  inventoryCheckin = checkin;  // askedAt (inventory.js) words each item's next question from it.
  it2.checkin = checkin; it2.returned = returned;
  it2TabCount("checkin", "Check-in", checkin.lots.length + checkin.waiting, "waiting");
  it2TabCount("returns", "Returns", returned.length, "to answer");
  activateIt2Tab(`it2-tab-${it2.tab}`);  // Draws the shown tab (tabshow).
}
// A tab's name with its count in a pill; the count is part of its accessible name ("Check-in, 2 waiting").
function it2TabCount(tab, label, count, words) {
  const button = $(`it2-tab-${tab}`);
  button.replaceChildren(label);
  if (count) {
    button.append(element("span", String(count), "nav-count attention"));
    button.setAttribute("aria-label", `${label}, ${count} ${words}`);
  } else button.removeAttribute("aria-label");
}
// The view into the URL (Layout rule 5): only what differs from the defaults, and only the shown tab's own controls.
function it2Url() {
  const next = new URLSearchParams();
  if (it2.tab !== "items") next.set("tab", it2.tab);
  if (it2.tab === "items" && it2.q) next.set("q", it2.q);
  if (it2.tab === "items" && it2.closed) next.set("closed", "1");
  if (it2.tab === "insights" && it2.period !== "90") next.set("period", it2.period);
  if (currentRoute?.name === "inventory") currentRoute.params = next;
  history.replaceState(null, "", `#/inventory${[...next].length ? `?${next}` : ""}`);
}
// The header's one primary action follows the tab: a warranty on Warranties, a return policy elsewhere.
function it2Action() {
  $("it2-add").replaceChildren(icon("plus"), it2.tab === "warranties" ? "Warranty" : "Return policy");
}
$("it2-add").addEventListener("click", () => (it2.tab === "warranties" ? openWarrantyPicker() : openPolicyDialog(null)).catch(error => notice(error, true)));

// One tab's draw: a loading line after 300 ms, then the content, or an error with Retry in the tab only.
const IT2_DRAWS = {checkin: renderCheckinTab, items: renderItemsTab, warranties: renderWarrantiesTab, returns: renderReturnsTab, insights: renderInsightsTab};
const IT2_WHAT = {checkin: "the check-in", items: "your items", warranties: "warranties", returns: "returns", insights: "item insights"};
async function it2Draw(tab) {
  const panel = $(`it2-${tab}-panel`);
  let status = panel.querySelector(":scope > .it2-tab-state");
  if (!status) { status = element("div", "", "it2-tab-state"); panel.prepend(status); }
  const generation = (it2.generation[tab] || 0) + 1;
  it2.generation[tab] = generation; it2.stale.delete(tab);
  const current = () => it2.generation[tab] === generation;
  const timer = setTimeout(() => {
    if (!current()) return;
    const line = element("p", "", "page-loading"); line.setAttribute("role", "status");
    line.append(icon("loader", "icon spin"), `Loading ${IT2_WHAT[tab]} …`);
    status.replaceChildren(line);
  }, 300);
  try {
    await IT2_DRAWS[tab](current);
    if (current()) status.replaceChildren();
  } catch (error) {
    if (!current()) return;
    it2.stale.add(tab);
    const retry = element("button", "Retry", "secondary"); retry.type = "button";
    retry.addEventListener("click", () => it2Draw(tab));
    status.replaceChildren(alertBox(`Couldn't load ${IT2_WHAT[tab]}. ${error?.message || error}`, {tone: "error", detail: error?.detail || "", action: retry}));
  } finally { clearTimeout(timer); }
}
function it2Region(title, body, id = "") {
  const region = element("section", "", "today-region");
  const heading = element("h2", title);
  if (id) { heading.id = `${id}-title`; region.id = id; region.setAttribute("aria-labelledby", heading.id); }
  region.append(heading, ...[].concat(body));
  return region;
}
function it2Table(columns, rows, className = "") {
  const table = element("table", "", `data-table ${className}`.trim()), head = table.createTHead().insertRow();
  for (const [title, cls = ""] of columns) {
    const th = element("th", "", cls); th.scope = "col";
    if (title) th.textContent = title; else th.append(element("span", "Actions", "visually-hidden"));
    head.append(th);
  }
  const body = table.createTBody();
  for (const row of rows) body.append(row);
  const wrap = element("div", "", "table-wrap"); wrap.append(table);
  return wrap;
}

// Check-in ---------------------------------------------------------------------------------------------------------
async function renderCheckinTab(current) {
  const checkin = it2.checkin || await api("/api/inventory/checkin");
  if (!current()) return;
  renderCheckin($("it2-checkin-list"), checkin);
  $("it2-checkin-form").hidden = !checkin.lots.length;
}
$("it2-checkin-form").addEventListener("submit", event => {
  event.preventDefault();
  submitCheckinText($("it2-checkin-text").value, $("it2-checkin-reading"), $("it2-checkin-submit"), $("it2-checkin-text"));
});

// Items ------------------------------------------------------------------------------------------------------------
async function renderItemsTab(current) {
  const query = new URLSearchParams({limit: 1000});
  if (it2.q) query.set("query", it2.q);
  if (it2.closed) query.set("include_closed", "true");
  const [lots, receipts] = await Promise.all([api(`/api/inventory?${query}`), api("/api/inventory/receipts-to-identify")]);
  if (!current()) return;
  it2Identify(receipts);
  if (!lots.length) {
    $("it2-items").replaceChildren(it2.q || it2.closed
      ? emptyState(it2.q ? "Nothing matches that search." : "No items yet.")
      : emptyState("No items yet. Items appear when you approve receipt lines.", homeLink("Open To check", "#/review")));
    return;
  }
  const groups = new Map();
  for (const lot of lots) { if (!groups.has(lot.category)) groups.set(lot.category, []); groups.get(lot.category).push(lot); }
  const table = element("table", "", "data-table it2-items-table"), head = table.createTHead().insertRow();
  for (const [title, cls] of [["Item", ""], ["Bought", "it2-col-bought"], ["Status", ""], ["Returnable / warranty", "it2-col-cover"], ["Next question", "it2-col-next"], ["", "it2-col-menu"]]) {
    const th = element("th", title, cls); th.scope = "col";
    if (!title) th.append(element("span", "Actions", "visually-hidden"));
    head.append(th);
  }
  for (const [category, members] of [...groups].sort(([a], [b]) => a.localeCompare(b))) {
    const body = table.createTBody(), group = body.insertRow();
    group.className = "group-row it2-group";
    const th = element("th", `${categoryLabel(category)} (${members.length})`); th.scope = "colgroup"; th.colSpan = 6;
    group.append(th);
    for (const lot of members) body.append(it2LotRow(lot));
  }
  const wrap = element("div", "", "table-wrap"); wrap.append(table);
  $("it2-items").replaceChildren(wrap);
}
function it2NextQuestion(lot) {
  return lot.status === "in_stock" ? (lot.consumable ? askedAt(lot.next_check_on) : "Not asked (lasts)") : "—";
}
function it2WarrantyText(warranty) {
  const text = warranty.lifetime ? "Lifetime warranty" : `${{manufacturer: "Warranty", store: "Store warranty", extended: "Extended warranty"}[warranty.kind]} to ${dateText(warranty.expires_on)}`;
  return warranty.review_status === "proposed" ? `${text} (found online, confirm in To check)` : text;
}
function it2LotRow(lot) {
  const tr = document.createElement("tr");
  const name = cell(tr, "");
  name.append(element("strong", productName(lot)));
  if (lot.units && lot.units !== "1") name.append(element("small", `Quantity ${lot.units}`, "muted block"));
  // Under 700px the Bought and Next question columns fold into this line.
  name.append(element("small", [lot.bought_on ? `Bought ${dateText(lot.bought_on)}` : "", lot.status === "in_stock" ? `Next: ${it2NextQuestion(lot)}` : ""].filter(Boolean).join(" · "), "muted block it2-inline"));
  cell(tr, lot.bought_on ? dateText(lot.bought_on) : "—").className = "it2-col-bought";
  const state = cell(tr, "");
  state.append(statusBadge(lot.status));
  if (lot.closed_on) state.append(element("small", `${lot.closed_precision_days ? "around " : ""}${dateText(lot.closed_on)}`, "muted block"));
  if (lot.opened_on) state.append(element("small", `Opened ${dateText(lot.opened_on)}`, "muted block"));
  const cover = cell(tr, ""); cover.className = "it2-col-cover";
  for (const warranty of lot.warranties || []) {
    const line = element("span", "", "it2-cover-line");
    line.append(icon("shield-check"), it2WarrantyText(warranty));
    line.title = warranty.quote ? `“${warranty.quote}” — ${warranty.source_title || warranty.source_url}` : warranty.note || "";
    cover.append(line);
  }
  const returnWindow = returnText(lot);
  if (returnWindow) { const line = element("span", returnWindow, `it2-cover-line ${lot.returnable ? "" : "muted"}`.trim()); line.title = lot.return_note || ""; cover.append(line); }
  if (cover.childNodes.length) {
    // Under 560px this column folds into the item's cell too, so the row's menu stays on screen.
    const folded = element("div", "", "it2-inline-cover");
    folded.append(...[...cover.childNodes].map(node => node.cloneNode(true)));
    name.append(folded);
  } else cover.append(element("span", "—", "muted"));
  cell(tr, it2NextQuestion(lot)).className = "it2-col-next";
  const actions = cell(tr, ""); actions.className = "it2-col-menu";
  actions.append(lotMenu(lot));
  return tr;
}
function it2Identify(receipts) {
  $("it2-identify").hidden = !receipts.length;
  $("it2-identify-list").replaceChildren(...receipts.map(receipt => {
    const li = element("li", "", "needs-row it2-identify-row"), text = element("div");
    text.append(element("strong", `${receipt.merchant || "Receipt"} · ${receipt.purchase_date ? dateText(receipt.purchase_date) : "no date"}`),
                element("small", `${receipt.unresolved} of ${receipt.lines} lines not identified`, "muted"));
    const actions = element("div", "", "it2-row-actions");
    const identify = asyncButton("Identify items", async () => {
      await api(`/api/receipts/${receipt.id}/item-resolution-runs`, {method: "POST"});
      notice("Identifying items. Proposals appear in To check as they're found.");
    }, "link-button");
    const which = receipt.merchant ? `the ${receipt.merchant} receipt` : "the receipt";
    identify.setAttribute("aria-label", `Identify items on ${which}`);
    const open = homeLink("Open", `#/documents/${receipt.document_id}`, "needs-action");
    open.setAttribute("aria-label", `Open ${which}`);
    actions.append(identify, open);
    li.append(icon("file", "icon needs-icon"), text, actions);
    return li;
  }));
}
$("it2-search").addEventListener("search", () => it2Search());
$("it2-search").addEventListener("keydown", event => { if (event.key === "Enter") it2Search(); });
$("it2-closed").addEventListener("change", () => { it2.closed = $("it2-closed").checked; it2Url(); it2Draw("items"); });
function it2Search() { it2.q = $("it2-search").value.trim(); it2Url(); it2Draw("items"); }

// Warranties -------------------------------------------------------------------------------------------------------
async function renderWarrantiesTab(current) {
  const [list, ending] = await Promise.all([api("/api/warranties"), api("/api/warranties/expiring?days=30")]);
  if (!current()) return;
  const panel = $("it2-warranties-panel"), status = panel.querySelector(":scope > .it2-tab-state");
  const parts = [];
  const proposed = list.filter(warranty => warranty.review_status === "proposed");
  if (proposed.length) {
    const ul = element("ul", "", "needs-list"), li = element("li", "", "needs-row attention"), text = element("div");
    text.append(element("strong", `${proposed.length} ${proposed.length === 1 ? "warranty found online waits" : "warranties found online wait"} in To check`),
                element("small", "They show on your items once you confirm them.", "muted"));
    li.append(icon("alert", "icon needs-icon"), text, homeLink("Open To check", "#/review", "needs-action"));
    ul.append(li); parts.push(ul);
  }
  const confirmed = list.filter(warranty => warranty.review_status === "verified");
  if (!confirmed.length) {
    parts.push(emptyState("No warranties yet. Add one for an item that lasts, or look one up from the item's Actions menu on Items."));
  } else {
    const endingIds = new Set(ending.map(warranty => warranty.id)), today = todayIso();
    parts.push(it2Table([["Item"], ["Kind", "it2-col-kind"], ["Ends"], ["Source", "it2-col-source"], ["Status"], [""]],
                        confirmed.map(warranty => it2WarrantyRow(warranty, endingIds.has(warranty.id) ? "warranty_ending" :
                          !warranty.lifetime && warranty.expires_on < today ? "ended" : "warranty_active")), "it2-warranties-table"));
  }
  panel.replaceChildren(...(status ? [status] : []), ...parts);
}
function it2WarrantyRow(warranty, state) {
  const tr = document.createElement("tr"), item = cell(tr, ""), name = productName(warranty);
  item.append(element("strong", name));
  item.append(element("small", [warranty.merchant, warranty.lot_status !== "in_stock" ? statusLabel(warranty.lot_status) : ""].filter(Boolean).join(" · "), "muted block"));
  cell(tr, IT2_WARRANTY_KINDS[warranty.kind] || warranty.kind).className = "it2-col-kind";
  cell(tr, warranty.lifetime ? "Lifetime" : dateText(warranty.expires_on));
  const source = cell(tr, ""); source.className = "it2-col-source";
  source.append(warranty.source === "user" ? "You added" : "Found online");
  // The page it was found on, as text: never a link out of the app.
  if (warranty.source !== "user" && warranty.source_title) source.append(element("small", warranty.source_title, "muted block"));
  if (warranty.note) source.append(element("small", warranty.note, "muted block"));
  cell(tr, "").append(statusBadge(state));
  const remove = element("button", "Remove"); remove.type = "button";
  remove.addEventListener("click", async () => {
    try {
      if (!await confirmAction({title: `Remove this warranty for ${name}?`, message: "It stops showing on the item. You can add it again later.", confirmLabel: "Remove warranty", danger: true})) return;
      await api(`/api/warranties/${warranty.id}`, {method: "DELETE"});
      notice("Warranty removed."); await afterInventoryChange();
    } catch (error) { notice(error, true); }
  });
  cell(tr, "").append(menu(`Actions for ${name}`, [remove]));
  return tr;
}
// "+ Warranty": choose an item that lasts, then the shared warranty dialog (inventory.js openWarrantyDialog).
let it2WarrantyLots = [];
async function openWarrantyPicker() {
  it2.opener = document.activeElement;
  const lots = await api("/api/inventory?limit=1000");
  it2WarrantyLots = lots.filter(lot => !lot.consumable && lot.bought_on && lot.status === "in_stock");
  const select = $("it2-warranty-lot");
  select.replaceChildren(...it2WarrantyLots.map(lot => new Option(`${productName(lot)} · bought ${dateText(lot.bought_on)}`, lot.id)));
  if (!it2WarrantyLots.length) select.add(new Option("No items that last are in stock", ""));
  select.disabled = !it2WarrantyLots.length; $("it2-warranty-pick-next").disabled = !it2WarrantyLots.length;
  $("it2-warranty-pick").showModal();
  select.focus();
}
$("it2-warranty-pick-cancel").addEventListener("click", () => { $("it2-warranty-pick").close(); it2.opener?.focus?.(); });
$("it2-warranty-pick-form").addEventListener("submit", event => {
  event.preventDefault();
  const lot = it2WarrantyLots.find(row => String(row.id) === $("it2-warranty-lot").value);
  if (!lot) return;
  $("it2-warranty-pick").close();
  openWarrantyDialog(lot);
});

// Returns ----------------------------------------------------------------------------------------------------------
async function renderReturnsTab(current) {
  const [returned, closing, policies] = await Promise.all([api("/api/inventory/returned"), api("/api/inventory/returns?days=14"), api("/api/return-policies")]);
  if (!current()) return;
  // Did this go back? A decision, so it comes first, and only when there is something to answer.
  $("it2-returned").hidden = !returned.length;
  const list = element("ul", "", "needs-list");
  for (const proposal of returned) {
    const li = returnedRow(proposal, "needs-row attention it2-returned-row");
    li.prepend(icon("undo-2", "icon needs-icon"));
    list.append(li);
  }
  $("it2-returned-body").replaceChildren(list);
  if (!closing.length) $("it2-closing-body").replaceChildren(emptyState("No return windows close in the next 14 days."));
  else {
    const ul = element("ul", "", "dated-list");
    for (const lot of closing) {
      const li = element("li", "", "dated-row it2-closing-row"), when = element("span", "", "dated-when"), text = element("div");
      when.append(dateDisplay(lot.return_by));
      text.append(element("strong", productName(lot)), element("small", [lot.merchant, lot.bought_on ? `bought ${dateText(lot.bought_on)}` : ""].filter(Boolean).join(" · "), "muted"));
      li.append(when, text, element("span", returnText(lot), "small it2-closing-text"));
      ul.append(li);
    }
    $("it2-closing-body").replaceChildren(ul);
  }
  if (!policies.length) { $("it2-policies-body").replaceChildren(emptyState("No store policies. Add the stores you shop at.")); return; }
  $("it2-policies-body").replaceChildren(it2Table([["Store"], ["Days", "numeric"], ["Notes"], ["Source"], [""]], policies.map(policy => {
    const tr = document.createElement("tr");
    cell(tr, policy.merchant); cell(tr, policy.days ?? "No limit").className = "numeric"; cell(tr, policy.note || "—");
    cell(tr, policy.source === "typical" ? "Typical (check your receipt)" : "Yours");
    const change = element("button", "Change"); change.type = "button";
    change.addEventListener("click", () => openPolicyDialog(policy).catch(error => notice(error, true)));
    const remove = element("button", "Remove"); remove.type = "button";
    remove.addEventListener("click", async () => {
      try {
        if (!await confirmAction({title: `Remove the ${policy.merchant} policy?`, message: "Items from this store will have no return window unless their receipt prints one.",
                                  confirmLabel: "Remove policy", danger: true})) return;
        await api(`/api/return-policies/${policy.id}`, {method: "DELETE"}); notice("Policy removed."); await afterInventoryChange();
      } catch (error) { notice(error, true); }
    });
    cell(tr, "").append(menu(`Actions for the ${policy.merchant} policy`, [change, remove]));
    return tr;
  }), "it2-policies-table"));
}
async function openPolicyDialog(policy) {
  it2.opener = document.activeElement; it2.policy = policy;
  const form = $("it2-policy-form");
  form.reset(); clearFieldErrors(form);
  $("it2-policy-title").textContent = policy ? `Change the ${policy.merchant} policy` : "Add a return policy";
  $("it2-policy-merchant").value = policy?.merchant || "";
  $("it2-policy-days").value = policy?.days ?? "";
  $("it2-policy-note").value = policy?.note || "";
  $("it2-policy-dialog").showModal();
  $("it2-policy-merchant").focus();
}
function it2PolicyClose() { $("it2-policy-dialog").close(); it2.opener?.focus?.(); }
$("it2-policy-cancel").addEventListener("click", it2PolicyClose);
$("it2-policy-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = $("it2-policy-form"), merchant = $("it2-policy-merchant").value.trim(), days = $("it2-policy-days").value.trim();
  clearFieldErrors(form);
  if (!merchant) { fieldError(form, "merchant", "Enter the store's name."); return; }
  $("it2-policy-save").disabled = true;
  try {
    const saved = await api("/api/return-policies", {method: "PUT", body: JSON.stringify({merchant, days: days === "" ? null : Number(days), note: $("it2-policy-note").value.trim()})});
    it2PolicyClose();
    notice(`Saved: ${saved.merchant}, ${saved.days ?? "no fixed"} ${saved.days === 1 ? "day" : "days"}${saved.days === null ? " limit" : ""}.`);
    await afterInventoryChange();
  } catch (error) {
    fieldError(form, errorField(error) || (/days/i.test(error.message) ? "days" : null), error.message || String(error));
  } finally { $("it2-policy-save").disabled = false; }
});

// Item insights ----------------------------------------------------------------------------------------------------
function it2Tile(label, main, sub = []) {
  const tile = element("div", "", "figure-tile");
  tile.append(element("p", label, "figure-label"), main);
  for (const line of sub.filter(Boolean)) tile.append(element("p", line, "figure-sub"));
  return tile;
}
function it2Count(n, one, many) { return `${n} ${n === 1 ? one : many}`; }
async function renderInsightsTab(current) {
  const data = await api(`/api/inventory/insights?${new URLSearchParams({period: it2.period})}`);
  if (!current()) return;
  const {figures, counts} = data, approximate = data.consumption.some(row => row.approximate);
  const tiles = element("div", "", "it2-tiles");
  tiles.append(
    it2Tile("Spent on items", figure(figures.spending, {signed: false}), [it2Count(counts.purchases, "purchase", "purchases"), `${dateText(data.period.start)} to ${dateText(data.period.end)}`]),
    it2Tile("Cost per 30 days", figure(figures.per_30_days, {signed: false}), counts.finished_products
      ? [`from ${it2Count(counts.finished_products, "finished product", "finished products")}`, approximate ? "~ approximate" : ""]
      : ["Mark items finished in the check-in to see cost per day."]),
    it2Tile("Thrown out", figure(figures.waste, {signed: false}), [it2Count(counts.thrown_out, "item", "items")]),
    it2Tile("Next month's consumables", figure(figures.forecast, {signed: false}), [`for ${monthText(data.month)}`, "projected from finished items"]));
  fitFigures(tiles);
  const rises = data.increases.length ? it2Table([["Product"], ["Price per unit, first → last", "numeric"], ["Went up by", "numeric"]], data.increases.map(row => {
    const tr = document.createElement("tr"), product = cell(tr, "");
    product.append(element("strong", row.product));
    if (row.package_size_changed) product.append(element("small", `smaller pack: ${row.first.size} → ${row.last.size}`, "muted block"));
    const prices = cell(tr, ""); prices.className = "numeric";
    prices.append(amount(row.first.unit_price, {signed: false}), " → ", amount(row.last.unit_price, {signed: false}), element("small", row.per, "muted block"));
    cell(tr, `↑ ${row.change_percent}`).className = "numeric";
    return tr;
  })) : emptyState("No prices went up in this period.");
  const most = data.top_products.length ? it2Table([["Product"], ["Purchases", "numeric"], ["Spent", "numeric"]], data.top_products.map(row => {
    const tr = document.createElement("tr");
    cell(tr, row.product); cell(tr, String(row.purchases)).className = "numeric";
    const spent = cell(tr, ""); spent.className = "numeric"; spent.append(amount(row.spent, {signed: false}));
    return tr;
  })) : emptyState("No purchases in this period.");
  const pair = element("div", "", "it2-pair");
  pair.append(it2Region("Prices that went up", rises), it2Region("Costs most", most));
  let waste;
  if (!data.waste_items.length) waste = emptyState("Nothing thrown out in this period.");
  else {
    waste = element("ul", "", "dated-list");
    for (const row of data.waste_items) {
      const li = element("li", "", "dated-row"), when = element("span", "", "dated-when"), cost = element("span", "", "dated-amount");
      when.append(dateDisplay(row.thrown_out_on));
      // Waste is money spent, shown with a minus and never in red (MASTER.md "Meaning is fixed").
      cost.append("−", amount(row.cost, {signed: false}));
      li.append(when, element("span", row.product), cost);
      waste.append(li);
    }
  }
  const notes = element("ul", "", "it2-notes muted small");
  for (const note of data.notes) notes.append(element("li", note));
  $("it2-insights").replaceChildren(tiles, pair, it2Region("Thrown out", waste), notes);
}
for (const chip of document.querySelectorAll("#it2-insights-panel [data-period]")) chip.addEventListener("click", () => {
  it2.period = chip.dataset.period;
  for (const other of document.querySelectorAll("#it2-insights-panel [data-period]")) other.setAttribute("aria-pressed", String(other === chip));
  it2Url(); it2Draw("insights");
});
