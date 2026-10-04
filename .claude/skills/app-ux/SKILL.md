---
name: app-ux
description: Screen and interaction rules for Home Manager's web UI (src/home_manager/app/static — index.html, *.js, style.css). Use before designing or changing any page, layout, panel, dialog, drawer, table, form, review flow or decision screen in this app, including the Review page and the document/receipt inspector. Carries the app's layout rules (decision in view, source beside the record), its design system and conventions, and how to verify a layout in the browser tests. Pair with frontend-design for visual direction and forecast-charts for charts.
---

# Screens in Home Manager

The full design record is `docs/ui.md` ("Pages", "Design system", "Accessibility", "Money and dates on screen").
Known UI bugs and UX findings are under "UI" in `docs/open-work.md`.
These are the rules to apply on every UI change; they win over general design advice where the two differ.
Use `frontend-design` for visual direction *within* the tokens below, never to replace them. Use
`forecast-charts` for any chart.

## 1. Layout rules

1. **Decision in view.** A screen that asks the user to decide (Review, reconcile prompts, confirmations) keeps
   *what*, *why it needs you*, the evidence, and the decision buttons visible together without scrolling at
   1366×768 and 1440×900. Primary actions never sit below variable-height content (images, lists, transcriptions).
   If the evidence can be tall, it scrolls inside its own region; the decision bar stays put (sticky or pinned).
2. **Source beside the record.** Wherever a record is checked against its document (Review, the receipt/document
   inspector), the document preview sits beside the record, not above or below it. Below 900px it stacks, and the
   decision bar pins to the bottom of the viewport.
3. **Many-valued facts show every value.** A receipt spanning several categories shows all of them (largest share
   first), never a single "primary" one. The same applies to matches, sources and linked records.
4. **One primary button per region.** Everything else is secondary or quiet. Destructive actions confirm first,
   state the consequence, and focus Cancel.
5. **Hierarchy through type and space, not boxes.** Borders only where a region needs containment (tables, drawer,
   inspector panes). No card-by-default.
6. **Filters and views live in the URL** so Back, reload and new windows keep them.
7. **No horizontal page scroll at 390px.** Tables scroll inside `.table-wrap`.

## 2. Conventions that must survive

- **Tokens only** (the `:root` block at the top of `style.css`): colors `--canvas --surface --surface-sunken --border --text --text-secondary
  --text-muted --accent --positive --warning --danger` (+ `-subtle`), sizes `--text-xs..xl`, `--figure-lg`,
  spacing `--space-1..8`, radii `--radius-sm/md/lg`, controls `--control-sm/md/lg`. No new hex values, no pills
  except count badges, no shadows on in-flow content.
- **Color means something.** Accent = interactive; green = money in or verified; red = errors, past due,
  destructive. **Red never means spending.**
- **Status** always through `statusBadge()` and the one `STATUS` map in `ui.js` (icon + text + tone; never color
  alone). Add new states to that map, not ad-hoc badges.
- **Money**: the browser does no arithmetic. Render the server's exact text with `amount()`; amounts right-aligned
  with tabular figures. Dates with `dateText()`/`dateDisplay()`.
- **DOM idiom**: vanilla factory functions (`element()`, `cell()`, `homeLink()`, `asyncButton()`), no framework, no
  build step, strict CSP (no inline scripts/styles, no CDN assets; icons from `icons.svg`).
- **Copy**: plain words from the user's side ("Count it", "Not a match"), no internal IDs or scores in the default
  view (they go in a Details disclosure). Errors in user language.
- **Keyboard**: every control reachable in visual order; Review keeps J/K to move, V to verify, R to reject;
  shortcuts never fire inside inputs. Visible 2px accent focus ring.
- **Links from documents** (URLs read from receipts or web lookups) are shown as text, never as live links.

## 3. Verify a layout

- Extend the opt-in browser tests (`tests/test_browser.py`, `tests/test_home_browser.py`), run with
  `.venv/Scripts/python.exe -m pytest tests/test_browser.py --browser`.
- For a decision screen, assert the primary button is inside the viewport at 1366×768 without scrolling:
  `box = page.locator("#review-confirm").bounding_box(); assert box and box["y"] + box["height"] <= 768`.
- Check 390, 768 and 1440 widths for horizontal overflow:
  `page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")`.
- Use synthetic data only; never open the live library.
