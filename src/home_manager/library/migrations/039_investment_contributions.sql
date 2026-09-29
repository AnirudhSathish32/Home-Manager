-- Investments phase 4 (docs/investments.md): contributions. Pay stub 401(k), Roth, HSA and employer-match lines are read at
-- the account whose employer they come from; the forecast adds contributions each month.
-- The employer (as pay stubs name it: income_records.payer_merchant_id) whose pay stub contributions go to this account.
ALTER TABLE investment_accounts ADD COLUMN payroll_merchant_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL;
-- How that was decided: auto (matched from the documents), user (chosen), none (the user said no employer pays into it).
ALTER TABLE investment_accounts ADD COLUMN payroll_link TEXT CHECK (payroll_link IS NULL OR payroll_link IN ('auto','user','none'));
-- What you put in yourself each month, for the forecast; NULL uses your recent contributions.
ALTER TABLE investment_accounts ADD COLUMN monthly_contribution_minor INTEGER
    CHECK (monthly_contribution_minor IS NULL OR (typeof(monthly_contribution_minor) = 'integer' AND monthly_contribution_minor >= 0));
PRAGMA user_version=39;
