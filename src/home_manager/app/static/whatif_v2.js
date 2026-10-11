"use strict";
// What If, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/wealth.md): four tabs over one plan. Plan
// puts the inputs beside the plan tried against now; Compare, Paycheck planner and Follow this plan hold the rest.
// whatif.js keeps every builder both screens use, on inputs with the "wi2-" prefix here. Every amount and date is the
// server's.
const WI2 = "wi2-";
const WI2_TABS = ["plan", "compare", "planner", "follow"];
// tab: the open tab; stub: the pay stub the planner started from (kept in the URL, as on the original page).
const wi2 = {tab: "plan", stub: null};

V2_SCREENS.whatif = {title: "What If", show: route => loadWhatIfV2(route.params)};

wireWhatIf(WI2);
const activateWi2Tab = wireTabs(WI2_TABS.map(tab => `wi2-tab-${tab}`));
for (const tab of WI2_TABS) $(`wi2-tab-${tab}`).addEventListener("tabshow", () => { wi2.tab = tab; wi2Url(); });
wi.hooks[WI2] = {
  showTab: tab => { if (!$(`wi2-tab-${tab}`).hidden) activateWi2Tab(`wi2-tab-${tab}`); },
  tried: (result, error) => renderAgainstNowV2(result, error),
  followChanged: shown => {
    $("wi2-tab-follow").hidden = !shown;
    if (!shown && wi2.tab === "follow") activateWi2Tab("wi2-tab-plan");
  },
  href: plan => `#/whatif?plan=${plan}${wi2.tab !== "plan" ? `&tab=${wi2.tab}` : ""}`,
};
// Each group's summary counts its rows (or says On/Off); the counts change as rows are added and removed.
for (const details of document.querySelectorAll("#wi2-scenario-form .wi2-group[data-list]")) {
  new MutationObserver(wi2Counts).observe($(details.dataset.list), {childList: true});
}
$("wi2-scenario-form").addEventListener("change", wi2Counts);
$("wi2-scenario-form").addEventListener("input", wi2Counts);
$("wi2-scenario-paychecks").addEventListener("paycheckschange", wi2Counts);

// The URL: the plan, the tab when it isn't Plan, and the pay stub the planner started from.
function wi2Url() {
  const next = new URLSearchParams();
  if (scenarioId != null) next.set("plan", String(scenarioId));
  if (wi2.tab !== "plan") next.set("tab", wi2.tab);
  if (wi2.stub) next.set("stub", wi2.stub);
  if (currentRoute?.name === "whatif") currentRoute.params = next;
  history.replaceState(null, "", `#/whatif${[...next].length ? `?${next}` : ""}`);
}

function loadWhatIfV2(params) {
  const tab = params?.get?.("tab"), stub = params?.get?.("stub");
  wi2.stub = /^\d+$/.test(stub || "") ? stub : null;
  // A pay stub opens the planner, as on the original page.
  wi2.tab = WI2_TABS.includes(tab) ? tab : wi2.stub ? "planner" : "plan";
  const before = wi.shown === WI2 ? scenarioId : undefined;
  return pageState($("wi2-state"), async () => {
    await openWhatIf(WI2, params);
    // Another plan: what was tried belongs to the one before.
    if (before !== scenarioId || !$("wi2-against-body").hasChildNodes()) renderAgainstNowV2(null);
    $("wi2-tab-follow").hidden = !wi.follow;
    if (wi2.tab === "follow" && !wi.follow) wi2.tab = "plan";
    activateWi2Tab(`wi2-tab-${wi2.tab}`);
    wi2Counts();
    // Each group opens when it has something in it; the tax fieldsets when any of their fields has a value.
    for (const details of document.querySelectorAll("#wi2-scenario-form .wi2-group")) details.open = wi2Filled(details);
    for (const details of document.querySelectorAll("#wi2-paycheck-form .wi2-tax-group")) {
      details.open = [...details.querySelectorAll("input")].some(input => input.type === "checkbox" ? input.checked : input.value.trim() !== "")
        || details.querySelector("select")?.value === "percent" || details.querySelector("select")?.value === "amount";
    }
  }, {loading: "Loading your plans …", what: "your plans", needsLibrary: !familyMode, content: [$("wi2-body")]});
}
// Whether a plan group holds anything: rows in its list, or its switch on.
function wi2Filled(details) {
  if (details.dataset.switch) return $(details.dataset.switch).checked;
  return details.dataset.list === "wi2-scenario-paychecks" ? scenarioPaychecks.length > 0 : $(details.dataset.list).children.length > 0;
}
// The summaries: a count of rows (not amounts), On/Off, and each paycheck's name with its take-home once tried.
function wi2Counts() {
  for (const details of document.querySelectorAll("#wi2-scenario-form .wi2-group")) {
    const count = details.querySelector(".fc2-count");
    if (details.dataset.switch) count.textContent = $(details.dataset.switch).checked ? "On" : "Off";
    else count.textContent = `(${details.dataset.list === "wi2-scenario-paychecks" ? scenarioPaychecks.length : $(details.dataset.list).children.length})`;
  }
  const line = document.querySelector("#wi2-scenario-form .wi2-group-line"), parts = [];
  scenarioPaychecks.forEach((plan, index) => {
    const run = wi.paychecksRun?.[index];
    if (parts.length) parts.push("; ");
    parts.push(plan.label || "Paycheck");
    if (run) parts.push(" · ", amount(run.net_per_check, {signed: false}), " a check");
  });
  line.replaceChildren(...(parts.length ? [" ", ...parts] : []));
}

// Against now: the plan on screen and Now, at the end of the plan's years, from the last Try it.
function renderAgainstNowV2(result, error = null) {
  const host = $("wi2-against-body");
  if (error) { host.replaceChildren(alertBox(`Couldn't try the plan. ${error.message}`, {tone: "error", detail: error.detail || ""})); return; }
  if (!result) {
    wi.paychecksRun = null;
    host.replaceChildren(emptyState("Try the plan to see it against now."));
    return;
  }
  const now = result.runs[0], plan = result.runs[result.runs.length - 1];
  // The plan's paychecks as worked out: their take-home shows in the Paychecks group.
  wi.p = WI2; wi.paychecksRun = plan.paychecks; renderScenarioPaychecks(); wi2Counts();
  const runs = [["Now", now], ["This plan", plan]], last = run => run.years[run.years.length - 1];
  const group = (title, row) => {
    const box = element("div", "", "wi2-against-group");
    box.append(element("h3", title));
    for (const [label, run] of runs) {
      const line = element("div", "", "wi2-against-row"), value = element("span", "", "wi2-against-value");
      value.append(...[].concat(row(run)));
      line.append(element("span", label, "wi2-against-label"), value);
      box.append(line);
    }
    return box;
  };
  const worth = group(`Net worth, end of ${fc2EndOf(last(plan).year)}`, run => figure(yearFigure(last(run), "end_net_worth"), {size: "sm", signed: false}));
  const below = group("Cash below zero", run => {
    if (!run.first_month_cash_below_zero) { const ok = element("span", "", "wi2-ok"); ok.append(icon("check-circle"), "Never"); return ok; }
    const warn = element("span", "", "wi2-warn"); warn.append(icon("trending-down"), `From ${monthText(run.first_month_cash_below_zero)}`); return warn;
  });
  const taxes = group(`Tax time${now.tax_zen?.year ? `, ${now.tax_zen.year}` : ""}`, run => {
    const zen = run.tax_zen;
    if (!zen?.ready || zen.result_minor == null) return element("span", zen?.note || "Not ready yet", "muted small");
    if (zen.zen) return "Tax Zen";
    const label = zen.result_minor > 0 ? "Refund " : "You'd owe ";
    return [label, figure({display: zen.display.result_minor, trace: zen.trace}, {size: "sm", magnitude: true})];
  });
  const more = element("button", "See the full comparison", "link-button"); more.type = "button";
  more.addEventListener("click", () => { activateWi2Tab("wi2-tab-compare"); $("wi2-tab-compare").focus(); });
  host.replaceChildren(worth, below, taxes, more);
}
