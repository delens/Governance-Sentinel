"""Disparate impact on the synthetic approval label."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bias_audit import run_fairness_audit
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
