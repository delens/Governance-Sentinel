"""Shared result types for the rules engine, the fairness audit, and the PDF."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class Rule:
    """One declarative data-quality rule."""

    rule_id: str
    cde: str
    column: str
    dimension: str
    rule_type: str
    threshold: float
    owner: str
    steward: str
    principle: str
    principle_title: str
    description: str
    remediation: str
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleSet:
    """Rules loaded from YAML."""

    version: int
    id_column: str
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class RuleResult:
    """Granular outcome of one rule against one dataset."""

    rule_id: str
    cde: str
    column: str
    dimension: str
    rule_type: str
    description: str
    remediation: str
    records_checked: int
    records_failed: int
    pass_pct: float
    threshold: float
    status: str
    sample_failing_ids: tuple[str, ...]
    failing_ids: tuple[str, ...]
    owner: str
    steward: str
    principle: str
    principle_title: str
    detail: str = ""

    @property
    def records_passed(self) -> int:
        return self.records_checked - self.records_failed


@dataclass(frozen=True)
class FairnessResult:
    """Group sizes, selection rates, and the disparate-impact ratio."""

    ratio: float
    unprivileged_rate: float
    privileged_rate: float
    unprivileged_count: int
    privileged_count: int
    unprivileged_positives: int
    privileged_positives: int
    rows_excluded: int
    rows_in_other_groups: int
    threshold: float
    status: str
    protected_attribute: str
    unprivileged_value: int
    privileged_value: int

    @property
    def defined(self) -> bool:
        return math.isfinite(self.ratio)
