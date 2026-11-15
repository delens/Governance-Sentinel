"""DataHub MCP and Collibra import files stay inside the documented shape."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from governance_sentinel import catalog_export
from governance_sentinel.catalog import Glossary, load_glossary
from governance_sentinel.catalog_export import (
    COLLIBRA_COLUMNS,
    RELATION_HEADER,
    RELATION_KEY,
    collibra_commands,
    collibra_frame,
    datahub_mcp,
    dataset_urn,
    group_urn,
    write_catalog_export,
)
from governance_sentinel.column_lineage import COLUMN_EDGES
from governance_sentinel.ownership import OwnershipMatrix, load_ownership
from governance_sentinel.rules import load_rules

REPO = Path(__file__).resolve().parents[1]


def _inputs() -> tuple[Glossary, OwnershipMatrix]:
    ruleset = load_rules(REPO / "rules" / "dq_rules.yml")
    glossary = load_glossary(REPO / "catalog" / "glossary.yml", ruleset)
    ownership = load_ownership(REPO / "governance" / "ownership.yml", glossary, ruleset)
    return glossary, ownership


def test_datahub_file_is_an_mcp_array() -> None:
    glossary, ownership = _inputs()
    proposals = datahub_mcp(glossary, ownership)
    assert isinstance(proposals, list)
    assert proposals
    aspects: set[tuple[str, str]] = set()
    for item in proposals:
        assert set(item) >= {"entityType", "entityUrn", "changeType", "aspectName", "aspect"}
        assert item["changeType"] == "UPSERT"
        assert "proposedSnapshot" not in item
        aspect = item["aspect"]
        assert isinstance(aspect, dict)
        assert isinstance(aspect["json"], dict)
        aspects.add((str(item["entityType"]), str(item["aspectName"])))
    assert ("glossaryNode", "glossaryNodeInfo") in aspects
    assert ("glossaryTerm", "glossaryTermInfo") in aspects
    assert ("glossaryTerm", "ownership") in aspects
    assert ("dataset", "schemaMetadata") in aspects
    assert ("dataset", "ownership") in aspects
    assert ("dataset", "upstreamLineage") in aspects
    assert ("dataset", "glossaryTerms") in aspects

    staging = dataset_urn("staging.risk_transactions")
    schema = _aspect(proposals, staging, "schemaMetadata")
    fields = schema["fields"]
    assert isinstance(fields, list)
    paths = {field["fieldPath"] for field in fields if isinstance(field, dict)}
    assert "transaction_id" in paths
    txn = next(
        field
        for field in fields
        if isinstance(field, dict) and field["fieldPath"] == "transaction_id"
    )
    field_type = txn["type"]
    assert isinstance(field_type, dict)
    assert "com.linkedin.schema.StringType" in field_type["type"]

    lineage = _aspect(proposals, staging, "upstreamLineage")
    upstreams = lineage["upstreams"]
    assert isinstance(upstreams, list)
    assert any(
        isinstance(item, dict) and item["dataset"] == dataset_urn("core_banking.transactions")
        for item in upstreams
    )
    fine = lineage["fineGrainedLineages"]
    assert isinstance(fine, list)
    assert len(fine) == sum(
        1 for edge in COLUMN_EDGES if edge.target_dataset == "staging.risk_transactions"
    )
    assert any(
        isinstance(item, dict) and item["transformOperation"] == "derivation" for item in fine
    )

    aggregate = _aspect(proposals, dataset_urn("risk_mart.exposure_by_entity"), "upstreamLineage")
    aggregate_fine = aggregate["fineGrainedLineages"]
    assert isinstance(aggregate_fine, list)
    assert any(
        isinstance(item, dict) and item["transformOperation"] == "aggregation"
        for item in aggregate_fine
    )

    owners = _aspect(proposals, dataset_urn("staging.risk_transactions"), "ownership")
    owner_rows = owners["owners"]
    assert isinstance(owner_rows, list)
    assert any(
        isinstance(item, dict) and item["owner"] == group_urn("Group Risk Data Office")
        for item in owner_rows
    )
    assert group_urn("Group Risk Data Office") == "urn:li:corpGroup:group_risk_data_office"


def test_collibra_csv_and_json_cover_terms_owners_and_relations() -> None:
    glossary, ownership = _inputs()
    frame = collibra_frame(glossary, ownership)
    assert list(frame.columns) == list(COLLIBRA_COLUMNS)
    terms = frame.loc[frame["Asset Type"] == "Business Term"]
    elements = frame.loc[frame["Asset Type"] == "Data Element"]
    assert set(terms["Name"]) == {term.term for term in glossary.terms}
    assert "Group Risk Data Office" in set(frame["Data Owner Role"])
    assert "Transaction Data Steward" in set(frame["Data Steward Role"])
    exposure = elements.loc[elements["CDE"] == "exposure_amount"]
    assert set(exposure["Physical Dataset"]) == {
        "staging.risk_transactions",
        "risk_mart.exposure_by_entity",
    }
    identifier = terms.loc[terms["Name"] == "Transaction identifier"].iloc[0]
    assert identifier[RELATION_HEADER] == "staging.risk_transactions.transaction_id"
    assert identifier["Status"] == "Candidate"

    commands = collibra_commands(glossary, ownership)
    kinds = {command["resourceType"] for command in commands}
    assert kinds == {"Community", "Domain", "Asset"}
    business = [
        command
        for command in commands
        if command.get("type") == {"name": "Business Term"}
        and command.get("name") == "Transaction identifier"
    ]
    assert len(business) == 1
    relations = business[0]["relations"]
    assert isinstance(relations, dict)
    assert RELATION_KEY in relations
    targets = relations[RELATION_KEY]
    assert isinstance(targets, list)
    assert targets[0]["name"] == "staging.risk_transactions.transaction_id"
    note = business[0]["attributes"]
    assert isinstance(note, dict)
    notes = note["Note"]
    assert isinstance(notes, list)
    assert "Group Risk Data Office" in notes[0]["value"]
    assert "not Collibra user accounts" in notes[0]["value"]


def test_writer_and_cli(tmp_path: Path) -> None:
    glossary, ownership = _inputs()
    datahub_dir = tmp_path / "datahub"
    paths = write_catalog_export("datahub", datahub_dir, glossary, ownership)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload[0]["aspect"]["json"]

    collibra_dir = tmp_path / "collibra"
    csv_path, json_path = write_catalog_export("collibra", collibra_dir, glossary, ownership)
    assert len(pd.read_csv(csv_path)) == len(glossary.terms) * 2
    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["resourceType"] == "Community"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "governance_sentinel",
            "export-catalog",
            "--target",
            "datahub",
            "--out",
            str(tmp_path / "cli"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    written = json.loads((tmp_path / "cli" / "datahub_mcp.json").read_text(encoding="utf-8"))
    assert isinstance(written, list)


def test_export_module_does_not_call_the_network() -> None:
    source = Path(catalog_export.__file__).read_text(encoding="utf-8")
    for banned in (
        "urllib.request",
        "import requests",
        "import httpx",
        "import socket",
        "acryl",
        "datahub.emitter",
    ):
        assert banned not in source
    tree = ast.parse(source)
    imported = {
        alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    }
    imported.update(node.module or "" for node in tree.body if isinstance(node, ast.ImportFrom))
    assert imported.isdisjoint({"requests", "httpx", "socket", "urllib"})


def _aspect(proposals: list[dict[str, object]], urn: str, name: str) -> dict[str, object]:
    for item in proposals:
        if item["entityUrn"] == urn and item["aspectName"] == name:
            aspect = item["aspect"]
            assert isinstance(aspect, dict)
            body = aspect["json"]
            assert isinstance(body, dict)
            return body
    raise AssertionError(f"missing {name} on {urn}")
