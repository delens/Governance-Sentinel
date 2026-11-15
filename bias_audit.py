"""Disparate-impact ratio on a synthetic credit-approval label.

The ratio illustrates a bias measure discussed alongside EU AI Act Article 10
(data and data governance for high-risk systems). It is not an Article 13
transparency file and it is not a conformity assessment.

``age_category`` 1 is the unprivileged group in this demo (labelled
"40_and_over"). ``age_category`` 2 is the privileged group (labelled
"under_40"). Those labels belong to the synthetic file. They are not a legal
age classification.

The 0.80 cutoff used by the report is the US EEOC four-fifths rule of thumb.
It is a heuristic for this demo. The EU AI Act does not set that number, and
this prototype does not treat 0.80 as an EU requirement.

Rows are removed only when ``age_category`` or ``loan_approved`` is missing.
A null in any other column, including ``transaction_id``, stays in the metric.
An empty unprivileged or privileged group raises ``ValueError`` instead of
returning a silent NaN from AIF360.
"""

from __future__ import annotations

import logging

import pandas as pd
from aif360.datasets import BinaryLabelDataset
from aif360.metrics import BinaryLabelDatasetMetric

from governance_sentinel.models import FairnessResult

logger = logging.getLogger(__name__)

PROTECTED_ATTRIBUTE = "age_category"
LABEL = "loan_approved"
UNPRIVILEGED_VALUE = 1
PRIVILEGED_VALUE = 2
UNPRIVILEGED_LABEL = "40_and_over"
PRIVILEGED_LABEL = "under_40"

# US EEOC four-fifths rule, used only as a heuristic cutoff.
FOUR_FIFTHS_HEURISTIC = 0.80


def audit_fairness(df: pd.DataFrame) -> FairnessResult:
    """Measure disparate impact without dropping rows for unrelated nulls.

    AIF360 supplies the ratio when both groups are non-empty and the
    privileged selection rate is positive. A zero privileged rate makes the
    ratio undefined (division by zero). The result then carries a NaN ratio
    and status ``UNDEFINED`` rather than a pass or a fail.

    Raises:
        ValueError: a required column is missing, no row keeps both fields,
            or either demo group has no complete row.
    """
    missing = [column for column in (PROTECTED_ATTRIBUTE, LABEL) if column not in df.columns]
    if missing:
        raise ValueError(f"Fairness audit requires columns {missing}.")

    # Subset first. dropna() on the whole frame would discard a row because
    # an unrelated column is null, which hides the row from the metric.
    subset = df.loc[:, [PROTECTED_ATTRIBUTE, LABEL]]
    incomplete = subset.isna().any(axis=1)
    rows_excluded = int(incomplete.sum())
    complete = subset.loc[~incomplete].astype(float)
    if complete.empty:
        raise ValueError(
            f"Fairness audit needs at least one row with both {PROTECTED_ATTRIBUTE} and {LABEL}."
        )

    unprivileged_mask = complete[PROTECTED_ATTRIBUTE] == float(UNPRIVILEGED_VALUE)
    privileged_mask = complete[PROTECTED_ATTRIBUTE] == float(PRIVILEGED_VALUE)
    unprivileged = complete.loc[unprivileged_mask, LABEL]
    privileged = complete.loc[privileged_mask, LABEL]
    rows_in_other_groups = int((~unprivileged_mask & ~privileged_mask).sum())

    if unprivileged.empty or privileged.empty:
        raise ValueError(
            "Fairness audit needs at least one complete row in both groups "
            f"(unprivileged {UNPRIVILEGED_VALUE}, privileged {PRIVILEGED_VALUE}). "
            f"Counts: unprivileged={len(unprivileged)}, privileged={len(privileged)}."
        )

    unprivileged_positives = int(unprivileged.sum())
    privileged_positives = int(privileged.sum())
    unprivileged_rate = unprivileged_positives / len(unprivileged)
    privileged_rate = privileged_positives / len(privileged)

    if privileged_rate == 0.0:
        ratio = float("nan")
        status = "UNDEFINED"
        logger.warning(
            "Disparate impact is undefined: the privileged group has no positive labels "
            "(unprivileged rate %.4f, n=%d; privileged n=%d).",
            unprivileged_rate,
            len(unprivileged),
            len(privileged),
        )
    else:
        ratio = _aif360_ratio(complete)
        status = "PASS" if ratio >= FOUR_FIFTHS_HEURISTIC else "FAIL"
        logger.info(
            "Disparate impact (unprivileged / privileged): %.4f "
            "(unprivileged %.4f on n=%d, privileged %.4f on n=%d, excluded %d). "
            "Cutoff %.2f is the US EEOC four-fifths heuristic, not an EU requirement.",
            ratio,
            unprivileged_rate,
            len(unprivileged),
            privileged_rate,
            len(privileged),
            rows_excluded,
            FOUR_FIFTHS_HEURISTIC,
        )

    return FairnessResult(
        ratio=ratio,
        unprivileged_rate=unprivileged_rate,
        privileged_rate=privileged_rate,
        unprivileged_count=int(len(unprivileged)),
        privileged_count=int(len(privileged)),
        unprivileged_positives=unprivileged_positives,
        privileged_positives=privileged_positives,
        rows_excluded=rows_excluded,
        rows_in_other_groups=rows_in_other_groups,
        threshold=FOUR_FIFTHS_HEURISTIC,
        status=status,
        protected_attribute=PROTECTED_ATTRIBUTE,
        unprivileged_value=UNPRIVILEGED_VALUE,
        privileged_value=PRIVILEGED_VALUE,
    )


def run_fairness_audit(df: pd.DataFrame) -> float:
    """Return the disparate-impact ratio. See ``audit_fairness`` for the rules."""
    return audit_fairness(df).ratio


def _aif360_ratio(complete: pd.DataFrame) -> float:
    dataset = BinaryLabelDataset(
        df=complete.reset_index(drop=True),
        label_names=[LABEL],
        protected_attribute_names=[PROTECTED_ATTRIBUTE],
    )
    metric = BinaryLabelDatasetMetric(
        dataset,
        unprivileged_groups=[{PROTECTED_ATTRIBUTE: UNPRIVILEGED_VALUE}],
        privileged_groups=[{PROTECTED_ATTRIBUTE: PRIVILEGED_VALUE}],
    )
    return float(metric.disparate_impact())
