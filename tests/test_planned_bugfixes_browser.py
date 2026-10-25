"""Planned bug fixes through the browser, against a synthetic local household."""
import json

import pytest

from conftest import inbox_scan
from home_manager.documents.reasoning import ReasoningConfig
from seed_documents import document_server
from test_document_v2_browser import open_document
from test_planned_bugfixes import bill_reading, income
from test_receipts import make_receipt
from test_ui_parity import browser_test

TOKEN = 'planned-bugfix-test'


@browser_test
def test_receipt_money_item_price_undo_and_pay_period(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    expect = playwright.expect
    with document_server(tmp_path, TOKEN) as (base, ids, manager), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        failures = []
        page.on('pageerror', lambda error: failures.append(str(error)))
        page.goto(f'{base}/#token={TOKEN}')
        open_document(page, base, ids['receipt_doc'])
        expect(page.locator('.ledger-rows tfoot')).to_contain_text('Tax')
        expect(page.locator('.ledger-rows tbody')).to_contain_text('with tax')
        page.locator('.doc2-fields').get_by_role('button', name='Correct tax', exact=True).click()
        form = page.locator('#doc2-decision .cc-form')
        expect(form.get_by_label('Tax', exact=True)).to_be_focused()
        form.get_by_label('Tax', exact=True).fill('3.00')
        form.get_by_role('button', name='Save', exact=True).click()
        expect(page.locator('.ledger-rows tfoot')).to_contain_text('3.00 USD')
        expect(page.locator('.item-warning', has_text="Doesn't add up")).to_be_visible()
        # A receipt's row Correct shows only once the record's Correct is open.
        expect(page.get_by_role('button', name='Correct EGGS', exact=True)).to_be_hidden()
        page.locator('#doc2-decision').get_by_role('button', name='Correct…', exact=True).click()
        page.get_by_role('button', name='Correct EGGS', exact=True).click()
        row_form = page.locator('.doc2-row-form .cc-form')
        row_form.get_by_label('Price', exact=True).fill('19.00')
        row_form.get_by_role('button', name='Save', exact=True).click()
        expect(page.locator('.ledger-rows tbody tr').first).to_contain_text('19.00 USD')
        page.locator('.toast').last.get_by_role('button', name='Undo', exact=True).click()
        expect(page.locator('.ledger-rows tbody tr').first).to_contain_text('18.00 USD')
        # A synthetic paystub publication, so both range endpoints use the same real correction API.
        doc = manager.store.document(ids['receipt_doc'])
        rid = income(manager.ledger, doc)
        with manager.store.connection() as db:
            db.execute("UPDATE extraction_runs SET document_type='paystub',publication_json=? WHERE document_id=?",
                       (json.dumps({'record_type': 'income_record', 'id': rid, 'status': 'published'}), doc['id']))
        page.reload()
        page.get_by_role('button', name='Correct period end', exact=True).click()
        form = page.locator('#doc2-decision .cc-form')
        expect(form.get_by_label('Period end', exact=True)).to_be_focused()
        form.get_by_label('Period start', exact=True).fill('2026-09-16')
        form.get_by_label('Period end', exact=True).fill('2026-09-30')
        form.get_by_role('button', name='Save', exact=True).click()
        expect(page.locator('.doc2-fields')).to_contain_text('Sep 16, 2026 to Sep 30, 2026')
        assert failures == []
        browser.close()


@browser_test
def test_idle_badge_read_filter_and_record_selected(tmp_path, local_model):
    playwright = pytest.importorskip('playwright.sync_api')
    expect = playwright.expect
    with document_server(tmp_path, TOKEN) as (base, ids, manager), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        failures = []
        page.on('pageerror', lambda error: failures.append(str(error)))
        page.goto(f'{base}/#token={TOKEN}')
        page.goto(f'{base}/#/documents?folder=Inbox&status=needs_text')
        expect(page.locator('#rc2-table tbody tr')).to_have_count(1)
        badge = page.locator('#nav-inbox .nav-count')
        expect(badge).to_have_text('1')
        make_receipt(manager.store.library.inbox / 'second-bill.png', ['CITY BILL', 'Amount due 25.00'])
        inbox_scan(manager.store)  # Completes while no model/capture busy flag is visible to the poll.
        expect(badge).to_have_text('2', timeout=10000)
        expect(page.locator('#rc2-table tbody tr')).to_have_count(2)
        manager.configure_vision(local_model['config'])
        manager.configure_reasoning(ReasoningConfig(base_url=local_model['config'].base_url, model='synthetic-reasoning'))
        local_model['outputs'] = [{'full_text': 'CORNER CAFE\nAmount due USD 4.50'}]
        page.get_by_role('button', name='Read unread.png', exact=True).click()
        row = page.locator('#rc2-table tbody tr', has=page.get_by_role('link', name='unread.png', exact=True))
        expect(row.get_by_role('button', name='Record unread.png', exact=True)).to_be_visible(timeout=15000)
        expect(page.locator('.toast', has_text='ready to record and still in Inbox')).to_be_visible()
        assert manager.store.document(ids['unread_doc'])['folder'] == 'Inbox'
        page.locator('#rc2-refresh').click()
        expect(page.locator('#rc2-table tbody tr')).to_have_count(1)
        page.goto(f'{base}/#/documents?folder=Inbox')
        expect(page.locator('#rc2-table tbody tr')).to_have_count(2)
        # Both are bills (docs/money.md "Bills and their lines"): recorded, filed to Bills, and waiting for review (no new charges printed).
        local_model['outputs'] = [{'full_text': 'CITY BILL\nAmount due USD 25.00'}, *bill_reading('CORNER CAFE', '4.50'), *bill_reading('CITY BILL', '25.00')]
        for checkbox in page.locator('#rc2-table tbody input[type=checkbox]').all():
            checkbox.check()
        with page.expect_request(lambda req: req.method == 'POST' and req.url.endswith('/api/receipt-batches')) as sent:
            page.locator('#rc2-selection').get_by_role('button', name='Record', exact=True).click()
        assert sent.value.post_data_json['record'] is True and len(sent.value.post_data_json['document_ids']) == 2
        expect(page.locator('#rc2-table tbody tr')).to_have_count(0, timeout=20000)
        page.goto(f'{base}/#/documents?folder=Bills')
        expect(page.locator('#rc2-table tbody tr')).to_have_count(2)
        expect(page.locator('#rc2-table .status-badge[data-status="bill_doc"]')).to_have_count(2)
        expect(page.locator('#rc2-table .rc2-step')).to_have_count(0)
        assert failures == []
        browser.close()


@browser_test
def test_split_category_link_and_confirmation(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    expect = playwright.expect
    with document_server(tmp_path, TOKEN) as (base, ids, manager), playwright.sync_playwright() as driver:
        receipt = manager.ledger.record('receipt', ids['receipt_record'])
        account = manager.ledger.create_account('Example card', 'credit_card', 'USD')
        charge = manager.ledger.add_manual_transaction(account['id'], receipt['purchase_date'], 'Fresh Market', '52.00', 'out')
        manager.reconciler.run('manual')
        assert manager.ledger.record('transaction', charge['id'])['splits']
        browser = driver.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(f'{base}/#token={TOKEN}')
        page.goto(f'{base}/#/transactions?view=charges')
        row = page.locator('#tx2-table tbody tr', has_text='Fresh Market')
        row.get_by_role('button', name='Split by items', exact=True).click()
        expect(page.locator('#tx2-view-items')).to_have_attribute('aria-selected', 'true')
        page.locator('#tx2-view-charges').click()
        row.get_by_role('button', name='Fresh Market', exact=True).click()
        page.locator('#tx-drawer-category').fill('groceries')
        page.locator('#tx-drawer').get_by_role('button', name='Save category').click()
        expect(page.locator('#confirm-dialog')).to_be_visible()
        page.locator('#confirm-cancel').click()
        assert manager.ledger.record('transaction', charge['id'])['splits']
        page.locator('#tx-drawer').get_by_role('button', name='Save category').click()
        page.get_by_role('button', name='Use for whole charge', exact=True).click()
        expect(page.locator('#tx-drawer')).not_to_contain_text("Split by the receipt's items")
        assert manager.ledger.record('transaction', charge['id'])['category_source'] == 'user'
        browser.close()
