"""Mock and CSV loading."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data_loader import REQUIRED_COLUMNS, generate_mock_data


def test_unknown_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown mode"):
        generate_mock_data(mode="warehouse", csv_path=str(tmp_path / "x.csv"))


def test_real_mode_reads_the_mock_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "raw.csv"
    mock = generate_mock_data(csv_path=str(csv_path))
    loaded = generate_mock_data(mode="real", csv_path=str(csv_path))
    assert list(loaded.columns) == list(REQUIRED_COLUMNS)
    assert len(loaded) == len(mock)


def test_real_mode_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        generate_mock_data(mode="real", csv_path=str(tmp_path / "missing.csv"))


def test_real_mode_missing_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "partial.csv"
    pd.DataFrame({"transaction_id": [1]}).to_csv(csv_path, index=False)
    with pytest.raises(ValueError, match="client_id"):
        generate_mock_data(mode="real", csv_path=str(csv_path))
