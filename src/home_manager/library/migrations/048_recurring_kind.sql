-- Recurring payments are the user's bills (important) or subscriptions (less so). Detection suggests one from the
-- category; the user confirms or changes it, and re-detection never overwrites it. Both count in forecasts and budgets.
ALTER TABLE recurring_obligations ADD COLUMN kind TEXT NOT NULL DEFAULT 'bill' CHECK (kind IN ('bill','subscription'));
UPDATE recurring_obligations SET kind='subscription' WHERE category IN ('subscriptions','entertainment');
PRAGMA user_version=48;
