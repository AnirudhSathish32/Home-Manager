-- A receipt's order-wide discount and its printed order number (docs/money.md "Item categories and splits"). Only adds two
-- NULL columns, so no existing receipt, item or split changes.
-- discount_minor: the printed Discounts (or promo, coupon) total, money off the whole order, with the receipt's sign: positive
-- on a sale, negative on a return. order_number: the order or transaction number an online order prints, as printed.
ALTER TABLE receipts ADD COLUMN discount_minor INTEGER CHECK (discount_minor IS NULL OR typeof(discount_minor)='integer');
ALTER TABLE receipts ADD COLUMN order_number TEXT;
PRAGMA user_version=76;
