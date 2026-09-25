"use strict";
// Shared interface primitives (docs/ui-design-plan.md §4.3). Each returns a DOM node; no framework, no build step.

// Icon paths adapted from Lucide (ISC License, https://lucide.dev). Drawn inline so the CSP needs no extra sources.
const ICONS = {
  check: ["M20 6 9 17l-5-5"],
  "check-circle": ["circle", "m9 12 2 2 4-4"],
  alert: ["m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "M12 9v4", "M12 17h.01"],
  "x-circle": ["circle", "m15 9-6 6", "m9 9 6 6"],
  clock: ["circle", "M12 6v6l4 2"],
  loader: ["M21 12a9 9 0 1 1-6.219-8.56"],
  octagon: ["M12 16h.01", "M12 8v4", "M15.312 2a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586l-4.688-4.688A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2z"],
  slash: ["circle", "m4.9 4.9 14.2 14.2"],
  dashed: ["dashed-circle"],
  pause: ["circle", "M10 15V9", "M14 15V9"],
  half: ["circle", "M12 2a10 10 0 0 1 0 20z"],
  info: ["circle", "M12 16v-4", "M12 8h.01"],
  x: ["M18 6 6 18", "m6 6 12 12"],
  more: ["M5 12h.01", "M12 12h.01", "M19 12h.01"],
  wallet: ["M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1", "M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"],
  file: ["M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z", "M14 2v4a2 2 0 0 0 2 2h4", "M16 13H8", "M16 17H8", "M10 9H8"],
  activity: ["M22 12h-4l-3 9L9 3l-3 9H2"],
  settings: ["m9 3-.6 2.2-2 .9-2.1-.6-2 3.5 1.5 1.6v2.8L2.3 15l2 3.5 2.1-.6 2 .9L9 21h4l.6-2.2 2-.9 2.1.6 2-3.5-1.5-1.6v-2.8L19.7 9l-2-3.5-2.1.6-2-.9L13 3Z", "M11 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0"],
  inbox: ["M22 12h-6l-2 3h-4l-2-3H2", "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"],
  folder: ["M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"],
  transfer: ["M8 3 4 7l4 4", "M4 7h16", "m16 21 4-4-4-4", "M20 17H4"],
  "arrow-left": ["m12 19-7-7 7-7", "M19 12H5"],
  paperclip: ["m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"],
};
const SVG = "http://www.w3.org/2000/svg";
function icon(name, className = "icon") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
  svg.setAttribute("class", className);
  for (const path of ICONS[name] || []) {
    const shape = document.createElementNS(SVG, path.endsWith("circle") ? "circle" : "path");
    if (path.endsWith("circle")) {
      shape.setAttribute("cx", "12"); shape.setAttribute("cy", "12"); shape.setAttribute("r", "10");
      if (path === "dashed-circle") shape.setAttribute("stroke-dasharray", "3.2 3.2");
    } else shape.setAttribute("d", path);
    if (name === "half" && path.startsWith("M12 2")) shape.setAttribute("fill", "currentColor");
    svg.appendChild(shape);
  }
  return svg;
}

// One status vocabulary for the whole application: internal value -> [label, tone, icon].
const STATUS = {
  proposed: ["Proposed", "info", "dashed"], needs_review: ["Needs review", "warning", "alert"],
  verified: ["Verified", "positive", "check-circle"], rejected: ["Rejected", "neutral", "x-circle"],
  checked: ["Checked automatically", "positive", "check-circle"],
  queued: ["Queued", "neutral", "clock"], running: ["Processing", "info", "loader"],
  succeeded: ["Done", "positive", "check"], completed: ["Completed", "positive", "check"],
  partial: ["Partly done", "warning", "half"], failed: ["Failed", "danger", "octagon"],
  interrupted: ["Interrupted", "warning", "pause"], cancelled: ["Cancelled", "neutral", "slash"],
  cancel_requested: ["Cancelling", "neutral", "loader"], imported: ["Imported", "positive", "check"],
  not_imported: ["Not imported", "neutral", null], not_extracted: ["Not extracted", "neutral", null],
  payment_found: ["Payment found", "positive", "check"], due: ["Due", "neutral", "clock"],
  past_due_no_payment_found: ["Past due · no payment found", "danger", "alert"],
  posted_credit_found: ["Credit posted", "positive", "check"], evidence_only_not_settled: ["Refund not yet posted", "warning", "clock"],
  // Document summary states (docs/ui-design-plan.md §3.7).
  not_read: ["Not read yet", "neutral", null], read: ["Read, not recorded", "neutral", "file"], recorded: ["Recorded", "positive", "check-circle"],
  ready_to_import: ["Ready to import", "neutral", null], in_trash: ["In Trash", "neutral", null], process_failed: ["Couldn't process", "danger", "octagon"],
};
function statusLabel(status) {
  return STATUS[status]?.[0] || String(status || "").replaceAll("_", " ").replace(/^./, character => character.toUpperCase());
}
function setStatusBadge(target, status, prefix = "") {
  const [, tone = "neutral", glyph = null] = STATUS[status] || [];
  target.className = "status-badge"; target.dataset.status = status || ""; target.dataset.tone = tone;
  target.replaceChildren(...(glyph ? [icon(glyph, status === "running" ? "icon spin" : "icon")] : []), document.createTextNode(prefix + statusLabel(status)));
  return target;
}
function statusBadge(status, prefix = "") { return setStatusBadge(document.createElement("span"), status, prefix); }

// Money: the server supplies exact display text such as "-1,234.56 USD". This only rearranges that text
// (sign, symbol); it never parses a number or does arithmetic.
const CURRENCY_SYMBOLS = {USD: "$", CAD: "$", AUD: "$", NZD: "$", MXN: "$", EUR: "€", GBP: "£", INR: "₹", JPY: "¥"};
let homeCurrency = "";
function amount(value, {signed = true} = {}) {
  const text = typeof value === "string" ? value : value?.display;
  const span = element("span", "", "amount");
  const match = /^(-)?([\d,]+(?:\.\d+)?) ([A-Z]{3})$/.exec(text || "");
  if (!match) { span.textContent = text ?? "—"; return span; }
  const [, minus, magnitude, currency] = match, zero = /^[0,.]+$/.test(magnitude);
  const direction = minus ? "out" : zero ? "zero" : "in";
  const sign = minus ? "−" : signed && !zero ? "+" : "";
  if (signed) { span.dataset.direction = direction; span.appendChild(element("span", direction === "out" ? "money out " : direction === "in" ? "money in " : "", "visually-hidden")); }
  const symbol = currency === homeCurrency ? CURRENCY_SYMBOLS[currency] : "";
  span.appendChild(document.createTextNode(symbol ? `${sign}${symbol}${magnitude}` : `${sign}${magnitude} ${currency}`));
  span.title = text;
  return span;
}

// Dates: ISO in, "Sep 24, 2026" out, always with the year; the ISO value stays available as a tooltip.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function dateText(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!match) return iso || "—";
  const [, year, month, day] = match;
  return `${MONTHS[Number(month) - 1]} ${Number(day)}, ${year}`;
}
function dateDisplay(iso) {
  const time = document.createElement("time"); time.textContent = dateText(iso);
  if (iso) { time.dateTime = iso; time.title = iso; }
  return time;
}

function emptyState(message, action = null) {
  const box = element("div", "", "empty-state"); box.appendChild(element("p", message));
  if (action) box.appendChild(action);
  return box;
}
function alertBox(message, {tone = "info", action = null, detail = ""} = {}) {
  const box = element("div", "", "alert"); box.dataset.tone = tone;
  if (tone === "error") box.setAttribute("role", "alert");
  box.append(icon(tone === "error" ? "octagon" : tone === "warning" ? "alert" : "info"));
  const body = element("div", "", "alert-body"); body.appendChild(element("p", message));
  if (detail) body.appendChild(technicalDetail(detail));
  if (action) body.appendChild(action);
  box.appendChild(body);
  return box;
}
function technicalDetail(detail) {
  const box = element("details", "", "technical-detail");
  box.append(element("summary", "Technical details"), element("pre", detail));
  return box;
}

// Toasts replace the old single notice line. Successes fade; errors stay until dismissed.
function toast(message, {tone = "success", detail = "", timeout = tone === "error" ? 0 : 6000} = {}) {
  const region = $("toasts"), item = element("div", "", "toast"); item.dataset.tone = tone;
  item.append(icon(tone === "error" ? "octagon" : tone === "info" ? "info" : "check"));
  const body = element("div", "", "toast-body");
  if (tone === "error") body.appendChild(element("span", "Error: ", "visually-hidden"));
  body.appendChild(element("p", message));
  if (detail) body.appendChild(technicalDetail(detail));
  const close = element("button", "", "icon-button quiet"); close.type = "button"; close.setAttribute("aria-label", "Dismiss");
  close.appendChild(icon("x")); close.addEventListener("click", () => item.remove());
  item.append(body, close);
  region.appendChild(item);
  while (region.children.length > 4) region.firstElementChild.remove();
  if (timeout) {
    let timer = setTimeout(() => item.remove(), timeout);
    item.addEventListener("mouseenter", () => clearTimeout(timer));
    item.addEventListener("focusin", () => clearTimeout(timer));
    item.addEventListener("mouseleave", () => { timer = setTimeout(() => item.remove(), timeout); });
  }
  return item;
}

// Overflow menu: a button that opens a list of menu items. Items are ordinary buttons made by the caller.
function menu(label, items) {
  const wrap = element("div", "", "menu");
  const trigger = element("button", "", "icon-button menu-trigger"); trigger.type = "button";
  trigger.setAttribute("aria-label", label); trigger.setAttribute("aria-haspopup", "menu"); trigger.setAttribute("aria-expanded", "false");
  trigger.appendChild(icon("more"));
  const list = element("div", "", "menu-list"); list.setAttribute("role", "menu"); list.hidden = true;
  const entries = () => [...list.querySelectorAll('[role="menuitem"]:not(:disabled)')];
  for (const item of items) {
    if (item.tagName === "BUTTON") { item.setAttribute("role", "menuitem"); item.tabIndex = -1; item.addEventListener("click", () => close(false)); }
    else item.setAttribute("role", "none");
    list.appendChild(item);
  }
  function outside(event) { if (!wrap.contains(event.target)) close(false); }
  function place() {
    // Fixed positioning escapes scrolling table containers; opens upward when there is no room below.
    const box = trigger.getBoundingClientRect(), below = window.innerHeight - box.bottom;
    list.style.right = `${window.innerWidth - box.right}px`;
    const upward = below < list.offsetHeight + 8 && box.top > below;
    list.style.top = upward ? "" : `${box.bottom + 4}px`;
    list.style.bottom = upward ? `${window.innerHeight - box.top + 4}px` : "";
  }
  function dismiss() {
    // Follow the trigger while it stays visible; close once it scrolls away.
    const box = trigger.getBoundingClientRect();
    if (box.bottom < 0 || box.top > window.innerHeight || box.right < 0 || box.left > window.innerWidth) close(false); else place();
  }
  function close(focus = true) {
    if (list.hidden) return;
    list.hidden = true; trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outside);
    window.removeEventListener("scroll", dismiss, true); window.removeEventListener("resize", dismiss);
    if (focus) trigger.focus();
    wrap.dispatchEvent(new CustomEvent("menuclose", {bubbles: true}));
  }
  function open() {
    list.hidden = false; trigger.setAttribute("aria-expanded", "true");
    place();
    document.addEventListener("pointerdown", outside);
    window.addEventListener("scroll", dismiss, true); window.addEventListener("resize", dismiss);
    entries()[0]?.focus();
  }
  trigger.addEventListener("click", () => list.hidden ? open() : close());
  list.addEventListener("keydown", event => {
    const all = entries(), index = all.indexOf(document.activeElement);
    const moves = {ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: all.length - 1};
    if (event.key in moves) { event.preventDefault(); all[(moves[event.key] + all.length) % all.length]?.focus(); }
    else if (event.key === "Escape") { event.preventDefault(); close(); }
    else if (event.key === "Tab") close(false);
  });
  wrap.append(trigger, list);
  return wrap;
}

// Confirmation for consequential actions. Resolves true only when the user confirms.
function confirmAction({title, message, confirmLabel, danger = false}) {
  const dialog = $("confirm-dialog");
  $("confirm-title").textContent = title; $("confirm-message").textContent = message;
  $("confirm-accept").textContent = confirmLabel; $("confirm-accept").className = danger ? "danger" : "primary";
  return new Promise(resolve => {
    const finish = result => { dialog.close(); resolve(result); };
    $("confirm-accept").onclick = () => finish(true);
    $("confirm-cancel").onclick = () => finish(false);
    dialog.oncancel = () => resolve(false);
    dialog.showModal(); $("confirm-cancel").focus();
  });
}
