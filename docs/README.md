# Home Manager docs

The project [readme](../readme.md) has the quick start. Every doc describes the app as it is now; what isn't built yet
is in [open work](open-work.md). Git history keeps the older plans and proposals these docs were consolidated from
(2026-10-04).

| Doc | What it covers |
|---|---|
| [operations](operations.md) | Install, first start, local models and residency, commands, environment variables, where files live, backups, background work, the log and ledger health, troubleshooting. |
| [development](development.md) | Code layout, architecture and security rules, tests, manual checks, ruff/mypy, adding a migration, the schema map (001–062), database checks. |
| [documents](documents.md) | The managed library, watched folders, duplicates, browsing and Trash, schema upgrades; reading images, PDFs and CSV/XLSX; several receipts in one file; several images as one document; typed extraction and review; decision models; document search. |
| [money](money.md) | Money rules; what counts; statements and reconciliation; categories and item splits; rules and budgets; rewards; recurring bills; currency conversion; the money pages and Home. |
| [planning](planning.md) | The forecast, assets and loans, retirement and RMDs; What If (paycheck planner, saved plans, following a plan); investments. |
| [taxes](taxes.md) | The design behind Tax Zen and the engines; tax tags; the year's return; Engines 1 and 2; Tax Zen; the CPA pack; jobs and pay stubs; notes for a CPA. |
| [household](household.md) | Identifying receipt lines, inventory, run-out and check-ins, return windows, warranties, item analysis. |
| [assistant](assistant.md) | The Ask panel, how questions are answered, every tool and route, the web lookup agents, the independent reviewer. |
| [family](family.md) | Profiles, families and the family hub, the family inbox, ledger and corrections, `.hmshare` sharing, the shared GPU relay. |
| [ui](ui.md) | Pages, Review, the document page, Processing and Settings; the design system; accessibility; money on screen; the proposed restyle. Rules to apply: its "Screen rules". |
| [evals](evals.md) | Why and how models are evaluated; donating documents; the private corpus and its AI boundary. Runbook: [evals/README.md](../evals/README.md). |
| [open work](open-work.md) | Everything known to be unbuilt or broken. |
| [donation consent](donation-consent.md) | The consent form given to people who donate documents. |

Licenses for the vendored tax engine are in `src/home_manager/vendor/NOTICES.md`.
