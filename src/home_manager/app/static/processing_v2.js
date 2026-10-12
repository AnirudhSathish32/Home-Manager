"use strict";
// Processing, redesigned (docs/ui.md "Processing"; design-system/home-manager/pages/system.md): what is running now and
// each pipeline stage's state over five tabs (Recent work, Data health, Watched folders, Scans, Model runs), each drawn on
// its first show. processing.js keeps JOB_KINDS, LANES, duration and whenText; app.js keeps cancelButton, seconds,
// tokenRate and receiptBatch, calls renderPr2Activity on every poll, and calls pr2Refresh while this screen shows, while
// work runs and when it finishes.
const PR2_TABS = ["work", "health", "folders", "scans", "models"];
// The view (in the URL): tab; kind and failed (Recent work); task and status (Model runs). history and reconciliation:
// the lanes' last runs; health: the newest health report (or {error}); scan and offset: the Scans tab's place;
// stale: tabs to draw on their next show; generation: each tab's newest draw, so an older one finishing late draws nothing.
// healthShown: the Data health tab drew pr2.health already. nowKey: the Now running list's work and stages as drawn.
const pr2 = {tab: "work", kind: "", failed: false, task: "", status: "", history: [], reconciliation: null, health: null, healthShown: false,
             scan: "", offset: 0, stale: new Set(PR2_TABS), generation: {}, nowKey: "", opener: null};
const PR2_HEALTH_LINKS = 20;

V2_SCREENS.processing = {title: "Processing", show: route => loadProcessingV2(route.params)};

const activatePr2Tab = wireTabs(PR2_TABS.map(tab => `pr2-tab-${tab}`));
for (const tab of PR2_TABS) $(`pr2-tab-${tab}`).addEventListener("tabshow", () => {
  pr2.tab = tab; pr2Url();
  // Model runs refetch their task and status lists on every show, so new tasks appear in the filter.
  if (pr2.stale.has(tab) || tab === "models") pr2Draw(tab);
});
$("pr2-kind").replaceChildren(new Option("All kinds of work", ""), ...Object.entries(JOB_KINDS).map(([value, label]) => new Option(label, value)));

function loadProcessingV2(params) {
  const tab = params?.get?.("tab");
  pr2.tab = PR2_TABS.includes(tab) ? tab : "work";
  const kind = params?.get?.("kind") || "", status = params?.get?.("status") || "";
  pr2.kind = pr2.tab === "work" && kind in JOB_KINDS ? kind : "";
  pr2.failed = pr2.tab === "work" && status === "failed";
  pr2.task = pr2.tab === "models" ? (params?.get?.("task") || "").slice(0, 40) : "";
  pr2.status = pr2.tab === "models" ? status.slice(0, 20) : "";
  $("pr2-kind").value = pr2.kind;
  pr2Chips();
  return pr2Reload();
}
function pr2Reload() {
  pr2.stale = new Set(PR2_TABS);
  return pageState($("pr2-state"), renderProcessingV2, {loading: "Loading processing …", what: "processing", needsLibrary: true, content: [$("pr2-body")]});
}
async function renderProcessingV2() {
  pr2.healthShown = false;
  await Promise.all([pr2LoadStrip(), pr2LoadHealth()]);
  pr2HealthCount();
  activatePr2Tab(`pr2-tab-${pr2.tab}`);  // Draws the shown tab (tabshow).
}
// While work runs or just finished (app.js poll): the strip and the shown tab. Data health is checked again on its next show.
async function pr2Refresh() {
  if (currentRoute?.name !== "processing") return;
  await pr2LoadStrip();
  for (const tab of PR2_TABS) if (tab !== pr2.tab) pr2.stale.add(tab);
  if (pr2.tab === "health") pr2.stale.add("health"); else await pr2Draw(pr2.tab, {quiet: true});
}
// The view into the URL (Layout rule 5): only what differs from the defaults, and only the shown tab's own controls.
function pr2Url() {
  const next = new URLSearchParams();
  if (pr2.tab !== "work") next.set("tab", pr2.tab);
  if (pr2.tab === "work" && pr2.kind) next.set("kind", pr2.kind);
  if (pr2.tab === "work" && pr2.failed) next.set("status", "failed");
  if (pr2.tab === "models" && pr2.task) next.set("task", pr2.task);
  if (pr2.tab === "models" && pr2.status) next.set("status", pr2.status);
  if (currentRoute?.name === "processing") currentRoute.params = next;
  history.replaceState(null, "", `#/processing${[...next].length ? `?${next}` : ""}`);
}

// One tab's draw: a loading line after 300 ms, then the content, or an error with Retry in the tab only. quiet: a poll's
// redraw, which shows no loading line.
const PR2_DRAWS = {work: renderWorkTab, health: renderHealthTab, folders: renderFoldersTab, scans: renderScansTab, models: renderModelsTab};
const PR2_WHAT = {work: "recent work", health: "data health", folders: "watched folders", scans: "scans", models: "model runs"};
async function pr2Draw(tab, {quiet = false} = {}) {
  const panel = $(`pr2-${tab}-panel`);
  let status = panel.querySelector(":scope > .pr2-tab-state");
  if (!status) { status = element("div", "", "pr2-tab-state"); panel.prepend(status); }
  const generation = (pr2.generation[tab] || 0) + 1;
  pr2.generation[tab] = generation; pr2.stale.delete(tab);
  const current = () => pr2.generation[tab] === generation;
  const timer = quiet ? 0 : setTimeout(() => {
    if (!current()) return;
    const line = element("p", "", "page-loading"); line.setAttribute("role", "status");
    line.append(icon("loader", "icon spin"), `Loading ${PR2_WHAT[tab]} …`);
    status.replaceChildren(line);
  }, 300);
  try {
    await PR2_DRAWS[tab](current);
    if (current()) status.replaceChildren();
  } catch (error) {
    if (!current()) return;
    pr2.stale.add(tab);
    const retry = element("button", "Retry", "secondary"); retry.type = "button";
    retry.addEventListener("click", () => pr2Draw(tab));
    status.replaceChildren(alertBox(`Couldn't load ${PR2_WHAT[tab]}. ${error?.message || error}`, {tone: "error", detail: error?.detail || "", action: retry}));
  } finally { clearTimeout(timer); }
}
// columns: [title, className] pairs; an empty title is the actions column. rows: <tr> elements.
function pr2Table(columns, rows, className = "") {
  return dataTable(columns.map(([title, cls = ""]) => [title || element("span", "Actions", "visually-hidden"), cls]), rows, {className});
}
function pr2Count(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

// The strip: Now running, then one column per pipeline stage --------------------------------------------------------
async function pr2LoadStrip() {
  const [history, reconciliations] = await Promise.all([api("/api/jobs?limit=200"), api("/api/finance/reconciliation-runs?limit=1")]);
  pr2.history = history; pr2.reconciliation = reconciliations[0] || null;
  renderPr2Activity(lastActivity);
}
// Called by app.js renderActivity on every poll. The Now running list is a polite live region: it is replaced only when
// the work or its stage changes, and the seconds count in place (hidden from screen readers) so it doesn't chatter.
function renderPr2Activity(activity) {
  const list = $("pr2-activity"), work = activity || [];
  const key = JSON.stringify(work.map(item => [item.id, item.status, item.progress?.stage]));
  if (key !== pr2.nowKey) {
    pr2.nowKey = key;
    if (!work.length) list.replaceChildren(element("li", "Nothing running.", "pr2-now-idle"));
    else list.replaceChildren(...work.map(item => {
      const li = element("li", "", "pr2-now-row"), text = element("span", "", "pr2-now-text");
      text.append(element("strong", item.label));
      if (item.progress) text.append(element("span", ` · ${statusLabel(item.progress.stage)}`, "pr2-now-stage"));
      const elapsed = element("span", "", "pr2-now-stage"); elapsed.dataset.work = item.id; elapsed.setAttribute("aria-hidden", "true");
      text.append(elapsed);
      li.append(statusBadge(item.status), text);
      if (item.queue === "inference" && ["queued", "running"].includes(item.status)) {
        const cancel = cancelButton(item);
        cancel.setAttribute("aria-label", `Cancel ${item.label.replace(/^./, character => character.toLowerCase())}`);
        li.append(cancel);
      }
      return li;
    }));
  }
  for (const item of work) {
    const elapsed = list.querySelector(`[data-work="${CSS.escape(String(item.id))}"]`);
    if (elapsed) elapsed.textContent = item.progress ? ` · ${item.progress.elapsed_seconds} s` : "";
  }
  renderPr2Lanes(work);
}
function renderPr2Lanes(activity) {
  const batch = receiptBatch;
  $("pr2-lanes").replaceChildren(...LANES.map(([title, liveKinds, historyKinds]) => {
    const lane = element("div", "", "pr2-lane"), live = activity.filter(work => liveKinds.includes(work.kind));
    lane.append(element("p", title, "pr2-lane-title"));
    const last = title === "Reconciliation" ? pr2.reconciliation : pr2.history.find(row => historyKinds.includes(row.kind));
    if (live.length) {
      const running = live.find(work => work.status === "running") || live[0];
      lane.append(statusBadge(running.status));
      const queued = live.filter(work => work.status === "queued").length;
      if (queued) lane.append(element("p", `${queued} queued`, "pr2-lane-last"));
    } else lane.append(last ? statusBadge("idle") : element("p", "Not run yet", "pr2-lane-state"));
    if (last) {
      const line = element("p", "", "pr2-lane-last");
      line.append(`Last ${whenText(last.started_at)} `, statusBadge(last.status));
      lane.append(line);
    }
    if (title === "Reconciliation" && last) {
      lane.append(element("p", `${pr2Count(last.receipt_links ?? 0, "link", "links")} · ${last.open_issues ?? 0} open`, "pr2-lane-last"));
    }
    if (title === "Reading" && ["running", "queued"].includes(batch?.status)) lane.append(element("p", receiptBatchText(batch), "pr2-lane-last"));
    if (title === "Reading" && !modelsConfigured.vision) lane.append(homeLink("Set up a vision model", "#/settings", "small"));
    if (["Recording", "Item identification"].includes(title) && !modelsConfigured.reasoning) lane.append(homeLink("Set up a reasoning model", "#/settings", "small"));
    return lane;
  }));
}

// Header actions --------------------------------------------------------------------------------------------------
$("pr2-scan").addEventListener("click", async () => {
  try {
    busy.capture = true; controls();
    const result = await api("/api/inbox-scans", {method: "POST", body: "{}"});
    pr2.scan = result.job_id; pr2.offset = 0;
    notice("Inbox capture started. Files are preserved before any organization.");
    await Promise.all([refresh(), pr2Refresh()]);
  } catch (error) { busy.capture = false; controls(); notice(error, true); }
});
function pr2ReadMenu(open, focusButton = false) {
  $("pr2-read-menu").hidden = !open; $("pr2-read").setAttribute("aria-expanded", String(open));
  if (open) $("pr2-force").focus(); else if (focusButton) $("pr2-read").focus();
}
$("pr2-read").addEventListener("click", () => pr2ReadMenu($("pr2-read-menu").hidden));
$("pr2-read-menu").addEventListener("keydown", event => { if (event.key === "Escape") { event.preventDefault(); pr2ReadMenu(false, true); } });
document.addEventListener("pointerdown", event => { if (!$("pr2-read-menu").hidden && !event.target.closest(".pr2-read")) pr2ReadMenu(false); });
$("pr2-read-start").addEventListener("click", async () => {
  try {
    busy.inference = true; controls();
    await api("/api/receipt-batches", {method: "POST", body: JSON.stringify({force: $("pr2-force").checked})});
    pr2ReadMenu(false, true);
    notice("Text extraction queued. Progress appears here and in the sidebar; results appear in the library as they are saved.");
    await pr2Refresh();
  } catch (error) { busy.inference = false; controls(); notice(error, true); }
});

// Recent work -----------------------------------------------------------------------------------------------------
async function renderWorkTab(current) {
  const query = new URLSearchParams({limit: pr2.failed ? 200 : 50});
  if (pr2.kind) query.append("kind", pr2.kind);
  const jobs = (await api(`/api/jobs?${query}`)).filter(job => !pr2.failed || job.status === "failed");
  if (!current()) return;
  if (!jobs.length) {
    $("pr2-work").replaceChildren(emptyState(pr2.failed ? "No failed work." : pr2.kind ? "No work of this kind yet." : "No work recorded yet."));
    return;
  }
  $("pr2-work").replaceChildren(pr2Table([["Work"], ["Started"], ["Took", "numeric"], ["Result"], ["Details"]], jobs.map(job => {
    const tr = document.createElement("tr");
    cell(tr, JOB_KINDS[job.kind] || statusLabel(job.kind)); cell(tr, whenText(job.started_at));
    cell(tr, duration(job.started_at, job.finished_at)).className = "numeric";
    cell(tr, "").append(statusBadge(job.status));
    const details = cell(tr, ""), links = element("div", "", "pr2-details");
    if (job.document_id) links.append(homeLink("Open document", `#/documents/${job.document_id}`));
    if (job.kind === "inbox_capture") {
      const files = element("button", "Show files", "link-button"); files.type = "button";
      files.addEventListener("click", () => { pr2.scan = job.id; pr2.offset = 0; pr2.stale.add("scans"); activatePr2Tab("pr2-tab-scans"); $("pr2-tab-scans").focus(); });
      links.append(files);
    }
    details.append(links);
    if (job.error) details.append(technicalDetail(job.error));
    return tr;
  }), "pr2-work-table"));
}
$("pr2-kind").addEventListener("change", () => { pr2.kind = $("pr2-kind").value; pr2Url(); pr2Draw("work"); });
function pr2Chips() {
  for (const chip of document.querySelectorAll("#pr2-work-panel [data-result]")) chip.setAttribute("aria-pressed", String((chip.dataset.result === "failed") === pr2.failed));
}
for (const chip of document.querySelectorAll("#pr2-work-panel [data-result]")) chip.addEventListener("click", () => {
  pr2.failed = chip.dataset.result === "failed"; pr2Chips(); pr2Url(); pr2Draw("work");
});

// Data health -----------------------------------------------------------------------------------------------------
async function pr2LoadHealth() {
  pr2.health = await api("/api/finance/health").catch(error => ({error}));
}
// The tab's name carries the count of errors and warnings (notes are expected while records are incomplete); none after
// a failed check.
function pr2HealthCount() {
  const button = $("pr2-tab-health"), summary = pr2.health?.summary;
  const count = summary ? summary.error + summary.warning : 0;
  button.replaceChildren(icon("heart-pulse"), "Data health");
  if (count) {
    button.append(element("span", String(count), "nav-count attention"));
    button.setAttribute("aria-label", `Data health, ${pr2Count(count, "problem", "problems")}`);
  } else button.removeAttribute("aria-label");
}
const PR2_SEVERITY = {error: ["health_error", "error", "errors", "octagon"], warning: ["health_warning", "warning", "warnings", "alert"],
                      info: ["health_info", "note", "notes", "info"]};
// The record's kind as words ("investment_event" → "Investment event"); not statusLabel, whose STATUS words differ.
function pr2RecordName(problem) {
  return `${problem.record_type.replaceAll("_", " ").replace(/^./, character => character.toUpperCase())} #${problem.record_id}`;
}
function pr2RecordHref(link) {
  return link?.document_id ? `#/documents/${link.document_id}` : link?.investment_account_id ? `#/investments?account=${link.investment_account_id}` : "";
}
async function renderHealthTab(current) {
  // The page's load checked the ledger just now; a later draw (after work ran, or Retry) checks it again.
  if (pr2.healthShown || !pr2.health || pr2.health.error) await pr2LoadHealth();
  if (!current()) return;
  pr2.healthShown = true;
  pr2HealthCount();
  if (pr2.health.error) throw pr2.health.error;
  const {summary, problems, tax_engines: engines} = pr2.health;
  const line = element("div", "", "pr2-health-summary");
  if (!problems.length) line.append(statusBadge("health_ok"));
  else for (const severity of ["warning", "error", "info"]) {
    const [status, one, many] = PR2_SEVERITY[severity];
    line.append(statusBadge(summary[severity] ? status : "", "", pr2Count(summary[severity], one, many)));
  }
  // One row per rule, in the server's order (errors first).
  const rules = new Map();
  for (const problem of problems) {
    if (!rules.has(problem.code)) rules.set(problem.code, []);
    rules.get(problem.code).push(problem);
  }
  const list = element("ul", "", "needs-list pr2-health-list");
  for (const [code, records] of rules) {
    const first = records[0], [, one, , glyph] = PR2_SEVERITY[first.severity];
    const row = element("li", "", `needs-row pr2-health-row${first.severity === "warning" ? " attention" : first.severity === "error" ? " error" : ""}`);
    const text = element("div", "", "pr2-health-text");
    text.append(element("strong", first.detail), element("small", `${pr2Count(records.length, "record", "records")} · ${one}`, "muted"));
    let action = element("span");
    if (records.length === 1 && first.link) {
      action = element("a", "Open", "needs-action"); action.href = pr2RecordHref(first.link);
      action.setAttribute("aria-label", `Open ${pr2RecordName(first).toLowerCase()}`);
    } else {
      const disclosure = element("details", "", "pr2-records");
      disclosure.append(element("summary", records.length === 1 ? "Which record" : `Which ${records.length} records`));
      const items = element("ul", "", "pr2-record-list");
      for (const problem of records.slice(0, PR2_HEALTH_LINKS)) {
        const li = document.createElement("li"), href = pr2RecordHref(problem.link);
        li.append(href ? homeLink(pr2RecordName(problem), href) : element("span", `${pr2RecordName(problem)} (no page to open)`, "muted"));
        items.append(li);
      }
      disclosure.append(items);
      if (records.length > PR2_HEALTH_LINKS) {
        const more = element("p", `and ${records.length - PR2_HEALTH_LINKS} more (run `, "muted small");
        more.append(element("code", "home-manager check-ledger"), " for all)");
        disclosure.append(more);
      }
      text.append(disclosure);
    }
    text.append(technicalDetail(code));
    row.append(icon(glyph, "icon needs-icon"), text, action);
    list.append(row);
  }
  const engineList = element("ul", "", "pr2-engines");
  for (const engine of engines) {
    const li = element("li", "", "pr2-engine"), head = element("div", "", "pr2-engine-head");
    head.append(element("strong", engine.label), statusBadge(engine.ready ? "succeeded" : "not_started", "", engine.ready ? "Ready" : "Not ready"));
    li.append(head, element("p", engine.note, "muted small"));
    engineList.append(li);
  }
  const engineRegion = element("section", "", "today-region");
  engineRegion.setAttribute("aria-labelledby", "pr2-engines-title");
  const heading = element("h2", "Tax engines"); heading.id = "pr2-engines-title";
  engineRegion.append(heading, engineList);
  $("pr2-health").replaceChildren(line, ...(problems.length ? [list] : []), engineRegion);
}

// Watched folders -------------------------------------------------------------------------------------------------
async function renderFoldersTab(current) {
  const usable = configured && !familyMode;
  $("pr2-inbox").textContent = usable && inboxDirectory ? `Inbox: ${inboxDirectory}` : "";
  $("pr2-add-source").hidden = !usable;
  if (!usable) { $("pr2-folders").replaceChildren(emptyState("Choose a library folder first.")); return; }
  const sources = await api("/api/sources");
  if (!current()) return;
  if (!sources.length) { $("pr2-folders").replaceChildren(emptyState("No watched folders. Only Inbox is read.")); return; }
  $("pr2-folders").replaceChildren(pr2Table([["Folder"], ["Subfolders"], ["Last scan"], [""]], sources.map(source => {
    const row = document.createElement("tr"), where = cell(row, ""), name = source.label || source.path.split(/[\\/]/).pop();
    where.append(element("strong", name), element("div", source.path, "path-text"));
    if (!source.enabled) where.append(element("div", "Paused", "muted small"));
    cell(row, source.recursive ? "Included" : "Not included");
    cell(row, source.last_scan_at ? whenText(source.last_scan_at) : "Not yet");
    const actions = element("div", "", "button-row pr2-source-actions");
    const scan = asyncButton("Scan now", async () => {
      const result = await api(`/api/sources/${source.id}/scans`, {method: "POST", body: "{}"});
      pr2.scan = result.job_id; pr2.offset = 0;
      notice("Watched folder scan started. Files are copied; the folder is not changed.");
      await Promise.all([refresh(), pr2Refresh()]);
    });
    const pause = asyncButton(source.enabled ? "Pause" : "Resume", async () => {
      await api(`/api/sources/${source.id}`, {method: "PATCH", body: JSON.stringify({enabled: !source.enabled})});
      await pr2Draw("folders", {quiet: true});
    });
    const stop = asyncButton("Stop watching", async () => {
      if (!await confirmAction({title: "Stop watching this folder?", message: "New files there will no longer be copied in. Documents already copied from it stay in the library, and the folder is not changed.",
                                confirmLabel: "Stop watching", danger: true})) return;
      await api(`/api/sources/${source.id}`, {method: "DELETE"});
      notice("Folder no longer watched. Its documents stay in the library.");
      await pr2Draw("folders", {quiet: true});
    });
    for (const [button, words] of [[scan, "Scan"], [pause, source.enabled ? "Pause" : "Resume"], [stop, "Stop watching"]]) button.setAttribute("aria-label", `${words} ${name}`);
    actions.append(scan, pause, stop);
    cell(row, "").append(actions);
    return row;
  }), "pr2-folders-table"));
}
function openSourceDialog() {
  pr2.opener = document.activeElement;
  const form = $("pr2-source-form");
  form.reset(); clearFieldErrors(form);
  $("pr2-source-dialog").showModal();
  $("pr2-source-path").focus();
}
function pr2SourceClose() { $("pr2-source-dialog").close(); pr2.opener?.focus?.(); }
$("pr2-add-source").prepend(icon("plus"));
$("pr2-add-source").addEventListener("click", openSourceDialog);
$("pr2-source-cancel").addEventListener("click", pr2SourceClose);
$("pr2-source-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = $("pr2-source-form"), path = $("pr2-source-path").value.trim();
  clearFieldErrors(form);
  if (!path) { fieldError(form, "path", "Enter the folder's full path."); return; }
  $("pr2-source-save").disabled = true;
  try {
    await api("/api/sources", {method: "POST", body: JSON.stringify({path, label: $("pr2-source-label").value.trim(), recursive: $("pr2-source-recursive").checked})});
    pr2SourceClose();
    notice("Folder added. It is scanned within a minute, and new files are copied in from then on.");
    await pr2Draw("folders", {quiet: true});
  } catch (error) {
    fieldError(form, errorField(error) || "path", error.message || String(error));
  } finally { $("pr2-source-save").disabled = false; }
});

// Scans ------------------------------------------------------------------------------------------------------------
async function renderScansTab(current) {
  const scans = await api("/api/scans");
  if (!current()) return;
  const select = $("pr2-scans");
  if (!scans.length) {
    select.replaceChildren(new Option("No scans yet", "")); select.disabled = true;
    $("pr2-scan-state").textContent = "No scans yet.";
    $("pr2-events").replaceChildren(); $("pr2-events-page").textContent = "";
    $("pr2-events-prev").disabled = $("pr2-events-next").disabled = true;
    return;
  }
  select.disabled = false;
  select.replaceChildren(...scans.map(scan => new Option(`${whenText(scan.created_at)} · ${statusLabel(scan.status)} · ${scan.year || "all years"}/${scan.month || "all months"}`, scan.id)));
  if (!scans.some(scan => scan.id === pr2.scan)) { pr2.scan = scans[0].id; pr2.offset = 0; }
  select.value = pr2.scan;
  await pr2Events(current);
}
async function pr2Events(current = () => true) {
  const [scan, events] = await Promise.all([api(`/api/scans/${encodeURIComponent(pr2.scan)}`),
                                            api(`/api/scans/${encodeURIComponent(pr2.scan)}/events?offset=${pr2.offset}&limit=${pageSize}`)]);
  if (!current()) return;
  const counts = Object.entries(scan.counts).map(([key, value]) => `${value} ${key}`).join(", ");
  let state = `${statusLabel(scan.status)} — ${counts || "Waiting for file inventory"}${scan.error ? `. ${scan.error}` : ""}`;
  if (scan.organization_status) state += ` · Text extraction: ${scan.organization_status}. ${scan.organization_message || ""}`;
  $("pr2-scan-state").textContent = state;
  const rows = events.map(event => {
    const row = document.createElement("tr");
    cell(row, event.relative_path).className = "pr2-path"; cell(row, event.status); cell(row, event.message);
    return row;
  });
  if (rows.length) $("pr2-events").replaceChildren(...rows); else tableMessage($("pr2-events"), 3, "No files in this scan.");
  $("pr2-events-prev").disabled = pr2.offset === 0;
  $("pr2-events-next").disabled = events.length < pageSize;
  $("pr2-events-page").textContent = events.length ? `${pr2.offset + 1}–${pr2.offset + events.length}` : "No results on this page";
}
$("pr2-scans").addEventListener("change", () => { pr2.scan = $("pr2-scans").value; pr2.offset = 0; pr2Events().catch(error => notice(error, true)); });
for (const [id, delta] of [["pr2-events-prev", -pageSize], ["pr2-events-next", pageSize]]) $(id).addEventListener("click", () => {
  pr2.offset = Math.max(0, pr2.offset + delta); pr2Events().catch(error => notice(error, true));
});

// Model runs -------------------------------------------------------------------------------------------------------
async function renderModelsTab(current) {
  const query = new URLSearchParams({limit: 50});
  if (pr2.task) query.set("task", pr2.task);
  if (pr2.status) query.set("status", pr2.status);
  const [facets, runs] = await Promise.all([api("/api/model-runs/facets"), api(`/api/model-runs?${query}`)]);
  if (!current()) return;
  for (const [id, values, label, chosen] of [["pr2-task", facets.tasks, "All tasks", pr2.task], ["pr2-status", facets.statuses, "All statuses", pr2.status]]) {
    // A value from the URL that no run has (yet) stays chosen, so the empty result explains itself.
    const options = chosen && !values.includes(chosen) ? [...values, chosen] : values;
    $(id).replaceChildren(new Option(label, ""), ...options.map(value => new Option(statusLabel(value), value)));
    $(id).value = chosen;
  }
  if (!runs.length) {
    $("pr2-models").replaceChildren(emptyState(pr2.task || pr2.status ? "No model requests match these filters." : "No model requests yet."));
    return;
  }
  $("pr2-models").replaceChildren(pr2Table([["Started"], ["Task"], ["Model"], ["Status"], ["Prompt tokens", "numeric"], ["Completion tokens", "numeric"],
                                            ["Time to first token", "numeric"], ["Generation", "numeric"], ["Model time", "numeric"]], runs.map(run => {
    const row = document.createElement("tr");
    cell(row, whenText(run.started_at)); cell(row, statusLabel(run.task)); cell(row, run.model_id).className = "pr2-path";
    cell(row, "").append(statusBadge(run.status));
    for (const value of [run.prompt_tokens ?? "—", run.completion_tokens ?? "—", seconds(run.time_to_first_token_ms), tokenRate(run), seconds(run.total_ms)])
      cell(row, value).className = "numeric";
    return row;
  }), "pr2-models-table"));
}
for (const [id, key] of [["pr2-task", "task"], ["pr2-status", "status"]]) $(id).addEventListener("change", () => {
  pr2[key] = $(id).value; pr2Url(); pr2Draw("models");
});
