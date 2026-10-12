-- Account default names (docs/money.md "Money pages"):the generated name left out the type only from now on, so older
-- rows read "Household checking checking". Renames a row only while its name is still exactly the old generated form
-- (institution, type, optional last four) and its institution already ends with the type as a word. Names the user
-- chose are never touched.
UPDATE accounts
   SET display_name = institution || CASE WHEN account_last_four IS NULL THEN '' ELSE ' ' || account_last_four END
 WHERE display_name = institution || ' ' || replace(account_type, '_', ' ')
                      || CASE WHEN account_last_four IS NULL THEN '' ELSE ' ' || account_last_four END
   AND (lower(institution) = replace(account_type, '_', ' ') OR lower(institution) LIKE '% ' || replace(account_type, '_', ' '));
PRAGMA user_version=65;
