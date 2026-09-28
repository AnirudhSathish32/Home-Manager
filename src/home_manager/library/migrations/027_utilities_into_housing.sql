-- Utilities became part of the housing receipt category (rent, mortgage, HOA and utilities).
UPDATE receipts SET category='housing' WHERE category='utilities';
UPDATE record_corrections SET value='housing' WHERE record_type='receipt' AND field='category' AND value='utilities';
PRAGMA user_version=27;
