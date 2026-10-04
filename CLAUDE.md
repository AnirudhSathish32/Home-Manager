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
- `forecast-charts` — chart and chart-color rules; read before changing `src/home_manager/finance/charts.py`,
  the Home dashboard charts or any new chart.
- `app-ux` — this app's screen rules (decision in view, source beside the record, tokens, status, money);
  read before changing any page, layout, dialog or flow in `src/home_manager/app/static/`.
- `frontend-design` — Anthropic's visual-design skill (Apache 2.0, copied from anthropics/claude-code); use for
  visual direction within the `app-ux` tokens, never to replace them.
