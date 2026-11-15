"""UTC logging used by the command-line entry points."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

_HANDLERS: list[logging.Handler] = []


class _OptionalExtraFilter(logging.Filter):
    """Hide AIF360 notices for optional extras this prototype does not use.

    Importing the disparate-impact metric pulls those notices onto the root
    logger. They are not TensorFlow runtime logs, and the root level itself
    stays at the level the caller requested.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "will be unavailable" not in record.getMessage()


class UtcFormatter(logging.Formatter):
    """Format ``asctime`` from a timezone-aware UTC timestamp."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        moment = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            return moment.strftime(datefmt)
        formatted = moment.strftime(self.default_time_format)
        if self.default_msec_format:
            return self.default_msec_format % (formatted, record.msecs)
        return formatted


def install_optional_extra_filter() -> None:
    """Drop AIF360 optional-extra import notices from the root logger."""
    root = logging.getLogger()
    if not any(isinstance(item, _OptionalExtraFilter) for item in root.filters):
        root.addFilter(_OptionalExtraFilter())


def configure_logging(level: str, log_file: str) -> None:
    """Send logs to stdout and ``log_file`` at the requested root level.

    Third-party loggers are left alone. The root logger is not forced to ERROR.
    TensorFlow is not a dependency, so its log-level variable is not set.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    install_optional_extra_filter()
    formatter = UtcFormatter(
        "%(asctime)s UTC | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for handler in _HANDLERS:
        root.removeHandler(handler)
        handler.close()
    _HANDLERS.clear()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(stream)
    root.addHandler(file_handler)
    _HANDLERS.extend((stream, file_handler))
