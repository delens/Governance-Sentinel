"""Disparate impact on the synthetic approval label."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from bias_audit import audit_fairness, run_fairness_audit
from data_loader import generate_mock_data


def test_mock_data_has_total_exclusion(tmp_path: Path) -> None:
    frame = generate_mock_data(csv_path=str(tmp_path / "mock.csv"))
    assert run_fairness_audit(frame) == pytest.approx(0.0)


def test_balanced_groups_score_one() -> None:
    frame = pd.DataFrame(
        {
            "age_category": [1, 1, 2, 2],
            "loan_approved": [1, 0, 1, 0],
        }
    )
    assert run_fairness_audit(frame) == pytest.approx(1.0)


def test_null_transaction_id_stays_in_the_fairness_metric() -> None:
    frame = pd.DataFrame(
        {
            "transaction_id": [None, 2, 3, 4],
            "age_category": [1, 1, 2, 2],
            "loan_approved": [1, 0, 1, 0],
        }
    )
    assert run_fairness_audit(frame) == pytest.approx(1.0)


def test_missing_fairness_column_raises() -> None:
    frame = pd.DataFrame({"age_category": [1]})
    with pytest.raises(ValueError, match="loan_approved"):
        run_fairness_audit(frame)


def test_no_complete_fairness_rows_raises() -> None:
    frame = pd.DataFrame({"age_category": [None], "loan_approved": [1]})
    with pytest.raises(ValueError, match="at least one row"):
        run_fairness_audit(frame)


def test_empty_group_raises_instead_of_returning_nan() -> None:
    frame = pd.DataFrame({"age_category": [1, 1, 1], "loan_approved": [1, 0, 1]})
    with pytest.raises(ValueError, match="both groups"):
        run_fairness_audit(frame)


def test_nulls_in_other_columns_do_not_drop_the_row() -> None:
    frame = pd.DataFrame(
        {
            "transaction_id": [None, None, None, None],
            "exposure_amount": [None, None, None, None],
            "currency": [None, None, None, None],
            "age_category": [1, 1, 2, 2],
            "loan_approved": [1, 0, 1, 0],
        }
    )
    result = audit_fairness(frame)
    assert result.rows_excluded == 0
    assert result.ratio == pytest.approx(1.0)
    assert result.unprivileged_count == 2
    assert result.privileged_count == 2


def test_only_missing_protected_attribute_or_label_is_excluded() -> None:
    frame = pd.DataFrame(
        {
            "age_category": [1, None, 2, 2],
            "loan_approved": [1, 1, None, 0],
        }
    )
    result = audit_fairness(frame)
    assert result.rows_excluded == 2
    assert result.unprivileged_count == 1
    assert result.privileged_count == 1
    assert result.unprivileged_rate == pytest.approx(1.0)
    assert result.privileged_rate == pytest.approx(0.0)
    assert result.status == "UNDEFINED"
    assert math.isnan(result.ratio)


def test_zero_privileged_rate_is_undefined_not_a_pass() -> None:
    frame = pd.DataFrame(
        {
            "age_category": [1, 1, 2, 2],
            "loan_approved": [1, 1, 0, 0],
        }
    )
    result = audit_fairness(frame)
    assert result.status == "UNDEFINED"
    assert result.privileged_rate == 0.0
