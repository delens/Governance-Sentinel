"""Expected PASS/FAIL for each BCBS 239 check, including the synthetic file."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data_loader import generate_mock_data
from validators import (
    AMOUNT_MAX,
    CHECK_NAMES,
    DQ_DIMENSIONS,
    NOT_IMPLEMENTED,
    TIMELINESS_REFERENCE_DATE,
    run_bcbs239_audit,
)

ALL_PASS: dict[str, bool] = dict.fromkeys(CHECK_NAMES, True)


def _row(**overrides: object) -> pd.DataFrame:
    record: dict[str, object] = {
        "transaction_id": 101,
        "amount": 1500,
        "currency": "EUR",
        "timestamp": "2023-10-01",
    }
    record.update(overrides)
    return pd.DataFrame([record])


def _expect(**flags: bool) -> dict[str, bool]:
    expected = dict(ALL_PASS)
    expected.update(flags)
    return expected


def test_principle_numbers_follow_bcbs239() -> None:
    assert DQ_DIMENSIONS["Completeness"]["principle"] == "4"
    assert DQ_DIMENSIONS["Completeness"]["principle_title"] == "Completeness"
    assert DQ_DIMENSIONS["Accuracy"]["principle"] == "3"
    assert DQ_DIMENSIONS["Accuracy"]["principle_title"] == "Accuracy and Integrity"
    assert DQ_DIMENSIONS["Validity"]["principle"] == "3"
    assert DQ_DIMENSIONS["Validity"]["kind"] == "dq_dimension"
    assert DQ_DIMENSIONS["Timeliness"]["principle"] == "5"
    assert DQ_DIMENSIONS["Timeliness"]["principle_title"] == "Timeliness"
    assert {number for number, _title in NOT_IMPLEMENTED} == {"6", "7", "11"}
    mapped = {info["principle"] for info in DQ_DIMENSIONS.values()}
    assert mapped.isdisjoint({"6", "11"})


def test_clean_row_passes_every_check() -> None:
    assert run_bcbs239_audit(_row()) == ALL_PASS


def test_mock_dataset_fails_every_check(tmp_path: Path) -> None:
    frame = generate_mock_data(csv_path=str(tmp_path / "mock.csv"))
    assert run_bcbs239_audit(frame) == dict.fromkeys(CHECK_NAMES, False)


def test_each_mock_row_has_the_designed_result(tmp_path: Path) -> None:
    frame = generate_mock_data(csv_path=str(tmp_path / "mock.csv"))
    expected_rows = [
        ALL_PASS,
        _expect(Accuracy=False),
        _expect(Completeness=False, Timeliness=False),
        _expect(Validity=False),
        _expect(Accuracy=False),
    ]
    for index, expected in enumerate(expected_rows):
        result = run_bcbs239_audit(frame.iloc[[index]])
        assert result == expected, f"row {index}"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"transaction_id": None}, _expect(Completeness=False)),
        ({"amount": -50}, _expect(Accuracy=False)),
        ({"amount": None}, _expect(Accuracy=False)),
        ({"amount": AMOUNT_MAX + 1}, _expect(Accuracy=False)),
        ({"amount": 0}, ALL_PASS),
        ({"amount": AMOUNT_MAX}, ALL_PASS),
        ({"currency": "XYZ"}, _expect(Validity=False)),
        ({"currency": None}, _expect(Validity=False)),
        ({"currency": "eur"}, _expect(Validity=False)),
        ({"timestamp": "2022-12-31"}, _expect(Timeliness=False)),
        ({"timestamp": TIMELINESS_REFERENCE_DATE}, ALL_PASS),
        ({"timestamp": None}, _expect(Timeliness=False)),
        ({"timestamp": "not-a-date"}, _expect(Timeliness=False)),
    ],
)
def test_single_defect_fails_only_its_check(
    overrides: dict[str, object],
    expected: dict[str, bool],
) -> None:
    assert run_bcbs239_audit(_row(**overrides)) == expected


def test_null_amount_does_not_fail_completeness() -> None:
    result = run_bcbs239_audit(_row(amount=None))
    assert result["Completeness"] is True
    assert result["Accuracy"] is False


def test_missing_column_raises() -> None:
    frame = pd.DataFrame({"amount": [10]})
    with pytest.raises(ValueError, match="transaction_id"):
        run_bcbs239_audit(frame)


def test_empty_frame_fails_every_check() -> None:
    frame = pd.DataFrame(columns=["transaction_id", "amount", "currency", "timestamp"])
    assert run_bcbs239_audit(frame) == dict.fromkeys(CHECK_NAMES, False)


def test_audit_does_not_mutate_the_input(tmp_path: Path) -> None:
    frame = generate_mock_data(csv_path=str(tmp_path / "mock.csv"))
    original = frame.copy(deep=True)
    run_bcbs239_audit(frame)
    pd.testing.assert_frame_equal(frame, original)
