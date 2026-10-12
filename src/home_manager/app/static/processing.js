"use strict";
// Processing's shared parts (processing_v2.js draws the page; docs/ui.md "Processing"), and Settings' connection tests
// and backups.
const JOB_KINDS = {inbox_capture: "Inbox capture", text_batch: "Reading documents (batch)", text_reading: "Reading a document", ledger_extraction: "Recording to the ledger",
                   item_identification: "Identifying receipt items", reconciliation: "Reconciliation", backup: "Backup", assistant: "Assistant question",
                   audit_analysis: "Audit analysis", checkin_text: "Check-in answer", warranty_lookup: "Warranty lookup", tax_table_lookup: "Tax table lookup"};
// Lane -> [live work kinds, history kinds].
const LANES = [["Capture", ["capture"], ["inbox_capture"]], ["Reading", ["transcription"], ["text_batch", "text_reading"]],
               ["Recording", ["extraction", "item_categories"], ["ledger_extraction"]], ["Item identification", ["item_resolution"], ["item_identification"]],
               ["Reconciliation", ["recurring_scan"], ["reconciliation"]]];
let lastActivity = [];  // The running work from the latest poll (app.js renderActivity).

function duration(start, end) {
  if (!start || !end) return "—";
  const ms = new Date(end) - new Date(start);
  return ms < 1000 ? "<1 s" : ms < 60000 ? `${Math.round(ms / 1000)} s` : `${Math.round(ms / 60000)} min`;
}
function whenText(iso) { return iso ? new Date(iso).toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"}) : "—"; }

// Settings depth (Phase E): connection tests and backup & restore.
for (const button of document.querySelectorAll("[data-test]")) button.addEventListener("click", async () => {
  const kind = button.dataset.test, target = $(`test-${kind}-result`), provider = $(`${kind}-provider`);
  button.disabled = true; target.replaceChildren(element("p", "Asking the local server which models it serves…", "muted small"));
  try {
    const body = {base_url: $(`${kind}-url`).value.trim(), model: $(`${kind}-model`).value.trim(), ...(provider ? {provider: provider.value} : {})};
    const result = await api(button.dataset.endpoint || "/api/model-connection-tests", {method: "POST", body: JSON.stringify(body)});
    const ok = result.reachable && result.model_listed && !result.problem;
    const done = provider ? "The model answers with option probabilities." : "The server lists this model.";
    const parts = [alertBox(ok ? `Connected in ${result.latency_ms} ms. ${done}` : result.problem, {tone: ok ? "info" : "warning"})];
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
$("backup-tab").addEventListener("tabshow", () => loadBackups().catch(error => notice(error, true)));
$("backup-form").addEventListener("submit", async event => {
  event.preventDefault();
  busy.capture = true; controls();  // Back up now stays unavailable until this backup finishes (app.js controls).
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
  } catch (error) { notice(error, true); busy.capture = false; controls(); }
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
