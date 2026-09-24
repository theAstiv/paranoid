"""LOG_LEVEL env var wiring and level-gating semantics.

backend/main.py applies `settings.log_level` via `logging.basicConfig(level=
settings.log_level.upper())` at import time — importing it here would boot
the whole FastAPI app/DB, so this reproduces just the two things that matter:
(1) the env var reaches `Settings`, and (2) applying that level to the root
logger actually gates whether a child logger's INFO/DEBUG calls are enabled,
the same mechanism `backend.pipeline.runner`'s lifecycle logging relies on.
"""

import logging

from backend.config import Settings


def test_log_level_env_var_reaches_settings(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings().log_level == "debug"

    monkeypatch.setenv("LOG_LEVEL", "error")
    assert Settings().log_level == "error"


def test_log_level_debug_enables_info_and_error_suppresses_it():
    """Reproduces `logging.basicConfig(level=settings.log_level.upper())` against
    a child logger with no explicit level of its own (matching
    `backend.pipeline.runner`'s logger) and checks the actual gating effect —
    not just that the string reached Settings."""
    logger = logging.getLogger("backend.pipeline.runner")
    root_logger = logging.getLogger()
    previous_root_level = root_logger.level
    previous_logger_level = logger.level
    try:
        root_logger.setLevel("DEBUG")
        logger.setLevel(logging.NOTSET)  # inherit from root, like the real logger does
        assert logger.isEnabledFor(logging.INFO) is True
        assert logger.isEnabledFor(logging.DEBUG) is True

        root_logger.setLevel("ERROR")
        assert logger.isEnabledFor(logging.INFO) is False
    finally:
        root_logger.setLevel(previous_root_level)
        logger.setLevel(previous_logger_level)
