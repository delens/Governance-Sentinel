"""BCBS 239 data-quality checks on a small set of critical data elements.

Principle numbers follow the Basel Committee on Banking Supervision,
"Principles for effective risk data aggregation and risk reporting"
(BCBS 239, January 2013, https://www.bis.org/publ/bcbs239.pdf):

- Principle 3, Accuracy and Integrity (paragraphs 36-40): risk data is
  accurate and reliable. Paragraph 37 also expects a dictionary of concepts
  so data is defined consistently.
- Principle 4, Completeness (paragraphs 41-43): the bank can capture and
  aggregate all material risk data across the group.
- Principle 5, Timeliness (paragraphs 44-47): aggregate, up-to-date risk
  data is available in time for reporting. The deadline is bank-specific.
- Principle 6, Adaptability (paragraphs 48-50): ad hoc aggregation.
  Not implemented here.
- Principle 7, Accuracy (paragraphs 52-56): risk reports accurately convey
  aggregated data. This is a reporting principle, separate from Principle 3.
  Not implemented here.
- Principle 11, Distribution (paragraphs 72-73): reports reach the right
  people and stay confidential. Not implemented here.

Validity is a data-quality dimension (a value belongs to an allowed domain).
It is not a BCBS 239 principle. The currency whitelist supports Principle 3.
"""

from __future__ import annotations

import logging
from typing import Literal, TypedDict

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_AUDIT_COLUMNS: tuple[str, ...] = (
    "transaction_id",
    "amount",
    "currency",
    "timestamp",
)
AMOUNT_MIN = 0
AMOUNT_MAX = 1_000_000
APPROVED_CURRENCIES: tuple[str, ...] = ("EUR", "USD", "GBP")
# Demo stand-in for a bank-specific Principle 5 deadline. Not a T+1 SLA.
TIMELINESS_REFERENCE_DATE = "2023-01-01"

CHECK_NAMES: tuple[str, ...] = ("Completeness", "Accuracy", "Validity", "Timeliness")


class DimensionInfo(TypedDict):
    """How one DQ result maps onto BCBS 239."""

    principle: str
    principle_title: str
    kind: Literal["principle", "dq_dimension"]


# Official principle titles. Validity is a DQ dimension under Principle 3,
# not Principle 6 (Adaptability).
DQ_DIMENSIONS: dict[str, DimensionInfo] = {
    "Completeness": {
        "principle": "4",
        "principle_title": "Completeness",
        "kind": "principle",
    },
    "Accuracy": {
        "principle": "3",
        "principle_title": "Accuracy and Integrity",
        "kind": "principle",
    },
    "Validity": {
        "principle": "3",
        "principle_title": "Accuracy and Integrity",
        "kind": "dq_dimension",
    },
    "Timeliness": {
        "principle": "5",
        "principle_title": "Timeliness",
        "kind": "principle",
    },
}

# Principles a reader should not confuse with the four checks above.
NOT_IMPLEMENTED: tuple[tuple[str, str], ...] = (
    ("6", "Adaptability"),
    ("7", "Accuracy"),
    ("11", "Distribution"),
)


def run_bcbs239_audit(df: pd.DataFrame) -> dict[str, bool]:
    """Return PASS/FAIL for each DQ check.

    The input frame is copied and is not modified. An empty frame fails every
    check: there is no risk data to aggregate.

    Completeness is only the transaction identifier. Null amounts, currencies,
    and timestamps fail Accuracy, Validity, and Timeliness respectively.
    """
    audited = df.copy()

    missing = [column for column in REQUIRED_AUDIT_COLUMNS if column not in audited.columns]
    if missing:
        logger.error("Required column missing: %s. Audit stopped.", ", ".join(missing))
        raise ValueError(f"Required column not found: {missing}.")

    if audited.empty:
        logger.error("Input dataset is empty. All data-quality checks fail.")
        return dict.fromkeys(CHECK_NAMES, False)

    completeness_ok = bool(audited["transaction_id"].notna().all())
    logger.debug("Completeness check: %s", completeness_ok)

    amounts = audited["amount"]
    accuracy_ok = bool(
        amounts.notna().all() and ((amounts >= AMOUNT_MIN) & (amounts <= AMOUNT_MAX)).all()
    )
    logger.debug("Accuracy check: %s", accuracy_ok)

    currencies = audited["currency"]
    validity_ok = bool(currencies.notna().all() and currencies.isin(APPROVED_CURRENCIES).all())
    logger.debug("Validity check: %s", validity_ok)

    audited["timestamp"] = pd.to_datetime(audited["timestamp"], errors="coerce")
    reference = pd.Timestamp(TIMELINESS_REFERENCE_DATE)
    timeliness_ok = bool(
        audited["timestamp"].notna().all() and (audited["timestamp"] >= reference).all()
    )
    logger.debug("Timeliness check: %s", timeliness_ok)

    results = {
        "Completeness": completeness_ok,
        "Accuracy": accuracy_ok,
        "Validity": validity_ok,
        "Timeliness": timeliness_ok,
    }
    logger.info("BCBS 239 audit completed: %s", results)
    return results
