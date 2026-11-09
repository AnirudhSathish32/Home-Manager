-- Account default names (docs/money.md "Money pages"): every word of the type is capitalized ("Chase Credit Card 1234", not
-- "Chase Credit card 1234", which 074 gave). Renames a row only while its name is still exactly 074's generated form;
-- names the user chose, and names that left the type out (065), are never touched. credit_card is the only type of two words.
UPDATE accounts
   SET display_name = institution || ' Credit Card' || CASE WHEN account_last_four IS NULL THEN '' ELSE ' ' || account_last_four END
 WHERE account_type = 'credit_card'
   AND display_name = institution || ' Credit card' || CASE WHEN account_last_four IS NULL THEN '' ELSE ' ' || account_last_four END;
PRAGMA user_version=78;
