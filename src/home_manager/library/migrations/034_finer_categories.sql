-- A finer, flat category list (core/categories.py): "shopping" is retired in favour of furniture & decor, household
-- supplies, home improvement, clothing, electronics, personal care and others. Items filed under it keep the name,
-- marked legacy, so totals still add up until the model re-sorts them (finance/item_categories.py).
-- SQLite cannot alter a CHECK constraint, so category_source is rebuilt with 'legacy' allowed.
ALTER TABLE receipt_items ADD COLUMN category_origin TEXT CHECK (category_origin IS NULL OR category_origin IN ('model','memory','receipt','user','legacy'));
UPDATE receipt_items SET category_origin=CASE WHEN category='shopping' THEN 'legacy' ELSE category_source END;
ALTER TABLE receipt_items DROP COLUMN category_source;
ALTER TABLE receipt_items RENAME COLUMN category_origin TO category_source;
-- Remembered choices of the retired name are only hints: the next choice for the item rebuilds them.
DELETE FROM item_category_memory WHERE category='shopping';
PRAGMA user_version=34;
