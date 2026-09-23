"use strict";
let receipt = null, receiptImageURL = null;

function receiptControls() {
  $("parse-receipt").disabled = !receipt || busy || Boolean(receipt?.doc.deleted_at);
  $("reparse-receipt").disabled = !receipt || busy || Boolean(receipt?.doc.deleted_at);
  $("receipt-rotation").disabled = busy;
}
function closeReceipt() {
  receipt = null;
  if (receiptImageURL) { URL.revokeObjectURL(receiptImageURL); receiptImageURL = null; }
  $("receipt-image").removeAttribute("src");
  $("receipt-dialog").close();
}
async function imageForReceipt(path, expected) {
  const response = await fetch(path, {headers:{"Authorization":`Bearer ${token}`}});
  if (!response.ok) { const data = await response.json(); throw new Error(data.detail || "Could not retrieve image."); }
  const blob = await response.blob();
  if (receipt !== expected) return;
  if (receiptImageURL) URL.revokeObjectURL(receiptImageURL);
  receiptImageURL = URL.createObjectURL(blob); $("receipt-image").src = receiptImageURL;
}
async function openReceipt(doc, digest = doc.current_hash) {
  closeReceipt();
  const state = {doc, digest, runId:"", pending:false, result:null}; receipt = state;
  $("receipt-title").textContent = "Inspect receipt";
  $("receipt-path").textContent = doc.relative_path;
  $("receipt-version").textContent = `Source version: ${digest}${digest === doc.current_hash ? " (latest preserved)" : " (historical)"}. Source status: ${doc.source_status}.`;
  $("receipt-status").textContent = "Loading preserved receipt. Select Parse receipt to extract its contents.";
  $("receipt-rotation").value = "0";
  for (const id of ["receipt-fields","receipt-components","receipt-codes","receipt-regions","receipt-issues","receipt-overlay"]) $(id).replaceChildren();
  $("receipt-text").value = ""; $("receipt-calculation").textContent = ""; $("receipt-provenance").textContent = "";
  $("receipt-runs").replaceChildren(new Option("Not parsed yet", ""));
  $("receipt-dialog").showModal(); receiptControls();
  await imageForReceipt(`/api/documents/${doc.id}/image?blob_hash=${digest}`, state);
  await receiptHistory(state);
  if (receipt !== state) return;
  if (state.runId) await displayReceiptRun(state.runId, state);
  else $("receipt-status").textContent = "Not parsed yet. Parse receipt reads the preserved image locally; the original remains unchanged.";
}
async function receiptHistory(state) {
  const history = await api(`/api/documents/${state.doc.id}/receipt-runs?blob_hash=${state.digest}`);
  if (receipt !== state) return;
  const selector = $("receipt-runs"); selector.replaceChildren();
  if (!history.length) { selector.add(new Option("Not parsed yet", "")); return; }
  for (const run of history) {
    const rotation = JSON.parse(run.options_json).clockwise_rotation;
    selector.add(new Option(`${new Date(run.created_at).toLocaleString()} · ${run.status} · ${rotation}°`, run.id));
  }
  if (!state.runId) state.runId = history[0].id;
  selector.value = state.runId;
}
function highlightEvidence(ids) {
  if (!receipt?.result) return;
  if (receipt.result.transcription_method === "vision_model" && !ids.some(id => id.startsWith("code-"))) {
    const line = receipt.result.lines.find(line => ids.includes(line.id));
    if (line) {
      const field = $("receipt-text"), start = field.value.indexOf(line.text);
      field.focus(); field.setSelectionRange(start, start + line.text.length);
    }
    return;
  }
  const wanted = new Set(ids);
  for (const line of receipt.result.lines) if (wanted.has(line.id)) for (const id of line.block_ids) wanted.add(id);
  for (const element of $("receipt-overlay").children) element.classList.toggle("selected", wanted.has(element.dataset.evidenceId));
}
function candidateCard(candidate) {
  const card = document.createElement("div"); card.className = "receipt-field";
  const title = document.createElement("strong"); title.textContent = `${candidate.name.replaceAll("_"," ")}: ${candidate.value ?? "Not resolved"} · ${candidate.status}`;
  card.appendChild(title);
  if (candidate.raw_text) { const text = document.createElement("pre"); text.textContent = candidate.raw_text; card.appendChild(text); }
  const note = document.createElement("small"); note.textContent = candidate.note; card.appendChild(note);
  if (candidate.evidence_ids.length) {
    const button = document.createElement("button"); button.type = "button";
    button.textContent = receipt?.result?.transcription_method === "vision_model" ? "Find in transcription" : "Highlight source";
    button.addEventListener("click", () => highlightEvidence(candidate.evidence_ids)); card.appendChild(button);
  }
  return card;
}
function renderReceipt(result) {
  $("receipt-title").textContent = result.title || "Inspect receipt";
  $("receipt-fields").replaceChildren(...[result.fields.date,result.fields.currency,result.fields.total].map(candidateCard));
  $("receipt-components").replaceChildren(...result.fields.components.map(candidateCard));
  if (!result.fields.components.length) $("receipt-components").textContent = "No unambiguous subtotal, tax, tip or fee labels were resolved. All other text is retained below.";
  $("receipt-calculation").textContent = `${result.fields.calculation_status}${result.fields.calculated_total !== null ? ` · detected components sum: ${result.fields.calculated_total} · total minus sum: ${result.fields.difference}` : ""}. ${result.fields.calculation_note}`;
  $("receipt-text").value = result.extracted_text;
  $("receipt-issues").replaceChildren();
  for (const issue of result.issues) { const li = document.createElement("li"); li.textContent = issue.message; $("receipt-issues").appendChild(li); }
  $("receipt-codes").replaceChildren();
  if (!result.codes.length) $("receipt-codes").textContent = "No code decoded. A QR code may be absent or unreadable; check the image.";
  for (const code of result.codes) {
    const card = document.createElement("div"); card.className = "receipt-field";
    const title = document.createElement("strong"); title.textContent = `${code.format} · ${code.valid ? "decoded" : "decode error"}`;
    const text = document.createElement("pre"); text.textContent = code.text || "No text representation";
    const bytes = document.createElement("details"), summary = document.createElement("summary"), value = document.createElement("pre");
    summary.textContent = "Exact payload bytes (base64)"; value.textContent = code.bytes_base64; bytes.append(summary,value);
    const highlight = document.createElement("button"); highlight.type = "button"; highlight.textContent = "Highlight code";
    highlight.addEventListener("click", () => highlightEvidence([code.id]));
    card.append(title,text,bytes,highlight); $("receipt-codes").appendChild(card);
  }
  $("receipt-overlay").replaceChildren(); $("receipt-overlay").setAttribute("viewBox", `0 0 ${result.width} ${result.height}`);
  for (const block of [...result.blocks,...result.codes]) {
    const polygon = document.createElementNS("http://www.w3.org/2000/svg","polygon");
    polygon.setAttribute("points",block.polygon.map(pair => pair.join(",")).join(" ")); polygon.dataset.evidenceId = block.id;
    const title = document.createElementNS("http://www.w3.org/2000/svg","title"); title.textContent = block.text; polygon.appendChild(title);
    polygon.addEventListener("click", () => highlightEvidence([block.id])); $("receipt-overlay").appendChild(polygon);
  }
  $("receipt-regions").replaceChildren();
  for (const block of result.blocks) {
    const button = document.createElement("button"); button.type = "button";
    button.textContent = `${block.id} · engine score ${block.confidence.toFixed(3)} · ${block.text}`;
    button.addEventListener("click", () => highlightEvidence([block.id])); $("receipt-regions").appendChild(button);
  }
  $("receipt-provenance").textContent = JSON.stringify({schema_version:result.schema_version,parser_version:result.parser_version,
    input_hash:result.input_hash,transcription_method:result.transcription_method,engine:result.engine,model_hashes:result.model_hashes,coverage:result.coverage,
    original_size:[result.original_width,result.original_height],preview_size:[result.width,result.height],
    exif_orientation:result.exif_orientation,clockwise_rotation:result.clockwise_rotation,coordinate_space:result.coordinate_space},null,2);
}
async function displayReceiptRun(runId, state) {
  const run = await api(`/api/receipt-runs/${runId}`);
  if (receipt !== state || state.runId !== runId) return;
  state.pending = ["queued","running"].includes(run.status);
  $("receipt-status").textContent = `${run.status}${run.error ? ": " + run.error : ""}${run.result ? " · Unreviewed extraction. Compare the entire receipt before relying on any field." : ""}${!run.result && state.result ? " · Previous completed extraction remains displayed below." : ""}`;
  if (run.result) {
    state.result = run.result; renderReceipt(run.result);
    await imageForReceipt(`/api/receipt-runs/${runId}/preview`,state);
  }
  await receiptHistory(state);
}
async function startReceipt(force) {
  if (!receipt) return;
  const state = receipt;
  try {
    busy = true; controls();
    const data = await api(`/api/documents/${state.doc.id}/receipt-runs`,{method:"POST",body:JSON.stringify({blob_hash:state.digest,clockwise_rotation:Number($("receipt-rotation").value),force})});
    if (receipt !== state) return;
    state.runId = data.run_id; state.pending = true;
    $("receipt-status").textContent = "Parsing receipt locally with the configured reader. Image reading and QR/barcode decoding may take several minutes.";
    await displayReceiptRun(state.runId,state);
  } catch (error) { $("receipt-status").textContent = error.message; busy = false; controls(); }
}
async function pollReceipt() {
  const state = receipt;
  if (state?.pending && state.runId) await displayReceiptRun(state.runId,state);
}
$("parse-receipt").addEventListener("click", () => startReceipt(false));
$("reparse-receipt").addEventListener("click", () => startReceipt(true));
$("close-receipt").addEventListener("click",closeReceipt);
$("receipt-dialog").addEventListener("cancel",closeReceipt);
$("receipt-runs").addEventListener("change", () => {
  if (!receipt || !$("receipt-runs").value) return;
  receipt.runId = $("receipt-runs").value;
  displayReceiptRun(receipt.runId,receipt).catch(error => { $("receipt-status").textContent = error.message; });
});
$("copy-receipt-text").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("receipt-text").value); $("copy-receipt-text").textContent = "Copied"; }
  catch { $("receipt-text").select(); $("receipt-status").textContent = "Text selected. Press Ctrl+C to copy."; }
});
