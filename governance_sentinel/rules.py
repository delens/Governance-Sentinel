"""Declarative data-quality rules loaded from YAML.

``threshold`` is the minimum pass percentage. A rule PASSes when at least one
record was checked and the pass percentage is greater than or equal to that
figure. An empty extract FAILs every rule: there is nothing to aggregate.

Null handling is per rule, not a silent ``dropna`` of the whole frame:

- ``not_null`` and ``referential`` check every row. A missing value fails.
- ``unique``, ``range``, ``domain``, and ``outlier`` check non-missing values.
  A missing value is left to the ``not_null`` rule on that column.
- ``outlier`` can also ignore values below ``lower_bound`` so a negative-amount
  rule and the IQR screen do not both claim the same defect.
- ``timeliness`` checks every row. An unparseable date fails.

The outlier screen is an interquartile-range fence. It is a heuristic for
review, not a risk limit and not an accounting-materiality test. The
timeliness rule compares the availability date with the reporting date in
business days (the numpy weekmask, with no holiday calendar). A lag of one
business day is the T+1 example used here. Principle 5 leaves the real
deadline to the bank.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from governance_sentinel.models import SAMPLE_LIMIT, Rule, RuleResult, RuleSet
from governance_sentinel.principles import PRINCIPLE_TITLES

logger = logging.getLogger(__name__)

RULE_TYPES: frozenset[str] = frozenset(
    {"not_null", "unique", "range", "domain", "referential", "timeliness", "outlier"}
)
DIMENSIONS: frozenset[str] = frozenset({"completeness", "accuracy", "validity", "timeliness"})
MIN_OUTLIER_ROWS = 8

_REQUIRED_RULE_FIELDS: tuple[str, ...] = (
    "id",
    "cde",
    "column",
    "dimension",
    "rule_type",
    "threshold",
    "owner",
    "steward",
    "principle",
    "principle_title",
    "description",
    "remediation",
)


def load_rules(path: str | Path) -> RuleSet:
    """Load and validate a rules file.

    Raises:
        ValueError: the file is not the expected mapping, or a rule is invalid.
        FileNotFoundError: ``path`` does not exist.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Rules file {path} must be a mapping.")
    version = raw.get("version")
    id_column = raw.get("id_column")
    rules_raw = raw.get("rules")
    if version != 1:
        raise ValueError(f"Unsupported rules version: {version!r}. Expected 1.")
    if not isinstance(id_column, str) or not id_column:
        raise ValueError("Rules file needs a non-empty id_column.")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ValueError("Rules file needs a non-empty rules list.")

    rules: list[Rule] = []
    seen: set[str] = set()
    for entry in rules_raw:
        rule = _parse_rule(entry)
        if rule.rule_id in seen:
            raise ValueError(f"Duplicate rule id: {rule.rule_id}.")
        seen.add(rule.rule_id)
        rules.append(rule)
    return RuleSet(version=1, id_column=id_column, rules=tuple(rules))


def evaluate_rules(
    frame: pd.DataFrame,
    ruleset: RuleSet,
    references: dict[str, pd.DataFrame] | None = None,
) -> list[RuleResult]:
    """Evaluate every rule. The input frame is not modified."""
    audited = frame.copy()
    lookups = references or {}
    results = [_evaluate_one(audited, rule, ruleset.id_column, lookups) for rule in ruleset.rules]
    failed = [item.rule_id for item in results if item.status == "FAIL"]
    logger.info(
        "Data-quality rules: %d checked, %d failed (%s).",
        len(results),
        len(failed),
        ", ".join(failed) if failed else "none",
    )
    return results


def dimension_rollup(results: list[RuleResult]) -> list[tuple[str, str, int, int]]:
    """Return ``(dimension, status, rules, failed_rules)`` in display order.

    A dimension FAILs when any of its rules fail. A dimension with no rules is
    omitted.
    """
    order = ("completeness", "accuracy", "validity", "timeliness")
    rolled: list[tuple[str, str, int, int]] = []
    for dimension in order:
        group = [item for item in results if item.dimension == dimension]
        if not group:
            continue
        failed = sum(1 for item in group if item.status == "FAIL")
        status = "FAIL" if failed else "PASS"
        rolled.append((dimension, status, len(group), failed))
    return rolled


def _parse_rule(entry: object) -> Rule:
    if not isinstance(entry, dict):
        raise ValueError("Each rule must be a mapping.")
    missing = [key for key in _REQUIRED_RULE_FIELDS if key not in entry]
    if missing:
        raise ValueError(f"Rule is missing fields: {missing}.")
    rule_id = _text(entry, "id")
    rule_type = _text(entry, "rule_type")
    dimension = _text(entry, "dimension")
    principle = str(entry["principle"]).strip()
    principle_title = _text(entry, "principle_title")
    if rule_type not in RULE_TYPES:
        raise ValueError(f"Rule {rule_id} has unknown rule_type {rule_type!r}.")
    if dimension not in DIMENSIONS:
        raise ValueError(f"Rule {rule_id} has unknown dimension {dimension!r}.")
    if principle not in PRINCIPLE_TITLES:
        raise ValueError(f"Rule {rule_id} cites unknown principle {principle!r}.")
    if principle_title != PRINCIPLE_TITLES[principle]:
        raise ValueError(
            f"Rule {rule_id} title {principle_title!r} does not match "
            f"principle {principle} ({PRINCIPLE_TITLES[principle]!r})."
        )
    threshold = entry["threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(f"Rule {rule_id} threshold must be a number.")
    if not 0 <= float(threshold) <= 100:
        raise ValueError(f"Rule {rule_id} threshold must be between 0 and 100.")
    parameters = entry.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ValueError(f"Rule {rule_id} parameters must be a mapping.")
    return Rule(
        rule_id=rule_id,
        cde=_text(entry, "cde"),
        column=_text(entry, "column"),
        dimension=dimension,
        rule_type=rule_type,
        threshold=float(threshold),
        owner=_text(entry, "owner"),
        steward=_text(entry, "steward"),
        principle=principle,
        principle_title=principle_title,
        description=_text(entry, "description"),
        remediation=_text(entry, "remediation"),
        parameters=dict(parameters),
    )


def _text(entry: dict[str, object], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Rule field {key} must be a non-empty string.")
    return " ".join(value.split())


def _evaluate_one(
    frame: pd.DataFrame,
    rule: Rule,
    id_column: str,
    references: dict[str, pd.DataFrame],
) -> RuleResult:
    if rule.column not in frame.columns and rule.rule_type != "timeliness":
        raise ValueError(f"Rule {rule.rule_id} requires column {rule.column!r}.")
    if frame.empty:
        return _result(rule, 0, 0, (), "No records to check.")

    if rule.rule_type == "not_null":
        failed = _missing(frame[rule.column])
        return _from_mask(frame, rule, id_column, failed, checked=len(frame))
    if rule.rule_type == "unique":
        return _unique(frame, rule, id_column)
    if rule.rule_type == "range":
        return _range(frame, rule, id_column)
    if rule.rule_type == "domain":
        return _domain(frame, rule, id_column)
    if rule.rule_type == "referential":
        return _referential(frame, rule, id_column, references)
    if rule.rule_type == "timeliness":
        return _timeliness(frame, rule, id_column)
    if rule.rule_type == "outlier":
        return _outlier(frame, rule, id_column)
    raise ValueError(f"Rule {rule.rule_id} has unknown rule_type {rule.rule_type!r}.")


def _unique(frame: pd.DataFrame, rule: Rule, id_column: str) -> RuleResult:
    column = frame[rule.column]
    present = ~_missing(column)
    duplicated = pd.Series(False, index=frame.index)
    populated = column.loc[present]
    duplicated.loc[present] = populated.duplicated(keep=False).to_numpy()
    return _from_mask(frame, rule, id_column, duplicated, checked=int(present.sum()))


def _range(frame: pd.DataFrame, rule: Rule, id_column: str) -> RuleResult:
    numeric = pd.to_numeric(frame[rule.column], errors="coerce")
    present = numeric.notna()
    failed = pd.Series(False, index=frame.index)
    lower = _optional_float(rule, "min")
    upper = _optional_float(rule, "max")
    if lower is not None:
        failed = failed | (present & numeric.lt(lower))
    if upper is not None:
        failed = failed | (present & numeric.gt(upper))
    return _from_mask(frame, rule, id_column, failed, checked=int(present.sum()))


def _domain(frame: pd.DataFrame, rule: Rule, id_column: str) -> RuleResult:
    allowed = _string_list(rule, "allowed")
    column = frame[rule.column]
    present = ~_missing(column)
    failed = present & ~column.isin(allowed)
    return _from_mask(frame, rule, id_column, failed, checked=int(present.sum()))


def _referential(
    frame: pd.DataFrame,
    rule: Rule,
    id_column: str,
    references: dict[str, pd.DataFrame],
) -> RuleResult:
    dataset_name = _required_str(rule, "reference_dataset")
    reference_column = _required_str(rule, "reference_column")
    if dataset_name not in references:
        raise ValueError(
            f"Rule {rule.rule_id} needs reference dataset {dataset_name!r}. "
            "Pass it in the references mapping."
        )
    reference = references[dataset_name]
    if reference_column not in reference.columns:
        raise ValueError(
            f"Reference {dataset_name!r} has no column {reference_column!r} "
            f"for rule {rule.rule_id}."
        )
    known = set(reference[reference_column].dropna().astype(str))
    column = frame[rule.column]
    # astype(str) would turn a missing id into the literal "nan", so missing
    # rows are failed on their own and only populated ids are looked up.
    failed = _missing(column) | (column.notna() & ~column.astype(str).isin(known))
    return _from_mask(frame, rule, id_column, failed, checked=len(frame))


def _timeliness(frame: pd.DataFrame, rule: Rule, id_column: str) -> RuleResult:
    event_column = _required_str(rule, "event_column")
    available_column = _required_str(rule, "available_column")
    max_lag = _required_int(rule, "max_lag_business_days")
    for name in (event_column, available_column):
        if name not in frame.columns:
            raise ValueError(f"Rule {rule.rule_id} requires column {name!r}.")
    event = pd.to_datetime(frame[event_column], errors="coerce")
    available = pd.to_datetime(frame[available_column], errors="coerce")
    valid = event.notna() & available.notna()
    lag = pd.Series(np.nan, index=frame.index, dtype="float64")
    if bool(valid.any()):
        lag.loc[valid] = np.busday_count(
            event.loc[valid].to_numpy(dtype="datetime64[D]"),
            available.loc[valid].to_numpy(dtype="datetime64[D]"),
        )
    failed = ~valid | lag.gt(max_lag) | lag.lt(0)
    detail = (
        f"Business-day lag from {event_column} to {available_column} "
        f"must be between 0 and {max_lag} inclusive. "
        "Weekends use the numpy default weekmask. No holiday calendar is applied."
    )
    return _from_mask(frame, rule, id_column, failed, checked=len(frame), detail=detail)


def _outlier(frame: pd.DataFrame, rule: Rule, id_column: str) -> RuleResult:
    method = _required_str(rule, "method")
    if method != "iqr":
        raise ValueError(f"Rule {rule.rule_id} supports outlier method 'iqr' only.")
    k = _required_float(rule, "k")
    if k <= 0:
        raise ValueError(f"Rule {rule.rule_id} k must be positive.")
    lower_bound = _optional_float(rule, "lower_bound")
    numeric = pd.to_numeric(frame[rule.column], errors="coerce")
    eligible = numeric.notna()
    if lower_bound is not None:
        eligible = eligible & numeric.ge(lower_bound)
    checked = int(eligible.sum())
    if checked < MIN_OUTLIER_ROWS:
        return _result(
            rule,
            checked,
            0,
            (),
            f"Fewer than {MIN_OUTLIER_ROWS} values in scope. The IQR fence was not estimated.",
            status="FAIL",
        )
    values = numeric.loc[eligible].to_numpy(dtype=float)
    q1 = float(np.percentile(values, 25))
    q3 = float(np.percentile(values, 75))
    iqr = q3 - q1
    fence_low = q1 - k * iqr
    fence_high = q3 + k * iqr
    failed = eligible & (numeric.lt(fence_low) | numeric.gt(fence_high))
    detail = (
        f"IQR fence on values"
        f"{'' if lower_bound is None else f' at or above {lower_bound:g}'}: "
        f"[{fence_low:.4g}, {fence_high:.4g}] with k={k:g}. "
        "This is a screening heuristic, not a risk limit."
    )
    return _from_mask(frame, rule, id_column, failed, checked=checked, detail=detail)


def _from_mask(
    frame: pd.DataFrame,
    rule: Rule,
    id_column: str,
    failed: pd.Series,
    checked: int,
    detail: str = "",
) -> RuleResult:
    failed = failed.fillna(False).astype(bool)
    if checked == 0:
        return _result(rule, 0, 0, (), detail or "No records in scope.", status="FAIL")
    # A failure outside the checked population would mean the mask is wrong.
    failed_count = int(failed.sum())
    if failed_count > checked:
        raise ValueError(f"Rule {rule.rule_id} failed {failed_count} rows but checked {checked}.")
    ids = _ids(frame, failed, id_column)
    return _result(rule, checked, failed_count, ids, detail)


def _result(
    rule: Rule,
    checked: int,
    failed: int,
    failing_ids: tuple[str, ...],
    detail: str,
    status: str | None = None,
) -> RuleResult:
    if checked == 0:
        pass_pct = 0.0
    else:
        pass_pct = 100.0 * (checked - failed) / checked
    if status is None:
        status = "PASS" if checked > 0 and pass_pct + 1e-9 >= rule.threshold else "FAIL"
    return RuleResult(
        rule_id=rule.rule_id,
        cde=rule.cde,
        column=rule.column,
        dimension=rule.dimension,
        rule_type=rule.rule_type,
        description=rule.description,
        remediation=rule.remediation,
        records_checked=checked,
        records_failed=failed,
        pass_pct=pass_pct,
        threshold=rule.threshold,
        status=status,
        sample_failing_ids=failing_ids[:SAMPLE_LIMIT],
        failing_ids=failing_ids,
        owner=rule.owner,
        steward=rule.steward,
        principle=rule.principle,
        principle_title=rule.principle_title,
        detail=detail,
    )


def _ids(frame: pd.DataFrame, failed: pd.Series, id_column: str) -> tuple[str, ...]:
    rows = frame.loc[failed]
    if id_column in rows.columns:
        labels = rows[id_column]
        text = labels.where(labels.notna(), "row-" + labels.index.astype(str)).astype(str)
    else:
        text = pd.Series(["row-" + str(index) for index in rows.index], index=rows.index)
    return tuple(text.tolist())


def _missing(series: pd.Series) -> pd.Series:
    missing = series.isna()
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        blank = series.astype("string").str.strip().eq("").fillna(False)
        missing = missing | blank
    return missing


def _optional_float(rule: Rule, key: str) -> float | None:
    if key not in rule.parameters or rule.parameters[key] is None:
        return None
    value = rule.parameters[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Rule {rule.rule_id} parameter {key} must be a number.")
    return float(value)


def _required_float(rule: Rule, key: str) -> float:
    value = _optional_float(rule, key)
    if value is None:
        raise ValueError(f"Rule {rule.rule_id} needs numeric parameter {key}.")
    return value


def _required_int(rule: Rule, key: str) -> int:
    value = _required_float(rule, key)
    if not value.is_integer():
        raise ValueError(f"Rule {rule.rule_id} parameter {key} must be an integer.")
    return int(value)


def _required_str(rule: Rule, key: str) -> str:
    value = rule.parameters.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Rule {rule.rule_id} needs string parameter {key}.")
    return value


def _string_list(rule: Rule, key: str) -> list[str]:
    value = rule.parameters.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError(
            f"Rule {rule.rule_id} parameter {key} must be a non-empty list of strings."
        )
    return list(value)
