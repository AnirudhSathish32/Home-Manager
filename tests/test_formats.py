"""Format routing by extension only: content never chooses a reader."""

from pathlib import Path

import pytest

from home_manager.core.formats import IMAGES, SUPPORTED, TABLES, TEXT_READERS, extension, reader


@pytest.mark.parametrize(("name", "expected"), [
    ("receipt.png", "image"), ("RECEIPT.JPG", "image"), ("scan.JpEg", "image"),
    ("statement.pdf", "pdf"), ("Statement.PDF", "pdf"),
    ("export.csv", "csv"), ("Export.XLSX", "xlsx"),
    ("macro.xlsm", None), ("old.xls", None), ("notes.txt", None), ("archive.zip", None), ("no_extension", None), (".png", None),
])
def test_reader_is_chosen_by_extension(name, expected):
    assert reader(name) == expected
    assert reader(Path("Library") / "Inbox" / name) == expected


def test_only_the_last_suffix_counts():
    assert extension("receipt.pdf.png") == ".png" and reader("receipt.pdf.png") == "image"
    assert reader("statement.csv.exe") is None


def test_the_format_sets_agree():
    assert TEXT_READERS == IMAGES | {".pdf"}
    assert SUPPORTED == TEXT_READERS | TABLES
    assert not TEXT_READERS & TABLES  # Tables are imported deterministically, never sent to a model.
    assert all(suffix == suffix.lower() and suffix.startswith(".") for suffix in SUPPORTED)
