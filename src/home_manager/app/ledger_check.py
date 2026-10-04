"""`home-manager check-ledger`: the ledger health report for each profile's library, printed for the user to read or share.

Opens each database read-only (no lock, no upgrade), so it can run while the app is open. The report names rules and
record ids only; it prints no amounts, names or document text. It starts with whether each tax engine can run here.
"""

import argparse
from pathlib import Path
import sqlite3

from ..finance.health import SEVERITIES, check_ledger, summary
from ..library.storage import MIGRATIONS
from .manager import default_control_dir
from .profiles import Profiles

SHOW_IDS = 20  # Record ids listed per rule; the count is always complete.


def open_read_only(database: Path):
    """A read-only connection. With no write-ahead log beside it, immutable=1 also avoids creating one."""
    wal = database.with_name(database.name + "-wal")
    db = sqlite3.connect(database.as_uri() + ("?mode=ro" if wal.exists() else "?mode=ro&immutable=1"), uri=True)
    db.row_factory = sqlite3.Row
    return db


def libraries(control: Path, chosen: Path | None):
    """(label, database path) for the chosen library folder, or for every individual profile."""
    if chosen:
        return [(str(chosen), chosen / "inventory.sqlite3")]
    profiles = [item for item in Profiles(control).all() if item.get("kind") == "individual"]
    return [(f"Profile {index}: {item.get('name', '')}", Path(item["folder"]) / "inventory.sqlite3") for index, item in enumerate(profiles, 1)]


def report(label, database: Path):
    lines = [label]
    if not database.is_file():
        return lines + ["  No library database here yet."]
    db = open_read_only(database)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != MIGRATIONS[-1][0]:
            return lines + [f"  Library is at version {version}; this Home Manager expects {MIGRATIONS[-1][0]}. Open the app once, then check again."]
        problems = check_ledger(db)
    finally:
        db.close()
    counts = summary(problems)
    lines.append("  " + ", ".join(f"{counts[severity]} {severity}" for severity in SEVERITIES))
    for code, count in counts["by_rule"].items():
        found = [item for item in problems if item.code == code]
        ids = ", ".join(f"{item.record_type} {item.record_id}" for item in found[:SHOW_IDS]) + (" ..." if count > SHOW_IDS else "")
        lines += [f"  [{found[0].severity}] {code} x{count}: {found[0].detail}", f"    {ids}"]
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog="home-manager check-ledger", description="Check each profile's ledger for broken money rules. Read-only.")
    parser.add_argument("--control-dir", type=Path, help="Settings location; default is %%LOCALAPPDATA%%/HomeManager on Windows.")
    parser.add_argument("--library", type=Path, help="Check this library folder instead of the profiles'.")
    args = parser.parse_args(argv)
    found = libraries(args.control_dir or default_control_dir(), args.library)
    if not found:
        print("No profiles with a library were found. Pass --library to check a folder.")
        return 1
    from ..finance import tax_engine
    print("\n".join(["Tax engines"] + [f"  {item['note']}" for item in (tax_engine.readiness(slot) for slot in tax_engine.ENGINES)]) + "\n")
    failed = False
    for label, database in found:
        lines = report(label, database)
        failed |= any("[error]" in line for line in lines)
        print("\n".join(lines) + "\n")
    return 1 if failed else 0
