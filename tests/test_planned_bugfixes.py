"""Planned October fixes, using only synthetic documents and local model responses."""
from conftest import inbox_scan
from home_manager.finance import family_corrections
from test_correction_preview import app_client, itemised_receipt  # noqa: F401
from test_extraction import MISSING, cite, extract, transcribe, value
from test_receipts import make_receipt
from test_reconcile_tools import source_of


def test_missing_receipt_money_splits_reread_and_undo(app_client):
    client, manager, docs = app_client
    ledger = manager.ledger
    rid = itemised_receipt(ledger, docs['receipt.png'])
    with manager.store.connection() as db:
        db.execute('UPDATE receipts SET total_minor=NULL WHERE id=?', (rid,))
    saved = client.patch(f'/api/finance/records/receipt/{rid}', json={'changes': {'tax': '2.00', 'total': '52.00'}})
    assert saved.status_code == 200, saved.text
    record = ledger.record('receipt', rid)
    assert record['tax_minor'] == 200 and record['total_minor'] == 5200
    assert sum(row['amount_minor'] for row in record['splits']) == 5200
    assert not record['totals_mismatch']
    itemised_receipt(ledger, docs['receipt.png'])
    assert ledger.record('receipt', rid)['tax_minor'] == 200
    undone = ledger.undo_corrections('receipt', rid, saved.json()['correction_ids'])
    assert undone['tax_minor'] is None and undone['total_minor'] is None
    assert client.patch(f'/api/finance/records/receipt/{rid}', json={'changes': {'tax': '-2'}}).status_code == 400


def test_return_amounts_and_item_price_survive_reread(app_client):
    client, manager, docs = app_client
    ledger = manager.ledger
    rid = itemised_receipt(ledger, docs['receipt.png'])
    ledger.correct('receipt', rid, {'direction': 'return'})
    ledger.correct('receipt', rid, {'subtotal': '60', 'tax': '2', 'tip': '1', 'total': '63'})
    saved = client.patch(f'/api/receipts/{rid}/items/1', json={'price': '50', 'reason': 'Printed price'})
    assert saved.status_code == 200, saved.text
    itemised_receipt(ledger, docs['receipt.png'])
    record = ledger.record('receipt', rid)
    assert [record[f + '_minor'] for f in ('subtotal', 'tax', 'tip', 'total')] == [-6000, -200, -100, -6300]
    assert record['items'][0]['line_total_minor'] == -5000
    assert sum(row['amount_minor'] for row in record['splits']) == -6300
    entry = next(row for row in ledger.history('receipt', rid) if row['field'] == 'price:1')
    assert entry['reason'] == 'Printed price' and entry['undoable']
    undone = ledger.undo_corrections('receipt', rid, saved.json()['correction_ids'])
    assert undone['items'][0]['line_total_minor'] == -4000
    assert client.patch(f'/api/receipts/{rid}/items/999', json={'price': '1'}).status_code == 400


def test_missing_total_remembers_return_direction_and_family_money_kind(app_client):
    _, manager, docs = app_client
    ledger = manager.ledger
    rid = itemised_receipt(ledger, docs['receipt.png'])
    ledger.correct('receipt', rid, {'direction': 'return', 'total': None})
    assert ledger.record('receipt', rid)['direction'] == 'return'
    ledger.correct('receipt', rid, {'tax': '2', 'total': '52'})
    assert ledger.record('receipt', rid)['total_minor'] == -5200
    with manager.store.connection() as db:
        assert family_corrections.current_text(db, 'receipt', rid, 'total') == '52.00'
        assert family_corrections.checked_value(db, 'receipt', rid, 'tax', '3') == '3.00'
        family_corrections.apply_to_view(db, 'receipt', rid, 'tax', '3.00')
        assert db.execute('SELECT tax_minor FROM receipts WHERE id=?', (rid,)).fetchone()[0] == -300


def test_undo_item_price_preserves_a_later_return_direction(app_client):
    _, manager, docs = app_client
    ledger = manager.ledger
    rid = itemised_receipt(ledger, docs['receipt.png'])
    saved = ledger.correct_item(rid, 1, '35')
    ledger.correct('receipt', rid, {'direction': 'return'})
    undone = ledger.undo_corrections('receipt', rid, saved['correction_ids'])
    assert undone['items'][0]['line_total_minor'] == -4000
    assert undone['direction'] == 'return' and undone['sale_label'] == 'Return'


def test_item_only_correction_reapplies_and_undo_missing(app_client):
    _, manager, docs = app_client
    ledger = manager.ledger
    rid = itemised_receipt(ledger, docs['receipt.png'])
    with manager.store.connection() as db:
        db.execute('UPDATE receipt_items SET line_total_minor=NULL WHERE receipt_id=? AND position=1', (rid,))
    saved = ledger.correct_item(rid, 1, '35')
    itemised_receipt(ledger, docs['receipt.png'])
    assert ledger.record('receipt', rid)['items'][0]['line_total_minor'] == 3500
    assert ledger.undo_corrections('receipt', rid, saved['correction_ids'])['items'][0]['line_total_minor'] is None
    assert sum(row['amount_minor'] for row in ledger.record('receipt', rid)['splits']) == 5000


def income(ledger, doc):
    return ledger.publish_income({'payer_or_employer': 'Example Employer', 'pay_date': '2026-09-30', 'period_start': None, 'period_end': None,
                                  'gross_pay_minor': 100000, 'net_pay_minor': 80000, 'taxes_minor': 20000, 'deductions_minor': 0,
                                  'currency': 'USD', 'issues': [], 'locator': {}}, source_of(doc, 'extraction:stub'), 'proposed')['id']


def test_both_pay_period_ends_reapply_and_undo(app_client):
    _, manager, docs = app_client
    rid = income(manager.ledger, docs['stub.png'])
    saved = manager.ledger.correct('income_record', rid, {'period_start': '2026-09-16', 'period_end': '2026-09-30'})
    income(manager.ledger, docs['stub.png'])
    record = manager.ledger.record('income_record', rid)
    assert (record['period_start'], record['period_end']) == ('2026-09-16', '2026-09-30')
    undone = manager.ledger.undo_corrections('income_record', rid, saved['correction_ids'])
    assert undone['period_start'] is None and undone['period_end'] is None


def test_fast_capture_and_filing_change_library_revision(app_client):
    client, manager, _ = app_client
    before = client.get('/api/settings').json()['library_version']
    inbox_scan(manager.store, {'fast.png': b'synthetic fast capture'})
    captured = client.get('/api/settings').json()['library_version']
    assert captured > before
    doc = next(row for row in manager.store.documents()['items'] if row['relative_path'] == 'fast.png')
    manager.store.library.file_classified(doc['id'], doc['current_hash'], 'bill', None, None, 'Synthetic bill')
    assert manager.store.document(doc['id'])['folder'] == 'Bills'
    assert client.get('/api/settings').json()['library_version'] > captured


def bill_reading(name, due):
    """Model answers for a one-line synthetic bill: its type, its summary (amount due only) and no lines."""
    header = {field: MISSING for field in ('account_reference', 'issue_date', 'due_date', 'period_start', 'period_end', 'new_charges')}
    return [{'document_type': 'bill', 'evidence': cite(1, name), 'issuer': MISSING, 'document_date': MISSING},
            {**header, 'provider': value(name, 1), 'amount_due': value(due, 2, f'Amount due USD {due}'), 'currency': value('USD', 2, 'USD')},
            {'line_items': []}]


def test_a_bill_is_recorded_filed_and_leaves_ready_filter(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, ['CITY BILL', 'Amount due USD 25.00'])
    local_model['outputs'] = bill_reading('CITY BILL', '25.00')
    try:
        run = extract(manager, doc, parse_id)
        assert run['status'] == 'succeeded', run['error']
        # A bill is a receipt (docs/money.md "Bills and their lines"); without new charges its amount due counts, with a note.
        assert (run['publication']['record_type'], run['publication']['document_kind'], run['publication']['review_status']) == ('receipt', 'bill', 'needs_review')
        filed = manager.store.document(doc['id'])
        assert (filed['folder'], filed['ledger_status'], filed['ledger_kind']) == ('Bills', 'needs_review', 'bill')
        assert not manager.store.documents(status='ready_for_ledger')['items']
    finally:
        manager.close()


def test_record_selected_reuses_readings_and_records_sequentially(tmp_path, local_model):
    manager, first, _ = transcribe(tmp_path, local_model, ['CITY BILL', 'Amount due USD 25.00'])
    try:
        make_receipt(manager.store.library.inbox / 'second.png', ['SECOND BILL', 'Amount due USD 30.00'])
        inbox_scan(manager.store)
        second = next(row for row in manager.store.documents()['items'] if row['relative_path'] == 'second.png')
        local_model['outputs'] = [{'full_text': 'SECOND BILL\nAmount due USD 30.00'}]
        manager.start_receipt_batch(document_ids=[first['id'], second['id']])
        manager.future.result(timeout=30)
        assert all(row['folder'] == 'Inbox' and row['ledger_status'] is None for row in manager.store.documents()['items'])
        local_model['outputs'] = bill_reading('CITY BILL', '25.00') + bill_reading('SECOND BILL', '30.00')
        batch = manager.start_receipt_batch(document_ids=[first['id'], second['id']], record=True)
        manager.future.result(timeout=30)
        assert manager.batches.get(batch['batch_id'])['reused'] == 2
        assert all(row['folder'] == 'Bills' and row['ledger_status'] == 'needs_review' for row in manager.store.documents()['items'])
    finally:
        manager.close()
