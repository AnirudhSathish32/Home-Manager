"""The app's diagnostic log: <control>/logs/home-manager.log, rotated at 1 MB with five old files kept.

Privacy rule: log what happened and where, never what a document says. Entries carry event names, record and
run ids, counts, exception class names and code tracebacks. Never exception messages (they can quote document
text), amounts, merchant names or file names.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import traceback

from .paths import safe_path

LOG_FILE = "home-manager.log"
MAX_BYTES = 1_000_000
BACKUPS = 5
# Our own loggers and Python warnings. Other libraries stay out: their messages may quote data.
LOGGERS = ("home_manager", "py.warnings")
# The web server's errors. Uvicorn resets its loggers as it starts, so attach_server() runs once the app is starting.
SERVER_LOGGER = "uvicorn.error"
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_handler: logging.Handler | None = None


class PrivateFormatter(logging.Formatter):
    """Tracebacks from any logger (including the web server's) keep the exception class and code frames, never the message."""

    def formatException(self, ei):
        kind, _, tb = ei
        name = kind.__name__ if kind else "Exception"
        return f"{name} (message omitted)\n" + "".join(traceback.format_tb(tb)).rstrip()


def configure(control: Path) -> Path:
    """Send the app's loggers to the rotating log file under control. Safe to call again (replaces the handler)."""
    global _handler
    folder = safe_path(control / "logs")
    folder.mkdir(parents=True, exist_ok=True)
    path = safe_path(folder / LOG_FILE)
    handler = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8", delay=True)
    handler.setFormatter(PrivateFormatter(FORMAT))
    logging.captureWarnings(True)
    for name in (*LOGGERS, SERVER_LOGGER):
        logger = logging.getLogger(name)
        if _handler in logger.handlers:
            logger.removeHandler(_handler)
    if _handler is not None:
        _handler.close()
    _handler = handler
    for name in LOGGERS:
        logging.getLogger(name).addHandler(handler)
        logging.getLogger(name).setLevel(logging.INFO)
    attach_server()
    return path


def attach_server() -> None:
    """Also log the web server's errors, once configure() has run. Does nothing otherwise, or if already attached."""
    logger = logging.getLogger(SERVER_LOGGER)
    if _handler is not None and _handler not in logger.handlers:
        logger.addHandler(_handler)


def describe(ids) -> str:
    return "".join(f" {key}={value}" for key, value in ids.items() if value is not None)


def log_failure(logger: logging.Logger, event: str, exc: BaseException, **ids) -> None:
    """Record a failure by class and code traceback only. The exception's message is left out on purpose."""
    causes: list[str] = []
    cause = exc.__cause__ or exc.__context__
    while cause is not None and len(causes) < 5:
        causes.append(type(cause).__name__)
        cause = cause.__cause__ or cause.__context__
    chain = f" (from {' <- '.join(causes)})" if causes else ""
    frames = "".join(traceback.format_tb(exc.__traceback__)).rstrip()
    logger.error("%s failed: %s%s%s\n%s", event, type(exc).__name__, chain, describe(ids), frames)
