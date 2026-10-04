"use strict";
// Donate documents (docs/private-reliability-testing.md): check a record against its original, field by field, then
// save a donation file the person hands over themselves. A check is a label for testing; it never changes records.
const DONATE_TYPES = {receipt: "Receipt", bank_statement: "Bank statement", credit_card_statement: "Card statement", paystub: "Pay stub",
                      statement: "Statement", income_record: "Pay stub"};
const DONATE_STATES = [["correct", "Correct"], ["fixed", "Fixed"], ["unchecked", "Not checked"]];
const PAY_LINE_GROUPS = [["earnings", "Earnings"], ["pre_tax", "Before tax"], ["tax", "Tax"], ["post_tax", "After tax"], ["employer_paid", "Paid by employer"]];
let donateCheck = null, donateImageURL = null, donateBoxes = [], donatePage = 1, donateRowsTouched = false;

async function openDonate(route) {
  const checking = Boolean(route.id);
  $("donate-list-view").hidden = checking; $("donate-check-view").hidden = !checking;
  return checking ? openDonationCheck(route.id) : loadDonations();
}

// The list: finished checks to donate, and documents to check ------------------------------------------------

function donationBadge(status) {
  return statusBadge(status === "checked" ? "donation_checked" : "donation_draft");
}

async function loadDonations() {
  const data = await api("/api/donations");
  const checks = $("donate-checks"), candidates = $("donate-candidates");
  checks.replaceChildren(); candidates.replaceChildren();
  const names = Object.fromEntries(data.candidates.filter(row => row.check_id).map(row => [row.check_id, row.name]));
  for (const check of data.checks) {
    const row = document.createElement("tr"), pick = document.createElement("td"), box = document.createElement("input");
    box.type = "checkbox"; box.value = check.id; box.checked = check.status === "checked"; box.disabled = check.status !== "checked";
    box.setAttribute("aria-label", `Include ${names[check.id] || "this document"}`); pick.append(box); row.append(pick);
    const name = document.createElement("td"), link = element("a", names[check.id] || `Document ${check.document_id}`);
    link.href = `#/donate/${check.id}`; name.append(link); row.append(name);
    cell(row, DONATE_TYPES[check.document_type]);
    const state = document.createElement("td"); state.append(donationBadge(check.status)); row.append(state);
    const when = document.createElement("td"); when.append(element("time", dateText(check.updated_at.slice(0, 10)))); row.append(when);
    checks.append(row);
  }
  if (!data.checks.length) tableMessage(checks, 5, "No documents checked yet. Choose one below to start.");
  for (const item of data.candidates) {
    const row = document.createElement("tr");
    cell(row, item.name); cell(row, DONATE_TYPES[item.record_type]);
    const when = document.createElement("td"); when.append(element("time", item.document_date ? dateText(item.document_date) : "—")); row.append(when);
    const action = document.createElement("td");
    if (item.check_id) {
      const link = element("a", item.check_status === "checked" ? "Checked · view" : "Continue checking"); link.href = `#/donate/${item.check_id}`; action.append(link);
    } else {
      action.append(asyncButton("Check", async () => {
        const check = await api("/api/donations/checks", {method: "POST", body: JSON.stringify({record_type: item.record_type, record_id: item.id})});
        location.hash = `#/donate/${check.id}`;
      }));
    }
    row.append(action); candidates.append(row);
  }
  if (!data.candidates.length) tableMessage(candidates, 4, "No receipts, statements or pay stubs have been read from a document yet.");
}

$("donate-export").addEventListener("click", async () => {
  const button = $("donate-export"), ids = [...document.querySelectorAll("#donate-checks input:checked")].map(box => Number(box.value));
  const donor = $("donate-donor").value.trim();
  if (!ids.length) { notice("Tick at least one checked document to donate.", true); return; }
  if (donor && !/^[a-z0-9-]{1,16}$/.test(donor)) { notice("The donor ID uses lowercase letters, digits and dashes, at most 16 characters.", true); $("donate-donor").focus(); return; }
  button.disabled = true;
  try {
    const bundle = await api("/api/donations/bundles", {method: "POST", body: JSON.stringify({check_ids: ids, donor: donor || null})});
    const response = await fetch(`/api/donations/bundles/${bundle.name}`, {headers: {"Authorization": `Bearer ${token}`}});
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "The donation file could not be saved."); }
    const url = URL.createObjectURL(await response.blob());
    const link = element("a"); link.href = url; link.download = bundle.name;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice(`Saved ${bundle.name} with ${bundle.cases} document${bundle.cases === 1 ? "" : "s"}. Hand it to the person collecting donations; nothing was sent.`);
  } catch (error) { notice(error, true); } finally { button.disabled = false; }
});

// One check: the original beside the values ---------------------------------------------------------------------

async function openDonationCheck(id) {
  donateCheck = await api(`/api/donations/checks/${id}`);
  donateBoxes = donateCheck.redactions.map(box => ({...box})); donatePage = 1; donateRowsTouched = false;
  $("donate-check-title").textContent = `Check this ${DONATE_TYPES[donateCheck.document_type].toLowerCase()}`;
  $("donate-check-state").replaceChildren(donationBadge(donateCheck.status));
  $("donate-source-kind").value = donateCheck.source_kind;
  $("donate-error").textContent = "";
  const pages = $("donate-page"); pages.replaceChildren();
  for (let number = 1; number <= donateCheck.pages; number += 1) pages.add(new Option(`${number} of ${donateCheck.pages}`, String(number)));
  pages.parentElement.hidden = donateCheck.pages < 2;
  renderDonationFields(); renderDonationRows(); setDonateRedacting(false);
  await showDonationPage(1);
  const locked = donateCheck.status === "checked";
  for (const control of $("donate-check-view").querySelectorAll(".record-pane input, .record-pane select, .record-pane .donate-check button, #donate-add-row, #donate-redact, #donate-clear-boxes, .donate-row-remove"))
    control.disabled = locked;
  $("donate-save").textContent = locked ? "Change answers" : "Save for later";
  $("donate-finish").hidden = locked;
  $("donate-check-title").focus({preventScroll: true});
}

function stateButtons(current, onChange, label) {
  const group = element("div", "", "donate-check"); group.setAttribute("role", "group"); group.setAttribute("aria-label", label);
  for (const [state, text] of DONATE_STATES) {
    const button = element("button", text, "small"); button.type = "button"; button.dataset.state = state;
    button.setAttribute("aria-pressed", String(state === current));
    button.addEventListener("click", () => onChange(state));
    group.append(button);
  }
  return group;
}
function pressState(group, state) {
  for (const button of group.querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.state === state));
}

function fieldInput(field, value) {
  const input = document.createElement("input");
  input.type = field.kind === "date" ? "date" : "text"; input.value = value;
  if (field.kind === "money") { input.inputMode = "decimal"; input.autocomplete = "off"; }
  if (field.kind === "currency") { input.maxLength = 3; input.autocapitalize = "characters"; }
  input.maxLength = input.maxLength > 0 ? input.maxLength : 200;
  return input;
}

function renderDonationFields() {
  const body = $("donate-fields"); body.replaceChildren();
  for (const field of donateCheck.fields) {
    const row = document.createElement("tr"); row.dataset.name = field.name; row.dataset.state = field.state;
    const label = element("th", field.label); label.scope = "row";
    label.append(element("small", `Read as ${field.proposed || "nothing"}`, "donate-read")); row.append(label);
    const holder = document.createElement("td"), input = fieldInput(field, field.input);
    input.id = `donate-field-${field.name}`; input.setAttribute("aria-label", `${field.label} on the document`);
    if (field.kind === "money") holder.className = "numeric";
    holder.append(input); row.append(holder);
    const states = stateButtons(field.state, state => {
      if (state === "correct") input.value = field.input;  // Correct means the value as shown before any typing.
      row.dataset.state = state; pressState(states, state);
    }, `Check ${field.label}`);
    input.addEventListener("input", () => { row.dataset.state = input.value === field.input ? row.dataset.state : "fixed"; pressState(states, row.dataset.state); });
    const check = document.createElement("td"); check.append(states); row.append(check);
    body.append(row);
  }
}

function rowControl(column, value) {
  if (column.kind === "group") {
    const select = document.createElement("select");
    for (const [key, text] of PAY_LINE_GROUPS) select.add(new Option(text, key));
    select.value = value || "earnings"; return select;
  }
  return fieldInput(column, value);
}

function addDonationRow(values) {
  const row = document.createElement("tr");
  for (const column of donateCheck.columns) {
    const td = document.createElement("td"), control = rowControl(column, values[column.name] ?? "");
    control.dataset.column = column.name; control.setAttribute("aria-label", column.label);
    control.addEventListener(control.tagName === "SELECT" ? "change" : "input", () => { donateRowsTouched = true; });
    if (column.kind === "money") td.className = "numeric";
    td.append(control); row.append(td);
  }
  const remove = document.createElement("td"), button = element("button", "Remove", "small donate-row-remove"); button.type = "button";
  button.addEventListener("click", () => { donateRowsTouched = true; row.remove(); });
  remove.append(button); row.append(remove);
  $("donate-rows").append(row);
  return row;
}

function renderDonationRows() {
  const head = document.createElement("tr");
  for (const column of donateCheck.columns) head.append(Object.assign(element("th", column.label), {scope: "col"}));
  head.append(Object.assign(element("th", ""), {scope: "col"})); head.lastChild.append(element("span", "Remove", "visually-hidden"));
  $("donate-rows-head").replaceChildren(head);
  $("donate-rows").replaceChildren();
  for (const item of donateCheck.rows) addDonationRow(Object.fromEntries(Object.entries(item).map(([name, value]) => [name, value.input])));
  $("donate-rows-complete").checked = donateCheck.rows_complete === true;
  $("donate-rows-note").textContent = `Home Manager listed ${donateCheck.proposed_rows} row${donateCheck.proposed_rows === 1 ? "" : "s"}. Fix any wrong value, remove rows that aren't on the document, and add missing ones. Rows count only once you tick the box below.`;
}
$("donate-add-row").addEventListener("click", () => {
  donateRowsTouched = true;
  addDonationRow({}).querySelector("input, select")?.focus();
});

function donationAnswers(finish) {
  const fields = {};
  for (const row of $("donate-fields").querySelectorAll("tr")) fields[row.dataset.name] = {text: row.querySelector("input").value.trim() || null, state: row.dataset.state};
  const rows = [...$("donate-rows").querySelectorAll("tr")].map(row =>
    Object.fromEntries([...row.querySelectorAll("[data-column]")].map(control => [control.dataset.column, control.value.trim() || null])));
  const complete = $("donate-rows-complete").checked;
  const rowsState = donateRowsTouched ? "fixed" : complete ? "correct" : donateCheck.rows_state;
  return {fields, rows, rows_state: rowsState, rows_complete: rowsState === "unchecked" ? null : complete,
          source_kind: $("donate-source-kind").value, redactions: donateBoxes, finish};
}

async function saveDonationCheck(finish) {
  $("donate-error").textContent = "";
  if (donateCheck.status === "checked") {  // Reopen: back to a draft that can be changed and finished again.
    await api(`/api/donations/checks/${donateCheck.id}/reopen`, {method: "POST"});
    await openDonationCheck(donateCheck.id);
    return;
  }
  try {
    donateCheck = await api(`/api/donations/checks/${donateCheck.id}`, {method: "PUT", body: JSON.stringify(donationAnswers(finish))});
  } catch (error) { $("donate-error").textContent = error.message; throw error; }
  if (finish) { notice("Check finished. It's ready to donate."); location.hash = "#/donate"; }
  else { notice("Saved. You can finish this check later."); await openDonationCheck(donateCheck.id); }
}
for (const [id, finish] of [["donate-save", false], ["donate-finish", true]]) {
  $(id).addEventListener("click", async () => {
    const button = $(id); button.disabled = true;
    try { await saveDonationCheck(finish); } catch (error) { if (!$("donate-error").textContent) notice(error, true); } finally { button.disabled = false; }
  });
}

// The page image and its blacked-out areas ---------------------------------------------------------------------

async function showDonationPage(number) {
  donatePage = number; $("donate-page").value = String(number);
  const expected = donateCheck.id;
  const response = await fetch(`/api/donations/checks/${expected}/pages/${number}`, {headers: {"Authorization": `Bearer ${token}`}});
  if (!response.ok || donateCheck?.id !== expected) return;
  if (donateImageURL) URL.revokeObjectURL(donateImageURL);
  donateImageURL = URL.createObjectURL(await response.blob());
  $("donate-image").src = donateImageURL;
  drawDonationBoxes();
}
$("donate-page").addEventListener("change", () => showDonationPage(Number($("donate-page").value)).catch(error => notice(error, true)));

function placeBox(node, box) {
  // Positions are fractions of the page; the browser only places them, the server applies them.
  node.style.left = `${box.x * 100}%`; node.style.top = `${box.y * 100}%`; node.style.width = `${box.w * 100}%`; node.style.height = `${box.h * 100}%`;
}
function drawDonationBoxes() {
  const layer = $("donate-boxes"); layer.replaceChildren();
  for (const box of donateBoxes.filter(item => item.page === donatePage)) { const node = element("div", "", "donate-box"); placeBox(node, box); layer.append(node); }
  const count = donateBoxes.length;
  $("donate-clear-boxes").textContent = count ? `Remove blacked-out areas (${count})` : "Remove blacked-out areas";
}
function setDonateRedacting(on) {
  $("donate-redact").setAttribute("aria-pressed", String(on));
  $("donate-redact").textContent = on ? "Done blacking out" : "Black out an area";
  $("donate-frame").classList.toggle("drawing", on);
}
$("donate-redact").addEventListener("click", () => setDonateRedacting($("donate-redact").getAttribute("aria-pressed") !== "true"));
$("donate-clear-boxes").addEventListener("click", async () => {
  if (!donateBoxes.length) return;
  if (!await confirmAction({title: "Remove blacked-out areas?", message: "Every page will be donated without the areas you blacked out, unless you draw them again.",
                            confirmLabel: "Remove them", danger: true})) return;
  donateBoxes = []; drawDonationBoxes();
});

(() => {
  const frame = $("donate-frame");
  let start = null, pending = null;
  const point = event => {
    const rect = frame.getBoundingClientRect();
    return {x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)), y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))};
  };
  const shape = (a, b) => ({page: donatePage, x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y)});
  frame.addEventListener("pointerdown", event => {
    if (!frame.classList.contains("drawing") || event.button !== 0) return;
    event.preventDefault(); frame.setPointerCapture(event.pointerId);
    start = point(event); pending = element("div", "", "donate-box pending"); $("donate-boxes").append(pending); placeBox(pending, shape(start, start));
  });
  frame.addEventListener("pointermove", event => { if (start) placeBox(pending, shape(start, point(event))); });
  frame.addEventListener("pointerup", event => {
    if (!start) return;
    const box = shape(start, point(event)); start = null; pending.remove(); pending = null;
    if (box.w < 0.005 || box.h < 0.005) return;
    if (donateBoxes.length >= 50) { notice("Use at most 50 blacked-out areas.", true); return; }
    donateBoxes.push({...box, w: Math.min(box.w, 1 - box.x), h: Math.min(box.h, 1 - box.y)}); drawDonationBoxes();
  });
})();
