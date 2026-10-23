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

from main import UtcFormatter
from reporter import DI_THRESHOLD, FRAMEWORK_VERSION, create_pdf_report
from validators import CHECK_NAMES

ALL_FAIL = dict.fromkeys(CHECK_NAMES, False)
ALL_PASS = dict.fromkeys(CHECK_NAMES, True)


def _text(path: Path) -> str:
    reader = PdfReader(str(path))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(raw.split())


def test_version_constant_is_1_2_0() -> None:
    assert FRAMEWORK_VERSION == "1.2.0"


def test_pdf_states_the_corrected_principle_mapping(tmp_path: Path) -> None:
    path = tmp_path / "audit.pdf"
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        create_pdf_report(ALL_FAIL, 0.0, output_path=str(path))

    text = _text(path)
    assert "[Principle 4 - Completeness] Completeness: FAIL" in text
    assert "[Principle 3 - Accuracy and Integrity] Accuracy: FAIL" in text
    assert "[Principle 3 - Accuracy and Integrity] Validity: FAIL" in text
    assert "[Principle 5 - Timeliness] Timeliness: FAIL" in text
    assert "not a BCBS 239 principle" in text
    assert "not a T+1 control" in text
    assert "not a statistical outlier test" in text
    assert "Principle 6 (Adaptability)" in text
    assert "Principle 7 (Accuracy)" in text
    assert "Principle 11 (Distribution)" in text
    assert "Principle 3 - Completeness" not in text
    assert "Principle 4 - Accuracy" not in text
    assert "Principle 6 - Validity" not in text
    assert "Principle 11 - Timeliness" not in text
    assert "DI = 0.00" in text
    assert f"{DI_THRESHOLD:.2f}" in text
    assert "CRITICAL REMEDIATION REQUIRED" in text
    for banned in ("\u2713", "\u2717", "\u2014", "\u2500"):
        assert banned not in text
    assert path.read_bytes().startswith(b"%PDF")


def test_di_threshold_boundary(tmp_path: Path) -> None:
    passing = tmp_path / "pass.pdf"
    failing = tmp_path / "fail.pdf"
    create_pdf_report(ALL_PASS, DI_THRESHOLD, output_path=str(passing))
    create_pdf_report(ALL_PASS, DI_THRESHOLD - 0.01, output_path=str(failing))
    assert "Status: PASS" in _text(passing)
    assert "CRITICAL REMEDIATION REQUIRED" in _text(failing)


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
    create_pdf_report(ALL_PASS, 1.0, output_path=str(path))
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
