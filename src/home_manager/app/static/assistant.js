"use strict";
// The assistant panel (docs/ui-design-plan.md §3.11, Phase F). Answers are prose in the secondary style, never large
// figures; each cited tool call becomes an evidence chip that opens the matching page; "How I got this" lists every call.
const TOOL_LABELS = {get_transactions: "transactions", find_purchase: "transactions", get_spending: "spending", spending_series: "monthly spending",
  get_spending_by_category: "spending by category", compare_periods: "period comparison", compare_categories: "category comparison",
  calculate_cashflow: "cash flow", get_accounts: "accounts", get_account_balance: "account balance", get_statement: "statement",
  get_recurring_obligations: "recurring payments", get_upcoming_bills: "bills", find_receipt: "receipts", get_unmatched_receipts: "unmatched receipts",
  match_receipt_to_transaction: "receipt matching", get_refunds: "refunds", review_queue: "review queue", get_inventory: "inventory",
  get_budgets: "budgets", get_categories: "categories", get_item_spending: "item spending", item_price_history: "price history",
  get_price_changes: "price changes", compare_merchant_prices: "store prices", get_consumption_cost: "consumption", get_waste: "waste",
  forecast_consumables_spend: "consumables forecast", detect_spending_anomalies: "unusual spending"};
let assistantBusy = false;

function toolPeriod(args) {
  if (args?.start && args?.end) return `${dateText(args.start)} – ${dateText(args.end)}`;
  if (args?.month) return args.month;
  if (args?.first && args?.second) return `${dateText(args.second.start)} – ${dateText(args.second.end)}`;
  return "";
}
function toolHref(tool, args = {}) {
  // Where the evidence lives in the app, with the same scope where the page supports it.
  const month = (args.month || args.start || args.second?.start || "").slice(0, 7);
  if (["get_transactions", "find_purchase"].includes(tool)) {
    const query = new URLSearchParams();
    for (const key of ["start", "end"]) if (args[key]) query.set(key, args[key]);
    if (args.query) query.set("q", args.query);
    if (args.category) query.set("category", args.category);
    if (!args.start && !args.end) query.set("period", "all");
    return `#/transactions?${query}`;
  }
  if (["get_upcoming_bills", "get_recurring_obligations"].includes(tool)) return "#/bills";
  if (["get_accounts", "get_account_balance", "get_statement"].includes(tool)) return "#/accounts";
  if (["find_receipt", "get_unmatched_receipts", "review_queue", "match_receipt_to_transaction"].includes(tool)) return "#/review";
  if (["get_inventory", "get_item_spending", "item_price_history", "get_price_changes", "compare_merchant_prices", "get_consumption_cost", "get_waste",
       "forecast_consumables_spend"].includes(tool)) return args.query ? `#/inventory?${new URLSearchParams({q: args.query})}` : "#/inventory";
  return month ? `#/spending?${new URLSearchParams({month})}` : "#/spending";
}
function pageContext() {
  // The page's name plus its filters, as plain words; sent as labelled context, never as an instruction.
  if (!currentRoute) return null;
  const title = ROUTES[currentRoute.name]?.title || currentRoute.name;
  const params = [...currentRoute.params].filter(([key]) => !["token", "section"].includes(key)).map(([key, value]) => `${key} ${value}`);
  if (currentRoute.name === "home" && $("home-month").value) params.push(`month ${$("home-month").value}`);
  if (currentRoute.name === "spending" && $("spend-month").value && !params.some(item => item.startsWith("month"))) params.push(`month ${$("spend-month").value}`);
  return [title, ...params].join(" · ").slice(0, 300);
}
function renderAnswer(run) {
  const box = element("article", "", "assistant-turn");
  box.append(element("p", run.question, "assistant-question"));
  if (["queued", "running"].includes(run.status)) { box.append(element("p", "Looking through your records with the local model…", "muted small")); return box; }
  if (run.status !== "succeeded") { box.append(alertBox(run.error || `The question ${statusLabel(run.status).toLowerCase()}.`, {tone: "error"})); return box; }
  const result = run.result;
  box.append(element("p", result.answer, "assistant-answer"));
  if (result.unverified_figures.length) box.append(alertBox(`Check these figures: ${result.unverified_figures.join(", ")} ${result.unverified_figures.length === 1 ? "isn't" : "aren't"} in the records the answer cites.`, {tone: "warning"}));
  if (result.missing_evidence.length) {
    const missing = element("ul", "", "assistant-missing");
    for (const text of result.missing_evidence) missing.append(element("li", text));
    box.append(element("p", "Not in your records:", "muted small"), missing);
  }
  const chips = element("div", "", "evidence-chips");
  for (const number of result.cited_calls) {
    const call = result.tool_calls[number - 1];
    const period = toolPeriod(call.arguments);
    const chip = homeLink(`From ${TOOL_LABELS[call.tool] || call.tool}${period ? ` · ${period}` : ""}`, toolHref(call.tool, call.arguments), "evidence-chip");
    chips.append(chip);
  }
  if (chips.children.length) box.append(chips);
  const how = element("details", "", "assistant-how");
  how.append(element("summary", `How I got this (${result.tool_calls.length} lookup${result.tool_calls.length === 1 ? "" : "s"}${result.route === "items" ? ", household item tools" : ""})`));
  const list = element("ol", "", "assistant-calls");
  for (const call of result.tool_calls) {
    const li = element("li", "");
    li.append(element("code", call.tool), element("small", typeof call.arguments === "string" ? call.arguments : JSON.stringify(call.arguments), "mono block"));
    if (call.error) li.append(element("small", call.error, "item-warning block"));
    list.append(li);
  }
  how.append(list);
  box.append(how);
  return box;
}
async function loadAssistantHistory() {
  if (!configured) return;
  const runs = await api("/api/assistant-runs?limit=15");
  $("assistant-history").replaceChildren(...runs.map(run => {
    const li = document.createElement("li"), open = element("button", run.question, "link-button"); open.type = "button";
    open.addEventListener("click", async () => $("assistant-log").append(renderAnswer({...run, ...(await api(`/api/assistant-runs/${run.id}`))})));
    li.append(open, element("small", `${new Date(run.created_at).toLocaleString()} · ${statusLabel(run.status)}`, "muted"));
    return li;
  }));
  if (!runs.length) $("assistant-history").append(element("li", "No questions yet.", "muted"));
}
function toggleAssistant(open = $("assistant-panel").hidden) {
  $("assistant-panel").hidden = !open;
  $("nav-ask").setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("assistant-open", open);
  if (open) {
    if (!configured) $("assistant-log").replaceChildren(emptyState("Set up your library first.", homeLink("Open Settings", "#/settings")));
    else if (!modelsConfigured.reasoning && !$("assistant-log").children.length) $("assistant-log").append(alertBox("The assistant needs a local reasoning model.", {action: homeLink("Set one up", "#/settings")}));
    loadAssistantHistory().catch(() => {});
    $("assistant-question").focus();
  } else $("nav-ask").focus();
}
$("close-assistant").append(icon("x"));
$("close-assistant").addEventListener("click", () => toggleAssistant(false));
$("nav-ask").addEventListener("click", () => toggleAssistant());
document.addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "j") { event.preventDefault(); toggleAssistant(); }
  else if (event.key === "Escape" && !$("assistant-panel").hidden && $("assistant-panel").contains(document.activeElement)) { event.preventDefault(); toggleAssistant(false); }
});
$("assistant-question").addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); $("assistant-form").requestSubmit(); }
});
$("assistant-form").addEventListener("submit", async event => {
  event.preventDefault();
  const question = $("assistant-question").value.trim();
  if (!question || assistantBusy) return;
  assistantBusy = true; $("assistant-ask").disabled = true;
  const turn = renderAnswer({question, status: "running"});
  $("assistant-log").append(turn); turn.scrollIntoView({block: "end"});
  try {
    const {run_id} = await api("/api/assistant-runs", {method: "POST", body: JSON.stringify({question, context: pageContext()})});
    $("assistant-question").value = "";
    let run;
    do { await new Promise(resolve => setTimeout(resolve, 1000)); run = await api(`/api/assistant-runs/${run_id}`); } while (["queued", "running"].includes(run.status));
    const done = renderAnswer(run); turn.replaceWith(done); done.scrollIntoView({block: "end"});
    loadAssistantHistory().catch(() => {});
  } catch (error) { turn.replaceWith(renderAnswer({question, status: "failed", error: error.message})); }
  finally { assistantBusy = false; $("assistant-ask").disabled = false; }
});
