"""Committed run history matches a fresh seeded audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from governance_sentinel.history import build_history_record, history_frame, read_history
from governance_sentinel.rules import load_rules

REPO = Path(__file__).resolve().parents[1]


def test_committed_history_matches_the_engine() -> None:
    records = read_history(REPO / "runs" / "history.jsonl")
    assert len(records) >= 6
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    stored = next(record for record in records if record["seed"] == 239)
    row_count = stored["rows"]
    generated_at = stored["generated_at"]
    assert isinstance(row_count, int)
    assert isinstance(generated_at, str)
    fresh = build_history_record(
        ruleset,
        seed=239,
        rows=row_count,
        generated_at=generated_at,
    )
    assert fresh["rules_failed"] == stored["rules_failed"]
    assert fresh["rules_total"] == stored["rules_total"]
    assert fresh["reconciliation_status"] == "FAIL"
    assert fresh["aggregate_status"] == "FAIL"
    assert fresh["fairness_status"] == stored["fairness_status"]
    assert fresh["disparate_impact"] == pytest.approx(stored["disparate_impact"])
    assert fresh["dataset_sha256"] == stored["dataset_sha256"]
    frame = history_frame(records)
    assert list(frame["generated_at"]) == sorted(str(item["generated_at"]) for item in records)
    assert "pass_pct_completeness" in frame.columns
