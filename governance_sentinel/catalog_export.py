"""File exports for a DataHub file source and a Collibra import.

Nothing in this module opens a socket. There is no DataHub or Collibra SDK.
The shapes are the documented file formats, written to local JSON and CSV.
Limits and the source documents are in ``docs/catalog-export.md``.

DataHub output is a JSON array of Metadata Change Proposals. Each proposal
carries one aspect under ``aspect.json``, which is the shape the DataHub
file sink writes and the file source reads.

Collibra output is a CSV whose headers follow the import wizard, plus a JSON
array of Import API commands (community, domain, asset). Owner and steward
roles are attributes. They are not Collibra responsibilities, because a
responsibility expects a user or a group id and this matrix names roles.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from governance_sentinel.catalog import DATASET_COLUMNS, Glossary
from governance_sentinel.column_lineage import COLUMN_EDGES, native_column_type
from governance_sentinel.ownership import OwnershipMatrix

PLATFORM = "governance_sentinel"
FABRIC = "DEV"
ACTOR = "urn:li:corpuser:governance_sentinel"
GLOSSARY_NODE = "urn:li:glossaryNode:bcbs239RiskData"

COMMUNITY = "Governance Sentinel"
GLOSSARY_DOMAIN = "Risk Data Glossary"
ELEMENT_DOMAIN = "Risk Data Elements"
GLOSSARY_DOMAIN_TYPE = "Glossary"
ELEMENT_DOMAIN_TYPE = "Physical Data Dictionary"

# Fully qualified relation key. See docs/catalog-export.md for the limit:
# the out-of-the-box relation is often registered on the parent types.
RELATION_KEY = "Business Term:represents:is represented by:Data Element:TARGET"
RELATION_HEADER = "[Business Term] represents [Data Element]"

COLLIBRA_COLUMNS: tuple[str, ...] = (
    "Name",
    "Full Name",
    "Community",
    "Domain",
    "Domain Type",
    "Asset Type",
    "Status",
    "Definition",
    "Criticality",
    "Source System",
    "Tolerance Threshold",
    "Data Owner Role",
    "Data Steward Role",
    "CDE",
    "Physical Dataset",
    "Physical Column",
    "DQ Rules",
    RELATION_HEADER,
)

_DATASET_ORDER: tuple[str, ...] = (
    "core_banking.transactions",
    "reference.counterparties",
    "staging.risk_transactions",
    "risk_mart.exposure_by_entity",
)

_DATASET_TEXT: dict[str, str] = {
    "core_banking.transactions": (
        "Booking-system origin of the staged extract. This prototype does not "
        "read a separate booking file. The source node is not measured."
    ),
    "reference.counterparties": (
        "Counterparty master used by the referential rule. The rows are fictional."
    ),
    "staging.risk_transactions": ("Staged risk transactions. The YAML rules run on this extract."),
    "risk_mart.exposure_by_entity": (
        "Exposure summed by legal entity, currency, and reporting date."
    ),
}

_SCHEMA_TYPE: dict[str, str] = {
    "string": "StringType",
    "double": "NumberType",
    "integer": "NumberType",
    "date": "DateType",
}

_KEY_FIELDS: dict[str, frozenset[str]] = {
    "core_banking.transactions": frozenset({"transaction_id"}),
    "staging.risk_transactions": frozenset({"transaction_id"}),
    "risk_mart.exposure_by_entity": frozenset({"legal_entity_id", "currency", "reporting_date"}),
    "reference.counterparties": frozenset({"counterparty_id"}),
}


def dataset_urn(name: str) -> str:
    """DataHub dataset URN. The fabric is DEV because the data is synthetic."""
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{name},{FABRIC})"


def field_urn(dataset: str, field: str) -> str:
    """Schema-field URN for one column of a dataset URN."""
    return f"urn:li:schemaField:({dataset_urn(dataset)},{field})"


def group_urn(role: str) -> str:
    """Corp-group URN for a role. This is not a person and not a CorpUser."""
    slug = "".join(character.lower() if character.isalnum() else "_" for character in role)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return "urn:li:corpGroup:" + slug.strip("_")


def term_urn(term_id: str) -> str:
    """Glossary-term URN. The id is the glossary term id."""
    return f"urn:li:glossaryTerm:{term_id}"


def datahub_mcp(glossary: Glossary, ownership: OwnershipMatrix) -> list[dict[str, object]]:
    """Metadata Change Proposals for datasets, fields, terms, owners, and lineage."""
    proposals: list[dict[str, object]] = [_glossary_node()]
    for term in glossary.terms:
        row = ownership.by_term(term.term_id)
        proposals.append(
            _mcp(
                "glossaryTerm",
                term_urn(term.term_id),
                "glossaryTermInfo",
                {
                    "name": term.term,
                    "definition": term.definition,
                    "termSource": "INTERNAL",
                    "parentNode": GLOSSARY_NODE,
                    "customProperties": {
                        "cde": term.cde,
                        "criticality": row.criticality,
                        "source_system": row.source_system,
                        "tolerance_threshold": _number(row.tolerance_threshold),
                        "physical_dataset": term.physical_dataset,
                        "physical_column": term.physical_column,
                    },
                },
            )
        )
        proposals.append(
            _mcp(
                "glossaryTerm",
                term_urn(term.term_id),
                "ownership",
                _ownership_aspect(
                    [(row.data_owner, "BUSINESS_OWNER"), (row.data_steward, "DATA_STEWARD")]
                ),
            )
        )
        proposals.append(_mcp("glossaryTerm", term_urn(term.term_id), "status", {"removed": False}))
    for dataset in _DATASET_ORDER:
        proposals.extend(_dataset_proposals(dataset, glossary, ownership))
    return proposals


def collibra_commands(glossary: Glossary, ownership: OwnershipMatrix) -> list[dict[str, object]]:
    """Import API commands. Communities and domains come before the assets."""
    commands: list[dict[str, object]] = [
        {
            "resourceType": "Community",
            "identifier": {"name": COMMUNITY},
            "name": COMMUNITY,
        },
        _domain(GLOSSARY_DOMAIN, GLOSSARY_DOMAIN_TYPE),
        _domain(ELEMENT_DOMAIN, ELEMENT_DOMAIN_TYPE),
    ]
    for term in glossary.terms:
        row = ownership.by_term(term.term_id)
        element_name = _element_name(term.physical_dataset, term.physical_column)
        note = _role_note(row.data_owner, row.data_steward, row.source_system, row.criticality)
        commands.append(
            _asset(
                name=element_name,
                display_name=term.physical_column,
                domain=ELEMENT_DOMAIN,
                asset_type="Data Element",
                definition=term.definition,
                note=note,
                relations=None,
            )
        )
        commands.append(
            _asset(
                name=term.term,
                display_name=term.term,
                domain=GLOSSARY_DOMAIN,
                asset_type="Business Term",
                definition=term.definition,
                note=note + f" CDE {term.cde}. Rules {', '.join(row.dq_rule_ids)}.",
                relations={
                    RELATION_KEY: [
                        {
                            "name": element_name,
                            "domain": {
                                "name": ELEMENT_DOMAIN,
                                "community": {"name": COMMUNITY},
                            },
                        }
                    ]
                },
            )
        )
    return commands


def collibra_frame(glossary: Glossary, ownership: OwnershipMatrix) -> pd.DataFrame:
    """One CSV row per data element, then one per business term."""
    rows: list[dict[str, str]] = []
    for term in glossary.terms:
        row = ownership.by_term(term.term_id)
        element_name = _element_name(term.physical_dataset, term.physical_column)
        shared = {
            "Criticality": row.criticality,
            "Source System": row.source_system,
            "Tolerance Threshold": _number(row.tolerance_threshold),
            "Data Owner Role": row.data_owner,
            "Data Steward Role": row.data_steward,
            "CDE": term.cde,
            "Physical Dataset": term.physical_dataset,
            "Physical Column": term.physical_column,
            "DQ Rules": "|".join(row.dq_rule_ids),
            "Definition": term.definition,
        }
        rows.append(
            _csv_row(
                element_name,
                ELEMENT_DOMAIN,
                ELEMENT_DOMAIN_TYPE,
                "Data Element",
                shared,
                "",
            )
        )
    for term in glossary.terms:
        row = ownership.by_term(term.term_id)
        element_name = _element_name(term.physical_dataset, term.physical_column)
        shared = {
            "Criticality": row.criticality,
            "Source System": row.source_system,
            "Tolerance Threshold": _number(row.tolerance_threshold),
            "Data Owner Role": row.data_owner,
            "Data Steward Role": row.data_steward,
            "CDE": term.cde,
            "Physical Dataset": term.physical_dataset,
            "Physical Column": term.physical_column,
            "DQ Rules": "|".join(row.dq_rule_ids),
            "Definition": term.definition,
        }
        rows.append(
            _csv_row(
                term.term,
                GLOSSARY_DOMAIN,
                GLOSSARY_DOMAIN_TYPE,
                "Business Term",
                shared,
                element_name,
            )
        )
    return pd.DataFrame(rows, columns=list(COLLIBRA_COLUMNS))


def write_catalog_export(
    target: str,
    out_dir: Path,
    glossary: Glossary,
    ownership: OwnershipMatrix,
) -> tuple[Path, ...]:
    """Write the files for ``datahub`` or ``collibra``. Return the paths."""
    if target not in {"datahub", "collibra"}:
        raise ValueError("Catalog target must be datahub or collibra.")
    out_dir.mkdir(parents=True, exist_ok=True)
    if target == "datahub":
        path = out_dir / "datahub_mcp.json"
        payload = datahub_mcp(glossary, ownership)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return (path,)
    csv_path = out_dir / "collibra_assets.csv"
    json_path = out_dir / "collibra_import.json"
    collibra_frame(glossary, ownership).to_csv(csv_path, index=False)
    commands = collibra_commands(glossary, ownership)
    json_path.write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    return (csv_path, json_path)


def _dataset_proposals(
    dataset: str,
    glossary: Glossary,
    ownership: OwnershipMatrix,
) -> list[dict[str, object]]:
    urn = dataset_urn(dataset)
    terms = [
        term
        for term in glossary.terms
        if _term_on_dataset(term.physical_dataset, term.physical_column, dataset)
    ]
    proposals = [
        _mcp(
            "dataset",
            urn,
            "datasetProperties",
            {
                "name": dataset,
                "description": _DATASET_TEXT[dataset],
                "customProperties": {
                    "prototype": "governance-sentinel",
                    "platform": PLATFORM,
                    "fabric": FABRIC,
                },
            },
        ),
        _mcp("dataset", urn, "status", {"removed": False}),
        _mcp("dataset", urn, "ownership", _dataset_ownership(dataset, glossary, ownership)),
        _mcp("dataset", urn, "schemaMetadata", _schema(dataset, glossary)),
    ]
    if terms:
        proposals.append(
            _mcp(
                "dataset",
                urn,
                "glossaryTerms",
                {
                    "terms": [{"urn": term_urn(term.term_id)} for term in terms],
                    "auditStamp": _stamp(),
                },
            )
        )
    lineage = _lineage(dataset)
    if lineage is not None:
        proposals.append(_mcp("dataset", urn, "upstreamLineage", lineage))
    return proposals


def _term_on_dataset(physical_dataset: str, column: str, dataset: str) -> bool:
    if physical_dataset == dataset:
        return True
    if dataset == "core_banking.transactions" and physical_dataset == "staging.risk_transactions":
        return column in DATASET_COLUMNS[dataset]
    if dataset == "reference.counterparties" and column == "counterparty_id":
        return physical_dataset == "staging.risk_transactions"
    return False


def _dataset_ownership(
    dataset: str,
    glossary: Glossary,
    ownership: OwnershipMatrix,
) -> dict[str, object]:
    pairs: list[tuple[str, str]] = []
    for term in glossary.terms:
        if not _term_on_dataset(term.physical_dataset, term.physical_column, dataset):
            continue
        row = ownership.by_term(term.term_id)
        pairs.append((row.data_owner, "BUSINESS_OWNER"))
        pairs.append((row.data_steward, "DATA_STEWARD"))
    if not pairs:
        pairs.append(("Group Risk Data Office", "BUSINESS_OWNER"))
    return _ownership_aspect(pairs)


def _schema(dataset: str, glossary: Glossary) -> dict[str, object]:
    columns = DATASET_COLUMNS[dataset]
    fields: list[dict[str, object]] = []
    for column in columns:
        native = native_column_type(column)
        schema_type = _SCHEMA_TYPE[native]
        field: dict[str, object] = {
            "fieldPath": column,
            "nullable": True,
            "description": _field_description(dataset, column, glossary),
            "type": {"type": {f"com.linkedin.schema.{schema_type}": {}}},
            "nativeDataType": native,
            "recursive": False,
            "isPartOfKey": column in _KEY_FIELDS[dataset],
        }
        linked = [
            term.term_id
            for term in glossary.terms
            if term.physical_column == column
            and _term_on_dataset(term.physical_dataset, term.physical_column, dataset)
        ]
        if linked:
            field["glossaryTerms"] = {
                "terms": [{"urn": term_urn(term_id)} for term_id in linked],
                "auditStamp": _stamp(),
            }
        fields.append(field)
    digest = hashlib.sha256("|".join(columns).encode("utf-8")).hexdigest()
    return {
        "schemaName": dataset,
        "platform": f"urn:li:dataPlatform:{PLATFORM}",
        "version": 0,
        "hash": digest,
        "created": _stamp(),
        "lastModified": _stamp(),
        "platformSchema": {"com.linkedin.schema.OtherSchema": {"rawSchema": ", ".join(columns)}},
        "fields": fields,
    }


def _field_description(dataset: str, column: str, glossary: Glossary) -> str:
    for term in glossary.terms:
        if term.physical_dataset == dataset and term.physical_column == column:
            return term.definition
    return f"{column} on {dataset}."


def _lineage(dataset: str) -> dict[str, object] | None:
    incoming = [edge for edge in COLUMN_EDGES if edge.target_dataset == dataset]
    if not incoming:
        return None
    upstream_names = sorted({edge.source_dataset for edge in incoming})
    fine: list[dict[str, object]] = []
    for edge in incoming:
        fine.append(
            {
                "upstreamType": "FIELD_SET",
                "upstreams": [field_urn(edge.source_dataset, edge.source_column)],
                "downstreamType": "FIELD",
                "downstreams": [field_urn(edge.target_dataset, edge.target_column)],
                "transformOperation": edge.transformation,
                "confidenceScore": 1.0,
            }
        )
    return {
        "upstreams": [
            {
                "dataset": dataset_urn(name),
                "type": "TRANSFORMED",
                "auditStamp": _stamp(),
            }
            for name in upstream_names
        ],
        "fineGrainedLineages": fine,
    }


def _glossary_node() -> dict[str, object]:
    return _mcp(
        "glossaryNode",
        GLOSSARY_NODE,
        "glossaryNodeInfo",
        {
            "name": "BCBS 239 risk data",
            "definition": (
                "Critical data elements for the synthetic risk extract in "
                "Governance-Sentinel. Terms are roles and definitions from the glossary."
            ),
        },
    )


def _ownership_aspect(pairs: list[tuple[str, str]]) -> dict[str, object]:
    owners: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for role, kind in pairs:
        urn = group_urn(role)
        key = (urn, kind)
        if key in seen:
            continue
        seen.add(key)
        owners.append({"owner": urn, "type": kind, "source": {"type": "MANUAL"}})
    return {"owners": owners, "lastModified": _stamp()}


def _mcp(
    entity_type: str,
    urn: str,
    aspect_name: str,
    aspect: dict[str, object],
) -> dict[str, object]:
    return {
        "entityType": entity_type,
        "entityUrn": urn,
        "changeType": "UPSERT",
        "aspectName": aspect_name,
        "aspect": {"json": aspect},
    }


def _stamp() -> dict[str, object]:
    return {"time": 0, "actor": ACTOR}


def _domain(name: str, domain_type: str) -> dict[str, object]:
    return {
        "resourceType": "Domain",
        "identifier": {"name": name, "community": {"name": COMMUNITY}},
        "name": name,
        "community": {"name": COMMUNITY},
        "type": {"name": domain_type},
    }


def _asset(
    *,
    name: str,
    display_name: str,
    domain: str,
    asset_type: str,
    definition: str,
    note: str,
    relations: dict[str, object] | None,
) -> dict[str, object]:
    command: dict[str, object] = {
        "resourceType": "Asset",
        "identifier": {
            "name": name,
            "domain": {"name": domain, "community": {"name": COMMUNITY}},
        },
        "name": name,
        "displayName": display_name,
        "type": {"name": asset_type},
        "domain": {"name": domain, "community": {"name": COMMUNITY}},
        "status": {"name": "Candidate"},
        "attributes": {
            "Definition": [{"value": definition}],
            "Note": [{"value": note}],
        },
    }
    if relations is not None:
        command["relations"] = relations
    return command


def _csv_row(
    name: str,
    domain: str,
    domain_type: str,
    asset_type: str,
    shared: dict[str, str],
    relation: str,
) -> dict[str, str]:
    row = {
        "Name": name,
        "Full Name": name,
        "Community": COMMUNITY,
        "Domain": domain,
        "Domain Type": domain_type,
        "Asset Type": asset_type,
        "Status": "Candidate",
        RELATION_HEADER: relation,
    }
    row.update(shared)
    return row


def _element_name(dataset: str, column: str) -> str:
    return f"{dataset}.{column}"


def _role_note(owner: str, steward: str, source: str, criticality: str) -> str:
    return (
        f"Data owner role: {owner}. Data steward role: {steward}. "
        f"Source system: {source}. Criticality: {criticality}. "
        "Roles are not Collibra user accounts."
    )


def _number(value: float) -> str:
    if value == int(value):
        return f"{value:.1f}"
    return str(value)
