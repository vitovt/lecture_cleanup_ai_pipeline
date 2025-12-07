import logging
import sys
from typing import Callable

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def _routing_filter(max_level: int) -> Callable[[logging.LogRecord], bool]:
    def _filter(record: logging.LogRecord) -> bool:
        return record.levelno <= max_level
    return _filter


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("lecture_pipeline")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(levelname)s] %(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(fmt)
    stdout_handler.addFilter(_routing_filter(logging.INFO))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(fmt)
    stderr_handler.setLevel(logging.WARNING)

    logger.addHandler(stdout_handler)
    logger.addHandler(stderr_handler)
    logger.propagate = False
    return logger


_LOGGER = _build_logger()


def set_log_level(level: str) -> None:
    """Set logger level based on config/CLI string."""
    lvl = str(level or "").strip().lower()
    mapping = {
        "trace": TRACE_LEVEL,
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warn": logging.WARNING,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    resolved = mapping.get(lvl, logging.INFO)
    _LOGGER.setLevel(resolved)


def log_trace(message: str) -> None:
    _LOGGER.log(TRACE_LEVEL, message)


def log_debug(message: str) -> None:
    _LOGGER.debug(message)


def log_info(message: str) -> None:
    _LOGGER.info(message)


def log_warn(message: str) -> None:
    _LOGGER.warning(message)


def log_error(message: str) -> None:
    _LOGGER.error(message)


def log_trace_block(title: str, body: str) -> None:
    """Log a multi-line block at TRACE level with consistent framing."""
    log_trace(f"{title} BEGIN")
    for line in (body or "").splitlines() or [""]:
        log_trace(line)
    log_trace(f"{title} END")
