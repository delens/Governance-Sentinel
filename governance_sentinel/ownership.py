"""Data ownership matrix: one row per glossary term.

The matrix names a data owner and a data steward for each critical data
element in the glossary. Both are roles. The file does not name a person.

Load-time checks:

- Every glossary term has one row, and the CDE matches.
- The owner and the steward match the glossary, so the two files do not drift.
- Every rule id on a row exists in the rules file.
- The rule list on a row is the same set the glossary term cites.
- Every rule in the rules file appears on at least one row.
- ``tolerance_threshold`` is the lowest minimum pass percentage of those rules.

A failed check raises ``ValueError``. The audit calls this loader, so a
broken matrix stops the run.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from governance_sentinel.catalog import Glossary, GlossaryTerm
from governance_sentinel.rules import RuleSet

CRITICALITIES: tuple[str, ...] = ("high", "medium", "low")

CSV_COLUMNS: tuple[str, ...] = (
    "term_id",
    "cde",
    "data_owner",
    "data_steward",
    "source_system",
    "criticality",
    "tolerance_threshold",
    "dq_rule_ids",
)


@dataclass(frozen=True)
class OwnershipRow:
    """One critical data element and the roles accountable for it."""

    term_id: str
    cde: str
    data_owner: str
    data_steward: str
    source_system: str
    criticality: str
    tolerance_threshold: float
    dq_rule_ids: tuple[str, ...]


@dataclass(frozen=True)
class OwnershipMatrix:
    """The loaded matrix."""

    version: int
    rows: tuple[OwnershipRow, ...]

    def by_term(self, term_id: str) -> OwnershipRow:
        """Return the row for a glossary term. Missing is an error."""
        for row in self.rows:
            if row.term_id == term_id:
                return row
        raise KeyError(f"Ownership matrix has no row for {term_id}.")

    def for_rule(self, rule_id: str) -> tuple[OwnershipRow, ...]:
        """Rows that cite ``rule_id``, in file order."""
        return tuple(row for row in self.rows if rule_id in row.dq_rule_ids)


def load_ownership(path: str | Path, glossary: Glossary, ruleset: RuleSet) -> OwnershipMatrix:
    """Load the matrix and check it against the glossary and the rules."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError(f"Ownership matrix {path} must be version 1.")
    entries = raw.get("elements")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Ownership matrix needs a non-empty elements list.")

    glossary_by_id = {term.term_id: term for term in glossary.terms}
    rule_thresholds = {rule.rule_id: float(rule.threshold) for rule in ruleset.rules}
    rows: list[OwnershipRow] = []
    seen: set[str] = set()
    for entry in entries:
        row = _parse_row(entry, glossary_by_id, rule_thresholds)
        if row.term_id in seen:
            raise ValueError(f"Duplicate ownership row: {row.term_id}.")
        seen.add(row.term_id)
        rows.append(row)

    missing_terms = [term.term_id for term in glossary.terms if term.term_id not in seen]
    if missing_terms:
        raise ValueError(f"Glossary terms with no owner: {missing_terms}.")
    missing_cdes = sorted(
        {term.cde for term in glossary.terms if term.cde not in {row.cde for row in rows}}
    )
    if missing_cdes:
        raise ValueError(f"Glossary CDEs with no owner: {missing_cdes}.")
    covered = {rule_id for row in rows for rule_id in row.dq_rule_ids}
    missing_rules = [rule.rule_id for rule in ruleset.rules if rule.rule_id not in covered]
    if missing_rules:
        raise ValueError(f"Rules with no owner on the ownership matrix: {missing_rules}.")
    return OwnershipMatrix(version=1, rows=tuple(rows))


def ownership_records(matrix: OwnershipMatrix) -> list[dict[str, object]]:
    """Flat records for the CSV export and the dashboard table."""
    return [
        {
            "term_id": row.term_id,
            "cde": row.cde,
            "data_owner": row.data_owner,
            "data_steward": row.data_steward,
            "source_system": row.source_system,
            "criticality": row.criticality,
            "tolerance_threshold": row.tolerance_threshold,
            "dq_rule_ids": "|".join(row.dq_rule_ids),
        }
        for row in matrix.rows
    ]


def export_ownership(matrix: OwnershipMatrix, path: Path) -> None:
    """Write the matrix as a CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(ownership_records(matrix), columns=list(CSV_COLUMNS))
    frame.to_csv(path, index=False)


def ownership_sentence(matrix: OwnershipMatrix, rule_id: str) -> str:
    """One sentence naming the accountable roles for a failed rule.

    A rule that sits on more than one row lists each role once. The data
    owner is the accountable owner. Raises when the rule is not on the matrix.
    """
    rows = matrix.for_rule(rule_id)
    if not rows:
        raise ValueError(
            f"Rule {rule_id} is not on the ownership matrix, "
            "so the report cannot name an accountable owner."
        )
    owners = _unique(row.data_owner for row in rows)
    stewards = _unique(row.data_steward for row in rows)
    systems = _unique(row.source_system for row in rows)
    return (
        "Ownership matrix: accountable data owner "
        + ", ".join(owners)
        + ". Data steward "
        + ", ".join(stewards)
        + ". Source system "
        + ", ".join(systems)
        + "."
    )


def _parse_row(
    entry: object,
    glossary_by_id: dict[str, GlossaryTerm],
    rule_thresholds: dict[str, float],
) -> OwnershipRow:
    if not isinstance(entry, dict):
        raise ValueError("Each ownership element must be a mapping.")
    term_id = _text(entry, "term_id")
    term = glossary_by_id.get(term_id)
    if term is None:
        raise ValueError(f"Ownership row {term_id} is not a glossary term.")
    cde = _text(entry, "cde")
    if cde != term.cde:
        raise ValueError(f"Ownership row {term_id} CDE {cde} does not match the glossary.")
    owner = _text(entry, "data_owner")
    steward = _text(entry, "data_steward")
    if owner != term.owner:
        raise ValueError(f"Ownership row {term_id} data owner does not match the glossary.")
    if steward != term.steward:
        raise ValueError(f"Ownership row {term_id} data steward does not match the glossary.")
    criticality = _text(entry, "criticality")
    if criticality not in CRITICALITIES:
        raise ValueError(f"Ownership row {term_id} criticality must be high, medium, or low.")
    raw_rules = entry.get("dq_rule_ids")
    if not isinstance(raw_rules, list):
        raise ValueError(f"Ownership row {term_id} needs a dq_rule_ids list.")
    rule_ids: list[str] = []
    for item in raw_rules:
        if not isinstance(item, str) or not item:
            raise ValueError(f"Ownership row {term_id} needs a dq_rule_ids list.")
        rule_ids.append(item)
    unknown = [item for item in rule_ids if item not in rule_thresholds]
    if unknown:
        raise ValueError(f"Ownership row {term_id} cites unknown rules {unknown}.")
    if set(rule_ids) != set(term.dq_rule_ids):
        raise ValueError(
            f"Ownership row {term_id} rules {list(rule_ids)} do not match the glossary."
        )
    threshold = entry.get("tolerance_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        raise ValueError(f"Ownership row {term_id} tolerance_threshold must be a number.")
    tolerance = float(threshold)
    if not 0.0 <= tolerance <= 100.0:
        raise ValueError(f"Ownership row {term_id} tolerance_threshold must be from 0 to 100.")
    expected = min(rule_thresholds[item] for item in rule_ids)
    if abs(tolerance - expected) > 1e-9:
        raise ValueError(
            f"Ownership row {term_id} tolerance_threshold is {tolerance}, "
            f"the lowest linked rule threshold is {expected}."
        )
    return OwnershipRow(
        term_id=term_id,
        cde=cde,
        data_owner=owner,
        data_steward=steward,
        source_system=_text(entry, "source_system"),
        criticality=criticality,
        tolerance_threshold=tolerance,
        dq_rule_ids=tuple(rule_ids),
    )


def _text(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Ownership field {key} must be a non-empty string.")
    return " ".join(value.split())


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)
