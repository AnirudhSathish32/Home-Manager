-- Bills with line items, and money in on the ledger (docs/money.md "Bills and their lines", "Money in and paystubs").
-- A bill is a receipt with document_kind 'bill': it counts on its due date (purchase_date) by its lines' categories
-- until the payment that paid it replaces it. The old bills table is copied in and dropped; every typed-id row that
-- named a bill now names its receipt.
ALTER TABLE receipts ADD COLUMN document_kind TEXT NOT NULL DEFAULT 'receipt' CHECK (document_kind IN ('receipt','bill'));
ALTER TABLE receipts ADD COLUMN issue_date TEXT;
ALTER TABLE receipts ADD COLUMN due_date TEXT;
ALTER TABLE receipts ADD COLUMN period_start TEXT;
ALTER TABLE receipts ADD COLUMN period_end TEXT;
-- Everything the bill asks for, past-due balances included; total_minor is only the new charges, which is what counts.
ALTER TABLE receipts ADD COLUMN amount_due_minor INTEGER CHECK (amount_due_minor IS NULL OR typeof(amount_due_minor) = 'integer');
-- The bill's own account number at the provider, last four digits only: it can name the payment on a bank line.
ALTER TABLE receipts ADD COLUMN account_last_four TEXT CHECK (account_last_four IS NULL OR account_last_four GLOB '[0-9][0-9][0-9][0-9]');
-- Who a bill's line is for, as printed (a phone line's name and number), the family member it belongs to, and what it is.
ALTER TABLE receipt_items ADD COLUMN line_holder TEXT CHECK (line_holder IS NULL OR length(line_holder) <= 80);
ALTER TABLE receipt_items ADD COLUMN member_id TEXT CHECK (member_id IS NULL OR length(member_id) BETWEEN 1 AND 32);
ALTER TABLE receipt_items ADD COLUMN member_source TEXT CHECK (member_source IS NULL OR member_source IN ('configured','user'));
ALTER TABLE receipt_items ADD COLUMN line_kind TEXT
    CHECK (line_kind IS NULL OR line_kind IN ('service','usage','subscription','device','tax_fee','credit','other'));

INSERT OR IGNORE INTO receipts(document_id,blob_hash,segment,extraction_run_id,merchant_id,purchase_date,total_minor,currency,review_status,
                               validation_json,created_at,updated_at,review_source,document_kind,issue_date,due_date,period_start,period_end,
                               amount_due_minor)
SELECT document_id,blob_hash,0,extraction_run_id,provider_merchant_id,coalesce(due_date,issue_date),amount_due_minor,currency,review_status,
       validation_json,created_at,updated_at,review_source,'bill',issue_date,due_date,period_start,period_end,amount_due_minor FROM bills;
CREATE TEMP TABLE bill_receipts AS
SELECT b.id AS bill_id,r.id AS receipt_id,b.payment_transaction_id FROM bills b
  JOIN receipts r ON r.blob_hash=b.blob_hash AND r.segment=0 AND r.document_kind='bill';

-- The transaction a person said paid a bill is now that receipt's verified match, unless the line already matches another.
INSERT OR IGNORE INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at)
SELECT payment_transaction_id,receipt_id,100,'user_choice','verified',strftime('%Y-%m-%dT%H:%M:%S+00:00','now'),strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
  FROM bill_receipts WHERE payment_transaction_id IS NOT NULL
   AND NOT EXISTS(SELECT 1 FROM transaction_receipt_links l WHERE l.transaction_id=payment_transaction_id AND l.review_status<>'rejected');

UPDATE record_corrections SET record_id=(SELECT receipt_id FROM bill_receipts WHERE bill_id=record_corrections.record_id),record_type='receipt',
       field=CASE field WHEN 'provider' THEN 'merchant' ELSE field END
 WHERE record_type='bill' AND record_id IN (SELECT bill_id FROM bill_receipts);
DELETE FROM record_corrections WHERE record_type='bill';
UPDATE review_events SET record_id=(SELECT receipt_id FROM bill_receipts WHERE bill_id=review_events.record_id),record_type='receipt'
 WHERE record_type='bill' AND record_id IN (SELECT bill_id FROM bill_receipts);
DELETE FROM review_events WHERE record_type IN ('bill','bill_payment');
UPDATE financial_evidence_links SET record_id=(SELECT receipt_id FROM bill_receipts WHERE bill_id=financial_evidence_links.record_id),record_type='receipt'
 WHERE record_type='bill' AND record_id IN (SELECT bill_id FROM bill_receipts);
DELETE FROM financial_evidence_links WHERE record_type='bill';
UPDATE OR IGNORE reconciliation_issues SET record_id=(SELECT receipt_id FROM bill_receipts WHERE bill_id=reconciliation_issues.record_id),record_type='receipt'
 WHERE record_type='bill' AND record_id IN (SELECT bill_id FROM bill_receipts);
DELETE FROM reconciliation_issues WHERE record_type='bill';
UPDATE family_corrections SET record_id=(SELECT receipt_id FROM bill_receipts WHERE bill_id=family_corrections.record_id),record_type='receipt',
       field=CASE field WHEN 'provider' THEN 'merchant' ELSE field END
 WHERE record_type='bill' AND record_id IN (SELECT bill_id FROM bill_receipts);
DELETE FROM family_corrections WHERE record_type='bill';
UPDATE OR IGNORE record_shares SET record_id=(SELECT receipt_id FROM bill_receipts WHERE bill_id=record_shares.record_id),record_type='receipt'
 WHERE record_type='bill' AND record_id IN (SELECT bill_id FROM bill_receipts);
DELETE FROM record_shares WHERE record_type='bill';
-- Shared by line: the member whose lines this library's part is (docs/family.md "Sharing a bill by line").
ALTER TABLE record_shares ADD COLUMN member_id TEXT CHECK (member_id IS NULL OR length(member_id) BETWEEN 1 AND 32);

-- A family record can now go to people by its lines (mode 'lines'), and is never a bill row.
CREATE TABLE family_assignments_new (
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','statement','income_record')),
    record_id INTEGER NOT NULL,
    family_record_key TEXT NOT NULL UNIQUE,
    mode TEXT CHECK (mode IS NULL OR mode IN ('member','shared','lines')),
    members_json TEXT NOT NULL DEFAULT '[]',
    suggested_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('unassigned','suggested','confirmed','delivered')),
    delivered_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    actor TEXT,
    PRIMARY KEY (record_type, record_id)
) STRICT;
INSERT OR IGNORE INTO family_assignments_new
SELECT CASE record_type WHEN 'bill' THEN 'receipt' ELSE record_type END,
       CASE record_type WHEN 'bill' THEN (SELECT receipt_id FROM bill_receipts WHERE bill_id=f.record_id) ELSE record_id END,
       family_record_key,mode,members_json,suggested_json,status,delivered_json,updated_at,actor
  FROM family_assignments f WHERE record_type<>'bill' OR record_id IN (SELECT bill_id FROM bill_receipts);
DROP TABLE family_assignments;
ALTER TABLE family_assignments_new RENAME TO family_assignments;

DROP TABLE bill_receipts;
DROP TABLE bills;

-- A person asks their family to share a bill by its lines; the family computer reads the request from their copy.
CREATE TABLE share_requests (
    receipt_id INTEGER PRIMARY KEY REFERENCES receipts(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('lines')),
    requested_at TEXT NOT NULL,
    actor TEXT
) STRICT;

-- A pay stub counts as net pay on its pay date until the bank deposit that paid it is linked here.
CREATE TABLE transaction_income_links (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    income_record_id INTEGER NOT NULL REFERENCES income_records(id) ON DELETE CASCADE,
    match_score INTEGER NOT NULL,
    match_method TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(transaction_id, income_record_id)
) STRICT;
CREATE INDEX transaction_income_links_income ON transaction_income_links(income_record_id);

-- Housing narrowed to rent, mortgage and HOA; utilities and phone & internet are their own categories now. Items the
-- model put in housing are re-sorted once by Categorise their items (finance/item_categories.py); a person's choice stays.
UPDATE receipt_items SET category_source='legacy' WHERE category='housing' AND category_source='model';
PRAGMA user_version=67;
