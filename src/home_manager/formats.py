"""Document format routing by extension. Content is never used to choose a reader."""

from pathlib import PurePath

IMAGES = {".png", ".jpg", ".jpeg"}
TEXT_READERS = IMAGES | {".pdf"}  # Transcription: embedded PDF text or local vision.
TABLES = {".csv", ".xlsx"}  # Deterministic transaction import; never sent to a model.
SUPPORTED = TEXT_READERS | TABLES


def extension(path) -> str:
    return PurePath(str(path)).suffix.lower()


def reader(path) -> str | None:
    suffix = extension(path)
    if suffix in IMAGES:
        return "image"
    return suffix[1:] if suffix in SUPPORTED else None
