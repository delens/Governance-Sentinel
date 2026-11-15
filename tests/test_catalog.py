"""Business glossary links and the JSON / CSV export."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from governance_sentinel.catalog import export_glossary, load_glossary
from governance_sentinel.rules import load_rules

REPO = Path(__file__).resolve().parents[1]


def test_glossary_links_resolve_to_rules_and_columns() -> None:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    glossary = load_glossary(REPO / "catalog" / "glossary.yml", ruleset)
    rule_ids = {rule.rule_id for rule in ruleset.rules}
    assert glossary.version == 1
    assert len(glossary.terms) >= 8
    cited: set[str] = set()
    for term in glossary.terms:
        assert term.dq_rule_ids
        assert set(term.dq_rule_ids) <= rule_ids
        assert term.physical_column
        assert term.owner
        cited.update(term.dq_rule_ids)
    assert "counterparty_known" in cited
    assert "availability_t_plus_1" in cited
    assert "exposure_outlier" in cited


def test_unknown_rule_is_rejected(tmp_path: Path) -> None:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    path = tmp_path / "glossary.yml"
    path.write_text(
        """
version: 1
terms:
  - id: broken
    term: Broken term
    definition: Points at a rule that does not exist.
    cde: exposure_amount
    physical_column: exposure_amount
    physical_dataset: staging.risk_transactions
    dq_rule_ids:
      - not_a_rule
    owner: Group Risk Data Office
    steward: Credit Risk Data Steward
    principles:
      - "3"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not_a_rule"):
        load_glossary(path, ruleset)


def test_export_writes_json_and_csv(tmp_path: Path) -> None:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    glossary = load_glossary(REPO / "catalog" / "glossary.yml", ruleset)
    json_path = tmp_path / "glossary.json"
    csv_path = tmp_path / "glossary.csv"
    export_glossary(glossary, json_path, csv_path)
    rows = json.loads(json_path.read_text(encoding="utf-8"))
    frame = pd.read_csv(csv_path)
    assert len(rows) == len(glossary.terms) == len(frame)
    assert "dq_rule_ids" in frame.columns
    exposure = frame.loc[frame["term_id"] == "gross_exposure"].iloc[0]
    assert "exposure_outlier" in str(exposure["dq_rule_ids"])
    assert exposure["physical_dataset"] == "staging.risk_transactions"
