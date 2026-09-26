"use strict";
// Processing (docs/ui-design-plan.md §3.9, Phase E): pipeline lanes, one history of every kind of work, and model runs.
const JOB_KINDS = {inbox_capture: "Inbox capture", text_batch: "Reading documents (batch)", text_reading: "Reading a document", ledger_extraction: "Recording to the ledger",
                   item_identification: "Identifying receipt items", reconciliation: "Reconciliation", backup: "Backup", assistant: "Assistant question",
                   audit_analysis: "Audit analysis", checkin_text: "Check-in answer", warranty_lookup: "Warranty lookup"};
// Lane -> [live work kinds, history kinds].
const LANES = [["Capture", ["capture"], ["inbox_capture"]], ["Reading", ["transcription"], ["text_batch", "text_reading"]],
               ["Recording", ["extraction"], ["ledger_extraction"]], ["Item identification", ["item_resolution"], ["item_identification"]],
               ["Reconciliation", [], ["reconciliation"]]];
let processingLoad = 0, lastActivity = [];

function duration(start, end) {
  if (!start || !end) return "—";
  const ms = new Date(end) - new Date(start);
  return ms < 1000 ? "<1 s" : ms < 60000 ? `${Math.round(ms / 1000)} s` : `${Math.round(ms / 60000)} min`;
}
function whenText(iso) { return iso ? new Date(iso).toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"}) : "—"; }

async function loadProcessing() {
  if (!configured) return;
  const load = ++processingLoad;
  const [latest, reconciliations] = await Promise.all([api("/api/jobs?limit=200"), api("/api/finance/reconciliation-runs?limit=1")]);
  if (load !== processingLoad) return;
  renderLanes(latest, reconciliations[0]);
  await Promise.all([loadJobHistory(), loadModelFacets()]);
}
function renderLanes(history, reconciliation) {
  const lanes = LANES.map(([title, liveKinds, historyKinds]) => {
    const card = element("div", "", "pipeline-lane"), live = lastActivity.filter(work => liveKinds.includes(work.kind));
    card.append(element("h3", title));
    if (live.length) {
      const running = live.find(work => work.status === "running") || live[0];
      card.append(statusBadge(running.status), element("small", `${running.label}${running.progress ? ` · ${running.progress.stage.replaceAll("_", " ")} · ${running.progress.elapsed_seconds} s` : ""}`, "block"));
      const queued = live.filter(work => work.status === "queued").length;
      if (queued) card.append(element("small", `${queued} queued`, "muted block"));
    } else card.append(element("span", "Idle", "muted"));
    const last = title === "Reconciliation" ? null : history.find(row => historyKinds.includes(row.kind));
    if (title === "Reconciliation" && reconciliation) {
      card.append(element("small", `Last run ${whenText(reconciliation.started_at)} · ${statusLabel(reconciliation.status)}`, "muted block"),
                  element("small", `${reconciliation.receipt_links ?? 0} receipt links · ${reconciliation.transfers ?? 0} transfers · ${reconciliation.refunds ?? 0} refunds · ${reconciliation.open_issues ?? 0} open questions`, "muted block"));
    } else if (last) card.append(element("small", `Last ${whenText(last.started_at)} · ${statusLabel(last.status)}`, "muted block"));
    else card.append(element("small", "Not run yet", "muted block"));
    if (title === "Reading" && !modelsConfigured.vision) card.append(homeLink("Set up a vision model", "#/settings", "small block"));
    if (["Recording", "Item identification"].includes(title) && !modelsConfigured.reasoning) card.append(homeLink("Set up a reasoning model", "#/settings", "small block"));
    return card;
  });
  $("pipeline-lanes").replaceChildren(...lanes);
}
async function loadJobHistory() {
  const kind = $("job-kind").value, query = new URLSearchParams({limit: 50});
  if (kind) query.append("kind", kind);
  const jobs = await api(`/api/jobs?${query}`);
  const rows = jobs.map(job => {
    const tr = document.createElement("tr");
    cell(tr, JOB_KINDS[job.kind] || statusLabel(job.kind)); cell(tr, whenText(job.started_at));
    cell(tr, duration(job.started_at, job.finished_at)).className = "numeric";
    cell(tr, "").append(statusBadge(job.status));
    const details = cell(tr, "");
    if (job.document_id) details.append(homeLink("Open document", `#/documents/${job.document_id}`));
    if (job.kind === "inbox_capture") {
      const view = element("button", "Show files", "link-button"); view.type = "button";
      view.addEventListener("click", () => { selectedJob = job.id; eventOffset = 0; $("scans").value = job.id; loadEvents().then(() => $("events").scrollIntoView({block: "center"})).catch(error => notice(error, true)); });
      details.append(view);
    }
    if (job.error) details.append(technicalDetail(job.error));
    return tr;
  });
  if (rows.length) $("job-rows").replaceChildren(...rows); else tableMessage($("job-rows"), 5, "No work recorded yet.");
}
async function loadModelFacets() {
  const facets = await api("/api/model-runs/facets");
  for (const [id, values, label] of [["model-task", facets.tasks, "All tasks"], ["model-status", facets.statuses, "All statuses"]]) {
    const chosen = $(id).value;
    $(id).replaceChildren(new Option(label, ""), ...values.map(value => new Option(statusLabel(value), value)));
    $(id).value = values.includes(chosen) ? chosen : "";
  }
}
// Settings depth (Phase E): connection tests and backup & restore.
for (const button of document.querySelectorAll("[data-test]")) button.addEventListener("click", async () => {
  const kind = button.dataset.test, target = $(`test-${kind}-result`);
  button.disabled = true; target.replaceChildren(element("p", "Asking the local server which models it serves…", "muted small"));
  try {
    const result = await api("/api/model-connection-tests", {method: "POST", body: JSON.stringify({base_url: $(`${kind}-url`).value.trim(), model: $(`${kind}-model`).value.trim()})});
    const ok = result.reachable && result.model_listed;
    const parts = [alertBox(ok ? `Connected in ${result.latency_ms} ms. The server lists this model.` : result.problem, {tone: ok ? "info" : "warning"})];
    if (result.available_models.length) {
      const list = element("ul", "", "model-list");
      for (const id of result.available_models) {
        const choose = element("button", id, "link-button"); choose.type = "button";
        choose.addEventListener("click", () => { $(`${kind}-model`).value = id; notice(`Model ID set to ${id}. Save to use it.`); });
        const li = document.createElement("li"); li.append(choose); list.append(li);
      }
      parts.push(element("p", "Models the server lists (select one to use it):", "muted small"), list);
    }
    target.replaceChildren(...parts);
  } catch (error) { target.replaceChildren(alertBox(error.message, {tone: "error"})); }
  finally { button.disabled = false; }
});
function sizeText(bytes) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB"]; let value = bytes, unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}
async function loadBackups() {
  if (!configured) return;
  const backups = await api("/api/backups");
  const rows = backups.map(backup => {
    const tr = document.createElement("tr");
    cell(tr, whenText(backup.started_at)); cell(tr, "").append(statusBadge(backup.status));
    cell(tr, backup.file_count ?? "—").className = "numeric"; cell(tr, sizeText(backup.total_bytes)).className = "numeric";
    const where = cell(tr, backup.destination); where.className = "path-text";
    if (backup.error) where.append(technicalDetail(backup.error));
    return tr;
  });
  if (rows.length) $("backup-rows").replaceChildren(...rows); else tableMessage($("backup-rows"), 5, "No backups yet.");
}
$("backup-tab").addEventListener("click", () => loadBackups().catch(error => notice(error, true)));
$("backup-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/backups", {method: "POST", body: JSON.stringify({destination: $("backup-destination").value.trim()})});
    notice("Backup started. Progress shows in the sidebar; the list updates when it finishes.");
    let running = true;
    while (running) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      const [latest] = await api("/api/backups?limit=1");
      running = latest?.status === "running";
      await loadBackups();
      if (!running && latest) notice(latest.status === "succeeded" ? `Backup finished: ${latest.file_count} files.` : `The backup ${statusLabel(latest.status).toLowerCase()}. ${latest.error || ""}`, latest.status !== "succeeded");
    }
  } catch (error) { notice(error, true); }
});
$("restore-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!await confirmAction({title: "Restore this backup?", message: "Home Manager checks every file against the backup's manifest and builds a new library in the folder you chose. Your open library isn't changed.", confirmLabel: "Verify and restore"})) return;
  try {
    const {restore_id} = await api("/api/restores", {method: "POST", body: JSON.stringify({backup: $("restore-backup").value.trim(), target: $("restore-target").value.trim()})});
    $("restore-status").textContent = "Verifying and restoring…";
    let record;
    do { await new Promise(resolve => setTimeout(resolve, 1500)); record = await api(`/api/restores/${restore_id}`); } while (record.status === "running");
    $("restore-status").textContent = record.status === "succeeded"
      ? `Restored ${record.result.files} files to ${record.result.restored_to}. To use it, enter that folder in Library folder.`
      : `The restore ${statusLabel(record.status).toLowerCase()}. ${record.error || ""}`;
  } catch (error) { $("restore-status").textContent = error.message; }
});

$("job-kind").replaceChildren(new Option("All kinds of work", ""), ...Object.entries(JOB_KINDS).map(([value, label]) => new Option(label, value)));
$("job-kind").addEventListener("change", () => loadJobHistory().catch(error => notice(error, true)));
for (const id of ["model-task", "model-status"]) $(id).addEventListener("change", () => loadModelHistory().catch(error => notice(error, true)));
