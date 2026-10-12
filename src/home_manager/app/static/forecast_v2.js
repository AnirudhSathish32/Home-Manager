"use strict";
// Forecast, redesigned (docs/ui.md "Pages"; design-system/home-manager/pages/wealth.md): the assumptions in a column
// beside the answer (where cash and net worth end up, and whether cash goes below zero), one chart at a time, then what
// the numbers rest on. The assumptions live in the URL. forecast.js keeps the builders, on this page's "fc2-" inputs.
// Every amount and date is the server's.
const FC2 = "fc2-";
const FC2_CHARTS = ["net_worth", "cash_flow", "balance_sheet"];
const FC2_DEFAULTS = {years: 10, inflation: "2", growth: "0", history: 6, chart: "net_worth"};
// The repeated URL keys, each to its list and the order of its "~"-separated fields (Layout rule 5).
const FC2_LISTS = {spend: ["spending", ["category", "percent"]], income: ["income", ["month", "monthly_amount"]],
                   oneoff: ["oneoff", ["month", "amount", "label"]], edu: ["edu", ["month", "amount", "label"]]};
// load: the newest run, so an older one finishing late draws nothing; result: the last one drawn.
const fc2 = {load: 0, chart: "net_worth", result: null};

V2_SCREENS.forecast = {title: "Forecast", show: route => loadForecastV2(route.params)};

wireForecast();
const fc2Wide = matchMedia("(min-width: 1100px)");
// Wide, the assumptions are a column that is always open; narrower, they fold above the results.
fc2Wide.addEventListener("change", () => { if (fc2Wide.matches) $("fc2-assumptions").open = true; });
$("fc2-assumptions").addEventListener("toggle", () => { if (fc2Wide.matches && !$("fc2-assumptions").open) $("fc2-assumptions").open = true; });
// Each list's summary counts its rows; the count changes as rows are added and removed.
for (const details of document.querySelectorAll("#fc2-forecast-form .fc2-list[data-list]")) {
  new MutationObserver(fc2Counts).observe($(details.dataset.list), {childList: true});
}
$("fc2-retire-plan").addEventListener("change", fc2Counts);
$("fc2-forecast-form").addEventListener("input", fc2Counts);
for (const chip of $("fc2-chart-switch").querySelectorAll("[data-chart]")) {
  chip.addEventListener("click", () => {
    fc2.chart = chip.dataset.chart;
    fc2Url();
    if (fc2.result) forecastChartV2(fc2.result);
  });
}
$("fc2-forecast-form").addEventListener("submit", event => {
  event.preventDefault();
  const form = $("fc2-forecast-form");
  if (!form.checkValidity()) {
    // A folded field can't show its message: open whatever holds the first one, then report it.
    const invalid = form.querySelector(":invalid");
    for (let node = invalid?.parentElement; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
    form.reportValidity();
    return;
  }
  fc2Url();
  fc2Run();
});

// Parsing ----------------------------------------------------------------------------------------------------------
// "a~b~c" into n fields: the last keeps any further "~" (a label may contain one).
function fc2Split(text, n) {
  const parts = String(text).split("~");
  return parts.length < n ? null : [...parts.slice(0, n - 1), parts.slice(n - 1).join("~")];
}
const FC2_DECIMAL = /^-?\d+(\.\d+)?$/, FC2_MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
function fc2Valid(key, value) {
  if (key === "month") return FC2_MONTH.test(value);
  if (["percent", "monthly_amount", "amount"].includes(key)) return FC2_DECIMAL.test(value);
  if (key === "category") return value.trim().length > 0 && value.length <= 80;
  if (key === "label") return value.length <= 80;
  return false;
}
// The URL's assumptions, checked. Anything invalid is dropped and its default used.
function forecastParamsV2(params) {
  const get = key => params?.get?.(key) ?? null, int = (key, min, max, fallback) => {
    const value = Number(get(key));
    return get(key) !== null && Number.isInteger(value) && value >= min && value <= max ? value : fallback;
  };
  const decimal = (key, fallback) => FC2_DECIMAL.test(get(key) || "") ? get(key) : fallback;
  const state = {years: int("years", 1, 100, FC2_DEFAULTS.years), inflation: decimal("inflation", FC2_DEFAULTS.inflation),
                 growth: decimal("growth", FC2_DEFAULTS.growth), history: int("history", 1, 24, FC2_DEFAULTS.history),
                 chart: FC2_CHARTS.includes(get("chart")) ? get("chart") : FC2_DEFAULTS.chart, lists: {}, retire: null};
  for (const [param, [list, keys]] of Object.entries(FC2_LISTS)) {
    state.lists[list] = (params?.getAll?.(param) || []).map(text => fc2Split(text, keys.length))
      .filter(parts => parts && parts.every((value, i) => fc2Valid(keys[i], value)))
      .map(parts => Object.fromEntries(keys.map((key, i) => [key, parts[i]])));
  }
  const retire = fc2Split(get("retire") ?? "", 4);
  if (retire && FC2_MONTH.test(retire[0]) && ["fixed", "shortfall"].includes(retire[1]) && FC2_DECIMAL.test(retire[2]) && FC2_DECIMAL.test(retire[3])) {
    state.retire = {month: retire[0], mode: retire[1], amount: retire[2], tax: retire[3]};
  }
  return state;
}
// The form's assumptions into the URL: only what differs from the defaults.
function fc2Url() {
  const request = forecastRequest(), next = new URLSearchParams();
  if (request.years !== FC2_DEFAULTS.years) next.set("years", String(request.years));
  if (request.inflation_percent !== FC2_DEFAULTS.inflation) next.set("inflation", request.inflation_percent);
  if (request.income_growth_percent !== FC2_DEFAULTS.growth) next.set("growth", request.income_growth_percent);
  if (request.history_months !== FC2_DEFAULTS.history) next.set("history", String(request.history_months));
  for (const item of request.spending_changes) next.append("spend", `${item.category}~${item.percent}`);
  for (const item of request.income_changes) next.append("income", `${item.month}~${item.monthly_amount}`);
  for (const item of request.one_offs) next.append("oneoff", `${item.month}~${item.amount}~${item.label}`);
  for (const item of request.education_withdrawals) next.append("edu", `${item.month}~${item.amount}~${item.label}`);
  const plan = request.retirement;
  if (plan) next.set("retire", `${plan.start_month}~${plan.mode}~${plan.mode === "fixed" ? plan.monthly_amount : plan.cash_floor}~${plan.tax_percent}`);
  if (fc2.chart !== FC2_DEFAULTS.chart) next.set("chart", fc2.chart);
  if (currentRoute?.name === "forecast") currentRoute.params = next;
  history.replaceState(null, "", `#/forecast${[...next].length ? `?${next}` : ""}`);
  return next;
}

// Loading ----------------------------------------------------------------------------------------------------------
function loadForecastV2(params) {
  const state = forecastParamsV2(params);
  fc2.chart = state.chart;
  $(FC2 + "forecast-years").value = state.years;
  $(FC2 + "forecast-inflation").value = state.inflation;
  $(FC2 + "forecast-income-growth").value = state.growth;
  $(FC2 + "forecast-history").value = state.history;
  const lists = forecastLists();
  for (const [key, items] of Object.entries(state.lists)) {
    const [list, fields] = lists[key];
    $(list).replaceChildren();
    for (const item of items) {
      const row = forecastRow(list, fields, {focus: false});
      for (const input of row.querySelectorAll("input")) input.value = item[input.dataset.key] ?? "";
    }
  }
  $(FC2 + "retire-plan").checked = Boolean(state.retire);
  $(FC2 + "retire-month").value = state.retire?.month || "";
  $(FC2 + "retire-mode").value = state.retire?.mode || "shortfall";
  $(FC2 + "retire-amount").value = state.retire?.mode === "fixed" ? state.retire.amount : "";
  $(FC2 + "retire-floor").value = state.retire?.mode === "shortfall" ? state.retire.amount : "0";
  $(FC2 + "retire-tax").value = state.retire?.tax || "0";
  showRetirementFields();
  fc2Counts();
  // Each list opens when it has rows; the column opens on a narrow screen only when the URL sets nothing.
  for (const details of document.querySelectorAll("#fc2-forecast-form .fc2-list[data-list]")) details.open = $(details.dataset.list).children.length > 0;
  $("fc2-retirement").open = Boolean(state.retire);
  $("fc2-assumptions").open = fc2Wide.matches || ![...(params?.keys?.() || [])].length;
  if (!$(FC2 + "asset-as-of").value) $(FC2 + "asset-as-of").value = todayIso();
  return fc2Reload();
}
function fc2Reload() {
  return pageState($("fc2-state"), async () => { await loadAssets(); fc2AssetRows(); await fc2Run(); },
                   {loading: "Loading the forecast …", what: "the forecast", needsLibrary: true, content: [$("fc2-body")]});
}
// The shared asset rows, marked so a narrow screen can fold Kind and As of into the name line.
function fc2AssetRows() {
  for (const row of $(FC2 + "asset-rows").rows) {
    if (row.cells.length < 8) continue;  // The "No assets or loans yet" row.
    const [name, kind, , asOf] = row.cells;
    kind.classList.add("fc2-col-kind"); asOf.classList.add("fc2-col-as-of");
    name.append(element("small", `${kind.textContent} · ${asOf.textContent}`, "muted fc2-inline"));
  }
}
// One run of the forecast. Its own errors show above the tiles and keep the inputs; an older run finishing late is dropped.
async function fc2Run() {
  const load = ++fc2.load;
  let result;
  try {
    result = await api("/api/forecast", {method: "POST", body: JSON.stringify(forecastRequest())});
  } catch (error) {
    if (load !== fc2.load) return;
    $("fc2-alerts").replaceChildren(alertBox(`Couldn't update the forecast. ${error?.message || error}`, {tone: "error", detail: error?.detail || ""}));
    $("fc2-status").textContent = "";
    return;
  }
  if (load !== fc2.load) return;
  renderForecastV2(result);
  $("fc2-status").textContent = "Forecast updated";
}
// The column's summary line and each list's count (counts of rows, not amounts).
function fc2Counts() {
  for (const details of document.querySelectorAll("#fc2-forecast-form .fc2-list[data-list]")) {
    details.querySelector(".fc2-count").textContent = `(${$(details.dataset.list).children.length})`;
  }
  const on = $(FC2 + "retire-plan").checked;
  $("fc2-retire-state").textContent = on ? "On" : "Off";
  const changes = [...document.querySelectorAll("#fc2-forecast-form .forecast-list")].reduce((n, list) => n + list.children.length, 0) + (on ? 1 : 0);
  const years = $(FC2 + "forecast-years").value, inflation = $(FC2 + "forecast-inflation").value.trim();
  $("fc2-assumptions-line").textContent = `: ${years} ${years === "1" ? "year" : "years"} · ${inflation}% inflation · ${changes} ${changes === 1 ? "change" : "changes"}`;
}

// Results ----------------------------------------------------------------------------------------------------------
function renderForecastV2(result) {
  fc2.result = result;
  $("fc2-alerts").replaceChildren();
  forecastTilesV2(result);
  forecastChartV2(result);
  $("fc2-notes").replaceChildren(...result.notes.map(note => element("li", note)));
  $("fc2-about").hidden = !result.notes.length;
  $("fc2-start").replaceChildren(...forecastStart(result, categoryLabel));
  forecastCategoryOptions(result);
  fc2Counts();
}
// "2036", or the last month of a year that doesn't start in January ("2036-10 to 2037-09" → "September 2037").
function fc2EndOf(year) { return /^\d{4}$/.test(year) ? year : monthText(year.slice(-7)); }
function fc2Tile(label, main, sub = [], className = "") {
  const tile = element("div", "", `figure-tile ${className}`.trim());
  tile.append(element("p", label, "figure-label"), main);
  for (const line of sub) { const p = element("p", "", "figure-sub"); p.append(...[].concat(line)); tile.append(p); }
  return tile;
}
function forecastTilesV2(result) {
  const last = result.years[result.years.length - 1];
  if (!last) { $("fc2-tiles").replaceChildren(); return; }
  const end = fc2EndOf(last.year);
  const cash = fc2Tile(`Cash, end of ${end}`, figure({display: last.display.end_cash, trace: last.traces?.end_cash}, {signed: false}));
  const today = element("span"); today.append(amount(last.display.end_net_worth_today, {signed: false}), " in today's dollars");
  const worth = fc2Tile(`Net worth, end of ${end}`, figure({display: last.display.end_net_worth, trace: last.traces?.end_net_worth}, {signed: false}), [today]);
  let below;
  if (result.first_month_cash_below_zero) {
    const text = element("p", "", "fc2-tile-text"); text.append(icon("trending-down"), `From ${monthText(result.first_month_cash_below_zero)}`);
    below = fc2Tile("Cash below zero", text, ["Cash goes below zero; see the Cash chart."], "attention");
  } else {
    const text = element("p", "", "fc2-tile-text fc2-ok"); text.append(icon("check-circle"), "Stays above zero");
    below = fc2Tile("Cash below zero", text);
  }
  $("fc2-tiles").replaceChildren(cash, worth, below);
  fitFigures($("fc2-tiles"));
}
// The chosen chart, its summary, and its numbers by year. Traced columns are figures that open their breakdown.
function forecastChartV2(result) {
  for (const chip of $("fc2-chart-switch").querySelectorAll("[data-chart]")) chip.setAttribute("aria-pressed", String(chip.dataset.chart === fc2.chart));
  const svg = forecastSvg(result.charts[fc2.chart]);
  $("fc2-chart").replaceChildren(svg);
  $("fc2-chart-desc").textContent = svg.querySelector("desc")?.textContent || "";
  const [title, columns] = forecastColumns(result)[fc2.chart];
  const money = (year, key) => year.traces?.[key]
    ? figure({display: year.display[key], trace: year.traces[key]}, {size: "sm", signed: false})
    : amount(year.display[key], {signed: false});
  const table = forecastTable(result, columns, money);
  table.querySelector("table").setAttribute("aria-label", `${title} by year`);
  $("fc2-chart-table").replaceChildren(table);
}
