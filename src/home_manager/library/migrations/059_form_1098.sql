-- Form 1098 (a lender's mortgage interest statement) among the tax forms read (finance/investments.py TAX_FORMS): box 1
-- mortgage interest, box 2 the principal outstanding on Jan 1 and box 10 property tax fill the year's return
-- (finance/tax_year.py), including the mortgage's average balance the tax engine needs (Pub 936).
CREATE TABLE "tax_form_boxes_new" (
    id INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL REFERENCES tax_forms(id) ON DELETE CASCADE,
    form TEXT NOT NULL CHECK (form IN ('1099-INT','1099-DIV','1099-B','1099-R','1099-SA','1099-Q','1099-DA','5498','5498-SA','1098')),
    box TEXT NOT NULL,  -- As printed, lower case: 1, 1a, 2b.
    label TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer'),
    locator_json TEXT NOT NULL DEFAULT '{}'
) STRICT;
INSERT INTO "tax_form_boxes_new"("id","form_id","form","box","label","amount_minor","locator_json") SELECT "id","form_id","form","box","label","amount_minor","locator_json" FROM "tax_form_boxes";
DROP TABLE "tax_form_boxes";
ALTER TABLE "tax_form_boxes_new" RENAME TO "tax_form_boxes";
CREATE INDEX tax_form_boxes_form ON tax_form_boxes(form_id);

PRAGMA user_version=59;
