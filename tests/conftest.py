"""Synthetic local model server; never sends documents outside the test process."""

import os

import pytest

from home_manager.library.scanner import ScanLimits, Scanner
from model_server import start_model_server


def pytest_addoption(parser):
    parser.addoption("--browser", action="store_true", help="Also run the opt-in local browser tests (same as RUN_BROWSER_TESTS=1).")


def pytest_configure(config):
    # Set before collection: the browser tests' skip conditions read the variable when their modules are imported.
    if config.getoption("--browser"):
        os.environ["RUN_BROWSER_TESTS"] = "1"


def inbox_scan(store, files=None, **limits):
    """Put files directly in Library/Inbox, the only way documents enter a library, and capture them."""
    for name, data in (files or {}).items():
        (store.library.inbox / name).write_bytes(data)
    job = store.create_job()
    Scanner(store, ScanLimits(stability_seconds=0, **limits)).run(job)
    return job


def documents_by_name(store):
    return {doc["relative_path"]: doc for doc in store.documents()["items"]}


def assert_ledger_healthy(store):
    """No ledger rule at error level is broken (finance/health.py). Warnings and info may be expected mid-scenario."""
    from home_manager.finance.health import check_ledger
    with store.connection() as db:
        errors = [item for item in check_ledger(db) if item.severity == "error"]
    assert errors == []


@pytest.fixture
def local_model():
    state, stop = start_model_server()
    try:
        yield state
    finally:
        stop()
