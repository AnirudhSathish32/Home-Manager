"use strict";
const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has("token")) {
  sessionStorage.setItem("home-manager-token", fragment.get("token"));
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("home-manager-token") || "";
let configured = false, busy = false, selectedJob = "", docOffset = 0, eventOffset = 0;
const pageSize = 100;
function notice(text, error = false) {
  $("notice").textContent = text; $("notice").className = error ? "error" : "";
  $("settings-notice").textContent = text; $("settings-notice").className = error ? "error" : "";
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {"Authorization": `Bearer ${token}`, "Content-Type": "application/json"}});
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
  return body;
}
function controls() {
  $("parse-all-receipts").disabled = !configured || busy;
  for (const id of ["save-vision", "vision-url", "vision-model", "force-receipts", "auto-organize", "confirm-library-action"]) $(id).disabled = busy;
  document.querySelectorAll("[data-library-action]").forEach(button => { button.disabled = busy; });
  $("scan").disabled = !configured || busy;
  $("save-settings").disabled = busy;
  $("source").disabled = busy;
  $("managed").disabled = busy;
  if (typeof receiptControls === "function") receiptControls();
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
  configured = settings.configured; busy = settings.busy;
  $("source").value = settings.source_directory;
  $("managed").value = settings.managed_directory;
  $("vision-url").value = settings.vision.base_url;
  $("vision-model").value = settings.vision.model;
  $("auto-organize").checked = settings.vision.organize_after_scan;
  showReceiptBatch(settings.receipt_batch);
  $("limits").textContent = `Capture limits: ${settings.max_file_mib} MiB per file; ${settings.max_store_gib} GiB of unique preserved evidence.`;
  if (settings.startup_error) notice(settings.startup_error, true);
  else if (!configured) notice("Open Settings using the gear icon to choose your directories.");
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
  if (job.organization_status) $("scan-state").textContent += ` · Organization: ${job.organization_status}. ${job.organization_message || ""}`;
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
  const folder = activeFolder, offset = docOffset;
  const data = await api(`/api/documents?offset=${offset}&limit=${pageSize}&folder=${encodeURIComponent(folder)}`);
  const catalog = await api("/api/folders");
  if (folder !== activeFolder || offset !== docOffset) return;
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
    if (/\.(png|jpe?g)$/i.test(doc.relative_path)) {
      const inspect = document.createElement("button"); inspect.type = "button"; inspect.textContent = "Inspect this version";
      inspect.addEventListener("click", () => { $("versions-dialog").close(); openReceipt(doc, version.hash).catch(e => notice(e.message, true)); });
      p.appendChild(inspect);
    }
  }
  $("versions-dialog").showModal();
}
async function refresh() {
  if (!configured) return;
  await loadJobs(); await loadEvents(); await loadDocuments();
}
$("settings-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/settings", {method:"PUT", body:JSON.stringify({source_directory:$("source").value.trim(), managed_directory:$("managed").value.trim()})});
    if (typeof closeReceipt === "function") closeReceipt();
    selectedJob = ""; docOffset = eventOffset = 0;
    activeFolder = "all";
    await loadSettings(); await refresh(); notice("Directories saved. You can scan your documents now.");
  } catch (error) { notice(error.message, true); }
});
$("scan-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const scope = {year:$("year").value ? Number($("year").value) : null, month:$("month").value ? Number($("month").value) : null};
    if (scope.month && !scope.year) throw new Error("Select a year when choosing a month.");
    busy = true; controls();
    const job = await api("/api/scans", {method:"POST", body:JSON.stringify(scope)});
    selectedJob = job.job_id; eventOffset = 0; notice("Scan started. You can leave this page open to follow progress.");
    await refresh();
  } catch (error) { notice(error.message, true); busy = false; controls(); }
});
$("scans").addEventListener("change", () => { selectedJob = $("scans").value; eventOffset = 0; loadEvents().catch(e => notice(e.message, true)); });
$("refresh").addEventListener("click", () => refresh().catch(e => notice(e.message, true)));
$("close-versions").addEventListener("click", () => $("versions-dialog").close());
for (const [id, delta, type] of [["docs-prev",-pageSize,"docs"],["docs-next",pageSize,"docs"],["events-prev",-pageSize,"events"],["events-next",pageSize,"events"]]) {
  $(id).addEventListener("click", () => {
    if (type === "docs") { docOffset = Math.max(0, docOffset + delta); loadDocuments().catch(e => notice(e.message,true)); }
    else { eventOffset = Math.max(0,eventOffset + delta); loadEvents().catch(e => notice(e.message,true)); }
  });
}
async function poll() {
  try {
    if (configured) {
      const settings = await api("/api/settings");
      const wasBusy = busy; busy = settings.busy; controls();
      showReceiptBatch(settings.receipt_batch);
      if (busy || wasBusy) await refresh();
      if (typeof pollReceipt === "function") await pollReceipt();
    }
  } catch (error) { notice(error.message, true); }
  finally { setTimeout(poll, 1500); }
}
loadSettings().then(refresh).then(poll).catch(error => notice(error.message, true));

function showReceiptBatch(batch) {
  $("receipt-batch-status").textContent = batch ?
    `Batch ${batch.status}: ${batch.total} documents; ${Object.entries(batch.counts).map(([state, count]) => `${count} ${state}`).join(", ")}. ${batch.unique_runs} distinct images; ${batch.reused} reused/duplicate results; ${batch.skipped} unsupported documents skipped.` : "No receipt batch yet.";
}
$("vision-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/vision-settings", {method:"PUT", body:JSON.stringify({base_url:$("vision-url").value.trim(), model:$("vision-model").value.trim(), organize_after_scan:$("auto-organize").checked})});
    notice("Local model settings saved. Start the model server before parsing; saving does not test the connection.");
  } catch (error) { notice(error.message, true); }
});
$("parse-all-receipts").addEventListener("click", async () => {
  try {
    busy = true; controls();
    await api("/api/receipt-batches", {method:"POST", body:JSON.stringify({force:$("force-receipts").checked})});
    notice("Receipt batch queued. Titles and parsing progress appear in the library as results are saved.");
    await refresh();
  } catch (error) { busy = false; controls(); notice(error.message, true); }
});
