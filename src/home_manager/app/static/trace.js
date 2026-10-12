"use strict";
// Observability components (docs/ui.md "Observability components"): a traced figure, the breakdown panel that explains
// it, where each input came from, and the rule it followed. Vanilla factories; the server sends every amount and date.

// A figure from the API (the money() views plus trace and verification). Without a trace ref it is a plain amount().
// signed/magnitude go to amount(), and the breakdown it opens shows its answer the same way.
function figure(fig, {size = "lg", signed = true, magnitude = false} = {}) {
  if (!fig?.trace) return amount(fig, {signed, magnitude});
  const button = element("button", "", "figure-button"); button.type = "button";
  button.dataset.figureRef = fig.trace; button.dataset.figureDisplay = fig.display; button.dataset.size = size;
  button.dataset.signed = String(signed); button.dataset.magnitude = String(magnitude);
  button.setAttribute("aria-controls", "breakdown"); button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-label", `${magnitude ? fig.display.replace(/^-/, "") : fig.display}, show how it's worked out`);
  button.append(amount(fig, {signed, magnitude}));
  const flag = status => { const span = element("span", "", ""); setStatusBadge(span, status); span.classList.add("figure-flag"); return span; };
  if (fig.verification === "needs_review" || ["unverified", "partial"].includes(fig.verification?.state)) button.append(flag("unconfirmed"));
  if (fig.stale === true) button.append(flag("stale"));
  button.addEventListener("click", () => openBreakdown(fig.trace, button));
  return button;
}

// A row of figure tiles (or a plan headline) shares one figure size, fitted to its longest amount
// (style.css "Observability": figure tile). Counts what's on screen: the visually-hidden "money in/out" words aren't.
function fitFigures(row) {
  const shown = node => [...node.childNodes].filter(child => !child.classList?.contains("visually-hidden")).map(child => child.textContent).join("");
  const amounts = row.querySelectorAll(".figure-tile > .figure-button[data-size='lg'] > .amount, .figure-tile > .amount, "
    + ".plan-figure > .figure-button > .amount, .plan-figure > .amount");
  row.style.setProperty("--figure-chars", String(Math.max(1, ...[...amounts].map(node => shown(node).length))));
  return row;
}

// The breakdown panel: one shared, non-modal <aside id="breakdown">. Computed steps and inputs open as breadcrumbs.
// sign: how the opener shows its figure; the answer, Running and "Sums to" follow it, drilled traces too.
const breakdown = {stack: [], opener: null, labels: new Map(), sign: {signed: true, magnitude: false}};
function openBreakdown(ref, opener) {
  if (breakdown.opener && breakdown.opener !== opener) breakdown.opener.setAttribute("aria-expanded", "false");
  breakdown.stack = [ref]; breakdown.opener = opener;
  breakdown.sign = {signed: opener?.dataset.signed !== "false", magnitude: opener?.dataset.magnitude === "true"};
  opener?.setAttribute("aria-expanded", "true");
  // One side panel at a time: the breakdown takes Ask's column (assistant.js), leaving focus with the figure.
  if (typeof toggleAssistant === "function" && !$("assistant-panel").hidden) toggleAssistant(false, {returnFocus: false});
  $("breakdown").hidden = false; document.querySelector(".app-shell").classList.add("breakdown-open");
  return renderBreakdown();
}
function drillBreakdown(ref) { breakdown.stack.push(ref); return renderBreakdown(); }
function backBreakdown() {
  if (breakdown.stack.length > 1) { breakdown.stack.pop(); return renderBreakdown(); }
  closeBreakdown();
}
function closeBreakdown() {
  $("breakdown").hidden = true; document.querySelector(".app-shell").classList.remove("breakdown-open");
  breakdown.stack = [];
  const opener = breakdown.opener; breakdown.opener = null;
  if (opener) { opener.setAttribute("aria-expanded", "false"); opener.focus(); }
}
$("breakdown").addEventListener("keydown", event => {
  if (event.key !== "Escape" || event.defaultPrevented) return;
  if (document.querySelector("dialog[open]") || event.target.closest("input, select, textarea")) return;
  event.preventDefault(); backBreakdown();
});
async function renderBreakdown() {
  const panel = $("breakdown"), ref = breakdown.stack.at(-1);
  // Named until its title loads, then by the title.
  panel.setAttribute("aria-label", "How it's worked out"); panel.removeAttribute("aria-labelledby");
  // Fetches and renders, so the error's Retry (which re-runs this) shows the breakdown too.
  const load = async () => {
    const trace = await api("/api/traces/" + encodeURIComponent(ref));
    if (breakdown.stack.at(-1) !== ref) return trace;
    breakdown.labels.set(ref, trace.label);
    $("breakdown-body").replaceChildren(breakdownHeader(trace), breakdownSteps(trace), breakdownInputs(trace),
                                        ...(trace.rule ? [ruleCard(trace.rule)] : []), breakdownMeta(trace));
    panel.removeAttribute("aria-label"); panel.setAttribute("aria-labelledby", "breakdown-title");
    return trace;
  };
  const trace = await pageState($("breakdown-state"), load, {loading: "Loading the breakdown …", what: "this breakdown", content: [$("breakdown-body")]});
  if (breakdown.stack.at(-1) !== ref) return;
  if (trace) $("breakdown-title").focus();
  else if ($("breakdown-state").hasChildNodes()) $("breakdown-state").prepend(breakdownClose());  // The error still needs a way out.
}
function breakdownClose() {
  const close = element("button", "", "icon-button breakdown-close"); close.type = "button"; close.setAttribute("aria-label", "Close");
  close.append(icon("x")); close.addEventListener("click", closeBreakdown);
  return close;
}
function breakdownHeader(trace) {
  const header = element("header", "", "breakdown-header");
  const top = element("div", "", "breakdown-top");
  top.append(element("p", "How it's worked out", "breakdown-kicker"), breakdownClose());
  header.append(top);
  if (breakdown.stack.length > 1) {
    const nav = element("nav", "", "breakdown-crumbs"); nav.setAttribute("aria-label", "Breakdown path");
    breakdown.stack.forEach((ref, index) => {
      const label = breakdown.labels.get(ref) || "Breakdown";
      if (index) nav.append(icon("chevron-right"));
      if (index === breakdown.stack.length - 1) { const current = element("span", label); current.setAttribute("aria-current", "page"); nav.append(current); return; }
      const link = element("button", label, "link-button"); link.type = "button";
      link.addEventListener("click", () => { breakdown.stack.length = index + 1; renderBreakdown(); });
      nav.append(link);
    });
    header.append(nav);
  }
  const title = element("h2", trace.label); title.id = "breakdown-title"; title.tabIndex = -1;
  const answer = element("p", "", "breakdown-answer"); answer.append(amount(trace.result, breakdown.sign));
  header.append(title, answer);
  if (trace.formula) header.append(element("p", trace.formula, "breakdown-formula"));
  return header;
}
function breakdownSteps(trace) {
  const wrap = element("div", "", "table-wrap"), table = element("table", "", "data-table breakdown-steps");
  const head = table.createTHead().insertRow();
  for (const [title, numeric] of [["Step", false], ["Amount", true], ["Running", true]]) { const th = element("th", title, numeric ? "numeric" : ""); th.scope = "col"; head.append(th); }
  const body = table.createTBody();
  for (const step of trace.steps) {
    const tr = body.insertRow(), label = tr.insertCell();
    if (step.trace) {
      const link = element("button", step.label, "link-button"); link.type = "button";
      link.addEventListener("click", () => drillBreakdown(step.trace));
      label.append(link);
    } else label.append(step.label);
    if (step.count != null) label.append(element("span", ` · ${step.count} ${step.count === 1 ? "line" : "lines"}`, "muted"));
    const value = tr.insertCell(); value.className = "numeric";
    value.append(element("span", step.op, "sign"), amount(step.value, {signed: false}));
    const running = tr.insertCell(); running.className = "numeric"; running.append(amount(step.running, breakdown.sign));
  }
  if (trace.rounding?.adjustment) {
    const tr = body.insertRow(), label = tr.insertCell();
    label.append("Rounding");
    if (trace.rounding.note) label.append(element("span", ` · ${trace.rounding.note}`, "muted"));
    const value = tr.insertCell(); value.className = "numeric"; value.append(amount(trace.rounding.adjustment));
    tr.insertCell();
  }
  const foot = table.createTFoot().insertRow(), sums = foot.insertCell(); sums.colSpan = 3;
  if (trace.reconciles) { sums.className = "breakdown-sums"; sums.append(icon("check"), "Sums to ", amount(trace.result, breakdown.sign)); }
  else sums.append(alertBox("These steps don't add up to the figure. This is a bug; please report it.", {tone: "warning"}));
  wrap.append(table);
  return wrap;
}
function breakdownInputs(trace) {
  const section = element("section", "", "breakdown-inputs-section");
  const heading = element("h3", "Inputs "); heading.append(element("span", `(${trace.inputs_page.total})`, "muted"));
  section.append(heading);
  if (!trace.inputs.length) { section.append(element("p", "No recorded inputs.", "muted small")); return section; }
  const list = element("ul", "", "breakdown-inputs");
  for (const input of trace.inputs) {
    const li = element("li", "", "input-row"); li.dataset.verification = input.verification;
    const top = element("div", "", "input-main");
    top.append(element("span", input.label, "input-label"), amount(input.value));
    const marks = element("div", "", "input-marks");
    if (input.provenance) marks.append(provenanceBadge(input.provenance));
    if (input.verification === "needs_review") marks.append(statusBadge("unconfirmed"));
    if (input.verification === "checked_automatically") marks.append(element("span", "Checked automatically", "muted"));
    const links = [];
    if (input.trace) {
      const link = element("button", "How it's worked out", "link-button"); link.type = "button";
      link.addEventListener("click", () => drillBreakdown(input.trace));
      links.push(link);
    }
    const doc = input.provenance?.document;
    if (doc) links.push(homeLink("Open source", `#/documents/${doc.id}${doc.lines?.length ? `?lines=${doc.lines.join(",")}` : ""}`));
    if (links.length) marks.append(...links);
    li.append(top, marks); list.append(li);
  }
  section.append(list);
  if (trace.inputs_page.total > trace.inputs_page.shown) section.append(element("p", `Showing ${trace.inputs_page.shown} of ${trace.inputs_page.total}.`, "muted small"));
  return section;
}
function breakdownMeta(trace) {
  const meta = element("p", `Calculated ${dateText(trace.computed_at)} · `, "breakdown-meta");
  if (trace.stale) meta.append("inputs changed since this was last shown ", statusBadge("stale"));
  else meta.append("inputs unchanged");
  return meta;
}

// Where one input came from, as icon + text from the server's fields only (docs/ui.md "Trace contract").
function provenanceBadge(prov) {
  const kind = prov?.kind, status = `prov_${kind}`;
  let text = null;
  if (kind === "manual") text = prov.actor?.person ? `Entered by ${prov.actor.person}${prov.actor.at ? ` · ${dateText(prov.actor.at)}` : ""}` : "Entered";
  else if (kind === "extracted") {
    text = prov.model?.id ? `Read by model ${prov.model.id}` : "Read by model";
    if (prov.document?.page != null) text += ` · page ${prov.document.page}`;
    if (prov.confidence?.level === "doubted") text += ` · doubted by ${prov.confidence.by}`;
  } else if (kind === "imported") text = prov.import ? `Imported · ${prov.import.file} row ${prov.import.row}` : "Imported";
  else if (kind === "override") text = `Changed by ${prov.actor?.person || "hand"}${prov.override?.reason || prov.reason ? ` · ${prov.override?.reason || prov.reason}` : ""}`;
  else if (!STATUS[status]) text = statusLabel(kind);
  return setStatusBadge(element("span"), STATUS[status] ? status : kind, "", text);
}

// The rule a figure followed: name, source (text, never a link), version, tax year and when it was checked.
function ruleCard(rule) {
  const section = element("section", "", "rule-card"), list = element("dl");
  const row = (term, ...value) => { const dd = element("dd"); dd.append(...value); list.append(element("dt", term), dd); };
  row("Rule", rule.name || "—");
  row("Source", rule.source || "—");
  row("Version", element("code", rule.version || "—"));
  if (rule.tax_year != null) row("Tax year", String(rule.tax_year));
  row("Checked on", rule.checked_on ? dateText(rule.checked_on) : "No check recorded");
  row("CPA review", rule.cpa_reviewed_on ? dateText(rule.cpa_reviewed_on) : "Not CPA-reviewed");
  section.append(list);
  return section;
}

// A document's latest reading ({doc, run, result}; result is null while it's unread), cached until clearReadings().
// The newest reading that finished is used, else the newest; one still running isn't cached.
const readings = new Map();
function clearReadings() { readings.clear(); }
async function loadReading(documentId, digest = null) {
  const key = `${documentId}:${digest || ""}`;
  if (readings.has(key)) return readings.get(key);
  const doc = await api(`/api/documents/${documentId}`);
  const runs = await api(`/api/documents/${documentId}/receipt-runs?blob_hash=${digest || doc.current_hash}`);
  const chosen = runs.find(run => run.status === "succeeded") || runs[0];
  const run = chosen ? await api(`/api/receipt-runs/${chosen.id}`) : null;
  const reading = {doc, run, result: run?.result || null};
  if (!PENDING_RUN.includes(run?.status)) readings.set(key, reading);
  return reading;
}

// The source beside the record (docs/ui.md "Layout" rule 2): the preserved image or PDF with its read regions, and the
// text read from it as a list of lines. highlight(ids) lights the cited lines; a region click or Enter on a line tells
// onRegionClick's callbacks which lines it is. Document text is always set as text, links included.
let sourceViewerCount = 0;
function sourceViewer(doc, reading, {runId = null, digest = null} = {}) {
  const n = ++sourceViewerCount, idOf = name => `sv${n}-${name}`;
  const state = {doc, reading, runId, digest: digest || doc.current_hash, url: null, generation: 0, callbacks: []};
  const el = element("section", "", "source-viewer"); el.setAttribute("aria-label", "Source document");
  const toolbar = element("div", "", "sv-toolbar"), tabs = element("div", "", "tabs sv-tabs");
  tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Source view");
  const pageField = element("label", "Page ", "inline-field sv-page"), pageSelect = document.createElement("select");
  pageField.append(pageSelect); pageField.hidden = true;
  const preserved = element("span", "Original preserved", "status-badge"); preserved.dataset.tone = "neutral";
  const imagePanel = element("div", "", "sv-panel sv-image"), textPanel = element("div", "", "sv-panel sv-text");
  const tabFor = (label, name, panel) => {
    const tab = element("button", label); tab.type = "button"; tab.id = idOf(`${name}-tab`); tab.setAttribute("role", "tab");
    panel.id = idOf(name); panel.setAttribute("role", "tabpanel"); panel.setAttribute("aria-labelledby", tab.id); tab.setAttribute("aria-controls", panel.id);
    return tab;
  };
  const imageTab = tabFor("Image", "image", imagePanel), textTab = tabFor("Text", "text", textPanel);
  const select = name => {
    for (const [tab, panel, key] of [[imageTab, imagePanel, "image"], [textTab, textPanel, "text"]]) {
      tab.setAttribute("aria-selected", String(key === name)); tab.tabIndex = key === name ? 0 : -1; panel.hidden = key !== name;
    }
  };
  for (const tab of [imageTab, textTab]) {
    tab.addEventListener("click", () => select(tab === imageTab ? "image" : "text"));
    tab.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      // Two tabs: the arrows switch to the other one; Home and End go to the first and last.
      const next = event.key === "Home" ? imageTab : event.key === "End" ? textTab : tab === imageTab ? textTab : imageTab;
      select(next === imageTab ? "image" : "text"); next.focus();
    });
  }
  tabs.append(imageTab, textTab); toolbar.append(tabs, pageField, preserved);

  const alert = element("div", "", "sv-alert");
  let pdf = element("iframe", "", "sv-pdf"); pdf.title = "Preserved PDF document"; pdf.hidden = true;
  const scroll = element("div", "", "sv-scroll"), frame = element("div", "", "sv-frame"), image = element("img", "", "sv-img");
  image.alt = "Preserved document";
  // The regions are for the mouse; the list of lines is their keyboard equivalent.
  const overlay = document.createElementNS(SVG, "svg"); overlay.setAttribute("class", "sv-overlay"); overlay.setAttribute("aria-hidden", "true");
  frame.append(image, overlay); scroll.append(frame);
  imagePanel.append(alert, pdf, scroll, element("p", "Select a highlighted region to find the recorded rows that cite it.", "muted small sv-hint"));
  const lines = element("ol", "", "sv-lines"); lines.setAttribute("aria-label", "Text read from the document");
  const copy = element("button", "Copy text", "small sv-copy"); copy.type = "button";
  textPanel.append(lines, copy);
  const extras = element("details", "", "sv-extras"), issues = element("ul", "", "sv-issues"), codes = element("div", "", "sv-codes");
  extras.append(element("summary", "Reading notes & codes"), issues, element("h3", "QR codes and barcodes"), codes);
  el.append(toolbar, imagePanel, textPanel, extras);
  select("image");

  const textLines = () => state.reading?.result?.lines || [];
  const tell = (blockId, lineIds) => { for (const callback of state.callbacks) callback({blockId, lineIds}); };
  function showPdf(url) {
    // A fresh frame given its source before it is inserted adds no browser history entry (receipt.js showPdf).
    const fresh = element("iframe", "", "sv-pdf"); fresh.title = pdf.title; fresh.hidden = !url;
    if (url) fresh.src = url;
    pdf.replaceWith(fresh); pdf = fresh;
  }
  async function showImage(path) {
    const generation = ++state.generation;
    alert.replaceChildren();
    try {
      const response = await fetch(path, {headers: {"Authorization": `Bearer ${token}`}});
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Could not retrieve image."); }
      const blob = await response.blob();
      if (generation !== state.generation) return;
      if (state.url) URL.revokeObjectURL(state.url);
      state.url = URL.createObjectURL(blob);
      const isPdf = blob.type === "application/pdf";
      showPdf(isPdf ? state.url : null); scroll.hidden = isPdf;
      if (!isPdf) image.src = state.url;
    } catch (error) {
      // The error stands alone: no empty frame or broken image beside it.
      if (generation === state.generation) { alert.replaceChildren(alertBox(`The preview couldn't be shown: ${error.message}`, {tone: "error"})); scroll.hidden = true; showPdf(null); }
    }
  }
  function focusLine(item) {
    for (const other of lines.children) other.tabIndex = other === item ? 0 : -1;
    item.focus();
  }
  function render() {
    const result = state.reading?.result;
    lines.replaceChildren(); issues.replaceChildren(); codes.replaceChildren(); overlay.replaceChildren();
    pageField.hidden = true; pageSelect.replaceChildren();
    if (!result) lines.append(element("li", "Not read yet. The text appears here once the document is read.", "muted sv-empty"));
    textLines().forEach((line, index) => {
      const item = element("li", line.text || " ", "sv-line"); item.dataset.lineId = line.id; item.tabIndex = index ? -1 : 0;
      lines.append(item);
    });
    copy.disabled = !result;
    if (result?.pages) {
      pageSelect.append(...result.pages.map(page => new Option(`${page.number} of ${result.pages.length} · ${page.method}`, String(page.number))));
      pageField.hidden = result.pages.length < 2;
    }
    for (const issue of result?.issues || []) if (issue.code !== "interpretation_pending") issues.append(element("li", issue.message));
    if (result && !result.codes?.length) codes.append(element("p", "No code decoded. A QR code may be absent or unreadable; check the image.", "muted small"));
    for (const code of result?.codes || []) {
      const card = element("div", "", "receipt-field");
      const bytes = element("details"); bytes.append(element("summary", "Exact payload bytes (base64)"), element("pre", code.bytes_base64));
      const find = element("button", "Highlight code", "small"); find.type = "button";
      find.addEventListener("click", () => highlight([code.id]));
      card.append(element("strong", `${code.format} · ${code.valid ? "decoded" : "decode error"}`), element("pre", code.text || "No text representation"), bytes, find);
      codes.append(card);
    }
    if (result && result.transcription_method !== "pdf_pages") {
      overlay.setAttribute("viewBox", `0 0 ${result.width} ${result.height}`);
      for (const block of [...(result.blocks || []), ...(result.codes || [])]) {
        const polygon = document.createElementNS(SVG, "polygon");
        polygon.setAttribute("points", block.polygon.map(pair => pair.join(",")).join(" ")); polygon.dataset.evidenceId = block.id;
        const title = document.createElementNS(SVG, "title"); title.textContent = block.text; polygon.append(title);
        polygon.addEventListener("click", () => {
          highlight([block.id]);
          tell(block.id, textLines().filter(line => (line.block_ids || []).includes(block.id)).map(line => line.id));
        });
        overlay.append(polygon);
      }
    }
    const path = result && state.runId && result.transcription_method !== "pdf_pages" ? `/api/receipt-runs/${state.runId}/preview`
      : `/api/documents/${state.doc.id}/preview?blob_hash=${state.digest}`;
    return showImage(path);
  }
  function highlight(ids) {
    const result = state.reading?.result;
    if (!result || !ids?.length) return;
    const wanted = new Set(ids);
    let first = null;
    for (const item of lines.children) {
      const selected = wanted.has(item.dataset.lineId);
      item.classList.toggle("selected", selected);
      if (selected && !first) first = item;
    }
    if (first) {
      for (const other of lines.children) other.tabIndex = other === first ? 0 : -1;
      lines.scrollTop = Math.max(0, first.offsetTop - lines.clientHeight / 3);
    }
    if (["vision_model", "pdf_pages"].includes(result.transcription_method) && !ids.some(id => id.startsWith("code-"))) { select("text"); return; }
    select("image");
    for (const line of result.lines) if (wanted.has(line.id)) for (const id of line.block_ids || []) wanted.add(id);
    for (const polygon of overlay.children) polygon.classList.toggle("selected", wanted.has(polygon.dataset.evidenceId));
  }
  lines.addEventListener("keydown", event => {
    const item = event.target.closest(".sv-line");
    if (!item) return;
    const all = [...lines.querySelectorAll(".sv-line")], index = all.indexOf(item);
    const moves = {ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: all.length - 1};
    if (event.key in moves) { event.preventDefault(); const next = all[Math.max(0, Math.min(all.length - 1, moves[event.key]))]; if (next) focusLine(next); }
    else if (event.key === "Enter") { event.preventDefault(); highlight([item.dataset.lineId]); tell(null, [item.dataset.lineId]); }
  });
  lines.addEventListener("click", event => { const item = event.target.closest(".sv-line"); if (item) focusLine(item); });
  pageSelect.addEventListener("change", () => {
    const first = textLines().find(line => line.id.startsWith(`page-${pageSelect.value}-`));
    if (first) highlight([first.id]);
  });
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(textLines().map(line => line.text).join("\n")); copy.textContent = "Copied"; }
    catch { notice("Copying isn't available here. Select the text and press Ctrl+C.", true); }
  });
  render();
  return {
    el, highlight,
    onRegionClick(callback) { state.callbacks.push(callback); },
    update(reading, nextRunId = state.runId) { state.reading = reading; state.runId = nextRunId; return render(); },
    showDocument(id) { select("image"); return showImage(`/api/documents/${id}/preview`); },
    destroy() { state.generation++; state.callbacks = []; if (state.url) URL.revokeObjectURL(state.url); state.url = null; },
  };
}

// Confirm, Reject and Correct for one record (docs/ui.md "Observability components"). Correct opens a form whose preview
// shows what saving would change (the correction-preview endpoint) before anything is saved; a save or decision can be
// undone for 8 seconds. decision: false offers Correct only (a statement's row).
let confirmCorrectCount = 0;
const SALE_TYPES = {sale: "Sale", return: "Return"}, DIRECTION_WORDS = {out: "Money out", in: "Money in"};
function confirmCorrect({recordType, recordId, reviewStatus, reviewSource, correctable = [], reviewPath = null, confirmBody = {status: "verified"},
                         rejectBody = {status: "rejected"}, undoBody = {status: "needs_review"}, labels = {}, onChange = () => {}, preview = true,
                         member = null, decision = true, onClose = null, showState = true} = {}) {
  const n = ++confirmCorrectCount, idOf = name => `cc${n}-${name}`;
  const record = `/api/finance/records/${recordType}/${recordId}`, path = reviewPath || `${record}/review`;
  const words = {confirm: "Confirm", reject: "Reject", correct: "Correct…", ...labels};
  const el = element("div", "", "confirm-correct");
  const actions = element("div", "", "cc-actions"); actions.setAttribute("role", "group"); actions.setAttribute("aria-label", "Decision");
  const stateLine = element("div", "", "cc-state");
  const form = element("form", "", "cc-form"); form.id = idOf("form"); form.hidden = true; form.noValidate = true;
  el.append(actions, stateLine, form);
  const button = (label, className = "") => { const node = element("button", label, className); node.type = "button"; return node; };
  const automatic = reviewStatus === "verified" && reviewSource === "automatic";
  let confirmButton = null, rejectButton = null, correctButton = null;
  const failed = error => stateLine.replaceChildren(alertBox(error.message || String(error), {tone: "error"}));
  async function decide(body, message, undo) {
    stateLine.replaceChildren();
    for (const node of actions.querySelectorAll("button")) node.disabled = true;
    try { await api(path, {method: "POST", body: JSON.stringify(body)}); }
    catch (error) { failed(error); for (const node of actions.querySelectorAll("button")) node.disabled = false; return; }
    if (undo) undoToast(message, () => api(path, {method: "POST", body: JSON.stringify(undo)}));
    else notice(message);
    await onChange();
  }
  function undoToast(message, undo) {
    const item = toast(message, {timeout: 8000}), again = button("Undo", "small");
    again.addEventListener("click", async () => {
      again.disabled = true;
      try { await undo(); item.remove(); notice("Undone."); await onChange(); } catch (error) { notice(error, true); again.disabled = false; }
    });
    item.querySelector(".toast-body").append(again);
  }
  // showState: false where the record's status badge already shows beside its title (the document page).
  const status = name => { if (showState) stateLine.append(statusBadge(name)); };
  if (decision) {
    if (["needs_review", "proposed"].includes(reviewStatus)) {
      confirmButton = button(words.confirm, "primary"); rejectButton = button(words.reject);
      confirmButton.addEventListener("click", () => decide(confirmBody, "Confirmed.", {...undoBody}));
      rejectButton.addEventListener("click", () => decide(rejectBody, "Rejected. It no longer counts.", {...undoBody}));
      actions.append(confirmButton, rejectButton);
    } else if (automatic) {
      status("checked");
      rejectButton = button("Not right? Reject");
      rejectButton.addEventListener("click", () => decide(rejectBody, "Rejected. It no longer counts.", {status: "verified"}));
      actions.append(rejectButton);
    } else if (reviewStatus === "verified") {
      status("verified");
      const undo = button("Undo verification"); undo.addEventListener("click", () => decide(undoBody, "Back to needs review."));
      actions.append(undo);
    } else if (reviewStatus === "rejected") {
      status("rejected");
      const undo = button("Undo rejection"); undo.addEventListener("click", () => decide(undoBody, "Back to needs review."));
      actions.append(undo);
    }
  }
  const fields = {};
  if (correctable.length && reviewStatus !== "rejected") {
    correctButton = button(words.correct);
    correctButton.setAttribute("aria-expanded", "false"); correctButton.setAttribute("aria-controls", form.id);
    correctButton.addEventListener("click", () => form.hidden ? openCorrect() : close());
    actions.append(correctButton);
    for (const item of correctable) {
      const box = element("div", "", "field"), caption = element("label", item.label);
      let input;
      if (item.options) {
        input = document.createElement("select");
        if (item.kind === "category" && !item.value) input.add(new Option("Not set", ""));
        const text = item.kind === "category" ? categoryLabel : item.kind === "sale_type" ? value => SALE_TYPES[value] || value
          : item.kind === "direction" ? value => DIRECTION_WORDS[value] || value : statusLabel;
        for (const option of item.options) input.add(new Option(text(option), option));
      } else {
        input = document.createElement("input");
        input.type = item.kind === "date" ? "date" : "text";
        if (["money", "amount"].includes(item.kind)) input.inputMode = "decimal";
        input.maxLength = item.kind === "text" ? 60 : 120;
      }
      input.value = item.value ?? ""; input.id = idOf(item.field); caption.htmlFor = input.id;
      box.append(caption, input); form.append(box); fields[item.field] = input;
    }
    const reasonBox = element("div", "", "field"), reasonLabel = element("label", "Why (optional)"), reason = document.createElement("input");
    reason.id = idOf("reason"); reason.maxLength = 500; reasonLabel.htmlFor = reason.id;
    const hint = element("small", "Kept with the change.", "muted"); hint.id = idOf("reason-hint"); reason.setAttribute("aria-describedby", hint.id);
    reasonBox.append(reasonLabel, reason, hint);
    const previewBox = element("div", "", "cc-preview"); previewBox.setAttribute("role", "status"); previewBox.setAttribute("aria-live", "polite");
    const error = element("p", "", "error-text"); error.setAttribute("role", "alert");
    const save = element("button", "Save", "primary"); save.type = "submit";
    const cancel = button("Cancel"); cancel.addEventListener("click", () => close());
    const row = element("div", "", "button-row"); row.append(save, cancel);
    form.append(reasonBox, previewBox, error, row);
    const changes = () => Object.fromEntries(correctable.filter(item => fields[item.field].value.trim() !== (item.value ?? ""))
      .map(item => [item.field, fields[item.field].value.trim() || null]));
    let sequence = 0, timer = null, shown = null;
    const showPreview = async () => {
      const wanted = changes(), mine = ++sequence;
      error.textContent = ""; save.disabled = false; shown = null;
      if (!preview || !Object.keys(wanted).length) { previewBox.replaceChildren(); return; }
      const slow = setTimeout(() => { if (mine === sequence) previewBox.replaceChildren(element("p", "Working out what changes …", "muted small")); }, 300);
      try {
        const found = await api(`${record}/correction-preview`, {method: "POST", body: JSON.stringify({changes: wanted})});
        if (mine !== sequence) return;
        shown = found; previewBox.replaceChildren(...previewParts(found));
        save.scrollIntoView({block: "nearest"});  // The preview pushed it down; Save stays in view.
      } catch (failure) {
        if (mine !== sequence) return;
        if (failure.status === 400) { previewBox.replaceChildren(); error.textContent = failure.message; save.disabled = true; }
        else previewBox.replaceChildren(element("p", "Couldn't work out the preview. You can still save.", "muted small"));
      } finally { clearTimeout(slow); }
    };
    form.addEventListener("input", event => {
      if (event.target === reason) return;
      clearTimeout(timer); timer = setTimeout(showPreview, 450);
    });
    form.addEventListener("keydown", event => { if (event.key === "Escape") { event.preventDefault(); close(); } });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const wanted = changes();
      if (!Object.keys(wanted).length) { close(); return; }
      save.disabled = true; error.textContent = "";
      try {
        const saved = await api(`${record}${member ? `?member=${member}` : ""}`, {method: "PATCH", body: JSON.stringify({changes: wanted, reason: reason.value.trim() || null})});
        const moved = shown?.figures?.length;
        close(false);
        const message = moved ? `Saved. ${moved} ${moved === 1 ? "total" : "totals"} changed.` : "Saved.";
        if (saved.correction_ids?.length) undoToast(message, () => api(`${record}/corrections/undo`, {method: "POST", body: JSON.stringify({ids: saved.correction_ids})}));
        else notice(message);
        await onChange();
      } catch (failure) { error.textContent = failure.message; save.disabled = false; }
    });
  }
  function openCorrect(field = null) {
    if (!correctButton) return;
    form.hidden = false; correctButton.setAttribute("aria-expanded", "true"); el.classList.add("cc-open");
    (fields[field] || Object.values(fields)[0])?.focus();
  }
  function close(focus = true) {
    if (!correctButton || form.hidden) return;
    form.hidden = true; correctButton.setAttribute("aria-expanded", "false"); el.classList.remove("cc-open");
    for (const item of correctable) fields[item.field].value = item.value ?? "";
    form.querySelector(".cc-preview").replaceChildren(); form.querySelector(".error-text").textContent = "";
    if (focus) correctButton.focus();
    onClose?.();
  }
  return {el, confirmButton, rejectButton, correctButton, openCorrect, close};
}
// What a correction would change, from the preview: each moved total as before → after (after is a plain amount: its
// breakdown would open today's figure, not the corrected one), then what stays, the match, the review state and notes.
function previewParts(found) {
  const parts = [];
  if (found.figures.length) {
    const list = element("ul", "", "cc-preview-list");
    for (const item of found.figures) {
      const row = element("li", "", "cc-preview-row");
      const arrow = element("span", "→", "cc-arrow"); arrow.setAttribute("aria-hidden", "true");
      const delta = element("span", "", "cc-delta"); if (item.difference) delta.append(amount(item.difference));
      row.append(element("span", item.label, "cc-label"), item.before ? figure(item.before, {size: "inline", signed: false}) : element("span", "—"),
                 arrow, element("span", " becomes ", "visually-hidden"), item.after ? amount(item.after, {signed: false}) : element("span", "—"), delta);
      list.append(row);
    }
    parts.push(list);
  } else if (!found.notes.length) parts.push(element("p", "No totals change.", "muted small"));
  if (found.unchanged_count) parts.push(element("p", `${found.unchanged_count} other ${found.unchanged_count === 1 ? "total stays" : "totals stay"} the same.`, "muted small"));
  if (found.matching?.changed) {
    const name = side => side.map(link => link.counterpart?.name || "a record").join(", ");
    parts.push(element("p", found.matching.after.length ? `It will be matched to ${name(found.matching.after)}.` : `It will no longer be matched to ${name(found.matching.before)}.`, "small"));
  }
  if (found.review.automatic && found.review.after === "verified") parts.push(element("p", "It will count automatically: every check passes.", "small"));
  else if (found.issues.remaining.length && found.review.after === "needs_review") parts.push(element("p", `Still needs you: ${found.issues.remaining[0]}`, "small"));
  for (const note of found.notes) parts.push(element("p", note, "muted small"));
  return parts;
}

// A record's history (newest first): who changed which field from what to what and why, and review decisions.
function loadHistory(type, id) { return api(`/api/finance/records/${type}/${id}/history`).then(found => found.entries); }
function historyValue(entry, value) {
  if (value == null || value === "") return "empty";
  if (entry.value_kind === "date") return dateText(value);
  if (entry.value_kind === "category") return categoryLabel(value);
  if (entry.value_kind === "sale_type") return SALE_TYPES[value] || value;
  if (entry.value_kind === "direction") return DIRECTION_WORDS[value] || value;
  return value;
}
function historyList(entries, {field = null, empty = "No changes yet. Corrections and review decisions appear here."} = {}) {
  const shown = field ? entries.filter(entry => entry.field === field) : entries;
  if (!shown.length) return emptyState(empty);
  const list = element("ol", "", "history-list");
  for (const entry of shown) {
    const row = element("li", "", "history-row"); row.dataset.kind = entry.kind;
    const when = dateDisplay(entry.at); when.classList.add("history-when");
    const what = element("p", "", "history-what");
    if (entry.kind === "review") what.append(statusBadge(entry.from_status), element("span", " → ", "history-arrow"), statusBadge(entry.to_status));
    else {
      what.append(`${entry.row ? `${entry.row.label} · ` : ""}${entry.label}: `, element("span", historyValue(entry, entry.from), "history-from"),
                  element("span", " → ", "history-arrow"), element("span", historyValue(entry, entry.to), "history-to"));
      if (entry.kind === "family") what.append(element("span", ` · from the family, ${statusLabel(entry.status).toLowerCase()}`, "muted"));
    }
    row.append(when, element("span", entry.who, "history-who"), what);
    const why = entry.reason || entry.note;
    if (why) row.append(element("p", why, "history-why muted"));
    list.append(row);
  }
  return list;
}
