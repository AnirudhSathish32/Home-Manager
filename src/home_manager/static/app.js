"use strict";
const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has("token")) {
  sessionStorage.setItem("home-manager-token", fragment.get("token"));
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("home-manager-token") || "";
// Capture and model inference are independent queues; library actions wait for neither.
let savedManaged = "", inboxDirectory = "", modelsConfigured = {vision: false, reasoning: false}, configured = false, busy = {capture: false, inference: false}, selectedJob = "", docOffset = 0, eventOffset = 0;
const pageSize = 100;
function element(tag, text = "", className = "") {
  const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
}
function wireTabs(ids) {
  function activate(id) {
    for (const key of ids) {
      const tab = $(key), active = key === id;
      tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1;
      $(tab.getAttribute("aria-controls")).hidden = !active;
    }
  }
  ids.forEach((id, index) => {
    $(id).addEventListener("click", () => activate(id));
    $(id).addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const forward = ["ArrowRight", "ArrowDown"].includes(event.key);
      const next = event.key === "Home" ? 0 : event.key === "End" ? ids.length - 1 : (index + (forward ? 1 : -1) + ids.length) % ids.length;
      activate(ids[next]); $(ids[next]).focus();
    });
  });
  return activate;
}
function notice(message, error = false) {
  // Accepts text or an Error; ApiError carries the server's technical detail separately.
  toast(message instanceof Error ? message.message : message, {tone: error ? "error" : "success", detail: message?.detail || ""});
}
class ApiError extends Error {
  constructor(message, status = 0, detail = "") { super(message); this.status = status; this.detail = detail; }
}
function apiError(status, detail) {
  // The server writes user-facing sentences for expected failures; only translate the rest.
  if (Array.isArray(detail)) {
    const problems = detail.map(item => `${(item.loc || []).filter(part => part !== "body").join(" ") || "value"}: ${String(item.msg || "").replace(/^Value error, /, "")}`);
    return new ApiError(`Some values weren't accepted. ${problems[0]}${problems.length > 1 ? ` (+${problems.length - 1} more)` : ""}`, status, JSON.stringify(detail, null, 2));
  }
  if (typeof detail === "string" && detail && status < 500) return new ApiError(detail, status);
  if (status >= 500) return new ApiError("Home Manager hit an unexpected problem with this request. Try again; if it keeps happening, restart Home Manager.", status, detail ? String(detail) : `HTTP ${status}`);
  return new ApiError(`The request failed (HTTP ${status}).`, status, detail ? JSON.stringify(detail) : "");
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {...options, headers: {"Authorization": `Bearer ${token}`, "Content-Type": "application/json"}}); }
  catch (error) { throw new ApiError("Home Manager isn't responding. It may have been closed; start it again from its launcher.", 0, String(error)); }
  let body = null;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) throw apiError(response.status, body?.detail);
  return body;
}
const anyBusy = () => busy.capture || busy.inference;
function setBusy(settings) { busy = {capture: settings.capture_busy, inference: settings.inference_busy}; }
function controls() {
  $("parse-all-receipts").disabled = !configured || busy.inference;
  for (const id of ["save-reasoning", "reasoning-url", "reasoning-model", "save-vision", "vision-url", "vision-model", "force-receipts", "auto-organize"]) $(id).disabled = busy.inference;
  for (const id of ["scan", "scan-inbox"]) $(id).disabled = !configured || busy.capture;
  for (const id of ["save-settings", "source", "managed"]) $(id).disabled = anyBusy();
  document.querySelectorAll("[data-step]").forEach(button => { button.disabled = busy.inference; });
  if (typeof receiptControls === "function") receiptControls();
  if (typeof renderSelection === "function") renderSelection();
}
function seconds(ms) { return ms == null ? "—" : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`; }
function tokenRate(run) {
  return run.generation_tokens_per_second == null ? "—" : `${run.metrics_source === "estimated" ? "~" : ""}${run.generation_tokens_per_second.toFixed(1)} tok/s`;
}
function telemetryText(run) {
  const source = {server_timings: "server timings", server_usage: "server token counts", estimated: "estimated from characters"}[run.metrics_source];
  return `${run.model_id} · ${run.status} · prompt ${run.prompt_tokens ?? "—"} tok · completion ${run.completion_tokens ?? "—"} tok · ` +
    `first token ${seconds(run.time_to_first_token_ms)} · generation ${tokenRate(run)} · model time ${seconds(run.total_ms)} (${source})`;
}
function cancelButton(work) {
  const cancel = element("button", "Cancel", "small"); cancel.type = "button";
  cancel.addEventListener("click", () => api("/api/activity/cancel", {method:"POST", body:JSON.stringify({work_id:work.id})})
    .then(() => notice("Cancellation requested. Completed results are kept; nothing partial is published."), error => notice(error, true)));
  return cancel;
}
function renderActivityIndicator(activity) {
  // Sidebar summary of running work; silent when idle.
  const target = $("activity-indicator"); target.replaceChildren();
  const work = activity.find(item => item.queue === "inference" && item.status === "running") || activity[0];
  target.hidden = !work;
  if (!work) return;
  const stage = work.progress ? `${work.progress.stage.replaceAll("_", " ")} · ${work.progress.elapsed_seconds} s` : statusLabel(work.status);
  const link = element("a", "", "activity-summary"); link.href = "#/processing";
  link.append(element("span", "", "activity-dot"), element("span", work.label, "activity-label"),
              element("span", `${stage}${activity.length > 1 ? ` · +${activity.length - 1} more` : ""}`, "activity-stage"));
  target.appendChild(link);
  if (work.queue === "inference" && ["queued", "running"].includes(work.status)) target.appendChild(cancelButton(work));
}
function renderActivity(activity) {
  renderActivityIndicator(activity);
  $("activity").replaceChildren();
  if (!activity.length) $("activity").appendChild(element("li", "No active scans or model work.", "muted"));
  for (const work of activity) {
    const item = element("li", "", "activity-item");
    const text = element("div", "", "activity-text");
    text.append(element("strong", work.label), element("small", `${work.queue === "inference" ? "Model queue" : "Capture queue"}${work.progress ? ` · ${work.progress.stage.replaceAll("_", " ")} · ${work.progress.characters} characters · ${work.progress.elapsed_seconds} s` : ""}`));
    item.append(statusBadge(work.status), text);
    if (work.queue === "inference" && ["queued", "running"].includes(work.status)) item.appendChild(cancelButton(work));
    $("activity").appendChild(item);
  }
}
async function loadModelHistory() {
  const runs = await api("/api/model-runs?limit=25");
  $("model-history").replaceChildren();
  for (const run of runs) {
    const row = document.createElement("tr");
    cell(row, new Date(run.started_at).toLocaleString()); cell(row, run.task); cell(row, run.model_id); cell(row, "").appendChild(statusBadge(run.status));
    for (const value of [run.prompt_tokens ?? "—", run.completion_tokens ?? "—", seconds(run.time_to_first_token_ms), tokenRate(run), seconds(run.total_ms)])
      cell(row, value).className = "numeric";
    $("model-history").appendChild(row);
  }
  if (!runs.length) { const row = document.createElement("tr"); cell(row, "No model requests yet.").colSpan = 9; $("model-history").appendChild(row); }
}
function cell(row, value, code = false) {
  const td = document.createElement("td");
  const target = code ? document.createElement("code") : td;
  target.textContent = String(value ?? "");
  if (code) td.appendChild(target);
  row.appendChild(td);
  return td;
}
async function loadSettings() {
  const settings = await api("/api/settings");
  configured = settings.configured; setBusy(settings); renderActivity(settings.activity);
  $("source").value = settings.source_directory;
  $("managed").value = settings.managed_directory;
  inboxDirectory = settings.inbox_directory || "";
  modelsConfigured = {vision: Boolean(settings.vision.model), reasoning: Boolean(settings.reasoning.model)};
  $("inbox-location").textContent = settings.inbox_directory ? `Drop files into ${settings.inbox_directory}` : "Configure directories to create your managed Inbox.";
  $("vision-url").value = settings.vision.base_url;
  $("vision-model").value = settings.vision.model;
  $("reasoning-url").value = settings.reasoning.base_url;
  $("reasoning-model").value = settings.reasoning.model;
  $("laya-status").textContent = settings.laya.installed
    ? `Laya is installed (revision ${settings.laya.revision.slice(0, 12)}) and checks every ledger extraction on this computer. A value it cannot confirm sends the record to review; it never approves one.`
    : `Laya weights are not installed at ${settings.laya.path}.`;
  $("auto-organize").checked = settings.vision.organize_after_scan;
  $("home-currency").value = homeCurrency = settings.household.home_currency || "";
  showReceiptBatch(settings.receipt_batch);
  $("limits").textContent = `Capture limits: ${settings.max_file_mib} MiB per file; ${settings.max_store_gib} GiB of unique preserved evidence.`;
  savedManaged = settings.managed_directory;
  const setup = element("a", "Open Settings", "button primary"); setup.href = "#/settings";
  $("app-alert").replaceChildren(...(settings.startup_error ? [alertBox(settings.startup_error, {tone: "error"})]
    : !configured ? [alertBox("Choose where Home Manager keeps its library to get started.", {action: setup})] : []));
  controls();
}
async function loadJobs() {
  const jobs = await api("/api/scans");
  const selector = $("scans"); selector.replaceChildren();
  if (!jobs.length) selector.add(new Option("No scans yet", ""));
  for (const job of jobs) selector.add(new Option(`${new Date(job.created_at).toLocaleString()} · ${job.status} · ${job.year || "all years"}/${job.month || "all months"}`, job.id));
  if (!selectedJob && jobs.length) selectedJob = jobs[0].id;
  if (jobs.some(job => job.id === selectedJob)) selector.value = selectedJob;
}
async function loadEvents() {
  if (!selectedJob) return;
  const job = await api(`/api/scans/${selectedJob}`);
  $("scan-state").textContent = `${job.status} — ${Object.entries(job.counts).map(([key,value]) => `${value} ${key}`).join(", ") || "Waiting for file inventory"}${job.error ? ". " + job.error : ""}`;
  if (job.organization_status) $("scan-state").textContent += ` · Text extraction: ${job.organization_status}. ${job.organization_message || ""}`;
  const events = await api(`/api/scans/${selectedJob}/events?offset=${eventOffset}&limit=${pageSize}`);
  $("events").replaceChildren();
  for (const event of events) {
    const row = document.createElement("tr");
    cell(row, event.relative_path); cell(row, event.status); cell(row, event.message);
    $("events").appendChild(row);
  }
  $("events-prev").disabled = eventOffset === 0;
  $("events-next").disabled = events.length < pageSize;
  $("events-page").textContent = events.length ? `${eventOffset + 1}–${eventOffset + events.length}` : "No results on this page";
}
async function loadDocuments() {
  const params = new URLSearchParams({offset: docOffset, limit: pageSize, folder: activeFolder, status: activeStatus, q: searchQuery, sort: activeSort});
  if (activeFrom) params.set("date_from", activeFrom);
  if (activeTo) params.set("date_to", activeTo);
  const requested = params.toString();
  const data = await api(`/api/documents?${requested}`);
  const catalog = await api("/api/folders");
  // A newer filter, page or sort supersedes this response.
  const current = new URLSearchParams({offset: docOffset, limit: pageSize, folder: activeFolder, status: activeStatus, q: searchQuery, sort: activeSort});
  if (activeFrom) current.set("date_from", activeFrom);
  if (activeTo) current.set("date_to", activeTo);
  if (current.toString() !== requested) return;
  renderFolders(catalog); renderDocuments(data);
  $("docs-prev").disabled = docOffset === 0;
  $("docs-next").disabled = docOffset + pageSize >= data.total;
  $("docs-page").textContent = data.items.length ? `${docOffset + 1}–${docOffset + data.items.length} of ${data.total}` : "No documents on this page";
}
async function showVersions(doc) {
  const versions = await api(`/api/documents/${doc.id}/versions`);
  $("versions-path").textContent = doc.relative_path;
  $("versions-content").replaceChildren();
  for (const version of versions) {
    const p = document.createElement("p"), hash = document.createElement("code");
    p.textContent = `${new Date(version.captured_at).toLocaleString()} · ${version.size.toLocaleString()} bytes${version.hash === doc.current_hash ? " · Current" : ""}`;
    hash.textContent = version.hash; p.appendChild(hash); $("versions-content").appendChild(p);
    if (/\.(png|jpe?g|pdf)$/i.test(doc.relative_path)) {
      const inspect = document.createElement("button"); inspect.type = "button"; inspect.textContent = "Inspect this version";
      inspect.addEventListener("click", () => { $("versions-dialog").close(); location.hash = `#/documents/${doc.id}?version=${version.hash}`; });
      p.appendChild(inspect);
    }
  }
  $("versions-dialog").showModal();
}
async function refresh() {
  if (!configured) return;
  await loadJobs(); await loadEvents(); await loadDocuments(); await loadModelHistory();
}
$("settings-form").addEventListener("submit", async event => {
  event.preventDefault();
  const managed = $("managed").value.trim();
  if (configured && managed !== savedManaged && !await confirmAction({title: "Switch to a different library?",
      message: `Home Manager will open the library at ${managed}. The current library stays on disk unchanged; switch back by entering its folder again.`,
      confirmLabel: "Switch library"})) return;
  try {
    await api("/api/settings", {method:"PUT", body:JSON.stringify({source_directory:$("source").value.trim(), managed_directory:managed})});
    if (typeof closeReceipt === "function") closeReceipt();
    selectedJob = ""; docOffset = eventOffset = 0;
    activeFolder = "all"; activeStatus = "all";
    await loadSettings(); await refresh(); notice("Directories saved. You can scan your documents now.");
  } catch (error) { notice(error, true); }
});
$("scans").addEventListener("change", () => { selectedJob = $("scans").value; eventOffset = 0; loadEvents().catch(e => notice(e, true)); });
$("refresh").addEventListener("click", () => refresh().catch(e => notice(e, true)));
$("close-versions").addEventListener("click", () => $("versions-dialog").close());
for (const [id, delta, type] of [["docs-prev",-pageSize,"docs"],["docs-next",pageSize,"docs"],["events-prev",-pageSize,"events"],["events-next",pageSize,"events"]]) {
  $(id).addEventListener("click", () => {
    if (type === "docs") { docOffset = Math.max(0, docOffset + delta); loadDocuments().catch(e => notice(e, true)); }
    else { eventOffset = Math.max(0,eventOffset + delta); loadEvents().catch(e => notice(e, true)); }
  });
}
async function poll() {
  try {
    if (configured) {
      const settings = await api("/api/settings");
      const wasBusy = anyBusy(); setBusy(settings); controls();
      showReceiptBatch(settings.receipt_batch); renderActivity(settings.activity);
      if (anyBusy() || wasBusy) await refresh();
      if (typeof pollReceipt === "function") await pollReceipt();
    }
    if (pollFailure) { pollFailure = null; $("app-alert").replaceChildren(); }
  } catch (error) {
    // Background polling reports one persistent alert, not a toast every tick.
    if (!pollFailure || pollFailure.message !== error.message) {
      pollFailure = error;
      $("app-alert").replaceChildren(alertBox(error.message, {tone: "error", detail: error.detail || ""}));
    }
  }
  finally { setTimeout(poll, 1500); }
}
let pollFailure = null;
loadSettings().then(refresh).then(() => showRoute(false)).then(poll).catch(error => notice(error, true));

function showReceiptBatch(batch) {
  $("receipt-batch-status").textContent = batch ?
    `Batch ${batch.status}: ${batch.total} documents; ${Object.entries(batch.counts).map(([state, count]) => `${count} ${state}`).join(", ")}. ${batch.unique_runs} distinct images; ${batch.reused} reused/duplicate results; ${batch.skipped} unsupported documents skipped.` : "";
}
function saveSettingsForm(form, path, body, message) {
  $(form).addEventListener("submit", async event => {
    event.preventDefault();
    try { await api(path, {method:"PUT", body:JSON.stringify(body())}); notice(message); await loadSettings(); }
    catch (error) { notice(error, true); }
  });
}
saveSettingsForm("vision-form", "/api/vision-settings",
  () => ({base_url:$("vision-url").value.trim(), model:$("vision-model").value.trim(), organize_after_scan:$("auto-organize").checked}),
  "Local model settings saved. Start the model server before parsing; saving does not test the connection.");
saveSettingsForm("reasoning-form", "/api/reasoning-settings",
  () => ({base_url:$("reasoning-url").value.trim(), model:$("reasoning-model").value.trim()}),
  "Reasoning settings saved. Open a read document and select Extract to ledger.");
saveSettingsForm("household-form", "/api/household-settings", () => ({home_currency: $("home-currency").value || null}),
  "Home currency saved. Extract documents to the ledger again to apply it.");
for (const [id, path, message] of [["scan", "/api/scans", "Scan started. Source files are read, never changed."],
                                   ["scan-inbox", "/api/inbox-scans", "Inbox capture started. Files are preserved before any organization."]]) {
  $(id).addEventListener("click", async () => {
    try {
      busy.capture = true; controls();
      const result = await api(path, {method:"POST", body:"{}"});
      selectedJob = result.job_id; eventOffset = 0;
      notice(message);
      await refresh();
    } catch (error) { busy.capture = false; controls(); notice(error, true); }
  });
}
$("parse-all-receipts").addEventListener("click", async () => {
  try {
    busy.inference = true; controls();
    await api("/api/receipt-batches", {method:"POST", body:JSON.stringify({force:$("force-receipts").checked})});
    notice("Text extraction queued. Progress appears in the sidebar and results appear in the library as they are saved.");
    await refresh();
  } catch (error) { busy.inference = false; controls(); notice(error, true); }
});
