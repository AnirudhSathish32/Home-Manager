# Home Manager docs

Every doc, grouped by what it is for. Updated 2026-09-30. The project [readme](../readme.md) has the quick start.

## Start here

| Doc | What it covers |
|---|---|
| [operations](operations.md) | Install, commands and flags, environment variables, where files live, LM Studio, backups, background work, troubleshooting. |
| [development](development.md) | Code layout, tests (unit, browser, decision models), ruff/mypy, how to add a migration. |
| [manual testing](manual-testing.md) | Starting the app, capture checks, a manual check list per feature. |
| [milestones](milestones.md) | What is built, and the **[open work](milestones.md#open-work)** list. |

## Reference: how built features work

| Doc | What it covers |
|---|---|
| [managed library](managed-library.md) | Library/Inbox, automatic filing, schema upgrades and recovering from a failed one. |
| [library browser](library-browser.md) | The sidebar, folders, document rows, Trash. |
| [image transcription](receipt-parsing.md) | The vision model: setup, evidence, failure handling. |
| [financial reasoning](financial-reasoning.md) | The reasoning stage over saved text (API only), model residency. |
| [V2 phases](v2-phases.md) | Typed extraction, review, reconciliation, the finance tools. |
| [decision models](decision-models.md) | The independent checks: a plug-and-play System One model in LM Studio or a `/v1/systemone` server (Kev), calibration. |
| [receipts and statements](receipts-and-statements.md) | Money vs document folders, receipt counting, statements, recurring bills, rewards. |
| [money, review and inventory](money-review-inventory.md) | Review, budgets and rules, check-ins, inventory. |
| [household items](household-items.md) | Item identification, inventory lots, web lookups. |
| [items, assets and search](items-assets-search.md) | Returns, statement assets, item questions. |
| [warranties](warranties-assistant-processing.md) | Warranty lookups and the assistant's processing. |
| [document search](document-search.md) | Full-text search of document text (FTS5), `index-documents`. |
| [assistant](assistant.md) | How Ask answers, every tool and route, web lookup agents, the independent reviewer. |
| [home screen](home-screen-design.md) | The Home dashboard. |
| [forecast](forecast.md) | Long-range forecast, assets and loans, retirement and RMDs. |
| [What If](what-if.md) | Paycheck planner, saved scenarios, plan vs actual. |
| [jobs and paystubs](jobs-and-paystubs.md) | Employers, the Jobs folders, the paystub tax breakdown, tax tables. |
| [investments](investments.md) | Investment accounts, holdings, lots, tax forms, RMDs, payment matching. |
| [taxes](taxes.md) | Tax tags, the year's return estimate, Tax Zen, estimated tax, family returns, the year-end CPA pack. |
| [currency conversion](currency-conversion.md) | ECB rates, USD totals, foreign receipts matched to USD card charges, the rate tools. |
| [sharing](sharing.md) | Profiles, `.hmshare` exports, families, the family inbox. |
| [schema map](schema.md) | What each migration (001–047) adds. |

## Plans with an "as built" record

These plans are built. They explain the reasoning behind a feature; the reference docs above describe how it works now.

| Doc | Status |
|---|---|
| [architecture](architecture.md) | The original design proposal; mostly built. It also covers the diagnostic log and ledger health. |
| [document reading](document-reading.md) | The original reading/ingestion design; built, with open items. |
| [document parsing](document-parsing.md) | Parsing decisions; built, with open items. |
| [UI design plan](ui-design-plan.md) | Phases A–F built. With the `app-ux` skill, it is the current design system. |
| [profiles and family plan](profiles-and-family-plan.md) | Built 2026-09-28; current behavior is in [sharing](sharing.md). |
| [shared GPU plan](shared-gpu-plan.md) | Built 2026-09-28. LM Studio load/unload is not yet confirmed. |

## Planned, not built

| Doc | Status |
|---|---|
| [Donated document corpus](private-reliability-testing.md) | Built: friends and family check and donate documents (Donate documents page); a private corpus run locally by the deterministic eval suite in `evals/`. Consent text: [donation-consent.md](donation-consent.md). |
| [Model comparison evaluations](../eval_plan.md) | Proposed: task inventory, graders, and comparing local model configurations; paired with the private reliability plan. |
| [new UI/UX design](new_ui_ux_design.md) | The "Household ledger" restyle (dark theme, fonts); not started. |

## Archive

Superseded; kept for history.

| Doc | Replaced by |
|---|---|
| [homepage proposal](archive/homepage-proposal.md) | [UI design plan](ui-design-plan.md), [home screen](home-screen-design.md) |
| [V2 Phase 1 plan](archive/phase-1-plan.md) | [managed library](managed-library.md) |

`Home_Manager_Architecture_Implementation_Spec.docx` is the V2 specification the phases were built from.
