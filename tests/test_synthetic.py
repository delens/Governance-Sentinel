"""Seeded risk dataset: schema, defect counts, and a stable fairness gap."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bias_audit import FOUR_FIFTHS_HEURISTIC, audit_fairness
from governance_sentinel.synthetic import (
    DEFAULT_ROWS,
    DEFAULT_SEED,
    DEFECT_RATES,
    MAX_ROWS,
    MIN_ROWS,
    OUTLIER_EXPOSURE,
    SAMPLE_ROWS,
    TRANSACTION_COLUMNS,
    defect_count,
    generate_risk_dataset,
    write_risk_dataset,
)


def test_default_size_is_inside_the_portfolio_band() -> None:
    assert 1_000 <= DEFAULT_ROWS <= 10_000
    assert MIN_ROWS <= SAMPLE_ROWS < 1_000


def test_defect_rate_override_keeps_the_other_rates() -> None:
    _frame, _reference, manifest = generate_risk_dataset(
        n=100,
        seed=DEFAULT_SEED,
        defect_rates={"missing_transaction_id": 0.1},
    )
    assert manifest.counts["missing_transaction_id"] == 10
    assert manifest.rates["null_exposure"] == DEFECT_RATES["null_exposure"]
    with pytest.raises(ValueError, match="Unknown defect"):
        generate_risk_dataset(n=40, seed=1, defect_rates={"not_a_defect": 0.1})


def test_generation_is_reproducible() -> None:
    first, reference, manifest = generate_risk_dataset(n=400, seed=DEFAULT_SEED)
    second, _, _ = generate_risk_dataset(n=400, seed=DEFAULT_SEED)
    pd.testing.assert_frame_equal(first, second)
    assert manifest.seed == DEFAULT_SEED
    assert manifest.row_count == 400
    assert reference["counterparty_id"].is_unique
    assert len(reference) == 40


def test_schema_and_exact_defect_counts_at_the_default_size() -> None:
    frame, reference, manifest = generate_risk_dataset()
    assert list(frame.columns) == list(TRANSACTION_COLUMNS)
    assert len(frame) == DEFAULT_ROWS
    assert frame["record_id"].is_unique
    assert set(frame["legal_entity_id"]) == {"LE-FR", "LE-DE", "LE-UK", "LE-US", "LE-SG", "LE-CH"}
    present_currencies = {str(value) for value in frame["currency"].dropna().unique()}
    assert {"EUR", "USD", "GBP", "CHF", "JPY"} <= present_currencies

    for name, rate in DEFECT_RATES.items():
        assert manifest.counts[name] == defect_count(DEFAULT_ROWS, rate)
        assert manifest.counts[name] == int(round(rate * DEFAULT_ROWS))
        assert len(manifest.record_ids[name]) == manifest.counts[name]

    missing = set(manifest.record_ids["missing_transaction_id"])
    assert frame.loc[frame["record_id"].isin(missing), "transaction_id"].isna().all()
    present = frame.loc[~frame["record_id"].isin(missing), "transaction_id"]
    assert present.notna().all()

    duplicates = frame["transaction_id"].dropna()
    duplicated_ids = set(duplicates[duplicates.duplicated(keep=False)])
    failing = set(manifest.duplicate_failing_ids)
    assert set(frame.loc[frame["transaction_id"].isin(duplicated_ids), "record_id"]) == failing

    null_exposure = set(manifest.record_ids["null_exposure"])
    negative = set(manifest.record_ids["negative_exposure"])
    outliers = set(manifest.record_ids["outlier_exposure"])
    assert null_exposure.isdisjoint(negative)
    assert null_exposure.isdisjoint(outliers)
    outlier_amounts = frame.loc[frame["record_id"].isin(outliers), "exposure_amount"]
    assert outlier_amounts.eq(OUTLIER_EXPOSURE).all()
    assert frame.loc[frame["record_id"].isin(negative), "exposure_amount"].lt(0).all()

    orphans = set(manifest.record_ids["orphan_counterparty"])
    orphan_ids = set(frame.loc[frame["record_id"].isin(orphans), "counterparty_id"])
    assert orphan_ids.isdisjoint(set(reference["counterparty_id"]))
    assert frame["counterparty_id"].dropna().str.startswith("CP-").all()


def test_fairness_groups_are_large_and_below_the_heuristic() -> None:
    frame, _, manifest = generate_risk_dataset()
    result = audit_fairness(frame)
    assert result.unprivileged_count >= 1_500
    assert result.privileged_count >= 1_500
    assert result.rows_excluded == (
        manifest.counts["null_age_category"] + manifest.counts["null_loan_approved"]
    )
    assert result.rows_in_other_groups == 0
    assert result.ratio < FOUR_FIFTHS_HEURISTIC
    assert result.status == "FAIL"
    assert 0.60 <= result.ratio <= 0.78


def test_rejects_a_frame_outside_the_supported_range() -> None:
    with pytest.raises(ValueError, match="between"):
        generate_risk_dataset(n=MIN_ROWS - 1)
    with pytest.raises(ValueError, match="between"):
        generate_risk_dataset(n=MAX_ROWS + 1)


def test_write_roundtrip_keeps_the_orphan_and_the_null(tmp_path: Path) -> None:
    transactions = tmp_path / "transactions.csv"
    counterparties = tmp_path / "counterparties.csv"
    manifest = write_risk_dataset(transactions, counterparties, n=SAMPLE_ROWS, seed=DEFAULT_SEED)
    loaded = pd.read_csv(transactions)
    reference = pd.read_csv(counterparties)
    assert len(loaded) == SAMPLE_ROWS
    assert list(loaded.columns) == list(TRANSACTION_COLUMNS)
    assert len(reference) == 40
    missing = manifest.record_ids["missing_transaction_id"]
    if missing:
        assert loaded.loc[loaded["record_id"].isin(missing), "transaction_id"].isna().all()
    result = audit_fairness(loaded)
    assert result.unprivileged_count > 0
    assert result.privileged_count > 0
