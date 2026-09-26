"""Deterministic SVG line charts for the forecast. Same data in, byte-identical SVG out.

Follows the app's chart rules: one y-axis, 2px lines, hairline solid gridlines, a legend for
two or more series plus direct end labels (with leader lines when they would collide), text in
text colors never series colors, and a hover target per point whose tooltip lists every series.
Every value is also in the forecast's table view. All text is XML-escaped.
"""

from decimal import Decimal
from xml.sax.saxutils import escape

from .money import EXPONENTS

# Validated categorical order (light surface #FFFFFF): blue, orange, aqua. Aqua sits below 3:1
# contrast, which the always-visible end labels and the table view relieve.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")
GRID, BASELINE, TEXT, MUTED, SURFACE = "#E1E4E8", "#C9CED6", "#1A1F26", "#4D5663", "#FFFFFF"
WIDTH, HEIGHT = 720, 320
LEFT, RIGHT, TOP, BOTTOM = 64, 132, 40, 36
LABEL_GAP = 16


def major(minor, currency):
    return Decimal(minor).scaleb(-EXPONENTS[currency])


def compact(value):
    """1,284 · 12.9K · 4.2M · -350K, for ticks and labels."""
    sign, value = ("-" if value < 0 else ""), abs(value)
    for size, suffix in ((Decimal(10) ** 9, "B"), (Decimal(10) ** 6, "M"), (Decimal(1000), "K")):
        if value >= size and value >= 10000:  # Four-digit amounts read better in full.
            scaled = value / size
            text = f"{scaled:.1f}".rstrip("0").rstrip(".") if scaled < 100 else f"{scaled:.0f}"
            return f"{sign}{text}{suffix}"
    return f"{sign}{value:,.0f}"


def full(value, currency):
    return f"{value:,.{EXPONENTS[currency]}f} {currency}"


def nice_ticks(low, high, count=5):
    """Round tick values (1, 2, 2.5 or 5 x 10^n) covering low..high, always including zero."""
    low, high = min(low, Decimal(0)), max(high, Decimal(0))
    if low == high:
        high = low + 1
    raw = (high - low) / count
    power = Decimal(10) ** (raw.adjusted())
    step = next(power * factor for factor in (Decimal(1), Decimal(2), Decimal("2.5"), Decimal(5), Decimal(10)) if power * factor >= raw)
    start = (low / step).to_integral_value(rounding="ROUND_FLOOR") * step
    ticks, value = [], start
    while value < high + step:
        ticks.append(value)
        if value >= high:
            break
        value += step
    return ticks


def line_chart(title, subtitle, labels, series, currency):
    """labels: x labels (years); series: [{"name", "short" (end label), "values": [minor units]}], at most three."""
    if not series or len(series) > len(SERIES) or any(len(item["values"]) != len(labels) for item in series) or not labels:
        raise ValueError("A chart needs one to three series with one value per label.")
    values = [[major(value, currency) for value in item["values"]] for item in series]
    ticks = nice_ticks(min(min(row) for row in values), max(max(row) for row in values))
    bottom, top = ticks[0], ticks[-1]
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def x(index):
        return LEFT + (plot_w * index / (len(labels) - 1) if len(labels) > 1 else plot_w / 2)

    def y(value):
        return TOP + plot_h - float((value - bottom) / (top - bottom)) * plot_h

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="t d" class="forecast-chart" '
           f'font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">',
           f'<title id="t">{escape(title)}</title><desc id="d">{escape(subtitle)}. Values by year are in the table below the chart.</desc>',
           f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{SURFACE}"/>']
    # Legend (always, for two or more series): a short line key beside plain text.
    if len(series) > 1:
        position = LEFT
        for index, item in enumerate(series):
            out.append(f'<line x1="{position}" y1="14" x2="{position + 16}" y2="14" stroke="{SERIES[index]}" stroke-width="2" stroke-linecap="round"/>'
                       f'<text x="{position + 22}" y="18" fill="{TEXT}">{escape(item["name"])}</text>')
            position += 30 + 7 * len(item["name"])
    for tick in ticks:
        out.append(f'<line x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y(tick):.1f}" y2="{y(tick):.1f}" stroke="{BASELINE if tick == 0 else GRID}" stroke-width="1"/>'
                   f'<text x="{LEFT - 8}" y="{y(tick) + 4:.1f}" text-anchor="end" fill="{MUTED}">{compact(tick)}</text>')
    step = max(1, -(-len(labels) // 8))
    for index in range(0, len(labels), step):
        out.append(f'<text x="{x(index):.1f}" y="{HEIGHT - 12}" text-anchor="middle" fill="{MUTED}">{escape(labels[index])}</text>')
    for index, row in enumerate(values):
        points = " ".join(f"{x(i):.1f},{y(value):.1f}" for i, value in enumerate(row))
        out.append(f'<polyline points="{points}" fill="none" stroke="{SERIES[index]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    # End markers with a surface ring, then end labels; collisions get leader lines, never stacking on the mark.
    ends = sorted(((y(row[-1]), index, row[-1]) for index, row in enumerate(values)), key=lambda item: item[0])
    placed = []
    for mark_y, index, value in ends:
        label_y = max(mark_y, placed[-1] + LABEL_GAP) if placed else mark_y
        placed.append(label_y)
        end_x = x(len(labels) - 1)
        out.append(f'<circle cx="{end_x:.1f}" cy="{mark_y:.1f}" r="4" fill="{SERIES[index]}" stroke="{SURFACE}" stroke-width="2"/>')
        if abs(label_y - mark_y) > 0.5:
            out.append(f'<line x1="{end_x + 6:.1f}" y1="{mark_y:.1f}" x2="{end_x + 14:.1f}" y2="{label_y:.1f}" stroke="{MUTED}" stroke-width="1"/>')
        out.append(f'<text x="{end_x + 16:.1f}" y="{label_y + 4:.1f}" fill="{TEXT}">{compact(value)} {escape(series[index].get("short", series[index]["name"]))}</text>')
    # Hover layer: one full-height target per point; its tooltip lists every series at that point.
    band = plot_w / max(len(labels) - 1, 1)
    for i, label in enumerate(labels):
        tip = "\n".join([label] + [f"{item['name']}: {full(values[n][i], currency)}" for n, item in enumerate(series)])
        out.append(f'<rect x="{x(i) - band / 2:.1f}" y="{TOP}" width="{band:.1f}" height="{plot_h}" fill="transparent" class="hover-target">'
                   f'<title>{escape(tip)}</title></rect>')
    out.append("</svg>")
    return "".join(out)


def forecast_charts(result):
    """The three forecast charts from project()'s yearly rows."""
    years, currency = result["years"], result["currency"]
    labels = [row["year"][:4] if len(row["year"]) == 4 else row["year"][-7:-3] for row in years]
    first, last = labels[0], labels[-1]
    span = f"{first}–{last}" if first != last else first
    return {
        "net_worth": line_chart("Net worth", f"{currency}, end of each year, {span}. Today's dollars remove {result['assumptions']['inflation_percent']}% yearly inflation", labels,
                                [{"name": "Net worth", "short": "net worth", "values": [row["end_net_worth"] for row in years]},
                                 {"name": "In today's dollars", "short": "today's $", "values": [row["end_net_worth_today"] for row in years]}], currency),
        "cash_flow": line_chart("Income and spending", f"{currency} per year, {span}. Spending includes loan payments", labels,
                                [{"name": "Income", "short": "income", "values": [row["income"] for row in years]},
                                 {"name": "Spending", "short": "spending", "values": [row["spending"] + row["loan_payments"] for row in years]}], currency),
        "balance_sheet": line_chart("Cash, assets and loans", f"{currency}, end of each year, {span}", labels,
                                    [{"name": "Cash", "short": "cash", "values": [row["end_cash"] for row in years]},
                                     {"name": "Assets", "short": "assets", "values": [row["end_assets"] for row in years]},
                                     {"name": "Loans owed", "short": "owed", "values": [row["end_loans"] for row in years]}], currency),
    }
