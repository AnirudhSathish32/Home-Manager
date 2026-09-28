-- Where a purchase was made: the store's city, or Online for delivery orders. Part of a
-- receipt's title (Merchant - Location - Description) and correctable by the user.
ALTER TABLE receipts ADD COLUMN location TEXT;
PRAGMA user_version=19;
