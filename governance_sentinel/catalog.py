"""Business glossary: term to CDE, physical column, rule, and owner.

The glossary is the demo of the dictionary BCBS 239 paragraph 37 asks for,
and of the metadata in Principle 2, paragraph 33. A term that cannot be
joined to a rule or a physical column is rejected at load time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from governance_sentinel.principles import PRINCIPLE_TITLES
from governance_sentinel.rules import RuleSet
from governance_sentinel.synthetic import TRANSACTION_COLUMNS

DATASET_COLUMNS: dict[str, tuple[str, ...]] = {
    "core_banking.transactions": TRANSACTION_COLUMNS,
    "staging.risk_transactions": TRANSACTION_COLUMNS,
    "risk_mart.exposure_by_entity": (
        "legal_entity_id",
        "currency",
        "reporting_date",
        "exposure_amount",
    ),
    "reference.counterparties": (
        "counterparty_id",
        "counterparty_name",
        "country",
        "sector",
    ),
}


@dataclass(frozen=True)
class GlossaryTerm:
    """One business term and the physical objects it points at."""

    term_id: str
    term: str
    definition: str
    cde: str
    physical_column: str
    physical_dataset: str
    dq_rule_ids: tuple[str, ...]
    owner: str
    steward: str
    principles: tuple[str, ...]


@dataclass(frozen=True)
class Glossary:
    """The loaded glossary."""

    version: int
    terms: tuple[GlossaryTerm, ...]


def load_glossary(path: str | Path, ruleset: RuleSet) -> Glossary:
    """Load the glossary and check that every link resolves.

    Raises:
        ValueError: a rule id, column, dataset, or principle does not resolve.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError(f"Glossary {path} must be version 1.")
    entries = raw.get("terms")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Glossary needs a non-empty terms list.")

    known_rules = {rule.rule_id for rule in ruleset.rules}
    terms: list[GlossaryTerm] = []
    seen: set[str] = set()
    for entry in entries:
        term = _parse_term(entry, known_rules)
        if term.term_id in seen:
            raise ValueError(f"Duplicate glossary term: {term.term_id}.")
        seen.add(term.term_id)
        terms.append(term)
    return Glossary(version=1, terms=tuple(terms))


def export_glossary(glossary: Glossary, json_path: Path, csv_path: Path) -> None:
    """Write the glossary as JSON and as a flat CSV."""
    rows = [
        {
            "term_id": term.term_id,
            "term": term.term,
            "definition": term.definition,
            "cde": term.cde,
            "physical_column": term.physical_column,
            "physical_dataset": term.physical_dataset,
            "dq_rule_ids": "|".join(term.dq_rule_ids),
            "owner": term.owner,
            "steward": term.steward,
            "principles": "|".join(term.principles),
        }
        for term in glossary.terms
    ]
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False)


def _parse_term(entry: object, known_rules: set[str]) -> GlossaryTerm:
    if not isinstance(entry, dict):
        raise ValueError("Each glossary term must be a mapping.")
    term_id = _text(entry, "id")
    dataset = _text(entry, "physical_dataset")
    column = _text(entry, "physical_column")
    if dataset not in DATASET_COLUMNS:
        raise ValueError(f"Term {term_id} names unknown dataset {dataset!r}.")
    if column not in DATASET_COLUMNS[dataset]:
        raise ValueError(f"Term {term_id} column {column!r} is not on {dataset}.")
    rule_ids = entry.get("dq_rule_ids")
    if not isinstance(rule_ids, list) or not all(isinstance(item, str) for item in rule_ids):
        raise ValueError(f"Term {term_id} needs a dq_rule_ids list.")
    unknown = [item for item in rule_ids if item not in known_rules]
    if unknown:
        raise ValueError(f"Term {term_id} cites unknown rules {unknown}.")
    principles = entry.get("principles")
    if not isinstance(principles, list) or not principles:
        raise ValueError(f"Term {term_id} needs a principles list.")
    normalized = [str(item) for item in principles]
    bad = [item for item in normalized if item not in PRINCIPLE_TITLES]
    if bad:
        raise ValueError(f"Term {term_id} cites unknown principles {bad}.")
    return GlossaryTerm(
        term_id=term_id,
        term=_text(entry, "term"),
        definition=_text(entry, "definition"),
        cde=_text(entry, "cde"),
        physical_column=column,
        physical_dataset=dataset,
        dq_rule_ids=tuple(rule_ids),
        owner=_text(entry, "owner"),
        steward=_text(entry, "steward"),
        principles=tuple(normalized),
    )


def _text(entry: dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Glossary field {key} must be a non-empty string.")
    return " ".join(value.split())
