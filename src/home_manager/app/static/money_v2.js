"use strict";
// Dialogs the redesigned Money screens share (design-system/home-manager/pages/money.md): Add a payment by hand, and
// Import a bank or card export already in the library. Transactions v2 (transactions_v2.js) and Accounts v2
// (accounts_v2.js) open them. Errors show beside the field they name, never as a toast.
const money2 = {onSaved: null, onImported: null, opener: null, accounts: []};
const MONEY2_FIELDS = {account_id: "account", date: "date", description: "description", amount: "amount", direction: "direction", category: "category",
                       // Investments v2's Add an account (investments_v2.js).
                       name: "name", kind: "kind", institution: "institution", currency: "currency", value: "value", as_of: "as-of", annual_rate_percent: "rate",
                       // Inventory v2's Return policy (inventory_v2.js).
                       merchant: "merchant", days: "days", note: "note",
                       // Processing v2's Watch a folder (processing_v2.js).
                       path: "path", label: "label"};

// A form's error under the field the server named (FastAPI's loc), or at the top of the form.
function fieldError(form, field, message) {
  const target = (field && form.querySelector(`[data-error-for="${field}"]`)) || form.querySelector("[data-error-for='form']");
  target.replaceChildren(icon("alert"), message);
  const control = field && $(`${form.id.replace(/-form$/, "")}-${field}`);
  (control?.matches?.("input, select") ? control : form.querySelector("input, select"))?.focus();
}
function clearFieldErrors(form) { for (const node of form.querySelectorAll(".field-error")) node.replaceChildren(); }
// The field an ApiError is about: a validation error's loc, by its last part.
function errorField(error) {
  try {
    const detail = JSON.parse(error.detail || "null");
    if (Array.isArray(detail) && detail[0]?.loc) return MONEY2_FIELDS[detail[0].loc.at(-1)] || null;
  } catch { /* Not a validation error: shown at the top of the form. */ }
  return null;
}
function money2Close(dialog) {
  dialog.close();
  money2.opener?.focus?.();
}

// Add a payment ----------------------------------------------------------------------------------------------------
async function addTransactionDialog({onSaved = null} = {}) {
  money2.onSaved = onSaved; money2.opener = document.activeElement;
  const [{accounts}] = await Promise.all([tool("get_accounts"), loadCategoryOptions().catch(() => [])]);
  money2.accounts = accounts;
  const form = $("money2-add-form");
  form.reset(); clearFieldErrors(form);
  $("money2-add-account").replaceChildren(...accounts.map(account => new Option(account.display_name, account.id)));
  $("money2-add-date").value = todayIso(); $("money2-add-date").max = todayIso();
  money2Currency();
  $("money2-add-account").disabled = !accounts.length;
  $("money2-add-save").disabled = !accounts.length;
  if (!accounts.length) fieldError(form, "account", "Add an account first: import a bank or card export, or record a statement.");
  $("money2-add").showModal();
  $("money2-add-account").focus();
}
function money2Currency() {
  const account = money2.accounts.find(row => String(row.id) === $("money2-add-account").value);
  $("money2-add-currency").textContent = account?.currency || "";
}
$("money2-add-account").addEventListener("change", money2Currency);
$("money2-add-cancel").addEventListener("click", () => money2Close($("money2-add")));
$("money2-add").addEventListener("close", () => { if (document.activeElement === document.body) money2.opener?.focus?.(); });
$("money2-add-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = $("money2-add-form"), description = $("money2-add-description").value.trim();
  clearFieldErrors(form);
  const body = {account_id: Number($("money2-add-account").value), date: $("money2-add-date").value, description,
                amount: $("money2-add-amount").value.trim(), direction: form.querySelector('input[name="money2-add-direction"]:checked')?.value || "out"};
  if ($("money2-add-category").value.trim()) body.category = $("money2-add-category").value.trim();
  $("money2-add-save").disabled = true;
  try {
    const result = await api("/api/finance/transactions", {method: "POST", body: JSON.stringify(body)});
    money2Close($("money2-add"));
    notice(`Added ${description}.`);
    refreshReviewCount();
    if (money2.onSaved) await money2.onSaved(result.record);
  } catch (error) {
    fieldError(form, errorField(error), error.message || String(error));
  } finally { $("money2-add-save").disabled = false; }
});

// Import a bank or card export -------------------------------------------------------------------------------------
async function importPicker({onImported = null} = {}) {
  money2.onImported = onImported; money2.opener = document.activeElement;
  const list = $("money2-import-list");
  list.replaceChildren(element("li", "Looking for exports …", "muted small"));
  $("money2-import").showModal();
  $("money2-import-close").focus();
  try {
    // The server lists ready CSV and XLSX files and PDFs with a transactions table, filtered before it cuts the list.
    const {items: exports, indexing} = await api("/api/finance/import-candidates");
    const checking = indexing ? element("li", "Still checking older PDFs …", "muted small") : null;
    if (!exports.length) {
      const inbox = element("button", "Open Inbox", "secondary"); inbox.type = "button";
      inbox.addEventListener("click", () => { $("money2-import").close(); showFolder("Inbox"); });
      list.replaceChildren(emptyState("No bank or card exports waiting. Put a PDF, CSV or XLSX statement or export in the Inbox folder.", inbox), ...(checking ? [checking] : []));
      return;
    }
    list.replaceChildren(...exports.map(doc => {
      const parts = doc.relative_path.split("/"), name = parts.pop();
      const li = element("li", "", "dated-row money2-import-row"), when = element("span", "", "dated-when"), text = element("div");
      if (doc.first_seen) when.append(dateDisplay(doc.first_seen.slice(0, 10)));
      const where = element("small", "", "muted");
      where.append(element("span", doc.import_kind.toUpperCase(), "status-badge"), ` ${parts.join("/") || "Library"}`);
      text.append(element("strong", name), where);
      const choose = element("button", "Import", "secondary"); choose.type = "button";
      choose.setAttribute("aria-label", `Import ${name}`);
      choose.addEventListener("click", () => {
        $("money2-import").close();
        openImport(doc, {onDone: money2.onImported}).catch(error => notice(error, true));
      });
      li.append(when, text, choose);
      return li;
    }), ...(checking ? [checking] : []));
    list.querySelector("button")?.focus();
  } catch (error) {
    list.replaceChildren(alertBox(`Couldn't list the exports. ${error.message}`, {tone: "error"}));
  }
}
$("money2-import-close").addEventListener("click", () => money2Close($("money2-import")));
