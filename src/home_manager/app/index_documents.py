"""`home-manager index-documents`: build the full-text index of each profile's documents (docs/documents.md "Searching document text").

The app does this by itself at start for readings not yet indexed; this command is for a full rebuild. It opens each
library as the app does (taking its lock), so close Home Manager first. It prints counts only, never document text.
"""

import argparse
from pathlib import Path

from ..core.paths import PathError
from ..library import text_index
from ..library.storage import Store
from .ledger_check import libraries
from .manager import default_control_dir


def main(argv=None):
    parser = argparse.ArgumentParser(prog="home-manager index-documents", description="Index the text of each profile's documents for search.")
    parser.add_argument("--control-dir", type=Path, help="Settings location; default is %%LOCALAPPDATA%%/HomeManager on Windows.")
    parser.add_argument("--library", type=Path, help="Index this library folder instead of the profiles'.")
    parser.add_argument("--rebuild", action="store_true", help="Discard the index and build it again from every saved reading.")
    args = parser.parse_args(argv)
    found = libraries(args.control_dir or default_control_dir(), args.library)
    if not found:
        print("No profiles with a library were found. Pass --library to index a folder.")
        return 1
    failed = False
    for label, database in found:
        if not database.is_file():
            print(f"{label}\n  No library database here yet.\n")
            continue
        try:
            store = Store(database.parent)
        except (PathError, OSError) as exc:
            print(f"{label}\n  Could not open the library ({exc}). Close Home Manager and try again.\n")
            failed = True
            continue
        try:
            print(f"{label}\n  Indexed {text_index.backfill(store, rebuild=args.rebuild)} readings.\n")
        finally:
            store.close()
    return 1 if failed else 0
