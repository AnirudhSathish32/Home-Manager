"""UI-plan backend dependencies (docs/ui-design-plan.md §7, B1-B16)."""

import json
import socket

from fastapi.testclient import TestClient
import pytest

from home_manager.api import create_app
from home_manager.assistant import AssistantService
from home_manager.backup import BackupService, restore_backup, verify_backup
from home_manager.finance_tools import AsOfInput, CompareInput, FinanceTools, PeriodInput, SeriesInput, TransactionsInput, call_tool
from home_manager.jobs import Work
from home_manager.model_client import check_connection
from home_manager.paths import PathError, separate_folder
from home_manager.reasoning import ReasoningConfig
from home_manager.reconcile import Reconciler
from home_manager.scanner import ScanLimits
from home_manager.storage import Store
from test_reconcile_tools import add, books, receipt, source_of  # noqa: F401  (books is a fixture)


@pytest.fixture
def reconciled(books):
    """Two accounts, a matched receipt, an ambiguous one, a transfer and a card payment."""
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    card = ledger.create_account("Fidelity", "credit_card", "USD", last_four="7314")
    bank = add(store, ledger, checking, docs["export.csv"], [("2026-08-03", "GROCER", -4000), ("2026-09-20", "ONLINE PAYMENT TO CREDIT CARD 7314", -50000)])
    cards = add(store, ledger, card, docs["export.csv"], [("2026-09-15", "COSTCO WHSE #1234", -16382), ("2026-09-18", "CAFE ONE", -1200),
                                                          ("2026-09-18", "BOOKSHOP TWO", -1200), ("2026-09-21", "PAYMENT - THANK YOU", 50000)])
    costco = receipt(ledger, docs["receipt.png"], "Costco Wholesale", "2026-09-15", 16382)
    corner = receipt(ledger, docs["bill.png"], "Corner Market", "2026-09-18", 1200)
    reconciler = Reconciler(store)
    reconciler.run("import")
    return store, ledger, docs, reconciler, {"bank": bank, "card": cards, "costco": costco, "corner": corner, "checking": checking}


def test_review_queue_carries_summaries_of_every_record_involved(reconciled):  # B1
    store, _, docs, _, ids = reconciled
    queue = FinanceTools(store).review_queue()
    costco = next(item for item in queue["records"] if item["id"] == ids["costco"])
    assert costco["summary"]["name"] == "Costco Wholesale" and costco["summary"]["amount"]["display"] == "163.82 USD"
    assert costco["summary"]["document_path"].endswith("receipt.png")
    link = next(item for item in queue["links"] if item["kind"] == "receipt")
    assert link["match_signals"] == ["amount", "same_day", "merchant"]
    assert link["from"]["account"] == "Fidelity credit card 7314" and link["to"]["name"] == "Costco Wholesale"
    transfer = next(item for item in queue["links"] if item["kind"] == "transfer")
    assert transfer["from"]["id"] == ids["bank"][1] and transfer["to"]["id"] == ids["card"][3]
    [issue] = queue["issues"]
    assert issue["record"]["name"] == "Corner Market" and "detail_json" not in issue
    assert sorted(candidate["description"] for candidate in issue["candidates"]) == ["BOOKSHOP TWO", "CAFE ONE"]


def test_transaction_filters_sort_paging_and_receipt_linkage(reconciled):  # B2
    store, _, _, _, ids = reconciled
    tools = FinanceTools(store)
    everything = tools.get_transactions(TransactionsInput())
    assert everything["total_matching"] == 6 and [row["posted_date"] for row in everything["transactions"]][:2] == ["2026-09-21", "2026-09-20"]
    page = tools.get_transactions(TransactionsInput(sort="amount_asc", limit=2, offset=1))
    assert [row["amount_minor"] for row in page["transactions"]] == [-16382, -4000] and page["total_matching"] == 6
    linked = tools.get_transactions(TransactionsInput(has_receipt=True))["transactions"]
    assert [(row["id"], row["receipt_id"]) for row in linked] == [(ids["card"][0], ids["costco"])]
    assert tools.get_transactions(TransactionsInput(has_receipt=False))["total_matching"] == 5
    # Words match the description or the merchant name taken from a linked receipt.
    assert [row["id"] for row in tools.get_transactions(TransactionsInput(query="wholesale"))["transactions"]] == [ids["card"][0]]
    assert tools.get_transactions(TransactionsInput(transaction_types=["payment"]))["total_matching"] == 2
    store_ledger = FinanceTools(store).ledger
    store_ledger.set_category(ids["card"][1], "Dining Out")
    assert [row["id"] for row in tools.get_transactions(TransactionsInput(category="dining out"))["transactions"]] == [ids["card"][1]]
    assert tools.get_transactions(TransactionsInput(category="uncategorized"))["total_matching"] == 5
    store_ledger.review("transaction", ids["bank"][0], "rejected")
    assert tools.get_transactions(TransactionsInput(statuses=["rejected"]))["total_matching"] == 1
    assert tools.get_transactions(TransactionsInput())["total_matching"] == 5
    with pytest.raises(ValueError):
        call_tool(tools, "get_transactions", {"sort": "random"})


def test_transaction_record_includes_account_and_links(reconciled):  # B3
    _, ledger, _, _, ids = reconciled
    record = ledger.record("transaction", ids["card"][0])
    assert record["account"] == "Fidelity credit card 7314"
    [link] = record["links"]
    assert link["kind"] == "receipt" and link["counterpart"]["id"] == ids["costco"] and link["counterpart"]["amount"]["display"] == "163.82 USD"
    payment = ledger.record("transaction", ids["card"][3])
    assert [(item["kind"], item["counterpart"]["id"]) for item in payment["links"]] == [("transfer", ids["bank"][1])]
    assert [item["counterpart"]["id"] for item in ledger.record("receipt", ids["costco"])["links"]] == [ids["card"][0]]


def test_monthly_series_and_category_comparison_are_exact(reconciled):  # B4, B5
    store, ledger, _, _, ids = reconciled
    tools = FinanceTools(store)
    series = tools.spending_series(SeriesInput(start_month="2026-07", end_month="2026-09"))
    assert [month["month"] for month in series["months"]] == ["2026-07", "2026-08", "2026-09"]
    assert series["months"][0]["by_currency"] == []
    assert series["months"][1]["by_currency"][0]["net_spending"]["display"] == "40.00 USD"
    assert series["months"][2]["by_currency"][0]["net_spending"]["display"] == "187.82 USD"  # Transfers and card payments excluded.
    with pytest.raises(ValueError):
        SeriesInput(start_month="2023-01", end_month="2026-09")
    ledger.set_category(ids["bank"][0], "groceries")
    ledger.set_category(ids["card"][0], "groceries")
    comparison = tools.compare_categories(CompareInput(first={"start": "2026-08-01", "end": "2026-08-31"}, second={"start": "2026-09-01", "end": "2026-09-30"}))
    groceries = next(row for row in comparison["categories"] if row["category"] == "groceries")
    assert (groceries["first"]["display"], groceries["second"]["display"], groceries["change"]["display"], groceries["percent_change"]) == \
        ("40.00 USD", "163.82 USD", "123.82 USD", "309.6")
    new = next(row for row in comparison["categories"] if row["category"] == "uncategorized")
    assert new["first"]["minor"] == 0 and new["percent_change"] is None


def test_user_bill_payment_state_wins_and_is_audited(books):  # B6
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    [autopay] = add(store, ledger, checking, docs["export.csv"], [("2026-09-28", "CITY POWER AUTOPAY", -12000)])
    bill = ledger.publish_bill({"provider": "City Power", "issue_date": "2026-09-10", "due_date": "2026-09-20", "period_start": None, "period_end": None,
                                "amount_due_minor": 12000, "currency": "USD", "issues": [], "locator": {}}, source_of(docs["bill.png"], "extraction:bill"), "proposed")["id"]
    tools = FinanceTools(store)
    assert tools.get_upcoming_bills(AsOfInput(as_of="2026-09-24"))["bills"][0]["payment_state"] == "past_due_no_payment_found"
    with pytest.raises(ValueError, match="not found"):
        ledger.set_bill_payment(bill, "paid", transaction_id=999)
    with pytest.raises(ValueError, match="Only a paid bill"):
        ledger.set_bill_payment(bill, "unpaid", transaction_id=autopay)
    ledger.set_bill_payment(bill, "paid", transaction_id=autopay)
    assert tools.get_upcoming_bills(AsOfInput(as_of="2026-09-24"))["bills"] == []  # Paid and past due: nothing to show.
    ledger.set_bill_payment(bill, "unpaid")
    [shown] = tools.get_upcoming_bills(AsOfInput(as_of="2026-09-24"))["bills"]
    assert (shown["payment_state"], shown["payment_source"]) == ("past_due_unpaid", "user")
    assert [(event["previous_status"], event["new_status"]) for event in ledger.review_history("bill_payment", bill)] == [("unknown", "paid"), ("paid", "unpaid")]
    with store.connection() as db:
        assert db.execute("SELECT reconciliation_status FROM (" + store.library_query() + "SELECT * FROM library) WHERE id=?",
                          (docs["bill.png"]["id"],)).fetchone()[0] == "unmatched"  # B9: the bill's state reaches its document.


def test_recurring_review_is_audited_and_never_reproposed_after_rejection(books):  # B6
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["export.csv"], [(f"2026-0{month}-05", "NETFLIX.COM", -1549) for month in (6, 7, 8, 9)])
    reconciler = Reconciler(store)
    reconciler.run()
    [obligation] = FinanceTools(store).get_recurring_obligations()["obligations"]
    with pytest.raises(ValueError):
        reconciler.review_obligation(obligation["id"], "proposed")
    reconciler.review_obligation(obligation["id"], "rejected", "Cancelled last month.")
    reconciler.run()
    assert FinanceTools(store).get_recurring_obligations()["obligations"] == []
    assert ledger.review_history("recurring_obligation", obligation["id"])[0]["note"] == "Cancelled last month."


def test_resolving_ambiguous_matches_and_reconciliation_history(reconciled):  # B15, B10, B9
    store, ledger, docs, reconciler, ids = reconciled
    [issue] = FinanceTools(store).review_queue()["issues"]
    with pytest.raises(ValueError, match="listed"):
        reconciler.resolve_issue(issue["id"], ids["card"][0])
    reconciler.resolve_issue(issue["id"], ids["card"][1])
    with pytest.raises(ValueError, match="already answered"):
        reconciler.resolve_issue(issue["id"], None)
    link = ledger.record("receipt", ids["corner"])["links"][0]
    assert (link["counterpart"]["id"], link["review_status"], link["match_signals"][-1]) == (ids["card"][1], "verified", "user_choice")
    summary = reconciler.run("manual")
    assert summary["open_issues"] == 0 and summary["receipt_links"] == 0
    history = reconciler.history()
    assert [(run["trigger"], run["status"], run["open_issues"]) for run in history] == [("manual", "succeeded", 0), ("import", "succeeded", 1)]
    with store.connection() as db:
        states = dict(db.execute(store.library_query() + "SELECT relative_path,reconciliation_status FROM library").fetchall())
    assert states["receipt.png"] == "proposed" and states["bill.png"] == "matched" and states["export.csv"] is None


def test_leaving_a_record_unmatched_is_respected_by_later_passes(reconciled):  # B15
    store, _, _, reconciler, ids = reconciled
    [issue] = FinanceTools(store).review_queue()["issues"]
    assert reconciler.resolve_issue(issue["id"], None)["resolution"] == "left_unmatched"
    reconciler.run()
    assert FinanceTools(store).review_queue()["issues"] == []


def test_job_history_unifies_scans_reconciliation_and_backups(tmp_path, reconciled):  # B11
    store, *_ = reconciled
    history = store.job_history()
    assert {item["kind"] for item in history} == {"inbox_capture", "reconciliation"}
    assert all(set(item) == {"kind", "id", "status", "started_at", "finished_at", "document_id", "error"} for item in history)
    assert [item["kind"] for item in store.job_history(kinds=["reconciliation"])] == ["reconciliation"]
    with pytest.raises(ValueError):
        store.job_history(kinds=["DROP TABLE"])


def test_connection_check_lists_models_without_sending_content(local_model):  # B12
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    result = check_connection(config)
    assert result["reachable"] and result["model_listed"] and "synthetic-vision" in result["available_models"] and result["problem"] is None
    assert local_model["requests"] == []  # Only GET /v1/models; no completion was requested.
    assert "does not list" in check_connection(ReasoningConfig(base_url=config.base_url, model="missing"))["problem"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed = sock.getsockname()[1]
    assert check_connection(ReasoningConfig(base_url=f"http://127.0.0.1:{closed}/v1", model="x"))["reachable"] is False


def test_backup_is_complete_verified_and_restores_into_a_new_library(tmp_path):  # B13
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager = app.state.manager
        (manager.store.library.inbox / "export.csv").write_text("date,amount\n2026-09-01,10.00\n")
        (manager.store.library.inbox / "dropped.csv").write_text("date,amount\n2026-09-02,5.00\n")
        client.post("/api/inbox-scans", json={}); manager.future.result(timeout=30)
        assert client.get("/api/documents").json()["total"] == 2
        # Backups never go inside the library or the application's folders.
        for inside in (tmp_path / "managed" / "Library", tmp_path / "control"):
            assert client.post("/api/backups", json={"destination": str(inside)}).status_code == 400
        destination = tmp_path / "backups"
        destination.mkdir()
        backup_id = client.post("/api/backups", json={"destination": str(destination)}).json()["backup_id"]
        manager.future.result(timeout=30)
        [record] = client.get("/api/backups").json()
        assert record["id"] == backup_id and record["status"] == "succeeded" and record["file_count"] >= 4
        [folder] = destination.iterdir()
        assert not folder.name.endswith(".partial")
        manifest, problems = verify_backup(folder)
        assert problems == [] and {entry["kind"] for entry in manifest["files"]} == {"database", "original", "library"}
        assert any(item["kind"] == "backup" for item in client.get("/api/jobs").json())
        restore_id = client.post("/api/restores", json={"backup": str(folder), "target": str(tmp_path / "restored")}).json()["restore_id"]
        manager.future.result(timeout=30)
        restored = client.get(f"/api/restores/{restore_id}").json()
        assert restored["status"] == "succeeded", restored
        assert client.get("/api/documents").json()["total"] == 2  # The open library is untouched.
    # The restored library opens, and Inbox documents follow it to its new location.
    store = Store(tmp_path / "restored")
    try:
        assert store.documents()["total"] == 2
        with store.connection() as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        store.close()


def test_restore_refuses_tampered_backups_and_non_empty_targets(tmp_path):  # B13
    store = Store(tmp_path / "managed")
    try:
        service = BackupService(store)
        destination = tmp_path / "backups"
        destination.mkdir()
        service.run(service.begin(destination), destination, Work.detached())
    finally:
        store.close()
    [folder] = destination.iterdir()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("user file")
    with pytest.raises(PathError):
        restore_backup(folder, occupied)
    assert (occupied / "keep.txt").read_text() == "user file"
    database = folder / "inventory.sqlite3"
    database.write_bytes(database.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="did not verify"):
        restore_backup(folder, tmp_path / "fresh")
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["files"].append({"path": "../outside.txt", "size": 0, "sha256": "0" * 64, "kind": "library"})
    (folder / "manifest.json").write_text(json.dumps(manifest))
    assert verify_backup(folder)[0] is None
    with pytest.raises(PathError):
        separate_folder(str(tmp_path / "managed" / "x"), tmp_path / "control", (tmp_path / "managed",))


def test_assistant_answers_from_tool_results_and_flags_unsupported_figures(reconciled, local_model):  # B16
    store, *_ = reconciled
    service = AssistantService(store, FinanceTools(store))
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    step = lambda **fields: {"action": "call_tool", "tool": None, "arguments_json": None, "answer": None, "cited_calls": [], "missing_evidence": [], **fields}  # noqa: E731
    local_model["outputs"] = [
        step(tool="get_spending", arguments_json=json.dumps({"start": "2026-09-01", "end": "2026-09-30"})),
        step(tool="get_spending", arguments_json="{\"start\": \"not a date\"}"),
        step(action="answer", answer="You spent $187.82 in September, about 12.50 more than usual.", cited_calls=[1, 2, 9])]
    run_id = service.enqueue("How much did I spend in September?", config)
    service.run(run_id, config, Work("inference", "assistant", "Answering a question", sink=store.record_model_run))  # As the queue runs it.
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    result = run["result"]
    assert result["cited_calls"] == [1]  # The failed call and a call that never happened are not citations.
    assert "Invalid call" in result["tool_calls"][1]["error"]
    assert result["unverified_figures"] == ["12.50"] and result["verified"] is False
    requests = local_model["requests"]
    assert len(requests) == 3 and "not instructions" in requests[1]["messages"][-1]["content"]
    assert run["model_runs"] and all(item["task"] == "assistant" for item in run["model_runs"])
    with pytest.raises(ValueError, match="reasoning model"):
        service.enqueue("Anything?", ReasoningConfig())


def test_new_endpoints_are_typed_and_wired(tmp_path, local_model):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        test = client.post("/api/model-connection-tests", json={"base_url": local_model["config"].base_url, "model": "synthetic-reasoning"}).json()
        assert test["model_listed"] is True
        assert client.post("/api/model-connection-tests", json={"base_url": "http://example.com/v1", "model": "x"}).status_code == 422
        assert client.post("/api/finance/issues/1/resolve", json={}).status_code == 422
        assert client.post("/api/finance/issues/1/resolve", json={"transaction_id": None}).status_code == 400
        assert client.post("/api/finance/bills/1/payment", json={"status": "settled"}).status_code == 422
        assert client.post("/api/finance/recurring/1/review", json={"status": "verified"}).status_code == 400
        assert client.post("/api/finance/reconcile").status_code == 200
        assert client.get("/api/finance/reconciliation-runs").json()[0]["trigger"] == "manual"
        assert client.post("/api/finance/tools/spending_series", json={"start_month": "2026-01", "end_month": "2026-03"}).status_code == 200
        assert client.post("/api/assistant-runs", json={"question": "Spending?"}).status_code == 400  # No reasoning model configured.
        client.put("/api/reasoning-settings", json={"base_url": local_model["config"].base_url, "model": "synthetic-reasoning"})
        local_model["output"] = {"action": "answer", "tool": None, "arguments_json": None, "answer": "No data yet.", "cited_calls": [], "missing_evidence": ["transactions"]}
        run_id = client.post("/api/assistant-runs", json={"question": "Spending?"}).json()["run_id"]
        app.state.manager.future.result(timeout=30)
        assert client.get(f"/api/assistant-runs/{run_id}").json()["result"]["verified"] is True
        assert client.get("/api/assistant-runs").json()[0]["id"] == run_id
        assert client.get("/api/restores/unknown").status_code == 400


def test_transactions_link_their_receipts_and_unmatched_receipts_are_listed_not_counted(reconciled):
    store, ledger, docs, _, ids = reconciled
    tools = FinanceTools(store)
    rows = {row["id"]: row for row in tools.get_transactions(TransactionsInput())["transactions"]}
    costco = rows[ids["card"][0]]
    assert (costco["receipt_id"], costco["receipt_link_status"], costco["receipt_document_id"]) == (ids["costco"], "proposed", docs["receipt.png"]["id"])
    assert rows[ids["card"][1]]["receipt_document_id"] is None
    undated = receipt(ledger, docs["return.png"], "Corner Market", None, 999)
    result = call_tool(tools, "get_unmatched_receipts", {"start": "2026-09-01", "end": "2026-09-30"})
    # The matched Costco receipt is not listed; the ambiguous one is, with why; undated receipts are listed apart.
    assert [(item["id"], item["reason"]) for item in result["receipts"]] == [(ids["corner"], "several_possible_charges")]
    assert result["receipts"][0]["issue_id"] is not None and result["receipts"][0]["document_path"].endswith("bill.png")
    assert [item["id"] for item in result["undated"]] == [undated]
    assert [(row["currency"], row["total"]["display"], row["receipts"]) for row in result["by_currency"]] == [("USD", "12.00 USD", 1)]
    # Not counted: spending comes from transactions only.
    before = tools.get_spending(PeriodInput(start="2026-09-01", end="2026-09-30"))["by_currency"]
    assert before[0]["net_spending"]["display"] == "187.82 USD"
    [issue] = tools.review_queue()["issues"]
    Reconciler(store).resolve_issue(issue["id"], ids["card"][1])
    assert call_tool(tools, "get_unmatched_receipts", {"start": "2026-09-01", "end": "2026-09-30"})["receipts"] == []
