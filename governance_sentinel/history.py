"""Run history used by the dashboard trend.

Each line of ``runs/history.jsonl`` is one seeded audit. The file is produced
by ``build_history_record`` so the numbers are the engine's, not a hand-written
series. ``generated_at`` is the label on the chart, not the wall clock of the
machine that wrote the file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from governance_sentinel.lineage import build_lineage
from governance_sentinel.rules import RuleSet, evaluate_rules
from governance_sentinel.synthetic import generate_risk_dataset

DIMENSIONS: tuple[str, ...] = ("completeness", "accuracy", "validity", "timeliness")


def build_history_record(
    ruleset: RuleSet,
    *,
    seed: int,
    rows: int,
    generated_at: str,
) -> dict[str, object]:
    """Audit one seeded extract and return a JSON-ready summary."""
    frame, reference, _manifest = generate_risk_dataset(n=rows, seed=seed)
    digest = hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()
    results = evaluate_rules(frame, ruleset, {"counterparties": reference})
    # Imported here so a history rebuild pays the AIF360 import only when called.
    from bias_audit import audit_fairness

    fairness = audit_fairness(frame)
    lineage = build_lineage(frame, results, inject_break=True)
    by_dimension: dict[str, float] = {}
    for dimension in DIMENSIONS:
        group = [item.pass_pct for item in results if item.dimension == dimension]
        by_dimension[dimension] = sum(group) / len(group) if group else 0.0
    return {
        "seed": seed,
        "rows": rows,
        "generated_at": generated_at,
        "dataset_sha256": digest,
        "rules_failed": sum(1 for item in results if item.status == "FAIL"),
        "rules_total": len(results),
        "pass_pct_by_dimension": by_dimension,
        "reconciliation_status": lineage.reconciliation.status,
        "aggregate_status": lineage.statuses["agg_exposure"],
        "disparate_impact": None if not fairness.defined else round(fairness.ratio, 6),
        "fairness_status": fairness.status,
        "unprivileged_count": fairness.unprivileged_count,
        "privileged_count": fairness.privileged_count,
    }


def read_history(path: Path) -> list[dict[str, object]]:
    """Read a JSONL history file. A missing file is an empty history."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def history_frame(records: list[dict[str, object]]) -> pd.DataFrame:
    """Flatten dimension pass rates so a chart can plot one column per dimension."""
    rows: list[dict[str, object]] = []
    for record in records:
        flat = {key: value for key, value in record.items() if key != "pass_pct_by_dimension"}
        rates = record.get("pass_pct_by_dimension")
        if isinstance(rates, dict):
            for dimension, value in rates.items():
                flat[f"pass_pct_{dimension}"] = value
        rows.append(flat)
    frame = pd.DataFrame(rows)
    if "generated_at" in frame.columns:
        frame = frame.sort_values("generated_at").reset_index(drop=True)
    return frame
