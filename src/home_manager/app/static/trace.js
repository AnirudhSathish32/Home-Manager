"use strict";
// Observability components (docs/ui.md "Observability components"): a traced figure, the breakdown panel that explains
// it, where each input came from, and the rule it followed. Vanilla factories; the server sends every amount and date.

// A figure from the API (the money() views plus trace and verification). Without a trace ref it is a plain amount().
function figure(fig, {size = "lg"} = {}) {
  if (!fig?.trace) return amount(fig);
  const button = element("button", "", "figure-button"); button.type = "button";
  button.dataset.figureRef = fig.trace; button.dataset.figureDisplay = fig.display; button.dataset.size = size;
  button.setAttribute("aria-controls", "breakdown"); button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-label", `${fig.display}, show how it's worked out`);
  button.append(amount(fig));
  const flag = status => { const span = element("span", "", ""); setStatusBadge(span, status); span.classList.add("figure-flag"); return span; };
  if (fig.verification === "needs_review" || ["unverified", "partial"].includes(fig.verification?.state)) button.append(flag("unconfirmed"));
  if (fig.stale === true) button.append(flag("stale"));
  button.addEventListener("click", () => openBreakdown(fig.trace, button));
  return button;
}

// The breakdown panel: one shared, non-modal <aside id="breakdown">. Computed steps and inputs open as breadcrumbs.
const breakdown = {stack: [], opener: null, labels: new Map()};
function openBreakdown(ref, opener) {
  if (breakdown.opener && breakdown.opener !== opener) breakdown.opener.setAttribute("aria-expanded", "false");
  breakdown.stack = [ref]; breakdown.opener = opener;
  opener?.setAttribute("aria-expanded", "true");
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
  const answer = element("p", "", "breakdown-answer"); answer.append(amount(trace.result));
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
    const running = tr.insertCell(); running.className = "numeric"; running.append(amount(step.running));
  }
  if (trace.rounding?.adjustment) {
    const tr = body.insertRow(), label = tr.insertCell();
    label.append("Rounding");
    if (trace.rounding.note) label.append(element("span", ` · ${trace.rounding.note}`, "muted"));
    const value = tr.insertCell(); value.className = "numeric"; value.append(amount(trace.rounding.adjustment));
    tr.insertCell();
  }
  const foot = table.createTFoot().insertRow(), sums = foot.insertCell(); sums.colSpan = 3;
  if (trace.reconciles) { sums.className = "breakdown-sums"; sums.append(icon("check"), "Sums to ", amount(trace.result)); }
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
