"""DuckDB history, principle scores, and the deterministic weekly seed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance_sentinel.history import (
    DEMO_ROWS,
    DEMO_WEEKS,
    HistoryStore,
    build_seed_runs,
    compare_runs,
    format_history,
    weekly_plan,
)
from governance_sentinel.synthetic import generate_risk_dataset

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "rules" / "dq_rules.yml"


def _score(run_principles: tuple, principle: str) -> float | None:
    match = next(item for item in run_principles if item.principle == principle)
    return match.score


def test_weekly_plan_is_twelve_dated_weeks() -> None:
    plan = weekly_plan()
    assert len(plan) == DEMO_WEEKS == 12
    assert plan[0].run_at == "2026-06-03T08:00:00Z"
    assert plan[0].seed == 239
    assert plan[0].rows == DEMO_ROWS
    assert plan[0].scale == 1.6
    assert plan[0].inject_break is True
    assert plan[4].inject_break is False
    assert plan[7].inject_break is False
    assert plan[8].inject_break is True
    assert plan[-1].run_at == "2026-08-19T08:00:00Z"
    assert plan[-1].scale == 1.35
    assert weekly_plan() == plan
    with pytest.raises(ValueError, match="weeks"):
        weekly_plan(weeks=0)


def test_store_round_trip_and_delta(tmp_path: Path) -> None:
    runs = build_seed_runs(RULES, weeks=5, rows=40)
    store = HistoryStore(tmp_path / "governance_history.duckdb")
    store.record(runs[0])
    store.record_many(runs)
    loaded = store.list_runs()
    assert [item.to_dict() for item in loaded] == [item.to_dict() for item in runs]
    comparison = store.comparison_for(runs[-1].run_id)
    assert comparison is not None
    assert comparison.previous_run_id == runs[-2].run_id
    assert comparison.overall_delta == pytest.approx(
        runs[-1].overall_score - runs[-2].overall_score
    )
    first = compare_runs(runs[0], None)
    assert first.previous_run_id is None
    assert first.overall_delta is None
    assert "No previous run" in format_history((runs[0],))
    text = format_history(runs)
    assert "principle scores" in text
    assert "not measured" in text

    assert _score(runs[0].principles, "6") == 100.0
    assert _score(runs[4].principles, "6") == 100.0
    assert _score(runs[0].principles, "11") is None
    failed_tie = next(item for item in runs[0].principles if item.principle == "7")
    assert failed_tie.status == "FAIL"
    assert failed_tie.score is not None and failed_tie.score < 100.0
    clear_tie = next(item for item in runs[4].principles if item.principle == "7")
    assert clear_tie.status == "PASS"
    assert clear_tie.score == 100.0
    early = {_item.principle: _item.score for _item in runs[0].principles}
    later = {_item.principle: _item.score for _item in runs[4].principles}
    assert early["7"] != later["7"]
    assert (early["3"], early["4"], early["5"]) != (later["3"], later["4"], later["5"])


def test_seed_runs_are_deterministic() -> None:
    first = build_seed_runs(RULES, weeks=2, rows=40)
    second = build_seed_runs(RULES, weeks=2, rows=40)
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert first[0].run_id == second[0].run_id
    assert first[0].input_sha256 == second[0].input_sha256


def test_unknown_defect_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown defect"):
        generate_risk_dataset(n=40, seed=1, defect_rates={"not_a_defect": 0.1})


def test_committed_demo_history_matches_the_engine() -> None:
    fresh = [item.to_dict() for item in build_seed_runs(RULES, weeks=DEMO_WEEKS, rows=DEMO_ROWS)]
    stored = json.loads((REPO / "runs" / "kpi_demo.json").read_text(encoding="utf-8"))
    assert stored == fresh
