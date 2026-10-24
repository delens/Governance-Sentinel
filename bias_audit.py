"""Disparate-impact ratio on a synthetic credit-approval label.

The ratio illustrates a bias measure discussed alongside EU AI Act Article 10
(data and data governance for high-risk systems). It is not an Article 13
transparency file and it is not a conformity assessment.

``age_category`` 1 is the unprivileged group in this demo (labelled Senior).
``age_category`` 2 is the privileged group (labelled Junior). The 0.80 cutoff
used by the report is the US EEOC four-fifths rule. The EU AI Act does not
set that number.
"""

from __future__ import annotations

import logging

import pandas as pd
from aif360.datasets import BinaryLabelDataset
from aif360.metrics import BinaryLabelDatasetMetric

logger = logging.getLogger(__name__)

PROTECTED_ATTRIBUTE = "age_category"
LABEL = "loan_approved"
UNPRIVILEGED_VALUE = 1
PRIVILEGED_VALUE = 2


def run_fairness_audit(df: pd.DataFrame) -> float:
    """Return unprivileged selection rate divided by privileged selection rate.

    Rows are dropped only when ``age_category`` or ``loan_approved`` is null.
    A null transaction id does not remove a row from this metric.
    """
    missing = [column for column in (PROTECTED_ATTRIBUTE, LABEL) if column not in df.columns]
    if missing:
        raise ValueError(f"Fairness audit requires columns {missing}.")

    numeric = df.loc[:, [PROTECTED_ATTRIBUTE, LABEL]].dropna().astype(float)
    if numeric.empty:
        raise ValueError(
            "Fairness audit needs at least one row with both age_category and loan_approved."
        )

    dataset = BinaryLabelDataset(
        df=numeric,
        label_names=[LABEL],
        protected_attribute_names=[PROTECTED_ATTRIBUTE],
    )
    metric = BinaryLabelDatasetMetric(
        dataset,
        unprivileged_groups=[{PROTECTED_ATTRIBUTE: UNPRIVILEGED_VALUE}],
        privileged_groups=[{PROTECTED_ATTRIBUTE: PRIVILEGED_VALUE}],
    )
    score = float(metric.disparate_impact())
    logger.info("Disparate impact (unprivileged / privileged): %.4f", score)
    return score
