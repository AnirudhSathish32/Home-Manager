CREATE TABLE folder_aliases (old_folder TEXT PRIMARY KEY, folder TEXT NOT NULL);
INSERT INTO folder_aliases VALUES
 ('01_Banking/Bank_Statements','Bank_Statements'),
 ('01_Banking/Credit_Card_Statements','Credit_Card_Statements'),
 ('02_Income/Pay_Stubs','Income'), ('02_Income/Tax_Documents','Taxes'),
 ('03_Purchases/Receipts','Receipts'), ('03_Purchases/Invoices','Bills'),
 ('03_Purchases/Refunds_Returns','Receipts'),
 ('04_Bills/Utilities','Bills'), ('04_Bills/Subscriptions','Bills'), ('04_Bills/Other_Bills','Bills'),
 ('05_Investments/Brokerage','Investments'), ('05_Investments/Retirement','Investments'),
 ('06_Obligations/Housing','Housing'), ('06_Obligations/Loans','Loans'), ('06_Obligations/Insurance','Insurance'),
 ('Inbox','Inbox'), ('Unfiled','Unfiled'), ('Bank_Statements','Bank_Statements'),
 ('Credit_Card_Statements','Credit_Card_Statements'), ('Income','Income'), ('Taxes','Taxes'),
 ('Receipts','Receipts'), ('Bills','Bills'), ('Investments','Investments'),
 ('Housing','Housing'), ('Loans','Loans'), ('Insurance','Insurance');
INSERT INTO library_events(document_id,blob_hash,action,detail,created_at)
 SELECT f.document_id,f.blob_hash,'folder_migration',f.folder || ' -> ' || a.folder,strftime('%Y-%m-%dT%H:%M:%fZ','now')
 FROM document_folders f JOIN folder_aliases a ON a.old_folder=f.folder WHERE a.folder<>f.folder;
UPDATE document_folders SET folder=(SELECT folder FROM folder_aliases WHERE old_folder=document_folders.folder)
 WHERE folder IN (SELECT old_folder FROM folder_aliases);
PRAGMA user_version=7;
