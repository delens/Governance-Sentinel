"""``python -m governance_sentinel`` command line.

``audit`` runs the same pipeline as ``python main.py``. ``generate`` writes a
seeded extract and does not audit it. ``history`` lists stored runs and the
principle-score trend. ``seed-history`` writes twelve deterministic weekly
runs into the DuckDB file.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from governance_sentinel.history import (
    DEFAULT_HISTORY_DB,
    DEMO_ROWS,
    DEMO_WEEKS,
    HistoryStore,
    format_history,
    seed_history,
)
from governance_sentinel.logging_config import configure_logging
from governance_sentinel.pipeline import (
    DEFAULT_COUNTERPARTIES,
    DEFAULT_GLOSSARY,
    DEFAULT_ROWS,
    DEFAULT_RULES,
    execute,
)
from governance_sentinel.synthetic import DEFAULT_SEED, write_risk_dataset

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    """Dispatch ``audit``, ``generate``, ``history``, or ``seed-history``."""
    parser = argparse.ArgumentParser(prog="governance_sentinel")
    subcommands = parser.add_subparsers(dest="command", required=True)

    audit = subcommands.add_parser("audit", help="Run the data-quality audit and write the PDF.")
    audit.add_argument(
        "--input",
        default=None,
        help="CSV to audit. Omit to generate a seeded extract.",
    )
    audit.add_argument("--rules", default=str(DEFAULT_RULES), help="YAML rules file.")
    audit.add_argument("--out", default="Audit_Report.pdf", help="PDF path.")
    audit.add_argument("--counterparties", default=str(DEFAULT_COUNTERPARTIES))
    audit.add_argument("--glossary", default=str(DEFAULT_GLOSSARY))
    audit.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    audit.add_argument("--seed", type=int, default=DEFAULT_SEED)
    audit.add_argument(
        "--generated",
        default="data/generated_transactions.csv",
        help="Where a generated extract is written when --input is omitted.",
    )
    audit.add_argument("--log-file", default="governance_sentinel.log")
    audit.add_argument(
        "--log-level",
        default="INFO",
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    )
    audit.add_argument("--history-db", default=str(DEFAULT_HISTORY_DB))
    audit.add_argument(
        "--no-history",
        action="store_true",
        help="Do not write this run to the history database.",
    )

    generate = subcommands.add_parser(
        "generate",
        help="Write a seeded extract and the counterparty master.",
    )
    generate.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    generate.add_argument("--seed", type=int, default=DEFAULT_SEED)
    generate.add_argument("--out", default="data/generated_transactions.csv")
    generate.add_argument("--counterparties", default="data/generated_counterparties.csv")

    history = subcommands.add_parser(
        "history",
        help="List stored audit runs and the principle-score trend.",
    )
    history.add_argument("--db", default=str(DEFAULT_HISTORY_DB))

    seed = subcommands.add_parser(
        "seed-history",
        help="Write a deterministic weekly demo history into DuckDB.",
    )
    seed.add_argument("--db", default=str(DEFAULT_HISTORY_DB))
    seed.add_argument("--rules", default=str(DEFAULT_RULES))
    seed.add_argument("--weeks", type=int, default=DEMO_WEEKS)
    seed.add_argument("--rows", type=int, default=DEMO_ROWS)

    args = parser.parse_args(argv)
    if args.command == "generate":
        manifest = write_risk_dataset(args.out, args.counterparties, n=args.rows, seed=args.seed)
        print(
            f"Wrote {manifest.row_count} rows to {args.out} (seed {manifest.seed}).",
            file=sys.stdout,
        )
        return
    if args.command == "history":
        _print_history(Path(str(args.db)))
        return
    if args.command == "seed-history":
        runs = seed_history(
            Path(str(args.db)),
            Path(str(args.rules)),
            weeks=int(args.weeks),
            rows=int(args.rows),
        )
        print(
            f"Seeded {len(runs)} runs into {args.db}.",
            file=sys.stdout,
        )
        print(format_history(runs), file=sys.stdout)
        return
    configure_logging(args.log_level, args.log_file)
    mapped = argparse.Namespace(
        mode="real" if args.input else "mock",
        csv=args.input or args.generated,
        output=args.out,
        rules=args.rules,
        counterparties=args.counterparties,
        glossary=args.glossary,
        rows=args.rows,
        seed=args.seed,
        log_file=args.log_file,
        log_level=args.log_level,
        history_db=args.history_db,
        no_history=args.no_history,
    )
    execute(mapped)


def _print_history(path: Path) -> None:
    if not path.is_file():
        print(f"No history database at {path}.", file=sys.stdout)
        return
    print(format_history(HistoryStore(path).list_runs()), file=sys.stdout)
