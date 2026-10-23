"""Load the financial dataset used by the audit pipeline.

``mode='mock'`` builds five synthetic rows with one intentional failure mode
each, and writes them to ``csv_path``:

- Row 101 passes every check.
- Row 102 has a negative amount, so Accuracy fails (Principle 3).
- The third row has no transaction id, so Completeness fails (Principle 4),
  and a timestamp before the reference date, so Timeliness fails (Principle 5).
- Row 104 uses the currency code XYZ, so Validity fails. Validity is a
  data-quality dimension supporting Principle 3, not a BCBS 239 principle.
- Row 105 has an amount above the cap, so Accuracy fails (Principle 3).

``mode='real'`` reads a CSV from ``csv_path`` and checks its columns.
There is no database or API connector.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "transaction_id",
    "client_id",
    "amount",
    "currency",
    "timestamp",
    "age_category",
    "loan_approved",
)


def generate_mock_data(
    mode: str = "mock",
    csv_path: str = "raw_financial_data.csv",
) -> pd.DataFrame:
    """Return a mock frame, or a schema-checked CSV frame.

    Raises:
        ValueError: ``mode`` is not ``mock`` or ``real``, or the CSV schema
            does not match ``REQUIRED_COLUMNS``.
        FileNotFoundError: ``mode`` is ``real`` and ``csv_path`` does not exist.
    """
    if mode == "mock":
        return _load_mock(csv_path)
    if mode == "real":
        return _load_real(csv_path)
    raise ValueError(f"Unknown mode: {mode!r}. Use 'mock' or 'real'.")


def _load_mock(output_path: str) -> pd.DataFrame:
    """Build the synthetic demo file and save it."""
    logger.info("Mock mode: generating a synthetic dataset with intentional anomalies.")

    data = {
        "transaction_id": [101, 102, None, 104, 105],
        "client_id": ["C01", "C02", "C03", "C04", "C05"],
        "amount": [1500, -50, 3000, 4500, 9_999_999],
        "currency": ["EUR", "EUR", "USD", "XYZ", "EUR"],
        "timestamp": [
            "2023-10-01",
            "2023-10-01",
            "2022-01-01",
            "2023-10-02",
            "2023-10-03",
        ],
        # Demo labels only: 1 = unprivileged (called Senior here), 2 = privileged
        # (called Junior here). These are not a legal age classification.
        "age_category": [1, 2, 1, 1, 2],
        "loan_approved": [0, 1, 0, 0, 1],
    }
    frame = pd.DataFrame(data)
    frame.to_csv(output_path, index=False)
    logger.info("Mock dataset written to %s (%d rows).", output_path, len(frame))
    return frame


def _load_real(csv_path: str) -> pd.DataFrame:
    """Read a CSV and reject a file that is missing required columns."""
    logger.info("Real mode: loading data from %s.", csv_path)
    try:
        frame = pd.read_csv(csv_path)
    except FileNotFoundError:
        logger.error("CSV file not found: %s", csv_path)
        raise

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        logger.error("CSV is missing required columns: %s", missing)
        raise ValueError(
            f"CSV {csv_path!r} is missing required columns: {missing}. "
            f"Expected schema: {list(REQUIRED_COLUMNS)}."
        )

    logger.info("Real dataset loaded: %d rows, %d columns.", len(frame), len(frame.columns))
    return frame
