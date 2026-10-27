-- Account default names (docs/money.md "Money pages"): the generated name now capitalizes its type ("Chase Savings 1234",
-- not "Chase savings 1234"). Renames a row only while its name is still exactly the old generated form (institution, the
-- type in lower case, optional last four). Names the user chose, and names that left the type out (065), are never touched.
UPDATE accounts
   SET display_name = institution || ' ' || upper(substr(replace(account_type, '_', ' '), 1, 1)) || substr(replace(account_type, '_', ' '), 2)
                      || CASE WHEN account_last_four IS NULL THEN '' ELSE ' ' || account_last_four END
 WHERE display_name = institution || ' ' || replace(account_type, '_', ' ')
                      || CASE WHEN account_last_four IS NULL THEN '' ELSE ' ' || account_last_four END;
PRAGMA user_version=74;
