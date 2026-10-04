"""Per-task evals (eval_plan.md A9–A11): each of the app's model tasks on its own, over synthetic cases with known answers.

A task module defines NAME, ROLE ("vision", "reasoning" or "decision"), VERSION (its dataset version) and PROMPT_VERSION, and:
  cases() -> [{"id", "tags", "input", "expected"}]   deterministic and made up, safe to read and share
  run(case, config, work) -> output                   calls the app's own task function; raises ValueError on failure
  grade(case, output) -> {"passed", "score", "checks"}
RUBRIC names a judge rubric in evals/rubrics/ for what code cannot check; MULTI_STEP marks an agent loop.
report_lines({candidate: [result line]}) -> [markdown line], when present, adds to the task's section of report.md.
The web agents (item_lookup, warranty, tax_table) run against recorded pages (tasks/web.py), never the web.

Reading, classification, header and row extraction of whole documents are measured end to end by `python -m evals.run`.
"""

from . import (
               assistant,
               checkin,
               decisions,
               describe,
               identify,
               interpretation,
               item_lookup,
               payees,
               payment_terms,
               reviewer,
               rewards,
               tax_table,
               transcription,
               warranty,
)

TASKS = {module.NAME: module for module in (transcription, identify, describe, rewards, payment_terms, interpretation, reviewer, payees,
                                            checkin, assistant, item_lookup, warranty, tax_table, decisions)}
