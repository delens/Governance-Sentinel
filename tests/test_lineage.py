"""Lineage, reconciliation, downstream status, and the OpenLineage event."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from governance_sentinel.lineage import (
    RECONCILIATION_BREAK,
    aggregate_exposures,
    build_lineage,
    lineage_graph,
    node_statuses,
    openlineage_event,
    reconcile,
    reported_aggregate,
    write_lineage_artifacts,
)
from governance_sentinel.models import RuleResult
from governance_sentinel.rules import load_rules
from governance_sentinel.synthetic import SAMPLE_ROWS, generate_risk_dataset

REPO = Path(__file__).resolve().parents[1]


def _result(status: str, rule_id: str = "demo") -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        cde="exposure_amount",
        column="exposure_amount",
        dimension="accuracy",
        rule_type="not_null",
        description="Demo.",
        remediation="Fix it.",
        records_checked=10,
        records_failed=0 if status == "PASS" else 1,
        pass_pct=100.0 if status == "PASS" else 90.0,
        threshold=99.0,
        status=status,
        sample_failing_ids=(),
        failing_ids=(),
        owner="Group Risk Data Office",
        steward="Credit Risk Data Steward",
        principle="3",
        principle_title="Accuracy and Integrity",
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "legal_entity_id": ["LE-UK", "LE-UK", "LE-FR"],
            "currency": ["EUR", "EUR", "USD"],
            "reporting_date": ["2026-09-30", "2026-09-30", "2026-09-30"],
            "exposure_amount": [100.0, 50.0, 20.0],
        }
    )


def test_clean_totals_tie_and_the_injected_break_is_explained() -> None:
    computed = aggregate_exposures(_frame())
    clean = reconcile(computed, reported_aggregate(computed, inject_break=False))
    assert clean.status == "PASS"
    assert clean.failed_slices == ()

    broken = reconcile(
        computed,
        reported_aggregate(computed, inject_break=True),
        injected_break=True,
    )
    assert broken.status == "FAIL"
    assert len(broken.failed_slices) == 1
    failed = broken.failed_slices[0]
    assert failed.legal_entity_id == RECONCILIATION_BREAK.legal_entity_id
    assert failed.currency == RECONCILIATION_BREAK.currency
    assert failed.difference == RECONCILIATION_BREAK.delta
    assert failed.transaction_total == 150.0


def test_downstream_node_inherits_a_staging_fail_and_a_reconciliation_fail() -> None:
    measured = node_statuses([_result("FAIL")], "PASS")
    assert measured["src_transactions"] == "NOT_MEASURED"
    assert measured["stg_transactions"] == "FAIL"
    assert measured["agg_exposure"] == "FAIL"

    tied = node_statuses([_result("PASS")], "FAIL")
    assert tied["stg_transactions"] == "PASS"
    assert tied["agg_exposure"] == "FAIL"

    clear = node_statuses([_result("PASS"), _result("PASS", "other")], "PASS")
    assert clear["stg_transactions"] == "PASS"
    assert clear["agg_exposure"] == "PASS"


def test_mermaid_and_networkx_come_from_the_metadata() -> None:
    frame, _reference, _manifest = generate_risk_dataset(n=SAMPLE_ROWS)
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    from governance_sentinel.rules import evaluate_rules

    results = evaluate_rules(frame, ruleset, {"counterparties": _reference})
    report = build_lineage(frame, results, inject_break=True)
    assert "core_banking.transactions" in report.mermaid
    assert "staging.risk_transactions" in report.mermaid
    assert "risk_mart.exposure_by_entity" in report.mermaid
    assert "NOT_MEASURED" in report.mermaid
    assert report.statuses["agg_exposure"] == "FAIL"
    summed = [item for item in report.column_flows if item.transform == "sum"]
    assert [item.column for item in summed] == ["exposure_amount"]

    graph = lineage_graph(report.statuses)
    assert list(graph.successors("src_transactions")) == ["stg_transactions"]
    assert list(graph.successors("stg_transactions")) == ["agg_exposure"]
    assert graph.nodes["agg_exposure"]["status"] == "FAIL"
    assert graph.nodes["stg_transactions"]["dataset"] == "staging.risk_transactions"


def test_openlineage_event_names_the_run_and_the_assertions(tmp_path: Path) -> None:
    frame = _frame()
    results = [_result("FAIL", "exposure_populated")]
    event = openlineage_event("run-1", frame, results)
    assert event["eventType"] == "COMPLETE"
    assert event["run"] == {"runId": "run-1"}
    job = event["job"]
    assert isinstance(job, dict)
    assert job["namespace"] == "governance-sentinel"
    assert job["name"] == "risk_exposure_audit"
    outputs = event["outputs"]
    assert isinstance(outputs, list)
    staging = outputs[0]
    assert isinstance(staging, dict)
    facets = staging["facets"]
    assert isinstance(facets, dict)
    metrics = facets["dataQualityMetrics"]
    assertions = facets["dataQualityAssertions"]
    assert isinstance(metrics, dict)
    column_metrics = metrics["columnMetrics"]
    assert isinstance(column_metrics, dict)
    assert "exposure_amount" in column_metrics
    assert isinstance(assertions, dict)
    assertion_rows = assertions["assertions"]
    assert isinstance(assertion_rows, list)
    assert assertion_rows[0]["assertion"] == "exposure_populated"
    assert assertion_rows[0]["success"] is False

    report = build_lineage(frame, results, inject_break=True)
    write_lineage_artifacts(report, event, tmp_path)
    written = json.loads((tmp_path / "openlineage.json").read_text(encoding="utf-8"))
    assert written["eventType"] == "COMPLETE"
    assert "flowchart LR" in (tmp_path / "lineage.mmd").read_text(encoding="utf-8")
    recon = pd.read_csv(tmp_path / "reconciliation.csv")
    assert set(recon["status"]) >= {"FAIL"}


def test_no_slices_is_a_failed_reconciliation() -> None:
    empty = aggregate_exposures(
        pd.DataFrame(
            {
                "legal_entity_id": [],
                "currency": [],
                "reporting_date": [],
                "exposure_amount": [],
            }
        )
    )
    result = reconcile(empty, empty)
    assert result.status == "FAIL"
    assert result.slices == ()
