"""Command-line audit used by ``python main.py``.

Mock mode writes a seeded synthetic extract, then reads that file back so the
SHA-256 is the hash of the bytes that were checked. Real mode reads ``--csv``.
The counterparty master is always the file passed in ``--counterparties``.
Mock mode does not rewrite that master.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from governance_sentinel.catalog import export_glossary, load_glossary
from governance_sentinel.history import DEFAULT_HISTORY_DB, HistoryStore, snapshot_run
from governance_sentinel.lineage import build_lineage, openlineage_event, write_lineage_artifacts
from governance_sentinel.ownership import export_ownership, load_ownership
from governance_sentinel.rules import evaluate_rules, load_rules
from governance_sentinel.synthetic import (
    DEFAULT_ROWS,
    DEFAULT_SEED,
    TRANSACTION_COLUMNS,
    generate_risk_dataset,
)
from reporter import FRAMEWORK_VERSION, create_pdf_report

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = REPO_ROOT / "rules" / "dq_rules.yml"
DEFAULT_COUNTERPARTIES = REPO_ROOT / "data" / "counterparties.csv"
DEFAULT_GLOSSARY = REPO_ROOT / "catalog" / "glossary.yml"
DEFAULT_OWNERSHIP = REPO_ROOT / "governance" / "ownership.yml"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the ``python main.py`` command line.

    ``LOG_LEVEL`` is the default for ``--log-level``. Bundled rules and the
    counterparty master resolve from the repository. The CSV and the PDF are
    relative to the working directory.
    """
    parser = argparse.ArgumentParser(description="Governance-Sentinel audit pipeline")
    parser.add_argument(
        "--mode",
        choices=("mock", "real"),
        default="mock",
        help="mock writes a synthetic CSV; real reads --csv (default: mock).",
    )
    parser.add_argument(
        "--csv",
        default="data/generated_transactions.csv",
        help="CSV written in mock mode, or read in real mode.",
    )
    parser.add_argument(
        "--output",
        default="Audit_Report.pdf",
        help="PDF report path (default: Audit_Report.pdf).",
    )
    parser.add_argument(
        "--rules",
        default=str(DEFAULT_RULES),
        help="YAML data-quality rules.",
    )
    parser.add_argument(
        "--counterparties",
        default=str(DEFAULT_COUNTERPARTIES),
        help="Counterparty master used by the referential rule.",
    )
    parser.add_argument(
        "--glossary",
        default=str(DEFAULT_GLOSSARY),
        help="Business glossary YAML.",
    )
    parser.add_argument(
        "--ownership",
        default=str(DEFAULT_OWNERSHIP),
        help="Data ownership matrix YAML.",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=DEFAULT_ROWS,
        help=f"Rows to generate in mock mode (default: {DEFAULT_ROWS}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Generator seed in mock mode (default: {DEFAULT_SEED}).",
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
    parser.add_argument(
        "--history-db",
        default=str(DEFAULT_HISTORY_DB),
        help="DuckDB file that stores this run (default: history/governance_history.duckdb).",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Do not write this run to the history database.",
    )
    return parser.parse_args(argv)


def execute(args: argparse.Namespace) -> str:
    """Run the audit described by ``args``. Return the run id."""
    run_id = uuid.uuid4().hex
    logger.info("Governance-Sentinel %s starting", FRAMEWORK_VERSION)
    logger.info("run_id: %s", run_id)
    logger.info("STEP 1/5 - Loading data (mode=%s)", args.mode)

    csv_path = Path(str(args.csv))
    if args.mode == "mock":
        frame, _reference, _manifest = generate_risk_dataset(n=int(args.rows), seed=int(args.seed))
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(csv_path, index=False)
        logger.info(
            "Synthetic dataset written to %s (%d rows, seed %s).",
            csv_path,
            len(frame),
            args.seed,
        )
    elif args.mode != "real":
        raise ValueError(f"Unknown mode: {args.mode!r}. Use 'mock' or 'real'.")

    try:
        loaded = pd.read_csv(csv_path)
    except FileNotFoundError:
        logger.error("CSV file not found: %s", csv_path)
        raise

    missing = [column for column in TRANSACTION_COLUMNS if column not in loaded.columns]
    if missing:
        logger.error("CSV is missing required columns: %s", missing)
        raise ValueError(
            f"CSV {str(csv_path)!r} is missing required columns: {missing}. "
            f"Expected schema: {list(TRANSACTION_COLUMNS)}."
        )

    digest = sha256_file(csv_path)
    logger.info(
        "Dataset loaded: %d rows, %d columns. SHA-256 %s",
        len(loaded),
        len(loaded.columns),
        digest,
    )

    logger.info("STEP 2/5 - Data-quality rules")
    ruleset = load_rules(str(args.rules))
    try:
        reference = pd.read_csv(str(args.counterparties))
    except FileNotFoundError:
        logger.error("Counterparty master not found: %s", args.counterparties)
        raise
    rule_results = evaluate_rules(loaded, ruleset, {"counterparties": reference})

    logger.info("STEP 3/5 - Disparate-impact audit")
    # Imported here so AIF360's optional-extra notices are filtered by the
    # logging configuration the caller installed before execute().
    from bias_audit import audit_fairness

    fairness = audit_fairness(loaded)

    logger.info("STEP 4/5 - Lineage, reconciliation, and glossary")
    lineage = build_lineage(loaded, rule_results, inject_break=True)
    event = openlineage_event(run_id, loaded, rule_results)
    output_dir = Path(str(args.output)).resolve().parent
    glossary = load_glossary(str(args.glossary), ruleset)
    ownership_path = getattr(args, "ownership", None) or str(DEFAULT_OWNERSHIP)
    ownership = load_ownership(str(ownership_path), glossary, ruleset)
    export_glossary(glossary, output_dir / "glossary.json", output_dir / "glossary.csv")
    export_ownership(ownership, output_dir / "ownership.csv")
    write_lineage_artifacts(lineage, event, output_dir, glossary.terms)
    logger.info(
        "Reconciliation %s. Aggregate status %s.",
        lineage.reconciliation.status,
        lineage.statuses["agg_exposure"],
    )

    trend = None
    if bool(getattr(args, "no_history", False)):
        logger.info("History persistence skipped.")
    else:
        run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stored = snapshot_run(
            run_id=run_id,
            run_at=run_at,
            input_sha256=digest,
            input_name=str(csv_path),
            row_count=len(loaded),
            results=rule_results,
            reconciliation=lineage.reconciliation,
        )
        history_path = Path(str(getattr(args, "history_db", DEFAULT_HISTORY_DB)))
        store = HistoryStore(history_path)
        store.record(stored)
        comparison = store.comparison_for(run_id)
        if comparison is not None and comparison.previous_run_id is not None:
            trend = comparison
        logger.info("History stored in %s.", history_path)

    logger.info("STEP 5/5 - Writing PDF audit report")
    create_pdf_report(
        rule_results,
        fairness,
        run_id=run_id,
        dataset_sha256=digest,
        row_count=len(loaded),
        output_path=str(args.output),
        dataset_name=str(csv_path),
        lineage=lineage,
        trend=trend,
        ownership=ownership,
    )
    logger.info("Pipeline completed successfully.")
    logger.info("Files: %s | %s", args.output, args.log_file)
    return run_id


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
