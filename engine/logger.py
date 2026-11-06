"""Structured, timestamped logging to console and file."""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

LOGGER = "engine"


class _ConsoleFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[2m",
        logging.INFO: "\033[0m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }

    def format(self, record: logging.LogRecord) -> str:
        colour = self.COLORS.get(record.levelno, "")
        reset = "\033[0m" if colour else ""
        prefix = {
            logging.DEBUG: "debug",
            logging.INFO: "  •",
            logging.WARNING: "  !",
            logging.ERROR: "  ✗",
            logging.CRITICAL: "  ✗",
        }.get(record.levelno, "  •")
        return f"{colour}{prefix} {record.getMessage()}{reset}"


class _FileFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return (f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')} "
                f"{record.levelname:<8} {record.name:<18} {record.getMessage()}")


def setup_logging(log_dir: Path, *, verbose: bool = False,
                  log_name: str | None = None) -> tuple[logging.Logger, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = log_dir / (log_name or f"install-{stamp}.log")
    logger = logging.getLogger(LOGGER)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(_ConsoleFormatter())
    logger.addHandler(console)

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_FileFormatter())
    logger.addHandler(file_handler)

    # Third-party modules that share the logger name also write to the file.
    logger.debug("logging to %s", path)
    return logger, path


def close_logging() -> None:
    logger = logging.getLogger(LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
