"""Declarative YAML rules: each rule type, the threshold, and the seeded file."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from governance_sentinel.models import Rule, RuleResult, RuleSet
from governance_sentinel.principles import PRINCIPLE_TITLES
from governance_sentinel.rules import evaluate_rules, load_rules
from governance_sentinel.synthetic import DEFAULT_SEED, REPORTING_DATE, generate_risk_dataset
from validators import DQ_DIMENSIONS

REPO = Path(__file__).resolve().parents[1]
RULES_PATH = REPO / "rules" / "dq_rules.yml"


def _rule(**overrides: Any) -> Rule:
    rule = Rule(
        rule_id="demo",
        cde="amount",
        column="amount",
        dimension="accuracy",
        rule_type="not_null",
        threshold=100.0,
        owner="Group Risk Data Office",
        steward="Credit Risk Data Steward",
        principle="3",
        principle_title="Accuracy and Integrity",
        description="Demo rule.",
        remediation="Fix the row.",
        parameters={},
    )
    return replace(rule, **overrides)


def _run(
    frame: pd.DataFrame,
    rule: Rule,
    references: dict[str, pd.DataFrame] | None = None,
) -> RuleResult:
    ruleset = RuleSet(version=1, id_column="record_id", rules=(rule,))
    return evaluate_rules(frame, ruleset, references)[0]


def test_yaml_rules_cite_official_titles() -> None:
    ruleset = load_rules(RULES_PATH)
    assert ruleset.version == 1
    assert ruleset.id_column == "record_id"
    kinds = {rule.rule_type for rule in ruleset.rules}
    assert {"referential", "timeliness", "outlier"} <= kinds
    assert {rule.principle_title for rule in ruleset.rules} <= set(PRINCIPLE_TITLES.values())
    assert DQ_DIMENSIONS["Accuracy"]["principle_title"] == PRINCIPLE_TITLES["3"]
    assert DQ_DIMENSIONS["Completeness"]["principle_title"] == PRINCIPLE_TITLES["4"]
    assert DQ_DIMENSIONS["Timeliness"]["principle_title"] == PRINCIPLE_TITLES["5"]


def test_yaml_rejects_a_mismatched_principle_title(tmp_path: Path) -> None:
    path = tmp_path / "rules.yml"
    path.write_text(
        """
version: 1
id_column: record_id
rules:
  - id: bad
    cde: amount
    column: amount
    dimension: accuracy
    rule_type: not_null
    parameters: {}
    threshold: 100
    owner: Group Risk Data Office
    steward: Credit Risk Data Steward
    principle: "3"
    principle_title: Completeness
    description: Wrong title.
    remediation: Fix it.
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        load_rules(path)


def test_not_null_range_domain_and_unique() -> None:
    frame = pd.DataFrame(
        {
            "record_id": ["R1", "R2", "R3", "R4"],
            "transaction_id": ["T1", "T1", None, "T4"],
            "amount": [10, -5, None, 40],
            "currency": ["EUR", "XYZ", None, "USD"],
        }
    )
    unique = _run(
        frame,
        _rule(
            rule_id="unique",
            column="transaction_id",
            cde="transaction_id",
            rule_type="unique",
        ),
    )
    assert unique.records_checked == 3
    assert unique.records_failed == 2
    assert set(unique.failing_ids) == {"R1", "R2"}

    ranged = _run(frame, _rule(rule_type="range", parameters={"min": 0}, threshold=50))
    assert ranged.records_checked == 3
    assert ranged.failing_ids == ("R2",)
    assert ranged.status == "PASS"

    domain = _run(
        frame,
        _rule(
            rule_id="currency",
            column="currency",
            cde="currency",
            dimension="validity",
            rule_type="domain",
            parameters={"allowed": ["EUR", "USD", "GBP"]},
        ),
    )
    assert domain.records_checked == 3
    assert domain.failing_ids == ("R2",)


def test_threshold_fails_when_the_pass_rate_is_short() -> None:
    frame = pd.DataFrame({"record_id": ["R1", "R2"], "amount": [1, None]})
    failed = _run(frame, _rule(threshold=100))
    passed = _run(frame, _rule(rule_id="loose", threshold=50))
    assert failed.status == "FAIL"
    assert failed.pass_pct == pytest.approx(50.0)
    assert passed.status == "PASS"


def test_empty_frame_fails_and_a_missing_column_raises() -> None:
    empty = pd.DataFrame(columns=["record_id", "amount"])
    result = _run(empty, _rule())
    assert result.status == "FAIL"
    assert result.records_checked == 0
    with pytest.raises(ValueError, match="amount"):
        _run(pd.DataFrame({"record_id": ["R1"]}), _rule())


def test_sample_failing_ids_are_capped() -> None:
    frame = pd.DataFrame({"record_id": [f"R{index}" for index in range(6)], "amount": [None] * 6})
    result = _run(frame, _rule(threshold=100))
    assert len(result.sample_failing_ids) == 5
    assert len(result.failing_ids) == 6


def test_referential_flags_orphans_and_blanks() -> None:
    frame = pd.DataFrame(
        {
            "record_id": ["R1", "R2", "R3"],
            "counterparty_id": ["CP-001", "CP-ORPHAN-0001", None],
        }
    )
    reference = pd.DataFrame({"counterparty_id": ["CP-001", "CP-002"]})
    result = _run(
        frame,
        _rule(
            rule_id="counterparty_known",
            column="counterparty_id",
            cde="counterparty_id",
            rule_type="referential",
            parameters={
                "reference_dataset": "counterparties",
                "reference_column": "counterparty_id",
            },
        ),
        {"counterparties": reference},
    )
    assert result.records_checked == 3
    assert set(result.failing_ids) == {"R2", "R3"}


def test_timeliness_is_a_business_day_t_plus_1() -> None:
    frame = pd.DataFrame(
        {
            "record_id": ["same", "next", "plus_two", "before", "blank"],
            "reporting_date": [REPORTING_DATE] * 5,
            "availability_date": [
                "2026-09-30",
                "2026-10-01",
                "2026-10-02",
                "2026-09-29",
                "not-a-date",
            ],
        }
    )
    result = _run(
        frame,
        _rule(
            rule_id="availability_t_plus_1",
            column="availability_date",
            cde="availability_date",
            dimension="timeliness",
            rule_type="timeliness",
            principle="5",
            principle_title="Timeliness",
            parameters={
                "event_column": "reporting_date",
                "available_column": "availability_date",
                "max_lag_business_days": 1,
            },
        ),
    )
    assert set(result.failing_ids) == {"plus_two", "before", "blank"}
    assert "business" in result.detail.lower()


def test_outlier_fence_flags_the_spike_only() -> None:
    amounts = [10, 12, 11, 13, 10, 12, 11, 14, 1_000_000, -50]
    frame = pd.DataFrame(
        {"record_id": [f"R{index}" for index in range(len(amounts))], "amount": amounts}
    )
    result = _run(
        frame,
        _rule(
            rule_id="exposure_outlier",
            rule_type="outlier",
            parameters={"method": "iqr", "k": 1.5, "lower_bound": 0},
            threshold=50,
        ),
    )
    assert result.failing_ids == ("R8",)
    assert result.records_checked == 9


def test_seeded_file_matches_the_injected_defects() -> None:
    frame, reference, manifest = generate_risk_dataset(seed=DEFAULT_SEED)
    ruleset = load_rules(RULES_PATH)
    original = frame.copy(deep=True)
    evaluated = evaluate_rules(frame, ruleset, {"counterparties": reference})
    results = {item.rule_id: item for item in evaluated}
    pd.testing.assert_frame_equal(frame, original)

    def ids(name: str) -> set[str]:
        return set(manifest.record_ids[name])

    assert set(results["txn_id_populated"].failing_ids) == ids("missing_transaction_id")
    assert set(results["txn_id_unique"].failing_ids) == set(manifest.duplicate_failing_ids)
    assert set(results["exposure_populated"].failing_ids) == ids("null_exposure")
    assert set(results["exposure_non_negative"].failing_ids) == ids("negative_exposure")
    assert set(results["exposure_outlier"].failing_ids) == ids("outlier_exposure")
    assert set(results["currency_domain"].failing_ids) == ids("invalid_currency")
    orphans = ids("orphan_counterparty") | ids("null_counterparty")
    assert set(results["counterparty_known"].failing_ids) == orphans
    late = ids("late_availability") | ids("unparseable_availability")
    assert set(results["availability_t_plus_1"].failing_ids) == late

    expected = {
        "txn_id_populated": "FAIL",
        "txn_id_unique": "FAIL",
        "exposure_populated": "FAIL",
        "exposure_non_negative": "FAIL",
        "exposure_outlier": "FAIL",
        "currency_populated": "PASS",
        "currency_domain": "FAIL",
        "rating_populated": "PASS",
        "rating_domain": "PASS",
        "legal_entity_domain": "PASS",
        "product_domain": "PASS",
        "counterparty_known": "FAIL",
        "availability_t_plus_1": "FAIL",
        "reporting_date_populated": "PASS",
    }
    assert {rule_id: item.status for rule_id, item in results.items()} == expected


def test_rules_do_not_use_a_full_frame_dropna() -> None:
    frame = pd.DataFrame({"record_id": ["R1", "R2"], "amount": [10, 12], "unrelated": [None, None]})
    result = _run(frame, _rule(rule_type="range", parameters={"min": 0, "max": 20}))
    assert result.records_checked == 2
    assert result.status == "PASS"
