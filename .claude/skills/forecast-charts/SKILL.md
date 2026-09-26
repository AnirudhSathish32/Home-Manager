---
name: forecast-charts
description: Charts and data visualization for Home Manager — the forecast's server-drawn SVG charts (src/home_manager/charts.py), the Home dashboard charts, and any new chart, graph, plot, stat tile or chart color choice in this app. Use before writing or changing chart code or chart colors. Carries the app's validated palette and chart rules plus the general procedure (form, color, validation, marks, interaction, accessibility).
---

# Charts in Home Manager

Project copy of the general data-visualization method (the `references/` and `scripts/` here), plus
how this app applies it. Read "This app" first; use the procedure for anything new.

## This app

- **Forecast charts are drawn in Python** by `src/home_manager/charts.py` as deterministic SVG:
  same data in, byte-identical SVG out. The browser only parses and inserts them
  (`static/forecast.js`, `DOMParser` as `image/svg+xml`); it never formats money or computes values.
- **Validated palette** (light surface `#FFFFFF`), in fixed order, never cycled:
  1. blue `#2a78d6` 2. orange `#eb6834` 3. aqua `#1baf7a`.
  All checks pass; aqua is below 3:1 contrast, which the always-visible end labels and the table
  view relieve. A fourth series needs a new validated slot (see `references/palette.md`), not a
  generated hue. The Home donut's `CHART_COLORS` in `static/home.js` use slots 1–6 of the reference
  palette (validated 2026-09-25; the contrast WARN is relieved by the labeled legend and table view).
- **Budget meters** (`.meter` in `style.css`) use the status palette: on track = accent blue on a
  lighter blue track, ahead of pace = warning `#fab219`, over = critical `#d03b3b`, always with
  a status badge (icon + label) and the exact amounts as text.
- **Text colors, never series colors, for text:** `#1A1F26` (text), `#4D5663` (secondary/muted);
  gridlines `#E1E4E8`, zero line `#C9CED6`.
- **Marks:** 2px lines, round joins; end markers r=4 with a 2px white ring; hairline solid grid.
- **Labels:** legend for two or more series; direct end labels with an explicit short name
  (`"short"` in the series spec); leader lines when end labels would collide, never stacking.
- **Hover:** one full-height transparent target per point whose `<title>` lists every series.
- **Accessibility:** `role="img"` with `<title>`/`<desc>`; every chart has a per-year table view.
- **Escape all text** with `xml.sax.saxutils.escape`; no scripts, no event attributes.
- **One y-axis per chart.** Different units get separate charts.
- Tests: `tests/test_forecast.py` (determinism, escaping, ticks). Render and look at the output
  before finishing (for example, screenshot with Playwright), as step 7 requires.

## The procedure — in order; color comes last

1. **Pick the form.** Magnitude, identity, polarity, a single headline, change over time? The job
   picks the chart; sometimes the answer is a stat tile. → `references/choosing-a-form.md`
2. **Assign color by its job:** categorical (identity), sequential (magnitude), diverging
   (polarity) or status (state). Categorical hues in fixed order. → `references/color-formula.md`
3. **Validate the palette — run it, don't eyeball it:**
   `node scripts/validate_palette.js "<hex,hex,...>" --mode light --surface "#FFFFFF"`
   (add `--pairs all` for all pairs). Fix every FAIL before continuing.
4. **Apply mark specs and spacers:** thin marks, 4px rounded bar ends at the baseline, 2px lines,
   ≥8px markers, 2px surface gap between fills, 2px surface ring on overlapping marks, selective
   direct labels. → `references/marks-and-anatomy.md`
5. **Add the hover layer by default:** crosshair/tooltip for lines, per-mark tooltip for bars;
   hit targets larger than marks. → `references/interaction.md`
6. **Accessibility pass:** legend for ≥2 series, direct labels for ≤4, a table view, texture
   available for color-blind/print cases.
7. **Render it and look at it** for label collisions, geometry and overflow.

Then check against `references/anti-patterns.md`.

## Non-negotiables

- Categorical hues in fixed order, never cycled; a 9th series folds into "Other" or small multiples.
- Never a dual-axis chart.
- Color follows the entity, never its rank.
- Sequential = one hue light→dark; diverging = two hues with a neutral gray midpoint; no rainbows.
- Run the validator for every categorical palette. CVD ΔE ≥ 8 target; 6–8 only with secondary
  encoding; normal-vision floor below 15 is a hard fail. A contrast WARN requires visible labels or
  a table view.
- Text wears text colors, never the series color.
- Status colors (good/warning/serious/critical) are reserved and always come with icon + label.

## Files

| File | Answers |
|---|---|
| `references/choosing-a-form.md` | Which chart type, or not a chart |
| `references/color-formula.md` | The four color jobs, the six checks |
| `references/marks-and-anatomy.md` | Mark specs, spacers, labels, figures |
| `references/interaction.md` | Tooltips, hover, filters |
| `references/components.md` | Chart building blocks |
| `references/anti-patterns.md` | What goes wrong — check every chart |
| `references/palette.md` | Reference palette structure; swap values to re-brand |
| `scripts/validate_palette.js` / `.py` | Runnable palette validator |
