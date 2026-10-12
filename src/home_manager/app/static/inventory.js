"use strict";
// Inventory's shared parts (inventory_v2.js draws the page) and the weekly check-in (docs/household.md "Run-out, cost
// per day and check-ins"). The user's answers apply at once; a free-text answer is read by the local model into a list of
// changes that apply only when confirmed.
const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const CHECKIN_BUTTONS = [["still_have", "Still have it"], ["finished_today", "Finished today"], ["finished_this_week", "Finished this week"], ["thrown_out", "Thrown out"]];
let inventoryCheckin = null;  // The latest check-in (inventory_v2.js sets it), which askedAt counts from.
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
  if (currentRoute?.name === "inventory") await it2Reload();
  else if (currentRoute?.name === "home") await reloadToday();
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

// Free-text answers: read by the model, shown as a list of changes, applied on confirmation. host: where the reading
// shows; input: the text box to clear once changes apply.
async function submitCheckinText(text, host, button, input) {
  const answer = text.trim();
  if (!answer) return;
  button.disabled = true;
  host.replaceChildren(element("p", "Reading your answer with the local model…", "muted small"));
  try {
    const {run_id} = await api("/api/inventory/checkin-runs", {method: "POST", body: JSON.stringify({answer})});
    let run;
    do { await new Promise(resolve => setTimeout(resolve, 1000)); run = await api(`/api/inventory/checkin-runs/${run_id}`); } while (["queued", "running"].includes(run.status));
    if (run.status !== "succeeded") throw new Error(run.error || `The reading ${statusLabel(run.status).toLowerCase()}.`);
    renderReading(run, host, input);
  } catch (error) { host.replaceChildren(alertBox(error.message, {tone: "error"})); }
  finally { button.disabled = false; }
}
function renderReading(run, host, input) {
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
      const {outcomes, applied, failed} = await api(`/api/inventory/checkin-runs/${run.id}/apply`, {method: "POST", body: JSON.stringify({lot_ids})});
      const firstError = outcomes.find(outcome => outcome.status === "failed")?.error;
      notice(failed ? `${applied} applied; ${failed} couldn't be: ${firstError}` : `${applied} change${applied === 1 ? "" : "s"} applied.`, Boolean(failed));
      input.value = "";
      renderReading(await api(`/api/inventory/checkin-runs/${run.id}`), host, input);
      await afterInventoryChange();
    }, "primary"));
  }
  host.replaceChildren(...nodes);
}

// Returned items (docs/household.md "Returned items"): a returned receipt line and the in-stock items it may have been,
// with its answers (Inventory's "Did this go back?"); className: the row's classes.
function returnedRow(proposal, className = "checkin-row") {
  const li = element("li", "", className), name = element("div", "", "checkin-name");
  name.append(element("strong", proposal.description),
    element("small", `Returned${proposal.merchant ? ` to ${proposal.merchant}` : ""}${proposal.returned_on ? ` on ${dateText(proposal.returned_on)}` : ""}`, "muted block"));
  const buttons = element("div", "", "checkin-buttons"); buttons.setAttribute("role", "group"); buttons.setAttribute("aria-label", `Which item went back: ${proposal.description}`);
  const answer = (lotId, message) => async () => {
    await api(`/api/inventory/returned/${proposal.receipt_item_id}`, {method: "POST", body: JSON.stringify({lot_id: lotId})});
    notice(message); await afterInventoryChange();
  };
  for (const lot of proposal.lots) {
    const label = proposal.lots.length === 1 ? `Yes, ${productName(lot)} went back` : `${productName(lot)}, bought ${lot.bought_on ? dateText(lot.bought_on) : "on an unknown date"}`;
    buttons.append(asyncButton(label, answer(lot.id, `${productName(lot)} is marked returned. Undo it from its Actions menu.`), "small"));
  }
  buttons.append(asyncButton(proposal.lots.length === 1 ? "Not this item" : "None of these", answer(null, "Kept in your inventory."), "small quiet"));
  li.append(name, buttons); return li;
}

// A lot's Actions menu (Inventory's Items table); extra: more items at the end.
function lotMenu(lot, extra = []) {
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
  return menu(`Actions for ${lot.name}`, [...items, ...extra]);
}
// Warranties (docs/household.md "Warranties"): entered by hand, or looked up and confirmed in Review.
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
  // One model job at a time: while one runs, a second click says so instead of starting another.
  if (busy.inference) { notice("Model work is running. The warranty can be looked up when it finishes.", true); return; }
  busy.inference = true; controls();
  let run_id;
  try { ({run_id} = await api(`/api/inventory/lots/${lot.id}/warranty-lookups`, {method: "POST"})); }
  catch (error) { busy.inference = false; controls(); throw error; }
  notice(`Looking up the warranty for ${lot.name}. A result waits for you in Review.`);
  let run;
  do { await new Promise(resolve => setTimeout(resolve, 1500)); run = await api(`/api/warranty-lookups/${run_id}`); } while (["queued", "running"].includes(run.status));
  if (run.status === "succeeded" && run.result?.warranty_id) { notice(`Found a warranty for ${lot.name}. Confirm it in Review.`); loadNavCounts().catch(() => {}); }
  else notice(run.result?.note || run.error || "No stated warranty was found.", run.status !== "succeeded");
  await afterInventoryChange();
}
