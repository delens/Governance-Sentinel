"""PDF content, UTC timestamp, and core-font safety."""

from __future__ import annotations

import logging
import os
import time
import warnings
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import pytest
from pypdf import PdfReader

from bias_audit import FOUR_FIFTHS_HEURISTIC
from governance_sentinel import __version__
from governance_sentinel.logging_config import UtcFormatter
from governance_sentinel.models import FairnessResult, RuleResult
from reporter import DI_THRESHOLD, FRAMEWORK_VERSION, create_pdf_report


def _text(path: Path) -> str:
    reader = PdfReader(str(path))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(raw.split())


def _rule(**overrides: object) -> RuleResult:
    payload: dict[str, object] = {
        "rule_id": "txn_id_populated",
        "cde": "transaction_id",
        "column": "transaction_id",
        "dimension": "completeness",
        "rule_type": "not_null",
        "description": "transaction_id is populated.",
        "remediation": "Backfill the identifier.",
        "records_checked": 100,
        "records_failed": 2,
        "pass_pct": 98.0,
        "threshold": 99.5,
        "status": "FAIL",
        "sample_failing_ids": ("R000001", "R000002"),
        "failing_ids": ("R000001", "R000002"),
        "owner": "Group Risk Data Office",
        "steward": "Transaction Data Steward",
        "principle": "4",
        "principle_title": "Completeness",
        "detail": "",
    }
    payload.update(overrides)
    return RuleResult(**payload)  # type: ignore[arg-type]


def _passing_rule() -> RuleResult:
    return _rule(
        status="PASS",
        records_failed=0,
        pass_pct=100,
        failing_ids=(),
        sample_failing_ids=(),
    )


def _fairness(ratio: float) -> FairnessResult:
    status = "PASS" if ratio >= FOUR_FIFTHS_HEURISTIC else "FAIL"
    return FairnessResult(
        ratio=ratio,
        unprivileged_rate=0.54,
        privileged_rate=0.78,
        unprivileged_count=1800,
        privileged_count=1800,
        unprivileged_positives=972,
        privileged_positives=1404,
        rows_excluded=24,
        rows_in_other_groups=0,
        threshold=FOUR_FIFTHS_HEURISTIC,
        status=status,
        protected_attribute="age_category",
        unprivileged_value=1,
        privileged_value=2,
    )


def test_version_constant_matches_the_package() -> None:
    assert FRAMEWORK_VERSION == "2.0.0"
    assert FRAMEWORK_VERSION == __version__
    assert DI_THRESHOLD == FOUR_FIFTHS_HEURISTIC


def test_pdf_states_the_scorecard_and_the_heuristic(tmp_path: Path) -> None:
    path = tmp_path / "audit.pdf"
    rules = [
        _rule(),
        _rule(
            rule_id="exposure_outlier",
            cde="exposure_amount",
            column="exposure_amount",
            dimension="accuracy",
            rule_type="outlier",
            principle="3",
            principle_title="Accuracy and Integrity",
            description="IQR screen on exposure_amount.",
            status="PASS",
            records_failed=0,
            pass_pct=100.0,
            threshold=99.5,
            sample_failing_ids=(),
            failing_ids=(),
        ),
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        create_pdf_report(
            rules,
            _fairness(0.0),
            run_id="abc123",
            dataset_sha256="a" * 64,
            row_count=4000,
            output_path=str(path),
            dataset_name="transactions.csv",
        )

    text = _text(path)
    assert "run_id: abc123" in text
    assert f"SHA-256: {'a' * 64}" in text
    assert "Records: 4000" in text
    assert "txn_id_populated" in text
    assert "98.00" in text
    assert "99.50" in text
    assert "Sample failing ids: R000001, R000002" in text
    assert "completeness: FAIL" in text
    assert "not a BCBS 239 principle" in text
    assert "T+1" in text
    assert "interquartile-range" in text
    assert "Principle 6 (Adaptability)" in text
    assert "Principle 7 (Accuracy)" in text
    assert "Principle 11 (Distribution)" in text
    assert "four-fifths" in text
    assert "not an EU legal requirement" in text
    assert "FAIL against the four-fifths heuristic" in text
    assert "Disparate impact ratio: 0.0000" in text
    assert "Rows excluded (missing group or label): 24" in text
    for banned in ("\u2713", "\u2717", "\u2014", "\u2500"):
        assert banned not in text
    assert path.read_bytes().startswith(b"%PDF")


def test_di_threshold_boundary(tmp_path: Path) -> None:
    passing = tmp_path / "pass.pdf"
    failing = tmp_path / "fail.pdf"
    create_pdf_report(
        [_passing_rule()],
        _fairness(DI_THRESHOLD),
        run_id="pass",
        dataset_sha256="b" * 64,
        row_count=10,
        output_path=str(passing),
    )
    create_pdf_report(
        [_rule()],
        _fairness(DI_THRESHOLD - 0.01),
        run_id="fail",
        dataset_sha256="c" * 64,
        row_count=10,
        output_path=str(failing),
    )
    assert "PASS against the four-fifths heuristic" in _text(passing)
    assert "FAIL against the four-fifths heuristic" in _text(failing)


def test_timestamp_is_timezone_aware_utc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FixedClock:
        @staticmethod
        def now(tz: tzinfo | None = None) -> datetime:
            if tz is None or tz.utcoffset(None) != timedelta(0):
                raise AssertionError("report timestamp must use timezone-aware UTC")
            return datetime(2026, 5, 24, 12, 30, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("reporter.datetime", FixedClock)
    path = tmp_path / "audit.pdf"
    create_pdf_report(
        [_passing_rule()],
        _fairness(1.0),
        run_id="clock",
        dataset_sha256="d" * 64,
        row_count=10,
        output_path=str(path),
    )
    assert "Generated: 2026-05-24 12:30:00 UTC" in _text(path)
    assert FRAMEWORK_VERSION in _text(path)


def test_log_formatter_formats_utc_even_if_local_zone_is_not() -> None:
    original = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp()
        record = logging.makeLogRecord(
            {
                "name": "test",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "msg": "hello",
                "created": created,
            }
        )
        utc_formatter = UtcFormatter("%(asctime)s", datefmt="%Y-%m-%d %H:%M:%S")
        local_formatter = logging.Formatter("%(asctime)s", datefmt="%Y-%m-%d %H:%M:%S")
        assert utc_formatter.format(record) == "2026-01-02 03:04:05"
        assert local_formatter.format(record) != "2026-01-02 03:04:05"
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()
