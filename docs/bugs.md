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