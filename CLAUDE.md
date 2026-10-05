# Home Manager

## Private financial data
Never read, list, query or open anything under P:\Finances (the live library, its database,
Library files, originals or extracted folders), or %LOCALAPPDATA%\HomeManager.
Reason about problems from the code, tests, docs and synthetic test data instead.
If live data is truly needed, first explain why and what exactly would be read,
then ask me to run a command myself and paste the result (redacted as I see fit).
Never access it directly, even read-only.

## Donated document corpus
Never read, list, search, copy or run anything against P:\EvalCorpus: friends' and family's donated
documents, their answer files and eval results. This is stricter than the rule above. Don't ask the
user to paste anything from it except an allowlisted `summary.json`. Write and test the eval suite
only on the synthetic fixtures in Git; the user runs it on the corpus in their own terminal.
See docs/evals.md.

## Docs
Docs live in `docs/` (index: docs/README.md), one doc per area. Describe what is built in the area's doc, and put
anything not built in docs/open-work.md, not in a new plan doc. Code comments cite docs as `docs/<doc>.md "Heading"`,
so keep headings stable or update the citations when renaming one.

## Everything Claude writes for this project stays in this directory
- **Skills:** create and change project skills only in `.claude/skills/` here. Never write skills to
  `C:\Users\Anirudh\.claude\skills` or any other location on the C: drive.
- **Memory:** auto memory lives in `.claude/memory/` here (`autoMemoryDirectory` in
  `.claude/settings.local.json`). Never write memory files to `C:\Users\Anirudh\.claude\projects\…`.
- **CLAUDE.md:** project instructions belong in this file (or a CLAUDE.md inside this directory),
  never in `C:\Users\Anirudh\.claude\CLAUDE.md`.
- Temporary scripts and scratch files may use Claude's session scratchpad, which is cleaned up.

## Skills in this project
- `ui-ux-pro-max` — visual design intelligence (styles, palettes, type, UX guidelines). Use it before changing
  any page in `src/home_manager/app/static/` or charts in `src/home_manager/finance/charts.py`. The persisted design
  system lives in `design-system/home-manager/MASTER.md`. On Windows run its scripts with `python`.
- `ui-redesign` — the redesign process: phases, the per-screen planning procedure, the hand-off template the
  implementation session builds from, the selector contract, and synthetic before/after screenshots
  (`scripts/ui_shots.py`). Load it in plan mode before planning any redesign work, and when implementing that plan.
- App rules beat any skill advice: `docs/ui.md` "Screen rules". That means decision in view, source beside the
  record, money from the server, a strict CSP (no CDN fonts or assets) and no framework or build step.
