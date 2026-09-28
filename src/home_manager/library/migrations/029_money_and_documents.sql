-- Bills are no longer tracked and the Bills folder is retired. Documents shown there now show as Unfiled;
-- on startup the managed library moves their files from Library/Bills to Library/Unfiled.
UPDATE folder_aliases SET folder='Unfiled' WHERE folder='Bills';
INSERT INTO library_events(document_id,blob_hash,action,detail,created_at)
 SELECT document_id,blob_hash,'folder_migration','Bills -> Unfiled',strftime('%Y-%m-%dT%H:%M:%fZ','now') FROM document_folders WHERE folder='Bills';
UPDATE document_folders SET folder='Unfiled' WHERE folder='Bills';
-- Receipts filed under Home (furniture, hardware, repairs, household supplies) are shopping.
UPDATE receipts SET category='shopping' WHERE category='home';
UPDATE record_corrections SET value='shopping' WHERE record_type='receipt' AND field='category' AND value='home';
PRAGMA user_version=29;
