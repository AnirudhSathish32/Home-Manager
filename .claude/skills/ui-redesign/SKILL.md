---
name: ui-redesign
description: Process for Home Manager's full UI redesign. Use when planning or implementing any part of the redesign or restyle, including a page, tokens, base components, dark theme, fonts or the persisted design system for src/home_manager/app/static. Covers phases, the per-screen planning procedure, the required hand-off template for the implementation session, the selector contract, before/after screenshots on synthetic data, and verification. Visual decisions come from the ui-ux-pro-max skill; this skill adds the app's hard limits and workflow.
---

# UI redesign: plan one screen well, hand it off completely

The redesign runs across many sessions. A **planning** session (plan mode) plans one unit of work, and a separate
**implementation** session builds it from the plan alone. The plan is the only bridge between them. A planner that
leaves something out forces the implementer to guess, and guesses drift from the design system.

**Who decides what:**
- `ui-ux-pro-max` makes the visual decisions: style, palette, type, spacing, motion and UX guidelines.
- This skill sets the process and the app's hard limits.
- `docs/ui.md` "Screen rules" win over both.

## 1. Read first, in order
1. `CLAUDE.md`, for the privacy rules (never the live library) and the skill list.
2. `docs/ui.md` "Screen rules": layout, conventions and verification. These are non-negotiable.
3. `design-system/home-manager/MASTER.md`, and `design-system/home-manager/pages/<page>.md` if it exists. If MASTER.md
   doesn't exist yet, you are in phase 0.
4. `.claude/skills/ui-ux-pro-max/SKILL.md`, for how to query it.
5. `references/screen-inventory.md` (this skill), for the page's files, containers, tests and selector Greps.
6. `references/plan-template.md` (this skill), for the shape the plan must take.

Read files with offset/limit or Grep. `style.css`, `index.html` and the page JS are large.

## 2. Hard limits (Pro Max advice that doesn't apply here)
- **No framework, no build step, no Tailwind or shadcn.** The UI is plain JS with vanilla DOM factories. Ignore Pro Max
  stack output for React/Next/Tailwind. If you query `--stack`, use `html-tailwind` only for ideas and translate them
  to plain CSS.
- **Strict CSP** (`src/home_manager/app/api.py`, the `Content-Security-Policy` header). It allows no inline `style=`
  attributes or `<style>`/`<script>` blocks and nothing from a CDN. Fonts are self-hosted in `app/static/fonts/` (woff2,
  with a checked license) and icons come from `icons.svg`. Google Fonts URLs from Pro Max become downloaded files.
- **Tokens only.** Every color, size, space, radius and shadow is a `:root` custom property in `style.css`. The dark
  theme redefines them under `[data-theme=dark]` and `prefers-color-scheme`, and doesn't add parallel classes.
- **Meaning stays fixed.** Accent is interactive. Green is money in or verified. Red is error, past due or destructive,
  and **never spending**. Status goes through `statusBadge()` and the `STATUS` map in `ui.js`.
- **Money and dates** are server text through `amount()`, `dateText()` and `dateDisplay()`. The browser does no
  arithmetic.
- **No landing-page patterns.** Pro Max often returns hero sections, CTAs and glassmorphism. This is a dense working app,
  so take its palette, type and spacing and leave the marketing layout. Prefer `--density 7–9` for data screens.
- **Privacy.** Screenshots and tests use synthetic data only (`scripts/ui_shots.py`). Never point anything at
  `P:\Finances` or `%LOCALAPPDATA%\HomeManager`.

## 3. Phases (one per session)
The design and its principle (every number explainable) are in docs/ui.md "Redesign: calculation observability". The
work items, in build order, are in docs/open-work.md "UI redesign". Its sections 1–4 are backend work (numbers that
can be wrong, browser math, traces and provenance) and come before the phases below. A screen session builds on those
traces and doesn't invent explanations the backend can't give.

0. **Design system.** Query Pro Max with a precise description, not a generic one, for example:
   `python .claude/skills/ui-ux-pro-max/scripts/search.py "personal finance household ledger records dashboard" --design-system --density 8 --persist -p "Home Manager" --output-dir .`
   Reconcile the result with docs/ui.md "Screen rules" and "Redesign: calculation observability". Then show the user
   2–3 directions **as browser pages** (a throwaway artifact), and have them approve MASTER.md. The output of this phase
   is MASTER.md. It has no app code changes.
1. **Foundation.** Tokens (light and dark), self-hosted fonts, and base components in `style.css` "Controls",
   "Feedback", "Tables" and "Menus and dialogs", plus the shell and sidebar. Page layouts don't change. Check every page
   afterwards with `ui_shots.py`, because tokens touch everything.
2. **Screens**, one per session, in the order in docs/open-work.md "UI redesign": Taxes → Today → To check and
   the document page → Money screens → Wealth → the rest. Each new screen sits behind the `ui_v2_screens` flag. The old
   loader is deleted once `tests/test_ui_parity.py` and the screen's tests pass; there's no separate sign-off.
3. **Cleanup.** Remove dead CSS and the old loaders, rewrite docs/ui.md "Design system" and "Pages" to match what was
   built, retire "Redesign: calculation observability" into them, and update "Screen rules" if any token names
   changed.

## 4. Planning procedure for one screen
1. **Before screenshots.**
   `.venv/Scripts/python.exe .claude/skills/ui-redesign/scripts/ui_shots.py --routes <route> --out <scratchpad>/before-<page>`
   It covers 390/768/1440 in light and dark, and accepts `--full-page`. Look at the images. If the default seed doesn't
   show the screen's interesting states, add seeding to the script.
2. **Selector contract.** Run the Greps in `references/screen-inventory.md` against the page's tests and JS. Every id,
   class and role found is kept, or renamed with a matching test edit listed.
3. **User job and problems.** Say what the user comes to this screen to do, and what's wrong today. Ask the user if you
   don't know. Don't guess at intent.
4. **Pro Max for the page.** Run `search.py "<page purpose>" --design-system --persist -p "Home Manager" --page "<page>" --output-dir .`
   plus `--domain ux` or `--domain chart` lookups as needed. Edit `pages/<page>.md` so it agrees with MASTER.md and the
   screen rules.
5. **Layout.** Draw ASCII at 1440 and 390. Check it against Layout rules 1–6, especially decision in view at 1366×768
   and source beside the record.
6. **Ask only real choices.** Use AskUserQuestion with ASCII mockup previews, for at most 2–3 decisions. Settle
   everything else from MASTER.md.
7. **Write the plan** with every heading in `references/plan-template.md`. Be concrete enough that the implementer
   makes no visual decisions.

## 5. Implementation rules (for the session that builds the plan)
- Build exactly what the hand-off says. If something in it is wrong or missing, stop and say so; don't improvise a new
  design.
- Use tokens only, reuse the helpers listed in the inventory, and add no new hex values outside `:root`.
- Keep the selector contract. Make the listed test edits in the same change.
- Use Edit/Write for changes (no sed or heredoc edits) and no `cd …;` compound commands.
- Make one commit per screen, after verification passes, only when the user asks for it.

## 6. Verification (every unit of work)
- The screen's browser tests, as listed in the plan:
  `$env:RUN_BROWSER_TESTS = "1"; .venv/Scripts/python.exe -m pytest tests/<files> -q`. Run only the touched
  components, not the full suite.
- Run `ui_shots.py` again into `after-<page>` and compare it with the before images at every width and theme. The
  script prints `HORIZONTAL OVERFLOW` and page errors, and both must be absent.
- Run the docs/ui.md "Verifying a layout" checks. Add an in-view assertion for any decision screen.
- Tab through the page to check keyboard order and the visible focus ring. Review must keep J/K/V/R.
- Check contrast for every new token pair, in light and dark.
- Update docs/ui.md as the plan's "Docs to update" says.

## 7. Pitfalls seen with this approach
- Generic Pro Max queries return generic or marketing results. Put the domain, the screen's job and the density in the
  query.
- Card-by-default layouts break the "hierarchy through type and space" rule. Use borders only for containment.
- Restyling two screens in one session leads to half-verified work and tangled diffs.
- Renaming an id without grepping the tests passes review but breaks browser tests silently, because they are opt-in.
- Dark theme added as an afterthought misses hardcoded colors. Find them with Grep `#[0-9a-fA-F]{3,6}` in `style.css`
  outside `:root`, and in the JS (`home.js` `CHART_COLORS`, `finance/charts.py`).
