"""Governance-Sentinel entry point.

Pipeline:
    1. Write a seeded synthetic extract, or read a CSV when ``--mode real``.
    2. Evaluate the YAML data-quality rules.
    3. Measure disparate impact on the synthetic approval label.
    4. Reconcile transaction totals to the exposure aggregate and write lineage.
    5. Write a PDF audit report.

Examples:
    python main.py
    python main.py --mode real --csv data/sample_transactions.csv
    python main.py --rows 2000 --seed 239
    python -m governance_sentinel audit --input data/sample_transactions.csv --out Audit_Report.pdf
"""

from __future__ import annotations

import logging
import sys

from governance_sentinel.logging_config import UtcFormatter, configure_logging
from governance_sentinel.pipeline import execute, parse_args

logger = logging.getLogger(__name__)

__all__ = ["UtcFormatter", "configure_logging", "main"]


def main(argv: list[str] | None = None) -> None:
    """Run the audit pipeline."""
    args = parse_args(argv)
    configure_logging(args.log_level, args.log_file)
    execute(args)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Fatal error during execution.")
        sys.exit(1)
