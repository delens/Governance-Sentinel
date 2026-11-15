"""Load the sample audit the dashboard displays.

The Streamlit script is a view over this function. Tests can call it without
starting a server.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from governance_sentinel.catalog import Glossary, load_glossary
from governance_sentinel.history import read_history
from governance_sentinel.lineage import LineageReport, build_lineage
from governance_sentinel.logging_config import install_optional_extra_filter
from governance_sentinel.models import FairnessResult, RuleResult
from governance_sentinel.rules import evaluate_rules, load_rules
from governance_sentinel.synthetic import TRANSACTION_COLUMNS


@dataclass(frozen=True)
class DashboardData:
    """One audited extract plus the committed trend."""

    frame: pd.DataFrame
    rules: tuple[RuleResult, ...]
    fairness: FairnessResult
    lineage: LineageReport
    glossary: Glossary
    history: tuple[dict[str, object], ...]
    source_name: str


def load_dashboard(root: Path) -> DashboardData:
    """Audit the committed sample and attach the committed run history."""
    install_optional_extra_filter()
    transactions = root / "data" / "sample_transactions.csv"
    frame = pd.read_csv(transactions)
    missing = [column for column in TRANSACTION_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Sample extract is missing columns: {missing}.")
    ruleset = load_rules(root / "rules" / "dq_rules.yml")
    reference = pd.read_csv(root / "data" / "counterparties.csv")
    rules = tuple(evaluate_rules(frame, ruleset, {"counterparties": reference}))
    glossary = load_glossary(root / "catalog" / "glossary.yml", ruleset)
    lineage = build_lineage(frame, list(rules), inject_break=True)
    from bias_audit import audit_fairness

    fairness = audit_fairness(frame)
    history = tuple(read_history(root / "runs" / "history.jsonl"))
    return DashboardData(
        frame=frame,
        rules=rules,
        fairness=fairness,
        lineage=lineage,
        glossary=glossary,
        history=history,
        source_name=transactions.name,
    )
