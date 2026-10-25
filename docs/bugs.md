> The nine fixes planned on 2026-10-12 are implemented. See [money.md](money.md#corrections), [documents.md](documents.md#browsing-the-library) and [ui.md](ui.md#the-document-page).
> Refunds, gas-station receipts and ingestion by content are listed under that doc's Ingestion and Money sections.

When saving a document directly from browser to the inbox folder, the inbox badge does not increment on the side panel but the inbox page shows the correct value. When pressing Read the badge then updates on the side panel. This behavior occured when the app was open. 

I cannot correct the price of an item, subtotal or total on a read reciept manually when i open that reciept. Additionally when  i open the reciept there is a paid category near individual line items. It says 0.00 on each item even though the LLM notices a payment near each line item on the reciept. Why does it show 0.00? 

I scanned a bill and had no where to put it when i pressed record the button did not work. Maybe we should have a bill folder. When i press Record and read on images/pdfs that are readily identified as reciepts these buttons work as intended. I think this factors in to my later complaint where document ingestion tries to treat everything as a receipt.. 

When scanning a paystub, If the LLM cant reason out the pay period i have no way to manually input the pay period.

When scanning a refund with perfectly extracted text, the reasoning LLM had no idea what to do. It did not list the refund price, did not recognize the item or furniture it didnt even recognize that it was a refund even though it says it in the text. The refund logic needs to be looked at again. 

When selecting multiple documents i should be able to record all/record selected. This record button should be next to read in the menu that appears when selecting multiple documents.

When scanning a gas station reciepts the system doesnt recognize it is a gas station receipt so it tries to say that Pump 17 is an item and does not note down the gallons, the price per gallon. So we need to develop a gas station recipt ingestion process. 

When approving a receipt the line item does not get stored in the transaction leder but rather the name of the merchant. This appeared when approving a refund reciept. This appears again when approving a dining reciept.

The transaction ledger sometimes does not allow me to change the category and sometimes it does why is this behavior inconsistent

I should be able to add a subtotal, total, tax in the event the LLM is not able to. 

From what i understand there is a singular document ingestion mechanism rather than document ingestion based off content of the document. So a document i simply want to store in my vault say an offer letter is treated the same as a receipt. There needs to be different document ingestion meechanisms based off of content. A gas station receipt and a dining receipt and a grocery recieept need to be treated differently. An offer letter or contract should not be treated like a receipt at all but if i put these things in the inbox it should trigger a different deterministic python pathway that makes them go into the prerequisite folder category. 

When reading a receipt from the inbox -> the document disappears from view and i have no idea where it went. IT should stay in the inbox until i press record. 

When taking a grocery reciept lets say it has 3 items. One for 12.99, one for 6.99 and one for 11.79. The taxes for these items are 1.19. The current system shows in the paid category 13.48, 7.25 and 12.23. Instead is should show the tax as its own line item of 1.19 and show 12.99 (13.48 with tax), 6.99 (7.25 with tax) etc. In the ledger we can keep the 13.48 but when opening up the document i want to see this information.

Adding a budget brings up a drop down menu that appears in the middle of the screen. 
## Agent findings

<!-- finding:61c3f8eee8040a9b -->
### #P:/Dev Environment/Git/documents/ID: kind change and Apply details offer no Undo
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/documents/36?tab=history
- Kind: bug · Severity: medium
- Steps: 1. Open a receipt's document page. 2. Pick another kind in Receipt kind and press Change kind..., then Read again. 3. Look at the toast and the History tab.
- Expected: FR-11/FR-12: the kind change (and Apply details) appears in history with Undo, as a field correction's toast does.
- Actual: Toast 'Read as fuel.' has no Undo; History lists 'Receipt kind: general -> fuel' with no Undo; the user can't undo it from the page (the API can: undo_corrections).
- Evidence: tests/.tmp/evidence/kind-change-history-no-undo.png

<!-- finding:de00e63a8b71470e -->
### #/documents/ID: kind change history says Home Manager, not the person
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/documents/36?tab=history
- Kind: bug · Severity: low
- Steps: 1. Open a receipt's document page. 2. Change its kind and confirm Read again. 3. Open the History tab.
- Expected: The correction names the person who changed the kind, like other corrections (record_corrections.actor).
- Actual: The Receipt kind row's who is 'Home Manager': the correction is written by the background reading, where no actor is set.
- Evidence: tests/.tmp/evidence/kind-change-history-who.png

<!-- finding:263db311b9774968 -->
### #/documents/ID: tender kept that the receipt doesn't print
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/documents/37
- Kind: bug · Severity: medium
- Steps: 1. Add uploads/grocery-receipt.png (prints no payment line) and let it be read. 2. Open its document page.
- Expected: FR-04: a tender is kept only when its payment is printed; a tender's type word (gift card, EBT, VISA, cash) must be in its citation, like account_type.
- Actual: Printed details shows 'Cash 18.24 USD', cited to 'Total USD 18.24'. Only the amount is checked; a gift_card answered the same way would make the receipt count 0.00 (refresh_paid).
- Evidence: tests/.tmp/evidence/grocery-invented-tender.png

<!-- finding:f0a75f11314255fd -->
### #/documents/ID: deposit split read from the net pay line passes its own check
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/documents/41
- Kind: bug · Severity: medium
- Steps: 1. Add uploads/pay-stub.png (prints no direct deposit) and let it be read. 2. Open its document page: Printed details and Arithmetic checks.
- Expected: FR-20/FR-21: a deposit split is kept only from a printed deposit line; the splits check never compares net pay with itself.
- Actual: Direct deposit 2,739.81 USD is stored, cited to 'Net pay 2,739.81' (its account was dropped), and 'Direct deposits 2,739.81 matches the printed 2,739.81' counts as a passed cross-check.
- Evidence: tests/.tmp/evidence/paystub-invented-deposit.png

<!-- finding:f9fd85ff793e1178 -->
### #/documents/ID: 401k line amount dropped as multiple amounts
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/documents/41
- Kind: bug · Severity: medium
- Steps: 1. Add uploads/pay-stub.png (prints '401k 184.98') and let it be read. 2. Open its document page: From gross pay to net pay.
- Expected: The 401k line keeps 184.98: the digits in the label '401k' aren't a second amount.
- Actual: 401k shows no amount, with 'Pay line 2 has multiple amounts without a validated source row' (extraction.anchor_paystub counts 401 as a number). Pre-existing, not from document forms.
- Evidence: tests/.tmp/evidence/paystub-401k-and-totals.png

<!-- finding:c6b704fd82020a31 -->
### #/documents/ID: Gross pay and Net pay read as earnings lines
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/documents/41
- Kind: bug · Severity: low
- Steps: 1. Add uploads/pay-stub.png and let it be read. 2. Open its document page: From gross pay to net pay, and the why.
- Expected: Totals (gross pay, net pay) are never pay lines, on the flat-text path too, so earnings equal gross.
- Actual: Earnings list Gross pay and Net pay as lines; 'Earnings (10,139.37 USD) do not add up to gross pay (3,699.78 USD)' sends it to review. The exclusion only runs for cited table rows. Pre-existing, not from document forms.
- Evidence: tests/.tmp/evidence/paystub-totals-as-lines.png

<!-- finding:95740f2e301c56cb -->
### #/documents/ID: failing check's breakdown says it's a bug and hides the printed amount
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/documents/35
- Kind: bug · Severity: medium
- Steps: 1. Open a dining receipt's document page. 2. Correct Tip to 1.00 and Save (the check now reads 9.06 doesn't match the printed 8.06). 3. Open the check figure under Arithmetic checks.
- Expected: FR-19: the breakdown shows the printed amount it is compared with (compared_with) and whether the check passes; reconciles false is a check's outcome, not a bug.
- Actual: The steps add up to 9.06, but the panel shows 'These steps don't add up to the figure. This is a bug; please report it.' and never shows 8.06: trace.js treats reconciles=false as a bug and ignores compared_with.
- Evidence: tests/.tmp/evidence/check-breakdown-calls-mismatch-a-bug.png

<!-- finding:1e6bf83b66ff7528 -->
### #/processing: Scan now right after Watch folder shows a lasting error
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude-validate-document-forms
- Page: http://127.0.0.1:8775/#/processing
- Kind: friction · Severity: low
- Steps: 1. Processing > Watched folders > Watch a folder, add a folder. 2. Press its Scan now at once.
- Expected: Scan now while the new folder's own first scan runs says it is already scanning, or is disabled until it finishes; no error.
- Actual: Error toast 'Wait for the current scan before scanning a watched folder.' stays on screen across pages for the rest of the session.
- Evidence: tests/.tmp/evidence/scan-now-after-watch-error.png

<!-- finding:c82c59a7eae2c950 -->
### #/documents/ID: one-amount note stays after entering the line's year to date
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude validate-feature paystub-columns
- Page: http://127.0.0.1:8775/#/documents/46
- Kind: bug · Severity: medium
- Steps: 1. Add a photographed pay stub printing DESCRIPTION CURRENT YTD and a one-amount line RELOCATION BONUS 5,000.00. 2. The model reads the bonus as this period; the stub needs review with 'This period: RELOCATION BONUS 5,000.00 USD: pay line 2 prints one amount; check whether it is this period or year to date'. 3. Correct RELOCATION BONUS: Year to date 5000.00, This period left empty, Save.
- Expected: Answering the note's question (it is year to date) clears the note; with no other notes the stub can be recorded.
- Actual: Year to date is saved (5,000.00 USD) but the note stays and the stub stays Needs review: the note starts with 'This period: RELOCATION BONUS', and a year-to-date correction only clears notes starting 'Year to date: RELOCATION BONUS'.
- Evidence: tests/.tmp/evidence/paystub-columns-bonus-note-stays.png

<!-- finding:1b2990d5f27113a7 -->
### #/documents/ID: pay line with no amounts recorded on a verified stub
- Date: 2026-10-19 (seed 2026-10-18)
- Agent: claude validate-feature paystub-columns
- Page: http://127.0.0.1:8775/#/documents/43
- Kind: bug · Severity: low
- Steps: 1. Add a photographed pay stub headed HARBOR TOOLS INC with REGULAR, FEDERAL INCOME TAX and 401K lines, each printing CURRENT and YTD. 2. The model also returns a pay line 'HARBOR TOOLS INC' (employer_paid) citing the employer name line, with no this-period or year-to-date amount. 3. Open the stub.
- Expected: A pay line with neither amount (citing a line that prints no amount) is left out or sends the stub to review.
- Actual: The stub is Recorded and verified, and the record lists 'Paid by your employer: HARBOR TOOLS INC' with no amounts.
- Evidence: tests/.tmp/evidence/paystub-amountless-employer-line.png

<!-- finding:da9edb71d92a200a -->
### #/documents/ID: statement Record fails: page-3 deposits read apart from their rows
- Date: 2026-10-25 (seed 2026-10-25)
- Agent: SL-08 manual run (claude)
- Page: http://127.0.0.1:8775/#/documents/31
- Kind: bug · Severity: medium
- Steps: 1. Add K.pdf (tests/pdf_import_fixtures.py k_pages) through the Scanner watched folder and let it be read. 2. Import it into First Local Bank checking 4821 (9 rows). 3. More actions > Record, then Try again twice (gemma-3-12b-it / openai/gpt-oss-20b).
- Expected: SC-12: a statement awaiting reconciliation; the 9 imported rows keep origin import, get linked and stay counted.
- Actual: All 3 attempts fail validation on transactions.6 and .8 (REFUND BOOKSTORE 19.99, INTEREST PAID 0.12): 'amount is not printed in its cited evidence' / 'citation is not an exact quote'. The Text tab shows page 3's Deposits amounts after the page footer, apart from their rows, so no single line holds both. Nothing published; ledger unchanged (9 counted). Import itself unaffected.
- Evidence: tests/.tmp/evidence/pdf-import-k-record-fails-page3.png

<!-- finding:8a5cd0d8b6033ddc -->
### #/documents/ID: badge says Couldn't process after a successful PDF import
- Date: 2026-10-25 (seed 2026-10-25)
- Agent: SL-08 manual run (claude)
- Page: http://127.0.0.1:8775/#/documents/31
- Kind: friction · Severity: low
- Steps: 1. Add K.pdf; the automatic Record fails validation. 2. Import transactions into First Local Bank checking 4821: 9 imported. 3. Reload K's page and its library row.
- Expected: The badge reads Imported (SC-20), as R.pdf's row does after its import.
- Actual: K's page and row still show 'Couldn't process' and 'Nothing is recorded from this document yet.'; the badge's title says 'Text: Done · Ledger: Imported'. Nothing on the page says 9 rows came from it.
- Evidence: tests/.tmp/evidence/pdf-import-k-badge-couldnt-process.png

<!-- finding:e93a1485730bf944 -->
### #/documents/ID: statement Record blocked: currency unresolved for an imported PDF's account
- Date: 2026-10-25 (seed 2026-10-25)
- Agent: SL-08 manual run (claude)
- Page: http://127.0.0.1:8775/#/documents/31
- Kind: bug · Severity: medium
- Steps: 1. K.pdf (prints FIRST LOCAL BANK, account ending 4821, no currency) imported into First Local Bank checking 4821 (USD). 2. Read again (rows now keep their amounts), then Record it, Try again, then set Settings > Home currency USD and Extract again.
- Expected: SC-12: Record uses the matched account's currency (USD) and leaves a statement awaiting reconciliation linked to the 9 imported rows.
- Actual: Run 1: validation failed (closing_balance, withdrawals_total not printed). Runs 2 and 3: 'Can't record this: Currency could not be resolved, so nothing was published.' Home currency can't help (it needs a printed symbol). Likely cause: Ledger.find_account matches institution with case-sensitive '=', so 'FIRST LOCAL BANK' never finds 'First Local Bank'. Ledger unchanged (12 charges, In 2,020.11 / Out 141.50).
- Evidence: tests/.tmp/evidence/pdf-import-k-record-currency-unresolved.png
