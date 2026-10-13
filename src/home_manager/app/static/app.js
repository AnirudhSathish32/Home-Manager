"use strict";
const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has("token")) {
  sessionStorage.setItem("home-manager-token", fragment.get("token"));
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("home-manager-token") || "";
// Capture and model inference are independent queues; library actions wait for neither.
// familyMode: a family profile is open. It has no library of its own; only Home and Settings apply.
let savedManaged = "", savedDecision = {}, savedReviewer = {}, inboxDirectory = "", modelsConfigured = {vision: false, reasoning: false}, configured = false, familyMode = false, busy = {capture: false, inference: false};
const pageSize = 100;
// Screens: route → {title, show}. Each screen registers itself here from its own script, which loads before shell.js
// routes the first page (docs/ui.md "Pages").
const V2_SCREENS = {};
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
    // However the tab was reached (click, arrow keys, Home/End or code), its panel can load: listen for "tabshow".
    $(id).dispatchEvent(new CustomEvent("tabshow"));
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
  // The person chosen in Who's here (profiles.js), so the server records changes and decisions under their name.
  const headers = {"Authorization": `Bearer ${token}`, "Content-Type": "application/json", ...(whoIsHere ? {"X-HM-Actor": encodeURIComponent(whoIsHere)} : {})};
  try { response = await fetch(path, {...options, headers}); }
  catch (error) { throw new ApiError("Home Manager isn't responding. It may have been closed; start it again from its launcher.", 0, String(error)); }
  let body = null;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) throw apiError(response.status, body?.detail);
  return body;
}
let whoIsHere = null;  // Set by profiles.js renderWho from the profile's people.
const anyBusy = () => busy.capture || busy.inference;
function setBusy(settings) { busy = {capture: settings.capture_busy, inference: settings.inference_busy}; }
function controls() {
  for (const id of ["save-reasoning", "reasoning-url", "reasoning-model", "reasoning-schema", "save-vision", "vision-url", "vision-model", "auto-organize", "save-reviewer"]) $(id).disabled = busy.inference;
  $("reviewer-busy").hidden = !busy.inference;
  $("pr2-scan").disabled = !configured || busy.capture;
  $("pr2-read").disabled = $("pr2-read-start").disabled = !configured || busy.inference;
  // Work that runs on in the background stays unavailable until it finishes, so a second click can't start it twice.
  if ($("bills2-scan")) $("bills2-scan").disabled = !configured || busy.inference;
  $("backup-start").disabled = !configured || busy.capture;
  $("share-export").disabled = !configured || anyBusy();
  for (const id of ["save-settings", "managed"]) $(id).disabled = anyBusy();
  document.querySelectorAll("[data-step]").forEach(button => { button.disabled = busy.inference; });
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
  // Processing (processing_v2.js): its Now running line and lanes.
  if (typeof lastActivity !== "undefined") lastActivity = activity;
  if (typeof renderPr2Activity === "function") renderPr2Activity(activity);
}
function cell(row, value, code = false) {
  const td = document.createElement("td");
  const target = code ? document.createElement("code") : td;
  target.textContent = String(value ?? "");
  if (code) td.appendChild(target);
  row.appendChild(td);
  return td;
}
// Shared-library session: a banner while one is open; the whole app reloads when it opens or ends.
let sessionShown = null, sessionFailure = null;
function renderSession(settings) {
  const session = settings.session, opening = settings.session_opening;
  if (opening?.status === "failed" && sessionFailure !== opening.id) {
    sessionFailure = opening.id; notice(`The shared library could not be opened. ${opening.error || ""}`, true);
  }
  if (!session) { $("session-banner").replaceChildren(); }
  else {
    const end = element("button", "End session", "primary");
    end.type = "button"; end.id = "session-end";
    end.addEventListener("click", async () => {
      try { await api("/api/sessions/current", {method: "DELETE"}); notice("Session ended. The shared copy was deleted and your library is open again."); await sessionChanged(); }
      catch (error) { notice(error, true); }
    });
    const shared = session.shared_at ? `, shared ${session.shared_at.slice(0, 10)}` : "";
    $("session-banner").replaceChildren(alertBox(`You are viewing “${session.label}”${shared}. Changes stay in this temporary copy and are deleted when you end the session. Your own library is closed and untouched.`,
      {tone: "warning", action: end}));
  }
  const changed = (session?.id || null) !== sessionShown;
  sessionShown = session?.id || null;
  return changed;
}
async function sessionChanged() {
  await loadSettings(); await refresh(); showRoute(false);
}
async function loadSettings() {
  const settings = await api("/api/settings");
  configured = settings.configured; familyMode = Boolean(settings.family);
  document.body.classList.toggle("family-mode", familyMode);
  setBusy(settings); renderActivity(settings.activity); renderSession(settings); renderProfiles(settings);
  $("managed").value = settings.managed_directory;
  inboxDirectory = settings.inbox_directory || "";
  const familyGpu = settings.model_computer.provider === "family_gpu";
  modelsConfigured = familyGpu ? {vision: true, reasoning: true} : {vision: Boolean(settings.vision.model), reasoning: Boolean(settings.reasoning.model)};
  renderModelComputer(settings.model_computer);
  $("vision-url").value = settings.vision.base_url;
  $("vision-model").value = settings.vision.model;
  $("reasoning-url").value = settings.reasoning.base_url;
  $("reasoning-model").value = settings.reasoning.model;
  $("reasoning-schema").checked = settings.reasoning.schema_enforced !== false;
  const decision = savedDecision = settings.decision;
  $("decision-provider").value = decision.provider;
  $("decision-url").value = decision.base_url;
  $("decision-model").value = decision.model;
  const decisionOn = decision.provider !== "off" && decision.model;
  $("decision-status").textContent = !decisionOn ? "No decision model is chosen, so extractions are not checked independently."
    : `${decision.model} checks every ledger extraction. ${decision.calibrated ? "It is calibrated on your documents." : "It is not yet calibrated on your documents, so its scores are a hint."}`;
  const reviewer = savedReviewer = settings.reviewer;
  $("reviewer-kind").value = reviewer.provider;
  $("reviewer-url").value = reviewer.base_url;
  $("reviewer-model").value = reviewer.model;
  showReviewerKind();
  $("auto-organize").checked = settings.vision.organize_after_scan;
  $("home-currency").value = homeCurrency = settings.household.home_currency || "";
  $("checkin-weekday").value = String(settings.household.checkin_weekday ?? 6);
  $("auto-identify").checked = settings.household.auto_identify_items !== false;
  $("fetch-rates").checked = settings.household.fetch_exchange_rates !== false;
  $("fetch-prices").checked = settings.household.fetch_crypto_prices === true;
  $("rescan-hours").value = settings.household.rescan_hours ?? 6;
  $("filing-status").value = settings.household.filing_status || "single";
  $("birth-year").value = settings.household.birth_year ?? "";
  // Whether the year's return can be worked out here (finance/tax_engine.py readiness), and where the licenses are.
  const engine = settings.tax_engine;
  const seconds = (settings.tax_engines || []).filter(item => item.slot !== engine?.slot);
  const notes = [engine?.note, ...seconds.map(item => item.ready ? `${item.label} can check it.` : item.note)].filter(Boolean);
  $("tax-engine-status").textContent = engine ? `${notes.join(" ")} Open-source components and their licenses are listed in vendor/NOTICES.md where Home Manager is installed.` : "";
  $("tax-engine-status").classList.toggle("item-warning", Boolean(engine && !engine.ready));
  // The second opinion is offered once another engine can run here.
  $("tax-compare-field").hidden = !seconds.some(item => item.ready);
  $("tax-compare").checked = settings.household.tax_engine_compare !== false;
  showReceiptBatch(settings.receipt_batch);
  $("limits").textContent = `Capture limits: ${settings.max_file_mib} MiB per file; ${settings.max_store_gib} GiB of unique preserved evidence.`;
  savedManaged = settings.managed_directory;
  const setup = element("a", "Open Settings", "button primary"); setup.href = "#/settings";
  $("app-alert").replaceChildren(...(settings.startup_error ? [alertBox(settings.startup_error, {tone: "error"})]
    : !configured && !familyMode ? [alertBox("Choose where Home Manager keeps its library to get started.", {action: setup})] : []));
  controls();
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
// What every page shares after work finishes: the sidebar's counts (library.js renderNavCounts).
async function refresh() {
  if (!configured) return;
  await renderNavCounts();
}
$("settings-form").addEventListener("submit", async event => {
  event.preventDefault();
  const managed = $("managed").value.trim();
  if (configured && managed !== savedManaged && !await confirmAction({title: "Switch to a different library?",
      message: `Home Manager will open the library at ${managed}. The current library stays on disk unchanged; switch back by entering its folder again.`,
      confirmLabel: "Switch library"})) return;
  try {
    await api("/api/settings", {method:"PUT", body:JSON.stringify({managed_directory:managed})});
    await loadSettings(); await refresh(); notice("Library folder saved. Drop documents into its Inbox.");
  } catch (error) { notice(error, true); }
});
$("close-versions").addEventListener("click", () => $("versions-dialog").close());
async function poll() {
  try {
    if (configured) {
      const settings = await api("/api/settings");
      const libraryChanged = settings.library_version !== lastLibraryVersion;
      const wasBusy = anyBusy(); setBusy(settings); controls();
      showReceiptBatch(settings.receipt_batch); renderActivity(settings.activity);
      // Member status in a family view; a finished family share or delivery updates the status lines.
      if (familyMode || (wasBusy && !anyBusy())) renderProfiles(settings);
      if (familyMode && wasBusy && !anyBusy() && currentRoute?.name === "review") await reloadReviewV2();
      if (renderSession(settings)) { reconcileChecked = false; await sessionChanged(); return; }
      if (anyBusy() || wasBusy || libraryChanged) {
        await refresh();
        // Processing redraws its strip and the shown tab; Records (records_v2.js) only when its documents changed.
        if (currentRoute?.name === "processing") await pr2Refresh();
        await rc2Refresh();
        lastLibraryVersion = settings.library_version;
      }
      if (wasBusy && !anyBusy() && currentRoute?.name === "home") await reloadToday();
      // Work just finished (it may have recorded a statement), or the first poll: check for statements to reconcile.
      if ((wasBusy && !anyBusy()) || !reconcileChecked) { reconcileChecked = true; await loadReconcilePrompt(); }
      if (typeof pollDocumentV2 === "function") await pollDocumentV2();
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
let pollFailure = null, reconcileChecked = false, lastLibraryVersion = null;
// Start once every deferred script has run: a fast settings response must not reach showRoute (shell.js) before it exists.
document.addEventListener("DOMContentLoaded", () => loadSettings().then(refresh).then(() => showRoute(false)).then(poll).catch(error => notice(error, true)));

// The latest batch of documents being read; Processing shows it under Reading while it runs (processing_v2.js).
let receiptBatch = null;
function showReceiptBatch(batch) { receiptBatch = batch || null; }
function receiptBatchText(batch) {
  return batch ? `Batch ${batch.status}: ${batch.total} documents; ${Object.entries(batch.counts).map(([state, count]) => `${count} ${state}`).join(", ")}. ${batch.unique_runs} distinct images; ${batch.reused} reused/duplicate results; ${batch.skipped} unsupported documents skipped.` : "";
}
// A Settings form's result line under its buttons (docs/ui.md "Settings"): "Saved." or why not. Focus stays put.
function settingsResult(form, message = "", error = false) {
  let line = $(form).querySelector(".save-result");
  if (!line) {
    line = element("p", "", "save-result"); line.setAttribute("aria-live", "polite");
    $(form).querySelector(".button-row").after(line);
  }
  line.classList.toggle("is-error", error);
  line.replaceChildren(...(message ? [icon(error ? "alert" : "check"), message] : []));
}
function saveSettingsForm(form, path, body, message) {
  $(form).addEventListener("submit", async event => {
    event.preventDefault();
    for (const node of $(form).querySelectorAll(".field-error")) node.replaceChildren();
    settingsResult(form);
    try { await api(path, {method:"PUT", body:JSON.stringify(body())}); notice(message); settingsResult(form, "Saved."); await loadSettings(); }
    catch (error) {
      notice(error, true);
      // A validation error goes under the field it names (money_v2.js errorField); a URL the server refused names no field.
      const field = errorField(error) || (/http:\/\/127\.0\.0\.1/.test(error.message) ? "url" : null);
      const target = field && $(form).querySelector(`[data-error-for="${field}"]`);
      if (target) target.replaceChildren(icon("alert"), error.message); else settingsResult(form, error.message, true);
    }
  });
}
saveSettingsForm("vision-form", "/api/vision-settings",
  () => ({base_url:$("vision-url").value.trim(), model:$("vision-model").value.trim(), organize_after_scan:$("auto-organize").checked}),
  "Local model settings saved. Start the model server before parsing; saving does not test the connection.");
// Model computer: this PC's server, or a shared GPU computer over Tailscale (models/gpu_host.py).
function showModelProvider(provider) {
  const family = provider === "family_gpu";
  $("family-gpu-fields").hidden = $("test-model-computer").hidden = !family;
  $("manage-loading-field").hidden = $("manage-loading-note").hidden = family;
  for (const id of ["vision-form", "reasoning-form", "local-models-note"]) $(id).hidden = family;
}
function renderModelComputer(computer) {
  $("model-provider").value = computer.provider;
  $("gpu-host-url").value = computer.gpu_host_url;
  $("gpu-token").value = "";
  $("gpu-token").placeholder = computer.token_set ? "Saved. Paste a new token to replace it." : "";
  $("manage-loading").checked = computer.manage_model_loading;
  $("loading-hint").replaceChildren(...(computer.loading_hint ? [alertBox(computer.loading_hint, {tone: "warning"})] : []));
  showModelProvider(computer.provider);
}
$("model-provider").addEventListener("change", () => showModelProvider($("model-provider").value));
saveSettingsForm("model-computer-form", "/api/model-computer",
  () => ({provider: $("model-provider").value, gpu_host_url: $("gpu-host-url").value.trim(),
          manage_model_loading: $("manage-loading").checked, ...($("gpu-token").value.trim() ? {token: $("gpu-token").value.trim()} : {})}),
  "Model computer saved. Saving does not test the connection.");
$("test-model-computer").addEventListener("click", async () => {
  const button = $("test-model-computer"), target = $("test-model-computer-result");
  button.disabled = true; target.replaceChildren(element("p", "Asking the GPU computer which models it shares…", "muted small"));
  try {
    const result = await api("/api/model-computer-tests", {method: "POST"});
    const problems = [result.vision, result.reasoning].filter(check => !(check.reachable && check.model_listed)).map(check => check.problem);
    target.replaceChildren(problems.length ? alertBox([...new Set(problems)].join(" "), {tone: "warning"})
      : alertBox(`Connected in ${result.reasoning.latency_ms} ms. The GPU computer shares a vision and a reasoning model.`, {tone: "info"}));
  } catch (error) { target.replaceChildren(alertBox(error.message, {tone: "error"})); }
  finally { button.disabled = false; }
});
saveSettingsForm("reasoning-form", "/api/reasoning-settings",
  () => ({base_url:$("reasoning-url").value.trim(), model:$("reasoning-model").value.trim(),
          schema_enforced:$("reasoning-schema").checked}),
  "Reasoning settings saved. Open a read document and select Extract to ledger.");
// The decision model (models/decisions.py). Calibration values come from an eval run and are kept as saved.
saveSettingsForm("decision-form", "/api/decision-settings",
  () => ({...savedDecision, provider: $("decision-provider").value, base_url: $("decision-url").value.trim(), model: $("decision-model").value.trim()}),
  "Decision model saved. Use Test connection to check that it answers.");
// The document reasoning reviewer (documents/reviewer.py). Only the fields shown are sent; sampling keeps its saved values.
function showReviewerKind() {
  const chat = $("reviewer-kind").value === "chat";
  $("reviewer-url-field").hidden = $("reviewer-model-field").hidden = $("test-reviewer").hidden = !chat;
  if (!chat) $("test-reviewer-result").replaceChildren();
}
$("reviewer-kind").addEventListener("change", showReviewerKind);
saveSettingsForm("reviewer-form", "/api/reviewer-settings", () => {
  const provider = $("reviewer-kind").value;
  return {...savedReviewer, provider, ...(provider === "chat" ? {base_url: $("reviewer-url").value.trim(), model: $("reviewer-model").value.trim()} : {})};
}, "Reviewer saved.");
// Settings › Donate: how many checked documents are ready; the work itself is on #/donate (donate.js).
async function loadDonateSettings() {
  const line = $("donate-settings-count");
  if (!configured) { line.textContent = "Choose a library folder first."; return; }
  try {
    const {checks} = await api("/api/donations");
    const ready = checks.filter(check => check.status === "checked").length;
    line.textContent = `${ready} ${ready === 1 ? "document" : "documents"} checked, ready to donate.`;
  } catch (error) { line.textContent = error.message; }
}
$("donate-tab").addEventListener("tabshow", () => loadDonateSettings());
$("share-form").addEventListener("submit", async event => {
  event.preventDefault();
  const passphrase = $("share-passphrase").value;
  if (passphrase !== $("share-passphrase-again").value) { notice("The two passphrases differ.", true); return; }
  busy.capture = true; controls();
  try {
    const {share_id} = await api("/api/shares", {method: "POST", body: JSON.stringify({destination: $("share-destination").value.trim(), passphrase, label: $("share-label").value.trim()})});
    $("share-passphrase").value = $("share-passphrase-again").value = "";
    notice("Creating the encrypted share file…");
    let record;
    do { await new Promise(resolve => setTimeout(resolve, 1000)); record = await api(`/api/shares/${share_id}`); } while (record.status === "running");
    if (record.status === "succeeded") notice(`Share file saved: ${record.result.path}. Send the file, and tell them the passphrase another way.`);
    else notice(`The share file was not created. ${record.error || ""}`, true);
  } catch (error) { notice(error, true); busy.capture = false; controls(); }  // Otherwise the next poll's busy flags bring the button back.
});
$("session-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await api("/api/sessions", {method: "POST", body: JSON.stringify({share_file: $("session-file").value.trim(), passphrase: $("session-passphrase").value})});
    $("session-passphrase").value = "";
    notice("Opening the shared library. Your own library stays closed and unchanged while you look.");
  } catch (error) { notice(error, true); }
});
saveSettingsForm("household-form", "/api/household-settings", () => ({home_currency: $("home-currency").value || null, checkin_weekday: Number($("checkin-weekday").value), auto_identify_items: $("auto-identify").checked,
                                                             filing_status: $("filing-status").value, birth_year: $("birth-year").value ? Number($("birth-year").value) : null,
                                                             fetch_exchange_rates: $("fetch-rates").checked,
                                                             fetch_crypto_prices: $("fetch-prices").checked, rescan_hours: Number($("rescan-hours").value),
                                                             tax_engine_compare: $("tax-compare").checked}),
  "Preferences saved. A changed home currency applies when documents are extracted to the ledger again.");
