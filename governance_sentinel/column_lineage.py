"""Column lineage from the booking extract to the exposure aggregate.

The booking extract is logical. This prototype does not read a second file
for it. Staging is the CSV the rules run on. The aggregate sums exposure.

Transformation types used here:

- ``direct``: the output column is the input column, unchanged.
- ``aggregation``: the output is the sum of the input.
- ``derivation``: the output is computed from a different input column.
  ``age_band`` is the only derived column. It is the label of ``age_category``.
- ``filter``: rows are dropped before the output is computed. Null exposure
  amounts are excluded before the sum.

OpenLineage maps ``direct`` to transformation type ``DIRECT`` and the other
three to ``INDIRECT``, with the word above kept in ``subtype`` and
``description``. The facet follows ColumnLineageDatasetFacet and
SchemaDatasetFacet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from governance_sentinel.catalog import DATASET_COLUMNS, GlossaryTerm

PRODUCER = "https://github.com/delens/Governance-Sentinel"
NAMESPACE = "governance-sentinel"
COLUMN_LINEAGE_SCHEMA_URL = (
    "https://openlineage.io/spec/facets/1-0-1/ColumnLineageDatasetFacet.json"
)
SCHEMA_FACET_URL = "https://openlineage.io/spec/facets/1-0-1/SchemaDatasetFacet.json"

TRANSFORMATION_TYPES: tuple[str, ...] = ("direct", "aggregation", "derivation", "filter")

# OpenLineage transformation type, then subtype. The subtype keeps our word.
_OPENLINEAGE_TYPE: dict[str, tuple[str, str]] = {
    "direct": ("DIRECT", "IDENTITY"),
    "aggregation": ("INDIRECT", "AGGREGATION"),
    "derivation": ("INDIRECT", "TRANSFORMATION"),
    "filter": ("INDIRECT", "FILTER"),
}


def native_column_type(column: str) -> str:
    """Schema type name for a known column. An unknown column is reported as string."""
    return _COLUMN_TYPES.get(column, "string")


_COLUMN_TYPES: dict[str, str] = {
    "record_id": "string",
    "transaction_id": "string",
    "legal_entity_id": "string",
    "legal_entity_name": "string",
    "source_system": "string",
    "counterparty_id": "string",
    "counterparty_name": "string",
    "country": "string",
    "sector": "string",
    "product_type": "string",
    "currency": "string",
    "exposure_amount": "double",
    "internal_rating": "string",
    "reporting_date": "date",
    "availability_date": "string",
    "age_category": "integer",
    "age_band": "string",
    "loan_approved": "integer",
}

_COLUMN_DESCRIPTIONS: dict[str, str] = {
    "record_id": "Surrogate key assigned on the extract. The business key is transaction_id.",
    "transaction_id": "Identifier of one risk transaction in the booking feed.",
    "legal_entity_id": "Group legal entity the exposure is booked on.",
    "legal_entity_name": "Name of the group legal entity. Fictional in this demo.",
    "source_system": "Booking application code carried on the extract.",
    "counterparty_id": "Counterparty identifier. Checked against the counterparty master.",
    "counterparty_name": "Counterparty name on the reference master.",
    "country": "Country on the counterparty master.",
    "sector": "Sector on the counterparty master.",
    "product_type": "Product family. The demo list is LOAN, DERIVATIVE, SECURITY, GUARANTEE.",
    "currency": "Booking currency. The demo list is EUR, USD, GBP, CHF, and JPY.",
    "exposure_amount": "Gross exposure in the booking currency, before netting or CRM.",
    "internal_rating": "Internal rating grade. NR is a grade, not a blank.",
    "reporting_date": "As-of date of the risk snapshot.",
    "availability_date": "Date the record was available to risk reporting. Stored as text.",
    "age_category": "Synthetic group for the fairness illustration. 1 or 2.",
    "age_band": "Label of age_category. 1 is 40_and_over and 2 is under_40.",
    "loan_approved": "Synthetic approval flag used only by the fairness illustration.",
}

_LAYER: dict[str, int] = {
    "core_banking.transactions": 0,
    "staging.risk_transactions": 1,
    "reference.counterparties": 1,
    "risk_mart.exposure_by_entity": 2,
}


@dataclass(frozen=True)
class ColumnEdge:
    """One input column contributing to one output column."""

    source_dataset: str
    source_column: str
    target_dataset: str
    target_column: str
    transformation: str
    description: str


@dataclass(frozen=True)
class ColumnRef:
    """A physical column named by dataset and column."""

    dataset: str
    column: str


@dataclass(frozen=True)
class GlossaryTrace:
    """Physical columns reached from one glossary term, source through aggregate."""

    term_id: str
    anchor: ColumnRef
    columns: tuple[ColumnRef, ...]


def _direct(source: str, target: str, column: str, description: str) -> ColumnEdge:
    return ColumnEdge(source, column, target, column, "direct", description)


def _build_edges() -> tuple[ColumnEdge, ...]:
    source = "core_banking.transactions"
    staging = "staging.risk_transactions"
    aggregate = "risk_mart.exposure_by_entity"
    copied = tuple(
        _direct(
            source,
            staging,
            column,
            "Direct copy from the booking extract into staging.",
        )
        for column in DATASET_COLUMNS[source]
    )
    derived = ColumnEdge(
        source_dataset=source,
        source_column="age_category",
        target_dataset=staging,
        target_column="age_band",
        transformation="derivation",
        description=(
            "age_band is the label of age_category. 1 is 40_and_over and 2 is under_40. "
            "The label is produced at staging."
        ),
    )
    grouped = tuple(
        _direct(
            staging,
            aggregate,
            column,
            "Direct copy of a group key into the exposure aggregate.",
        )
        for column in ("legal_entity_id", "currency", "reporting_date")
    )
    aggregated = ColumnEdge(
        source_dataset=staging,
        source_column="exposure_amount",
        target_dataset=aggregate,
        target_column="exposure_amount",
        transformation="aggregation",
        description=("Sum of exposure_amount by legal entity, currency, and reporting date."),
    )
    filtered = ColumnEdge(
        source_dataset=staging,
        source_column="exposure_amount",
        target_dataset=aggregate,
        target_column="exposure_amount",
        transformation="filter",
        description="Rows with a null exposure_amount are excluded before the sum.",
    )
    edges = copied + (derived,) + grouped + (aggregated, filtered)
    unknown = sorted({edge.transformation for edge in edges} - set(TRANSFORMATION_TYPES))
    if unknown:
        raise ValueError(f"Unknown column transformations: {unknown}.")
    return edges


COLUMN_EDGES: tuple[ColumnEdge, ...] = _build_edges()


def excerpt_edges() -> tuple[ColumnEdge, ...]:
    """The four transformation types on the exposure path and the age-band label."""
    wanted = {
        (
            "core_banking.transactions",
            "exposure_amount",
            "staging.risk_transactions",
            "exposure_amount",
            "direct",
        ),
        (
            "core_banking.transactions",
            "age_category",
            "staging.risk_transactions",
            "age_band",
            "derivation",
        ),
        (
            "staging.risk_transactions",
            "exposure_amount",
            "risk_mart.exposure_by_entity",
            "exposure_amount",
            "aggregation",
        ),
        (
            "staging.risk_transactions",
            "exposure_amount",
            "risk_mart.exposure_by_entity",
            "exposure_amount",
            "filter",
        ),
    }
    selected = tuple(
        edge
        for edge in COLUMN_EDGES
        if (
            edge.source_dataset,
            edge.source_column,
            edge.target_dataset,
            edge.target_column,
            edge.transformation,
        )
        in wanted
    )
    if len(selected) != len(wanted):
        raise ValueError("The column-lineage excerpt is missing an edge.")
    return selected


def column_lineage_mermaid(edges: Sequence[ColumnEdge] | None = None) -> str:
    """Mermaid flowchart. Labels are ``dataset.column``. The arrow is the type."""
    chosen = COLUMN_EDGES if edges is None else tuple(edges)
    lines = ["flowchart LR"]
    labels: dict[str, str] = {}
    for edge in chosen:
        for dataset, column in (
            (edge.source_dataset, edge.source_column),
            (edge.target_dataset, edge.target_column),
        ):
            labels[_node_id(dataset, column)] = f"{dataset}.{column}"
    for node_id, label in labels.items():
        lines.append(f'  {node_id}["{label}"]')
    for edge in chosen:
        source = _node_id(edge.source_dataset, edge.source_column)
        target = _node_id(edge.target_dataset, edge.target_column)
        lines.append(f'  {source} -->|"{edge.transformation}"| {target}')
    return "\n".join(lines)


def term_ids_for_edge(edge: ColumnEdge, terms: Sequence[GlossaryTerm]) -> tuple[str, ...]:
    """Glossary terms whose physical column is either end of the edge."""
    keys = {
        (edge.source_dataset, edge.source_column),
        (edge.target_dataset, edge.target_column),
    }
    return tuple(
        term.term_id for term in terms if (term.physical_dataset, term.physical_column) in keys
    )


def column_lineage_rows(terms: Sequence[GlossaryTerm] = ()) -> list[dict[str, object]]:
    """Flat records for the JSON and CSV exports."""
    rows: list[dict[str, object]] = []
    for edge in COLUMN_EDGES:
        linked = term_ids_for_edge(edge, terms)
        rows.append(
            {
                "source_dataset": edge.source_dataset,
                "source_column": edge.source_column,
                "target_dataset": edge.target_dataset,
                "target_column": edge.target_column,
                "transformation": edge.transformation,
                "description": edge.description,
                "glossary_term_ids": list(linked),
            }
        )
    return rows


def trace_glossary_term(
    term: GlossaryTerm,
    edges: Sequence[ColumnEdge] = COLUMN_EDGES,
) -> GlossaryTrace:
    """Walk column edges upstream and downstream from the term's physical column."""
    anchor = ColumnRef(term.physical_dataset, term.physical_column)
    found: set[tuple[str, str]] = {(anchor.dataset, anchor.column)}
    stack = [anchor]
    while stack:
        current = stack.pop()
        for edge in edges:
            if (edge.target_dataset, edge.target_column) == (current.dataset, current.column):
                key = (edge.source_dataset, edge.source_column)
                if key not in found:
                    found.add(key)
                    stack.append(ColumnRef(edge.source_dataset, edge.source_column))
            if (edge.source_dataset, edge.source_column) == (current.dataset, current.column):
                key = (edge.target_dataset, edge.target_column)
                if key not in found:
                    found.add(key)
                    stack.append(ColumnRef(edge.target_dataset, edge.target_column))
    ordered = tuple(
        ColumnRef(dataset, column)
        for dataset, column in sorted(found, key=lambda item: (_LAYER.get(item[0], 9), item[1]))
    )
    return GlossaryTrace(term_id=term.term_id, anchor=anchor, columns=ordered)


def schema_facet(dataset: str) -> dict[str, object]:
    """OpenLineage SchemaDatasetFacet for one dataset in this flow."""
    if dataset not in DATASET_COLUMNS:
        raise ValueError(f"No schema is declared for dataset {dataset!r}.")
    fields = []
    for name in DATASET_COLUMNS[dataset]:
        if name not in _COLUMN_TYPES:
            raise ValueError(f"No type is declared for column {name!r}.")
        fields.append(
            {
                "name": name,
                "type": _COLUMN_TYPES[name],
                "description": _COLUMN_DESCRIPTIONS[name],
            }
        )
    return {
        "_producer": PRODUCER,
        "_schemaURL": SCHEMA_FACET_URL,
        "fields": fields,
    }


def column_lineage_facet(target_dataset: str) -> dict[str, object]:
    """OpenLineage ColumnLineageDatasetFacet for one output dataset."""
    relevant = [edge for edge in COLUMN_EDGES if edge.target_dataset == target_dataset]
    grouped: dict[str, dict[tuple[str, str], list[ColumnEdge]]] = {}
    for edge in relevant:
        inputs = grouped.setdefault(edge.target_column, {})
        inputs.setdefault((edge.source_dataset, edge.source_column), []).append(edge)
    fields: dict[str, object] = {}
    for column, inputs in grouped.items():
        input_fields: list[dict[str, object]] = []
        descriptions: list[str] = []
        types: list[str] = []
        for (source_dataset, source_column), edge_list in inputs.items():
            transformations = []
            for edge in edge_list:
                openlineage_type, subtype = _OPENLINEAGE_TYPE[edge.transformation]
                transformations.append(
                    {
                        "type": openlineage_type,
                        "subtype": subtype,
                        "description": f"{edge.transformation}: {edge.description}",
                        "masking": False,
                    }
                )
                descriptions.append(edge.description)
                types.append(openlineage_type)
            input_fields.append(
                {
                    "namespace": NAMESPACE,
                    "name": source_dataset,
                    "field": source_column,
                    "transformations": transformations,
                }
            )
        transformation_type = (
            "DIRECT" if types and all(item == "DIRECT" for item in types) else "INDIRECT"
        )
        fields[column] = {
            "inputFields": input_fields,
            "transformationDescription": "; ".join(descriptions),
            "transformationType": transformation_type,
        }
    return {
        "_producer": PRODUCER,
        "_schemaURL": COLUMN_LINEAGE_SCHEMA_URL,
        "fields": fields,
    }


def _node_id(dataset: str, column: str) -> str:
    prefix = {
        "core_banking.transactions": "src",
        "staging.risk_transactions": "stg",
        "risk_mart.exposure_by_entity": "agg",
        "reference.counterparties": "ref",
    }.get(dataset)
    if prefix is None:
        raise ValueError(f"No Mermaid prefix for dataset {dataset!r}.")
    return f"{prefix}_{column}"
