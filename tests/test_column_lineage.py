"""Column lineage, glossary traces, and the OpenLineage columnLineage facet."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from governance_sentinel.catalog import load_glossary
from governance_sentinel.column_lineage import (
    COLUMN_EDGES,
    COLUMN_LINEAGE_SCHEMA_URL,
    SCHEMA_FACET_URL,
    TRANSFORMATION_TYPES,
    column_lineage_facet,
    column_lineage_mermaid,
    excerpt_edges,
    trace_glossary_term,
)
from governance_sentinel.lineage import build_lineage, openlineage_event, write_lineage_artifacts
from governance_sentinel.models import RuleResult
from governance_sentinel.rules import load_rules

REPO = Path(__file__).resolve().parents[1]


def _result() -> RuleResult:
    return RuleResult(
        rule_id="exposure_populated",
        cde="exposure_amount",
        column="exposure_amount",
        dimension="completeness",
        rule_type="not_null",
        description="Demo.",
        remediation="Fix it.",
        records_checked=3,
        records_failed=0,
        pass_pct=100.0,
        threshold=99.0,
        status="PASS",
        sample_failing_ids=(),
        failing_ids=(),
        owner="Group Risk Data Office",
        steward="Credit Risk Data Steward",
        principle="4",
        principle_title="Completeness",
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "legal_entity_id": ["LE-UK", "LE-UK", "LE-FR"],
            "currency": ["EUR", "EUR", "USD"],
            "reporting_date": ["2026-09-30", "2026-09-30", "2026-09-30"],
            "exposure_amount": [100.0, 50.0, 20.0],
            "transaction_id": ["TX-1", "TX-2", "TX-3"],
        }
    )


def _as_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _as_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def test_every_transformation_type_is_used_and_age_band_is_derived() -> None:
    kinds = {edge.transformation for edge in COLUMN_EDGES}
    assert kinds == set(TRANSFORMATION_TYPES)
    derived = [edge for edge in COLUMN_EDGES if edge.transformation == "derivation"]
    assert len(derived) == 1
    assert derived[0].source_column == "age_category"
    assert derived[0].target_column == "age_band"
    assert derived[0].target_dataset == "staging.risk_transactions"
    copied = [
        edge.target_column
        for edge in COLUMN_EDGES
        if edge.transformation == "direct" and edge.target_dataset == "staging.risk_transactions"
    ]
    assert "age_band" not in copied
    assert "exposure_amount" in copied


def test_glossary_term_reaches_the_aggregate_and_the_source() -> None:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    glossary = load_glossary(REPO / "catalog" / "glossary.yml", ruleset)
    gross = next(term for term in glossary.terms if term.term_id == "gross_exposure")
    trace = trace_glossary_term(gross)
    columns = [(item.dataset, item.column) for item in trace.columns]
    assert columns[0] == ("core_banking.transactions", "exposure_amount")
    assert ("staging.risk_transactions", "exposure_amount") in columns
    assert ("risk_mart.exposure_by_entity", "exposure_amount") in columns
    aggregated = next(term for term in glossary.terms if term.term_id == "aggregated_exposure")
    upstream = trace_glossary_term(aggregated)
    assert upstream.columns[0].dataset == "core_banking.transactions"
    assert upstream.columns[-1].dataset == "risk_mart.exposure_by_entity"


def test_openlineage_column_lineage_and_schema_facets() -> None:
    event = openlineage_event("run-1", _frame(), [_result()])
    outputs = _as_list(event["outputs"])
    staging = _as_dict(outputs[0])
    aggregate = _as_dict(outputs[1])
    assert staging["name"] == "staging.risk_transactions"
    assert aggregate["name"] == "risk_mart.exposure_by_entity"
    _assert_schema(_as_dict(_as_dict(staging["facets"])["schema"]), includes="transaction_id")
    staging_schema = _as_dict(_as_dict(staging["facets"])["schema"])
    names = [str(_as_dict(field)["name"]) for field in _as_list(staging_schema["fields"])]
    assert "age_band" in names
    source = _as_dict(_as_list(event["inputs"])[0])
    source_schema = _as_dict(_as_dict(source["facets"])["schema"])
    source_names = [str(_as_dict(field)["name"]) for field in _as_list(source_schema["fields"])]
    assert "age_band" not in source_names

    staging_lineage = column_lineage_facet("staging.risk_transactions")
    _assert_column_lineage(staging_lineage)
    age_band = _as_dict(_as_dict(staging_lineage["fields"])["age_band"])
    age_inputs = _as_list(age_band["inputFields"])
    assert len(age_inputs) == 1
    age_input = _as_dict(age_inputs[0])
    assert age_input["field"] == "age_category"
    assert age_input["name"] == "core_banking.transactions"
    transformations = _as_list(age_input["transformations"])
    assert _as_dict(transformations[0])["type"] == "INDIRECT"
    assert "derivation:" in str(_as_dict(transformations[0])["description"])

    aggregate_lineage = _as_dict(_as_dict(aggregate["facets"])["columnLineage"])
    _assert_column_lineage(aggregate_lineage)
    exposure = _as_dict(_as_dict(aggregate_lineage["fields"])["exposure_amount"])
    exposure_input = _as_dict(_as_list(exposure["inputFields"])[0])
    subtypes = {
        str(_as_dict(item)["subtype"]) for item in _as_list(exposure_input["transformations"])
    }
    assert subtypes == {"AGGREGATION", "FILTER"}
    assert exposure["transformationType"] == "INDIRECT"
    group_key = _as_dict(_as_dict(aggregate_lineage["fields"])["legal_entity_id"])
    group_input = _as_dict(_as_list(group_key["inputFields"])[0])
    assert _as_dict(_as_list(group_input["transformations"])[0])["type"] == "DIRECT"


def test_column_lineage_export_links_glossary_terms(tmp_path: Path) -> None:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    glossary = load_glossary(REPO / "catalog" / "glossary.yml", ruleset)
    report = build_lineage(_frame(), [_result()], inject_break=True)
    event = openlineage_event("run-1", _frame(), [_result()])
    write_lineage_artifacts(report, event, tmp_path, glossary.terms)
    rows = json.loads((tmp_path / "column_lineage.json").read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    exposure = next(
        row
        for row in rows
        if row["target_column"] == "exposure_amount" and row["transformation"] == "aggregation"
    )
    assert "gross_exposure" in exposure["glossary_term_ids"]
    assert "aggregated_exposure" in exposure["glossary_term_ids"]
    frame = pd.read_csv(tmp_path / "column_lineage.csv")
    assert set(frame["transformation"]) == set(TRANSFORMATION_TYPES)
    linked = frame.loc[frame["transformation"] == "aggregation", "glossary_term_ids"].iloc[0]
    assert "gross_exposure" in str(linked)
    assert "aggregated_exposure" in str(linked)


def test_committed_column_diagram_matches_the_generator() -> None:
    diagram = (REPO / "docs" / "column_lineage.mmd").read_text(encoding="utf-8")
    assert diagram == column_lineage_mermaid() + "\n"
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert column_lineage_mermaid(excerpt_edges()) in readme


def _assert_schema(facet: dict[str, object], *, includes: str) -> None:
    assert facet["_schemaURL"] == SCHEMA_FACET_URL
    assert isinstance(facet["_producer"], str) and facet["_producer"]
    fields = _as_list(facet["fields"])
    assert fields
    names = []
    for field in fields:
        item = _as_dict(field)
        assert isinstance(item["name"], str) and item["name"]
        assert isinstance(item["type"], str) and item["type"]
        names.append(item["name"])
    assert includes in names


def _assert_column_lineage(facet: dict[str, object]) -> None:
    assert facet["_schemaURL"] == COLUMN_LINEAGE_SCHEMA_URL
    assert isinstance(facet["_producer"], str) and facet["_producer"]
    fields = _as_dict(facet["fields"])
    assert fields
    for column, raw in fields.items():
        assert isinstance(column, str) and column
        entry = _as_dict(raw)
        inputs = _as_list(entry["inputFields"])
        assert inputs
        assert isinstance(entry["transformationType"], str)
        assert isinstance(entry["transformationDescription"], str)
        for raw_input in inputs:
            item = _as_dict(raw_input)
            assert isinstance(item["namespace"], str) and item["namespace"]
            assert isinstance(item["name"], str) and item["name"]
            assert isinstance(item["field"], str) and item["field"]
            for raw_transformation in _as_list(item["transformations"]):
                transformation = _as_dict(raw_transformation)
                assert transformation["type"] in {"DIRECT", "INDIRECT"}
                assert isinstance(transformation["subtype"], str)
                assert isinstance(transformation["description"], str)
                assert isinstance(transformation["masking"], bool)
