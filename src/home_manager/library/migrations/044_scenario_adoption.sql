-- A What If plan put to use (docs/planning.md "What If"): its set spending became budgets from this month, and its paychecks and
-- spending are compared with what actually happened from then on.
ALTER TABLE scenarios ADD COLUMN adopted_month TEXT;
PRAGMA user_version=44;
