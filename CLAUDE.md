# Home Manager

## Private financial data
Never read, list, query or open anything under P:\Finances (the live library, its database,
Library files, originals or extracted folders), or %LOCALAPPDATA%\HomeManager.
Reason about problems from the code, tests, docs and synthetic test data instead.
If live data is truly needed, first explain why and what exactly would be read,
then ask me to run a command myself and paste the result (redacted as I see fit).
Never access it directly, even read-only.

## Everything Claude writes for this project stays in this directory
- **Skills:** create and change project skills only in `.claude/skills/` here. Never write skills to
  `C:\Users\Anirudh\.claude\skills` or any other location on the C: drive.
- **Memory:** auto memory lives in `.claude/memory/` here (`autoMemoryDirectory` in
  `.claude/settings.local.json`). Never write memory files to `C:\Users\Anirudh\.claude\projects\…`.
- **CLAUDE.md:** project instructions belong in this file (or a CLAUDE.md inside this directory),
  never in `C:\Users\Anirudh\.claude\CLAUDE.md`.
- Temporary scripts and scratch files may use Claude's session scratchpad, which is cleaned up.

## Skills in this project
- `forecast-charts` — chart and chart-color rules; read before changing `src/home_manager/charts.py`,
  the Home dashboard charts or any new chart.
