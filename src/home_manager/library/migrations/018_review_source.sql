-- Who decided a record's review state: the user, or the automatic checks that accept an
-- extraction only when every deterministic check passes. Only the user's decisions keep a
-- later extraction from rewriting the record. Earlier decisions were all made by the user.
ALTER TABLE statements ADD COLUMN review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic'));
ALTER TABLE transactions ADD COLUMN review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic'));
ALTER TABLE receipts ADD COLUMN review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic'));
ALTER TABLE bills ADD COLUMN review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic'));
ALTER TABLE income_records ADD COLUMN review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic'));
UPDATE statements SET review_source='user' WHERE review_status IN ('verified','rejected');
UPDATE transactions SET review_source='user' WHERE review_status IN ('verified','rejected');
UPDATE receipts SET review_source='user' WHERE review_status IN ('verified','rejected');
UPDATE bills SET review_source='user' WHERE review_status IN ('verified','rejected');
UPDATE income_records SET review_source='user' WHERE review_status IN ('verified','rejected');
PRAGMA user_version=18;
