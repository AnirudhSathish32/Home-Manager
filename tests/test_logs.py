"""The diagnostic log: where it lives, that it rotates, and that it never records what an error said."""

import logging

import pytest

from home_manager.core import logs


@pytest.fixture
def log_file(tmp_path):
    path = logs.configure(tmp_path / "control")
    yield path
    for name in (*logs.LOGGERS, logs.SERVER_LOGGER):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if handler is logs._handler:
                logger.removeHandler(handler)
    logs._handler.close()
    logs._handler = None


def flush():
    logs._handler.flush()


def test_the_log_lives_under_the_control_folder(tmp_path, log_file):
    assert log_file == tmp_path / "control" / "logs" / "home-manager.log"
    logging.getLogger("home_manager.test").info("hello count=%d", 3)
    flush()
    assert "INFO home_manager.test: hello count=3" in log_file.read_text(encoding="utf-8")


# Built at run time: tracebacks quote source lines, so a literal in a raise statement would appear as code.
SECRET = "-".join(("SECRET", "TEXT"))


def test_failures_keep_the_class_and_code_but_not_the_message(log_file):
    def fails():
        raise ValueError(SECRET)

    try:
        try:
            fails()
        except ValueError as inner:
            raise RuntimeError(SECRET) from inner
    except RuntimeError as exc:
        logs.log_failure(logging.getLogger("home_manager.test"), "reading", exc, run="r1", skipped=None)
    flush()
    text = log_file.read_text(encoding="utf-8")
    assert "reading failed: RuntimeError (from ValueError) run=r1" in text
    assert "skipped" not in text
    assert "test_failures_keep_the_class_and_code_but_not_the_message" in text  # The code frames are kept.
    assert SECRET not in text


def test_tracebacks_from_any_logger_leave_out_the_message(log_file):
    logs.attach_server()
    try:
        raise KeyError(SECRET)
    except KeyError:
        logging.getLogger(logs.SERVER_LOGGER).exception("Exception in ASGI application")
    flush()
    text = log_file.read_text(encoding="utf-8")
    assert "KeyError (message omitted)" in text and "Exception in ASGI application" in text
    assert SECRET not in text


def test_the_server_logger_is_attached_again_after_a_reset(log_file):
    server = logging.getLogger(logs.SERVER_LOGGER)
    server.handlers.clear()  # What uvicorn's logging setup does as it starts.
    logs.attach_server()
    logs.attach_server()
    assert server.handlers.count(logs._handler) == 1


def test_the_log_rotates(log_file, monkeypatch):
    logs._handler.maxBytes = 2000
    logger = logging.getLogger("home_manager.test")
    for number in range(200):
        logger.info("entry %d %s", number, "x" * 40)
    flush()
    rotated = sorted(path.name for path in log_file.parent.iterdir())
    assert rotated[:2] == ["home-manager.log", "home-manager.log.1"]
    assert len(rotated) == 1 + logs.BACKUPS


def test_configuring_again_replaces_the_handler(tmp_path, log_file):
    first = logs._handler
    second_file = logs.configure(tmp_path / "other")
    logger = logging.getLogger("home_manager")
    assert first not in logger.handlers and logger.handlers.count(logs._handler) == 1
    assert second_file.parent.parent == tmp_path / "other"
