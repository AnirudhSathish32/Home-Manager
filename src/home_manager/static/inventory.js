"use strict";
// Inventory and the weekly check-in (docs/money-review-inventory.md §4). The user's answers apply at once;
// a free-text answer is read by the local model into a list of changes that apply only when confirmed.
const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const CHECKIN_BUTTONS = [["still_have", "Still have it"], ["finished_today", "Finished today"], ["finished_this_week", "Finished this week"], ["thrown_out", "Thrown out"]];
let inventoryLoad = 0, inventoryCheckin = null;
function askedAt(nextCheck) {
  // A lot's question is asked at the first weekly check-in on or after it is due.
  if (!nextCheck || !inventoryCheckin) return nextCheck ? dateText(nextCheck) : "—";
  if (nextCheck <= inventoryCheckin.checkin_on) return "This week's check-in";
  const day = new Date(`${inventoryCheckin.next_checkin_on}T12:00:00`);
  while (isoDay(day) < nextCheck) day.setDate(day.getDate() + 7);
  return `${WEEKDAY_NAMES[inventoryCheckin.weekday]} check-in, ${dateText(isoDay(day))}`;
}

function productName(lot) {
  // The brand is left out when the product name already starts with it ("Dawn Ultra Dish Soap").
  const brand = lot.brand && !(lot.name || "").toLowerCase().startsWith(lot.brand.toLowerCase()) ? lot.brand : null;
  return [brand, lot.name, lot.size_text].filter(Boolean).join(" · ");
}
function returnText(lot) {
  // Only non-food items carry a return window; its source is in the tooltip.
  if (!lot.openable || !lot.return_source) return "";
  if (lot.return_days === 0) return "Not returnable (printed on the receipt)";
  if (!lot.return_by) return lot.returnable ? "Returnable: no fixed time limit" : "";
  if (lot.returnable) return `Returnable until ${dateText(lot.return_by)}`;
  if (lot.opened_on && todayIso() <= lot.return_by) return `Opened: may not be returnable (window ends ${dateText(lot.return_by)})`;
  // A window that ended long ago is noise; mention it only for two weeks after it closes.
  const recent = new Date(`${lot.return_by}T12:00:00`) >= new Date(Date.now() - 14 * 86400000);
  return lot.status === "in_stock" && recent ? `Return window ended ${dateText(lot.return_by)}` : "";
}
function sinceText(day) {
  if (!day) return "";
  const days = Math.round((new Date(`${todayIso()}T12:00:00`) - new Date(`${day}T12:00:00`)) / 86400000);
  return days <= 0 ? "today" : days === 1 ? "yesterday" : `${days} days ago`;
}
async function afterInventoryChange() {
  loadNavCounts().catch(() => {});
  if (currentRoute?.name === "inventory") await loadInventory();
  else if (currentRoute?.name === "home") await renderHomeExtras();
}
async function answerLot(lot, answer, source = "checkin") {
  await api(`/api/inventory/lots/${lot.id}/checkin-answer`, {method: "POST", body: JSON.stringify({answer, source})});
  const shown = toast(`${lot.name}: ${CHECKIN_BUTTONS.find(([key]) => key === answer)?.[1] || statusLabel(answer)}.`, {timeout: 8000});
  const undo = element("button", "Undo", "small"); undo.type = "button";
  undo.addEventListener("click", async () => {
    try { await api(`/api/inventory/lots/${lot.id}/undo`, {method: "POST"}); shown.remove(); notice("Undone."); await afterInventoryChange(); } catch (error) { notice(error, true); }
  });
  shown.querySelector(".toast-body").append(undo);
  await afterInventoryChange();
}

// The check-in card, on Inventory and on Home.
function renderCheckin(target, checkin, {compact = false} = {}) {
  const nodes = [];
  const when = `${WEEKDAY_NAMES[checkin.weekday]} check-in${checkin.checkin_on === todayIso() ? " · today" : ` · since ${dateText(checkin.checkin_on)}`}`;
  if (!checkin.lots.length) {
    nodes.push(element("p", `Nothing to ask about. The next check-in is ${dateText(checkin.next_checkin_on)}.`, "muted"));
    target.replaceChildren(...nodes); return;
  }
  nodes.push(element("p", `${when}. Did any of these run out?${checkin.waiting ? ` ${checkin.waiting} more wait for next time.` : ""}`, "muted small"));
  const list = element("ul", "", "checkin-list");
  for (const lot of compact ? checkin.lots.slice(0, 5) : checkin.lots) {
    const li = element("li", "", "checkin-row");
    const name = element("div", "", "checkin-name");
    name.append(element("strong", productName(lot)), element("small", `Bought ${lot.bought_on ? `${dateText(lot.bought_on)} (${sinceText(lot.bought_on)})` : "on an unknown date"}`, "muted block"));
    const buttons = element("div", "", "checkin-buttons"); buttons.setAttribute("role", "group"); buttons.setAttribute("aria-label", `Answer for ${lot.name}`);
    for (const [answer, label] of CHECKIN_BUTTONS) buttons.append(asyncButton(label, () => answerLot(lot, answer), answer === "still_have" ? "small" : "small quiet"));
    li.append(name, buttons); list.append(li);
  }
  nodes.push(list);
  if (compact && checkin.lots.length > 5) nodes.push(homeLink(`Answer all ${checkin.lots.length} on the Inventory page`, "#/inventory"));
  target.replaceChildren(...nodes);
}

// Free-text answers: read by the model, shown as a list of changes, applied on confirmation.
$("checkin-text-form").addEventListener("submit", async event => {
  event.preventDefault();
  const answer = $("checkin-text").value.trim();
  if (!answer) return;
  const submit = $("checkin-text-submit");
  submit.disabled = true;
  $("checkin-reading").replaceChildren(element("p", "Reading your answer with the local model…", "muted small"));
  try {
    const {run_id} = await api("/api/inventory/checkin-runs", {method: "POST", body: JSON.stringify({answer})});
    let run;
    do { await new Promise(resolve => setTimeout(resolve, 1000)); run = await api(`/api/inventory/checkin-runs/${run_id}`); } while (["queued", "running"].includes(run.status));
    if (run.status !== "succeeded") throw new Error(run.error || `The reading ${statusLabel(run.status).toLowerCase()}.`);
    renderReading(run);
  } catch (error) { $("checkin-reading").replaceChildren(alertBox(error.message, {tone: "error"})); }
  finally { submit.disabled = false; }
});
function renderReading(run) {
  const result = run.result, nodes = [element("h3", "Confirm these changes")];
  const labels = {still_have: "Still have it", finished: "Finished", thrown_out: "Thrown out"};
  const list = element("ul", "", "checkin-list");
  for (const update of result.updates) {
    const li = element("li", "", "checkin-row"), check = document.createElement("input");
    check.type = "checkbox"; check.checked = !result.applied.includes(update.lot_id); check.disabled = result.applied.includes(update.lot_id); check.value = update.lot_id;
    const label = element("label", "", "compact-check");
    const when = update.effective_on ? ` · ${update.precision_days ? `around ${dateText(update.effective_on)}` : dateText(update.effective_on)}` : "";
    label.append(check, document.createTextNode(` ${update.product}: ${labels[update.event]}${when}${result.applied.includes(update.lot_id) ? " (applied)" : ""}`));
    li.append(label); list.append(li);
  }
  if (!result.updates.length) nodes.push(element("p", "The answer didn't name any item in this check-in.", "muted"));
  else nodes.push(list);
  for (const item of result.set_aside) nodes.push(element("p", `Set aside: ${item.reason}`, "muted small"));
  if (result.not_understood) nodes.push(element("p", `Not matched to an item: “${result.not_understood}”.`, "muted small"));
  if (result.updates.some(update => !result.applied.includes(update.lot_id))) {
    nodes.push(asyncButton("Apply selected changes", async () => {
      const lot_ids = [...list.querySelectorAll("input:checked:not(:disabled)")].map(input => Number(input.value));
      if (!lot_ids.length) { notice("Select at least one change.", true); return; }
      const {outcomes} = await api(`/api/inventory/checkin-runs/${run.id}/apply`, {method: "POST", body: JSON.stringify({lot_ids})});
      const failed = outcomes.filter(outcome => outcome.status === "failed");
      notice(failed.length ? `${outcomes.length - failed.length} applied; ${failed.length} couldn't be: ${failed[0].error}` : `${outcomes.length} change${outcomes.length === 1 ? "" : "s"} applied.`, Boolean(failed.length));
      $("checkin-text").value = "";
      renderReading(await api(`/api/inventory/checkin-runs/${run.id}`));
      await afterInventoryChange();
    }, "primary"));
  }
  $("checkin-reading").replaceChildren(...nodes);
}

// Inventory page.
async function loadInventory() {
  if (!configured) { $("inventory-groups").replaceChildren(emptyState("Set up your library to track household items.")); return; }
  const load = ++inventoryLoad, query = new URLSearchParams({limit: 1000});
  if ($("inventory-search").value.trim()) query.set("query", $("inventory-search").value.trim());
  if ($("inventory-closed").checked) query.set("include_closed", "true");
  const [lots, checkin, receipts, policies] = await Promise.all([api(`/api/inventory?${query}`), api("/api/inventory/checkin"),
    api("/api/inventory/receipts-to-identify"), api("/api/return-policies")]);
  if (load !== inventoryLoad) return;
  renderPolicies(policies);
  inventoryCheckin = checkin;
  renderCheckin($("checkin-content"), checkin);
  $("checkin-text-form").hidden = !checkin.lots.length;
  const groups = new Map();
  for (const lot of lots) { if (!groups.has(lot.category)) groups.set(lot.category, []); groups.get(lot.category).push(lot); }
  const panels = [];
  for (const [category, members] of [...groups].sort(([a], [b]) => a.localeCompare(b))) {
    const panel = element("section", "", "panel"); panel.append(element("h2", `${category} (${members.length})`));
    const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table");
    const head = document.createElement("thead"), headRow = document.createElement("tr");
    for (const title of ["Item", "Bought", "Status", "Next question", ""]) { const th = element("th", title); th.scope = "col"; headRow.append(th); }
    head.append(headRow);
    const body = document.createElement("tbody");
    for (const lot of members) body.append(inventoryRow(lot));
    table.append(head, body); wrap.append(table); panel.append(wrap); panels.push(panel);
  }
  $("inventory-groups").replaceChildren(...(panels.length ? panels : [emptyState($("inventory-search").value.trim() ? "Nothing matches that search." :
    "No items yet. Approve product names for receipt lines in Review, and they appear here.")]));
  const items = receipts.map(receipt => {
    const li = element("li", "", "review-item");
    li.append(element("strong", receipt.merchant || "Receipt"), element("span", `${receipt.purchase_date ? dateText(receipt.purchase_date) : "No date"} · ${receipt.unresolved} of ${receipt.lines} lines not identified`, "block muted small"));
    const row = element("div", "", "review-actions");
    row.append(asyncButton("Identify items", async () => {
      await api(`/api/receipts/${receipt.id}/item-resolution-runs`, {method: "POST"});
      notice("Identifying items. Proposals appear in Review as they're found.");
    }), homeLink("Open receipt", `#/documents/${receipt.document_id}`));
    li.append(row); return li;
  });
  $("identify-receipts").replaceChildren(...(items.length ? items : [element("li", "Every receipt line has a product or a proposal.", "muted")]));
}
function inventoryRow(lot) {
  const tr = document.createElement("tr");
  const name = cell(tr, ""); name.append(element("strong", productName(lot)));
  if (lot.units && lot.units !== "1") name.append(element("small", `Quantity ${lot.units}`, "muted block"));
  cell(tr, lot.bought_on ? `${dateText(lot.bought_on)}` : "—");
  const state = cell(tr, ""); state.append(statusBadge(lot.status));
  if (lot.closed_on) state.append(element("small", `${lot.closed_precision_days ? "around " : ""}${dateText(lot.closed_on)}`, "muted block"));
  if (lot.opened_on) state.append(element("small", `Opened ${dateText(lot.opened_on)}`, "muted block"));
  for (const warranty of lot.warranties || []) {
    const text = warranty.lifetime ? "Lifetime warranty" : `${{manufacturer: "Warranty", store: "Store warranty", extended: "Extended warranty"}[warranty.kind]} until ${dateText(warranty.expires_on)}`;
    const note = element("small", warranty.review_status === "proposed" ? `${text} (found online, confirm in Review)` : text, "warranty-note block");
    note.title = warranty.quote ? `“${warranty.quote}” — ${warranty.source_title || warranty.source_url}` : warranty.note || "";
    state.append(note);
  }
  const returnWindow = returnText(lot);
  if (returnWindow) { const note = element("small", returnWindow, `return-note block ${lot.returnable ? "" : "muted"}`); note.title = lot.return_note || ""; state.append(note); }
  cell(tr, lot.status === "in_stock" ? (lot.consumable ? askedAt(lot.next_check_on) : "Not asked (lasts)") : "—");
  const actions = cell(tr, "");
  const items = [];
  const add = (label, run) => { const button = element("button", label); button.type = "button"; button.addEventListener("click", () => run().catch(error => notice(error, true))); items.push(button); };
  if (lot.status === "in_stock" && lot.openable && !lot.opened_on) add("Mark opened", async () => {
    await api(`/api/inventory/lots/${lot.id}/events`, {method: "POST", body: JSON.stringify({event: "opened"})});
    notice(lot.return_by ? "Marked opened. Opened items usually can't be returned." : "Marked opened."); await afterInventoryChange();
  });
  if (lot.status === "in_stock") {
    for (const [answer, label] of [["still_have", "Still have it"], ["finished_today", "Finished today"], ["finished_this_week", "Finished this week"],
                                   ["thrown_out", "Thrown out today"], ["thrown_out_this_week", "Thrown out this week"]]) add(label, () => answerLot(lot, answer, "manual"));
  } else add("Reopen", async () => { await api(`/api/inventory/lots/${lot.id}/events`, {method: "POST", body: JSON.stringify({event: "reopened"})}); notice("Reopened."); await afterInventoryChange(); });
  if (!lot.consumable && lot.bought_on) {
    add("Add warranty…", async () => openWarrantyDialog(lot));
    if (lot.warranty_suggested && !(lot.warranties || []).some(warranty => warranty.kind === "manufacturer")) add("Look up warranty", () => lookUpWarranty(lot));
    for (const warranty of (lot.warranties || []).filter(warranty => warranty.source === "user")) add(`Remove ${warranty.kind} warranty`, async () => {
      await api(`/api/warranties/${warranty.id}`, {method: "DELETE"}); notice("Warranty removed."); await afterInventoryChange();
    });
  }
  add("Undo last change", async () => { await api(`/api/inventory/lots/${lot.id}/undo`, {method: "POST"}); notice("Undone."); await afterInventoryChange(); });
  add("History", async () => {
    const events = await api(`/api/inventory/lots/${lot.id}/history`);
    const existing = tr.nextElementSibling?.classList.contains("history-row") ? tr.nextElementSibling : null;
    if (existing) { existing.remove(); return; }
    const row = element("tr", "", "history-row"), td = document.createElement("td"); td.colSpan = 5;
    const list = element("ul", "", "finance-list");
    for (const event of events) list.append(element("li", `${dateText(event.effective_on)} · ${statusLabel(event.event)}${event.precision_days ? ` (±${event.precision_days} days)` : ""} · ${{approval: "approved", manual: "you, on this page", checkin: "check-in", checkin_text: "check-in in your words"}[event.source] || event.source}`));
    td.append(list); row.append(td); tr.after(row);
  });
  actions.append(menu(`Actions for ${lot.name}`, items));
  return tr;
}
// Warranties (docs/warranties-assistant-processing.md §1): entered by hand, or looked up and confirmed in Review.
let warrantyLot = null;
function openWarrantyDialog(lot) {
  warrantyLot = lot;
  $("warranty-dialog-item").textContent = `${productName(lot)} · bought ${dateText(lot.bought_on)}${lot.merchant ? ` at ${lot.merchant}` : ""}`;
  for (const id of ["warranty-months", "warranty-note"]) $(id).value = "";
  $("warranty-lifetime").checked = false; $("warranty-months").disabled = false; $("warranty-dialog-error").textContent = "";
  $("warranty-dialog").showModal(); $("warranty-months").focus();
}
$("warranty-lifetime").addEventListener("change", () => { $("warranty-months").disabled = $("warranty-lifetime").checked; });
$("cancel-warranty").addEventListener("click", () => $("warranty-dialog").close());
$("warranty-form").addEventListener("submit", async event => {
  event.preventDefault();
  const lifetime = $("warranty-lifetime").checked, months = $("warranty-months").value.trim();
  try {
    await api(`/api/inventory/lots/${warrantyLot.id}/warranties`, {method: "POST", body: JSON.stringify({kind: $("warranty-kind").value, lifetime,
      months: lifetime || !months ? null : Number(months), note: $("warranty-note").value.trim()})});
    $("warranty-dialog").close(); notice("Warranty saved."); await afterInventoryChange();
  } catch (error) { $("warranty-dialog-error").textContent = error.message; }
});
async function lookUpWarranty(lot) {
  const {run_id} = await api(`/api/inventory/lots/${lot.id}/warranty-lookups`, {method: "POST"});
  notice(`Looking up the warranty for ${lot.name}. A result waits for you in Review.`);
  let run;
  do { await new Promise(resolve => setTimeout(resolve, 1500)); run = await api(`/api/warranty-lookups/${run_id}`); } while (["queued", "running"].includes(run.status));
  if (run.status === "succeeded" && run.result?.warranty_id) { notice(`Found a warranty for ${lot.name}. Confirm it in Review.`); loadNavCounts().catch(() => {}); }
  else notice(run.result?.note || run.error || "No stated warranty was found.", run.status !== "succeeded");
  await afterInventoryChange();
}

function renderPolicies(policies) {
  const rows = policies.map(policy => {
    const tr = document.createElement("tr");
    cell(tr, policy.merchant); cell(tr, policy.days ?? "No limit").className = "numeric"; cell(tr, policy.note || "—");
    cell(tr, policy.source === "typical" ? "Typical (check your receipt)" : "Yours");
    const actions = cell(tr, "");
    actions.append(asyncButton("Change", async () => {
      $("policy-merchant").value = policy.merchant; $("policy-days").value = policy.days ?? ""; $("policy-note").value = policy.note; $("policy-days").focus();
    }, "small quiet"), asyncButton("Remove", async () => {
      if (!await confirmAction({title: `Remove the ${policy.merchant} policy?`, message: "Items from this store will have no return window unless their receipt prints one.", confirmLabel: "Remove policy"})) return;
      await api(`/api/return-policies/${policy.id}`, {method: "DELETE"}); notice("Policy removed."); await loadInventory();
    }, "small quiet"));
    return tr;
  });
  if (rows.length) $("policy-rows").replaceChildren(...rows); else tableMessage($("policy-rows"), 5, "No store policies. Add the stores you shop at.");
}
$("policy-form").addEventListener("submit", async event => {
  event.preventDefault();
  const days = $("policy-days").value.trim();
  try {
    const policy = await api("/api/return-policies", {method: "PUT", body: JSON.stringify({merchant: $("policy-merchant").value.trim(), days: days === "" ? null : Number(days), note: $("policy-note").value.trim()})});
    notice(`Saved: ${policy.merchant}, ${policy.days ?? "no fixed"} ${policy.days === 1 ? "day" : "days"}${policy.days === null ? " limit" : ""}.`);
    for (const id of ["policy-merchant", "policy-days", "policy-note"]) $(id).value = "";
    await loadInventory();
  } catch (error) { notice(error, true); }
});
$("inventory-search").addEventListener("search", () => loadInventory().catch(error => notice(error, true)));
$("inventory-search").addEventListener("keydown", event => { if (event.key === "Enter") loadInventory().catch(error => notice(error, true)); });
$("inventory-closed").addEventListener("change", () => loadInventory().catch(error => notice(error, true)));
