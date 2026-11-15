"""Business and technical lineage for the risk exposure flow.

The flow is source -> staging -> risk aggregate:

- ``core_banking.transactions`` is the booking origin. This prototype does not
  measure it separately, so its data-quality status is ``NOT_MEASURED``.
- ``staging.risk_transactions`` is the CSV the rules run on.
- ``risk_mart.exposure_by_entity`` sums ``exposure_amount`` by legal entity,
  currency, and reporting date. Its status is the worse of the staging result
  and the reconciliation against the reported total.

The reconciliation compares that sum with a reported total. The reported
total copies the sum and then adds a fixed 250,000 on LE-UK / EUR. That break
is injected so the control has something to catch. Footnote 17 of BCBS 239
defines reconciliation as comparing items and explaining the difference.

What the control supports, and what it does not:

- Principle 3, paragraph 36(c): risk data reconciled with the bank's sources.
- Principle 7, paragraph 53(a): a defined tie from a reported total back to
  risk data. This is not a board risk report, and paragraphs 52 and 54-56
  are not implemented.
- Principle 6, paragraph 49(a): one aggregate grain that can be cut by legal
  entity, currency, and reporting date. Paragraph 50 (an on-demand subset
  for a supervisory query) is not implemented.
- Principle 2, footnote 16, is about automated reconciliation where more than
  one data model is in use. The check here is source transactions against one
  aggregate, which is the Principle 3 / Principle 7 case, not that footnote.

OpenLineage output is a minimal COMPLETE event with the dataset facets this
run can fill. It is not a Marquez client and it does not talk to a server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import pandas as pd

from governance_sentinel.models import RuleResult


@dataclass(frozen=True)
class ReconciliationBreak:
    """The one reported-total break this demo injects."""

    legal_entity_id: str
    currency: str
    delta: float


RECONCILIATION_BREAK = ReconciliationBreak("LE-UK", "EUR", 250_000.0)
TOLERANCE_PCT = 0.1
AGGREGATE_KEYS: tuple[str, ...] = ("legal_entity_id", "currency", "reporting_date")

NOT_MEASURED = "NOT_MEASURED"


@dataclass(frozen=True)
class FlowNode:
    """One dataset in the exposure flow."""

    node_id: str
    layer: str
    dataset: str
    description: str


@dataclass(frozen=True)
class ColumnFlow:
    """How one column moves from one dataset to the next."""

    column: str
    source: str
    target: str
    transform: str


@dataclass(frozen=True)
class ReconciliationSlice:
    """One legal-entity / currency / reporting-date tie."""

    legal_entity_id: str
    currency: str
    reporting_date: str
    transaction_total: float
    reported_total: float
    difference: float
    tolerance: float
    status: str


@dataclass(frozen=True)
class ReconciliationResult:
    """Transaction-level totals against the reported aggregate."""

    status: str
    tolerance_pct: float
    injected_break: bool
    slices: tuple[ReconciliationSlice, ...]

    @property
    def failed_slices(self) -> tuple[ReconciliationSlice, ...]:
        return tuple(item for item in self.slices if item.status == "FAIL")


@dataclass(frozen=True)
class LineageReport:
    """Statuses, the Mermaid picture, and the reconciliation."""

    nodes: tuple[FlowNode, ...]
    edges: tuple[tuple[str, str], ...]
    column_flows: tuple[ColumnFlow, ...]
    statuses: dict[str, str]
    mermaid: str
    reconciliation: ReconciliationResult


FLOW_NODES: tuple[FlowNode, ...] = (
    FlowNode(
        "src_transactions",
        "source",
        "core_banking.transactions",
        "Booking-system origin. Not measured as its own extract in this run.",
    ),
    FlowNode(
        "stg_transactions",
        "staging",
        "staging.risk_transactions",
        "Staged risk transactions. The YAML rules run on this extract.",
    ),
    FlowNode(
        "agg_exposure",
        "aggregate",
        "risk_mart.exposure_by_entity",
        "Exposure summed by legal entity, currency, and reporting date.",
    ),
)

FLOW_EDGES: tuple[tuple[str, str], ...] = (
    ("src_transactions", "stg_transactions"),
    ("stg_transactions", "agg_exposure"),
)

# Staging keeps the transaction columns. The aggregate keeps the grain and the sum.
_STAGING_COLUMNS: tuple[str, ...] = (
    "record_id",
    "transaction_id",
    "legal_entity_id",
    "legal_entity_name",
    "source_system",
    "counterparty_id",
    "product_type",
    "currency",
    "exposure_amount",
    "internal_rating",
    "reporting_date",
    "availability_date",
    "age_category",
    "age_band",
    "loan_approved",
)

COLUMN_FLOWS: tuple[ColumnFlow, ...] = tuple(
    ColumnFlow(column, "src_transactions", "stg_transactions", "copy")
    for column in _STAGING_COLUMNS
) + (
    ColumnFlow("legal_entity_id", "stg_transactions", "agg_exposure", "group key"),
    ColumnFlow("currency", "stg_transactions", "agg_exposure", "group key"),
    ColumnFlow("reporting_date", "stg_transactions", "agg_exposure", "group key"),
    ColumnFlow("exposure_amount", "stg_transactions", "agg_exposure", "sum"),
)


def aggregate_exposures(frame: pd.DataFrame) -> pd.DataFrame:
    """Sum non-missing exposure amounts. The caller's frame is not modified."""
    amounts = pd.to_numeric(frame["exposure_amount"], errors="coerce")
    usable = frame.loc[amounts.notna(), list(AGGREGATE_KEYS)].copy()
    usable["exposure_amount"] = amounts.loc[amounts.notna()].to_numpy()
    grouped = (
        usable.groupby(list(AGGREGATE_KEYS), dropna=False)["exposure_amount"].sum().reset_index()
    )
    grouped["exposure_amount"] = grouped["exposure_amount"].round(2)
    return grouped.sort_values(list(AGGREGATE_KEYS)).reset_index(drop=True)


def reported_aggregate(
    computed: pd.DataFrame,
    *,
    inject_break: bool = True,
) -> pd.DataFrame:
    """Copy the computed aggregate. Optionally add the documented LE-UK EUR break."""
    reported = computed.copy()
    if not inject_break:
        return reported
    entity = RECONCILIATION_BREAK.legal_entity_id
    currency = RECONCILIATION_BREAK.currency
    delta = RECONCILIATION_BREAK.delta
    mask = (reported["legal_entity_id"] == entity) & (reported["currency"] == currency)
    if not bool(mask.any()):
        raise ValueError(f"Cannot inject the reconciliation break: no {entity} {currency} slice.")
    reported.loc[mask, "exposure_amount"] = reported.loc[mask, "exposure_amount"] + delta
    return reported


def reconcile(
    transaction_totals: pd.DataFrame,
    reported_totals: pd.DataFrame,
    *,
    tolerance_pct: float = TOLERANCE_PCT,
    injected_break: bool = False,
) -> ReconciliationResult:
    """Compare the two totals. A slice fails when the gap exceeds the tolerance.

    The tolerance is ``tolerance_pct`` percent of the absolute transaction
    total. A transaction total of zero fails when the reported total is not
    zero. No slices at all is a FAIL: there is nothing to tie.
    """
    keys = list(AGGREGATE_KEYS)
    merged = transaction_totals.merge(
        reported_totals,
        on=keys,
        how="outer",
        suffixes=("_transaction", "_reported"),
    )
    slices: list[ReconciliationSlice] = []
    for row in merged.itertuples(index=False):
        transaction_total = _blank_as_zero(getattr(row, "exposure_amount_transaction"))
        reported_total = _blank_as_zero(getattr(row, "exposure_amount_reported"))
        difference = reported_total - transaction_total
        tolerance = abs(transaction_total) * tolerance_pct / 100.0
        if transaction_total == 0.0:
            status = "PASS" if difference == 0.0 else "FAIL"
        else:
            status = "PASS" if abs(difference) <= tolerance + 1e-6 else "FAIL"
        slices.append(
            ReconciliationSlice(
                legal_entity_id=str(row.legal_entity_id),
                currency=str(row.currency),
                reporting_date=str(row.reporting_date)[:10],
                transaction_total=transaction_total,
                reported_total=reported_total,
                difference=difference,
                tolerance=tolerance,
                status=status,
            )
        )
    status = "FAIL" if not slices or any(item.status == "FAIL" for item in slices) else "PASS"
    return ReconciliationResult(
        status=status,
        tolerance_pct=tolerance_pct,
        injected_break=injected_break,
        slices=tuple(slices),
    )


def node_statuses(rule_results: list[RuleResult], reconciliation_status: str) -> dict[str, str]:
    """Measure staging, leave the source unmeasured, and push status downstream.

    The aggregate FAILs when staging FAILs or the reconciliation FAILs.
    ``NOT_MEASURED`` on the source does not, by itself, fail staging.
    """
    if not rule_results or any(item.status == "FAIL" for item in rule_results):
        staging = "FAIL"
    else:
        staging = "PASS"
    aggregate = "FAIL" if staging == "FAIL" or reconciliation_status == "FAIL" else "PASS"
    return {
        "src_transactions": NOT_MEASURED,
        "stg_transactions": staging,
        "agg_exposure": aggregate,
    }


def lineage_mermaid(statuses: dict[str, str]) -> str:
    """Mermaid flowchart. Labels come from the flow metadata, not from a hand edit."""
    lines = ["flowchart LR"]
    for node in FLOW_NODES:
        status = statuses.get(node.node_id, NOT_MEASURED)
        label = f"{node.dataset}\\n{status}"
        lines.append(f'  {node.node_id}["{label}"]')
    for source, target in FLOW_EDGES:
        lines.append(f"  {source} --> {target}")
    return "\n".join(lines)


def lineage_graph(statuses: dict[str, str]) -> nx.DiGraph:
    """Directed graph with dataset name and data-quality status on each node."""
    graph: nx.DiGraph = nx.DiGraph()
    for node in FLOW_NODES:
        graph.add_node(
            node.node_id,
            layer=node.layer,
            dataset=node.dataset,
            status=statuses.get(node.node_id, NOT_MEASURED),
            description=node.description,
        )
    graph.add_edges_from(FLOW_EDGES)
    return graph


def build_lineage(
    frame: pd.DataFrame,
    rule_results: list[RuleResult],
    *,
    inject_break: bool = True,
) -> LineageReport:
    """Aggregate, reconcile, propagate statuses, and draw the Mermaid picture."""
    computed = aggregate_exposures(frame)
    reported = reported_aggregate(computed, inject_break=inject_break)
    reconciliation = reconcile(computed, reported, injected_break=inject_break)
    statuses = node_statuses(rule_results, reconciliation.status)
    return LineageReport(
        nodes=FLOW_NODES,
        edges=FLOW_EDGES,
        column_flows=COLUMN_FLOWS,
        statuses=statuses,
        mermaid=lineage_mermaid(statuses),
        reconciliation=reconciliation,
    )


def openlineage_event(
    run_id: str,
    frame: pd.DataFrame,
    rule_results: list[RuleResult],
    *,
    event_time: datetime | None = None,
) -> dict[str, object]:
    """One COMPLETE event. Facets follow the public OpenLineage dataset shapes.

    ``dataQualityMetrics`` carries null and row counts.
    ``dataQualityAssertions`` carries one assertion per YAML rule.
    Schema URLs point at the published facet names. Fields this run does not
    know are omitted.
    """
    moment = event_time or datetime.now(timezone.utc)
    stamp = moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    stamp = stamp.replace("+00:00", "Z")
    producer = "https://github.com/delens/Governance-Sentinel"
    metrics_schema = "https://openlineage.io/spec/facets/1-0-0/DataQualityMetricsDatasetFacet.json"
    assertions_schema = (
        "https://openlineage.io/spec/facets/1-0-0/DataQualityAssertionsDatasetFacet.json"
    )
    return {
        "eventType": "COMPLETE",
        "eventTime": stamp,
        "run": {"runId": run_id},
        "job": {"namespace": "governance-sentinel", "name": "risk_exposure_audit"},
        "inputs": [
            {"namespace": "governance-sentinel", "name": "core_banking.transactions"},
            {"namespace": "governance-sentinel", "name": "reference.counterparties"},
        ],
        "outputs": [
            {
                "namespace": "governance-sentinel",
                "name": "staging.risk_transactions",
                "facets": {
                    "dataQualityMetrics": {
                        "_producer": producer,
                        "_schemaURL": metrics_schema,
                        "columnMetrics": _column_metrics(frame),
                    },
                    "dataQualityAssertions": {
                        "_producer": producer,
                        "_schemaURL": assertions_schema,
                        "assertions": [
                            {
                                "assertion": item.rule_id,
                                "success": item.status == "PASS",
                                "column": item.column,
                            }
                            for item in rule_results
                        ],
                    },
                },
            },
            {
                "namespace": "governance-sentinel",
                "name": "risk_mart.exposure_by_entity",
                "outputFacets": {},
            },
        ],
    }


def write_lineage_artifacts(
    report: LineageReport,
    event: dict[str, object],
    directory: Path,
) -> None:
    """Write the Mermaid picture, the OpenLineage event, and the tie-out."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "lineage.mmd").write_text(report.mermaid + "\n", encoding="utf-8")
    (directory / "openlineage.json").write_text(
        json.dumps(event, indent=2) + "\n",
        encoding="utf-8",
    )
    payload = {
        "nodes": [
            {
                "node_id": node.node_id,
                "layer": node.layer,
                "dataset": node.dataset,
                "status": report.statuses.get(node.node_id, NOT_MEASURED),
                "description": node.description,
            }
            for node in report.nodes
        ],
        "edges": [{"source": source, "target": target} for source, target in report.edges],
        "column_flows": [
            {
                "column": item.column,
                "source": item.source,
                "target": item.target,
                "transform": item.transform,
            }
            for item in report.column_flows
        ],
        "reconciliation": {
            "status": report.reconciliation.status,
            "tolerance_pct": report.reconciliation.tolerance_pct,
            "injected_break": report.reconciliation.injected_break,
            "failed_slices": [
                {
                    "legal_entity_id": item.legal_entity_id,
                    "currency": item.currency,
                    "reporting_date": item.reporting_date,
                    "transaction_total": item.transaction_total,
                    "reported_total": item.reported_total,
                    "difference": item.difference,
                    "status": item.status,
                }
                for item in report.reconciliation.failed_slices
            ],
        },
    }
    (directory / "lineage.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    recon_rows = [
        {
            "legal_entity_id": item.legal_entity_id,
            "currency": item.currency,
            "reporting_date": item.reporting_date,
            "transaction_total": item.transaction_total,
            "reported_total": item.reported_total,
            "difference": item.difference,
            "tolerance": item.tolerance,
            "status": item.status,
        }
        for item in report.reconciliation.slices
    ]
    pd.DataFrame(recon_rows).to_csv(directory / "reconciliation.csv", index=False)


def _column_metrics(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for column in ("transaction_id", "exposure_amount", "currency", "counterparty_id"):
        if column not in frame.columns:
            continue
        series = frame[column]
        populated = series.dropna()
        entry: dict[str, float] = {
            "nullCount": float(int(series.isna().sum())),
            "count": float(int(populated.shape[0])),
            "distinctCount": float(int(populated.nunique(dropna=True))),
        }
        if column == "exposure_amount":
            numeric = pd.to_numeric(populated, errors="coerce").dropna()
            if not numeric.empty:
                entry["sum"] = float(numeric.sum())
                entry["min"] = float(numeric.min())
                entry["max"] = float(numeric.max())
        metrics[column] = entry
    return metrics


def _blank_as_zero(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, float) and pd.isna(value):
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        try:
            if pd.isna(value):
                return 0.0
        except TypeError:
            pass
        return float(str(value))
    if isinstance(value, str) and value.strip() in {"", "nan", "None", "NaT"}:
        return 0.0
    return float(value)
