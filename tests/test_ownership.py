"""Ownership matrix checks, the CSV export, and the PDF remediation line."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from pypdf import PdfReader

from governance_sentinel.catalog import Glossary, load_glossary
from governance_sentinel.models import FairnessResult, RuleResult
from governance_sentinel.ownership import OwnershipMatrix, export_ownership, load_ownership
from governance_sentinel.rules import RuleSet, load_rules
from reporter import create_pdf_report

REPO = Path(__file__).resolve().parents[1]


def _load() -> tuple[RuleSet, Glossary, OwnershipMatrix]:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    glossary = load_glossary(REPO / "catalog" / "glossary.yml", ruleset)
    matrix = load_ownership(REPO / "governance" / "ownership.yml", glossary, ruleset)
    return ruleset, glossary, matrix


def _broken(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    raw = yaml.safe_load((REPO / "governance" / "ownership.yml").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AssertionError("ownership file must be a mapping")
    mutate(raw)
    path = tmp_path / "ownership.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_every_glossary_cde_has_an_owner_and_every_rule_exists() -> None:
    ruleset, glossary, matrix = _load()
    by_term = {row.term_id: row for row in matrix.rows}
    assert set(by_term) == {term.term_id for term in glossary.terms}
    cdes = {term.cde for term in glossary.terms}
    assert cdes <= {row.cde for row in matrix.rows}
    known = {rule.rule_id for rule in ruleset.rules}
    cited: set[str] = set()
    for term in glossary.terms:
        row = by_term[term.term_id]
        assert row.cde == term.cde
        assert row.data_owner == term.owner
        assert row.data_steward == term.steward
        assert set(row.dq_rule_ids) == set(term.dq_rule_ids)
        assert set(row.dq_rule_ids) <= known
        assert row.data_owner == "Group Risk Data Office"
        cited.update(row.dq_rule_ids)
    assert cited == known


def test_unknown_rule_is_rejected(tmp_path: Path) -> None:
    ruleset, glossary, _matrix = _load()

    def mutate(raw: dict[str, Any]) -> None:
        elements = raw["elements"]
        assert isinstance(elements, list)
        elements[0]["dq_rule_ids"] = ["not_a_rule"]

    with pytest.raises(ValueError, match="not_a_rule"):
        load_ownership(_broken(tmp_path, mutate), glossary, ruleset)


def test_missing_glossary_term_is_rejected(tmp_path: Path) -> None:
    ruleset, glossary, _matrix = _load()

    def mutate(raw: dict[str, Any]) -> None:
        elements = raw["elements"]
        assert isinstance(elements, list)
        raw["elements"] = [item for item in elements if item["term_id"] != "legal_entity"]

    with pytest.raises(ValueError, match="legal_entity"):
        load_ownership(_broken(tmp_path, mutate), glossary, ruleset)


def test_tolerance_must_match_the_strictest_rule(tmp_path: Path) -> None:
    ruleset, glossary, _matrix = _load()

    def mutate(raw: dict[str, Any]) -> None:
        elements = raw["elements"]
        assert isinstance(elements, list)
        elements[0]["tolerance_threshold"] = 50

    with pytest.raises(ValueError, match="tolerance_threshold"):
        load_ownership(_broken(tmp_path, mutate), glossary, ruleset)


def test_csv_export_lists_every_term(tmp_path: Path) -> None:
    _ruleset, glossary, matrix = _load()
    path = tmp_path / "ownership.csv"
    export_ownership(matrix, path)
    frame = pd.read_csv(path)
    assert list(frame.columns) == [
        "term_id",
        "cde",
        "data_owner",
        "data_steward",
        "source_system",
        "criticality",
        "tolerance_threshold",
        "dq_rule_ids",
    ]
    assert set(frame["term_id"]) == {term.term_id for term in glossary.terms}
    gross = frame.loc[frame["term_id"] == "gross_exposure"].iloc[0]
    assert gross["data_steward"] == "Credit Risk Data Steward"
    assert "exposure_outlier" in str(gross["dq_rule_ids"])
    assert float(gross["tolerance_threshold"]) == 99.0


def test_pdf_remediation_names_the_matrix_owner(tmp_path: Path) -> None:
    _ruleset, _glossary, matrix = _load()
    path = tmp_path / "audit.pdf"
    failed = RuleResult(
        rule_id="txn_id_populated",
        cde="transaction_id",
        column="transaction_id",
        dimension="completeness",
        rule_type="not_null",
        description="transaction_id is populated.",
        remediation="Backfill the identifier.",
        records_checked=100,
        records_failed=2,
        pass_pct=98.0,
        threshold=99.5,
        status="FAIL",
        sample_failing_ids=("R1",),
        failing_ids=("R1",),
        owner="Group Risk Data Office",
        steward="Transaction Data Steward",
        principle="4",
        principle_title="Completeness",
    )
    fairness = FairnessResult(
        ratio=0.9,
        unprivileged_rate=0.5,
        privileged_rate=0.55,
        unprivileged_count=10,
        privileged_count=10,
        unprivileged_positives=5,
        privileged_positives=6,
        rows_excluded=0,
        rows_in_other_groups=0,
        threshold=0.8,
        status="PASS",
        protected_attribute="age_category",
        unprivileged_value=1,
        privileged_value=2,
    )
    create_pdf_report(
        [failed],
        fairness,
        run_id="owner-check",
        dataset_sha256="a" * 64,
        row_count=100,
        output_path=str(path),
        ownership=matrix,
    )
    reader = PdfReader(str(path))
    text = " ".join((page.extract_text() or "") for page in reader.pages)
    assert "Ownership matrix: accountable data owner Group Risk Data Office" in text
    assert "Transaction Data Steward" in text
    assert "core_banking.transactions" in text
