"""Audit history.

``runs/history.jsonl`` is the six-point series the dashboard already charted.
Each line is one seeded audit. Defect rates on that series do not change, so
the dimension pass rates are flat and the disparate-impact ratio moves.

The DuckDB file is the store written by a real audit and by ``seed-history``.
It keeps the run, every rule result, and the principle scores. The default
path is ``history/governance_history.duckdb``. The file is local and is not
committed. DuckDB is used instead of SQLite because the history is a small
analytical table (scores by principle over time) and the package is one pin.
There is no server.

``runs/kpi_demo.json`` is the same twelve-week payload, committed so the
dashboard can chart it without a local database. A local database with at
least one run replaces that demo on the trend page.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd

from governance_sentinel import __version__
from governance_sentinel.lineage import ReconciliationResult, build_lineage
from governance_sentinel.models import RuleResult
from governance_sentinel.rules import RuleSet, evaluate_rules, load_rules
from governance_sentinel.scores import PrincipleScore, overall_score, score_principles
from governance_sentinel.synthetic import DEFECT_RATES, MAX_ROWS, MIN_ROWS, generate_risk_dataset

DIMENSIONS: tuple[str, ...] = ("completeness", "accuracy", "validity", "timeliness")

DEFAULT_HISTORY_DB = Path("history/governance_history.duckdb")
DEMO_WEEKS = 12
DEMO_ROWS = 800
_ANCHOR = datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc)
_SCALES: tuple[float, ...] = (1.6, 1.4, 1.2, 1.0, 0.8, 0.5, 0.3, 0.45, 0.7, 0.9, 1.15, 1.35)
# The injected 250,000 break is off for four July weeks, then it returns.
_BREAKS: tuple[bool, ...] = (
    True,
    True,
    True,
    True,
    False,
    False,
    False,
    False,
    True,
    True,
    True,
    True,
)

_CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS audit_runs (
    run_id VARCHAR PRIMARY KEY,
    run_at VARCHAR NOT NULL,
    input_sha256 VARCHAR NOT NULL,
    input_name VARCHAR NOT NULL,
    row_count INTEGER NOT NULL,
    overall_score DOUBLE NOT NULL,
    rules_passed INTEGER NOT NULL,
    rules_failed INTEGER NOT NULL,
    rules_total INTEGER NOT NULL,
    framework_version VARCHAR NOT NULL
)
"""

_CREATE_RULES = """
CREATE TABLE IF NOT EXISTS rule_results (
    run_id VARCHAR NOT NULL,
    ordinal INTEGER NOT NULL,
    rule_id VARCHAR NOT NULL,
    principle VARCHAR NOT NULL,
    dimension VARCHAR NOT NULL,
    column_name VARCHAR NOT NULL,
    records_checked INTEGER NOT NULL,
    records_failed INTEGER NOT NULL,
    pass_pct DOUBLE NOT NULL,
    threshold DOUBLE NOT NULL,
    status VARCHAR NOT NULL,
    PRIMARY KEY (run_id, rule_id)
)
"""

_CREATE_SCORES = """
CREATE TABLE IF NOT EXISTS principle_scores (
    run_id VARCHAR NOT NULL,
    ordinal INTEGER NOT NULL,
    principle VARCHAR NOT NULL,
    principle_title VARCHAR NOT NULL,
    score DOUBLE,
    measured BOOLEAN NOT NULL,
    status VARCHAR NOT NULL,
    basis VARCHAR NOT NULL,
    PRIMARY KEY (run_id, principle)
)
"""


@dataclass(frozen=True)
class StoredRule:
    """One rule result kept in the history store."""

    rule_id: str
    principle: str
    dimension: str
    column_name: str
    records_checked: int
    records_failed: int
    pass_pct: float
    threshold: float
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "principle": self.principle,
            "dimension": self.dimension,
            "column_name": self.column_name,
            "records_checked": self.records_checked,
            "records_failed": self.records_failed,
            "pass_pct": self.pass_pct,
            "threshold": self.threshold,
            "status": self.status,
        }


@dataclass(frozen=True)
class StoredRun:
    """One persisted audit."""

    run_id: str
    run_at: str
    input_sha256: str
    input_name: str
    row_count: int
    overall_score: float
    rules_passed: int
    rules_failed: int
    rules_total: int
    framework_version: str
    principles: tuple[PrincipleScore, ...]
    rules: tuple[StoredRule, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "run_at": self.run_at,
            "input_sha256": self.input_sha256,
            "input_name": self.input_name,
            "row_count": self.row_count,
            "overall_score": self.overall_score,
            "rules_passed": self.rules_passed,
            "rules_failed": self.rules_failed,
            "rules_total": self.rules_total,
            "framework_version": self.framework_version,
            "principles": [item.to_dict() for item in self.principles],
            "rules": [item.to_dict() for item in self.rules],
        }


@dataclass(frozen=True)
class PrincipleDelta:
    """One principle compared with the previous run."""

    principle: str
    title: str
    current: float | None
    previous: float | None
    delta: float | None
    current_status: str
    previous_status: str | None


@dataclass(frozen=True)
class RuleDelta:
    """A rule whose PASS or FAIL status changed."""

    rule_id: str
    previous_status: str
    current_status: str


@dataclass(frozen=True)
class RunComparison:
    """The current run against the previous one, when a previous one exists."""

    run_id: str
    previous_run_id: str | None
    overall_score: float
    previous_overall: float | None
    overall_delta: float | None
    principles: tuple[PrincipleDelta, ...]
    rule_changes: tuple[RuleDelta, ...]


@dataclass(frozen=True)
class WeekPlan:
    """One deterministic week of the demo history."""

    index: int
    run_id: str
    run_at: str
    seed: int
    rows: int
    scale: float
    inject_break: bool
    rates: dict[str, float]


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
    scores = score_principles(results, lineage.reconciliation)
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
        "overall_score": overall_score(scores),
        "principle_scores": [item.to_dict() for item in scores],
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
    if "generated_at" in frame.columns and not frame.empty:
        frame = frame.sort_values("generated_at").reset_index(drop=True)
    return frame


def snapshot_run(
    *,
    run_id: str,
    run_at: str,
    input_sha256: str,
    input_name: str,
    row_count: int,
    results: Sequence[RuleResult],
    reconciliation: ReconciliationResult,
) -> StoredRun:
    """Build the record that the store writes. Scores are rounded to 6 decimals."""
    scores = score_principles(results, reconciliation)
    rules = tuple(
        StoredRule(
            rule_id=item.rule_id,
            principle=item.principle,
            dimension=item.dimension,
            column_name=item.column,
            records_checked=item.records_checked,
            records_failed=item.records_failed,
            pass_pct=round(item.pass_pct, 6),
            threshold=float(item.threshold),
            status=item.status,
        )
        for item in results
    )
    passed = sum(1 for item in rules if item.status == "PASS")
    failed = sum(1 for item in rules if item.status == "FAIL")
    return StoredRun(
        run_id=run_id,
        run_at=run_at,
        input_sha256=input_sha256,
        input_name=input_name,
        row_count=row_count,
        overall_score=overall_score(scores),
        rules_passed=passed,
        rules_failed=failed,
        rules_total=len(rules),
        framework_version=__version__,
        principles=scores,
        rules=rules,
    )


def compare_runs(current: StoredRun, previous: StoredRun | None) -> RunComparison:
    """Subtract the previous principle scores from the current ones."""
    previous_scores: dict[str, PrincipleScore] = {}
    previous_rules: dict[str, StoredRule] = {}
    if previous is not None:
        previous_scores = {item.principle: item for item in previous.principles}
        previous_rules = {item.rule_id: item for item in previous.rules}
    deltas: list[PrincipleDelta] = []
    for item in current.principles:
        prior = previous_scores.get(item.principle)
        prior_score = None if prior is None else prior.score
        delta = None
        if item.score is not None and prior_score is not None:
            delta = round(item.score - prior_score, 6)
        deltas.append(
            PrincipleDelta(
                principle=item.principle,
                title=item.title,
                current=item.score,
                previous=prior_score,
                delta=delta,
                current_status=item.status,
                previous_status=None if prior is None else prior.status,
            )
        )
    changes: list[RuleDelta] = []
    for rule in current.rules:
        prior_rule = previous_rules.get(rule.rule_id)
        if prior_rule is not None and prior_rule.status != rule.status:
            changes.append(
                RuleDelta(
                    rule_id=rule.rule_id,
                    previous_status=prior_rule.status,
                    current_status=rule.status,
                )
            )
    overall_delta = None
    previous_overall = None if previous is None else previous.overall_score
    if previous_overall is not None:
        overall_delta = round(current.overall_score - previous_overall, 6)
    return RunComparison(
        run_id=current.run_id,
        previous_run_id=None if previous is None else previous.run_id,
        overall_score=current.overall_score,
        previous_overall=previous_overall,
        overall_delta=overall_delta,
        principles=tuple(deltas),
        rule_changes=tuple(changes),
    )


def weekly_plan(*, weeks: int = DEMO_WEEKS, rows: int = DEMO_ROWS) -> tuple[WeekPlan, ...]:
    """Return the deterministic weekly plan. Week 0 is 2026-06-03 08:00 UTC."""
    if weeks < 1 or weeks > len(_SCALES):
        raise ValueError(f"weeks must be from 1 to {len(_SCALES)}. Got {weeks}.")
    if rows < MIN_ROWS or rows > MAX_ROWS:
        raise ValueError(f"rows must be from {MIN_ROWS} to {MAX_ROWS}. Got {rows}.")
    plans: list[WeekPlan] = []
    for index in range(weeks):
        scale = _SCALES[index]
        rates = {name: round(rate * scale, 6) for name, rate in DEFECT_RATES.items()}
        moment = _ANCHOR + timedelta(days=7 * index)
        seed = 239 + index
        token = f"governance-sentinel/demo/{index}/{seed}/{rows}/{scale}"
        plans.append(
            WeekPlan(
                index=index,
                run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, token)),
                run_at=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                seed=seed,
                rows=rows,
                scale=scale,
                inject_break=_BREAKS[index],
                rates=rates,
            )
        )
    return tuple(plans)


def build_seed_runs(
    rules_path: Path,
    *,
    weeks: int = DEMO_WEEKS,
    rows: int = DEMO_ROWS,
) -> tuple[StoredRun, ...]:
    """Audit the weekly plan. The same arguments always return the same runs."""
    ruleset = load_rules(rules_path)
    runs: list[StoredRun] = []
    for plan in weekly_plan(weeks=weeks, rows=rows):
        frame, reference, _manifest = generate_risk_dataset(
            n=plan.rows,
            seed=plan.seed,
            defect_rates=plan.rates,
        )
        digest = hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()
        results = evaluate_rules(frame, ruleset, {"counterparties": reference})
        lineage = build_lineage(frame, results, inject_break=plan.inject_break)
        runs.append(
            snapshot_run(
                run_id=plan.run_id,
                run_at=plan.run_at,
                input_sha256=digest,
                input_name=f"synthetic:seed={plan.seed}:scale={plan.scale}",
                row_count=len(frame),
                results=results,
                reconciliation=lineage.reconciliation,
            )
        )
    return tuple(runs)


def seed_history(
    path: Path,
    rules_path: Path,
    *,
    weeks: int = DEMO_WEEKS,
    rows: int = DEMO_ROWS,
) -> tuple[StoredRun, ...]:
    """Write the weekly plan into DuckDB. Re-seeding upserts the same run ids."""
    runs = build_seed_runs(rules_path, weeks=weeks, rows=rows)
    HistoryStore(path).record_many(runs)
    return runs


class HistoryStore:
    """DuckDB file of audit runs, rule results, and principle scores."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, run: StoredRun) -> None:
        """Insert or replace one run."""
        self.record_many((run,))

    def record_many(self, runs: Sequence[StoredRun]) -> None:
        """Insert or replace each run in one transaction."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self.path))
        try:
            _create_tables(connection)
            connection.execute("BEGIN")
            try:
                for run in runs:
                    _delete_run(connection, run.run_id)
                    _insert_run(connection, run)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()

    def list_runs(self) -> tuple[StoredRun, ...]:
        """Return every run, oldest first."""
        if not self.path.is_file():
            return ()
        connection = duckdb.connect(str(self.path), read_only=True)
        try:
            headers = connection.execute(
                """
                SELECT run_id, run_at, input_sha256, input_name, row_count,
                       overall_score, rules_passed, rules_failed, rules_total,
                       framework_version
                FROM audit_runs
                ORDER BY run_at, run_id
                """
            ).fetchall()
            runs: list[StoredRun] = []
            for header in headers:
                run_id = str(header[0])
                runs.append(_assemble(connection, header, run_id))
            return tuple(runs)
        finally:
            connection.close()

    def comparison_for(self, run_id: str) -> RunComparison | None:
        """Compare ``run_id`` with the run immediately before it. Missing is None."""
        runs = self.list_runs()
        for index, run in enumerate(runs):
            if run.run_id == run_id:
                previous = runs[index - 1] if index else None
                return compare_runs(run, previous)
        return None


def kpi_frame(runs: Sequence[StoredRun]) -> pd.DataFrame:
    """One row per run, with a column per principle score."""
    rows: list[dict[str, object]] = []
    for run in runs:
        row: dict[str, object] = {
            "run_at": run.run_at,
            "run_id": run.run_id,
            "overall_score": run.overall_score,
            "rules_failed": run.rules_failed,
            "rules_total": run.rules_total,
            "input_sha256": run.input_sha256,
        }
        for score in run.principles:
            row[f"p{score.principle}"] = score.score
            row[f"p{score.principle}_status"] = score.status
        rows.append(row)
    return pd.DataFrame(rows)


def rule_status_frame(runs: Sequence[StoredRun]) -> pd.DataFrame:
    """One row per run and one column per rule, holding PASS or FAIL."""
    rows: list[dict[str, object]] = []
    for run in runs:
        row: dict[str, object] = {"run_at": run.run_at}
        for rule in run.rules:
            row[rule.rule_id] = rule.status
        rows.append(row)
    return pd.DataFrame(rows)


def load_kpi_runs(root: Path, *, database: Path | None = None) -> tuple[StoredRun, ...]:
    """Prefer a non-empty local database, then the committed demo JSON."""
    path = root / "history" / "governance_history.duckdb" if database is None else database
    if path.is_file():
        stored = HistoryStore(path).list_runs()
        if stored:
            return stored
    demo = root / "runs" / "kpi_demo.json"
    if not demo.is_file():
        return ()
    raw = json.loads(demo.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("runs/kpi_demo.json must be a list of runs.")
    return tuple(stored_run_from_dict(item) for item in raw)


def stored_run_from_dict(payload: object) -> StoredRun:
    """Parse one run object written by ``StoredRun.to_dict``."""
    if not isinstance(payload, dict):
        raise ValueError("A history run must be a JSON object.")
    principles_raw = payload.get("principles")
    rules_raw = payload.get("rules")
    if not isinstance(principles_raw, list) or not isinstance(rules_raw, list):
        raise ValueError("A history run needs principles and rules lists.")
    principles = tuple(_principle_from_dict(item) for item in principles_raw)
    rules = tuple(_rule_from_dict(item) for item in rules_raw)
    return StoredRun(
        run_id=_text(payload, "run_id"),
        run_at=_text(payload, "run_at"),
        input_sha256=_text(payload, "input_sha256"),
        input_name=_text(payload, "input_name"),
        row_count=_int(payload, "row_count"),
        overall_score=_float(payload, "overall_score"),
        rules_passed=_int(payload, "rules_passed"),
        rules_failed=_int(payload, "rules_failed"),
        rules_total=_int(payload, "rules_total"),
        framework_version=_text(payload, "framework_version"),
        principles=principles,
        rules=rules,
    )


def format_history(runs: Sequence[StoredRun]) -> str:
    """Plain-text list, principle matrix, and the latest delta."""
    if not runs:
        return "No audit runs are stored."
    lines = [f"runs {len(runs)}", ""]
    lines.append(f"{'run_at':<22} {'overall':>8} {'failed':>8}  run_id")
    for run in runs:
        failed = f"{run.rules_failed}/{run.rules_total}"
        lines.append(f"{run.run_at:<22} {run.overall_score:8.2f} {failed:>8}  {run.run_id}")
    lines.append("")
    lines.append("principle scores")
    header = f"{'run_at':<22}" + "".join(
        f"{'P' + item:>8}" for item in ("2", "3", "4", "5", "6", "7", "11")
    )
    lines.append(header)
    for run in runs:
        by_principle = {item.principle: item.score for item in run.principles}
        cells = "".join(
            _score_cell(by_principle.get(item)) for item in ("2", "3", "4", "5", "6", "7", "11")
        )
        lines.append(f"{run.run_at:<22}{cells}")
    lines.append("")
    latest = runs[-1]
    previous = runs[-2] if len(runs) > 1 else None
    lines.append(format_comparison(compare_runs(latest, previous)))
    return "\n".join(lines)


def format_comparison(comparison: RunComparison) -> str:
    """Plain-text delta. A missing previous run is stated."""
    lines = [f"run {comparison.run_id}"]
    if comparison.previous_run_id is None or comparison.previous_overall is None:
        lines.append(f"overall {comparison.overall_score:.2f}. No previous run is stored.")
        return "\n".join(lines)
    lines.append(f"previous {comparison.previous_run_id}")
    lines.append(
        f"overall {comparison.overall_score:.2f} versus {comparison.previous_overall:.2f} "
        f"(delta {_signed(comparison.overall_delta)})"
    )
    for item in comparison.principles:
        if item.current is None:
            lines.append(f"P{item.principle} {item.title}: not measured")
            continue
        if item.previous is None or item.delta is None:
            lines.append(f"P{item.principle} {item.title}: {item.current:.2f}")
            continue
        lines.append(
            f"P{item.principle} {item.title}: {item.current:.2f} versus {item.previous:.2f} "
            f"(delta {_signed(item.delta)}) {item.previous_status} to {item.current_status}"
        )
    if comparison.rule_changes:
        lines.append("rules that changed status:")
        for change in comparison.rule_changes:
            lines.append(f"  {change.rule_id}: {change.previous_status} to {change.current_status}")
    else:
        lines.append("No rule changed status versus the previous run.")
    return "\n".join(lines)


def _create_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(_CREATE_RUNS)
    connection.execute(_CREATE_RULES)
    connection.execute(_CREATE_SCORES)


def _delete_run(connection: duckdb.DuckDBPyConnection, run_id: str) -> None:
    connection.execute("DELETE FROM rule_results WHERE run_id = ?", [run_id])
    connection.execute("DELETE FROM principle_scores WHERE run_id = ?", [run_id])
    connection.execute("DELETE FROM audit_runs WHERE run_id = ?", [run_id])


def _insert_run(connection: duckdb.DuckDBPyConnection, run: StoredRun) -> None:
    connection.execute(
        """
        INSERT INTO audit_runs (
            run_id, run_at, input_sha256, input_name, row_count, overall_score,
            rules_passed, rules_failed, rules_total, framework_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run.run_id,
            run.run_at,
            run.input_sha256,
            run.input_name,
            run.row_count,
            run.overall_score,
            run.rules_passed,
            run.rules_failed,
            run.rules_total,
            run.framework_version,
        ],
    )
    for index, rule in enumerate(run.rules):
        connection.execute(
            """
            INSERT INTO rule_results (
                run_id, ordinal, rule_id, principle, dimension, column_name,
                records_checked, records_failed, pass_pct, threshold, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.run_id,
                index,
                rule.rule_id,
                rule.principle,
                rule.dimension,
                rule.column_name,
                rule.records_checked,
                rule.records_failed,
                rule.pass_pct,
                rule.threshold,
                rule.status,
            ],
        )
    for index, score in enumerate(run.principles):
        connection.execute(
            """
            INSERT INTO principle_scores (
                run_id, ordinal, principle, principle_title, score, measured, status, basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.run_id,
                index,
                score.principle,
                score.title,
                score.score,
                score.measured,
                score.status,
                score.basis,
            ],
        )


def _assemble(
    connection: duckdb.DuckDBPyConnection,
    header: tuple[object, ...],
    run_id: str,
) -> StoredRun:
    rule_rows = connection.execute(
        """
        SELECT rule_id, principle, dimension, column_name, records_checked,
               records_failed, pass_pct, threshold, status
        FROM rule_results
        WHERE run_id = ?
        ORDER BY ordinal
        """,
        [run_id],
    ).fetchall()
    score_rows = connection.execute(
        """
        SELECT principle, principle_title, score, measured, status, basis
        FROM principle_scores
        WHERE run_id = ?
        ORDER BY ordinal
        """,
        [run_id],
    ).fetchall()
    rules = tuple(
        StoredRule(
            rule_id=str(row[0]),
            principle=str(row[1]),
            dimension=str(row[2]),
            column_name=str(row[3]),
            records_checked=int(row[4]),
            records_failed=int(row[5]),
            pass_pct=float(row[6]),
            threshold=float(row[7]),
            status=str(row[8]),
        )
        for row in rule_rows
    )
    principles = tuple(
        PrincipleScore(
            principle=str(row[0]),
            title=str(row[1]),
            score=None if row[2] is None else float(row[2]),
            measured=bool(row[3]),
            status=str(row[4]),
            basis=str(row[5]),
        )
        for row in score_rows
    )
    return StoredRun(
        run_id=str(header[0]),
        run_at=str(header[1]),
        input_sha256=str(header[2]),
        input_name=str(header[3]),
        row_count=_as_int(header[4]),
        overall_score=_as_float(header[5]),
        rules_passed=_as_int(header[6]),
        rules_failed=_as_int(header[7]),
        rules_total=_as_int(header[8]),
        framework_version=str(header[9]),
        principles=principles,
        rules=rules,
    )


def _principle_from_dict(payload: object) -> PrincipleScore:
    if not isinstance(payload, dict):
        raise ValueError("A principle score must be a JSON object.")
    score = _optional_float(payload.get("score"))
    measured = payload.get("measured")
    if not isinstance(measured, bool):
        raise ValueError("principle.measured must be a boolean.")
    return PrincipleScore(
        principle=_text(payload, "principle"),
        title=_text(payload, "title"),
        score=score,
        measured=measured,
        status=_text(payload, "status"),
        basis=_text(payload, "basis"),
    )


def _rule_from_dict(payload: object) -> StoredRule:
    if not isinstance(payload, dict):
        raise ValueError("A rule result must be a JSON object.")
    return StoredRule(
        rule_id=_text(payload, "rule_id"),
        principle=_text(payload, "principle"),
        dimension=_text(payload, "dimension"),
        column_name=_text(payload, "column_name"),
        records_checked=_int(payload, "records_checked"),
        records_failed=_int(payload, "records_failed"),
        pass_pct=_float(payload, "pass_pct"),
        threshold=_float(payload, "threshold"),
        status=_text(payload, "status"),
    )


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"History field {key} must be a non-empty string.")
    return value


def _int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"History field {key} must be an integer.")
    return value


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected an integer from the history store, got {value!r}.")
    return int(value)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Expected a number from the history store, got {value!r}.")
    return float(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("principle.score must be a number or null.")
    return float(value)


def _float(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"History field {key} must be a number.")
    return float(value)


def _score_cell(value: float | None) -> str:
    if value is None:
        return f"{'n/a':>8}"
    return f"{value:8.2f}"


def _signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value > 0:
        return f"+{value:.2f}"
    return f"{value:.2f}"
