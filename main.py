"""Governance-Sentinel entry point.

Pipeline:
    1. Load mock rows, or a CSV when ``--mode real`` is set.
    2. Run the BCBS 239 data-quality checks.
    3. Measure disparate impact on the synthetic approval label.
    4. Write a PDF audit report.

Examples:
    python main.py
    python main.py --mode real --csv raw_financial_data.csv
    python main.py --log-level DEBUG
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from data_loader import generate_mock_data
from reporter import FRAMEWORK_VERSION, create_pdf_report
from validators import run_bcbs239_audit

logger = logging.getLogger(__name__)

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


def configure_logging(level: str, log_file: str) -> None:
    """Send logs to stdout and ``log_file`` at the requested root level.

    Third-party loggers are left alone. The root logger is not forced to ERROR.
    TensorFlow is not a dependency, so its log-level variable is not set.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(isinstance(item, _OptionalExtraFilter) for item in root.filters):
        root.addFilter(_OptionalExtraFilter())
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line. ``LOG_LEVEL`` is the default for ``--log-level``."""
    parser = argparse.ArgumentParser(description="Governance-Sentinel audit pipeline")
    parser.add_argument(
        "--mode",
        choices=("mock", "real"),
        default="mock",
        help="mock writes a synthetic CSV; real reads --csv (default: mock).",
    )
    parser.add_argument(
        "--csv",
        default="raw_financial_data.csv",
        help="CSV written in mock mode, or read in real mode.",
    )
    parser.add_argument(
        "--output",
        default="Audit_Report.pdf",
        help="PDF report path (default: Audit_Report.pdf).",
    )
    parser.add_argument(
        "--log-file",
        default="governance_sentinel.log",
        help="UTF-8 audit log, appended across runs.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Root logger level. Default: INFO, or the LOG_LEVEL environment variable.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the four pipeline steps."""
    args = parse_args(argv)
    configure_logging(args.log_level, args.log_file)

    logger.info("Governance-Sentinel %s starting", FRAMEWORK_VERSION)
    logger.info("STEP 1/4 - Loading data (mode=%s)", args.mode)
    frame = generate_mock_data(mode=args.mode, csv_path=args.csv)
    logger.info("Dataset loaded: %d rows, %d columns", len(frame), len(frame.columns))

    logger.info("STEP 2/4 - BCBS 239 data-quality audit")
    dq_results = run_bcbs239_audit(frame)

    logger.info("STEP 3/4 - Disparate-impact audit")
    # Imported here so AIF360's optional-extra notices are filtered by the
    # logging configuration above, instead of installing their own handler.
    from bias_audit import run_fairness_audit

    bias_score = run_fairness_audit(frame)

    logger.info("STEP 4/4 - Writing PDF audit report")
    create_pdf_report(dq_results, bias_score, output_path=args.output)
    logger.info("Pipeline completed successfully.")
    logger.info("Files: %s | %s", args.output, args.log_file)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Fatal error during execution.")
        sys.exit(1)
